from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import create_app
from app.models import User
from app.schemas.pending_action import PendingActionUpdateRequest
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

    def confirm_action(self, user_id: str, pending_action_id: str) -> dict:
        self.calls.append(("confirm", user_id, pending_action_id))
        return {
            "pending_action_id": pending_action_id,
            "status": "committed",
            "record_type": "meal",
            "record_id": "meal_test",
        }

    def discard_action(self, user_id: str, pending_action_id: str) -> dict:
        self.calls.append(("discard", user_id, pending_action_id))
        return {
            "pending_action_id": pending_action_id,
            "status": "discarded",
        }


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
    assert confirm.json()["data"] == {
        "pending_action_id": "pa_test",
        "status": "committed",
        "record_type": "meal",
        "record_id": "meal_test",
    }
    assert discard.status_code == 200
    assert discard.json()["data"] == {
        "pending_action_id": "pa_other",
        "status": "discarded",
    }
    assert service.calls == [
        ("confirm", "user_test", "pa_test"),
        ("discard", "user_test", "pa_other"),
    ]


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
