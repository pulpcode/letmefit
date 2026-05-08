from datetime import UTC, datetime
from typing import Any

from app.ai.types import ExtractionInput

CONTEXT_CONTRACT = {
    "authority_order": [
        "message_content",
        "current_observation",
        "profile",
        "recent_records",
        "active_pending_actions",
        "input_normalization",
        "latest_conversation_summary",
        "short_term_messages",
        "recent_messages",
    ],
    "rules": [
        "当前 message_content 是本轮用户输入和当前用户意图的最高优先级来源，优先于所有历史消息。",
        "profile 和 recent_records 是后端确认后的正式事实，可信度高于历史对话和摘要。",
        "当用户询问今天或近期已记录内容时，必须优先读取 recent_records。",
        "只有 active_pending_actions 表示当前仍待用户处理的草稿。",
        (
            "short_term_messages 是最近几轮完整原始对话，用于理解指代和承接，"
            "但不能覆盖当前 message_content。"
        ),
        (
            "recent_messages、short_term_messages、latest_conversation_summary 和 "
            "conversation_summary 只是历史线索，不能覆盖当前消息、正式记录或当前待确认草稿。"
        ),
        (
            "后端会在一次请求内运行有上限的 ReAct loop；简单问题可以直接 assistant_text 回答，"
            "需要查库时可请求只读工具，信息不足时用 assistant_text 追问且 tool_calls=[]。"
        ),
        (
            "记录工具生成 pending_confirmation 时，本次 loop 会暂停等待用户确认；用户确认、"
            "修改或放弃后，会以 current_observation 形式进入新的请求上下文。"
        ),
        (
            "如果 active_pending_actions 非空且当前用户消息是在修改确认卡，调用 "
            "update_pending_action；如果当前用户消息是在确认保存确认卡，调用 "
            "commit_pending_action；如果用户明确确认或放弃多条确认卡，调用 "
            "commit_pending_actions 或 discard_pending_actions。是否属于修改、确认或放弃"
            "由模型基于语义判断。"
        ),
        (
            "active_pending_actions 最多只注入最近 3 条；如果 overflow_count 大于 0，"
            "应询问用户是否查看更多待确认记录。"
        ),
        (
            "pending action 状态由后端规则决定；模型不能直接指定 pending_confirmation、"
            "needs_clarification 或 expired。"
        ),
        (
            "当 input_origin=pending_action_observation 时，只能把 current_observation 用于回答、"
            "规划或查库，不能据此创建新的记录写入工具调用。"
        ),
        (
            "profile、recent_records、active_pending_actions 已在默认上下文中；不要为了读取它们"
            "重复调用工具。超出 recent_records 日期范围的记录查询才使用只读查询工具。"
        ),
        (
            "记录类 tool_calls 必须带 grounding；current_user_message 和 normalized_media_text "
            "只会创建确认卡，recent_user_message、active_pending_action、tool_result、"
            "assistant_plan 最多也只能创建确认卡，confirmed_record 只能用于回答和总结，"
            "model_inference 不能写记录。"
        ),
        (
            "助手自己规划、推荐、建议或估算出的内容不能作为用户已发生事实自动保存；"
            "如需承接 assistant_plan，只能创建确认卡。"
        ),
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
