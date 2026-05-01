from fastapi import Request
from fastapi.testclient import TestClient

from app.auth.service import get_auth_service
from app.main import create_app


class FakeAuthService:
    def send_sms(self, phone_number: str, purpose: str, request: Request) -> dict:
        return {
            "cooldown_seconds": 60,
            "expires_in_seconds": 300,
        }

    def verify_sms(self, phone_number: str, code: str, request: Request) -> dict:
        return {
            "access_token": "access_test",
            "refresh_token": "refresh_test",
            "token_type": "bearer",
            "expires_in_seconds": 1800,
            "user": {
                "id": "user_test",
                "phone_number": "+8613800138000",
                "profile_completed": False,
            },
        }

    def refresh_access_token(self, refresh_token: str) -> dict:
        return {
            "access_token": "access_refreshed",
            "expires_in_seconds": 1800,
        }

    def logout(self, refresh_token: str) -> dict:
        return {"success": True}


def test_sms_send_route_uses_response_envelope() -> None:
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    client = TestClient(app)

    response = client.post(
        "/v1/auth/sms/send",
        json={"phone_number": "13800138000", "purpose": "login"},
        headers={"x-request-id": "req_auth_send"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "cooldown_seconds": 60,
            "expires_in_seconds": 300,
        },
        "request_id": "req_auth_send",
    }


def test_sms_verify_route_returns_tokens_and_user() -> None:
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    client = TestClient(app)

    response = client.post(
        "/v1/auth/sms/verify",
        json={"phone_number": "13800138000", "code": "123456"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["token_type"] == "bearer"
    assert data["access_token"] == "access_test"
    assert data["refresh_token"] == "refresh_test"
    assert data["user"]["id"] == "user_test"


def test_refresh_route_uses_response_envelope() -> None:
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    client = TestClient(app)

    response = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": "rt_test_token_long_enough"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "access_token": "access_refreshed",
        "expires_in_seconds": 1800,
    }


def test_logout_route_uses_response_envelope() -> None:
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    client = TestClient(app)

    response = client.post(
        "/v1/auth/logout",
        json={"refresh_token": "rt_test_token_long_enough"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"success": True}


def test_validation_error_uses_error_envelope() -> None:
    client = TestClient(create_app())

    response = client.post("/v1/auth/sms/send", json={"phone_number": "bad"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "请求参数不正确"
    assert body["request_id"].startswith("req_")
