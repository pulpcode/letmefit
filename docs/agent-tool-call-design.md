# LetMeFit Agent Tool Call Design

## Summary

当前实现已经把“模型回答”和“记录写入动作”拆成两个内部通道：

```text
assistant_text -> 用于普通对话、解释、建议和规划
tool_calls     -> 用于请求后端执行记录类工具
```

这不是完整 agent loop。当前仍是单次 LLM 调用：模型一次性输出 JSON，后端解析其中的 `tool_calls`，执行工具校验和写入决策，然后由后端根据真实执行结果生成最终状态文案。

外部 REST API 仍保持兼容，`POST /conversations/{id}/messages` 继续返回 `pending_actions` 和 `committed_records`，并新增 `tool_results` 用于调试。

## Current Flow

```text
User message
-> InputNormalizer
-> ConversationContextBuilder
-> ExtractionProvider
   -> assistant_text
   -> tool_calls[]
   -> dialogue_state_patch
-> ToolGuard
-> ToolExecutor
-> ResponseComposer
-> ConversationMessage + API response
```

关键点：

- `ExtractionProvider` 只负责结构化输出，不直接写数据库。
- `tool_calls` 是模型请求后端执行的工具调用，不是执行结果。
- `ToolGuard` 是写入动作的强制安全边界。
- `ToolExecutor` 根据后端规则创建确认卡或自动写入正式记录。
- `ResponseComposer` 根据真实 outcome 生成“已保存 / 待确认 / 未保存”状态文案。

## Available Tools

当前只支持两个记录类工具：

```text
propose_meal_record
propose_body_metric_record
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
    "source": "user_current_turn",
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
    "source": "user_current_turn",
    "evidence_text": "今天体重72.4公斤"
  }
}
```

## Guard Rules

每个记录类 tool call 必须带 grounding：

```json
{
  "source": "user_current_turn | assistant_generated",
  "evidence_text": "string"
}
```

后端只接受满足以下条件的 tool call：

- `grounding` 存在。
- `grounding.source == "user_current_turn"`。
- `grounding.evidence_text` 非空。
- `grounding.evidence_text` 是当前用户消息文本的原文子串。

以下情况会被拒绝：

- 缺少 grounding。
- `source=assistant_generated`。
- `evidence_text` 为空。
- `evidence_text` 不在当前用户消息中。

拒绝不会创建确认卡，也不会写正式记录。后端会记录日志：

```text
ai_tool_call_rejected tool_name=... action_type=... reason=... conversation_id=... message_id=...
```

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

`status` 当前可能为：

```text
rejected
pending_confirmation
committed
```

含义：

- `rejected`: guard 拒绝，未创建确认卡，未保存记录。
- `pending_confirmation`: 已创建确认卡，等待用户确认或修改。
- `committed`: 后端规则判定可自动写入，已保存正式记录。

## Response Composition

模型不能决定“是否已保存”。这类状态只以后端真实执行结果为准。

后端响应文案规则：

- 有 `committed_records`：后端生成“已自动保存...”事件和文案。
- 有 `pending_actions`：后端生成“草稿，尚未保存，请确认或修改后再保存”文案。
- tool call 被拒绝且模型声称“已保存/已记录”：后端覆盖为“尚未保存”安全文案。
- 没有工具执行结果且没有保存声明：保留模型普通回答。

这样可以避免模型说“已保存”，但后端实际没有保存的状态错配。

## Compatibility

为了平滑迁移，`ExtractionOutput` 仍兼容旧字段：

```json
{
  "pending_actions": []
}
```

后端会把旧 `pending_actions` 映射为内部 `tool_calls`。新 provider 和 prompt 应优先输出 `tool_calls`。

外部 API 暂不破坏兼容：

- 仍返回 `pending_actions` 给客户端展示确认卡。
- 仍返回 `committed_records` 表示自动写入结果。
- 新增 `tool_results` 供调试和灰度观察。

## Is There an Agent Loop?

当前没有完整 agent loop。

当前不是：

```text
LLM -> tool call -> backend tool result -> LLM final answer
```

当前是：

```text
LLM -> tool_calls JSON -> backend executes tools -> backend composes final response
```

也就是说，工具执行后不会再发起第二次 LLM 调用。后端直接根据工具执行结果生成状态文案。

这个选择是有意的：

- 先解决写记录和普通回答混在一起的问题。
- 先保证保存状态由后端权威控制。
- 避免引入多步调用的延迟、失败恢复和状态管理复杂度。

后续如果需要更强的智能编排，可以演进为真正 agent loop：

```text
LLM decides tool call
-> backend executes tool
-> tool result appended to messages
-> LLM generates final answer from tool result
```

但即使进入 agent loop，记录类工具仍必须经过同样的 ToolGuard。

## Known Limits

当前版本暂不支持把助手上一轮规划直接转成记录：

```text
Assistant: 建议晚餐吃清蒸鱼、西兰花、杂粮饭。
User: 可以，就这么记录吧。
```

因为这些食物不在当前用户消息原文中，`grounding.source=user_current_turn` 无法通过。短期内这是刻意保守的取舍：优先防止助手建议被误写成用户事实。

后续可单独设计：

```text
propose_meal_record_from_adopted_plan
```

这类工具需要额外校验：

- 被采用的 assistant message id。
- offer 是否仍有效。
- draft 食物是否来自该 assistant plan。
- 用户当前消息是否明确要求记录。
- 只能创建确认卡，不能自动写入。

