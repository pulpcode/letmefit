from __future__ import annotations

from typing import Any

STATE_VERSION = 1


def normalize_dialogue_state(value: Any) -> dict[str, Any]:
    return {"version": STATE_VERSION}
