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

# --- Fake OpenAI SDK objects supporting native function calling shape ---


class FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments

    def model_dump(self, mode: str = "json", exclude_none: bool = False) -> dict:
        return {"name": self.name, "arguments": self.arguments}


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.type = "function"
        self.function = FakeFunction(name, arguments)

    def model_dump(self, mode: str = "json", exclude_none: bool = False) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "function": self.function.model_dump(mode=mode),
        }


class FakeMessage:
    def __init__(self, content: str = "", tool_calls: list[FakeToolCall] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, mode: str = "json", exclude_none: bool = False) -> dict:
        result: dict = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            result["tool_calls"] = [tc.model_dump(mode=mode) for tc in self.tool_calls]
        return result


class FakeChoice:
    def __init__(self, message: FakeMessage) -> None:
        self.message = message
        self.finish_reason = "tool_calls" if message.tool_calls else "stop"
        self.index = 0


class FakeCompletion:
    def __init__(self, message: FakeMessage) -> None:
        self.choices = [FakeChoice(message)]
        self.id = "chatcmpl-fake"
        self.model = "qwen-plus"

    def model_dump(self, mode: str = "json") -> dict:
        return {
            "id": self.id,
            "model": self.model,
            "choices": [
                {
                    "index": choice.index,
                    "finish_reason": choice.finish_reason,
                    "message": choice.message.model_dump(mode=mode),
                }
                for choice in self.choices
            ],
        }


class FakeCompletions:
    def __init__(self, messages: FakeMessage | list[FakeMessage]) -> None:
        self.messages = messages if isinstance(messages, list) else [messages]
        self.calls: list[dict] = []

    def create(self, **kwargs):
        idx = min(len(self.calls), len(self.messages) - 1)
        self.calls.append(kwargs)
        return FakeCompletion(self.messages[idx])


class FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeClient:
    def __init__(self, messages: FakeMessage | list[FakeMessage]) -> None:
        self.completions = FakeCompletions(messages)
        self.chat = FakeChat(self.completions)


# --- Test helpers ---


def _input(text: str) -> ExtractionInput:
    return ExtractionInput(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text=text)],
    )


def _body_metric_message() -> FakeMessage:
    return FakeMessage(
        content="我整理出一条体重草稿，请确认。",
        tool_calls=[
            FakeToolCall(
                call_id="call_test_001",
                name="propose_body_metric_record",
                arguments=json.dumps(
                    {
                        "recorded_at": "2026-05-01T08:10:00+08:00",
                        "source_type": "text",
                        "weight_kg": 72.4,
                        "confidence": 0.82,
                        "grounding": {
                            "source": "user_message",
                            "evidence_text": "今天体重72.4公斤",
                            "confidence": 0.95,
                        },
                    }
                ),
            )
        ],
    )


def _text_only_message() -> FakeMessage:
    return FakeMessage(content="为你规划一份高蛋白午餐...", tool_calls=None)


# --- Tests ---


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
    assert result.tool_calls[0].name == "propose_body_metric_record"
    assert result.tool_calls[0].arguments["weight_kg"] == 72.4
    assert result.tool_calls[0].tool_call_id is not None


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


def test_bailian_provider_parses_native_tool_calls() -> None:
    client = FakeClient(_body_metric_message())
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
        bailian_model="qwen-plus",
    )
    provider = BailianExtractionProvider(settings, client=client)

    result = provider.extract(_input("今天体重72.4公斤"))

    assert result.intent == "fitness_record"
    assert result.requires_review is True
    assert result.confidence is not None
    tool_call = result.tool_calls[0]
    assert tool_call.name == "propose_body_metric_record"
    assert tool_call.tool_call_id == "call_test_001"
    assert tool_call.arguments["weight_kg"] == 72.4
    # Grounding should be lifted out of arguments
    assert "grounding" not in tool_call.arguments
    assert tool_call.grounding is not None
    assert tool_call.grounding.source == "user_message"
    assert tool_call.grounding.evidence_text == "今天体重72.4公斤"
    # Request should use tools parameter, not response_format
    call = client.completions.calls[0]
    assert call["model"] == "qwen-plus"
    assert "tools" in call
    assert "response_format" not in call
    assert call["tool_choice"] == "auto"
    # Raw output should preserve tool_call shape for prior_turns reconstruction
    assert result.raw_output["tool_calls"][0]["id"] == "call_test_001"


def test_bailian_provider_text_only_response_derives_answer_intent() -> None:
    client = FakeClient(_text_only_message())
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
    )
    provider = BailianExtractionProvider(settings, client=client)

    result = provider.extract(_input("帮我规划明天的饮食"))

    assert result.intent == "answer_fitness_question"
    assert result.requires_review is False
    assert result.tool_calls == []
    assert result.assistant_text.startswith("为你规划")


def test_bailian_provider_includes_conversation_context_in_prompt() -> None:
    client = FakeClient(_body_metric_message())
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
    assert prompt_json["context_contract"]["authority_order"][:6] == [
        "message_content",
        "current_observation",
        "profile",
        "energy_target",
        "today_summary",
        "recent_records",
    ]
    system_prompt = client.completions.calls[0]["messages"][0]["content"]
    # New prompt highlights: dual-channel output and grounding rules
    assert "健身管理对话助手" in system_prompt
    assert "tool_calls" in system_prompt
    assert "assistant text" in system_prompt
    # JSON Mode language must be gone
    assert "你必须只输出 JSON 对象" not in system_prompt


def test_bailian_provider_prompt_keeps_nutrition_estimation_rule() -> None:
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
    )
    provider = BailianExtractionProvider(settings, client=FakeClient(_body_metric_message()))

    body = provider.debug_request_body(_input("我吃了两片面包"))
    system_prompt = body["messages"][0]["content"]

    assert "recent_records" in system_prompt
    assert "common foods" in system_prompt.lower() or "常见食物" in system_prompt
    assert "confidence" in system_prompt.lower()


def test_bailian_debug_request_body_uses_tools_parameter() -> None:
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
        bailian_model="qwen-plus",
        ai_temperature=0.2,
    )
    provider = BailianExtractionProvider(settings, client=FakeClient(_body_metric_message()))

    body = provider.debug_request_body(_input("今天体重72.4公斤"))

    assert body["model"] == "qwen-plus"
    assert "tools" in body
    assert "response_format" not in body
    assert body["tool_choice"] == "auto"
    assert body["temperature"] == 0.2
    tool_names = {t["function"]["name"] for t in body["tools"]}
    assert "propose_meal_record" in tool_names
    assert "propose_body_metric_record" in tool_names
    assert "query_meal_records" in tool_names
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"
    assert json.loads(body["messages"][1]["content"])["message_content"][0]["text"] == (
        "今天体重72.4公斤"
    )


def test_bailian_provider_repairs_invalid_tool_arguments() -> None:
    bad_message = FakeMessage(
        content="",
        tool_calls=[
            FakeToolCall(
                call_id="call_bad",
                name="propose_body_metric_record",
                arguments="{not valid json",
            )
        ],
    )
    client = FakeClient([bad_message, _body_metric_message()])
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
        ai_schema_repair_retries=1,
    )
    provider = BailianExtractionProvider(settings, client=client)

    result = provider.extract(_input("今天体重72.4公斤"))

    assert result.tool_calls[0].arguments["weight_kg"] == 72.4
    assert len(client.completions.calls) == 2
    repair_messages = client.completions.calls[1]["messages"]
    assert repair_messages[-1]["role"] == "user"
    assert "invalid_tool_arguments_json" in repair_messages[-1]["content"]


def test_bailian_provider_rejects_empty_response() -> None:
    empty_message = FakeMessage(content="", tool_calls=None)
    client = FakeClient(empty_message)
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
        ai_schema_repair_retries=0,
    )
    provider = BailianExtractionProvider(settings, client=client)

    with pytest.raises(AppError) as exc_info:
        provider.extract(_input("今天体重72.4公斤"))

    assert exc_info.value.code == "AI_EXTRACTION_FAILED"
    assert exc_info.value.details["reason"] == "empty_response"


def test_bailian_provider_rejects_unsupported_tool_name() -> None:
    message = FakeMessage(
        content="",
        tool_calls=[
            FakeToolCall(
                call_id="call_x",
                name="some_unknown_tool",
                arguments="{}",
            )
        ],
    )
    client = FakeClient(message)
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        bailian_api_key="sk-test",
        ai_schema_repair_retries=0,
    )
    provider = BailianExtractionProvider(settings, client=client)

    with pytest.raises(AppError) as exc_info:
        provider.extract(_input("anything"))

    assert "unsupported_tool_name" in exc_info.value.details["reason"]
