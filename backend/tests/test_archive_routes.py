from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import create_app
from app.models import User
from app.schemas.archive import SummaryGenerateRequest
from app.services.archives import get_daily_archive_service, get_daily_summary_service


class FakeDailyArchiveService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_archive(self, user_id: str, archive_date, timezone: str = "Asia/Shanghai") -> dict:
        self.calls.append(("archive", user_id, archive_date, timezone))
        return {
            "archive": {
                "id": "archive_test",
                "date": archive_date.isoformat(),
                "timezone": timezone,
                "meal_count": 2,
                "body_metric_count": 1,
                "calorie_total": 600.0,
                "protein_total_g": 50.0,
                "carbs_total_g": 40.0,
                "fat_total_g": 20.0,
                "completeness_score": 0.7667,
                "last_calculated_at": "2026-05-01T12:00:00",
            }
        }


class FakeDailySummaryService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def generate_summary(
        self,
        user_id: str,
        summary_date,
        timezone: str = "Asia/Shanghai",
    ) -> dict:
        self.calls.append(("summary", user_id, summary_date, timezone))
        return {
            "summary": {
                "id": "summary_test",
                "date": summary_date.isoformat(),
                "archive_id": "archive_test",
                "calorie_total": 600.0,
                "protein_total_g": 50.0,
                "carbs_total_g": 40.0,
                "fat_total_g": 20.0,
                "meal_count": 2,
                "body_metric_count": 1,
                "summary_text": "今天记录了 2 条餐食。",
                "suggestions": ["餐食记录还不完整，建议补齐三餐后再看全天趋势。"],
                "completeness_score": 0.7667,
                "generation_status": "generated",
            }
        }


def _authorized_app(
    archive_service: FakeDailyArchiveService | None = None,
    summary_service: FakeDailySummaryService | None = None,
):
    app = create_app()
    if archive_service:
        app.dependency_overrides[get_daily_archive_service] = lambda: archive_service
    if summary_service:
        app.dependency_overrides[get_daily_summary_service] = lambda: summary_service
    app.dependency_overrides[get_current_user] = lambda: User(
        id="user_test",
        phone_number="+8613800138000",
        country_code="86",
        status="active",
    )
    return app


def test_daily_archive_requires_authentication() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/daily-archives/2026-05-01")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_get_daily_archive_uses_current_user_and_date() -> None:
    service = FakeDailyArchiveService()
    client = TestClient(_authorized_app(archive_service=service))

    response = client.get("/v1/daily-archives/2026-05-01")

    assert response.status_code == 200
    assert response.json()["data"]["archive"]["id"] == "archive_test"
    assert service.calls[0][0] == "archive"
    assert service.calls[0][1] == "user_test"
    assert service.calls[0][2].isoformat() == "2026-05-01"


def test_generate_summary_uses_current_user_and_payload() -> None:
    service = FakeDailySummaryService()
    client = TestClient(_authorized_app(summary_service=service))

    response = client.post(
        "/v1/summaries/generate",
        json={"date": "2026-05-01", "timezone": "Asia/Shanghai"},
        headers={"x-request-id": "req_summary"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "req_summary"
    assert body["data"]["summary"]["id"] == "summary_test"
    assert body["data"]["summary"]["generation_status"] == "generated"
    assert service.calls[0][0] == "summary"
    assert service.calls[0][1] == "user_test"
    assert service.calls[0][2].isoformat() == "2026-05-01"


def test_summary_generate_request_defaults_timezone() -> None:
    payload = SummaryGenerateRequest.model_validate({"date": "2026-05-01"})

    assert payload.timezone == "Asia/Shanghai"
