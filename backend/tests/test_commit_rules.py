from decimal import Decimal

from app.ai.commit_rules import decide_auto_commit


def test_auto_commit_rules_are_disabled_by_default() -> None:
    decision = decide_auto_commit(
        action_type="create_body_metric_record",
        draft_payload={
            "recorded_at": "2026-05-01T08:10:00+08:00",
            "recorded_tz": "Asia/Shanghai",
            "source_type": "text",
            "weight_kg": 72.4,
        },
        confidence=Decimal("0.99"),
        warnings=[],
        provider_warnings=[],
        input_types=["text"],
        input_text="我今天体重72.4公斤",
        input_normalization={},
    )

    assert decision.auto_commit is False
    assert decision.reason == "confirmation_required"
