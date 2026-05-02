import json
from datetime import UTC, datetime
from typing import Any

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from app.ai.output_schema import ExtractionOutput
from app.ai.providers.base import ExtractionProvider
from app.ai.types import ExtractionInput, ExtractionProviderResult
from app.core.config import Settings, get_settings
from app.core.errors import AppError

SYSTEM_PROMPT = """
你是 LetMeFit 的健身管理信息提取器。只处理一般健身、饮食记录、身体指标记录。
禁止提供医疗诊断、治疗方案、疾病管理、处方、极端节食建议。

你必须只输出 JSON 对象，不要输出 Markdown。JSON schema:
{
  "assistant_text": "string",
  "intent": "fitness_record | answer_fitness_question | out_of_scope",
  "requires_review": true,
  "confidence": 0.0,
  "warnings": [{"field": "string", "reason": "string"}],
  "pending_actions": [
    {
      "type": "create_meal_record | create_body_metric_record",
      "confidence": 0.0,
      "draft_payload": {},
      "warnings": [{"field": "string", "reason": "string"}]
    }
  ]
}

规则:
- 任何会写入餐食或身体指标的结果都必须进入 pending_actions，requires_review=true。
- 不能直接确认记录。低置信度字段放入 warnings。
- create_meal_record.draft_payload 必须尽量包含 recorded_at、source_type、meal_type、items。
- meal_type 只能是 breakfast/lunch/dinner/snack/unknown。
- meal source_type 只能是 photo/voice/text/manual/mixed。
- create_body_metric_record.draft_payload 必须尽量包含 recorded_at、source_type。
- body source_type 只能是 scale_photo/voice/text/manual。
- 没有明确数值的营养或身体指标字段可以省略，不要编造。
- 如果 conversation_context.input_normalization 标记图片或语音为 unprocessed，
  不能猜测媒体内容，只能根据已有文本、转写、图片描述或用户明确说明提取。
- 如果超出健身管理边界，intent=out_of_scope，pending_actions=[]。
""".strip()


class BailianOutputError(ValueError):
    pass


class BailianExtractionProvider(ExtractionProvider):
    provider_name = "bailian"

    def __init__(self, settings: Settings | None = None, client: OpenAI | None = None) -> None:
        self.settings = settings or get_settings()
        api_key = self.settings.bailian_api_key or self.settings.dashscope_api_key
        if not api_key:
            raise AppError(
                "INTERNAL_ERROR",
                "百炼 API Key 未配置",
                status_code=500,
                details={"required": ["BAILIAN_API_KEY", "DASHSCOPE_API_KEY"]},
            )
        self.client = client or OpenAI(
            api_key=api_key,
            base_url=self.settings.bailian_base_url,
            timeout=self.settings.ai_timeout_seconds,
            max_retries=self.settings.ai_max_retries,
        )

    def extract(self, payload: ExtractionInput) -> ExtractionProviderResult:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._user_prompt(payload)},
        ]
        attempts = max(1, self.settings.ai_schema_repair_retries + 1)
        last_reason = "unknown"
        validation_errors: list[dict[str, Any]] = []

        for attempt_index in range(attempts):
            content = self._complete(messages)
            try:
                return self._parse_and_validate(content)
            except BailianOutputError as exc:
                last_reason = str(exc)
            except ValidationError as exc:
                last_reason = "schema_validation_failed"
                validation_errors = self._validation_error_details(exc)

            if attempt_index < attempts - 1:
                messages.append({"role": "assistant", "content": content or ""})
                messages.append(
                    {
                        "role": "user",
                        "content": self._repair_prompt(last_reason),
                    }
                )

        details: dict[str, Any] = {"provider": self.provider_name, "reason": last_reason}
        if last_reason == "schema_validation_failed":
            details["validation_errors"] = validation_errors
        raise AppError(
            "AI_EXTRACTION_FAILED",
            "百炼 LLM 返回结构不合法",
            status_code=502,
            details=details,
        )

    def _complete(self, messages: list[dict[str, str]]) -> str:
        try:
            completion = self.client.chat.completions.create(
                model=self.settings.bailian_model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=self.settings.ai_temperature,
            )
        except OpenAIError as exc:
            raise AppError(
                "AI_EXTRACTION_FAILED",
                "百炼 LLM 调用失败",
                status_code=502,
                details={"provider": self.provider_name},
            ) from exc

        content = completion.choices[0].message.content if completion.choices else None
        if not isinstance(content, str) or not content:
            raise BailianOutputError("empty_response")
        return content

    def _user_prompt(self, payload: ExtractionInput) -> str:
        content = [item.model_dump(mode="json", exclude_none=True) for item in payload.content]
        request = {
            "current_time": datetime.now(UTC).astimezone().isoformat(),
            "input_types": sorted({item["type"] for item in content}),
            "message_content": content,
            "conversation_context": payload.context,
            "output_language": "zh-CN",
            "instruction": "请按 JSON schema 输出结构化提取结果。",
        }
        return json.dumps(request, ensure_ascii=False, default=str)

    def _parse_and_validate(self, content: str) -> ExtractionProviderResult:
        raw_output = self._parse_json(content)
        output = ExtractionOutput.model_validate(raw_output)
        return output.to_provider_result(raw_output)

    def _parse_json(self, content: str) -> dict[str, Any]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise BailianOutputError("invalid_json") from exc
        if not isinstance(data, dict):
            raise BailianOutputError("json_root_not_object")
        return data

    def _repair_prompt(self, reason: str) -> str:
        return (
            "上一次输出不是合法 JSON 或不符合 LetMeFit JSON schema。"
            f"失败原因: {reason}。"
            "请只重新输出一个合法 JSON 对象，不要 Markdown，不要解释。"
            "所有会写入记录的内容必须放入 pending_actions，且 requires_review=true。"
        )

    def _validation_error_details(self, exc: ValidationError) -> list[dict[str, Any]]:
        return exc.errors(include_url=False, include_context=False, include_input=False)[:5]
