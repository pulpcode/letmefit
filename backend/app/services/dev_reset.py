from typing import Annotated

from fastapi import Depends, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models import (
    AgentExtraction,
    AgentPendingAction,
    BodyMetricRecord,
    Conversation,
    ConversationMessage,
    ConversationSummary,
    DailyArchive,
    DailySummary,
    MealItem,
    MealRecord,
    MessageAttachment,
    UploadFile,
    UserMemory,
    UserProfile,
)

DEV_RESET_ENVIRONMENTS = {"local", "test"}


class DevResetService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def reset_current_user(self, user_id: str) -> dict:
        self._ensure_dev_environment()
        return self._reset_current_user(user_id, include_profile=False)

    def reset_current_user_full(self, user_id: str) -> dict:
        self._ensure_dev_environment()
        return self._reset_current_user(user_id, include_profile=True)

    def _reset_current_user(self, user_id: str, include_profile: bool) -> dict:
        deleted: dict[str, int] = {}
        try:
            meal_ids = select(MealRecord.id).where(MealRecord.user_id == user_id)
            message_ids = select(ConversationMessage.id).where(
                ConversationMessage.user_id == user_id
            )

            deleted["message_attachments"] = self._delete(
                delete(MessageAttachment).where(MessageAttachment.message_id.in_(message_ids))
            )
            deleted["daily_summaries"] = self._delete(
                delete(DailySummary).where(DailySummary.user_id == user_id)
            )
            deleted["daily_archives"] = self._delete(
                delete(DailyArchive).where(DailyArchive.user_id == user_id)
            )
            deleted["user_memories"] = self._delete(
                delete(UserMemory).where(UserMemory.user_id == user_id)
            )
            deleted["meal_items"] = self._delete(
                delete(MealItem).where(MealItem.meal_record_id.in_(meal_ids))
            )
            deleted["meal_records"] = self._delete(
                delete(MealRecord).where(MealRecord.user_id == user_id)
            )
            deleted["body_metric_records"] = self._delete(
                delete(BodyMetricRecord).where(BodyMetricRecord.user_id == user_id)
            )
            deleted["agent_pending_actions"] = self._delete(
                delete(AgentPendingAction).where(AgentPendingAction.user_id == user_id)
            )
            deleted["agent_extractions"] = self._delete(
                delete(AgentExtraction).where(AgentExtraction.user_id == user_id)
            )
            deleted["conversation_summaries"] = self._delete(
                delete(ConversationSummary).where(ConversationSummary.user_id == user_id)
            )
            deleted["conversation_messages"] = self._delete(
                delete(ConversationMessage).where(ConversationMessage.user_id == user_id)
            )
            deleted["conversations"] = self._delete(
                delete(Conversation).where(Conversation.user_id == user_id)
            )
            deleted["upload_files"] = self._delete(
                delete(UploadFile).where(UploadFile.user_id == user_id)
            )
            if include_profile:
                deleted["user_profiles"] = self._delete(
                    delete(UserProfile).where(UserProfile.user_id == user_id)
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        preserved = [
            "users",
            "refresh_sessions",
            "sms_verification_events",
        ]
        if not include_profile:
            preserved.append("user_profiles")

        return {
            "deleted": deleted,
            "preserved": preserved,
        }

    def _ensure_dev_environment(self) -> None:
        if self.settings.environment.lower() not in DEV_RESET_ENVIRONMENTS:
            raise AppError(
                "RESOURCE_NOT_FOUND",
                "接口不存在",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    def _delete(self, statement) -> int:
        result = self.db.execute(statement)
        if result.rowcount is None:
            return 0
        return max(int(result.rowcount), 0)


def get_dev_reset_service(
    db: Annotated[Session, Depends(get_db)],
) -> DevResetService:
    return DevResetService(db)
