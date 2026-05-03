from datetime import UTC, datetime
from typing import Any

from app.ai.types import ExtractionInput


def build_extraction_user_prompt_payload(payload: ExtractionInput) -> dict[str, Any]:
    content = [item.model_dump(mode="json", exclude_none=True) for item in payload.content]
    return {
        "current_time": datetime.now(UTC).astimezone().isoformat(),
        "input_types": sorted({item["type"] for item in content}),
        "message_content": content,
        "conversation_context": payload.context,
        "output_language": "zh-CN",
        "instruction": "请按 JSON schema 输出结构化提取结果。",
    }
