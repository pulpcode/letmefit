from datetime import date, datetime
from decimal import Decimal

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


def test_estimate_tokens_returns_small_positive_number() -> None:
    assert estimate_tokens("今天午餐吃了鸡胸肉") >= 1
    assert estimate_tokens("") == 0
