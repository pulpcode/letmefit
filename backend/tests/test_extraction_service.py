from datetime import datetime
from decimal import Decimal

from app.ai.extraction_service import ExtractionService
from app.ai.providers.base import ExtractionProvider
from app.ai.types import (
    ActionGrounding,
    ExtractionInput,
    ExtractionProviderResult,
    ExtractionToolCall,
)
from app.core.config import Settings
from app.schemas.conversation import MessageContentItem


class FakeDb:
    def __init__(self) -> None:
        self.added = []
        self.flush_count = 0

    def add(self, value) -> None:
        self.added.append(value)

    def flush(self) -> None:
        self.flush_count += 1


class FakeProvider(ExtractionProvider):
    provider_name = "fake"

    def __init__(self, result: ExtractionProviderResult) -> None:
        self.result = result

    def extract(self, payload: ExtractionInput) -> ExtractionProviderResult:
        return self.result

    def last_debug_request_body(self):
        return None


class FakeBodyMetricService:
    def __init__(self, db) -> None:
        self.db = db

    def create_body_metric(self, user_id, payload, commit=True):
        return {
            "id": "bm_auto",
            "recorded_at": payload.recorded_at,
            "recorded_tz": payload.recorded_tz,
            "local_date": datetime(2026, 5, 1).date(),
            "source_type": payload.source_type,
            "weight_kg": float(payload.weight_kg),
            "body_fat_percentage": None,
            "bmi": None,
            "muscle_mass_kg": None,
            "water_percentage": None,
            "confidence": 0.9,
            "source_pending_action_id": None,
        }


class FakeMealQueryService:
    def __init__(self, db) -> None:
        self.db = db

    def list_meals(self, user_id, local_date=None):
        return {
            "meals": [
                {
                    "id": "meal_query",
                    "local_date": str(local_date),
                    "meal_type": "lunch",
                    "items": [{"name": "鸡胸肉"}],
                }
            ]
        }


def _settings() -> Settings:
    return Settings(jwt_secret_key="test-secret-key-with-enough-length")


def test_extraction_service_auto_commits_clear_body_metric(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.extraction_service.BodyMetricService", FakeBodyMetricService)
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我识别到体重记录。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.90"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_body_metric_record",
                    confidence=Decimal("0.90"),
                    arguments={
                        "recorded_at": "2026-05-01T08:10:00+08:00",
                        "source_type": "text",
                        "weight_kg": 72.4,
                    },
                    grounding=ActionGrounding(
                        source="user_current_turn",
                        evidence_text="我今天体重72.4公斤",
                    ),
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="我今天体重72.4公斤")],
        context={},
    )

    assert result["requires_review"] is False
    assert result["pending_actions"] == []
    assert result["committed_records"][0]["type"] == "body_metric"
    assert result["committed_records"][0]["record_id"] == "bm_auto"
    assert result["assistant_content"][0]["event_type"] == "record_auto_committed"
    assert "已自动保存" in result["assistant_text"]


def test_extraction_service_keeps_fuzzy_meal_as_pending() -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我先整理成餐食草稿，请确认。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.90"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_meal_record",
                    confidence=Decimal("0.90"),
                    arguments={
                        "recorded_at": "2026-05-01T12:30:00+08:00",
                        "source_type": "text",
                        "meal_type": "lunch",
                        "items": [{"name": "米饭", "portion_text": "一碗"}],
                    },
                    grounding=ActionGrounding(
                        source="user_current_turn",
                        evidence_text="午餐吃了一碗米饭",
                    ),
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="午餐吃了一碗米饭")],
        context={},
    )

    assert result["requires_review"] is True
    assert result["committed_records"] == []
    assert result["pending_actions"][0]["type"] == "create_meal_record"


def test_extraction_service_normalizes_backfilled_meal_time(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.ai.extraction_service.utc_now",
        lambda: datetime.fromisoformat("2026-05-01T07:20:00"),
    )
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我先整理成餐食草稿，请确认。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.70"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_meal_record",
                    confidence=Decimal("0.70"),
                    arguments={
                        "recorded_at": "2026-05-01T23:00:00+08:00",
                        "recorded_tz": "Asia/Shanghai",
                        "source_type": "voice",
                        "meal_type": "breakfast",
                        "items": [{"name": "面包", "portion_text": "2片"}],
                    },
                    grounding=ActionGrounding(
                        source="user_current_turn",
                        evidence_text="我早上吃了两片面包",
                    ),
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="语音转写: 我早上吃了两片面包")],
        context={},
    )

    assert result["pending_actions"][0]["draft_payload"]["recorded_at"] == (
        "2026-05-01T08:00:00+08:00"
    )


def test_extraction_service_drops_assistant_generated_action_without_plan_evidence(caplog) -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text=(
                "好的，我来为你规划一份晚餐方案。需要我帮你把这份晚餐记录下来吗？"
            ),
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.92"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_meal_record",
                    confidence=Decimal("0.92"),
                    arguments={
                        "recorded_at": "2026-05-05T19:33:00+08:00",
                        "source_type": "manual",
                        "meal_type": "dinner",
                        "items": [{"name": "鸡胸肉", "portion_text": "120g"}],
                    },
                    grounding=ActionGrounding(
                        source="assistant_generated",
                        evidence_text="可以",
                    ),
                    warnings=[],
                )
            ],
        )
    )
    db = FakeDb()
    service = ExtractionService(db, settings=_settings(), provider=provider)

    with caplog.at_level("INFO", logger="app.ai.extraction_service"):
        result = service.process_message(
            user_id="user_test",
            conversation_id="conv_test",
            message_id="msg_test",
            content=[MessageContentItem(type="text", text="可以")],
            context={},
        )

    assert result["pending_actions"] == []
    assert result["requires_review"] is False
    assert db.added == []
    assert "ai_tool_call_rejected" in caplog.text
    assert "assistant_plan_evidence_not_found" in caplog.text


def test_extraction_service_rewrites_false_saved_text_after_rejected_tool() -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text=(
                "已为你将规划的晚餐存为今晚的正式记录："
                "清蒸鲈鱼、西兰花炒蒜、杂粮饭。"
            ),
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.92"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_meal_record",
                    confidence=Decimal("0.92"),
                    arguments={
                        "recorded_at": "2026-05-05T19:33:00+08:00",
                        "source_type": "manual",
                        "meal_type": "dinner",
                        "items": [{"name": "清蒸鲈鱼", "portion_text": "120g"}],
                    },
                    grounding=ActionGrounding(
                        source="assistant_generated",
                        evidence_text="可以，就这么记录吧",
                    ),
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="可以，就这么记录吧")],
        context={},
    )

    assert result["pending_actions"] == []
    assert result["committed_records"] == []
    assert result["tool_results"][0]["status"] == "rejected"
    assert "尚未保存为正式记录" in result["assistant_text"]


def test_extraction_service_drops_missing_grounding() -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我整理出一条餐食草稿，请确认。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.80"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_meal_record",
                    confidence=Decimal("0.80"),
                    arguments={
                        "recorded_at": "2026-05-05T19:33:00+08:00",
                        "source_type": "text",
                        "meal_type": "dinner",
                        "items": [{"name": "鸡胸肉", "portion_text": "120g"}],
                    },
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="我晚餐吃了120g鸡胸肉")],
        context={},
    )

    assert result["pending_actions"] == []
    assert result["requires_review"] is False


def test_extraction_service_drops_empty_evidence() -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我整理出一条餐食草稿，请确认。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.80"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_meal_record",
                    confidence=Decimal("0.80"),
                    arguments={
                        "recorded_at": "2026-05-05T19:33:00+08:00",
                        "source_type": "text",
                        "meal_type": "dinner",
                        "items": [{"name": "鸡胸肉", "portion_text": "120g"}],
                    },
                    grounding=ActionGrounding(
                        source="user_current_turn",
                        evidence_text="",
                    ),
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="我晚餐吃了120g鸡胸肉")],
        context={},
    )

    assert result["pending_actions"] == []
    assert result["requires_review"] is False


def test_extraction_service_drops_fabricated_evidence() -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我整理出一条餐食草稿，请确认。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.80"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_meal_record",
                    confidence=Decimal("0.80"),
                    arguments={
                        "recorded_at": "2026-05-05T19:33:00+08:00",
                        "source_type": "text",
                        "meal_type": "dinner",
                        "items": [{"name": "鸡胸肉", "portion_text": "120g"}],
                    },
                    grounding=ActionGrounding(
                        source="user_current_turn",
                        evidence_text="我晚餐吃了120g鸡胸肉",
                    ),
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="可以")],
        context={},
    )

    assert result["pending_actions"] == []
    assert result["requires_review"] is False


def test_extraction_service_keeps_valid_grounding() -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我先整理成餐食草稿，请确认。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.70"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_meal_record",
                    confidence=Decimal("0.70"),
                    arguments={
                        "recorded_at": "2026-05-05T19:33:00+08:00",
                        "source_type": "text",
                        "meal_type": "dinner",
                        "items": [{"name": "鸡胸肉", "portion_text": "120g"}],
                    },
                    grounding=ActionGrounding(
                        source="user_current_turn",
                        evidence_text="我晚餐吃了120g鸡胸肉",
                    ),
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="我晚餐吃了120g鸡胸肉")],
        context={},
    )

    assert result["requires_review"] is True
    assert result["pending_actions"][0]["type"] == "create_meal_record"


def test_extraction_service_recent_user_message_creates_confirmation_card_only() -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我根据上一条消息整理成身体指标草稿，请确认。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.95"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_body_metric_record",
                    confidence=Decimal("0.95"),
                    arguments={
                        "recorded_at": "2026-05-05T08:00:00+08:00",
                        "source_type": "text",
                        "weight_kg": 72.4,
                    },
                    grounding=ActionGrounding(
                        source="recent_user_message",
                        evidence_text="今天体重72.4公斤",
                    ),
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="就按上一条记录")],
        context={
            "recent_messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "今天体重72.4公斤"}],
                }
            ]
        },
    )

    assert result["committed_records"] == []
    assert result["requires_review"] is True
    assert result["pending_actions"][0]["type"] == "create_body_metric_record"
    assert result["pending_actions"][0]["warnings"][-1]["reason"] == (
        "grounding_requires_confirmation"
    )


def test_extraction_service_tool_result_creates_confirmation_card_only() -> None:
    provider_result = ExtractionProviderResult(
        assistant_text="我根据查询结果整理成餐食草稿，请确认。",
        intent="fitness_record",
        requires_review=True,
        confidence=Decimal("0.82"),
        tool_calls=[
            ExtractionToolCall(
                name="propose_meal_record",
                confidence=Decimal("0.82"),
                arguments={
                    "recorded_at": "2026-05-06T12:30:00+08:00",
                    "source_type": "manual",
                    "meal_type": "lunch",
                    "items": [{"name": "鸡胸肉", "portion_text": "120g"}],
                },
                grounding=ActionGrounding(
                    source="tool_result",
                    source_id="query_meal_records",
                    evidence_text="鸡胸肉",
                ),
                warnings=[],
            )
        ],
    )
    service = ExtractionService(
        FakeDb(),
        settings=_settings(),
        provider=FakeProvider(provider_result),
    )

    result = service.execute_provider_result(
        provider_result=provider_result,
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="把查询到的午餐作为今天的草稿")],
        context={},
        prior_tool_results=[
            {
                "tool_name": "query_meal_records",
                "status": "succeeded",
                "data": {"meals": [{"id": "meal_old", "items": [{"name": "鸡胸肉"}]}]},
            }
        ],
    )

    assert result["committed_records"] == []
    assert result["pending_actions"][0].action_type == "create_meal_record"
    assert result["tool_results"][0]["status"] == "pending_confirmation"


def test_extraction_service_assistant_plan_creates_confirmation_card_only() -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我把上一轮方案整理为草稿，请确认。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.82"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_meal_record",
                    confidence=Decimal("0.82"),
                    arguments={
                        "recorded_at": "2026-05-06T19:00:00+08:00",
                        "source_type": "manual",
                        "meal_type": "dinner",
                        "items": [{"name": "清蒸鱼", "portion_text": "120g"}],
                    },
                    grounding=ActionGrounding(
                        source="assistant_plan",
                        evidence_text="清蒸鱼",
                    ),
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="可以，就这么记录吧")],
        context={
            "recent_messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "建议晚餐吃清蒸鱼和西兰花。"}],
                }
            ]
        },
    )

    assert result["committed_records"] == []
    assert result["pending_actions"][0]["type"] == "create_meal_record"
    assert result["pending_actions"][0]["warnings"][-1]["reason"] == (
        "grounding_requires_confirmation"
    )


def test_extraction_service_rejects_model_inference_record() -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我猜测你可能吃了晚餐。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.50"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_meal_record",
                    confidence=Decimal("0.50"),
                    arguments={
                        "recorded_at": "2026-05-06T19:00:00+08:00",
                        "source_type": "manual",
                        "meal_type": "dinner",
                        "items": [{"name": "晚餐"}],
                    },
                    grounding=ActionGrounding(
                        source="model_inference",
                        evidence_text="可能吃了晚餐",
                    ),
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="我有点饿")],
        context={},
    )

    assert result["pending_actions"] == []
    assert result["tool_results"][0]["status"] == "rejected"
    assert result["tool_results"][0]["reason"] == "source=model_inference"


def test_extraction_service_rejects_confirmed_record_as_new_record_source() -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我不会把正式记录直接复制成新记录。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.70"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_meal_record",
                    confidence=Decimal("0.70"),
                    arguments={
                        "recorded_at": "2026-05-06T12:30:00+08:00",
                        "source_type": "manual",
                        "meal_type": "lunch",
                        "items": [{"name": "鸡胸肉"}],
                    },
                    grounding=ActionGrounding(
                        source="confirmed_record",
                        source_id="meal_1",
                        evidence_text="鸡胸肉",
                    ),
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="照昨天午餐再记一次")],
        context={"recent_records": {"meals": [{"id": "meal_1", "items": [{"name": "鸡胸肉"}]}]}},
    )

    assert result["pending_actions"] == []
    assert result["tool_results"][0]["reason"] == "source=confirmed_record"


def test_extraction_service_rejects_record_tool_from_pending_action_observation() -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我会继续安排晚餐，不会把确认事件再写成记录。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.90"),
            tool_calls=[
                ExtractionToolCall(
                    name="propose_meal_record",
                    confidence=Decimal("0.90"),
                    arguments={
                        "recorded_at": "2026-05-06T12:30:00+08:00",
                        "source_type": "manual",
                        "meal_type": "lunch",
                        "items": [{"name": "炒面", "portion_text": "一份"}],
                    },
                    grounding=ActionGrounding(
                        source="current_user_message",
                        evidence_text="用户已确认待确认动作",
                    ),
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[
            MessageContentItem(type="text", text="用户已确认待确认动作。已保存到正式记录：午餐。")
        ],
        context={"input_origin": "pending_action_observation"},
    )

    assert result["pending_actions"] == []
    assert result["committed_records"] == []
    assert result["tool_results"][0]["status"] == "rejected"
    assert result["tool_results"][0]["reason"] == (
        "record_tool_disallowed_for_pending_action_observation"
    )


def test_extraction_service_updates_active_pending_action_via_model_tool(monkeypatch) -> None:
    class FakePendingActionService:
        def __init__(self, db) -> None:
            self.db = db

        def update_action(self, user_id, pending_action_id, payload, commit=True):
            assert user_id == "user_test"
            assert pending_action_id == "pa_test"
            assert commit is False
            assert payload.draft_payload["items"][0]["portion_text"] == "3个"
            return {
                "pending_action_id": pending_action_id,
                "type": "create_meal_record",
                "status": "pending_confirmation",
                "confidence": 0.85,
                "draft_payload": payload.draft_payload,
                "warnings": [],
            }

    monkeypatch.setattr(
        "app.services.pending_actions.PendingActionService",
        FakePendingActionService,
    )
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我已按你的修改更新草稿，请确认后保存。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.90"),
            tool_calls=[
                ExtractionToolCall(
                    name="update_pending_action",
                    arguments={
                        "pending_action_id": "pa_test",
                        "draft_payload": {
                            "items": [{"name": "肉包", "portion_text": "3个"}],
                        },
                    },
                    confidence=Decimal("0.90"),
                    grounding=ActionGrounding(
                        source="current_user_message",
                        source_id="pa_test",
                        evidence_text="肉包不是2个，是3个",
                    ),
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="肉包不是2个，是3个")],
        context={
            "active_pending_actions": [
                {"pending_action_id": "pa_test", "type": "create_meal_record"}
            ]
        },
    )

    assert result["requires_review"] is True
    assert result["pending_actions"][0]["pending_action_id"] == "pa_test"
    assert result["pending_actions"][0]["draft_payload"]["items"][0]["portion_text"] == "3个"
    assert result["tool_results"][0]["tool_name"] == "update_pending_action"
    assert result["tool_results"][0]["status"] == "pending_confirmation"


def test_extraction_service_commits_active_pending_action_via_model_tool(monkeypatch) -> None:
    class FakePendingActionService:
        def __init__(self, db) -> None:
            self.db = db

        def commit_action_for_agent(self, user_id, pending_action_id):
            assert user_id == "user_test"
            assert pending_action_id == "pa_test"
            return {
                "pending_action_id": pending_action_id,
                "record_type": "meal",
                "record_id": "meal_test",
                "record": {"id": "meal_test", "meal_type": "breakfast", "items": []},
                "message": "已保存到正式记录：早餐。",
                "source_message_id": "msg_source",
                "confidence": 0.85,
            }

    monkeypatch.setattr(
        "app.services.pending_actions.PendingActionService",
        FakePendingActionService,
    )
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="好的，保存这条记录。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.90"),
            tool_calls=[
                ExtractionToolCall(
                    name="commit_pending_action",
                    arguments={"pending_action_id": "pa_test"},
                    confidence=Decimal("0.90"),
                    grounding=ActionGrounding(
                        source="current_user_message",
                        source_id="pa_test",
                        evidence_text="确认保存",
                    ),
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="确认保存")],
        context={
            "active_pending_actions": [
                {"pending_action_id": "pa_test", "type": "create_meal_record"}
            ]
        },
    )

    assert result["requires_review"] is False
    assert result["pending_actions"] == []
    assert result["committed_records"][0]["record_id"] == "meal_test"
    assert result["tool_results"][0]["tool_name"] == "commit_pending_action"
    assert result["tool_results"][0]["status"] == "committed"
    assert result["assistant_text"] == "已保存到正式记录：早餐。"


def test_pending_action_tool_requires_current_message_grounding() -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我不能在没有当前用户确认依据时处理待确认动作。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.90"),
            tool_calls=[
                ExtractionToolCall(
                    name="commit_pending_action",
                    arguments={"pending_action_id": "pa_test"},
                    confidence=Decimal("0.90"),
                    grounding=ActionGrounding(
                        source="active_pending_action",
                        source_id="pa_test",
                        evidence_text="pa_test",
                    ),
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="继续聊聊早餐")],
        context={
            "active_pending_actions": [
                {"pending_action_id": "pa_test", "type": "create_meal_record"}
            ]
        },
    )

    assert result["pending_actions"] == []
    assert result["committed_records"] == []
    assert result["tool_results"][0]["status"] == "rejected"
    assert result["tool_results"][0]["reason"] == (
        "pending_action_tool_requires_current_user_message"
    )


def test_extraction_service_executes_read_only_meal_query_tool(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.extraction_service.MealService", FakeMealQueryService)
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我先查询今天的餐食记录。",
            intent="answer_fitness_question",
            requires_review=True,
            confidence=Decimal("0.80"),
            tool_calls=[
                ExtractionToolCall(
                    name="query_meal_records",
                    arguments={"local_date": "2026-05-06"},
                    confidence=Decimal("0.80"),
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="今天吃了什么？")],
        context={},
    )

    assert result["pending_actions"] == []
    assert result["tool_results"][0]["status"] == "succeeded"
    assert result["tool_results"][0]["data"]["meals"][0]["items"][0]["name"] == "鸡胸肉"
