# LetMeFit Agent Tool Call Design

## Summary

当前模型定位是“健身管理对话助手 + 结构化记录工具调用者”。后端在一次请求内运行 bounded ReAct loop：

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

简单问题通常一轮模型决策结束并直接返回 `assistant_text`。复杂问题可以先调用工具，后端把 `tool_results` 放回上下文后再让模型生成最终回答。信息不足时，模型应直接用 `assistant_text` 追问用户，`tool_calls=[]`，后端不会创建草稿。

外部 REST API 保持兼容：`POST /conversations/{id}/messages` 仍返回 `pending_actions`、`committed_records` 和 `tool_results`。调试时可通过请求字段 `include_agent_trace=true` 额外返回脱敏 `agent_trace`。

## Loop Limits

第一版 loop 只在单次请求内运行，不持久化中间状态，也不支持中断恢复。默认限制：

- 最多 3 次模型决策。
- 最多 2 轮工具执行。
- 每轮最多 3 个工具调用。
- 单次请求最多 6 个工具调用。
- 单次 loop 有总超时保护。

触发限制后，后端停止执行新的工具调用，返回受控降级回答，并在 trace 中加入 `loop_limit_reached`。

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

- `current_user_message` / `normalized_media_text`: 可进入后端自动保存判断。
- `recent_user_message` / `active_pending_action` / `tool_result`: 可创建确认卡，默认不能自动保存。
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
- `pending_confirmation`: 已创建确认卡，等待用户确认或修改。
- `committed`: 后端规则判定可自动写入，已保存正式记录。

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

后续如需实时展示过程，可新增 `POST /conversations/{id}/messages/stream`，返回 chunked NDJSON 或 SSE-like event stream。当前普通 JSON 接口继续作为兼容 fallback。

## Response Composition

模型不能决定“是否已保存”。保存、确认卡、拒绝状态只以后端真实执行结果为准。

后端响应文案规则：

- 有 `committed_records`：后端生成“已自动保存...”事件和文案。
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
