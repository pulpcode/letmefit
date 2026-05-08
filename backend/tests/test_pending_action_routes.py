from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.security import utc_now
from app.core.errors import AppError
from app.main import create_app
from app.models import User
from app.schemas.pending_action import (
    PendingActionContinuationRequest,
    PendingActionUpdateRequest,
)
from app.services.pending_actions import PendingActionService, get_pending_action_service


class FakePendingActionService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def update_action(
        self,
        user_id: str,
        pending_action_id: str,
        payload: PendingActionUpdateRequest,
    ) -> dict:
        self.calls.append(("update", user_id, pending_action_id, payload.draft_payload))
        return {
            "pending_action_id": pending_action_id,
            "type": "create_meal_record",
            "status": "pending_confirmation",
            "confidence": 0.6,
            "draft_payload": payload.draft_payload,
            "warnings": [],
        }

    def confirm_action(
        self,
        user_id: str,
        pending_action_id: str,
        payload: PendingActionContinuationRequest | None = None,
    ) -> dict:
        payload = payload or PendingActionContinuationRequest()
        self.calls.append(("confirm", user_id, pending_action_id, payload.include_agent_trace))
        response = {
            "pending_action_id": pending_action_id,
            "status": "committed",
            "record_type": "meal",
            "record_id": "meal_test",
            "continuation": {
                "assistant_message_id": "msg_continuation",
                "assistant_text": "已确认午餐，我继续安排晚餐。",
                "intent": "answer_fitness_question",
                "requires_review": False,
                "pending_actions": [],
                "committed_records": [],
                "tool_results": [],
            },
        }
        if payload.include_agent_trace:
            response["continuation"]["agent_trace"] = [{"event": "agent_started"}]
        return response

    def discard_action(
        self,
        user_id: str,
        pending_action_id: str,
        payload: PendingActionContinuationRequest | None = None,
    ) -> dict:
        payload = payload or PendingActionContinuationRequest()
        self.calls.append(("discard", user_id, pending_action_id, payload.include_agent_trace))
        response = {
            "pending_action_id": pending_action_id,
            "status": "discarded",
            "continuation": {
                "assistant_message_id": "msg_continuation",
                "assistant_text": "已放弃记录，我继续按不记录午餐处理。",
                "intent": "answer_fitness_question",
                "requires_review": False,
                "pending_actions": [],
                "committed_records": [],
                "tool_results": [],
            },
        }
        if payload.include_agent_trace:
            response["continuation"]["agent_trace"] = [{"event": "agent_started"}]
        return response


def _authorized_app(service: FakePendingActionService):
    app = create_app()
    app.dependency_overrides[get_pending_action_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: User(
        id="user_test",
        phone_number="+8613800138000",
        country_code="86",
        status="active",
    )
    return app


def test_pending_actions_require_authentication() -> None:
    client = TestClient(create_app())

    response = client.post("/v1/agent/pending-actions/pa_test/confirm")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_update_pending_action_uses_current_user() -> None:
    service = FakePendingActionService()
    client = TestClient(_authorized_app(service))

    response = client.patch(
        "/v1/agent/pending-actions/pa_test",
        json={"draft_payload": {"meal_type": "dinner"}, "user_note": "改成晚餐"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["draft_payload"] == {"meal_type": "dinner"}
    assert service.calls[0] == ("update", "user_test", "pa_test", {"meal_type": "dinner"})


def test_confirm_and_discard_pending_action() -> None:
    service = FakePendingActionService()
    client = TestClient(_authorized_app(service))

    confirm = client.post("/v1/agent/pending-actions/pa_test/confirm")
    discard = client.post("/v1/agent/pending-actions/pa_other/discard")

    assert confirm.status_code == 200
    assert confirm.json()["data"]["pending_action_id"] == "pa_test"
    assert confirm.json()["data"]["status"] == "committed"
    assert confirm.json()["data"]["continuation"]["assistant_message_id"] == "msg_continuation"
    assert discard.status_code == 200
    assert discard.json()["data"]["pending_action_id"] == "pa_other"
    assert discard.json()["data"]["status"] == "discarded"
    assert discard.json()["data"]["continuation"]["assistant_message_id"] == "msg_continuation"
    assert service.calls == [
        ("confirm", "user_test", "pa_test", False),
        ("discard", "user_test", "pa_other", False),
    ]


def test_confirm_and_discard_include_agent_trace_when_requested() -> None:
    service = FakePendingActionService()
    client = TestClient(_authorized_app(service))

    confirm = client.post(
        "/v1/agent/pending-actions/pa_test/confirm",
        json={"include_agent_trace": True},
    )
    discard = client.post(
        "/v1/agent/pending-actions/pa_other/discard",
        json={"include_agent_trace": True},
    )

    assert confirm.status_code == 200
    assert confirm.json()["data"]["continuation"]["assistant_message_id"] == "msg_continuation"
    assert confirm.json()["data"]["continuation"]["agent_trace"][0]["event"] == "agent_started"
    assert discard.status_code == 200
    assert discard.json()["data"]["continuation"]["assistant_message_id"] == "msg_continuation"
    assert discard.json()["data"]["continuation"]["agent_trace"][0]["event"] == "agent_started"
    assert service.calls == [
        ("confirm", "user_test", "pa_test", True),
        ("discard", "user_test", "pa_other", True),
    ]


def test_run_continuation_passes_pending_action_observation_context(monkeypatch) -> None:
    captured: dict = {}

    class FakeDb:
        def __init__(self) -> None:
            self.conversation = SimpleNamespace(
                id="conv_test",
                user_id="user_test",
                dialogue_state_json={},
                dialogue_state_updated_at=None,
            )
            self.added = []

        def scalar(self, query):
            return self.conversation

        def add(self, value) -> None:
            self.added.append(value)

        def commit(self) -> None:
            pass

    class FakeContextBuilder:
        def __init__(self, db) -> None:
            self.db = db

        def build(self, **kwargs):
            return {
                "recent_messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "中午吃了炒面，安排晚餐"}],
                    }
                ]
            }

    class FakeAgentRuntime:
        def __init__(self, db) -> None:
            self.db = db

        def run(self, **kwargs):
            captured.update(kwargs)
            return {
                "assistant_text": "已确认午餐，我继续安排晚餐。",
                "assistant_content": [{"type": "text", "text": "已确认午餐，我继续安排晚餐。"}],
                "intent": "answer_fitness_question",
                "requires_review": False,
                "pending_actions": [],
                "committed_records": [],
                "tool_results": [],
                "agent_trace": [{"event": "agent_started"}],
            }

    monkeypatch.setattr(
        "app.services.pending_actions.ConversationContextBuilder",
        FakeContextBuilder,
    )
    monkeypatch.setattr("app.services.pending_actions.AgentRuntime", FakeAgentRuntime)
    db = FakeDb()
    service = PendingActionService(db=db)

    response = service._run_continuation(
        action=SimpleNamespace(
            id="pa_test",
            user_id="user_test",
            conversation_id="conv_test",
        ),
        observation={
            "type": "pending_action_observation",
            "event": "confirmed",
            "pending_action_id": "pa_test",
            "action_type": "create_meal_record",
            "text": "用户已确认待确认动作。",
        },
        event_message_id="msg_event",
        include_agent_trace=True,
    )

    assert captured["message_id"] == "msg_event"
    assert captured["context"]["input_origin"] == "pending_action_observation"
    assert captured["context"]["current_observation"]["pending_action_id"] == "pa_test"
    assert captured["context"]["recent_messages"][0]["role"] == "user"
    assert captured["content"][0].source == "pending_action_observation"
    assert response["agent_trace"][0]["event"] == "agent_started"
    assert db.added[0].role == "assistant"


def test_committed_event_text_summarizes_meal_items() -> None:
    service = PendingActionService(db=object())

    text = service._record_committed_text(
        "meal",
        {
            "meal_type": "breakfast",
            "total_calories": 156.0,
            "items": [{"name": "鸡蛋", "portion_text": "2个"}],
        },
    )

    assert text == "已保存到正式记录：早餐，鸡蛋（2个），约 156 千卡。"


def test_update_action_status_is_decided_by_backend_rules() -> None:
    action = SimpleNamespace(
        id="pa_test",
        user_id="user_test",
        action_type="create_meal_record",
        status="pending_confirmation",
        draft_payload_json={
            "recorded_at": "2026-05-01T12:30:00+08:00",
            "source_type": "text",
            "meal_type": "lunch",
            "items": [{"name": "炒面", "portion_text": "300g", "portion_grams": 300}],
        },
        warnings_json=[],
        expires_at=None,
        confidence=None,
        created_at=None,
        updated_at=None,
    )

    class FakeDb:
        def scalar(self, query):
            return action

        def flush(self):
            pass

    service = PendingActionService(db=FakeDb())

    fuzzy = service.update_action(
        "user_test",
        "pa_test",
        PendingActionUpdateRequest(
            draft_payload={"items": [{"name": "炒面", "portion_text": "比300g少一点"}]}
        ),
        commit=False,
    )
    precise = service.update_action(
        "user_test",
        "pa_test",
        PendingActionUpdateRequest(
            draft_payload={"items": [{"name": "炒面", "portion_text": "200g", "portion_grams": 200}]}
        ),
        commit=False,
    )

    assert fuzzy["status"] == "needs_clarification"
    assert fuzzy["warnings"][-1]["reason"] == "needs_clarification"
    assert precise["status"] == "pending_confirmation"
    assert precise["warnings"] == []


def test_list_for_conversation_marks_expired_actions() -> None:
    now = utc_now()
    expired = SimpleNamespace(
        id="pa_old",
        user_id="user_test",
        action_type="create_meal_record",
        status="pending_confirmation",
        draft_payload_json={"meal_type": "lunch", "items": [{"name": "炒面"}]},
        warnings_json=[],
        expires_at=now - timedelta(minutes=1),
        confidence=None,
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(days=1),
    )
    fresh = SimpleNamespace(
        id="pa_new",
        user_id="user_test",
        action_type="create_meal_record",
        status="pending_confirmation",
        draft_payload_json={"meal_type": "lunch", "items": [{"name": "炒面"}]},
        warnings_json=[],
        expires_at=now + timedelta(hours=1),
        confidence=None,
        created_at=now,
        updated_at=now,
    )

    class FakeDb:
        def __init__(self) -> None:
            self.commit_count = 0

        def scalar(self, query):
            return SimpleNamespace(id="conv_test")

        def scalars(self, query):
            return [expired, fresh]

        def commit(self):
            self.commit_count += 1

    db = FakeDb()
    service = PendingActionService(db=db)

    response = service.list_for_conversation("user_test", "conv_test")

    assert expired.status == "expired"
    assert fresh.status == "pending_confirmation"
    assert db.commit_count == 1
    assert [item["status"] for item in response["pending_actions"]] == [
        "expired",
        "pending_confirmation",
    ]


def test_needs_clarification_cannot_be_confirmed() -> None:
    class FakeDb:
        def flush(self):
            pass

    service = PendingActionService(db=FakeDb())
    action = SimpleNamespace(status="needs_clarification", expires_at=None)

    with pytest.raises(AppError) as exc:
        service._ensure_confirmable(action)

    assert exc.value.code == "PENDING_ACTION_NEEDS_CLARIFICATION"
