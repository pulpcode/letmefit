from datetime import datetime

from app.services.dialogue_state import (
    active_offer_from_patch,
    active_offer_from_state,
    dialogue_state_context,
    update_dialogue_state_after_assistant,
)


def _offer_patch() -> dict:
    return {
        "new_active_offer": {
            "kind": "assistant_offer",
            "surface_text": "需要我帮您规划一份适合的晚餐方案吗？",
            "referent": {
                "topic": "晚餐方案",
                "user_goal": "基于今日记录和减脂目标安排晚餐",
                "expected_followup": "用户同意时直接生成晚餐方案",
            },
        }
    }


def test_llm_patch_creates_generic_one_turn_active_offer() -> None:
    state = update_dialogue_state_after_assistant(
        None,
        assistant_text="需要我帮您规划一份适合的晚餐方案吗？",
        assistant_message_id="msg_assistant",
        created_at=datetime(2026, 5, 5, 20, 0, 0),
        dialogue_state_patch=_offer_patch(),
    )

    offer = active_offer_from_state(state)
    assert offer is not None
    assert offer["kind"] == "assistant_offer"
    assert offer["surface_text"] == "需要我帮您规划一份适合的晚餐方案吗？"
    assert offer["referent"]["topic"] == "晚餐方案"
    assert offer["referent"]["expected_followup"] == "用户同意时直接生成晚餐方案"
    assert offer["source_message_id"] == "msg_assistant"
    assert offer["status"] == "open"
    assert state["durable_context"]["last_topic"] == "晚餐方案"


def test_previous_active_offer_expires_after_next_user_turn() -> None:
    previous = {
        "version": 1,
        "ephemeral_state": {
            "active_offer": {
                "id": "offer_old",
                "kind": "assistant_offer",
                "status": "open",
                "surface_text": "需要我帮您规划一份适合的晚餐方案吗？",
                "referent": {
                    "topic": "晚餐方案",
                    "expected_followup": "用户同意时直接生成晚餐方案",
                },
            }
        },
        "durable_context": {"last_topic": "晚餐方案"},
    }

    state = update_dialogue_state_after_assistant(
        previous,
        assistant_text="这个问题涉及伤病处理，我不能提供诊断或治疗建议。",
        assistant_message_id="msg_assistant_2",
        created_at=datetime(2026, 5, 5, 20, 2, 0),
    )

    assert active_offer_from_state(state) is None
    assert state["durable_context"]["last_topic"] == "晚餐方案"


def test_dialogue_state_context_only_exposes_open_active_offer() -> None:
    state = {
        "ephemeral_state": {
            "active_offer": {
                "id": "offer_closed",
                "kind": "assistant_offer",
                "status": "consumed",
            }
        },
        "durable_context": {"last_topic": "晚餐方案"},
    }

    context = dialogue_state_context(state)

    assert context["ephemeral_state"] == {}
    assert context["durable_context"]["last_topic"] == "晚餐方案"


def test_invalid_offer_patch_is_ignored() -> None:
    patch = {
        "new_active_offer": {
            "kind": "specific_workflow_type",
            "surface_text": "需要我帮您规划一份适合的晚餐方案吗？",
            "referent": {
                "topic": "晚餐方案",
                "expected_followup": "用户同意时直接生成晚餐方案",
            },
        }
    }

    offer = active_offer_from_patch(
        patch,
        assistant_text="需要我帮您规划一份适合的晚餐方案吗？",
        assistant_message_id="msg_assistant",
        created_at=datetime(2026, 5, 5, 20, 0, 0),
    )

    assert offer is None


def test_offer_patch_with_forbidden_record_data_is_ignored() -> None:
    patch = _offer_patch()
    patch["new_active_offer"]["pending_actions"] = [{"type": "create_meal_record"}]

    offer = active_offer_from_patch(
        patch,
        assistant_text="需要我帮您规划一份适合的晚餐方案吗？",
        assistant_message_id="msg_assistant",
        created_at=datetime(2026, 5, 5, 20, 0, 0),
    )

    assert offer is None


def test_offer_patch_surface_text_is_debug_description_only() -> None:
    patch = _offer_patch()
    patch["new_active_offer"]["surface_text"] = "我可以帮你制定训练计划。"

    offer = active_offer_from_patch(
        patch,
        assistant_text="需要我帮您规划一份适合的晚餐方案吗？",
        assistant_message_id="msg_assistant",
        created_at=datetime(2026, 5, 5, 20, 0, 0),
    )

    assert offer is not None
    assert offer["surface_text"] == "我可以帮你制定训练计划。"
