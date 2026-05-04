import re
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo


def normalize_pending_action_draft(
    action_type: str,
    draft_payload: dict[str, Any],
    input_text: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if action_type == "create_meal_record":
        return _normalize_meal_draft(draft_payload, input_text=input_text, now=now)
    return dict(draft_payload)


EXPLICIT_CLOCK_PATTERN = re.compile(
    r"(\d{1,2}\s*[:：]\s*\d{1,2}|\d{1,2}\s*[点时](?:\s*\d{1,2}\s*分?)?)"
)
DEFAULT_MEAL_TIMES = {
    "breakfast": time(8, 0),
    "lunch": time(12, 30),
    "dinner": time(19, 0),
}


def _normalize_meal_draft(
    draft_payload: dict[str, Any],
    input_text: str | None,
    now: datetime | None,
) -> dict[str, Any]:
    normalized = dict(draft_payload)
    normalized.setdefault("recorded_tz", "Asia/Shanghai")
    items = normalized.get("items")
    if isinstance(items, list):
        normalized["items"] = [_normalize_meal_item(item) for item in items]
    if input_text is not None:
        _normalize_meal_recorded_at(normalized, input_text, now)
    return normalized


def _normalize_meal_item(item: Any) -> Any:
    if isinstance(item, str):
        value = item.strip()
        return {"name": value} if value else item
    if not isinstance(item, dict):
        return item

    normalized = dict(item)
    if not normalized.get("name"):
        for alias in ("food_name", "food", "item", "label"):
            value = normalized.get(alias)
            if isinstance(value, str) and value.strip():
                normalized["name"] = value.strip()
                break
    if not normalized.get("portion_text"):
        portion_text = _portion_text_from_quantity(normalized)
        if portion_text:
            normalized["portion_text"] = portion_text
    _copy_first_present(normalized, "calories", ("calories_kcal", "kcal", "energy_kcal"))
    _copy_first_present(normalized, "protein_g", ("protein", "protein_grams"))
    _copy_first_present(normalized, "carbs_g", ("carbs", "carbohydrate_g", "carbohydrates_g"))
    _copy_first_present(normalized, "fat_g", ("fat", "fat_grams"))
    return normalized


def _normalize_meal_recorded_at(
    draft_payload: dict[str, Any],
    input_text: str,
    now: datetime | None,
) -> None:
    if _has_explicit_clock(input_text):
        return

    timezone = ZoneInfo(str(draft_payload.get("recorded_tz") or "Asia/Shanghai"))
    local_now = _local_now(now, timezone)
    meal_type = draft_payload.get("meal_type")
    if meal_type == "snack" or meal_type == "unknown" or _current_window_matches(meal_type, local_now):
        local_time = local_now.replace(second=0, microsecond=0)
    else:
        default_time = DEFAULT_MEAL_TIMES.get(str(meal_type))
        if default_time is None:
            local_time = local_now.replace(second=0, microsecond=0)
        else:
            local_time = datetime.combine(local_now.date(), default_time, tzinfo=timezone)
    draft_payload["recorded_at"] = local_time.isoformat()
    draft_payload["recorded_tz"] = str(timezone.key)


def _local_now(now: datetime | None, timezone: ZoneInfo) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(timezone)


def _has_explicit_clock(input_text: str) -> bool:
    return bool(EXPLICIT_CLOCK_PATTERN.search(input_text))


def _current_window_matches(meal_type: Any, local_now: datetime) -> bool:
    hour = local_now.hour
    if meal_type == "breakfast":
        return 5 <= hour < 11
    if meal_type == "lunch":
        return 11 <= hour < 15
    if meal_type == "dinner":
        return 17 <= hour < 22
    return False


def _portion_text_from_quantity(item: dict[str, Any]) -> str | None:
    quantity = item.get("quantity")
    unit = item.get("unit")
    if quantity is None or not unit:
        return None
    return f"{quantity:g}{unit}" if isinstance(quantity, (int, float)) else f"{quantity}{unit}"


def _copy_first_present(item: dict[str, Any], target: str, aliases: tuple[str, ...]) -> None:
    if item.get(target) is not None:
        return
    for alias in aliases:
        if item.get(alias) is not None:
            item[target] = item[alias]
            return
