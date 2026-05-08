from __future__ import annotations

from copy import deepcopy
from time import monotonic
from typing import Any

from sqlalchemy.orm import Session

from app.ai.extraction_service import ExtractionService
from app.ai.types import HUMAN_CONFIRMATION_TOOL_NAMES, ExtractionInput, ExtractionProviderResult
from app.core.config import Settings, get_settings
from app.schemas.conversation import MessageContentItem


class AgentRuntime:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        extraction_service: ExtractionService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.extraction_service = extraction_service or ExtractionService(db, self.settings)
        self.provider = self.extraction_service.provider

    def run(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message_id: str,
        content: list[MessageContentItem],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        started_at = monotonic()
        trace: list[dict[str, Any]] = [
            {
                "event": "agent_started",
                "max_model_turns": self.settings.agent_max_model_turns,
                "max_tool_rounds": self.settings.agent_max_tool_rounds,
            }
        ]
        pending_actions = []
        committed_records = []
        # Each entry: {"assistant_output": raw_output_dict, "tool_results": list[dict]}
        prior_turns: list[dict[str, Any]] = []
        tool_rounds = 0
        total_tool_calls = 0
        provider_result: ExtractionProviderResult | None = None
        initial_context = self._initial_loop_context(context)

        for model_turn in range(1, max(1, self.settings.agent_max_model_turns) + 1):
            provider_result = self.provider.extract(
                ExtractionInput(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    content=content,
                    context=initial_context,
                    prior_turns=prior_turns,
                )
            )
            trace.append(
                {
                    "event": "model_decision",
                    "model_turn": model_turn,
                    "decision": self._decision_label(provider_result),
                    "tool_call_count": len(provider_result.tool_calls),
                    "tool_names": [tool_call.name for tool_call in provider_result.tool_calls],
                    "intent": provider_result.intent,
                }
            )

            if not provider_result.tool_calls:
                event = (
                    "clarifying_question"
                    if self._is_clarifying_question(provider_result)
                    else "final_answer"
                )
                trace.append({"event": event, "model_turn": model_turn})
                return self._response(
                    provider_result=provider_result,
                    pending_actions=pending_actions,
                    committed_records=committed_records,
                    prior_turns=prior_turns,
                    trace=trace,
                )

            # Check tool-level limits before executing (max_model_turns is handled by the for loop)
            limit_reason = self._loop_limit_reason(
                tool_rounds=tool_rounds,
                total_tool_calls=total_tool_calls,
                started_at=started_at,
            )
            if limit_reason:
                trace.append(
                    {
                        "event": "loop_limit_reached",
                        "model_turn": model_turn,
                        "tool_rounds": tool_rounds,
                        "reason": limit_reason,
                    }
                )
                return self._response(
                    provider_result=self._limit_result(provider_result),
                    pending_actions=pending_actions,
                    committed_records=committed_records,
                    prior_turns=prior_turns,
                    trace=trace,
                )

            remaining_total_calls = max(
                0,
                self.settings.agent_max_total_tool_calls - total_tool_calls,
            )
            per_round_limit = max(1, self.settings.agent_max_tool_calls_per_round)
            executable_count = min(per_round_limit, remaining_total_calls)
            if executable_count <= 0:
                trace.append(
                    {
                        "event": "loop_limit_reached",
                        "model_turn": model_turn,
                        "tool_rounds": tool_rounds,
                        "reason": "max_total_tool_calls",
                    }
                )
                return self._response(
                    provider_result=self._limit_result(provider_result),
                    pending_actions=pending_actions,
                    committed_records=committed_records,
                    prior_turns=prior_turns,
                    trace=trace,
                )

            tool_calls = provider_result.tool_calls[:executable_count]
            dropped_count = len(provider_result.tool_calls) - len(tool_calls)
            if dropped_count > 0:
                trace.append(
                    {
                        "event": "loop_limit_reached",
                        "dropped_count": dropped_count,
                        "reason": "tool_call_limit",
                    }
                )
                provider_result = self._with_tool_calls(provider_result, tool_calls)

            tool_rounds += 1
            total_tool_calls += len(tool_calls)
            for tool_call in tool_calls:
                trace.append(
                    {
                        "event": "tool_call_started",
                        "tool_round": tool_rounds,
                        "tool_name": tool_call.name,
                    }
                )

            prior_tool_results = self._all_tool_results(prior_turns)
            execution = self.extraction_service.execute_provider_result(
                provider_result=provider_result,
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                content=content,
                context=context,
                prior_tool_results=prior_tool_results,
            )
            pending_actions.extend(execution["pending_actions"])
            committed_records.extend(execution["committed_records"])
            new_tool_results = execution["tool_results"]
            self._prune_active_pending_actions(initial_context, new_tool_results)

            # Accumulate this turn for multi-turn conversation history
            prior_turns.append(
                {
                    "assistant_output": provider_result.raw_output,
                    "tool_results": new_tool_results,
                }
            )

            for result in new_tool_results:
                trace.append(
                    {
                        "event": "tool_result",
                        "tool_round": tool_rounds,
                        "tool_name": result.get("tool_name"),
                        "status": result.get("status"),
                        "reason": result.get("reason"),
                    }
                )

            if self._requires_human_confirmation(new_tool_results):
                trace.append(
                    {
                        "event": "human_confirmation_required",
                        "tool_round": tool_rounds,
                        "pending_action_ids": [
                            result.get("pending_action_id")
                            for result in new_tool_results
                            if result.get("status")
                            in {"pending_confirmation", "needs_clarification"}
                        ],
                    }
                )
                return self._response(
                    provider_result=provider_result,
                    pending_actions=pending_actions,
                    committed_records=committed_records,
                    prior_turns=prior_turns,
                    trace=trace,
                )

            # Tools executed; if this was the last model turn we cannot call LLM again
            if model_turn >= max(1, self.settings.agent_max_model_turns):
                trace.append({"event": "loop_limit_reached", "reason": "max_model_turns"})
                return self._response(
                    provider_result=self._limit_result(provider_result),
                    pending_actions=pending_actions,
                    committed_records=committed_records,
                    prior_turns=prior_turns,
                    trace=trace,
                )

        # Defensive fallback — unreachable for max_model_turns >= 1
        trace.append({"event": "loop_limit_reached", "reason": "max_model_turns"})
        return self._response(
            provider_result=self._limit_result(provider_result),
            pending_actions=pending_actions,
            committed_records=committed_records,
            prior_turns=prior_turns,
            trace=trace,
        )

    def _response(
        self,
        *,
        provider_result: ExtractionProviderResult,
        pending_actions: list,
        committed_records: list[dict[str, Any]],
        prior_turns: list[dict[str, Any]],
        trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        tool_results = self._all_tool_results(prior_turns)
        response = self.extraction_service._result_response(
            provider_result,
            pending_actions,
            committed_records,
            tool_results,
        )
        if self._should_append_final_text(
            provider_result=provider_result,
            pending_actions=pending_actions,
            committed_records=committed_records,
        ):
            final_text = provider_result.assistant_text.strip()
            response["assistant_text"] = f'{response["assistant_text"]} {final_text}'
            response["assistant_content"].append({"type": "text", "text": final_text})
        response["agent_trace"] = trace
        return response

    def _should_append_final_text(
        self,
        *,
        provider_result: ExtractionProviderResult,
        pending_actions: list,
        committed_records: list[dict[str, Any]],
    ) -> bool:
        if provider_result.tool_calls or pending_actions or not committed_records:
            return False
        final_text = provider_result.assistant_text.strip()
        if not final_text:
            return False
        committed_messages = {str(record.get("message") or "") for record in committed_records}
        return final_text not in committed_messages

    def _initial_loop_context(self, context: dict[str, Any]) -> dict[str, Any]:
        loop_context = deepcopy(context)
        loop_context["agent_loop"] = {
            "limits": {
                "max_model_turns": self.settings.agent_max_model_turns,
                "max_tool_rounds": self.settings.agent_max_tool_rounds,
                "max_tool_calls_per_round": self.settings.agent_max_tool_calls_per_round,
                "max_total_tool_calls": self.settings.agent_max_total_tool_calls,
            },
        }
        return loop_context

    def _all_tool_results(self, prior_turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for turn in prior_turns:
            results.extend(turn.get("tool_results") or [])
        return results

    def _loop_limit_reason(
        self,
        *,
        tool_rounds: int,
        total_tool_calls: int,
        started_at: float,
    ) -> str | None:
        # max_model_turns is enforced by the for-loop range; only tool-level limits here
        if tool_rounds >= max(0, self.settings.agent_max_tool_rounds):
            return "max_tool_rounds"
        if total_tool_calls >= max(1, self.settings.agent_max_total_tool_calls):
            return "max_total_tool_calls"
        if monotonic() - started_at > max(1, self.settings.agent_loop_timeout_seconds):
            return "timeout"
        return None

    def _requires_human_confirmation(self, tool_results: list[dict[str, Any]]) -> bool:
        return any(
            result.get("status") in {"pending_confirmation", "needs_clarification"}
            and result.get("tool_name") in HUMAN_CONFIRMATION_TOOL_NAMES
            for result in tool_results
        )

    def _prune_active_pending_actions(
        self, context: dict[str, Any], tool_results: list[dict[str, Any]]
    ) -> None:
        active = context.get("active_pending_actions")
        if not isinstance(active, list) or not active:
            return
        processed_ids: set[str] = set()
        for result in tool_results:
            tool_name = result.get("tool_name", "")
            if tool_name == "commit_pending_action":
                pid = result.get("pending_action_id")
                if pid:
                    processed_ids.add(pid)
            elif tool_name == "commit_pending_actions":
                for item in result.get("committed") or []:
                    pid = item.get("pending_action_id")
                    if pid:
                        processed_ids.add(pid)
            elif tool_name == "discard_pending_actions":
                for item in result.get("discarded") or []:
                    pid = item.get("pending_action_id")
                    if pid:
                        processed_ids.add(pid)
        if processed_ids:
            context["active_pending_actions"] = [
                a for a in active
                if a.get("pending_action_id") not in processed_ids
            ]

    def _decision_label(self, provider_result: ExtractionProviderResult) -> str:
        if provider_result.tool_calls:
            return "tool_calls"
        if self._is_clarifying_question(provider_result):
            return "ask_clarifying_question"
        return "final_answer"

    def _is_clarifying_question(self, provider_result: ExtractionProviderResult) -> bool:
        warning_reasons = {
            str(warning.get("reason") or "")
            for warning in provider_result.warnings
            if isinstance(warning, dict)
        }
        if warning_reasons.intersection(
            {"needs_clarification", "missing_information", "clarifying_question"}
        ):
            return True
        if provider_result.intent != "fitness_record":
            return False
        return "?" in provider_result.assistant_text or "？" in provider_result.assistant_text

    def _with_tool_calls(
        self,
        provider_result: ExtractionProviderResult,
        tool_calls,
    ) -> ExtractionProviderResult:
        return ExtractionProviderResult(
            assistant_text=provider_result.assistant_text,
            intent=provider_result.intent,
            requires_review=provider_result.requires_review,
            confidence=provider_result.confidence,
            tool_calls=list(tool_calls),
            warnings=provider_result.warnings,
            dialogue_state_patch=provider_result.dialogue_state_patch,
            raw_output=provider_result.raw_output,
        )

    def _limit_result(
        self,
        provider_result: ExtractionProviderResult | None,
    ) -> ExtractionProviderResult:
        return ExtractionProviderResult(
            assistant_text=(
                "这次需要的步骤有点多，我先停在这里。"
                "你可以补充更具体的信息，或者稍后让我继续整理。"
            ),
            intent=provider_result.intent if provider_result else "answer_fitness_question",
            requires_review=False,
            confidence=provider_result.confidence if provider_result else None,
            warnings=[
                *(provider_result.warnings if provider_result else []),
                {"field": "agent_loop", "reason": "loop_limit_reached"},
            ],
            raw_output=provider_result.raw_output if provider_result else {},
        )
