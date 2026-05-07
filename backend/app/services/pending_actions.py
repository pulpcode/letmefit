import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agent_runtime import AgentRuntime
from app.ai.draft_normalizer import normalize_pending_action_draft
from app.auth.security import new_id, utc_now
from app.core.database import get_db
from app.core.errors import AppError
from app.models import AgentPendingAction, Conversation, ConversationMessage
from app.schemas.conversation import MessageContentItem
from app.schemas.pending_action import (
    PendingActionContinuationRequest,
    PendingActionUpdateRequest,
    decimal_to_float,
)
from app.schemas.records import BodyMetricCreateRequest, MealCreateRequest
from app.services.body_metrics import BodyMetricService
from app.services.conversation_context import ConversationContextBuilder
from app.services.dialogue_state import (
    normalize_dialogue_state,
    update_dialogue_state_after_assistant,
)
from app.services.meals import MealService
from app.services.pending_action_lifecycle import (
    CONFIRMABLE_PENDING_ACTION_STATUS,
    EDITABLE_PENDING_ACTION_STATUSES,
    EXPIRED,
    NEEDS_CLARIFICATION,
    classify_pending_action_status,
    normalize_status_warnings,
    pending_action_is_expired,
)

logger = logging.getLogger(__name__)


EDITABLE_STATUSES = EDITABLE_PENDING_ACTION_STATUSES


@dataclass(frozen=True)
class PendingActionCommitHandler:
    record_type: str
    commit_method: str


class PendingActionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_conversation(self, user_id: str, conversation_id: str) -> dict:
        self._ensure_owned_conversation(user_id, conversation_id)
        actions = list(
            self.db.scalars(
                select(AgentPendingAction)
                .where(
                    AgentPendingAction.user_id == user_id,
                    AgentPendingAction.conversation_id == conversation_id,
                )
                .order_by(AgentPendingAction.created_at.asc())
            )
        )
        now = utc_now()
        expired_count = 0
        for action in actions:
            if action.status in EDITABLE_STATUSES and pending_action_is_expired(action, now):
                action.status = EXPIRED
                expired_count += 1
        if expired_count:
            self.db.commit()
        return {"pending_actions": [self._response(action) for action in actions]}

    def update_action(
        self,
        user_id: str,
        pending_action_id: str,
        payload: PendingActionUpdateRequest,
        commit: bool = True,
    ) -> dict:
        action = self._get_owned_action(user_id, pending_action_id, lock=True)
        self._ensure_editable(action)
        draft_payload = deepcopy(action.draft_payload_json or {})
        draft_payload.update(payload.draft_payload)
        if payload.user_note:
            draft_payload["user_note"] = payload.user_note
        action.draft_payload_json = normalize_pending_action_draft(
            action.action_type,
            draft_payload,
        )
        self._apply_status_from_draft(action)
        if commit:
            self.db.commit()
            self.db.refresh(action)
        else:
            self.db.flush()
        return self._response(action)

    def commit_action_for_agent(
        self,
        user_id: str,
        pending_action_id: str,
        draft_payload_patch: Any = None,
    ) -> dict[str, Any]:
        action = self._get_owned_action(user_id, pending_action_id, lock=True)
        if action.status == "committed":
            return {
                "pending_action_id": action.id,
                "record_type": action.committed_record_type or "",
                "record_id": action.committed_record_id or "",
                "record": {},
                "message": "已保存到正式记录。",
                "source_message_id": action.source_message_id,
                "confidence": decimal_to_float(action.confidence),
            }
        if draft_payload_patch is not None:
            if not isinstance(draft_payload_patch, dict):
                raise AppError("VALIDATION_ERROR", "草稿修改内容不正确", status_code=422)
            self._ensure_editable(action)
            draft_payload = deepcopy(action.draft_payload_json or {})
            draft_payload.update(draft_payload_patch)
            action.draft_payload_json = normalize_pending_action_draft(
                action.action_type,
                draft_payload,
            )
            self._apply_status_from_draft(action)
        self._ensure_confirmable(action)
        return self._commit_action(user_id, action)

    def commit_actions_for_agent(
        self,
        user_id: str,
        pending_action_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        committed = []
        failed = []
        for pending_action_id in pending_action_ids:
            try:
                committed.append(self.commit_action_for_agent(user_id, pending_action_id))
            except AppError as exc:
                failed.append(
                    {
                        "pending_action_id": pending_action_id,
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                    }
                )
        return {"committed": committed, "failed": failed}

    def confirm_action(
        self,
        user_id: str,
        pending_action_id: str,
        payload: PendingActionContinuationRequest | None = None,
    ) -> dict:
        payload = payload or PendingActionContinuationRequest()
        action = self._get_owned_action(user_id, pending_action_id, lock=True)
        if action.status == "committed":
            return self._committed_response(action)
        self._ensure_confirmable(action)
        committed = self._commit_action(user_id, action)
        event_message_id = committed["event_message_id"]
        self.db.commit()
        response = self._committed_response(action)
        if payload.continue_agent:
            observation = self._confirmed_observation(
                action=action,
                record_type=committed["record_type"],
                record=committed["record"],
            )
            continuation = self._run_continuation(
                action=action,
                observation=observation,
                event_message_id=event_message_id,
                include_agent_trace=payload.include_agent_trace,
            )
            if continuation is not None:
                response["continuation"] = continuation
        return response

    def discard_action(
        self,
        user_id: str,
        pending_action_id: str,
        payload: PendingActionContinuationRequest | None = None,
    ) -> dict:
        payload = payload or PendingActionContinuationRequest()
        action = self._get_owned_action(user_id, pending_action_id, lock=True)
        if action.status == "discarded":
            return {
                "pending_action_id": action.id,
                "status": action.status,
            }
        self._ensure_editable(action)
        action.status = "discarded"
        event_message = self._add_action_event(
            action=action,
            event_type="pending_action_discarded",
            text="已放弃这条候选记录。",
        )
        event_message_id = event_message.id
        self.db.commit()
        response = {
            "pending_action_id": action.id,
            "status": action.status,
        }
        if payload.continue_agent:
            observation = self._discarded_observation(action)
            continuation = self._run_continuation(
                action=action,
                observation=observation,
                event_message_id=event_message_id,
                include_agent_trace=payload.include_agent_trace,
            )
            if continuation is not None:
                response["continuation"] = continuation
        return response

    def discard_actions_for_agent(
        self,
        user_id: str,
        pending_action_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        discarded = []
        failed = []
        for pending_action_id in pending_action_ids:
            try:
                action = self._get_owned_action(user_id, pending_action_id, lock=True)
                if action.status == "discarded":
                    discarded.append({"pending_action_id": action.id, "status": action.status})
                    continue
                self._ensure_editable(action)
                action.status = "discarded"
                self._add_action_event(
                    action=action,
                    event_type="pending_action_discarded",
                    text="已放弃这条候选记录。",
                )
                self.db.flush()
                discarded.append({"pending_action_id": action.id, "status": action.status})
            except AppError as exc:
                failed.append(
                    {
                        "pending_action_id": pending_action_id,
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                    }
                )
        return {"discarded": discarded, "failed": failed}

    def _commit_meal(self, user_id: str, action: AgentPendingAction) -> dict:
        draft_payload = self._draft_with_source(action)
        try:
            payload = MealCreateRequest.model_validate(draft_payload)
        except ValidationError as exc:
            raise AppError(
                "VALIDATION_ERROR",
                "待确认餐食草稿不完整",
                status_code=422,
                details={"errors": exc.errors()},
            ) from exc
        return MealService(self.db).create_meal(user_id, payload, commit=False)

    def _commit_body_metric(self, user_id: str, action: AgentPendingAction) -> dict:
        draft_payload = self._draft_with_source(action)
        try:
            payload = BodyMetricCreateRequest.model_validate(draft_payload)
        except ValidationError as exc:
            raise AppError(
                "VALIDATION_ERROR",
                "待确认身体指标草稿不完整",
                status_code=422,
                details={"errors": exc.errors()},
            ) from exc
        return BodyMetricService(self.db).create_body_metric(user_id, payload, commit=False)

    def _commit_action(self, user_id: str, action: AgentPendingAction) -> dict[str, Any]:
        handler = self._commit_handler(action.action_type)
        commit_method = getattr(self, handler.commit_method)
        record = commit_method(user_id, action)
        action.status = "committed"
        action.confirmed_at = utc_now()
        action.committed_record_type = handler.record_type
        action.committed_record_id = record["id"]
        message = self._record_committed_text(handler.record_type, record)
        event_message = self._add_action_event(
            action=action,
            event_type="record_committed",
            text=message,
            record_type=handler.record_type,
            record_id=record["id"],
        )
        self.db.flush()
        return {
            "pending_action_id": action.id,
            "record_type": handler.record_type,
            "record_id": record["id"],
            "record": record,
            "message": message,
            "event_message_id": event_message.id,
            "source_message_id": action.source_message_id,
            "confidence": decimal_to_float(action.confidence),
        }

    def _commit_handler(self, action_type: str) -> PendingActionCommitHandler:
        handlers = {
            "create_meal_record": PendingActionCommitHandler(
                record_type="meal",
                commit_method="_commit_meal",
            ),
            "create_body_metric_record": PendingActionCommitHandler(
                record_type="body_metric",
                commit_method="_commit_body_metric",
            ),
        }
        handler = handlers.get(action_type)
        if handler is None:
            raise AppError("VALIDATION_ERROR", "该待确认动作暂不支持确认写入", status_code=422)
        return handler

    def _draft_with_source(self, action: AgentPendingAction) -> dict[str, Any]:
        draft_payload = normalize_pending_action_draft(
            action.action_type,
            action.draft_payload_json,
        )
        draft_payload["source_pending_action_id"] = action.id
        return draft_payload

    def _ensure_owned_conversation(self, user_id: str, conversation_id: str) -> None:
        self._get_owned_conversation(user_id, conversation_id)

    def _get_owned_conversation(self, user_id: str, conversation_id: str) -> Conversation:
        conversation = self.db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if not conversation:
            raise AppError("RESOURCE_NOT_FOUND", "会话不存在", status_code=404)
        return conversation

    def _get_owned_action(
        self,
        user_id: str,
        pending_action_id: str,
        lock: bool = False,
    ) -> AgentPendingAction:
        query = select(AgentPendingAction).where(
            AgentPendingAction.id == pending_action_id,
            AgentPendingAction.user_id == user_id,
        )
        if lock:
            query = query.with_for_update()
        action = self.db.scalar(query)
        if not action:
            raise AppError("RESOURCE_NOT_FOUND", "待确认动作不存在", status_code=404)
        return action

    def _ensure_editable(self, action: AgentPendingAction) -> None:
        self._expire_action_if_needed(action)
        if action.status not in EDITABLE_STATUSES:
            raise AppError("VALIDATION_ERROR", "待确认动作已处理，不能再次修改", status_code=422)

    def _ensure_confirmable(self, action: AgentPendingAction) -> None:
        self._expire_action_if_needed(action)
        if action.status == NEEDS_CLARIFICATION:
            raise AppError(
                "PENDING_ACTION_NEEDS_CLARIFICATION",
                "这条候选记录仍需补充信息，暂不能保存",
                status_code=422,
            )
        if action.status != CONFIRMABLE_PENDING_ACTION_STATUS:
            raise AppError("VALIDATION_ERROR", "待确认动作已处理，不能再次确认", status_code=422)

    def _expire_action_if_needed(self, action: AgentPendingAction) -> None:
        if action.status not in EDITABLE_STATUSES:
            return
        if pending_action_is_expired(action, utc_now()):
            action.status = EXPIRED
            self.db.flush()
            raise AppError(
                "PENDING_ACTION_EXPIRED",
                "这条候选记录已过期，请重新描述后再保存",
                status_code=422,
            )

    def _apply_status_from_draft(self, action: AgentPendingAction) -> None:
        prior_warnings = [
            item
            for item in action.warnings_json or []
            if item.get("reason")
            not in {
                "needs_clarification",
                "missing_information",
                "missing_required_field",
                "ambiguous_user_correction",
            }
        ]
        status = classify_pending_action_status(
            action.action_type,
            action.draft_payload_json or {},
            warnings=prior_warnings,
        )
        action.status = status
        action.warnings_json = normalize_status_warnings(status, prior_warnings)

    def _response(self, action: AgentPendingAction) -> dict:
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

    def _committed_response(self, action: AgentPendingAction) -> dict:
        return {
            "pending_action_id": action.id,
            "status": action.status,
            "record_type": action.committed_record_type or "",
            "record_id": action.committed_record_id or "",
        }

    def _confirmed_observation(
        self,
        *,
        action: AgentPendingAction,
        record_type: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        summary = self._record_committed_text(record_type, record)
        return {
            "type": "pending_action_observation",
            "event": "confirmed",
            "pending_action_id": action.id,
            "action_type": action.action_type,
            "record_type": record_type,
            "record_id": record["id"],
            "record_summary": summary,
            "text": f"用户已确认待确认动作。{summary}",
        }

    def _discarded_observation(self, action: AgentPendingAction) -> dict[str, Any]:
        return {
            "type": "pending_action_observation",
            "event": "discarded",
            "pending_action_id": action.id,
            "action_type": action.action_type,
            "text": "用户已放弃这条候选记录。",
        }

    def _run_continuation(
        self,
        *,
        action: AgentPendingAction,
        observation: dict[str, Any],
        event_message_id: str,
        include_agent_trace: bool,
    ) -> dict[str, Any] | None:
        try:
            conversation = self._get_owned_conversation(action.user_id, action.conversation_id)
            previous_dialogue_state = normalize_dialogue_state(conversation.dialogue_state_json)
            context = ConversationContextBuilder(self.db).build(
                user_id=action.user_id,
                conversation_id=action.conversation_id,
                dialogue_state=previous_dialogue_state,
            )
            context["current_observation"] = observation
            context["input_origin"] = "pending_action_observation"
            content = [
                MessageContentItem(
                    type="text",
                    text=observation["text"],
                    source="pending_action_observation",
                )
            ]
            result = AgentRuntime(self.db).run(
                user_id=action.user_id,
                conversation_id=action.conversation_id,
                message_id=event_message_id,
                content=content,
                context=context,
            )
            assistant_created_at = utc_now()
            assistant_message = ConversationMessage(
                id=new_id("msg"),
                conversation_id=action.conversation_id,
                user_id=action.user_id,
                role="assistant",
                content_json=result.get("assistant_content")
                or [{"type": "text", "text": result["assistant_text"]}],
                intent=result["intent"],
                requires_review=result["requires_review"],
                created_at=assistant_created_at,
            )
            conversation.dialogue_state_json = update_dialogue_state_after_assistant(
                previous_dialogue_state,
                assistant_text=result["assistant_text"],
                assistant_message_id=assistant_message.id,
                created_at=assistant_created_at,
                dialogue_state_patch=result.get("dialogue_state_patch"),
            )
            conversation.dialogue_state_updated_at = utc_now()
            self.db.add(assistant_message)
            self.db.commit()
            response = {
                "assistant_message_id": assistant_message.id,
                "assistant_text": result["assistant_text"],
                "intent": result["intent"],
                "requires_review": result["requires_review"],
                "pending_actions": result["pending_actions"],
                "committed_records": result["committed_records"],
                "tool_results": result.get("tool_results", []),
            }
            if include_agent_trace:
                response["agent_trace"] = result.get("agent_trace", [])
            return response
        except AppError as exc:
            logger.warning(
                "agent_continuation_failed pending_action_id=%s code=%s",
                action.id,
                exc.code,
            )
            return None

    def _add_action_event(
        self,
        action: AgentPendingAction,
        event_type: str,
        text: str,
        record_type: str | None = None,
        record_id: str | None = None,
    ) -> ConversationMessage:
        content: dict[str, Any] = {
            "type": "event",
            "event_type": event_type,
            "text": text,
            "pending_action_id": action.id,
        }
        if record_type:
            content["record_type"] = record_type
        if record_id:
            content["record_id"] = record_id
        message = ConversationMessage(
            id=new_id("msg"),
            conversation_id=action.conversation_id,
            user_id=action.user_id,
            role="assistant",
            content_json=[content],
            intent="fitness_record",
            requires_review=False,
            created_at=utc_now(),
        )
        self.db.add(message)
        return message

    def _record_committed_text(self, record_type: str, record: dict) -> str:
        if record_type == "meal":
            meal_label = self._meal_type_label(record.get("meal_type"))
            item_text = self._meal_items_text(record.get("items") or [])
            total = record.get("total_calories")
            total_text = f"，约 {total:g} 千卡" if isinstance(total, (int, float)) else ""
            if item_text:
                return f"已保存到正式记录：{meal_label}，{item_text}{total_text}。"
            return f"已保存到正式记录：{meal_label}{total_text}。"

        parts = []
        if record.get("weight_kg") is not None:
            parts.append(f"体重 {record['weight_kg']:g}kg")
        if record.get("body_fat_percentage") is not None:
            parts.append(f"体脂 {record['body_fat_percentage']:g}%")
        if record.get("bmi") is not None:
            parts.append(f"BMI {record['bmi']:g}")
        detail = "，".join(parts) if parts else "身体指标"
        return f"已保存到正式记录：{detail}。"

    def _meal_items_text(self, items: list[dict]) -> str:
        parts = []
        for item in items[:5]:
            name = item.get("name")
            if not name:
                continue
            portion = item.get("portion_text")
            parts.append(f"{name}（{portion}）" if portion else str(name))
        if len(items) > 5:
            parts.append(f"等 {len(items)} 项")
        return "、".join(parts)

    def _meal_type_label(self, meal_type: str | None) -> str:
        return {
            "breakfast": "早餐",
            "lunch": "午餐",
            "dinner": "晚餐",
            "snack": "加餐",
            "unknown": "餐食",
        }.get(meal_type or "unknown", "餐食")


def get_pending_action_service(
    db: Annotated[Session, Depends(get_db)],
) -> PendingActionService:
    return PendingActionService(db)
