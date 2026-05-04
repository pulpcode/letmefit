from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import create_app
from app.models import User
from app.services.dev_reset import get_dev_reset_service


class FakeDevResetService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def reset_current_user(self, user_id: str) -> dict:
        self.calls.append(f"reset:{user_id}")
        return {
            "deleted": {"conversations": 2, "meal_records": 3},
            "preserved": ["users", "refresh_sessions", "user_profiles"],
        }

    def reset_current_user_full(self, user_id: str) -> dict:
        self.calls.append(f"reset_full:{user_id}")
        return {
            "deleted": {"conversations": 2, "meal_records": 3, "user_profiles": 1},
            "preserved": ["users", "refresh_sessions", "sms_verification_events"],
        }


def _authorized_app(service: FakeDevResetService):
    app = create_app()
    app.dependency_overrides[get_dev_reset_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: User(
        id="user_test",
        phone_number="+8613800138000",
        country_code="86",
        status="active",
    )
    return app


def test_dev_reset_requires_authentication() -> None:
    client = TestClient(create_app())

    response = client.post("/v1/dev/reset-current-user")
    full_response = client.post("/v1/dev/reset-current-user-full")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert full_response.status_code == 401
    assert full_response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_dev_reset_uses_current_user_and_response_envelope() -> None:
    service = FakeDevResetService()
    client = TestClient(_authorized_app(service))

    response = client.post(
        "/v1/dev/reset-current-user",
        headers={"x-request-id": "req_dev_reset"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "req_dev_reset"
    assert body["data"]["deleted"]["meal_records"] == 3
    assert body["data"]["preserved"] == ["users", "refresh_sessions", "user_profiles"]
    assert service.calls == ["reset:user_test"]


def test_dev_reset_full_uses_current_user_and_response_envelope() -> None:
    service = FakeDevResetService()
    client = TestClient(_authorized_app(service))

    response = client.post(
        "/v1/dev/reset-current-user-full",
        headers={"x-request-id": "req_dev_reset_full"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "req_dev_reset_full"
    assert body["data"]["deleted"]["user_profiles"] == 1
    assert body["data"]["preserved"] == [
        "users",
        "refresh_sessions",
        "sms_verification_events",
    ]
    assert service.calls == ["reset_full:user_test"]
