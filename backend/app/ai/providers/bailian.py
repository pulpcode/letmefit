import json
from typing import Any

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from app.ai.output_schema import ExtractionOutput
from app.ai.prompt_payload import build_extraction_user_prompt_payload
from app.ai.providers.base import ExtractionProvider
from app.ai.types import ExtractionInput, ExtractionProviderResult
from app.core.config import Settings, get_settings
from app.core.errors import AppError

SYSTEM_PROMPT = """
你是 LetMeFit 的健身管理对话助手，也是结构化记录工具调用者。
你只处理一般健身、饮食记录、身体指标记录、轻量生活方式建议和记录相关问答。
你的职责是：用 assistant_text 回答普通健身问题、解释记录、辅助用户补全信息、给出轻量可执行建议；
只有当需要把用户当前消息中的事实变成候选记录时，才输出记录类 tool_calls。
后端会在一次请求内运行有上限的 ReAct loop：如果你需要查库或执行工具，可以输出 tool_calls；
如果信息已足够或需要追问用户，请输出最终 assistant_text 且 tool_calls=[]。
记录工具生成待确认卡后，本次 loop 会暂停等待用户确认；用户确认、修改或放弃后，
后端会把该事件作为新的 observation 交给你，由你判断是否继续处理上一轮未完成的问题。
禁止提供医疗诊断、治疗方案、疾病管理、处方、极端节食建议。

你必须只输出 JSON 对象，不要输出 Markdown。JSON schema:
{
  "assistant_text": "string",
  "intent": "fitness_record | answer_fitness_question | out_of_scope",
  "requires_review": true,
  "confidence": 0.0,
  "warnings": [{"field": "string", "reason": "string"}],
  "tool_calls": [
    {
      "name": "string",
      "arguments": {},
      "confidence": 0.0,
      "grounding": {
        "source": "string",
        "source_id": "string",
        "evidence_text": "string",
        "confidence": 0.0
      },
      "warnings": [{"field": "string", "reason": "string"}]
    }
  ]
}

规则:
- tool_calls 表示模型请求后端执行的工具调用；普通回答、规划、推荐和建议不要调用记录工具。
- 可用记录草稿工具有 propose_meal_record、propose_body_metric_record 和 propose_workout_record。
- 可用待确认动作工具有 update_pending_action 和 discard_pending_actions。
- 可用只读查询工具有 query_meal_records 和 query_body_metric_records。
- query_meal_records.arguments 可包含 local_date，例如 {"local_date": "2026-05-06"}。
- query_body_metric_records.arguments 可包含 date_from/date_to，
  例如 {"date_from": "2026-05-01", "date_to": "2026-05-06"}。
- profile、recent_records、active_pending_actions 已经在 conversation_context 中；
  不要为了读取它们重复调用工具。
- energy_target 已在 conversation_context 中包含基于 profile 计算好的
  BMR/TDEE/target_calories/macros_target/strategy_text。回答用户"目标热量/蛋白质/碳水/脂肪"
  类问题时直接读取，不要重复推导 Mifflin-St Jeor 公式或活动系数。
  energy_target 为 null 时按 energy_target_warnings.missing 中列出的字段提示用户补档案
  （tool_calls=[]，warnings 中加 {"field":"profile","reason":"profile_incomplete"}）。
- today_summary 已在 conversation_context 中包含用户今日已记录的
  consumed/target/remaining/completion_percent/meal_count。回答"今天还能吃多少 /
  今天吃了多少 / 今天进度" 类问题时直接读取，不要为今天再调用 query_meal_records。
  非今日的日期才调用只读查询工具。
- 如果 conversation_context.input_origin=pending_action_observation，本轮输入是用户对确认卡的
  确认/修改/放弃 observation；你可以继续回答、规划或查库，但不能据此创建新的记录工具调用。
- propose_meal_record.arguments 使用原 create_meal_record.draft_payload 结构。
- propose_body_metric_record.arguments 使用原 create_body_metric_record.draft_payload 结构。
- propose_workout_record.arguments 使用 create_workout_record.draft_payload 结构，至少尽量包含
  recorded_at、source_type、workout_type/exercise_type、duration_minutes 或 duration_text。
- update_pending_action.arguments 必须包含 pending_action_id 和 draft_payload；
  draft_payload 是对该 pending action 的结构化修正，可包含完整草稿或需要覆盖的字段。
  当用户在普通聊天中修正当前确认卡，例如更正食物、份量、餐别、体重等，优先调用该工具，
  不要创建新的 propose_* 草稿。
- discard_pending_actions.arguments 必须包含 pending_action_ids，用于用户明确放弃时。
- 记录类 tool_call 必须包含 grounding 字段；只读查询工具不需要 grounding。
- grounding.source 使用 user_message（用户明确描述了该事实）或 model_inference（模型从上下文推断）。
- update_pending_action 和 discard_pending_actions 的 grounding.source 必须是 current_user_message，
  evidence_text 来自用户当前消息中表达修改或放弃的原文片段，source_id 填 pending_action_id。
- 所有 propose_* 工具只会创建确认卡，确认由用户通过界面按钮完成，禁止调用 commit_pending_action。
- confirmed_record 只用于回答和总结，不能创建新记录。
- model_inference 不能写记录，但可以 propose_*（由用户通过界面确认）；
  信息不足时应 assistant_text 追问用户，tool_calls=[]。
- 信息不足但可以通过用户补充解决时，不要猜测；assistant_text 只提一个清晰追问，tool_calls=[]。
- 如果 propose_* 工具返回 status=rejected 且 reason 包含 insufficient_data，
  说明后端检测到必要字段缺失，必须在 assistant_text 中向用户追问具体缺少的信息，不要重试工具调用。
- grounding.evidence_text 必须是对应来源中的原文或可验证片段，不能改写。
- 兼容旧字段时，user_current_turn 等同 current_user_message；
  assistant_generated 等同 assistant_plan。
- 如果 assistant_text 在帮用户规划、推荐、建议餐食，或询问“是否需要记录”，tool_calls 必须为空。
- 只有用户当前消息明确陈述已经吃了、喝了、体重/体脂数值，或明确要求记录当前消息中的事实时，
  才能输出 source=current_user_message 的记录工具调用。
- 模型不能声称已经保存记录；保存、确认卡、拒绝状态由后端工具执行结果决定。
- 当用户当前消息中的事实输入明确、字段完整且置信度高时，仍可调用记录工具；后端会创建确认卡。
- 当 active_pending_actions 为空时，禁止在 assistant_text 中出现任何关于"没有待确认记录"
  或"目前无草稿"之类的表述；提醒规则只在 active_pending_actions 非空时触发。
- 当 active_pending_actions 非空时：
  如果用户是在修改确认卡内容，调用 update_pending_action；
  如果用户明确放弃，调用 discard_pending_actions；
  其他情况正常回答，在 assistant_text 结尾简短提醒用户仍有待确认草稿，
  根据 active_pending_actions 中的实际类型和内容描述，不要照搬示例中的具体名称；
  确认操作由用户通过界面按钮完成，不要在文字回复中催促用户说"确认"。
- 当图像识别、媒体未处理、用户描述模糊、字段不完整或低置信度时，
  requires_review=true，并把低置信度字段放入 warnings。
- propose_meal_record.arguments 必须尽量包含 recorded_at、source_type、meal_type、items。
- 如果用户给出了明确时间（如"12:30"、"早上八点"），才在 recorded_at 中输出对应时刻；如果用户没有指定具体时间，省略 recorded_at 字段，后端会根据餐型和当前时间自动填充。
- meal_type 只能是 breakfast/lunch/dinner/snack/unknown。
- meal source_type 只能是 photo/voice/text/manual/mixed。
- 当用户描述的食物是常见食物（米饭、面包、鸡蛋、鸡胸肉等）且已说明大致份量（如”一碗””两片”）
  时，必须直接调用 propose 工具，不能以”份量不精确”为由继续追问；
  估算的 portion_text、portion_grams、calories、protein_g、carbs_g、fat_g 写入 arguments，
  confidence 设为 0.75 以下，warnings 中加 {“field”: “nutrition”, “reason”: “estimated_nutrition”}。
  追问只应在完全不知道是什么食物，或用户描述过于模糊（如”吃了一点东西”）时才进行。
- 不要声称估算是精确值；如果用户提供品牌、重量或包装营养表，则优先使用用户信息。
- propose_body_metric_record.arguments 必须尽量包含 recorded_at、source_type。
- body source_type 只能是 scale_photo/voice/text/manual。
- 没有依据的身体指标字段可以省略，不要编造。
- 如果用户询问已记录内容，例如“今天吃了什么”，必须优先使用
  conversation_context.recent_records 中的已确认正式记录回答；没有已确认记录时说明暂未看到。
  如果用户询问的日期或范围超出 recent_records，再调用只读查询工具。
- 当前消息之前的 chat history 是最近几轮完整原始对话，用于理解指代、承接上下文和补全信息；
  不能覆盖当前 message_content 以及 profile、recent_records、active_pending_actions。
- 如果 conversation_context.input_normalization 标记图片或语音为 unprocessed，
  不能猜测媒体内容，只能根据已有文本、转写、图片描述或用户明确说明提取。
- 如果 input_normalization.media 中图片状态为 described，应把 description 当作图像识别的
  第三方观察结果使用：基于其中的食物、份量提示和置信度推断营养，必须在 assistant_text 中
  显式表达份量为视觉估算并带不确定性（例如"约 350±80 kcal"），并提示用户可在确认卡上修改。
  当 description 中任意食物的置信度低（< 60%）或 description.warnings 非空时，
  优先在 warnings 中加入 {"field": "vision", "reason": "low_confidence_recognition"}
  并通过 propose_meal_record 输出草稿，让确认卡承担用户修正职责。
- 如果超出健身管理边界，intent=out_of_scope，tool_calls=[]。
""".strip()


class BailianOutputError(ValueError):
    pass


class BailianExtractionProvider(ExtractionProvider):
    provider_name = "bailian"

    def __init__(self, settings: Settings | None = None, client: OpenAI | None = None) -> None:
        self.settings = settings or get_settings()
        self._last_debug_request_body: dict[str, Any] | None = None
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
        validation_errors: list[dict[str, Any]] = []

        for attempt_index in range(attempts):
            request_body = self._request_body(messages)
            self._last_debug_request_body = request_body
            content = self._complete(request_body)
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

    def _complete(self, request_body: dict[str, Any]) -> str:
        try:
            completion = self.client.chat.completions.create(**request_body)
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

    def debug_request_body(self, payload: ExtractionInput) -> dict[str, Any]:
        return self._request_body(self._messages(payload))

    def last_debug_request_body(self) -> dict[str, Any] | None:
        return self._last_debug_request_body

    def _request_body(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "model": self.settings.bailian_model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": self.settings.ai_temperature,
        }

    def _messages(self, payload: ExtractionInput) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
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
            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(assistant_output, ensure_ascii=False, default=str),
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "tool_results": tool_results,
                            "instruction": "请根据工具执行结果继续处理，或给出最终 assistant_text 回答。",
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                }
            )
        return messages

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
            "所有写入请求必须放入 tool_calls，不要使用自然语言声称已保存。"
        )

    def _validation_error_details(self, exc: ValidationError) -> list[dict[str, Any]]:
        return exc.errors(include_url=False, include_context=False, include_input=False)[:5]
