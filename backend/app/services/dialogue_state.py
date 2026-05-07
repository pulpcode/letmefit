from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.auth.security import new_id

STATE_VERSION = 1
OPEN_STATUS = "open"
ACTIVE_OFFER_KIND = "assistant_offer"
MAX_SURFACE_TEXT_CHARS = 500
MAX_REFERENT_FIELD_CHARS = 300
REFERENT_FIELDS = ("topic", "user_goal", "expected_followup")
FORBIDDEN_PATCH_KEYS = {
    "profile",
    "records",
    "recent_records",
    "active_pending_actions",
    "pending_actions",
    "draft_payload",
    "record_id",
    "committed_records",
}


def normalize_dialogue_state(value: Any) -> dict[str, Any]:
    state = deepcopy(value) if isinstance(value, dict) else {}
    state["version"] = STATE_VERSION

    ephemeral_state = state.get("ephemeral_state")
    if not isinstance(ephemeral_state, dict):
        ephemeral_state = {}
    state["ephemeral_state"] = ephemeral_state

    durable_context = state.get("durable_context")
    if not isinstance(durable_context, dict):
        durable_context = {}
    state["durable_context"] = durable_context
    return state


def dialogue_state_context(value: Any) -> dict[str, Any]:
    state = normalize_dialogue_state(value)
    active_offer = active_offer_from_state(state)
    return {
        "version": state["version"],
        "ephemeral_state": {"active_offer": active_offer} if active_offer else {},
        "durable_context": state.get("durable_context") or {},
    }


def active_offer_from_state(value: Any) -> dict[str, Any] | None:
    state = normalize_dialogue_state(value)
    active_offer = state.get("ephemeral_state", {}).get("active_offer")
    if not isinstance(active_offer, dict):
        return None
    if active_offer.get("status") != OPEN_STATUS:
        return None
    if active_offer.get("kind") != ACTIVE_OFFER_KIND:
        return None
    surface_text = _clean_text(active_offer.get("surface_text"), MAX_SURFACE_TEXT_CHARS)
    referent = _referent(active_offer.get("referent"))
    if not surface_text or not referent:
        return None
    sanitized = deepcopy(active_offer)
    sanitized["surface_text"] = surface_text
    sanitized["referent"] = referent
    return sanitized


def update_dialogue_state_after_assistant(
    previous_state: Any,
    *,
    assistant_text: str,
    assistant_message_id: str,
    created_at: Any,
    dialogue_state_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = normalize_dialogue_state(previous_state)

    # active_offer is a one-turn token. The previous token stays available while this
    # user turn is processed, then expires when the new assistant response is stored.
    state["ephemeral_state"].pop("active_offer", None)

    new_offer = active_offer_from_patch(
        dialogue_state_patch,
        assistant_text=assistant_text,
        assistant_message_id=assistant_message_id,
        created_at=created_at,
    )
    if new_offer:
        state["ephemeral_state"]["active_offer"] = new_offer
        state["durable_context"]["last_topic"] = new_offer["referent"].get("topic")
    return state


def active_offer_from_patch(
    dialogue_state_patch: Any,
    *,
    assistant_text: str,
    assistant_message_id: str,
    created_at: Any,
) -> dict[str, Any] | None:
    if not isinstance(dialogue_state_patch, dict):
        return None
    if _contains_forbidden_key(dialogue_state_patch):
        return None

    offer = dialogue_state_patch.get("new_active_offer")
    if not isinstance(offer, dict):
        return None
    if offer.get("kind") != ACTIVE_OFFER_KIND:
        return None

    surface_text = _clean_text(offer.get("surface_text"), MAX_SURFACE_TEXT_CHARS)
    if not surface_text:
        return None

    referent = _referent(offer.get("referent"))
    if not referent:
        return None

    return {
        "id": new_id("offer"),
        "kind": ACTIVE_OFFER_KIND,
        "surface_text": surface_text,
        "referent": referent,
        "source_message_id": assistant_message_id,
        "status": OPEN_STATUS,
        "created_at": _iso_or_str(created_at),
    }


def _referent(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    referent = {}
    for field in REFERENT_FIELDS:
        text = _clean_text(value.get(field), MAX_REFERENT_FIELD_CHARS)
        if text:
            referent[field] = text
    if not referent.get("topic") or not referent.get("expected_followup"):
        return {}
    return referent


def _clean_text(value: Any, max_chars: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:max_chars]


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in FORBIDDEN_PATCH_KEYS:
                return True
            if _contains_forbidden_key(child):
                return True
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _iso_or_str(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
