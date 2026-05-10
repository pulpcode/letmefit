# LetMeFit Agent Tool Call Design

## Summary

当前模型定位是“健身管理对话助手 + 结构化记录工具调用者”。后端运行 bounded ReAct loop；记录草稿需要人确认时，loop 会异步暂停，等待用户确认/修改/放弃后再用 observation 恢复：

```text
User message
-> InputNormalizer
-> ConversationContextBuilder
-> AgentRuntime
   -> model decision
   -> optional backend tools
   -> optional model final answer
-> ConversationMessage + API response
```

简单问题通常一轮模型决策结束并直接返回 `assistant_text`。复杂问题可以先调用只读工具，后端把 `tool_results` 放回上下文后再让模型生成最终回答。信息不足时，模型应直接用 `assistant_text` 追问用户，`tool_calls=[]`，后端不会创建草稿。

记录工具遵循异步确认语义：

- `pending_confirmation`：创建确认卡后立即结束当前 HTTP 请求，trace 追加 `human_confirmation_required`，等待用户动作。
- `needs_clarification`：创建需要补充信息的确认卡后立即结束当前 HTTP 请求，等待用户补充或放弃。
- `committed`：用户确认已有确认卡后写入正式记录，作为普通 tool observation 回填。
- `rejected`：作为普通 tool observation 回填，允许模型下一轮追问或解释失败原因。

用户确认、修改后确认、放弃确认卡时，正式客户端默认先由后端接口处理状态和写入。只有需要继续总结、回答剩余问题或客户端显式请求时，才传入 `continue_agent=true`；后端会把该动作构造成 `pending_action_observation`，作为新一轮 ReAct 的当前输入交给模型。这里不会把按钮文案“确认”当作普通用户消息发送给模型。

用户给出修改意见时优先更新现有 pending action，而不是创建新草稿。结构化编辑直接 PATCH `draft_payload`；普通聊天中的自然语言修改交给 LLM 判断，LLM 应调用 `update_pending_action` 工具更新原草稿。用户明确表达保存或确认待确认草稿时，LLM 应调用 `commit_pending_action`；批量确认/放弃时调用 `commit_pending_actions` / `discard_pending_actions`。后端不靠关键词判断“修改/保存”意图，只校验工具调用引用的 pending action、当前用户消息 evidence、用户归属、状态和过期时间。

外部 REST API 保持兼容：`POST /conversations/{id}/messages` 仍返回 `pending_actions`、`committed_records` 和 `tool_results`。调试时可通过请求字段 `include_agent_trace=true` 额外返回脱敏 `agent_trace`。

## Loop Limits

第一版不持久化模型内部推理栈。普通 loop 只在单次请求内运行；遇到确认卡时暂停，用户动作会作为新的 observation 触发一轮新的 bounded loop。默认限制：

- 最多 3 次模型决策。
- 最多 2 轮工具执行。
- 每轮最多 3 个工具调用。
- 单次请求最多 6 个工具调用。
- 单次 loop 有总超时保护。

触发限制后，后端停止执行新的工具调用，返回受控降级回答，并在 trace 中加入 `loop_limit_reached`。运行时熔断只写入 `agent_trace`，不会伪装成 `tool_results` 中的工具结果。

## Available Tools

默认上下文已经携带 `profile`、`recent_records`、`active_pending_actions`，因此不设计“读取 profile / recent_records”的必调工具。

记录工具：

```text
propose_meal_record
propose_body_metric_record
```

只读查询工具：

```text
query_meal_records
query_body_metric_records
```

后续可扩展：

```text
nutrition_lookup
nutrition_estimate
nutrition_calculate
record_trend_stats
```

### `propose_meal_record`

用于提议创建餐食记录草稿。`arguments` 使用餐食 draft payload：

```json
{
  "name": "propose_meal_record",
  "arguments": {
    "recorded_at": "2026-05-05T19:30:00+08:00",
    "source_type": "text",
    "meal_type": "dinner",
    "items": []
  },
  "grounding": {
    "source": "current_user_message",
    "evidence_text": "我晚餐吃了120g鸡胸肉"
  }
}
```

### `propose_body_metric_record`

用于提议创建身体指标记录草稿。`arguments` 使用身体指标 draft payload：

```json
{
  "name": "propose_body_metric_record",
  "arguments": {
    "recorded_at": "2026-05-05T08:00:00+08:00",
    "source_type": "text",
    "weight_kg": 72.4
  },
  "grounding": {
    "source": "current_user_message",
    "evidence_text": "今天体重72.4公斤"
  }
}
```

### `query_meal_records`

查询已确认餐食记录。优先使用默认上下文里的 `recent_records`；只有用户询问的日期或范围超出默认上下文时再调用。

```json
{
  "name": "query_meal_records",
  "arguments": {
    "local_date": "2026-05-06"
  }
}
```

### `query_body_metric_records`

查询已确认身体指标记录：

```json
{
  "name": "query_body_metric_records",
  "arguments": {
    "date_from": "2026-05-01",
    "date_to": "2026-05-06"
  }
}
```

## Grounding Levels

每个记录类 tool call 必须带 grounding。只读工具不需要 grounding。

```json
{
  "source": "current_user_message",
  "source_id": "optional",
  "evidence_text": "string",
  "confidence": 0.9
}
```

分级规则：

- `current_user_message` / `normalized_media_text`: 可创建确认卡。
- `recent_user_message` / `active_pending_action` / `tool_result`: 可创建确认卡。
- `assistant_plan`: 最多创建确认卡，不能自动保存。
- `confirmed_record`: 只能用于回答和总结，不能直接生成新记录。
- `model_inference`: 不能写记录，只能回答或追问。

兼容旧字段：

- `user_current_turn` 等同 `current_user_message`。
- `assistant_generated` 等同 `assistant_plan`。

后端会校验 `evidence_text` 是否能在对应来源中找到。校验失败的 tool call 会被拒绝，不创建确认卡，也不写正式记录。

## Execution Results

后端执行 tool call 后生成 `tool_results`：

```json
[
  {
    "tool_name": "propose_meal_record",
    "action_type": "create_meal_record",
    "status": "pending_confirmation",
    "pending_action_id": "pa_..."
  }
]
```

记录工具状态：

- `rejected`: guard 拒绝，未创建确认卡，未保存记录。
- `pending_confirmation`: 已创建可确认保存的确认卡，等待用户确认、修改或放弃。
- `needs_clarification`: 已创建候选卡，但关键字段不足或冲突，等待用户补充或放弃。
- `committed`: 用户确认待确认动作后，后端已保存正式记录。

只读工具状态：

- `succeeded`: 查询成功，结果放在 `data` 中。
- `rejected`: 参数或工具不支持。

## Agent Trace

`include_agent_trace=true` 时，响应会返回脱敏执行轨迹。trace 不包含模型隐含思维链，不包含原始 provider 输出。

事件类型：

```text
agent_started
model_decision
tool_call_started
tool_result
human_confirmation_required
clarifying_question
final_answer
loop_limit_reached
```

示例：

```json
[
  {"event": "agent_started", "max_model_turns": 3, "max_tool_rounds": 2},
  {"event": "model_decision", "model_turn": 1, "decision": "tool_calls"},
  {"event": "tool_call_started", "tool_round": 1, "tool_name": "query_meal_records"},
  {"event": "tool_result", "tool_round": 1, "tool_name": "query_meal_records", "status": "succeeded"},
  {"event": "model_decision", "model_turn": 2, "decision": "final_answer"},
  {"event": "final_answer", "model_turn": 2}
]
```

实时展示使用 `POST /conversations/{id}/messages/stream`，返回 SSE-like event stream。当前普通 JSON 接口继续作为兼容 fallback。图片输入会先流式返回 `type=vision` 的具体图片理解内容，随后再返回 assistant 文本和最终 `done` 数据；这些事件只能用于前端展示，不能绕过 pending action 确认直接写正式记录。

## Pending Action Observation

确认卡的用户动作可恢复异步 ReAct。接口请求体：

```json
{
  "continue_agent": true,
  "include_agent_trace": true
}
```

确认成功后，后端内部构造 observation：

```json
{
  "type": "pending_action_observation",
  "event": "confirmed",
  "pending_action_id": "pa_...",
  "action_type": "create_meal_record",
  "record_type": "meal",
  "record_id": "meal_...",
  "record_summary": "午餐：炒面，约 650 千卡"
}
```

放弃时：

```json
{
  "type": "pending_action_observation",
  "event": "discarded",
  "pending_action_id": "pa_...",
  "action_type": "create_meal_record"
}
```

该 observation 会进入 `conversation_context.current_observation`，并设置 `input_origin=pending_action_observation`。在这个输入来源下，模型可以回答、规划或调用只读查询工具，但不能基于 observation 创建新的记录写入工具调用；若输出记录工具，后端会拒绝，不创建新的 pending action。

## Response Composition

模型不能决定“是否已保存”。保存、确认卡、拒绝状态只以后端真实执行结果为准。

后端响应文案规则：

- 有 `committed_records`：后端生成“已保存...”事件和文案。
- 有 `pending_actions`：后端生成“草稿，尚未保存，请确认或修改后再保存”文案。
- tool call 被拒绝且模型声称“已保存/已记录”：后端覆盖为“尚未保存”安全文案。
- 没有工具执行结果且没有保存声明：保留模型普通回答。

## Known Limits

当前版本暂不支持把助手上一轮规划直接自动保存为正式记录：

```text
Assistant: 建议晚餐吃清蒸鱼、西兰花、杂粮饭。
User: 可以，就这么记录吧。
```

如果产品需要支持该能力，应新增专门工具，例如 `propose_meal_record_from_adopted_plan`。这类工具只能生成确认卡，不能自动保存，并且必须校验被采用的 assistant message、offer 有效性、用户当前消息是否明确要求记录。
