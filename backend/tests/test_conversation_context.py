from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.auth.security import utc_now
from app.core.config import Settings
from app.models import BodyMetricRecord, ConversationMessage, MealItem, MealRecord
from app.services.conversation_context import (
    ConversationContextBuilder,
    ConversationSummaryService,
    content_preview,
    content_types,
    estimate_tokens,
)


def _message(message_id: str, role: str, text: str, requires_review: bool = False):
    return ConversationMessage(
        id=message_id,
        conversation_id="conv_test",
        user_id="user_test",
        role=role,
        content_json=[{"type": "text", "text": text}],
        intent="fitness_record" if requires_review else None,
        requires_review=requires_review,
        created_at=datetime(2026, 5, 1, 12, 0, 0),
    )


def test_content_preview_handles_multimodal_message() -> None:
    preview = content_preview(
        [
            {"type": "text", "text": "午餐吃了鸡胸肉"},
            {"type": "image", "file_id": "file_test"},
            {"type": "audio", "duration_seconds": 8},
        ]
    )

    assert preview == "午餐吃了鸡胸肉 [image] [audio 8s]"


def test_content_preview_handles_backend_events() -> None:
    preview = content_preview(
        [
            {
                "type": "event",
                "event_type": "record_committed",
                "text": "已保存到正式记录：早餐，鸡蛋（2个）。",
            }
        ]
    )

    assert preview == "已保存到正式记录：早餐，鸡蛋（2个）。"


def test_content_types_returns_unique_sorted_types() -> None:
    types = content_types(
        [
            {"type": "audio", "file_id": "file_audio"},
            {"type": "text", "text": "语音转写: 早餐吃了鸡蛋"},
            {"type": "text", "text": "补充说明"},
        ]
    )

    assert types == ["audio", "text"]


def test_meal_record_context_includes_confirmed_items() -> None:
    builder = ConversationContextBuilder(
        db=object(),
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )
    meal = MealRecord(
        id="meal_test",
        user_id="user_test",
        recorded_at=datetime(2026, 5, 1, 0, 0, 0),
        recorded_tz="Asia/Shanghai",
        local_date=date(2026, 5, 1),
        source_type="voice",
        meal_type="breakfast",
        total_calories=Decimal("156"),
        total_protein_g=Decimal("12.6"),
        total_carbs_g=Decimal("1.2"),
        total_fat_g=Decimal("10.4"),
        confidence=Decimal("0.82"),
        source_pending_action_id="pa_test",
        notes="语音确认",
    )
    item = MealItem(
        id="mi_test",
        meal_record_id="meal_test",
        display_order=0,
        name="鸡蛋",
        portion_text="2个",
        calories=Decimal("156"),
        protein_g=Decimal("12.6"),
        user_corrected=True,
    )

    context = builder._meal_record_context(meal, [item])

    assert context["source_type"] == "voice"
    assert context["source_pending_action_id"] == "pa_test"
    assert context["total_carbs_g"] == 1.2
    assert context["items"][0]["name"] == "鸡蛋"
    assert context["items"][0]["portion_text"] == "2个"
    assert context["items"][0]["user_corrected"] is True


def test_body_metric_context_includes_confirmed_fields() -> None:
    builder = ConversationContextBuilder(
        db=object(),
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )
    record = BodyMetricRecord(
        id="bm_test",
        user_id="user_test",
        recorded_at=datetime(2026, 5, 1, 8, 0, 0),
        recorded_tz="Asia/Shanghai",
        local_date=date(2026, 5, 1),
        source_type="voice",
        weight_kg=Decimal("72.4"),
        body_fat_percentage=Decimal("18.6"),
        bmi=Decimal("23.1"),
        muscle_mass_kg=Decimal("54.2"),
        water_percentage=Decimal("55.0"),
        confidence=Decimal("0.8"),
        source_pending_action_id="pa_metric",
    )

    context = builder._body_metric_context(record)

    assert context["source_type"] == "voice"
    assert context["weight_kg"] == 72.4
    assert context["bmi"] == 23.1
    assert context["source_pending_action_id"] == "pa_metric"


def test_compose_summary_marks_non_authoritative_context() -> None:
    service = ConversationSummaryService(
        db=object(),
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )

    summary = service.compose_summary(
        previous_summary_text="此前用户确认过早餐。",
        messages=[
            _message("msg_1", "user", "今天午餐吃了鸡胸肉", requires_review=True),
            _message("msg_2", "assistant", "我整理成一条餐食草稿，请确认。"),
        ],
        max_chars=500,
    )

    assert "正式事实以档案和记录表为准" in summary
    assert "此前用户确认过早餐" in summary
    assert "用户: 今天午餐吃了鸡胸肉；需用户确认" in summary
    assert "助手: 我整理成一条餐食草稿，请确认。" in summary


def test_message_context_serializes_created_at() -> None:
    builder = ConversationContextBuilder(
        db=object(),
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )

    context = builder._message_context(_message("msg_1", "user", "午餐"))

    assert context["created_at"] == "2026-05-01T12:00:00"
    assert context["content_preview"] == "午餐"
    assert context["content_types"] == ["text"]
    assert "content" not in context


def test_full_message_context_keeps_original_content() -> None:
    builder = ConversationContextBuilder(
        db=object(),
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )

    message = _message("msg_1", "assistant", "需要我帮你规划晚餐吗？")
    context = builder._full_message_context(message)

    assert context["content"] == [{"type": "text", "text": "需要我帮你规划晚餐吗？"}]
    assert context["content_preview"] == "需要我帮你规划晚餐吗？"


def test_pending_action_context_limits_recent_active_actions() -> None:
    now = utc_now()

    class FakeDb:
        def scalar(self, query):
            return 4

        def scalars(self, query):
            if not hasattr(self, "calls"):
                self.calls = 0
            self.calls += 1
            if self.calls == 1:
                return []
            return [
                SimpleNamespace(
                    id=f"pa_{index}",
                    action_type="create_meal_record",
                    status="pending_confirmation",
                    draft_payload_json={
                        "meal_type": "lunch",
                        "items": [{"name": f"食物{index}", "portion_text": "100g"}],
                    },
                    warnings_json=[],
                    expires_at=now + timedelta(hours=1),
                )
                for index in range(3)
            ]

    builder = ConversationContextBuilder(
        db=FakeDb(),
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )

    context = builder._pending_action_context("user_test", "conv_test")

    assert len(context["active_pending_actions"]) == 3
    assert context["active_pending_actions"][0]["display_index"] == 1
    assert "draft_payload" not in context["active_pending_actions"][0]
    assert context["active_pending_actions_overflow_count"] == 1
    assert "还有 1 条" in context["active_pending_actions_overflow_hint"]


def test_pending_action_context_includes_workout_summary() -> None:
    now = utc_now()

    class FakeDb:
        def scalar(self, query):
            return 1

        def scalars(self, query):
            if not hasattr(self, "calls"):
                self.calls = 0
            self.calls += 1
            if self.calls == 1:
                return []
            return [
                SimpleNamespace(
                    id="pa_workout",
                    action_type="create_workout_record",
                    status="pending_confirmation",
                    draft_payload_json={
                        "recorded_at": "2026-05-01T19:30:00+08:00",
                        "source_type": "text",
                        "workout_type": "跑步",
                        "duration_minutes": 30,
                        "intensity": "moderate",
                    },
                    warnings_json=[],
                    expires_at=now + timedelta(hours=1),
                )
            ]

    builder = ConversationContextBuilder(
        db=FakeDb(),
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )

    context = builder._pending_action_context("user_test", "conv_test")
    action = context["active_pending_actions"][0]

    assert action["type"] == "create_workout_record"
    assert action["title"] == "跑步"
    assert action["editable_fields"]["duration_minutes"] == 30


def test_pending_action_context_expires_stale_actions() -> None:
    expired = SimpleNamespace(
        id="pa_old",
        action_type="create_meal_record",
        status="pending_confirmation",
        draft_payload_json={},
        warnings_json=[],
        expires_at=utc_now() - timedelta(minutes=1),
    )

    class FakeDb:
        def __init__(self) -> None:
            self.flush_count = 0
            self.scalars_count = 0

        def scalar(self, query):
            return 0

        def scalars(self, query):
            self.scalars_count += 1
            return [expired] if self.scalars_count == 1 else []

        def flush(self):
            self.flush_count += 1

    db = FakeDb()
    builder = ConversationContextBuilder(
        db=db,
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )

    context = builder._pending_action_context("user_test", "conv_test")

    assert expired.status == "expired"
    assert db.flush_count == 1
    assert context["active_pending_actions"] == []


def test_estimate_tokens_returns_small_positive_number() -> None:
    assert estimate_tokens("今天午餐吃了鸡胸肉") >= 1
    assert estimate_tokens("") == 0
