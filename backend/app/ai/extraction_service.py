import logging
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.commit_rules import decide_auto_commit
from app.ai.draft_normalizer import normalize_pending_action_draft
from app.ai.providers import ExtractionProvider, get_extraction_provider
from app.ai.types import (
    ExtractionActionSpec,
    ExtractionInput,
    ExtractionProviderResult,
    ExtractionToolCall,
)
from app.auth.security import new_id, utc_now
from app.core.config import Settings, get_settings
from app.models import AgentExtraction, AgentPendingAction
from app.schemas.conversation import MessageContentItem
from app.schemas.pending_action import decimal_to_float
from app.schemas.records import BodyMetricCreateRequest, MealCreateRequest
from app.services.body_metrics import BodyMetricService
from app.services.meals import MealService

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
        tool_calls, tool_results = self._filter_tool_calls(
            provider_result.tool_calls,
            content=content,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        if not tool_calls:
            return self._result_response(provider_result, [], [], tool_results)

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

        pending_actions = []
        committed_records = []
        input_text = self._joined_text(content)
        for tool_call in tool_calls:
            action_spec = tool_call.to_action_spec()
            draft_payload = normalize_pending_action_draft(
                action_spec.action_type,
                action_spec.draft_payload,
                input_text=input_text,
                now=utc_now(),
            )
            confidence = self._action_confidence(action_spec, provider_result, draft_payload)
            decision = decide_auto_commit(
                action_type=action_spec.action_type,
                draft_payload=draft_payload,
                confidence=confidence,
                warnings=action_spec.warnings,
                provider_warnings=provider_result.warnings,
                input_types=self._input_types(content),
                input_text=input_text,
                input_normalization=(context or {}).get("input_normalization"),
            )
            if decision.auto_commit:
                try:
                    record = self._auto_commit_action(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        action_type=action_spec.action_type,
                        draft_payload=draft_payload,
                        confidence=confidence,
                        decision_reason=decision.reason,
                    )
                    committed_records.append(record)
                    tool_results.append(self._tool_result(tool_call, "committed", record=record))
                except ValidationError:
                    action = self._create_pending_action(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        extraction_id=extraction.id,
                        confidence=confidence,
                        action_type=action_spec.action_type,
                        draft_payload=draft_payload,
                        warnings=[
                            *action_spec.warnings,
                            {
                                "field": "draft_payload",
                                "reason": "auto_commit_validation_failed",
                            },
                        ],
                    )
                    pending_actions.append(action)
                    tool_results.append(
                        self._tool_result(tool_call, "pending_confirmation", action=action)
                    )
                continue

            action = self._create_pending_action(
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                extraction_id=extraction.id,
                confidence=confidence,
                action_type=action_spec.action_type,
                draft_payload=draft_payload,
                warnings=action_spec.warnings,
            )
            pending_actions.append(action)
            tool_results.append(self._tool_result(tool_call, "pending_confirmation", action=action))
        extraction.requires_confirmation = bool(pending_actions)
        return self._result_response(
            provider_result,
            pending_actions,
            committed_records,
            tool_results,
        )

    def _filter_tool_calls(
        self,
        tool_calls: list[ExtractionToolCall],
        content: list[MessageContentItem],
        conversation_id: str,
        message_id: str,
    ) -> tuple[list[ExtractionToolCall], list[dict[str, Any]]]:
        if not tool_calls:
            return [], []

        input_text = self._joined_text(content)
        kept = []
        tool_results = []
        for tool_call in tool_calls:
            drop_reason = self._tool_call_drop_reason(tool_call, input_text)
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
    ) -> str | None:
        grounding = tool_call.grounding
        if grounding is None:
            return "grounding_missing"
        if grounding.source != "user_current_turn":
            return f"source={grounding.source}"

        evidence_text = grounding.evidence_text.strip()
        if not evidence_text:
            return "evidence_text_empty"
        if evidence_text not in input_text:
            return "evidence_not_in_user_message"
        return None

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
    ) -> AgentPendingAction:
        action = AgentPendingAction(
            id=new_id("pa"),
            user_id=user_id,
            conversation_id=conversation_id,
            source_message_id=message_id,
            extraction_id=extraction_id,
            action_type=action_type,
            status="pending_confirmation",
            draft_payload_json=draft_payload,
            warnings_json=warnings,
            confidence=confidence or Decimal("0"),
        )
        self.db.add(action)
        self.db.flush()
        return action

    def _auto_commit_action(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        action_type: str,
        draft_payload: dict[str, Any],
        confidence: Decimal | None,
        decision_reason: str,
    ) -> dict[str, Any]:
        if action_type == "create_meal_record":
            payload = MealCreateRequest.model_validate(draft_payload)
            record = MealService(self.db).create_meal(user_id, payload, commit=False)
            record_type = "meal"
        elif action_type == "create_body_metric_record":
            payload = BodyMetricCreateRequest.model_validate(draft_payload)
            record = BodyMetricService(self.db).create_body_metric(user_id, payload, commit=False)
            record_type = "body_metric"
        else:
            raise ValueError(f"Unsupported auto commit action: {action_type}")

        message = self._auto_commit_text(record_type, record)
        return {
            "type": record_type,
            "record_id": record["id"],
            "record": record,
            "source": "auto_commit",
            "source_message_id": message_id,
            "confidence": decimal_to_float(confidence),
            "decision_reason": decision_reason,
            "message": message,
        }

    def _result_response(
        self,
        provider_result: ExtractionProviderResult,
        pending_actions: list[AgentPendingAction],
        committed_records: list[dict[str, Any]],
        tool_results: list[dict[str, Any]] | None = None,
    ) -> dict:
        tool_results = tool_results or []
        pending_response = [self._pending_response(action) for action in pending_actions]
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
                    "event_type": "record_auto_committed",
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
        if len(pending_actions) == 1:
            action_type = pending_actions[0].get("type")
            if action_type == "create_meal_record":
                return (
                    "我整理出一条餐食记录草稿，尚未保存为正式记录，"
                    "请确认或修改后再保存。"
                )
            if action_type == "create_body_metric_record":
                return (
                    "我整理出一条身体指标草稿，尚未保存为正式记录，"
                    "请确认或修改后再保存。"
                )
        return (
            f"我整理出 {len(pending_actions)} 条记录草稿，尚未保存为正式记录，"
            "请逐项确认或修改后再保存。"
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

    def _auto_commit_text(self, record_type: str, record: dict[str, Any]) -> str:
        if record_type == "meal":
            meal_label = {
                "breakfast": "早餐",
                "lunch": "午餐",
                "dinner": "晚餐",
                "snack": "加餐",
                "unknown": "餐食",
            }.get(record.get("meal_type") or "unknown", "餐食")
            item_text = self._meal_items_text(record.get("items") or [])
            if item_text:
                return f"已自动保存：{meal_label}，{item_text}。可在记录页修改或删除。"
            return f"已自动保存：{meal_label}。可在记录页修改或删除。"

        parts = []
        if record.get("weight_kg") is not None:
            parts.append(f"体重 {record['weight_kg']:g}kg")
        if record.get("body_fat_percentage") is not None:
            parts.append(f"体脂 {record['body_fat_percentage']:g}%")
        if record.get("bmi") is not None:
            parts.append(f"BMI {record['bmi']:g}")
        detail = "，".join(parts) if parts else "身体指标"
        return f"已自动保存：{detail}。可在记录页修改或删除。"

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
