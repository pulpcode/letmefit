from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import create_app
from app.models import User
from app.schemas.conversation import ConversationCreateRequest, MessageCreateRequest
from app.services.conversations import get_conversation_service
from app.services.pending_actions import get_pending_action_service


class FakeConversationService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.debug_flags: list[bool] = []
        self.agent_trace_flags: list[bool] = []

    def create_conversation(self, user_id: str, payload: ConversationCreateRequest) -> dict:
        self.calls.append(("create", user_id, payload.title))
        return {
            "conversation_id": "conv_test",
            "conversation": self._conversation("conv_test", payload.title),
        }

    def list_conversations(self, user_id: str) -> dict:
        self.calls.append(("list", user_id))
        return {"conversations": [self._conversation("conv_test", "今天记录")]}

    def send_message(
        self,
        user_id: str,
        conversation_id: str,
        payload: MessageCreateRequest,
    ) -> dict:
        self.calls.append(("send", user_id, conversation_id, payload.content[0].type))
        self.debug_flags.append(payload.include_debug_context)
        self.agent_trace_flags.append(payload.include_agent_trace)
        response = {
            "message_id": "msg_user",
            "assistant_message_id": "msg_assistant",
            "assistant_text": "我先整理成一条餐食记录草稿，请确认或修改后再保存。",
            "intent": "fitness_record",
            "requires_review": True,
            "pending_actions": [
                {
                    "pending_action_id": "pa_test",
                    "type": "create_meal_record",
                    "status": "pending_confirmation",
                    "confidence": 0.5,
                    "draft_payload": {"meal_type": "lunch", "items": []},
                    "warnings": [],
                }
            ],
        }
        if payload.include_debug_context:
            response["debug_context"] = {
                "provider": "mock",
                "normalized_content": [{"type": "text", "text": "今天午餐吃了鸡胸肉"}],
                "conversation_context": {"input_normalization": {"media": []}},
                "llm_user_prompt_payload": {
                    "message_content": [{"type": "text", "text": "今天午餐吃了鸡胸肉"}],
                    "conversation_context": {"input_normalization": {"media": []}},
                },
            }
        if payload.include_agent_trace:
            response["agent_trace"] = [
                {"event": "agent_started"},
                {"event": "model_decision", "decision": "final_answer"},
                {"event": "final_answer"},
            ]
        return response

    def list_messages(self, user_id: str, conversation_id: str) -> dict:
        self.calls.append(("messages", user_id, conversation_id))
        return {
            "messages": [
                {
                    "id": "msg_user",
                    "conversation_id": conversation_id,
                    "role": "user",
                    "content": [{"type": "text", "text": "午餐"}],
                    "intent": "fitness_record",
                    "requires_review": True,
                    "created_at": "2026-05-01T12:00:00",
                }
            ]
        }

    def _conversation(self, conversation_id: str, title: str | None) -> dict:
        return {
            "id": conversation_id,
            "title": title,
            "status": "active",
            "created_at": "2026-05-01T12:00:00",
            "updated_at": "2026-05-01T12:00:00",
        }


class FakePendingActionService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def list_for_conversation(self, user_id: str, conversation_id: str) -> dict:
        self.calls.append(("pending", user_id, conversation_id))
        return {
            "pending_actions": [
                {
                    "pending_action_id": "pa_test",
                    "type": "create_meal_record",
                    "status": "pending_confirmation",
                    "confidence": 0.5,
                    "draft_payload": {"meal_type": "lunch", "items": []},
                    "warnings": [],
                }
            ]
        }


def _authorized_app(
    conversation_service: FakeConversationService,
    pending_action_service: FakePendingActionService | None = None,
):
    app = create_app()
    app.dependency_overrides[get_conversation_service] = lambda: conversation_service
    if pending_action_service:
        app.dependency_overrides[get_pending_action_service] = lambda: pending_action_service
    app.dependency_overrides[get_current_user] = lambda: User(
        id="user_test",
        phone_number="+8613800138000",
        country_code="86",
        status="active",
    )
    return app


def test_conversations_require_authentication() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/conversations")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_create_and_list_conversations_use_current_user() -> None:
    service = FakeConversationService()
    client = TestClient(_authorized_app(service))

    create_response = client.post("/v1/conversations", json={"title": "今天记录"})
    list_response = client.get("/v1/conversations")

    assert create_response.status_code == 200
    assert create_response.json()["data"]["conversation_id"] == "conv_test"
    assert list_response.status_code == 200
    assert list_response.json()["data"]["conversations"][0]["id"] == "conv_test"
    assert service.calls[0] == ("create", "user_test", "今天记录")
    assert service.calls[1] == ("list", "user_test")


def test_send_message_returns_pending_actions() -> None:
    service = FakeConversationService()
    client = TestClient(_authorized_app(service))

    response = client.post(
        "/v1/conversations/conv_test/messages",
        json={"content": [{"type": "text", "text": "今天午餐吃了鸡胸肉"}]},
        headers={"x-request-id": "req_conversation"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "req_conversation"
    assert body["data"]["message_id"] == "msg_user"
    assert body["data"]["requires_review"] is True
    assert body["data"]["pending_actions"][0]["pending_action_id"] == "pa_test"
    assert "debug_context" not in body["data"]
    assert "agent_trace" not in body["data"]
    assert service.calls[0] == ("send", "user_test", "conv_test", "text")
    assert service.debug_flags == [False]
    assert service.agent_trace_flags == [False]


def test_send_message_can_request_debug_context() -> None:
    service = FakeConversationService()
    client = TestClient(_authorized_app(service))

    response = client.post(
        "/v1/conversations/conv_test/messages",
        json={
            "content": [{"type": "text", "text": "今天午餐吃了鸡胸肉"}],
            "include_debug_context": True,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["debug_context"]["provider"] == "mock"
    assert data["debug_context"]["normalized_content"][0]["text"] == "今天午餐吃了鸡胸肉"
    assert data["debug_context"]["llm_user_prompt_payload"]["conversation_context"] == {
        "input_normalization": {"media": []}
    }
    assert service.debug_flags == [True]


def test_send_message_can_request_agent_trace() -> None:
    service = FakeConversationService()
    client = TestClient(_authorized_app(service))

    response = client.post(
        "/v1/conversations/conv_test/messages",
        json={
            "content": [{"type": "text", "text": "今天吃了什么？"}],
            "include_agent_trace": True,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["agent_trace"][0]["event"] == "agent_started"
    assert data["agent_trace"][-1]["event"] == "final_answer"
    assert service.agent_trace_flags == [True]


def test_send_message_stream_returns_sse_events() -> None:
    service = FakeConversationService()
    client = TestClient(_authorized_app(service))

    response = client.post(
        "/v1/conversations/conv_test/messages/stream",
        json={
            "content": [{"type": "text", "text": "今天吃了什么？"}],
            "include_agent_trace": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert "event: delta" in response.text
    assert "event: done" in response.text
    assert '"assistant_message_id": "msg_assistant"' in response.text
    assert service.calls[0] == ("send", "user_test", "conv_test", "text")
    assert service.agent_trace_flags == [True]


def test_list_messages_and_pending_actions_use_conversation_id() -> None:
    conversation_service = FakeConversationService()
    pending_action_service = FakePendingActionService()
    client = TestClient(_authorized_app(conversation_service, pending_action_service))

    messages = client.get("/v1/conversations/conv_test/messages")
    pending_actions = client.get("/v1/conversations/conv_test/pending-actions")

    assert messages.status_code == 200
    assert pending_actions.status_code == 200
    assert messages.json()["data"]["messages"][0]["id"] == "msg_user"
    assert pending_actions.json()["data"]["pending_actions"][0]["pending_action_id"] == "pa_test"
    assert conversation_service.calls[0] == ("messages", "user_test", "conv_test")
    assert pending_action_service.calls[0] == ("pending", "user_test", "conv_test")
