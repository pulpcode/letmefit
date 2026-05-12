import json
from decimal import Decimal
from typing import Any

from openai import OpenAI, OpenAIError

from app.ai.prompt_payload import build_extraction_user_prompt_payload
from app.ai.providers.base import ExtractionProvider
from app.ai.types import (
    ActionGrounding,
    ExtractionInput,
    ExtractionProviderResult,
    ExtractionToolCall,
    Intent,
)
from app.core.config import Settings, get_settings
from app.core.errors import AppError

SYSTEM_PROMPT = """
你是 LetMeFit 的健身管理对话助手，也是结构化记录工具调用者。
你只处理一般健身、饮食记录、身体指标记录、轻量生活方式建议和记录相关问答。
禁止医疗诊断、治疗方案、疾病管理、处方、极端节食建议。

## 核心规则：text 和 tool_calls 是两条独立的输出通道

不是二选一。每次回复都要分别判断：

判断 A — 用户当前消息里是否陈述了已发生的事实？
  · 饮食："吃了/喝了..." → 调用 propose_meal_record
  · 身体指标："体重/体脂..." → 调用 propose_body_metric_record
  · 锻炼："跑了/练了..." → 调用 propose_workout_record
  · 修改/放弃已有草稿 → 调用 update_pending_action / discard_pending_actions
  · 没有就不调用

判断 B — 用户当前消息里是否有需要你回答的内容？
  · 问题、规划、建议、解释、追问 → 在 assistant text 中回答
  · 没有就让 text 为空

两个判断同时进行。常见的混合场景必须同时输出 tool_calls 和 text，例如：

  用户："今天早上吃了两个鸡蛋，帮我规划一下午餐"
    → tool_calls: [propose_meal_record(早餐: 鸡蛋×2, grounding)]
    → text: "为你规划午餐：[具体方案]"
    （早餐草稿和午餐规划是两件独立的事，必须一次回复里同时给出）

  用户："今天吃了两个鸡蛋，我昨天吃了多少卡？"
    → tool_calls: [propose_meal_record(...), query_meal_records(昨天)]
    （两个工具可以并行）

  用户："帮我规划明天的饮食"
    → tool_calls: []
    → text: "[规划方案或追问]"

  用户："今天早上吃了两个鸡蛋"
    → tool_calls: [propose_meal_record(...)]
    → text: ""（无问题需要回答）

## 状态规则

记录工具生成的是待确认草稿（pending action），不是正式记录。
不要在 text 中说"已记录"或"已保存"——保存状态以后端工具结果为准。确认前只能说"已整理草稿"。
记录工具生成 pending_confirmation 后本次 loop 暂停，等待用户在 UI 上确认/修改/放弃。
用户动作会作为 observation 进入新一轮 ReAct（input_origin=pending_action_observation），
此时只能回答/规划/查库，不能据此创建新的记录工具调用。

## 上下文使用规则

- profile / recent_records / active_pending_actions / energy_target / today_summary 已在
  conversation_context 中，不要为了读取它们重复调用工具。
- energy_target 包含 BMR/TDEE/target_calories/macros_target/strategy_text；回答"目标热量/
  蛋白质/碳水/脂肪"类问题时直接读取，不要推导 Mifflin-St Jeor 公式。energy_target=null 时按
  energy_target_warnings.missing 提示用户补档案。
- today_summary 包含今日 consumed/target/remaining/completion_percent；回答"今天还能吃多少/
  今天吃了多少"时直接读取，不要为今天调用 query_meal_records。非今日才用查询工具。
- 询问"今天吃了什么"等已记录内容时，优先用 recent_records 中的已确认记录回答。
  日期或范围超出 recent_records 时再调用 query_meal_records / query_body_metric_records。
- chat history 用于理解指代、补全信息；不能覆盖当前消息、profile、recent_records、
  active_pending_actions。

## 工具调用细则

- grounding.source: user_message（用户明确描述）或 model_inference（从上下文推断）。
  evidence_text 必须是原文片段，不得改写。
- update_pending_action / discard_pending_actions 的 grounding.source_id 填 pending_action_id。
- model_inference 可以 propose_*（由用户确认），但信息不足时应只在 text 中追问、不调工具。
- propose_* 返回 status=rejected + insufficient_data 时，在 text 中追问缺失字段，不重试工具。
- 用户在聊天中修正当前确认卡（食物/份量/餐别/体重等）时，调用 update_pending_action，
  不要创建新的 propose_* 草稿。
- active_pending_actions 非空时：用户修改 → update_pending_action；用户放弃 →
  discard_pending_actions；其他情况在 text 末尾简短提醒仍有待确认草稿（基于实际内容描述）。
- active_pending_actions 为空时，禁止在 text 中提及"没有待确认记录""目前无草稿"等表述。

## 餐食与身体指标细则

- propose_meal_record.arguments 应尽量包含 source_type、meal_type、items；用户明确指定时间
  时填 recorded_at，未指定则省略（后端按餐型自动填充）。
- 用户描述的食物是常见食物（米饭、鸡蛋、鸡胸肉等）且已说明大致份量（"一碗""两片"）时，
  必须直接调用 propose_meal_record；估算份量和营养写入 arguments，confidence < 0.75。
  追问只在完全不知道食物或描述过于模糊（"吃了一点东西"）时才做。
- 不要声称估算是精确值；用户提供品牌/重量/包装营养表时，优先使用用户信息。
- 没有依据的身体指标字段省略，不要编造。

## 媒体输入细则

- conversation_context.input_normalization 标记图片/语音 unprocessed 时，不能猜测媒体内容，
  只能根据已有文本、转写、图片描述或用户明确说明提取。
- input_normalization.media 中图片 status=described 时，把 description 当作图像识别的第三方
  观察结果使用：基于食物、份量提示和置信度推断营养，必须在 text 中显式表达份量为视觉估算
  并带不确定性（例如"约 350±80 kcal"），并提示用户可在确认卡上修改。
""".strip()


_GROUNDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "记录工具调用的依据来源",
    "properties": {
        "source": {
            "type": "string",
            "enum": ["user_message", "model_inference"],
            "description": (
                "user_message: 用户当前消息中明确陈述; "
                "model_inference: 模型从上下文推断"
            ),
        },
        "evidence_text": {
            "type": "string",
            "description": "对应来源中的原文片段，不得改写",
        },
        "source_id": {
            "type": "string",
            "description": "对应的 pending_action_id 等，可选",
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["source", "evidence_text"],
}


_MEAL_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "alias": {"type": "string"},
        "portion_text": {"type": "string"},
        "portion_grams": {"type": "number", "minimum": 0, "maximum": 10000},
        "calories": {"type": "number", "minimum": 0, "maximum": 20000},
        "protein_g": {"type": "number", "minimum": 0, "maximum": 2000},
        "carbs_g": {"type": "number", "minimum": 0, "maximum": 2000},
        "fat_g": {"type": "number", "minimum": 0, "maximum": 2000},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "user_corrected": {"type": "boolean"},
    },
    "required": ["name"],
}


def _function_def(
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    _function_def(
        "propose_meal_record",
        "提议创建一条餐食记录草稿。当用户在当前消息中陈述已发生的餐食事实（吃了什么、什么时间、什么餐）时调用。"
        "只创建确认卡，不直接写入正式记录。",
        {
            "type": "object",
            "properties": {
                "recorded_at": {
                    "type": "string",
                    "description": "用户明确指定的餐食发生时间，ISO 8601 含时区；未指定时省略",
                },
                "source_type": {
                    "type": "string",
                    "enum": ["photo", "voice", "text", "manual", "mixed"],
                },
                "meal_type": {
                    "type": "string",
                    "enum": ["breakfast", "lunch", "dinner", "snack", "unknown"],
                },
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "items": _MEAL_ITEM_SCHEMA,
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "notes": {"type": "string"},
                "grounding": _GROUNDING_SCHEMA,
            },
            "required": ["source_type", "meal_type", "items", "grounding"],
        },
    ),
    _function_def(
        "propose_body_metric_record",
        "提议创建一条身体指标记录草稿。当用户在当前消息中陈述具体的体重/体脂/BMI 等数值时调用。",
        {
            "type": "object",
            "properties": {
                "recorded_at": {"type": "string"},
                "source_type": {
                    "type": "string",
                    "enum": ["scale_photo", "voice", "text", "manual"],
                },
                "weight_kg": {"type": "number", "minimum": 25, "maximum": 300},
                "body_fat_percentage": {"type": "number", "minimum": 1, "maximum": 80},
                "bmi": {"type": "number", "minimum": 10, "maximum": 80},
                "muscle_mass_kg": {"type": "number", "minimum": 1, "maximum": 200},
                "water_percentage": {"type": "number", "minimum": 1, "maximum": 90},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "grounding": _GROUNDING_SCHEMA,
            },
            "required": ["source_type", "grounding"],
        },
    ),
    _function_def(
        "propose_workout_record",
        "提议创建一条锻炼记录草稿。当用户陈述已完成的运动事实时调用。",
        {
            "type": "object",
            "properties": {
                "recorded_at": {"type": "string"},
                "source_type": {"type": "string"},
                "workout_type": {"type": "string"},
                "exercise_type": {"type": "string"},
                "duration_minutes": {"type": "number", "minimum": 0},
                "duration_text": {"type": "string"},
                "intensity": {"type": "string"},
                "calories_burned": {"type": "number", "minimum": 0},
                "notes": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "grounding": _GROUNDING_SCHEMA,
            },
            "required": ["grounding"],
        },
    ),
    _function_def(
        "update_pending_action",
        "对一个已存在的待确认草稿做结构化修正。当用户在普通聊天中提出修改时（更正食物、份量、餐别、体重等），"
        "应调用此工具更新原草稿，而不是创建新的 propose_* 草稿。",
        {
            "type": "object",
            "properties": {
                "pending_action_id": {"type": "string"},
                "draft_payload": {
                    "type": "object",
                    "description": "对该 pending action 的结构化修正，可包含完整草稿或需覆盖字段",
                },
                "grounding": _GROUNDING_SCHEMA,
            },
            "required": ["pending_action_id", "draft_payload", "grounding"],
        },
    ),
    _function_def(
        "discard_pending_actions",
        "用户明确表达放弃确认卡时调用。",
        {
            "type": "object",
            "properties": {
                "pending_action_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "grounding": _GROUNDING_SCHEMA,
            },
            "required": ["pending_action_ids", "grounding"],
        },
    ),
    _function_def(
        "query_meal_records",
        "查询用户已确认的餐食记录。优先使用 conversation_context.recent_records；"
        "只在日期或范围超出 recent_records 时调用。",
        {
            "type": "object",
            "properties": {
                "local_date": {"type": "string", "description": "本地日期 YYYY-MM-DD"},
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
            },
        },
    ),
    _function_def(
        "query_body_metric_records",
        "查询用户已确认的身体指标记录。",
        {
            "type": "object",
            "properties": {
                "local_date": {"type": "string"},
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
            },
        },
    ),
]


_RECORD_TOOL_NAMES: set[str] = {
    "propose_meal_record",
    "propose_body_metric_record",
    "propose_workout_record",
}


class BailianOutputError(ValueError):
    pass


class BailianExtractionProvider(ExtractionProvider):
    provider_name = "bailian"

    def __init__(self, settings: Settings | None = None, client: OpenAI | None = None) -> None:
        self.settings = settings or get_settings()
        self._last_debug_request_body: dict[str, Any] | None = None
        self._last_debug_response_body: dict[str, Any] | None = None
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
        messages = self._messages(payload)
        attempts = max(1, self.settings.ai_schema_repair_retries + 1)
        last_reason = "unknown"

        for attempt_index in range(attempts):
            request_body = self._request_body(messages)
            self._last_debug_request_body = request_body
            message = self._complete(request_body)
            try:
                return self._build_provider_result(message)
            except BailianOutputError as exc:
                last_reason = str(exc)

            if attempt_index < attempts - 1:
                messages.append(self._message_to_dict(message))
                messages.append(
                    {
                        "role": "user",
                        "content": self._repair_prompt(last_reason),
                    }
                )

        raise AppError(
            "AI_EXTRACTION_FAILED",
            "百炼 LLM 返回结构不合法",
            status_code=502,
            details={"provider": self.provider_name, "reason": last_reason},
        )

    def _complete(self, request_body: dict[str, Any]) -> Any:
        try:
            completion = self.client.chat.completions.create(**request_body)
        except OpenAIError as exc:
            self._last_debug_response_body = {"error": str(exc), "type": exc.__class__.__name__}
            raise AppError(
                "AI_EXTRACTION_FAILED",
                "百炼 LLM 调用失败",
                status_code=502,
                details={"provider": self.provider_name},
            ) from exc

        self._last_debug_response_body = self._dump_completion(completion)
        if not completion.choices:
            raise BailianOutputError("empty_response")
        return completion.choices[0].message

    def _dump_completion(self, completion: Any) -> dict[str, Any]:
        try:
            return completion.model_dump(mode="json")
        except AttributeError:
            pass
        try:
            return json.loads(completion.model_dump_json())
        except AttributeError:
            return {"repr": repr(completion)}

    def debug_request_body(self, payload: ExtractionInput) -> dict[str, Any]:
        return self._request_body(self._messages(payload))

    def last_debug_request_body(self) -> dict[str, Any] | None:
        return self._last_debug_request_body

    def last_debug_response_body(self) -> dict[str, Any] | None:
        return self._last_debug_response_body

    def _request_body(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "model": self.settings.bailian_model,
            "messages": messages,
            "tools": TOOL_SCHEMAS,
            "tool_choice": "auto",
            "temperature": self.settings.ai_temperature,
        }

    def _messages(self, payload: ExtractionInput) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        for msg in payload.context.get("short_term_messages") or []:
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            text = self._history_message_text(msg)
            if text:
                messages.append({"role": role, "content": text})
        messages.append({"role": "user", "content": self._user_prompt(payload)})
        for turn in payload.prior_turns:
            assistant_output = turn.get("assistant_output") or {}
            tool_results = turn.get("tool_results") or []
            messages.append(self._reconstruct_assistant_message(assistant_output))
            for result in tool_results:
                messages.append(self._reconstruct_tool_message(result))
        return messages

    def _reconstruct_assistant_message(self, assistant_output: dict[str, Any]) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_output.get("content") or "",
        }
        tool_calls = assistant_output.get("tool_calls") or []
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message

    def _reconstruct_tool_message(self, tool_result: dict[str, Any]) -> dict[str, Any]:
        tool_call_id = tool_result.get("tool_call_id")
        if not tool_call_id:
            tool_call_id = f"missing_{tool_result.get('tool_name', '')}"
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(tool_result, ensure_ascii=False, default=str),
        }

    def _message_to_dict(self, message: Any) -> dict[str, Any]:
        try:
            return message.model_dump(mode="json", exclude_none=False)
        except AttributeError:
            return {"role": "assistant", "content": str(getattr(message, "content", "") or "")}

    def _history_message_text(self, msg: dict[str, Any]) -> str:
        MAX_CHARS = 2000
        content = msg.get("content")
        if isinstance(content, list):
            parts = [
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            text = " ".join(p for p in parts if p).strip()
            if text:
                return text[:MAX_CHARS]
        preview = str(msg.get("content_preview") or "").strip()
        return preview[:MAX_CHARS]

    def _user_prompt(self, payload: ExtractionInput) -> str:
        request = build_extraction_user_prompt_payload(payload)
        return json.dumps(request, ensure_ascii=False, default=str)

    def _build_provider_result(self, message: Any) -> ExtractionProviderResult:
        content = (getattr(message, "content", None) or "").strip()
        native_tool_calls = getattr(message, "tool_calls", None) or []
        tool_calls: list[ExtractionToolCall] = []
        raw_tool_calls: list[dict[str, Any]] = []
        for native in native_tool_calls:
            extraction_tool_call, raw_dump = self._parse_native_tool_call(native)
            tool_calls.append(extraction_tool_call)
            raw_tool_calls.append(raw_dump)

        if not content and not tool_calls:
            raise BailianOutputError("empty_response")

        intent = self._derive_intent(tool_calls, content)
        requires_review = any(tc.name in _RECORD_TOOL_NAMES for tc in tool_calls)
        confidence = self._aggregate_confidence(tool_calls)
        raw_output: dict[str, Any] = {
            "content": content,
            "tool_calls": raw_tool_calls,
        }

        return ExtractionProviderResult(
            assistant_text=content,
            intent=intent,
            requires_review=requires_review,
            confidence=confidence,
            tool_calls=tool_calls,
            warnings=[],
            raw_output=raw_output,
        )

    def _parse_native_tool_call(self, native: Any) -> tuple[ExtractionToolCall, dict[str, Any]]:
        try:
            name = native.function.name
            arguments_text = native.function.arguments or "{}"
            tool_call_id = native.id
        except AttributeError as exc:
            raise BailianOutputError(f"malformed_tool_call: {exc}") from exc
        if name not in _ALLOWED_TOOL_NAMES:
            raise BailianOutputError(f"unsupported_tool_name: {name}")
        try:
            args = json.loads(arguments_text)
        except json.JSONDecodeError as exc:
            raise BailianOutputError(f"invalid_tool_arguments_json: {exc}") from exc
        if not isinstance(args, dict):
            raise BailianOutputError("tool_arguments_not_object")

        grounding = self._pop_grounding(args)
        tool_call = ExtractionToolCall(
            name=name,  # type: ignore[arg-type]
            arguments=args,
            confidence=self._extract_confidence(args),
            grounding=grounding,
            warnings=[],
            tool_call_id=tool_call_id,
        )
        raw_dump = {
            "id": tool_call_id,
            "type": "function",
            "function": {"name": name, "arguments": arguments_text},
        }
        return tool_call, raw_dump

    def _pop_grounding(self, args: dict[str, Any]) -> ActionGrounding | None:
        grounding_dict = args.pop("grounding", None)
        if not isinstance(grounding_dict, dict):
            return None
        source = grounding_dict.get("source")
        evidence_text = str(grounding_dict.get("evidence_text") or "")
        if source not in _GROUNDING_SOURCES:
            return None
        confidence_raw = grounding_dict.get("confidence")
        confidence: Decimal | None
        if isinstance(confidence_raw, (int, float)):
            try:
                confidence = Decimal(str(confidence_raw))
            except (ValueError, ArithmeticError):
                confidence = None
        else:
            confidence = None
        return ActionGrounding(
            source=source,  # type: ignore[arg-type]
            evidence_text=evidence_text,
            source_id=grounding_dict.get("source_id"),
            confidence=confidence,
        )

    def _extract_confidence(self, args: dict[str, Any]) -> Decimal | None:
        value = args.get("confidence")
        if isinstance(value, (int, float)):
            try:
                return Decimal(str(value))
            except (ValueError, ArithmeticError):
                return None
        return None

    def _derive_intent(
        self,
        tool_calls: list[ExtractionToolCall],
        assistant_text: str,
    ) -> Intent:
        if any(tc.name in _RECORD_TOOL_NAMES for tc in tool_calls):
            return "fitness_record"
        return "answer_fitness_question"

    def _aggregate_confidence(
        self,
        tool_calls: list[ExtractionToolCall],
    ) -> Decimal | None:
        values = [tc.confidence for tc in tool_calls if tc.confidence is not None]
        if not values:
            return None
        return max(values)

    def _repair_prompt(self, reason: str) -> str:
        return (
            f"上一次输出无法解析。失败原因: {reason}。"
            "请重新输出：使用 tool_calls 调用所需工具，或在 content 中给出最终回答。"
        )


_ALLOWED_TOOL_NAMES: set[str] = {
    tool["function"]["name"]
    for tool in TOOL_SCHEMAS
}


_GROUNDING_SOURCES: set[str] = {"user_message", "model_inference"}
