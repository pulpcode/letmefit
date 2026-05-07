import json
import logging
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.ai.draft_normalizer import normalize_pending_action_draft
from app.ai.providers import ExtractionProvider, get_extraction_provider
from app.ai.types import (
    ExtractionInput,
    ExtractionProviderResult,
    ExtractionToolCall,
    GroundingSource,
)
from app.auth.security import new_id, utc_now
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.models import AgentExtraction, AgentPendingAction
from app.schemas.conversation import MessageContentItem
from app.schemas.pending_action import decimal_to_float
from app.services.body_metrics import BodyMetricService
from app.services.meals import MealService
from app.services.pending_action_lifecycle import (
    PENDING_CONFIRMATION,
    classify_pending_action_status,
    normalize_status_warnings,
    pending_action_expires_at,
)

logger = logging.getLogger(__name__)

SAVE_CLAIM_TERMS = (
    "已保存",
    "已自动保存",
    "已经保存",
    "已为你将",
    "已为你把",
    "已将",
    "已存为",
    "保存到正式记录",
    "已记录到",
    "已经记录到",
)


class ExtractionService:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        provider: ExtractionProvider | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.provider = provider or get_extraction_provider(self.settings)

    def process_message(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        content: list[MessageContentItem],
        context: dict | None = None,
    ) -> dict:
        provider_result = self.provider.extract(
            ExtractionInput(
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                content=content,
                context=context or {},
            )
        )
        execution = self.execute_provider_result(
            provider_result=provider_result,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            content=content,
            context=context or {},
        )
        return self._result_response(
            provider_result,
            execution["pending_actions"],
            execution["committed_records"],
            execution["tool_results"],
        )

    def execute_provider_result(
        self,
        *,
        provider_result: ExtractionProviderResult,
        user_id: str,
        conversation_id: str,
        message_id: str,
        content: list[MessageContentItem],
        context: dict | None = None,
        prior_tool_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        context = context or {}
        prior_tool_results = prior_tool_results or []
        tool_calls, tool_results = self._filter_tool_calls(
            provider_result.tool_calls,
            content=content,
            context=context,
            prior_tool_results=prior_tool_results,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        if not tool_calls:
            return {
                "pending_actions": [],
                "committed_records": [],
                "tool_results": tool_results,
            }

        extraction = self._create_extraction_if_needed(
            provider_result=provider_result,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            content=content,
            tool_calls=tool_calls,
        )

        pending_actions = []
        committed_records = []
        input_text = self._joined_text(content)
        for tool_call in tool_calls:
            if tool_call.is_read_only_tool:
                tool_results.append(
                    self._execute_read_only_tool(
                        tool_call=tool_call,
                        user_id=user_id,
                    )
                )
                continue

            if tool_call.is_pending_action_tool:
                result = self._execute_pending_action_tool(tool_call=tool_call, user_id=user_id)
                if result.get("pending_action") is not None:
                    pending_actions.append(result["pending_action"])
                if result.get("pending_actions") is not None:
                    pending_actions.extend(result["pending_actions"])
                if result.get("committed_record") is not None:
                    committed_records.append(result["committed_record"])
                if result.get("committed_records") is not None:
                    committed_records.extend(result["committed_records"])
                tool_results.append(result["tool_result"])
                continue

            if not extraction:
                continue
            action_spec = tool_call.to_action_spec()
            draft_payload = normalize_pending_action_draft(
                action_spec.action_type,
                action_spec.draft_payload,
                input_text=input_text,
                now=utc_now(),
            )
            confidence = self._action_confidence(action_spec, provider_result, draft_payload)
            warnings = self._record_action_warnings(tool_call, action_spec.warnings)
            status = classify_pending_action_status(
                action_spec.action_type,
                draft_payload,
                warnings=warnings,
            )
            action = self._create_pending_action(
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                extraction_id=extraction.id,
                confidence=confidence,
                action_type=action_spec.action_type,
                draft_payload=draft_payload,
                warnings=normalize_status_warnings(status, warnings),
                status=status,
            )
            pending_actions.append(action)
            tool_results.append(self._tool_result(tool_call, status, action=action))
        if extraction:
            extraction.requires_confirmation = bool(pending_actions)
        return {
            "pending_actions": pending_actions,
            "committed_records": committed_records,
            "tool_results": tool_results,
        }

    def _create_extraction_if_needed(
        self,
        *,
        provider_result: ExtractionProviderResult,
        user_id: str,
        conversation_id: str,
        message_id: str,
        content: list[MessageContentItem],
        tool_calls: list[ExtractionToolCall],
    ) -> AgentExtraction | None:
        if not any(tool_call.is_record_tool for tool_call in tool_calls):
            return None
        extraction = AgentExtraction(
            id=new_id("ext"),
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            input_types_json=self._input_types(content),
            intent=provider_result.intent,
            confidence=provider_result.confidence,
            requires_confirmation=False,
            raw_output_json=provider_result.raw_output,
            warnings_json=provider_result.warnings,
            status="succeeded",
            created_at=utc_now(),
        )
        self.db.add(extraction)
        self.db.flush()
        return extraction

    def _filter_tool_calls(
        self,
        tool_calls: list[ExtractionToolCall],
        content: list[MessageContentItem],
        context: dict[str, Any],
        prior_tool_results: list[dict[str, Any]],
        conversation_id: str,
        message_id: str,
    ) -> tuple[list[ExtractionToolCall], list[dict[str, Any]]]:
        if not tool_calls:
            return [], []

        input_text = self._joined_text(content)
        kept = []
        tool_results = []
        for tool_call in tool_calls:
            drop_reason = self._tool_call_drop_reason(
                tool_call,
                input_text=input_text,
                context=context,
                prior_tool_results=prior_tool_results,
            )
            if drop_reason:
                self._log_rejected_tool_call(
                    tool_call=tool_call,
                    reason=drop_reason,
                    conversation_id=conversation_id,
                    message_id=message_id,
                )
                tool_results.append(self._tool_result(tool_call, "rejected", reason=drop_reason))
                continue
            kept.append(tool_call)
        return kept, tool_results

    def _tool_call_drop_reason(
        self,
        tool_call: ExtractionToolCall,
        input_text: str,
        context: dict[str, Any],
        prior_tool_results: list[dict[str, Any]],
    ) -> str | None:
        if tool_call.is_read_only_tool:
            return None
        if context.get("input_origin") == "pending_action_observation":
            return "record_tool_disallowed_for_pending_action_observation"

        if tool_call.is_pending_action_tool:
            return self._pending_action_tool_drop_reason(tool_call, input_text, context)

        grounding = tool_call.grounding
        if grounding is None:
            return "grounding_missing"

        source = self._normalized_grounding_source(grounding.source)
        if source == "model_inference":
            return "source=model_inference"
        evidence_text = grounding.evidence_text.strip()
        if not evidence_text:
            return "evidence_text_empty"

        if source in {"current_user_message", "normalized_media_text"}:
            if evidence_text not in input_text:
                return "evidence_not_in_current_message"
            return None
        if source == "recent_user_message":
            if not self._evidence_in_recent_user_messages(evidence_text, context):
                return "evidence_not_in_recent_user_messages"
            return None
        if source == "active_pending_action":
            if not self._grounding_references_active_pending_action(grounding, context):
                return "active_pending_action_not_found"
            return None
        if source == "tool_result":
            if not self._grounding_references_tool_result(grounding, prior_tool_results):
                return "tool_result_not_found"
            return None
        if source == "confirmed_record":
            return "source=confirmed_record"
        if source == "assistant_plan":
            if not self._evidence_in_assistant_plan(evidence_text, context):
                return "assistant_plan_evidence_not_found"
            return None
        if evidence_text not in input_text:
            return "evidence_not_in_user_message"
        return None

    def _normalized_grounding_source(self, source: GroundingSource) -> str:
        if source == "user_current_turn":
            return "current_user_message"
        if source == "assistant_generated":
            return "assistant_plan"
        return str(source)

    def _has_direct_record_grounding(self, tool_call: ExtractionToolCall) -> bool:
        if not tool_call.grounding:
            return False
        return self._normalized_grounding_source(tool_call.grounding.source) in {
            "current_user_message",
            "normalized_media_text",
        }

    def _record_action_warnings(
        self,
        tool_call: ExtractionToolCall,
        warnings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized = list(warnings)
        if self._has_direct_record_grounding(tool_call):
            return normalized
        if any(item.get("reason") == "grounding_requires_confirmation" for item in normalized):
            return normalized
        normalized.append({"field": "grounding", "reason": "grounding_requires_confirmation"})
        return normalized

    def _pending_action_tool_drop_reason(
        self,
        tool_call: ExtractionToolCall,
        input_text: str,
        context: dict[str, Any],
    ) -> str | None:
        pending_action_ids = self._pending_action_ids_from_tool_call(tool_call)
        if not pending_action_ids:
            return "pending_action_id_missing"
        if not all(
            self._active_pending_action_exists(pending_action_id, context)
            for pending_action_id in pending_action_ids
        ):
            return "active_pending_action_not_found"

        grounding = tool_call.grounding
        if grounding is None:
            return "grounding_missing"
        source = self._normalized_grounding_source(grounding.source)
        if source != "current_user_message":
            return "pending_action_tool_requires_current_user_message"
        evidence_text = grounding.evidence_text.strip()
        if not evidence_text:
            return "evidence_text_empty"
        if evidence_text not in input_text:
            return "evidence_not_in_current_message"
        return None

    def _pending_action_ids_from_tool_call(self, tool_call: ExtractionToolCall) -> list[str]:
        if tool_call.name in {"commit_pending_actions", "discard_pending_actions"}:
            value = tool_call.arguments.get("pending_action_ids")
            if not isinstance(value, list):
                return []
            return [str(item).strip() for item in value if str(item or "").strip()]
        pending_action_id = str(tool_call.arguments.get("pending_action_id") or "").strip()
        return [pending_action_id] if pending_action_id else []

    def _active_pending_action_exists(
        self,
        pending_action_id: str,
        context: dict[str, Any],
    ) -> bool:
        actions = context.get("active_pending_actions")
        if not isinstance(actions, list):
            return False
        return any(
            isinstance(action, dict) and action.get("pending_action_id") == pending_action_id
            for action in actions
        )

    def _execute_read_only_tool(
        self,
        *,
        tool_call: ExtractionToolCall,
        user_id: str,
    ) -> dict[str, Any]:
        if tool_call.name == "query_meal_records":
            local_date = self._date_arg(tool_call.arguments.get("local_date"))
            result = MealService(self.db).list_meals(user_id, local_date=local_date)
            return self._tool_result(tool_call, "succeeded", data=result)
        if tool_call.name == "query_body_metric_records":
            date_from = self._date_arg(tool_call.arguments.get("date_from"))
            date_to = self._date_arg(tool_call.arguments.get("date_to"))
            result = BodyMetricService(self.db).list_body_metrics(
                user_id,
                date_from=date_from,
                date_to=date_to,
            )
            return self._tool_result(tool_call, "succeeded", data=result)
        return self._tool_result(tool_call, "rejected", reason="unsupported_read_only_tool")

    def _execute_pending_action_tool(
        self,
        *,
        tool_call: ExtractionToolCall,
        user_id: str,
    ) -> dict[str, Any]:
        from app.schemas.pending_action import PendingActionUpdateRequest
        from app.services.pending_actions import PendingActionService

        service = PendingActionService(self.db)
        pending_action_id = str(tool_call.arguments.get("pending_action_id") or "").strip()
        if tool_call.name == "update_pending_action":
            draft_payload = tool_call.arguments.get("draft_payload")
            if not isinstance(draft_payload, dict):
                return {
                    "tool_result": self._tool_result(
                        tool_call,
                        "rejected",
                        reason="draft_payload_missing",
                    )
                }
            try:
                updated_action = service.update_action(
                    user_id,
                    pending_action_id,
                    PendingActionUpdateRequest(
                        draft_payload=draft_payload,
                        user_note=tool_call.arguments.get("user_note"),
                    ),
                    commit=False,
                )
            except AppError as exc:
                return {
                    "tool_result": self._tool_result(
                        tool_call,
                        "rejected",
                        reason=exc.code,
                    )
                }
            tool_result = self._tool_result(
                tool_call,
                str(updated_action.get("status") or "pending_confirmation"),
                data=updated_action,
            )
            tool_result["pending_action_id"] = pending_action_id
            return {"pending_action": updated_action, "tool_result": tool_result}

        if tool_call.name == "commit_pending_action":
            try:
                committed = service.commit_action_for_agent(
                    user_id,
                    pending_action_id,
                    draft_payload_patch=tool_call.arguments.get("draft_payload_patch"),
                )
            except AppError as exc:
                return {
                    "tool_result": self._tool_result(
                        tool_call,
                        "rejected",
                        reason=exc.code,
                    )
                }
            record = {
                "type": committed["record_type"],
                "record_id": committed["record_id"],
                "record": committed["record"],
                "source": "pending_action_commit",
                "source_message_id": committed["source_message_id"],
                "confidence": committed["confidence"],
                "decision_reason": "llm_judged_user_confirmed_pending_action",
                "message": committed["message"],
            }
            return {
                "committed_record": record,
                "tool_result": self._tool_result(tool_call, "committed", record=record),
            }

        if tool_call.name == "commit_pending_actions":
            pending_action_ids = self._pending_action_ids_from_tool_call(tool_call)
            result = service.commit_actions_for_agent(user_id, pending_action_ids)
            committed_records = [
                {
                    "type": item["record_type"],
                    "record_id": item["record_id"],
                    "record": item["record"],
                    "source": "pending_action_commit",
                    "source_message_id": item["source_message_id"],
                    "confidence": item["confidence"],
                    "decision_reason": "llm_judged_user_confirmed_pending_actions",
                    "message": item["message"],
                }
                for item in result["committed"]
            ]
            status = "committed" if not result["failed"] else "partial_committed"
            return {
                "committed_records": committed_records,
                "tool_result": {
                    "tool_name": tool_call.name,
                    "action_type": tool_call.action_type,
                    "status": status,
                    "committed": [
                        {
                            "pending_action_id": item["pending_action_id"],
                            "record_type": item["record_type"],
                            "record_id": item["record_id"],
                        }
                        for item in result["committed"]
                    ],
                    "failed": result["failed"],
                },
            }

        if tool_call.name == "discard_pending_actions":
            pending_action_ids = self._pending_action_ids_from_tool_call(tool_call)
            result = service.discard_actions_for_agent(user_id, pending_action_ids)
            return {
                "tool_result": {
                    "tool_name": tool_call.name,
                    "action_type": tool_call.action_type,
                    "status": "discarded" if not result["failed"] else "partial_discarded",
                    "discarded": result["discarded"],
                    "failed": result["failed"],
                }
            }

        return {
            "tool_result": self._tool_result(
                tool_call,
                "rejected",
                reason="unsupported_pending_action_tool",
            )
        }

    def _date_arg(self, value: Any) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
        return None

    def _evidence_in_recent_user_messages(
        self,
        evidence_text: str,
        context: dict[str, Any],
    ) -> bool:
        for message in self._context_messages(context):
            if message.get("role") != "user":
                continue
            if evidence_text in self._message_text(message):
                return True
        return False

    def _grounding_references_active_pending_action(
        self,
        grounding,
        context: dict[str, Any],
    ) -> bool:
        actions = context.get("active_pending_actions")
        if not isinstance(actions, list):
            return False
        for action in actions:
            if not isinstance(action, dict):
                continue
            if grounding.source_id and grounding.source_id == action.get("pending_action_id"):
                return True
            if grounding.evidence_text and grounding.evidence_text in self._json_text(action):
                return True
        return False

    def _grounding_references_tool_result(
        self,
        grounding,
        prior_tool_results: list[dict[str, Any]],
    ) -> bool:
        for result in prior_tool_results:
            if grounding.source_id and grounding.source_id in {
                str(result.get("tool_name") or ""),
                str(result.get("record_id") or ""),
                str(result.get("pending_action_id") or ""),
            }:
                return True
            if grounding.evidence_text and grounding.evidence_text in self._json_text(result):
                return True
        return False

    def _evidence_in_assistant_plan(
        self,
        evidence_text: str,
        context: dict[str, Any],
    ) -> bool:
        active_offer = context.get("ephemeral_state", {}).get("active_offer")
        if isinstance(active_offer, dict) and evidence_text in self._json_text(active_offer):
            return True
        for message in self._context_messages(context):
            if message.get("role") != "assistant":
                continue
            if evidence_text in self._message_text(message):
                return True
        return False

    def _context_messages(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        messages = []
        for key in ("short_term_messages", "recent_messages"):
            value = context.get(key)
            if isinstance(value, list):
                messages.extend(item for item in value if isinstance(item, dict))
        return messages

    def _message_text(self, message: dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("event_type") or ""))
            return " ".join(part for part in parts if part)
        return str(message.get("content_preview") or "")

    def _json_text(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    def _log_rejected_tool_call(
        self,
        tool_call: ExtractionToolCall,
        reason: str,
        conversation_id: str,
        message_id: str,
    ) -> None:
        logger.info(
            (
                "ai_tool_call_rejected tool_name=%s action_type=%s reason=%s "
                "conversation_id=%s message_id=%s"
            ),
            tool_call.name,
            tool_call.action_type,
            reason,
            conversation_id,
            message_id,
        )

    def _tool_result(
        self,
        tool_call: ExtractionToolCall,
        status: str,
        reason: str | None = None,
        action: AgentPendingAction | None = None,
        record: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = {
            "tool_name": tool_call.name,
            "action_type": tool_call.action_type,
            "status": status,
        }
        if reason:
            result["reason"] = reason
        if action is not None:
            result["pending_action_id"] = action.id
        if record is not None:
            result["record_type"] = record["type"]
            result["record_id"] = record["record_id"]
        if data is not None:
            result["data"] = data
        return result

    def _create_pending_action(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        extraction_id: str,
        confidence: Decimal | None,
        action_type: str,
        draft_payload: dict[str, Any],
        warnings: list[dict[str, Any]],
        status: str = PENDING_CONFIRMATION,
    ) -> AgentPendingAction:
        now = utc_now()
        action = AgentPendingAction(
            id=new_id("pa"),
            user_id=user_id,
            conversation_id=conversation_id,
            source_message_id=message_id,
            extraction_id=extraction_id,
            action_type=action_type,
            status=status,
            draft_payload_json=draft_payload,
            warnings_json=warnings,
            confidence=confidence or Decimal("0"),
            expires_at=pending_action_expires_at(now),
            created_at=now,
            updated_at=now,
        )
        self.db.add(action)
        self.db.flush()
        return action

    def _result_response(
        self,
        provider_result: ExtractionProviderResult,
        pending_actions: list[AgentPendingAction],
        committed_records: list[dict[str, Any]],
        tool_results: list[dict[str, Any]] | None = None,
    ) -> dict:
        tool_results = tool_results or []
        pending_response = [
            action if isinstance(action, dict) else self._pending_response(action)
            for action in pending_actions
        ]
        return {
            "assistant_text": self._assistant_text(
                provider_result.assistant_text,
                pending_response,
                committed_records,
                tool_results,
            ),
            "assistant_content": self._assistant_content(
                provider_result.assistant_text,
                pending_response,
                committed_records,
                tool_results,
            ),
            "intent": provider_result.intent,
            "requires_review": bool(pending_actions),
            "pending_actions": pending_response,
            "committed_records": committed_records,
            "tool_results": tool_results,
            "dialogue_state_patch": provider_result.dialogue_state_patch,
        }

    def _pending_response(self, action: AgentPendingAction) -> dict:
        return {
            "pending_action_id": action.id,
            "type": action.action_type,
            "status": action.status,
            "confidence": decimal_to_float(action.confidence),
            "draft_payload": action.draft_payload_json,
            "warnings": action.warnings_json or [],
            "created_at": action.created_at,
            "updated_at": action.updated_at,
            "expires_at": action.expires_at,
        }

    def _input_types(self, content: list[MessageContentItem]) -> list[str]:
        return sorted({item.type for item in content})

    def _action_confidence(
        self,
        action_spec,
        provider_result: ExtractionProviderResult,
        draft_payload: dict[str, Any],
    ) -> Decimal | None:
        if action_spec.confidence is not None:
            return action_spec.confidence
        if provider_result.confidence is not None:
            return provider_result.confidence
        draft_confidence = draft_payload.get("confidence")
        if draft_confidence is None:
            return None
        return Decimal(str(draft_confidence))

    def _joined_text(self, content: list[MessageContentItem]) -> str:
        return " ".join(item.text or "" for item in content if item.type == "text").strip()

    def _assistant_text(
        self,
        provider_text: str,
        pending_actions: list[dict],
        committed_records: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
    ) -> str:
        if committed_records:
            committed_text = " ".join(item["message"] for item in committed_records)
            if pending_actions:
                return f"{committed_text} 另有 {len(pending_actions)} 条记录草稿需要你确认。"
            return committed_text
        if pending_actions:
            return self._pending_actions_text(pending_actions)
        if self._has_rejected_tool_call(tool_results) and self._contains_save_claim(provider_text):
            return self._no_record_saved_text()
        return self._sanitize_provider_text(provider_text)

    def _assistant_content(
        self,
        provider_text: str,
        pending_actions: list[dict],
        committed_records: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if committed_records:
            content = [
                {
                    "type": "event",
                    "event_type": "record_committed",
                    "text": item["message"],
                    "record_type": item["type"],
                    "record_id": item["record_id"],
                    "source_message_id": item["source_message_id"],
                }
                for item in committed_records
            ]
            if pending_actions:
                content.append(
                    {
                        "type": "text",
                        "text": f"另有 {len(pending_actions)} 条记录草稿需要你确认。",
                    }
                )
            return content

        return [
            {
                "type": "text",
                "text": self._assistant_text(
                    provider_text,
                    pending_actions,
                    committed_records,
                    tool_results,
                ),
            }
        ]

    def _pending_actions_text(self, pending_actions: list[dict]) -> str:
        if any(action.get("status") == "needs_clarification" for action in pending_actions):
            return (
                "我整理出一条候选记录，但还有关键信息需要补充，"
                "请先补充或修改后再保存。"
            )
        if len(pending_actions) == 1:
            action_type = pending_actions[0].get("type")
            if action_type == "create_meal_record":
                return (
                    "我整理出一条餐食记录草稿，尚未保存为正式记录，"
                    "请确认或修改后再保存。确认后我会根据确认结果继续处理这轮剩余问题。"
                )
            if action_type == "create_body_metric_record":
                return (
                    "我整理出一条身体指标草稿，尚未保存为正式记录，"
                    "请确认或修改后再保存。确认后我会根据确认结果继续处理这轮剩余问题。"
                )
            if action_type == "create_workout_record":
                return (
                    "我整理出一条锻炼记录草稿，尚未保存为正式记录，"
                    "请确认或修改后再保存。"
                )
        return (
            f"我整理出 {len(pending_actions)} 条记录草稿，尚未保存为正式记录，"
            "请逐项确认或修改后再保存。确认后我会根据确认结果继续处理这轮剩余问题。"
        )

    def _has_rejected_tool_call(self, tool_results: list[dict[str, Any]]) -> bool:
        return any(result.get("status") == "rejected" for result in tool_results)

    def _sanitize_provider_text(self, provider_text: str) -> str:
        if self._contains_save_claim(provider_text):
            return self._no_record_saved_text()
        return provider_text

    def _contains_save_claim(self, text: str) -> bool:
        return any(term in text for term in SAVE_CLAIM_TERMS)

    def _no_record_saved_text(self) -> str:
        return (
            "这份内容尚未保存为正式记录。当前只会记录你本轮明确说出的实际饮食或身体指标。"
            "如果你已经实际吃了这份内容，请直接告诉我实际吃了什么，我再帮你记录。"
        )

    def _meal_items_text(self, items: list[dict]) -> str:
        parts = []
        for item in items[:5]:
            name = item.get("name")
            if not name:
                continue
            grams = item.get("portion_grams")
            parts.append(f"{name}（{grams:g}g）" if isinstance(grams, (int, float)) else str(name))
        if len(items) > 5:
            parts.append(f"等 {len(items)} 项")
        return "、".join(parts)
