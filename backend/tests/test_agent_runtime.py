from decimal import Decimal

from app.ai.agent_runtime import AgentRuntime
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


class SequenceProvider(ExtractionProvider):
    provider_name = "sequence"

    def __init__(self, results: list[ExtractionProviderResult]) -> None:
        self.results = results
        self.payloads: list[ExtractionInput] = []

    def extract(self, payload: ExtractionInput) -> ExtractionProviderResult:
        self.payloads.append(payload)
        index = min(len(self.payloads) - 1, len(self.results) - 1)
        return self.results[index]

    def last_debug_request_body(self):
        return None


class FakeMealService:
    def __init__(self, db) -> None:
        self.db = db

    def list_meals(self, user_id, local_date=None):
        return {
            "meals": [
                {
                    "id": "meal_today",
                    "local_date": str(local_date),
                    "meal_type": "lunch",
                    "items": [{"name": "鸡胸肉"}],
                }
            ]
        }


class FakeBodyMetricService:
    def __init__(self, db) -> None:
        self.db = db

    def create_body_metric(self, user_id, payload, commit=True):
        return {
            "id": "bm_auto",
            "recorded_at": payload.recorded_at,
            "recorded_tz": payload.recorded_tz,
            "local_date": payload.recorded_at.date(),
            "source_type": payload.source_type,
            "weight_kg": float(payload.weight_kg),
            "body_fat_percentage": None,
            "bmi": None,
            "muscle_mass_kg": None,
            "water_percentage": None,
            "confidence": 0.9,
            "source_pending_action_id": None,
        }


def _settings(**overrides) -> Settings:
    values = {"jwt_secret_key": "test-secret-key-with-enough-length"}
    values.update(overrides)
    return Settings(**values)


def _content(text: str) -> list[MessageContentItem]:
    return [MessageContentItem(type="text", text=text)]


def _runtime(provider: SequenceProvider, settings: Settings | None = None) -> AgentRuntime:
    runtime_settings = settings or _settings()
    service = ExtractionService(FakeDb(), settings=runtime_settings, provider=provider)
    return AgentRuntime(service.db, settings=runtime_settings, extraction_service=service)


def test_agent_runtime_simple_answer_finishes_in_one_model_turn() -> None:
    provider = SequenceProvider(
        [
            ExtractionProviderResult(
                assistant_text="今天可以做一次轻量力量训练。",
                intent="answer_fitness_question",
                requires_review=False,
                confidence=Decimal("0.80"),
            )
        ]
    )
    runtime = _runtime(provider)

    result = runtime.run(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=_content("今天适合训练吗？"),
        context={},
    )

    assert result["assistant_text"] == "今天可以做一次轻量力量训练。"
    assert len(provider.payloads) == 1
    assert [event["event"] for event in result["agent_trace"]] == [
        "agent_started",
        "model_decision",
        "final_answer",
    ]
    assert result["agent_trace"][1]["decision"] == "final_answer"


def test_agent_runtime_clarifying_question_does_not_create_pending_action() -> None:
    provider = SequenceProvider(
        [
            ExtractionProviderResult(
                assistant_text="你想记录的是早餐、午餐还是晚餐？",
                intent="fitness_record",
                requires_review=False,
                confidence=Decimal("0.60"),
                warnings=[{"field": "agent_decision", "reason": "needs_clarification"}],
            )
        ]
    )
    runtime = _runtime(provider)

    result = runtime.run(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=_content("帮我记一下"),
        context={},
    )

    assert result["pending_actions"] == []
    assert result["requires_review"] is False
    assert result["agent_trace"][-1]["event"] == "clarifying_question"
    assert result["agent_trace"][1]["decision"] == "ask_clarifying_question"


def test_agent_runtime_runs_query_tool_then_final_answer(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.extraction_service.MealService", FakeMealService)
    provider = SequenceProvider(
        [
            ExtractionProviderResult(
                assistant_text="我先查一下今天的记录。",
                intent="answer_fitness_question",
                requires_review=True,
                confidence=Decimal("0.70"),
                tool_calls=[
                    ExtractionToolCall(
                        name="query_meal_records",
                        arguments={"local_date": "2026-05-06"},
                        confidence=Decimal("0.80"),
                    )
                ],
            ),
            ExtractionProviderResult(
                assistant_text="今天已记录午餐：鸡胸肉。",
                intent="answer_fitness_question",
                requires_review=False,
                confidence=Decimal("0.80"),
            ),
        ]
    )
    runtime = _runtime(provider)

    result = runtime.run(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=_content("今天吃了什么？"),
        context={"recent_records": {"meals": []}},
    )

    assert result["assistant_text"] == "今天已记录午餐：鸡胸肉。"
    assert len(provider.payloads) == 2
    assert provider.payloads[1].context["agent_loop"]["tool_results"][0]["status"] == "succeeded"
    assert result["tool_results"][0]["tool_name"] == "query_meal_records"
    assert result["tool_results"][0]["data"]["meals"][0]["items"][0]["name"] == "鸡胸肉"
    assert [event["event"] for event in result["agent_trace"]] == [
        "agent_started",
        "model_decision",
        "tool_call_started",
        "tool_result",
        "model_decision",
        "final_answer",
    ]


def test_agent_runtime_pauses_when_record_tool_requires_human_confirmation() -> None:
    provider = SequenceProvider(
        [
            ExtractionProviderResult(
                assistant_text="我先整理成餐食草稿。",
                intent="fitness_record",
                requires_review=True,
                confidence=Decimal("0.70"),
                tool_calls=[
                    ExtractionToolCall(
                        name="propose_meal_record",
                        arguments={
                            "recorded_at": "2026-05-06T12:30:00+08:00",
                            "source_type": "text",
                            "meal_type": "lunch",
                            "items": [{"name": "炒面", "portion_text": "一份"}],
                        },
                        grounding=ActionGrounding(
                            source="current_user_message",
                            evidence_text="中午吃了炒面",
                        ),
                    )
                ],
            ),
            ExtractionProviderResult(
                assistant_text="不应该进入第二轮。",
                intent="answer_fitness_question",
                requires_review=False,
                confidence=Decimal("0.80"),
            ),
        ]
    )
    runtime = _runtime(provider)

    result = runtime.run(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=_content("中午吃了炒面，帮我安排今晚晚餐"),
        context={},
    )

    assert len(provider.payloads) == 1
    assert result["pending_actions"][0]["type"] == "create_meal_record"
    assert result["tool_results"][0]["status"] == "pending_confirmation"
    assert result["agent_trace"][-1]["event"] == "human_confirmation_required"


def test_agent_runtime_continues_after_auto_committed_record(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.extraction_service.BodyMetricService", FakeBodyMetricService)
    provider = SequenceProvider(
        [
            ExtractionProviderResult(
                assistant_text="我记录一下体重。",
                intent="fitness_record",
                requires_review=True,
                confidence=Decimal("0.90"),
                tool_calls=[
                    ExtractionToolCall(
                        name="propose_body_metric_record",
                        confidence=Decimal("0.90"),
                        arguments={
                            "recorded_at": "2026-05-06T08:00:00+08:00",
                            "source_type": "text",
                            "weight_kg": 72.4,
                        },
                        grounding=ActionGrounding(
                            source="current_user_message",
                            evidence_text="今天体重72.4公斤",
                        ),
                    )
                ],
            ),
            ExtractionProviderResult(
                assistant_text="体重已记录，今天训练建议轻量力量训练。",
                intent="answer_fitness_question",
                requires_review=False,
                confidence=Decimal("0.80"),
            ),
        ]
    )
    runtime = _runtime(provider)

    result = runtime.run(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=_content("今天体重72.4公斤，给我训练建议"),
        context={},
    )

    assert len(provider.payloads) == 2
    assert result["committed_records"][0]["type"] == "body_metric"
    assert result["assistant_text"] == (
        "已自动保存：体重 72.4kg。可在记录页修改或删除。"
        " 体重已记录，今天训练建议轻量力量训练。"
    )
    assert result["assistant_content"][-1]["text"] == "体重已记录，今天训练建议轻量力量训练。"
    assert any(event["event"] == "final_answer" for event in result["agent_trace"])


def test_agent_runtime_stops_when_model_turn_limit_is_reached(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.extraction_service.MealService", FakeMealService)
    settings = _settings(
        agent_max_model_turns=3,
        agent_max_tool_rounds=2,
        agent_max_tool_calls_per_round=3,
        agent_max_total_tool_calls=6,
    )
    provider = SequenceProvider(
        [
            ExtractionProviderResult(
                assistant_text="继续查询。",
                intent="answer_fitness_question",
                requires_review=True,
                confidence=Decimal("0.70"),
                tool_calls=[
                    ExtractionToolCall(
                        name="query_meal_records",
                        arguments={"local_date": "2026-05-06"},
                    )
                ],
            )
        ]
    )
    runtime = _runtime(provider, settings=settings)

    result = runtime.run(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=_content("帮我持续查询"),
        context={},
    )

    assert len(provider.payloads) == 3
    assert all(result["tool_name"] != "agent_loop" for result in result["tool_results"])
    assert result["agent_trace"][-1]["event"] == "loop_limit_reached"
    assert result["agent_trace"][-1]["reason"] == "max_model_turns"
    assert "步骤" in result["assistant_text"]
