from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
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
from app.services.pending_action_lifecycle import (
    ACTIVE_PENDING_ACTION_STATUSES,
    CONTEXT_PENDING_ACTION_LIMIT,
    EXPIRED,
    pending_action_context_summary,
)

ACTIVE_SUMMARY_JOB_STATUSES = {"pending", "running"}
PENDING_SUMMARY_JOB_STATUS = "pending"
RUNNING_SUMMARY_JOB_STATUS = "running"
SUCCEEDED_SUMMARY_STATUS = "succeeded"
FAILED_SUMMARY_STATUS = "failed"
CONTEXT_RECORD_LIMIT = 5
LOCAL_SUMMARY_MODEL_NAME = "local_compose_summary_v1"
_SUMMARY_HEADER = "滚动摘要，用于后续模型上下文；正式事实以档案和记录表为准。"


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
        active_job = self._active_summary_job(user_id, conversation_id)

        messages_after = self._messages_after_summary(messages, latest_summary)
        if active_job:
            short_term = [m for m in messages_after if m.id != exclude_message_id]
        else:
            short_term = self._short_term_messages_by_token(messages_after, exclude_message_id)

        return {
            "memory_policy": {
                "summary_mode": "async_rolling",
                "keep_tokens": self.settings.conversation_summary_keep_tokens,
                "summary_pending": active_job is not None,
            },
            "profile": self._profile_context(user_id),
            "latest_conversation_summary": self._summary_context(latest_summary),
            "short_term_messages": [
                self._full_message_context(message) for message in short_term
            ],
            **self._pending_action_context(user_id, conversation_id),
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
                ConversationSummary.status == SUCCEEDED_SUMMARY_STATUS,
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

    def _active_summary_job(
        self,
        user_id: str,
        conversation_id: str,
    ) -> ConversationSummary | None:
        return self.db.scalar(
            select(ConversationSummary)
            .where(
                ConversationSummary.user_id == user_id,
                ConversationSummary.conversation_id == conversation_id,
                ConversationSummary.status.in_(ACTIVE_SUMMARY_JOB_STATUSES),
            )
            .order_by(ConversationSummary.created_at.desc())
            .limit(1)
        )

    def _short_term_messages_by_token(
        self,
        messages: list[ConversationMessage],
        exclude_message_id: str | None,
    ) -> list[ConversationMessage]:
        filtered = [m for m in messages if m.id != exclude_message_id]
        keep_tokens = max(1, self.settings.conversation_summary_keep_tokens)
        selected: list[ConversationMessage] = []
        accumulated = 0
        for msg in reversed(filtered):
            msg_tokens = _estimate_message_tokens(msg)
            if accumulated + msg_tokens > keep_tokens and selected:
                break
            selected.insert(0, msg)
            accumulated += msg_tokens
        return selected

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
            "summary_type": summary.summary_type,
            "status": summary.status,
            "summary_text": summary.summary_text,
            "summary_json": summary.summary_json,
            "token_estimate": summary.token_estimate,
            "model_name": summary.model_name,
            "created_at": _iso_or_none(summary.created_at),
            "updated_at": _iso_or_none(summary.updated_at),
        }

    def _full_message_context(self, message: ConversationMessage) -> dict[str, Any]:
        return {
            "id": message.id,
            "role": message.role,
            "content": message.content_json,
            "content_preview": content_preview(message.content_json),
            "content_types": content_types(message.content_json),
            "intent": message.intent,
            "requires_review": message.requires_review,
            "created_at": _iso_or_none(message.created_at),
        }

    def _pending_action_context(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        now = utc_now()
        expired_actions = list(
            self.db.scalars(
                select(AgentPendingAction)
                .where(
                    AgentPendingAction.user_id == user_id,
                    AgentPendingAction.conversation_id == conversation_id,
                    AgentPendingAction.status.in_(ACTIVE_PENDING_ACTION_STATUSES),
                    AgentPendingAction.expires_at.is_not(None),
                    AgentPendingAction.expires_at <= now,
                )
                .limit(100)
            )
        )
        for action in expired_actions:
            action.status = EXPIRED

        active_query = (
            select(AgentPendingAction)
            .where(
                AgentPendingAction.user_id == user_id,
                AgentPendingAction.conversation_id == conversation_id,
                AgentPendingAction.status.in_(ACTIVE_PENDING_ACTION_STATUSES),
                (
                    AgentPendingAction.expires_at.is_(None)
                    | (AgentPendingAction.expires_at > now)
                ),
            )
            .order_by(AgentPendingAction.created_at.desc())
        )
        active_count = self.db.scalar(
            select(func.count())
            .select_from(AgentPendingAction)
            .where(
                AgentPendingAction.user_id == user_id,
                AgentPendingAction.conversation_id == conversation_id,
                AgentPendingAction.status.in_(ACTIVE_PENDING_ACTION_STATUSES),
                (
                    AgentPendingAction.expires_at.is_(None)
                    | (AgentPendingAction.expires_at > now)
                ),
            )
        ) or 0
        actions = list(self.db.scalars(active_query.limit(CONTEXT_PENDING_ACTION_LIMIT)))
        overflow_count = max(0, active_count - CONTEXT_PENDING_ACTION_LIMIT)
        if expired_actions:
            self.db.flush()
        return {
            "active_pending_actions": [
                pending_action_context_summary(action, display_index=index)
                for index, action in enumerate(actions, start=1)
            ],
            "active_pending_actions_overflow_count": overflow_count,
            "active_pending_actions_overflow_hint": (
                f"还有 {overflow_count} 条待确认记录未注入上下文；"
                "如需处理，请让用户查看更多待确认记录。"
                if overflow_count
                else None
            ),
        }

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

        trigger_tokens = max(1, self.settings.conversation_summary_trigger_tokens)
        total_tokens = sum(_estimate_message_tokens(m) for m in messages_after_summary)
        if total_tokens <= trigger_tokens:
            return latest_summary

        to_keep = self.context_builder._short_term_messages_by_token(messages_after_summary, None)
        messages_to_summarize = messages_after_summary[: len(messages_after_summary) - len(to_keep)]
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
            from_message_id=messages_to_summarize[0].id,
            to_message_id=messages_to_summarize[-1].id,
            summary_type="rolling",
            status=SUCCEEDED_SUMMARY_STATUS,
            summary_text=summary_text,
            summary_json=None,
            token_estimate=estimate_tokens(summary_text),
            model_name=None,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.db.add(summary)
        self.db.flush()
        return summary

    def enqueue_if_needed(
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

        trigger_tokens = max(1, self.settings.conversation_summary_trigger_tokens)
        total_tokens = sum(_estimate_message_tokens(m) for m in messages_after_summary)
        if total_tokens <= trigger_tokens:
            return None

        to_keep = self.context_builder._short_term_messages_by_token(messages_after_summary, None)
        messages_to_summarize = messages_after_summary[: len(messages_after_summary) - len(to_keep)]
        if not messages_to_summarize:
            return None

        existing_job = self._active_summary_job(user_id, conversation_id)
        if existing_job:
            return existing_job

        now = utc_now()
        job = ConversationSummary(
            id=new_id("conv_sum"),
            conversation_id=conversation_id,
            user_id=user_id,
            from_message_id=messages_to_summarize[0].id,
            to_message_id=messages_to_summarize[-1].id,
            summary_type="rolling",
            status=PENDING_SUMMARY_JOB_STATUS,
            summary_text="",
            summary_json=None,
            token_estimate=None,
            model_name=None,
            created_at=now,
            updated_at=now,
        )
        self.db.add(job)
        self.db.flush()
        return job

    def _active_summary_job(
        self,
        user_id: str,
        conversation_id: str,
    ) -> ConversationSummary | None:
        return self.db.scalar(
            select(ConversationSummary)
            .where(
                ConversationSummary.user_id == user_id,
                ConversationSummary.conversation_id == conversation_id,
                ConversationSummary.status.in_(ACTIVE_SUMMARY_JOB_STATUSES),
            )
            .order_by(ConversationSummary.created_at.desc())
            .limit(1)
        )

    def pending_jobs(self, limit: int = 10) -> list[ConversationSummary]:
        job_ids = self.pending_job_ids(limit=limit)
        if not job_ids:
            return []
        return list(
            self.db.scalars(
                select(ConversationSummary)
                .where(ConversationSummary.id.in_(job_ids))
                .order_by(ConversationSummary.created_at.asc())
            )
        )

    def pending_job_ids(self, limit: int = 10) -> list[str]:
        job_limit = max(1, limit)
        return list(
            self.db.scalars(
                select(ConversationSummary.id)
                .where(ConversationSummary.status == PENDING_SUMMARY_JOB_STATUS)
                .order_by(ConversationSummary.created_at.asc())
                .limit(job_limit)
            )
        )

    def process_pending_jobs(self, limit: int = 10, commit: bool = True) -> dict[str, int]:
        stats = {"processed": 0, "claimed": 0, "succeeded": 0, "failed": 0, "recovered": 0}
        stats["recovered"] = self.recover_stale_running_jobs()
        if commit and stats["recovered"]:
            self.db.commit()

        for job_id in self.pending_job_ids(limit=limit):
            job = self.claim_pending_job(job_id)
            if not job:
                continue
            stats["processed"] += 1
            stats["claimed"] += 1
            if commit:
                self.db.commit()
            if self.process_job(job):
                stats["succeeded"] += 1
            else:
                stats["failed"] += 1
            if commit:
                self.db.commit()
        return stats

    def claim_pending_job(self, job_id: str) -> ConversationSummary | None:
        now = utc_now()
        result = self.db.execute(
            update(ConversationSummary)
            .where(
                ConversationSummary.id == job_id,
                ConversationSummary.status == PENDING_SUMMARY_JOB_STATUS,
            )
            .values(status=RUNNING_SUMMARY_JOB_STATUS, updated_at=now)
        )
        self.db.flush()
        if (result.rowcount or 0) != 1:
            return None
        return self.db.scalar(select(ConversationSummary).where(ConversationSummary.id == job_id))

    def recover_stale_running_jobs(self) -> int:
        timeout = max(1, self.settings.conversation_summary_running_timeout_seconds)
        cutoff = utc_now() - timedelta(seconds=timeout)
        now = utc_now()
        result = self.db.execute(
            update(ConversationSummary)
            .where(
                ConversationSummary.status == RUNNING_SUMMARY_JOB_STATUS,
                ConversationSummary.updated_at < cutoff,
            )
            .values(
                status=PENDING_SUMMARY_JOB_STATUS,
                summary_json={"recovered_from": "running", "reason": "running_timeout"},
                updated_at=now,
            )
        )
        self.db.flush()
        return result.rowcount or 0

    def process_job(self, job: ConversationSummary) -> bool:
        if job.status != PENDING_SUMMARY_JOB_STATUS:
            if job.status != RUNNING_SUMMARY_JOB_STATUS:
                return False
        else:
            job.status = RUNNING_SUMMARY_JOB_STATUS
            job.updated_at = utc_now()
            self.db.flush()


        previous_summary = self._previous_succeeded_summary(job)
        messages = self._messages_for_summary_job(job)
        if not messages:
            self._fail_job(job, "summary_job_messages_not_found")
            return False

        prev_text = previous_summary.summary_text if previous_summary else None
        max_chars = self.settings.conversation_summary_max_chars

        llm_content = self._llm_summarize(
            previous_summary_text=prev_text,
            messages=messages,
            max_chars=max_chars,
        )
        if llm_content is not None:
            summary_text = truncate_text(f"{_SUMMARY_HEADER}\n{llm_content}", max_chars)
            used_model = self.settings.summary_llm_model
        else:
            summary_text = self.compose_summary(
                previous_summary_text=prev_text,
                messages=messages,
                max_chars=max_chars,
            )
            used_model = LOCAL_SUMMARY_MODEL_NAME

        job.status = SUCCEEDED_SUMMARY_STATUS
        job.summary_text = summary_text
        job.summary_json = {
            "message_count": len(messages),
            "from_message_id": job.from_message_id,
            "to_message_id": job.to_message_id,
            "method": used_model,
        }
        job.token_estimate = estimate_tokens(summary_text)
        job.model_name = used_model
        job.updated_at = utc_now()
        self.db.flush()
        return True

    def _fail_job(self, job: ConversationSummary, reason: str) -> None:
        job.status = FAILED_SUMMARY_STATUS
        job.summary_json = {"error": reason}
        job.updated_at = utc_now()
        self.db.flush()

    def _previous_succeeded_summary(
        self,
        job: ConversationSummary,
    ) -> ConversationSummary | None:
        return self.db.scalar(
            select(ConversationSummary)
            .where(
                ConversationSummary.user_id == job.user_id,
                ConversationSummary.conversation_id == job.conversation_id,
                ConversationSummary.status == SUCCEEDED_SUMMARY_STATUS,
                ConversationSummary.created_at < job.created_at,
            )
            .order_by(ConversationSummary.created_at.desc())
            .limit(1)
        )

    def _messages_for_summary_job(
        self,
        job: ConversationSummary,
    ) -> list[ConversationMessage]:
        messages = self.context_builder._conversation_messages(job.user_id, job.conversation_id)
        from_index = None
        to_index = None
        for index, message in enumerate(messages):
            if message.id == job.from_message_id:
                from_index = index
            if message.id == job.to_message_id:
                to_index = index
        if from_index is None or to_index is None or to_index < from_index:
            return []
        return messages[from_index : to_index + 1]

    def _llm_summarize(
        self,
        previous_summary_text: str | None,
        messages: list[ConversationMessage],
        max_chars: int,
    ) -> str | None:
        if not self.settings.summary_llm_enabled:
            return None
        api_key = self.settings.bailian_api_key or self.settings.dashscope_api_key
        if not api_key:
            return None

        lines = []
        for msg in messages:
            role = "用户" if msg.role == "user" else "助手"
            suffix = "（待确认）" if msg.requires_review else ""
            lines.append(f"{role}: {content_preview(msg.content_json)}{suffix}")
        dialogue_text = "\n".join(lines)

        user_content = ""
        if previous_summary_text:
            user_content += f"此前摘要:\n{previous_summary_text}\n\n"
        user_content += f"最新对话:\n{dialogue_text}"

        system_prompt = (
            "你是 LetMeFit 健身助手的对话摘要模块。"
            "请将用户提供的对话（可能包含此前摘要和最新对话）合并压缩为简洁中文摘要。"
            "保留：已确认的饮食/体重记录的关键数字、用户的明确意图、待确认记录（标注'待确认'）。"
            "删除：寒暄、重复追问、冗余解释。"
            f"输出纯文本，不超过 {max(100, max_chars - 50)} 字，不要 Markdown、不要 JSON。"
        )

        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url=self.settings.bailian_base_url,
                timeout=20,
                max_retries=0,
            )
            completion = client.chat.completions.create(
                model=self.settings.summary_llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                max_tokens=600,
            )
            content = completion.choices[0].message.content if completion.choices else None
            if isinstance(content, str) and content.strip():
                return content.strip()
            return None
        except Exception:
            return None

    def compose_summary(
        self,
        previous_summary_text: str | None,
        messages: list[ConversationMessage],
        max_chars: int,
    ) -> str:
        header = _SUMMARY_HEADER
        message_lines = []
        for message in messages:
            role = "用户" if message.role == "user" else "助手"
            suffix = "；需用户确认" if message.requires_review else ""
            message_lines.append(f"{role}: {content_preview(message.content_json)}{suffix}")
        new_content = "\n".join(message_lines)

        if not previous_summary_text:
            base = f"{header}\n{new_content}" if new_content else header
            return truncate_text(base, max_chars)

        prev_prefix = "此前摘要: "
        # Budget for previous summary = total - header - new messages - separators - prefix
        base_len = len(header) + (len("\n") + len(new_content) if new_content else 0)
        budget = max_chars - base_len - len("\n") - len(prev_prefix)

        if budget <= 20:
            base = f"{header}\n{new_content}" if new_content else header
            return truncate_text(base, max_chars)

        # Keep the tail of previous summary (most recent content first)
        if len(previous_summary_text) > budget:
            prev_text = "…" + previous_summary_text[-(budget - 1):]
        else:
            prev_text = previous_summary_text

        parts = [header, f"{prev_prefix}{prev_text}"]
        if new_content:
            parts.append(new_content)
        return "\n".join(parts)


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
    chinese = sum(1 for c in value if "一" <= c <= "鿿")
    other = len(value) - chinese
    return max(1, int(chinese * 1.5 + other / 4))


def _estimate_message_tokens(message: ConversationMessage) -> int:
    content = message.content_json
    if isinstance(content, list):
        text = " ".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict)
        )
    else:
        text = str(content or "")
    return estimate_tokens(text)


def _float_or_none(value: Any) -> float | None:
    return float(value) if value is not None else None


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
