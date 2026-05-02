from typing import Annotated, Any

from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.draft_normalizer import normalize_pending_action_draft
from app.auth.security import utc_now
from app.core.database import get_db
from app.core.errors import AppError
from app.models import AgentPendingAction, Conversation
from app.schemas.pending_action import PendingActionUpdateRequest, decimal_to_float
from app.schemas.records import BodyMetricCreateRequest, MealCreateRequest
from app.services.body_metrics import BodyMetricService
from app.services.meals import MealService

EDITABLE_STATUSES = {"needs_clarification", "pending_confirmation"}


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
        return {"pending_actions": [self._response(action) for action in actions]}

    def update_action(
        self,
        user_id: str,
        pending_action_id: str,
        payload: PendingActionUpdateRequest,
    ) -> dict:
        action = self._get_owned_action(user_id, pending_action_id)
        self._ensure_editable(action)
        draft_payload = dict(action.draft_payload_json)
        draft_payload.update(payload.draft_payload)
        if payload.user_note:
            draft_payload["user_note"] = payload.user_note
        action.draft_payload_json = draft_payload
        action.status = "pending_confirmation"
        self.db.commit()
        self.db.refresh(action)
        return self._response(action)

    def confirm_action(self, user_id: str, pending_action_id: str) -> dict:
        action = self._get_owned_action(user_id, pending_action_id)
        self._ensure_editable(action)
        if action.action_type == "create_meal_record":
            record = self._commit_meal(user_id, action)
            record_type = "meal"
        elif action.action_type == "create_body_metric_record":
            record = self._commit_body_metric(user_id, action)
            record_type = "body_metric"
        else:
            raise AppError("VALIDATION_ERROR", "该待确认动作暂不支持确认写入", status_code=422)

        action.status = "committed"
        action.confirmed_at = utc_now()
        action.committed_record_type = record_type
        action.committed_record_id = record["id"]
        self.db.commit()
        return {
            "pending_action_id": action.id,
            "status": action.status,
            "record_type": record_type,
            "record_id": record["id"],
        }

    def discard_action(self, user_id: str, pending_action_id: str) -> dict:
        action = self._get_owned_action(user_id, pending_action_id)
        self._ensure_editable(action)
        action.status = "discarded"
        self.db.commit()
        return {
            "pending_action_id": action.id,
            "status": action.status,
        }

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
        return MealService(self.db).create_meal(user_id, payload)

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
        return BodyMetricService(self.db).create_body_metric(user_id, payload)

    def _draft_with_source(self, action: AgentPendingAction) -> dict[str, Any]:
        draft_payload = normalize_pending_action_draft(
            action.action_type,
            action.draft_payload_json,
        )
        draft_payload["source_pending_action_id"] = action.id
        return draft_payload

    def _ensure_owned_conversation(self, user_id: str, conversation_id: str) -> None:
        conversation = self.db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if not conversation:
            raise AppError("RESOURCE_NOT_FOUND", "会话不存在", status_code=404)

    def _get_owned_action(self, user_id: str, pending_action_id: str) -> AgentPendingAction:
        action = self.db.scalar(
            select(AgentPendingAction).where(
                AgentPendingAction.id == pending_action_id,
                AgentPendingAction.user_id == user_id,
            )
        )
        if not action:
            raise AppError("RESOURCE_NOT_FOUND", "待确认动作不存在", status_code=404)
        return action

    def _ensure_editable(self, action: AgentPendingAction) -> None:
        if action.status not in EDITABLE_STATUSES:
            raise AppError("VALIDATION_ERROR", "待确认动作已处理，不能再次修改", status_code=422)

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
        }


def get_pending_action_service(
    db: Annotated[Session, Depends(get_db)],
) -> PendingActionService:
    return PendingActionService(db)
