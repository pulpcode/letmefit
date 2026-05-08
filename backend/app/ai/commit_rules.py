from dataclasses import dataclass
from decimal import Decimal
from typing import Any

AUTO_COMMIT_CONFIDENCE_THRESHOLD = Decimal("0.85")


@dataclass(frozen=True)
class CommitDecision:
    auto_commit: bool
    reason: str


def decide_auto_commit(
    action_type: str,
    draft_payload: dict[str, Any],
    confidence: Decimal | None,
    warnings: list[dict[str, Any]],
    provider_warnings: list[dict[str, Any]],
    input_types: list[str],
    input_text: str,
    input_normalization: dict[str, Any] | None,
) -> CommitDecision:
    return CommitDecision(False, "confirmation_required")
