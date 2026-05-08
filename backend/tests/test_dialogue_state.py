from app.services.dialogue_state import normalize_dialogue_state


def test_normalize_dialogue_state_returns_versioned_dict() -> None:
    state = normalize_dialogue_state(None)
    assert state == {"version": 1}


def test_normalize_dialogue_state_is_idempotent() -> None:
    state = normalize_dialogue_state({"version": 1, "stale_key": "old_value"})
    assert state == {"version": 1}


def test_normalize_dialogue_state_accepts_any_input() -> None:
    for value in [None, {}, "string", 42, [], {"version": 99}]:
        result = normalize_dialogue_state(value)
        assert result["version"] == 1
