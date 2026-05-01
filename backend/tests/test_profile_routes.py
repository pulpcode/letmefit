from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import create_app
from app.models import User
from app.schemas.profile import ProfileUpsertRequest
from app.services.profile import get_profile_service


class FakeProfileService:
    def __init__(self) -> None:
        self.user_id: str | None = None
        self.payload: ProfileUpsertRequest | None = None

    def get_profile(self, user_id: str) -> dict:
        self.user_id = user_id
        return {
            "profile": None,
            "profile_completed": False,
        }

    def upsert_profile(self, user_id: str, payload: ProfileUpsertRequest) -> dict:
        self.user_id = user_id
        self.payload = payload
        return {
            "profile": {
                "id": "profile_test",
                "age": payload.age,
                "sex": payload.sex,
                "height_cm": float(payload.height_cm),
                "current_weight_kg": float(payload.current_weight_kg),
                "target_weight_kg": float(payload.target_weight_kg),
                "activity_level": payload.activity_level,
                "goal_type": payload.goal_type,
                "completed_at": "2026-05-01T00:00:00",
            },
            "profile_completed": True,
        }


def test_profile_requires_authentication() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/profile")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_get_profile_uses_current_user() -> None:
    app = create_app()
    service = FakeProfileService()
    app.dependency_overrides[get_profile_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: User(
        id="user_test",
        phone_number="+8613800138000",
        country_code="86",
        status="active",
    )
    client = TestClient(app)

    response = client.get("/v1/profile")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "profile": None,
        "profile_completed": False,
    }
    assert service.user_id == "user_test"


def test_put_profile_uses_current_user_and_response_envelope() -> None:
    app = create_app()
    service = FakeProfileService()
    app.dependency_overrides[get_profile_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: User(
        id="user_test",
        phone_number="+8613800138000",
        country_code="86",
        status="active",
    )
    client = TestClient(app)

    response = client.put(
        "/v1/profile",
        json={
            "age": 30,
            "sex": "male",
            "height_cm": 175,
            "current_weight_kg": 72.4,
            "target_weight_kg": 68,
            "activity_level": "moderate",
            "goal_type": "fat_loss",
        },
        headers={"x-request-id": "req_profile"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "req_profile"
    assert body["data"]["profile_completed"] is True
    assert body["data"]["profile"]["id"] == "profile_test"
    assert service.user_id == "user_test"
    assert service.payload is not None
    assert service.payload.goal_type == "fat_loss"


def test_put_profile_validates_domain_values() -> None:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="user_test",
        phone_number="+8613800138000",
        country_code="86",
        status="active",
    )
    client = TestClient(app)

    response = client.put("/v1/profile", json={"goal_type": "medical_treatment"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
