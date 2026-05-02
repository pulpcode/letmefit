from datetime import datetime

from app.core.config import Settings
from app.models import ConversationMessage
from app.services.conversation_context import (
    ConversationContextBuilder,
    ConversationSummaryService,
    content_preview,
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


def test_estimate_tokens_returns_small_positive_number() -> None:
    assert estimate_tokens("今天午餐吃了鸡胸肉") >= 1
    assert estimate_tokens("") == 0
