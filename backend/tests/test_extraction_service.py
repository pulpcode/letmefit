from datetime import datetime
from decimal import Decimal

from app.ai.extraction_service import ExtractionService
from app.ai.providers.base import ExtractionProvider
from app.ai.types import ExtractionActionSpec, ExtractionInput, ExtractionProviderResult
from app.core.config import Settings
from app.schemas.conversation import MessageContentItem


class FakeDb:
    def __init__(self) -> None:
        self.added = []
        self.flush_count = 0

    def add(self, value) -> None:
        self.added.append(value)

    def flush(self) -> None:
        self.flush_count += 1


class FakeProvider(ExtractionProvider):
    provider_name = "fake"

    def __init__(self, result: ExtractionProviderResult) -> None:
        self.result = result

    def extract(self, payload: ExtractionInput) -> ExtractionProviderResult:
        return self.result

    def last_debug_request_body(self):
        return None


class FakeBodyMetricService:
    def __init__(self, db) -> None:
        self.db = db

    def create_body_metric(self, user_id, payload, commit=True):
        return {
            "id": "bm_auto",
            "recorded_at": payload.recorded_at,
            "recorded_tz": payload.recorded_tz,
            "local_date": datetime(2026, 5, 1).date(),
            "source_type": payload.source_type,
            "weight_kg": float(payload.weight_kg),
            "body_fat_percentage": None,
            "bmi": None,
            "muscle_mass_kg": None,
            "water_percentage": None,
            "confidence": 0.9,
            "source_pending_action_id": None,
        }


def _settings() -> Settings:
    return Settings(jwt_secret_key="test-secret-key-with-enough-length")


def test_extraction_service_auto_commits_clear_body_metric(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.extraction_service.BodyMetricService", FakeBodyMetricService)
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我识别到体重记录。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.90"),
            action_specs=[
                ExtractionActionSpec(
                    action_type="create_body_metric_record",
                    confidence=Decimal("0.90"),
                    draft_payload={
                        "recorded_at": "2026-05-01T08:10:00+08:00",
                        "source_type": "text",
                        "weight_kg": 72.4,
                    },
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="我今天体重72.4公斤")],
        context={},
    )

    assert result["requires_review"] is False
    assert result["pending_actions"] == []
    assert result["committed_records"][0]["type"] == "body_metric"
    assert result["committed_records"][0]["record_id"] == "bm_auto"
    assert result["assistant_content"][0]["event_type"] == "record_auto_committed"
    assert "已自动保存" in result["assistant_text"]


def test_extraction_service_keeps_fuzzy_meal_as_pending() -> None:
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我先整理成餐食草稿，请确认。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.90"),
            action_specs=[
                ExtractionActionSpec(
                    action_type="create_meal_record",
                    confidence=Decimal("0.90"),
                    draft_payload={
                        "recorded_at": "2026-05-01T12:30:00+08:00",
                        "source_type": "text",
                        "meal_type": "lunch",
                        "items": [{"name": "米饭", "portion_text": "一碗"}],
                    },
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="午餐吃了一碗米饭")],
        context={},
    )

    assert result["requires_review"] is True
    assert result["committed_records"] == []
    assert result["pending_actions"][0]["type"] == "create_meal_record"


def test_extraction_service_normalizes_backfilled_meal_time(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.ai.extraction_service.utc_now",
        lambda: datetime.fromisoformat("2026-05-01T07:20:00"),
    )
    provider = FakeProvider(
        ExtractionProviderResult(
            assistant_text="我先整理成餐食草稿，请确认。",
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.70"),
            action_specs=[
                ExtractionActionSpec(
                    action_type="create_meal_record",
                    confidence=Decimal("0.70"),
                    draft_payload={
                        "recorded_at": "2026-05-01T23:00:00+08:00",
                        "recorded_tz": "Asia/Shanghai",
                        "source_type": "voice",
                        "meal_type": "breakfast",
                        "items": [{"name": "面包", "portion_text": "2片"}],
                    },
                    warnings=[],
                )
            ],
        )
    )
    service = ExtractionService(FakeDb(), settings=_settings(), provider=provider)

    result = service.process_message(
        user_id="user_test",
        conversation_id="conv_test",
        message_id="msg_test",
        content=[MessageContentItem(type="text", text="语音转写: 我早上吃了两片面包")],
        context={},
    )

    assert result["pending_actions"][0]["draft_payload"]["recorded_at"] == (
        "2026-05-01T08:00:00+08:00"
    )
