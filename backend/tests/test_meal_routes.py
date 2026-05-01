from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import create_app
from app.models import User
from app.schemas.records import MealCreateRequest, MealPatchRequest
from app.services.meals import get_meal_service


class FakeMealService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def list_meals(self, user_id: str, local_date=None) -> dict:
        self.calls.append(("list", user_id, local_date))
        return {"meals": []}

    def get_meal(self, user_id: str, meal_id: str) -> dict:
        self.calls.append(("get", user_id, meal_id))
        return self._meal(meal_id)

    def create_meal(self, user_id: str, payload: MealCreateRequest) -> dict:
        self.calls.append(("create", user_id, payload))
        return self._meal("meal_test")

    def update_meal(self, user_id: str, meal_id: str, payload: MealPatchRequest) -> dict:
        self.calls.append(("update", user_id, meal_id, payload))
        return self._meal(meal_id)

    def delete_meal(self, user_id: str, meal_id: str) -> dict:
        self.calls.append(("delete", user_id, meal_id))
        return {"success": True}

    def _meal(self, meal_id: str) -> dict:
        return {
            "id": meal_id,
            "recorded_at": "2026-05-01T04:30:00",
            "recorded_tz": "Asia/Shanghai",
            "local_date": "2026-05-01",
            "source_type": "manual",
            "meal_type": "lunch",
            "total_calories": 198.0,
            "total_protein_g": 37.0,
            "total_carbs_g": 0.0,
            "total_fat_g": 4.0,
            "confidence": 0.9,
            "source_pending_action_id": None,
            "notes": None,
            "items": [
                {
                    "id": "mi_test",
                    "name": "鸡胸肉",
                    "alias": None,
                    "portion_text": "约120g",
                    "portion_grams": 120.0,
                    "calories": 198.0,
                    "protein_g": 37.0,
                    "carbs_g": 0.0,
                    "fat_g": 4.0,
                    "confidence": 0.9,
                    "user_corrected": False,
                }
            ],
        }


def _authorized_app(service: FakeMealService):
    app = create_app()
    app.dependency_overrides[get_meal_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: User(
        id="user_test",
        phone_number="+8613800138000",
        country_code="86",
        status="active",
    )
    return app


def test_meals_require_authentication() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/meals")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_list_meals_uses_current_user_and_date_filter() -> None:
    service = FakeMealService()
    client = TestClient(_authorized_app(service))

    response = client.get("/v1/meals?date=2026-05-01")

    assert response.status_code == 200
    assert response.json()["data"] == {"meals": []}
    assert service.calls[0][0] == "list"
    assert service.calls[0][1] == "user_test"
    assert service.calls[0][2].isoformat() == "2026-05-01"


def test_create_meal_returns_response_envelope() -> None:
    service = FakeMealService()
    client = TestClient(_authorized_app(service))

    response = client.post(
        "/v1/meals",
        json={
            "recorded_at": "2026-05-01T12:30:00+08:00",
            "source_type": "manual",
            "meal_type": "lunch",
            "items": [
                {
                    "name": "鸡胸肉",
                    "portion_text": "约120g",
                    "portion_grams": 120,
                    "calories": 198,
                    "protein_g": 37,
                    "carbs_g": 0,
                    "fat_g": 4,
                    "confidence": 0.9,
                }
            ],
        },
        headers={"x-request-id": "req_meal"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "req_meal"
    assert body["data"]["id"] == "meal_test"
    assert body["data"]["items"][0]["name"] == "鸡胸肉"
    assert service.calls[0][0] == "create"
    assert service.calls[0][1] == "user_test"


def test_update_and_delete_meal_use_path_id() -> None:
    service = FakeMealService()
    client = TestClient(_authorized_app(service))

    update = client.patch("/v1/meals/meal_test", json={"notes": "少油"})
    delete = client.delete("/v1/meals/meal_test")

    assert update.status_code == 200
    assert delete.status_code == 200
    assert service.calls[0][0:3] == ("update", "user_test", "meal_test")
    assert service.calls[1] == ("delete", "user_test", "meal_test")
