from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from app.schemas.records import BodyMetricCreateRequest, MealCreateRequest

PENDING_CONFIRMATION = "pending_confirmation"
NEEDS_CLARIFICATION = "needs_clarification"
COMMITTED = "committed"
DISCARDED = "discarded"
EXPIRED = "expired"

ACTIVE_PENDING_ACTION_STATUSES = {NEEDS_CLARIFICATION, PENDING_CONFIRMATION}
EDITABLE_PENDING_ACTION_STATUSES = {NEEDS_CLARIFICATION, PENDING_CONFIRMATION}
CONFIRMABLE_PENDING_ACTION_STATUS = PENDING_CONFIRMATION
PENDING_ACTION_TTL = timedelta(hours=24)
CONTEXT_PENDING_ACTION_LIMIT = 3

BODY_METRIC_VALUE_FIELDS = (
    "weight_kg",
    "body_fat_percentage",
    "bmi",
    "muscle_mass_kg",
    "water_percentage",
)


def pending_action_expires_at(now: datetime) -> datetime:
    return now + PENDING_ACTION_TTL


def pending_action_is_expired(action: Any, now: datetime) -> bool:
    return action.expires_at is not None and action.expires_at <= now


def classify_pending_action_status(
    action_type: str,
    draft_payload: dict[str, Any],
    warnings: list[dict[str, Any]] | None = None,
) -> str:
    if _needs_clarification_warning(warnings or []):
        return NEEDS_CLARIFICATION
    if action_type == "create_meal_record":
        return _meal_status(draft_payload)
    if action_type == "create_body_metric_record":
        return _body_metric_status(draft_payload)
    if action_type == "create_workout_record":
        return _workout_status(draft_payload)
    return NEEDS_CLARIFICATION


def normalize_status_warnings(
    status: str,
    warnings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    normalized = list(warnings or [])
    if status != NEEDS_CLARIFICATION:
        return normalized
    if any(item.get("reason") == "needs_clarification" for item in normalized):
        return normalized
    normalized.append({"field": "draft_payload", "reason": "needs_clarification"})
    return normalized


def pending_action_context_summary(action: Any, display_index: int) -> dict[str, Any]:
    payload = action.draft_payload_json or {}
    return {
        "pending_action_id": action.id,
        "display_index": display_index,
        "type": action.action_type,
        "status": action.status,
        "title": _action_title(action.action_type, payload),
        "editable_fields": _editable_fields(action.action_type, payload),
        "warnings": action.warnings_json or [],
        "expires_at": _iso_or_none(action.expires_at),
    }


def _meal_status(draft_payload: dict[str, Any]) -> str:
    try:
        MealCreateRequest.model_validate(draft_payload)
    except ValidationError:
        return NEEDS_CLARIFICATION

    items = draft_payload.get("items")
    if not isinstance(items, list) or not items:
        return NEEDS_CLARIFICATION
    for item in items:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            return NEEDS_CLARIFICATION
        if not _meal_item_has_clear_portion(item):
            return NEEDS_CLARIFICATION
    return PENDING_CONFIRMATION


def _body_metric_status(draft_payload: dict[str, Any]) -> str:
    if not any(draft_payload.get(field) is not None for field in BODY_METRIC_VALUE_FIELDS):
        return NEEDS_CLARIFICATION
    try:
        BodyMetricCreateRequest.model_validate(draft_payload)
    except ValidationError:
        return NEEDS_CLARIFICATION
    return PENDING_CONFIRMATION


def _workout_status(draft_payload: dict[str, Any]) -> str:
    workout_name = (
        draft_payload.get("workout_type")
        or draft_payload.get("exercise_type")
        or draft_payload.get("name")
    )
    duration = draft_payload.get("duration_minutes") or draft_payload.get("duration_text")
    if not workout_name or not duration:
        return NEEDS_CLARIFICATION
    return PENDING_CONFIRMATION


def _meal_item_has_clear_portion(item: dict[str, Any]) -> bool:
    return item.get("portion_grams") is not None


def _needs_clarification_warning(warnings: list[dict[str, Any]]) -> bool:
    reasons = {str(item.get("reason") or "") for item in warnings if isinstance(item, dict)}
    return bool(
        reasons.intersection(
            {
                "needs_clarification",
                "missing_information",
                "missing_required_field",
                "ambiguous_user_correction",
            }
        )
    )


def _action_title(action_type: str, payload: dict[str, Any]) -> str:
    if action_type == "create_meal_record":
        meal_type = {
            "breakfast": "早餐",
            "lunch": "午餐",
            "dinner": "晚餐",
            "snack": "加餐",
            "unknown": "餐食",
        }.get(str(payload.get("meal_type") or "unknown"), "餐食")
        names = [
            str(item.get("name"))
            for item in payload.get("items") or []
            if isinstance(item, dict) and item.get("name")
        ]
        return f"{meal_type}: {'、'.join(names[:3])}" if names else meal_type
    if action_type == "create_body_metric_record":
        parts = []
        for field, label in (
            ("weight_kg", "体重"),
            ("body_fat_percentage", "体脂"),
            ("bmi", "BMI"),
        ):
            if payload.get(field) is not None:
                parts.append(f"{label} {payload[field]}")
        return "身体指标: " + "，".join(parts) if parts else "身体指标"
    if action_type == "create_workout_record":
        return str(
            payload.get("workout_type")
            or payload.get("exercise_type")
            or payload.get("name")
            or "锻炼记录"
        )
    return "待确认记录"


def _editable_fields(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action_type == "create_meal_record":
        return {
            "recorded_at": payload.get("recorded_at"),
            "meal_type": payload.get("meal_type"),
            "items": [
                {
                    "name": item.get("name"),
                    "portion_text": item.get("portion_text"),
                    "portion_grams": item.get("portion_grams"),
                    "calories": item.get("calories"),
                }
                for item in payload.get("items") or []
                if isinstance(item, dict)
            ],
        }
    if action_type == "create_body_metric_record":
        return {
            field: payload.get(field)
            for field in ("recorded_at", *BODY_METRIC_VALUE_FIELDS)
            if payload.get(field) is not None
        }
    if action_type == "create_workout_record":
        return {
            field: payload.get(field)
            for field in (
                "recorded_at",
                "workout_type",
                "exercise_type",
                "duration_minutes",
                "duration_text",
                "intensity",
                "calories_burned",
                "notes",
            )
            if payload.get(field) is not None
        }
    return dict(payload)


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
