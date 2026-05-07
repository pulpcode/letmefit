import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.schemas.records import BodyMetricCreateRequest, MealCreateRequest

AUTO_COMMIT_CONFIDENCE_THRESHOLD = Decimal("0.85")
AUTO_COMMIT_SOURCE_TYPES = {"text", "voice", "manual"}
BODY_METRIC_VALUE_FIELDS = (
    "weight_kg",
    "body_fat_percentage",
    "bmi",
    "muscle_mass_kg",
    "water_percentage",
)
FUZZY_PORTION_TERMS = (
    "一碗",
    "半碗",
    "一盘",
    "一份",
    "半份",
    "一些",
    "少许",
    "适量",
    "大概",
    "大约",
    "左右",
    "差不多",
    "几个",
    "一点",
)
GRAM_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:克|g\b)", flags=re.IGNORECASE)


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


def legacy_decide_auto_commit(
    action_type: str,
    draft_payload: dict[str, Any],
    confidence: Decimal | None,
    warnings: list[dict[str, Any]],
    provider_warnings: list[dict[str, Any]],
    input_types: list[str],
    input_text: str,
    input_normalization: dict[str, Any] | None,
) -> CommitDecision:
    if warnings or provider_warnings:
        return CommitDecision(False, "has_warnings")
    if _has_unprocessed_media(input_normalization):
        return CommitDecision(False, "has_unprocessed_media")
    if "image" in input_types:
        return CommitDecision(False, "image_requires_confirmation")
    if not _meets_confidence_threshold(confidence):
        return CommitDecision(False, "low_confidence")

    if action_type == "create_body_metric_record":
        return _body_metric_decision(draft_payload)
    if action_type == "create_meal_record":
        return _meal_decision(draft_payload, input_text)
    return CommitDecision(False, "unsupported_action_type")


def _body_metric_decision(draft_payload: dict[str, Any]) -> CommitDecision:
    if draft_payload.get("source_type") not in AUTO_COMMIT_SOURCE_TYPES:
        return CommitDecision(False, "source_type_requires_confirmation")
    if not any(draft_payload.get(field) is not None for field in BODY_METRIC_VALUE_FIELDS):
        return CommitDecision(False, "missing_body_metric_value")
    try:
        BodyMetricCreateRequest.model_validate(draft_payload)
    except ValidationError:
        return CommitDecision(False, "invalid_body_metric_payload")
    return CommitDecision(True, "clear_body_metric")


def _meal_decision(draft_payload: dict[str, Any], input_text: str) -> CommitDecision:
    if draft_payload.get("source_type") not in AUTO_COMMIT_SOURCE_TYPES:
        return CommitDecision(False, "source_type_requires_confirmation")
    if not _contains_gram_unit(input_text):
        return CommitDecision(False, "no_explicit_gram_unit")
    if _contains_fuzzy_portion(input_text):
        return CommitDecision(False, "fuzzy_portion")
    items = draft_payload.get("items")
    if not isinstance(items, list) or not items:
        return CommitDecision(False, "missing_meal_items")
    for item in items:
        if not isinstance(item, dict):
            return CommitDecision(False, "invalid_meal_item")
        if not item.get("name"):
            return CommitDecision(False, "missing_meal_item_name")
        if item.get("portion_grams") is None:
            return CommitDecision(False, "missing_portion_grams")
    try:
        MealCreateRequest.model_validate(draft_payload)
    except ValidationError:
        return CommitDecision(False, "invalid_meal_payload")
    return CommitDecision(True, "clear_meal_with_grams")


def _meets_confidence_threshold(confidence: Decimal | None) -> bool:
    return confidence is not None and confidence >= AUTO_COMMIT_CONFIDENCE_THRESHOLD


def _has_unprocessed_media(input_normalization: dict[str, Any] | None) -> bool:
    if not input_normalization:
        return False
    media = input_normalization.get("media")
    if not isinstance(media, list):
        return False
    return any(isinstance(item, dict) and item.get("status") == "unprocessed" for item in media)


def _contains_gram_unit(input_text: str) -> bool:
    return bool(GRAM_PATTERN.search(input_text))


def _contains_fuzzy_portion(input_text: str) -> bool:
    return any(term in input_text for term in FUZZY_PORTION_TERMS)
