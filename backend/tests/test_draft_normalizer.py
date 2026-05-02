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


def test_normalize_body_metric_draft_keeps_payload() -> None:
    draft = {"source_type": "text", "weight_kg": 72.4}

    normalized = normalize_pending_action_draft("create_body_metric_record", draft)

    assert normalized == draft
    assert normalized is not draft
