from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import new_id, utc_now
from app.core.config import Settings, get_settings
from app.models import (
    AgentPendingAction,
    BodyMetricRecord,
    ConversationMessage,
    ConversationSummary,
    MealItem,
    MealRecord,
    UserProfile,
)

ACTIVE_PENDING_ACTION_STATUSES = {"needs_clarification", "pending_confirmation"}
CONTEXT_RECORD_LIMIT = 5
CONTEXT_PENDING_ACTION_LIMIT = 10


class ConversationContextBuilder:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def build(
        self,
        user_id: str,
        conversation_id: str,
        exclude_message_id: str | None = None,
    ) -> dict[str, Any]:
        latest_summary = self.latest_summary(user_id, conversation_id)
        messages = self._conversation_messages(user_id, conversation_id)
        recent_messages = self._recent_messages_after_summary(
            messages=messages,
            latest_summary=latest_summary,
            exclude_message_id=exclude_message_id,
        )

        return {
            "policy": {
                "summary_mode": "rolling",
                "recent_message_limit": self.settings.conversation_context_recent_messages,
            },
            "profile": self._profile_context(user_id),
            "conversation_summary": self._summary_context(latest_summary),
            "recent_messages": [self._message_context(message) for message in recent_messages],
            "active_pending_actions": self._pending_action_context(user_id, conversation_id),
            "recent_records": self._recent_records_context(user_id),
        }

    def latest_summary(
        self,
        user_id: str,
        conversation_id: str,
    ) -> ConversationSummary | None:
        return self.db.scalar(
            select(ConversationSummary)
            .where(
                ConversationSummary.user_id == user_id,
                ConversationSummary.conversation_id == conversation_id,
            )
            .order_by(ConversationSummary.created_at.desc())
            .limit(1)
        )

    def _conversation_messages(
        self,
        user_id: str,
        conversation_id: str,
    ) -> list[ConversationMessage]:
        return list(
            self.db.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.user_id == user_id,
                    ConversationMessage.conversation_id == conversation_id,
                )
                .order_by(ConversationMessage.created_at.asc())
            )
        )

    def _recent_messages_after_summary(
        self,
        messages: list[ConversationMessage],
        latest_summary: ConversationSummary | None,
        exclude_message_id: str | None,
    ) -> list[ConversationMessage]:
        messages_after_summary = self._messages_after_summary(messages, latest_summary)
        filtered_messages = [
            message for message in messages_after_summary if message.id != exclude_message_id
        ]
        recent_limit = max(1, self.settings.conversation_context_recent_messages)
        return filtered_messages[-recent_limit:]

    def _messages_after_summary(
        self,
        messages: list[ConversationMessage],
        latest_summary: ConversationSummary | None,
    ) -> list[ConversationMessage]:
        if not latest_summary:
            return messages
        for index, message in enumerate(messages):
            if message.id == latest_summary.to_message_id:
                return messages[index + 1 :]
        return messages

    def _profile_context(self, user_id: str) -> dict[str, Any] | None:
        profile = self.db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        if not profile:
            return None
        return {
            "age": profile.age,
            "sex": profile.sex,
            "height_cm": _float_or_none(profile.height_cm),
            "current_weight_kg": _float_or_none(profile.current_weight_kg),
            "target_weight_kg": _float_or_none(profile.target_weight_kg),
            "activity_level": profile.activity_level,
            "goal_type": profile.goal_type,
            "profile_completed": profile.completed_at is not None,
        }

    def _summary_context(self, summary: ConversationSummary | None) -> dict[str, Any] | None:
        if not summary:
            return None
        return {
            "id": summary.id,
            "from_message_id": summary.from_message_id,
            "to_message_id": summary.to_message_id,
            "summary_text": summary.summary_text,
            "token_estimate": summary.token_estimate,
            "created_at": _iso_or_none(summary.created_at),
        }

    def _message_context(self, message: ConversationMessage) -> dict[str, Any]:
        return {
            "id": message.id,
            "role": message.role,
            "content_preview": content_preview(message.content_json),
            "content_types": content_types(message.content_json),
            "intent": message.intent,
            "requires_review": message.requires_review,
            "created_at": _iso_or_none(message.created_at),
        }

    def _pending_action_context(self, user_id: str, conversation_id: str) -> list[dict[str, Any]]:
        actions = list(
            self.db.scalars(
                select(AgentPendingAction)
                .where(
                    AgentPendingAction.user_id == user_id,
                    AgentPendingAction.conversation_id == conversation_id,
                    AgentPendingAction.status.in_(ACTIVE_PENDING_ACTION_STATUSES),
                )
                .order_by(AgentPendingAction.created_at.asc())
                .limit(CONTEXT_PENDING_ACTION_LIMIT)
            )
        )
        return [
            {
                "pending_action_id": action.id,
                "type": action.action_type,
                "status": action.status,
                "draft_payload": action.draft_payload_json,
                "warnings": action.warnings_json or [],
            }
            for action in actions
        ]

    def _recent_records_context(self, user_id: str) -> dict[str, list[dict[str, Any]]]:
        meals = list(
            self.db.scalars(
                select(MealRecord)
                .where(MealRecord.user_id == user_id, MealRecord.deleted_at.is_(None))
                .order_by(MealRecord.recorded_at.desc())
                .limit(CONTEXT_RECORD_LIMIT)
            )
        )
        meal_items_by_id = self._meal_items_by_meal_id([meal.id for meal in meals])
        body_metrics = list(
            self.db.scalars(
                select(BodyMetricRecord)
                .where(
                    BodyMetricRecord.user_id == user_id,
                    BodyMetricRecord.deleted_at.is_(None),
                )
                .order_by(BodyMetricRecord.recorded_at.desc())
                .limit(CONTEXT_RECORD_LIMIT)
            )
        )
        return {
            "meals": [
                self._meal_record_context(meal, meal_items_by_id.get(meal.id, []))
                for meal in meals
            ],
            "body_metrics": [
                self._body_metric_context(record)
                for record in body_metrics
            ],
        }

    def _meal_items_by_meal_id(self, meal_ids: list[str]) -> dict[str, list[MealItem]]:
        if not meal_ids:
            return {}
        grouped: dict[str, list[MealItem]] = defaultdict(list)
        items = list(
            self.db.scalars(
                select(MealItem)
                .where(MealItem.meal_record_id.in_(meal_ids))
                .order_by(
                    MealItem.meal_record_id.asc(),
                    MealItem.display_order.asc(),
                    MealItem.created_at.asc(),
                )
            )
        )
        for item in items:
            grouped[item.meal_record_id].append(item)
        return grouped

    def _meal_record_context(self, meal: MealRecord, items: list[MealItem]) -> dict[str, Any]:
        return {
            "id": meal.id,
            "recorded_at": _iso_or_none(meal.recorded_at),
            "recorded_tz": meal.recorded_tz,
            "local_date": _iso_or_none(meal.local_date),
            "source_type": meal.source_type,
            "meal_type": meal.meal_type,
            "total_calories": _float_or_none(meal.total_calories),
            "total_protein_g": _float_or_none(meal.total_protein_g),
            "total_carbs_g": _float_or_none(meal.total_carbs_g),
            "total_fat_g": _float_or_none(meal.total_fat_g),
            "confidence": _float_or_none(meal.confidence),
            "source_pending_action_id": meal.source_pending_action_id,
            "notes": meal.notes,
            "items": [
                {
                    "name": item.name,
                    "alias": item.alias,
                    "portion_text": item.portion_text,
                    "portion_grams": _float_or_none(item.portion_grams),
                    "calories": _float_or_none(item.calories),
                    "protein_g": _float_or_none(item.protein_g),
                    "carbs_g": _float_or_none(item.carbs_g),
                    "fat_g": _float_or_none(item.fat_g),
                    "confidence": _float_or_none(item.confidence),
                    "user_corrected": item.user_corrected,
                }
                for item in items
            ],
        }

    def _body_metric_context(self, record: BodyMetricRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "recorded_at": _iso_or_none(record.recorded_at),
            "recorded_tz": record.recorded_tz,
            "local_date": _iso_or_none(record.local_date),
            "source_type": record.source_type,
            "weight_kg": _float_or_none(record.weight_kg),
            "body_fat_percentage": _float_or_none(record.body_fat_percentage),
            "bmi": _float_or_none(record.bmi),
            "muscle_mass_kg": _float_or_none(record.muscle_mass_kg),
            "water_percentage": _float_or_none(record.water_percentage),
            "confidence": _float_or_none(record.confidence),
            "source_pending_action_id": record.source_pending_action_id,
        }


class ConversationSummaryService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.context_builder = ConversationContextBuilder(db, self.settings)

    def compact_if_needed(
        self,
        user_id: str,
        conversation_id: str,
    ) -> ConversationSummary | None:
        latest_summary = self.context_builder.latest_summary(user_id, conversation_id)
        messages = self.context_builder._conversation_messages(user_id, conversation_id)
        messages_after_summary = self.context_builder._messages_after_summary(
            messages,
            latest_summary,
        )

        trigger_count = max(1, self.settings.conversation_summary_trigger_messages)
        if len(messages_after_summary) <= trigger_count:
            return latest_summary

        recent_limit = max(1, self.settings.conversation_context_recent_messages)
        messages_to_summarize = messages_after_summary[:-recent_limit]
        if not messages_to_summarize:
            return latest_summary

        summary_text = self.compose_summary(
            previous_summary_text=latest_summary.summary_text if latest_summary else None,
            messages=messages_to_summarize,
            max_chars=self.settings.conversation_summary_max_chars,
        )
        summary = ConversationSummary(
            id=new_id("conv_sum"),
            conversation_id=conversation_id,
            user_id=user_id,
            from_message_id=(
                latest_summary.from_message_id if latest_summary else messages_to_summarize[0].id
            ),
            to_message_id=messages_to_summarize[-1].id,
            summary_text=summary_text,
            token_estimate=estimate_tokens(summary_text),
            created_at=utc_now(),
        )
        self.db.add(summary)
        self.db.flush()
        return summary

    def compose_summary(
        self,
        previous_summary_text: str | None,
        messages: list[ConversationMessage],
        max_chars: int,
    ) -> str:
        lines = ["滚动摘要，用于后续模型上下文；正式事实以档案和记录表为准。"]
        if previous_summary_text:
            lines.append(f"此前摘要: {previous_summary_text}")
        for message in messages:
            role = "用户" if message.role == "user" else "助手"
            suffix = "；需用户确认" if message.requires_review else ""
            lines.append(f"{role}: {content_preview(message.content_json)}{suffix}")
        return truncate_text("\n".join(lines), max_chars)


def content_preview(content_json: Any, max_chars: int = 240) -> str:
    if not isinstance(content_json, list):
        return truncate_text(str(content_json), max_chars)

    parts = []
    for item in content_json:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        item_type = item.get("type")
        if item_type == "text":
            parts.append(str(item.get("text") or ""))
        elif item_type == "event":
            parts.append(str(item.get("text") or item.get("event_type") or "[event]"))
        elif item_type == "image":
            parts.append("[image]")
        elif item_type == "audio":
            duration = item.get("duration_seconds")
            parts.append(f"[audio {duration}s]" if duration is not None else "[audio]")
        else:
            parts.append(f"[{item_type or 'content'}]")
    return truncate_text(" ".join(part.strip() for part in parts if part), max_chars)


def content_types(content_json: Any) -> list[str]:
    if not isinstance(content_json, list):
        return []
    types = []
    for item in content_json:
        if isinstance(item, dict) and item.get("type"):
            types.append(str(item["type"]))
    return sorted(set(types))


def truncate_text(value: str, max_chars: int) -> str:
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 1]}..."


def estimate_tokens(value: str) -> int:
    if not value:
        return 0
    return max(1, len(value) // 4)


def _float_or_none(value: Any) -> float | None:
    return float(value) if value is not None else None


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
