from datetime import UTC, datetime
from typing import Any

from app.ai.types import ExtractionInput

CONTEXT_CONTRACT = {
    "authority_order": [
        "message_content",
        "current_observation",
        "profile",
        "energy_target",
        "today_summary",
        "recent_records",
        "active_pending_actions",
        "input_normalization",
        "latest_conversation_summary",
        "conversation_history",
    ],
    "rules": [
        "当前 message_content 是本轮用户输入和当前用户意图的最高优先级来源，优先于所有历史消息。",
        "profile 和 recent_records 是后端确认后的正式事实，可信度高于历史对话和摘要。",
        "当用户询问今天或近期已记录内容时，必须优先读取 recent_records。",
        "只有 active_pending_actions 表示当前仍待用户处理的草稿。",
        (
            "conversation_history（当前消息之前的 chat turns）是最近几轮完整原始对话，"
            "用于理解指代和承接，但不能覆盖当前 message_content。"
        ),
        (
            "conversation_history 和 latest_conversation_summary 只是历史线索，"
            "不能覆盖当前消息、正式记录或当前待确认草稿。"
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
            "如果 active_pending_actions 非空且当前用户消息是在修改确认卡内容，调用 "
            "update_pending_action；如果用户明确放弃，调用 discard_pending_actions；"
            "确认操作由用户通过界面按钮完成，禁止调用 commit_pending_action。"
        ),
        (
            "如果 active_pending_actions 非空且当前用户消息明显不是在处理这些确认卡，"
            "必须在 assistant_text 结尾简短提醒用户尚有待确认草稿，"
            "根据 active_pending_actions 中的实际类型和内容描述，不要照搬示例中的具体名称。"
        ),
        (
            "active_pending_actions 最多只注入最近 3 条；如果 overflow_count 大于 0，"
            "应询问用户是否查看更多待确认记录。"
        ),
        (
            "active_pending_actions 为空时，不要在 assistant_text 中提及"
            "'没有待确认记录'；提醒规则只在 active_pending_actions 非空时生效。"
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
            "energy_target 包含基于 profile 计算好的 BMR/TDEE/target_calories/macros_target；"
            "回答用户关于'目标热量/蛋白质/碳水/脂肪'的问题时直接读取，不要重复推导公式。"
            "energy_target 为 null 时按 energy_target_warnings 中的 missing 字段提示用户补档案。"
        ),
        (
            "today_summary 包含用户今日已记录的 consumed/target/remaining/completion_percent；"
            "回答'今天还能吃多少 / 今天吃了多少 / 今天完成度' 时直接读取它，"
            "不要调用 query_meal_records 重复查询今日数据。"
        ),
        (
            "记录类 tool_calls 必须带 grounding；grounding.source 使用 user_message 或 "
            "model_inference；所有 propose_* 只创建确认卡，由用户通过界面按钮确认；"
            "confirmed_record 只用于回答和总结，不能创建新记录。"
        ),
    ],
}


def build_extraction_user_prompt_payload(payload: ExtractionInput) -> dict[str, Any]:
    content = [item.model_dump(mode="json", exclude_none=True) for item in payload.content]
    context = {
        k: v for k, v in payload.context.items()
        if k not in ("short_term_messages", "recent_messages")
    }
    return {
        "current_time": datetime.now(UTC).astimezone().isoformat(),
        "context_contract": CONTEXT_CONTRACT,
        "input_types": sorted({item["type"] for item in content}),
        "message_content": content,
        "conversation_context": context,
        "output_language": "zh-CN",
        "instruction": "请按 JSON schema 输出结构化提取结果。",
    }
