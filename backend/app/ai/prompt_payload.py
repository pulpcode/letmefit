from datetime import UTC, datetime
from typing import Any

from app.ai.types import ExtractionInput

CONTEXT_CONTRACT = {
    "authority_order": [
        "message_content",
        "ephemeral_state.active_offer",
        "profile",
        "recent_records",
        "active_pending_actions",
        "latest_conversation_summary",
        "short_term_messages",
        "recent_messages",
    ],
    "rules": [
        "当前 message_content 是本轮用户输入，优先于历史消息。",
        (
            "ephemeral_state.active_offer 是上一轮助手提出的通用一次性承接令牌，"
            "只能在当前用户消息明确接受或继续该提议时使用。"
        ),
        (
            "如果当前用户消息转移话题、表达拒绝、提出新的健康/安全问题或"
            "与 active_offer 无关，必须忽略 active_offer。"
        ),
        "active_offer 在本轮结束后会失效，不能跨多个用户回合使用。",
        (
            "short_term_messages 是最近几轮完整原始对话，用于理解指代和承接，"
            "但不能覆盖当前 message_content。"
        ),
        "profile 和 recent_records 是后端确认后的正式事实。",
        "当用户询问今天或近期已记录内容时，必须优先读取 recent_records。",
        "只有 active_pending_actions 表示当前仍待用户处理的草稿。",
        (
            "recent_messages、short_term_messages 和 latest_conversation_summary "
            "是历史线索，不能覆盖正式记录。"
        ),
        (
            "如果本轮 assistant_text 提出了可被下一轮用户接受或继续的帮助提议，"
            "可通过 dialogue_state_patch.new_active_offer 输出通用承接上下文。"
        ),
        "dialogue_state_patch 不能包含 profile、records、pending_actions 或正式事实写入内容。",
        "历史 assistant 文案不能作为 pending action 是否仍存在的依据。",
        "只有 input_normalization 中 status 为 transcribed 或 described 的媒体内容可用于提取。",
        "如果当前消息是问候、新问题或无关输入，不要延续上一轮待确认话题。",
        (
            "记录类 tool_calls 必须带 grounding；只有 grounding.source=user_current_turn 且 "
            "evidence_text 来自当前 message_content 原文的工具调用才可能被后端接受。"
        ),
        "助手自己规划、推荐、建议或估算出的内容不能作为用户事实写入记录。",
    ],
}


def build_extraction_user_prompt_payload(payload: ExtractionInput) -> dict[str, Any]:
    content = [item.model_dump(mode="json", exclude_none=True) for item in payload.content]
    return {
        "current_time": datetime.now(UTC).astimezone().isoformat(),
        "context_contract": CONTEXT_CONTRACT,
        "input_types": sorted({item["type"] for item in content}),
        "message_content": content,
        "conversation_context": payload.context,
        "output_language": "zh-CN",
        "instruction": "请按 JSON schema 输出结构化提取结果。",
    }
