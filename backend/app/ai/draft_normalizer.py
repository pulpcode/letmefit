from typing import Any


def normalize_pending_action_draft(
    action_type: str,
    draft_payload: dict[str, Any],
) -> dict[str, Any]:
    if action_type == "create_meal_record":
        return _normalize_meal_draft(draft_payload)
    return dict(draft_payload)


def _normalize_meal_draft(draft_payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(draft_payload)
    items = normalized.get("items")
    if isinstance(items, list):
        normalized["items"] = [_normalize_meal_item(item) for item in items]
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
    return normalized
