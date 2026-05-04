from datetime import UTC, datetime

from app.ai.draft_normalizer import normalize_pending_action_draft


def test_normalize_meal_draft_converts_string_items_to_objects() -> None:
    normalized = normalize_pending_action_draft(
        "create_meal_record",
        {
            "recorded_at": "2026-05-02T12:30:00+08:00",
            "source_type": "text",
            "meal_type": "lunch",
            "items": ["鸡胸肉", "米饭"],
        },
    )

    assert normalized["items"] == [{"name": "鸡胸肉"}, {"name": "米饭"}]


def test_normalize_meal_draft_maps_common_name_aliases() -> None:
    normalized = normalize_pending_action_draft(
        "create_meal_record",
        {
            "items": [
                {"food_name": "鸡蛋", "portion_text": "2个"},
                {"food": "燕麦"},
            ],
        },
    )

    assert normalized["items"][0]["name"] == "鸡蛋"
    assert normalized["items"][0]["portion_text"] == "2个"
    assert normalized["items"][1]["name"] == "燕麦"


def test_normalize_meal_draft_maps_nutrition_aliases_and_quantity() -> None:
    normalized = normalize_pending_action_draft(
        "create_meal_record",
        {
            "items": [
                {
                    "food": "全麦面包",
                    "quantity": 2,
                    "unit": "片",
                    "calories_kcal": 160,
                    "protein": 6,
                    "carbs": 28,
                    "fat": 2,
                }
            ],
        },
    )

    item = normalized["items"][0]
    assert item["name"] == "全麦面包"
    assert item["portion_text"] == "2片"
    assert item["calories"] == 160
    assert item["protein_g"] == 6
    assert item["carbs_g"] == 28
    assert item["fat_g"] == 2


def test_normalize_meal_draft_uses_current_time_when_meal_matches_window() -> None:
    normalized = normalize_pending_action_draft(
        "create_meal_record",
        {
            "recorded_at": "2026-05-01T04:00:00+08:00",
            "recorded_tz": "Asia/Shanghai",
            "source_type": "voice",
            "meal_type": "lunch",
            "items": [{"name": "鸡胸肉"}],
        },
        input_text="语音转写: 我中午吃了鸡胸肉",
        now=datetime(2026, 5, 1, 4, 20, 30, tzinfo=UTC),
    )

    assert normalized["recorded_at"] == "2026-05-01T12:20:00+08:00"


def test_normalize_meal_draft_uses_default_time_for_backfilled_meal() -> None:
    normalized = normalize_pending_action_draft(
        "create_meal_record",
        {
            "recorded_at": "2026-05-01T23:00:00+08:00",
            "recorded_tz": "Asia/Shanghai",
            "source_type": "voice",
            "meal_type": "breakfast",
            "items": [{"name": "面包"}],
        },
        input_text="语音转写: 我早上吃了两片面包",
        now=datetime(2026, 5, 1, 7, 20, 0, tzinfo=UTC),
    )

    assert normalized["recorded_at"] == "2026-05-01T08:00:00+08:00"


def test_normalize_meal_draft_preserves_explicit_clock_time() -> None:
    normalized = normalize_pending_action_draft(
        "create_meal_record",
        {
            "recorded_at": "2026-05-01T12:30:00+08:00",
            "recorded_tz": "Asia/Shanghai",
            "source_type": "text",
            "meal_type": "lunch",
            "items": [{"name": "米饭"}],
        },
        input_text="今天12:30吃了米饭",
        now=datetime(2026, 5, 1, 7, 20, 0, tzinfo=UTC),
    )

    assert normalized["recorded_at"] == "2026-05-01T12:30:00+08:00"


def test_normalize_body_metric_draft_keeps_payload() -> None:
    draft = {"source_type": "text", "weight_kg": 72.4}

    normalized = normalize_pending_action_draft("create_body_metric_record", draft)

    assert normalized == draft
    assert normalized is not draft
