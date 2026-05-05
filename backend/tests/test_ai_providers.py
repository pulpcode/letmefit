import json
from datetime import datetime

import pytest

from app.ai.providers.bailian import BailianExtractionProvider
from app.ai.providers.base import get_extraction_provider
from app.ai.providers.mock import MockExtractionProvider
from app.ai.types import ExtractionInput
from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.conversation import MessageContentItem


class FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    def __init__(self, content: str | list[str]) -> None:
        self.contents = content if isinstance(content, list) else [content]
        self.calls = []

    def create(self, **kwargs):
        content = self.contents[min(len(self.calls), len(self.contents) - 1)]
        self.calls.append(kwargs)
        return FakeCompletion(content)


class FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeClient:
    def __init__(self, content: str | list[str]) -> None:
        self.completions = FakeCompletions(content)
        self.chat = FakeChat(self.completions)


def _input(text: str) -> ExtractionInput:
    return ExtractionInput(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text=text)],
    )


def _body_metric_content() -> str:
    return json.dumps(
        {
            "assistant_text": "我整理出一条体重记录，请确认。",
            "intent": "fitness_record",
            "requires_review": True,
            "confidence": 0.82,
            "warnings": [],
            "pending_actions": [
                {
                    "type": "create_body_metric_record",
                    "confidence": 0.82,
                    "draft_payload": {
                        "recorded_at": "2026-05-01T08:10:00+08:00",
                        "source_type": "text",
                        "weight_kg": 72.4,
                    },
                    "grounding": {
                        "source": "user_current_turn",
                        "evidence_text": "今天体重72.4公斤",
                    },
                    "warnings": [],
                }
            ],
        },
        ensure_ascii=False,
    )


def _offer_content() -> str:
    return json.dumps(
        {
            "assistant_text": "需要我帮您规划一份适合的晚餐方案吗？",
            "intent": "answer_fitness_question",
            "requires_review": False,
            "confidence": 0.86,
            "warnings": [],
            "pending_actions": [],
            "dialogue_state_patch": {
                "new_active_offer": {
                    "kind": "assistant_offer",
                    "surface_text": "需要我帮您规划一份适合的晚餐方案吗？",
                    "referent": {
                        "topic": "晚餐方案",
                        "user_goal": "基于今日记录和减脂目标安排晚餐",
                        "expected_followup": "用户同意时直接生成晚餐方案",
                    },
                }
            },
        },
        ensure_ascii=False,
    )


def test_get_extraction_provider_defaults_to_mock() -> None:
    provider = get_extraction_provider(
        Settings(jwt_secret_key="test-secret-key-with-enough-length", ai_provider="mock")
    )

    assert isinstance(provider, MockExtractionProvider)


def test_mock_provider_extracts_body_metric_action() -> None:
    provider = MockExtractionProvider(Settings(jwt_secret_key="test-secret-key-with-enough-length"))

    result = provider.extract(_input("今天体重72.4公斤"))

    assert result.intent == "fitness_record"
    assert result.requires_review is True
    assert result.action_specs[0].action_type == "create_body_metric_record"
    assert result.action_specs[0].draft_payload["weight_kg"] == 72.4


def test_bailian_provider_requires_api_key() -> None:
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        ai_provider="bailian",
        bailian_api_key="",
        dashscope_api_key="",
    )

    with pytest.raises(AppError) as exc_info:
        BailianExtractionProvider(settings)

    assert exc_info.value.code == "INTERNAL_ERROR"


def test_bailian_provider_parses_json_mode_response() -> None:
    client = FakeClient(_body_metric_content())
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
        bailian_model="qwen-plus",
    )
    provider = BailianExtractionProvider(settings, client=client)

    result = provider.extract(_input("今天体重72.4公斤"))

    assert result.intent == "fitness_record"
    assert result.confidence is not None
    assert result.action_specs[0].action_type == "create_body_metric_record"
    assert result.action_specs[0].grounding is not None
    assert result.action_specs[0].grounding.source == "user_current_turn"
    assert result.action_specs[0].draft_payload["weight_kg"] == 72.4
    call = client.completions.calls[0]
    assert call["model"] == "qwen-plus"
    assert call["response_format"] == {"type": "json_object"}


def test_bailian_provider_parses_dialogue_state_patch() -> None:
    client = FakeClient(_offer_content())
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
    )
    provider = BailianExtractionProvider(settings, client=client)

    result = provider.extract(_input("我晚上还吃饭吗？"))

    offer = result.dialogue_state_patch["new_active_offer"]
    assert offer["kind"] == "assistant_offer"
    assert offer["referent"]["topic"] == "晚餐方案"


def test_bailian_provider_includes_conversation_context_in_prompt() -> None:
    client = FakeClient(_body_metric_content())
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
    )
    provider = BailianExtractionProvider(settings, client=client)
    payload = _input("今天体重72.4公斤")
    payload = ExtractionInput(
        user_id=payload.user_id,
        conversation_id=payload.conversation_id,
        message_id=payload.message_id,
        content=payload.content,
        context={
            "conversation_summary": {
                "summary_text": "用户昨天记录过体重72.8kg",
                "created_at": datetime(2026, 5, 1, 12, 0, 0),
            }
        },
    )

    provider.extract(payload)

    user_prompt = client.completions.calls[0]["messages"][1]["content"]
    prompt_json = json.loads(user_prompt)
    assert prompt_json["conversation_context"]["conversation_summary"]["summary_text"] == (
        "用户昨天记录过体重72.8kg"
    )
    assert prompt_json["conversation_context"]["conversation_summary"]["created_at"] == (
        "2026-05-01 12:00:00"
    )
    assert prompt_json["context_contract"]["authority_order"][:4] == [
        "message_content",
        "ephemeral_state.active_offer",
        "profile",
        "recent_records",
    ]
    assert "只有 active_pending_actions" in "".join(prompt_json["context_contract"]["rules"])
    assert "优先读取 recent_records" in "".join(prompt_json["context_contract"]["rules"])
    assert "active_offer 在本轮结束后会失效" in "".join(
        prompt_json["context_contract"]["rules"]
    )
    assert "pending_actions 必须带 grounding" in "".join(
        prompt_json["context_contract"]["rules"]
    )
    system_prompt = client.completions.calls[0]["messages"][0]["content"]
    assert "每个 pending_action 必须包含 grounding 字段" in system_prompt
    assert "assistant_generated 不能作为写入记录或确认卡依据" in system_prompt
    assert "dialogue_state_patch 不能包含 profile" in "".join(
        prompt_json["context_contract"]["rules"]
    )


def test_bailian_provider_prompt_requires_recent_records_and_nutrition_estimates() -> None:
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
    )
    provider = BailianExtractionProvider(settings, client=FakeClient(_body_metric_content()))

    body = provider.debug_request_body(_input("我吃了两片面包"))
    system_prompt = body["messages"][0]["content"]

    assert "conversation_context.recent_records" in system_prompt
    assert "portion_grams" in system_prompt
    assert "calories" in system_prompt
    assert "estimated_nutrition" in system_prompt


def test_bailian_debug_request_body_matches_chat_completion_body() -> None:
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
        bailian_model="qwen-plus",
        ai_temperature=0.2,
    )
    provider = BailianExtractionProvider(settings, client=FakeClient(_body_metric_content()))

    body = provider.debug_request_body(_input("今天体重72.4公斤"))

    assert body["model"] == "qwen-plus"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.2
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"
    assert json.loads(body["messages"][1]["content"])["message_content"][0]["text"] == (
        "今天体重72.4公斤"
    )


def test_bailian_provider_repairs_invalid_json_response() -> None:
    client = FakeClient(["not-json", _body_metric_content()])
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
        bailian_model="qwen-plus",
        ai_schema_repair_retries=1,
    )
    provider = BailianExtractionProvider(settings, client=client)

    result = provider.extract(_input("今天体重72.4公斤"))

    assert result.action_specs[0].draft_payload["weight_kg"] == 72.4
    assert len(client.completions.calls) == 2
    repair_messages = client.completions.calls[1]["messages"]
    assert repair_messages[-1]["role"] == "user"
    assert "失败原因: invalid_json" in repair_messages[-1]["content"]


def test_bailian_provider_rejects_invalid_schema_response() -> None:
    client = FakeClient(
        json.dumps(
            {
                "assistant_text": "bad",
                "intent": "unknown",
                "requires_review": False,
                "confidence": 0.5,
                "warnings": [],
                "pending_actions": [],
            }
        )
    )
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
        ai_schema_repair_retries=0,
    )
    provider = BailianExtractionProvider(settings, client=client)

    with pytest.raises(AppError) as exc_info:
        provider.extract(_input("今天体重72.4公斤"))

    assert exc_info.value.code == "AI_EXTRACTION_FAILED"
    assert exc_info.value.details["reason"] == "schema_validation_failed"
