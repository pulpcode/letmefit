from datetime import UTC, datetime
from typing import Any

from app.ai.types import ExtractionInput

CONTEXT_CONTRACT = {
    "authority_order": [
        "message_content",
        "profile",
        "recent_records",
        "active_pending_actions",
        "conversation_summary",
        "recent_messages",
    ],
    "rules": [
        "当前 message_content 是本轮用户输入，优先于历史消息。",
        "profile 和 recent_records 是后端确认后的正式事实。",
        "只有 active_pending_actions 表示当前仍待用户处理的草稿。",
        "recent_messages 和 conversation_summary 只是历史线索，不能覆盖正式记录。",
        "历史 assistant 文案不能作为 pending action 是否仍存在的依据。",
        "只有 input_normalization 中 status 为 transcribed 或 described 的媒体内容可用于提取。",
        "如果当前消息是问候、新问题或无关输入，不要延续上一轮待确认话题。",
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
