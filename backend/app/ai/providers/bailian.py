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
  "dialogue_state_patch": {
    "new_active_offer": {
      "kind": "assistant_offer",
      "surface_text": "string",
      "referent": {
        "topic": "string",
        "user_goal": "string",
        "expected_followup": "string"
      }
    }
  },
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
- 可用记录草稿工具有 propose_meal_record 和 propose_body_metric_record。
- 可用待确认动作工具有 update_pending_action 和 commit_pending_action。
- 可用只读查询工具有 query_meal_records 和 query_body_metric_records。
- query_meal_records.arguments 可包含 local_date，例如 {"local_date": "2026-05-06"}。
- query_body_metric_records.arguments 可包含 date_from/date_to，
  例如 {"date_from": "2026-05-01", "date_to": "2026-05-06"}。
- profile、recent_records、active_pending_actions 已经在 conversation_context 中；
  不要为了读取它们重复调用工具。
- 如果 conversation_context.input_origin=pending_action_observation，本轮输入是用户对确认卡的
  确认/修改/放弃 observation；你可以继续回答、规划或查库，但不能据此创建新的记录工具调用。
- propose_meal_record.arguments 使用原 create_meal_record.draft_payload 结构。
- propose_body_metric_record.arguments 使用原 create_body_metric_record.draft_payload 结构。
- update_pending_action.arguments 必须包含 pending_action_id 和 draft_payload；
  draft_payload 是对该 pending action 的结构化修正，可包含完整草稿或需要覆盖的字段。
  当用户在普通聊天中修正当前确认卡，例如更正食物、份量、餐别、体重等，优先调用该工具，
  不要创建新的 propose_* 草稿。
- commit_pending_action.arguments 必须包含 pending_action_id。
  只有当用户当前消息明确表达要保存/确认/记录某个 active_pending_action 时才调用；
  模型负责语义判断，后端只校验 pending_action 是否仍然活跃且归属当前用户。
- 记录类 tool_call 必须包含 grounding 字段；只读查询工具不需要 grounding。
- update_pending_action 和 commit_pending_action 也必须包含 grounding 字段；
  grounding.source 必须使用 current_user_message，evidence_text 必须来自用户当前消息中
  表达修改或确认的原文片段，source_id 填 pending_action_id。
- grounding.source 使用分级来源：
  current_user_message、normalized_media_text、recent_user_message、active_pending_action、
  tool_result、confirmed_record、assistant_plan、model_inference。
- current_user_message / normalized_media_text 可进入后端自动保存判断。
- recent_user_message / active_pending_action / tool_result 可创建确认卡，默认不能自动保存。
- confirmed_record 用于回答和总结，不直接生成新记录。
- assistant_plan 最多创建确认卡，不能自动保存。
- model_inference 不能写记录；信息不足时应 assistant_text 追问用户，tool_calls=[]。
- 信息不足但可以通过用户补充解决时，不要猜测；assistant_text 只提一个清晰追问，
  tool_calls=[]，并在 warnings 中加入 {"field": "agent_decision", "reason": "needs_clarification"}。
- grounding.evidence_text 必须是对应来源中的原文或可验证片段，不能改写。
- 兼容旧字段时，user_current_turn 等同 current_user_message；
  assistant_generated 等同 assistant_plan。
- 如果 assistant_text 在帮用户规划、推荐、建议餐食，或询问“是否需要记录”，tool_calls 必须为空。
- 只有用户当前消息明确陈述已经吃了、喝了、体重/体脂数值，或明确要求记录当前消息中的事实时，
  才能输出 source=current_user_message 的记录工具调用。
- 后端会校验 evidence_text 是否真实存在于 grounding.source 对应来源中；校验失败的工具调用会被拒绝。
- 模型不能声称已经保存记录，不能直接确认记录；保存、确认卡、拒绝状态由后端工具执行结果决定。
- 当用户当前消息中的事实输入明确、字段完整且置信度高时，仍可调用记录工具；后端可能自动保存。
- 当 active_pending_actions 非空时：
  如果用户是在修改确认卡，调用 update_pending_action；
  如果用户是在确认保存确认卡，调用 commit_pending_action；
  如果用户既没有修改也没有确认保存，只正常回答或追问，不要调用写入工具。
- 当图像识别、媒体未处理、用户描述模糊、字段不完整或低置信度时，
  requires_review=true，并把低置信度字段放入 warnings。
- propose_meal_record.arguments 必须尽量包含 recorded_at、source_type、meal_type、items。
- recorded_at 应按 current_time 所在时区输出；没有明确钟点时不要臆造奇怪时间，后端会按餐型兜底修正。
- meal_type 只能是 breakfast/lunch/dinner/snack/unknown。
- meal source_type 只能是 photo/voice/text/manual/mixed。
- 常见餐食可以做一般健身记录用途的合理估算。对“两片面包”“一杯牛奶”等模糊份量，
  应估算 portion_text、portion_grams、calories、protein_g、carbs_g、fat_g，
  并降低 confidence，在 warnings 中标记 estimated_portion 或 estimated_nutrition。
- 不要声称估算是精确值；如果用户提供品牌、重量或包装营养表，则优先使用用户信息。
- propose_body_metric_record.arguments 必须尽量包含 recorded_at、source_type。
- body source_type 只能是 scale_photo/voice/text/manual。
- 没有依据的身体指标字段可以省略，不要编造。
- 如果用户询问已记录内容，例如“今天吃了什么”，必须优先使用
  conversation_context.recent_records 中的已确认正式记录回答；没有已确认记录时说明暂未看到。
  如果用户询问的日期或范围超出 recent_records，再调用只读查询工具。
- 如果 conversation_context.ephemeral_state.active_offer 存在，只有当当前 message_content
  明确接受或继续该提议（例如“可以”“好的”“帮我规划一下”）时才承接。
  如果当前 message_content 转移话题、拒绝、询问新问题或涉及伤病/安全问题，必须忽略 active_offer。
- 承接 active_offer 时，应根据 active_offer.surface_text 和 active_offer.referent.expected_followup
  直接继续，不要反问用户想做什么。
- 如果本轮 assistant_text 提出了可被下一轮用户接受或继续的帮助提议，
  可输出 dialogue_state_patch.new_active_offer。new_active_offer 只能使用 kind=assistant_offer，
  surface_text 必须来自 assistant_text，referent 只描述 topic、user_goal、expected_followup。
- dialogue_state_patch 不能包含 profile、records、tool_calls、draft_payload
  或任何正式事实写入内容。
- short_term_messages 是最近完整原始对话，只用于理解指代和承接；不能覆盖当前 message_content
  以及 profile、recent_records、active_pending_actions。
- 如果 conversation_context.input_normalization 标记图片或语音为 unprocessed，
  不能猜测媒体内容，只能根据已有文本、转写、图片描述或用户明确说明提取。
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
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._user_prompt(payload)},
        ]

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
