from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import create_app
from app.models import User
from app.schemas.records import BodyMetricCreateRequest, BodyMetricPatchRequest
from app.services.body_metrics import get_body_metric_service


class FakeBodyMetricService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def list_body_metrics(self, user_id: str, date_from=None, date_to=None) -> dict:
        self.calls.append(("list", user_id, date_from, date_to))
        return {"body_metrics": []}

    def get_body_metric(self, user_id: str, body_metric_id: str) -> dict:
        self.calls.append(("get", user_id, body_metric_id))
        return self._record(body_metric_id)

    def create_body_metric(self, user_id: str, payload: BodyMetricCreateRequest) -> dict:
        self.calls.append(("create", user_id, payload))
        return self._record("bm_test")

    def update_body_metric(
        self,
        user_id: str,
        body_metric_id: str,
        payload: BodyMetricPatchRequest,
    ) -> dict:
        self.calls.append(("update", user_id, body_metric_id, payload))
        return self._record(body_metric_id)

    def delete_body_metric(self, user_id: str, body_metric_id: str) -> dict:
        self.calls.append(("delete", user_id, body_metric_id))
        return {"success": True}

    def _record(self, body_metric_id: str) -> dict:
        return {
            "id": body_metric_id,
            "recorded_at": "2026-05-01T00:10:00",
            "recorded_tz": "Asia/Shanghai",
            "local_date": "2026-05-01",
            "source_type": "manual",
            "weight_kg": 72.4,
            "body_fat_percentage": 18.6,
            "bmi": 23.1,
            "muscle_mass_kg": None,
            "water_percentage": None,
            "confidence": 0.8,
            "source_pending_action_id": None,
        }


def _authorized_app(service: FakeBodyMetricService):
    app = create_app()
    app.dependency_overrides[get_body_metric_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: User(
        id="user_test",
        phone_number="+8613800138000",
        country_code="86",
        status="active",
    )
    return app


def test_body_metrics_require_authentication() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/body-metrics")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_list_body_metrics_uses_current_user_and_date_range() -> None:
    service = FakeBodyMetricService()
    client = TestClient(_authorized_app(service))

    response = client.get("/v1/body-metrics?date_from=2026-04-01&date_to=2026-05-01")

    assert response.status_code == 200
    assert response.json()["data"] == {"body_metrics": []}
    assert service.calls[0][0] == "list"
    assert service.calls[0][1] == "user_test"
    assert service.calls[0][2].isoformat() == "2026-04-01"
    assert service.calls[0][3].isoformat() == "2026-05-01"


def test_create_body_metric_returns_response_envelope() -> None:
    service = FakeBodyMetricService()
    client = TestClient(_authorized_app(service))

    response = client.post(
        "/v1/body-metrics",
        json={
            "recorded_at": "2026-05-01T08:10:00+08:00",
            "source_type": "manual",
            "weight_kg": 72.4,
            "body_fat_percentage": 18.6,
            "bmi": 23.1,
            "confidence": 0.8,
        },
        headers={"x-request-id": "req_body_metric"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "req_body_metric"
    assert body["data"]["id"] == "bm_test"
    assert body["data"]["weight_kg"] == 72.4
    assert service.calls[0][0] == "create"
    assert service.calls[0][1] == "user_test"


def test_update_and_delete_body_metric_use_path_id() -> None:
    service = FakeBodyMetricService()
    client = TestClient(_authorized_app(service))

    update = client.patch("/v1/body-metrics/bm_test", json={"weight_kg": 72.1})
    delete = client.delete("/v1/body-metrics/bm_test")

    assert update.status_code == 200
    assert delete.status_code == 200
    assert service.calls[0][0:3] == ("update", "user_test", "bm_test")
    assert service.calls[1] == ("delete", "user_test", "bm_test")
