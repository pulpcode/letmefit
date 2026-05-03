from decimal import Decimal

from app.ai.commit_rules import decide_auto_commit


def _base_meal() -> dict:
    return {
        "recorded_at": "2026-05-01T12:30:00+08:00",
        "recorded_tz": "Asia/Shanghai",
        "source_type": "text",
        "meal_type": "lunch",
        "items": [
            {
                "name": "鸡胸肉",
                "portion_grams": 150,
                "portion_text": "150g",
            }
        ],
    }


def _base_body_metric() -> dict:
    return {
        "recorded_at": "2026-05-01T08:10:00+08:00",
        "recorded_tz": "Asia/Shanghai",
        "source_type": "text",
        "weight_kg": 72.4,
    }


def test_clear_body_metric_can_auto_commit() -> None:
    decision = decide_auto_commit(
        action_type="create_body_metric_record",
        draft_payload=_base_body_metric(),
        confidence=Decimal("0.90"),
        warnings=[],
        provider_warnings=[],
        input_types=["text"],
        input_text="我今天体重72.4公斤",
        input_normalization={},
    )

    assert decision.auto_commit is True
    assert decision.reason == "clear_body_metric"


def test_clear_meal_with_explicit_grams_can_auto_commit() -> None:
    decision = decide_auto_commit(
        action_type="create_meal_record",
        draft_payload=_base_meal(),
        confidence=Decimal("0.90"),
        warnings=[],
        provider_warnings=[],
        input_types=["text"],
        input_text="午餐吃了150克鸡胸肉",
        input_normalization={},
    )

    assert decision.auto_commit is True
    assert decision.reason == "clear_meal_with_grams"


def test_clear_voice_transcript_can_auto_commit() -> None:
    decision = decide_auto_commit(
        action_type="create_body_metric_record",
        draft_payload=_base_body_metric() | {"source_type": "voice"},
        confidence=Decimal("0.90"),
        warnings=[],
        provider_warnings=[],
        input_types=["audio", "text"],
        input_text="语音转写: 我今天体重72.4公斤",
        input_normalization={"media": [{"type": "audio", "status": "transcribed"}]},
    )

    assert decision.auto_commit is True
    assert decision.reason == "clear_body_metric"


def test_fuzzy_meal_requires_confirmation() -> None:
    draft = _base_meal()
    draft["items"][0]["portion_grams"] = None
    decision = decide_auto_commit(
        action_type="create_meal_record",
        draft_payload=draft,
        confidence=Decimal("0.90"),
        warnings=[],
        provider_warnings=[],
        input_types=["text"],
        input_text="午餐吃了一碗米饭",
        input_normalization={},
    )

    assert decision.auto_commit is False
    assert decision.reason == "no_explicit_gram_unit"


def test_images_and_warnings_require_confirmation() -> None:
    image_decision = decide_auto_commit(
        action_type="create_body_metric_record",
        draft_payload=_base_body_metric() | {"source_type": "scale_photo"},
        confidence=Decimal("0.95"),
        warnings=[],
        provider_warnings=[],
        input_types=["image", "text"],
        input_text="帮我识别体重秤",
        input_normalization={"media": [{"status": "described"}]},
    )
    warning_decision = decide_auto_commit(
        action_type="create_body_metric_record",
        draft_payload=_base_body_metric(),
        confidence=Decimal("0.95"),
        warnings=[{"field": "weight_kg", "reason": "low_confidence"}],
        provider_warnings=[],
        input_types=["text"],
        input_text="体重可能是72.4公斤",
        input_normalization={},
    )

    assert image_decision.auto_commit is False
    assert image_decision.reason == "image_requires_confirmation"
    assert warning_decision.auto_commit is False
    assert warning_decision.reason == "has_warnings"


def test_low_confidence_or_unprocessed_media_requires_confirmation() -> None:
    low_confidence = decide_auto_commit(
        action_type="create_body_metric_record",
        draft_payload=_base_body_metric(),
        confidence=Decimal("0.84"),
        warnings=[],
        provider_warnings=[],
        input_types=["text"],
        input_text="体重72.4公斤",
        input_normalization={},
    )
    unprocessed_media = decide_auto_commit(
        action_type="create_body_metric_record",
        draft_payload=_base_body_metric() | {"source_type": "voice"},
        confidence=Decimal("0.95"),
        warnings=[],
        provider_warnings=[],
        input_types=["audio", "text"],
        input_text="语音转写: 体重72.4公斤",
        input_normalization={"media": [{"status": "unprocessed"}]},
    )

    assert low_confidence.auto_commit is False
    assert low_confidence.reason == "low_confidence"
    assert unprocessed_media.auto_commit is False
    assert unprocessed_media.reason == "has_unprocessed_media"
