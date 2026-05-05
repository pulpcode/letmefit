# LetMeFit 对话上下文组织设计

本文说明 LetMeFit V1 当前对话上下文的组织方式、压缩方式、待确认内容与已确认内容的生命周期，以及后续需要明确的上下文优先级规则。

相关代码入口：

- `backend/app/services/conversations.py`
- `backend/app/services/conversation_context.py`
- `backend/app/services/pending_actions.py`
- `backend/app/ai/prompt_payload.py`
- `backend/app/ai/providers/bailian.py`

## 1. 设计目标

LetMeFit 的 Agent 对话同时承担三件事：

1. 接收用户输入，包括文本、语音、图片。
2. 通过 LLM 提取结构化候选动作，由后端规则决定自动保存或进入待确认。
3. 自动保存或用户确认后，把记录写入正式记录，并在后续对话中作为可信事实使用。

因此上下文不能只是“最近聊天记录”。它必须区分：

- 当前用户这次说了什么
- 哪些内容只是历史对话
- 哪些内容是当前还在等待用户确认的草稿
- 哪些内容已经由用户确认并写入正式记录
- 哪些内容只是压缩摘要，不能当作正式事实

## 2. 当前消息处理链路

当前 `POST /conversations/{conversation_id}/messages` 的主要链路如下：

```text
用户消息
  -> ConversationService.send_message
  -> 保存 user ConversationMessage
  -> 绑定 MessageAttachment
  -> InputNormalizer 处理语音/图片
  -> ConversationContextBuilder.build
  -> ExtractionService.process_message
  -> BailianExtractionProvider.extract
  -> 生成 assistant ConversationMessage
  -> 必要时生成 AgentPendingAction
  -> compact_if_needed 滚动压缩旧消息
```

### 2.1 原始消息

用户原始消息会先写入 `conversation_messages`：

| 字段 | 含义 |
| --- | --- |
| `role` | `user` 或 `assistant` |
| `content_json` | 原始消息内容，例如文本、图片 `file_id`、音频 `file_id` |
| `intent` | LLM 识别后的意图，用户消息在提取后回填 |
| `requires_review` | 是否产生需要用户确认的动作 |
| `created_at` | 消息创建时间 |

注意：这里保存的是原始用户消息，不包含 ASR 派生出来的文本。

### 2.2 输入归一化

`InputNormalizer` 会把多模态输入转成 LLM 更容易处理的形式。

语音输入：

```text
audio file_id
  -> ASR provider
  -> transcript
  -> 追加一条派生 text: "语音转写: ..."
```

图片输入：

```text
image file_id
  -> vision provider
  -> description
  -> 追加一条派生 text: "图片理解: ..."
```

归一化结果分两部分进入 LLM：

```json
{
  "message_content": [
    {
      "type": "text",
      "text": "这是一段餐食语音，请转写并整理成待确认记录。"
    },
    {
      "type": "audio",
      "file_id": "file_...",
      "duration_seconds": 10
    },
    {
      "type": "text",
      "text": "语音转写: 今天早餐吃了两个鸡蛋",
      "source": "asr"
    }
  ],
  "conversation_context": {
    "input_normalization": {
      "asr_provider": "dashscope_recording",
      "vision_provider": "mock",
      "media": [
        {
          "file_id": "file_...",
          "type": "audio",
          "status": "transcribed",
          "transcript": "今天早餐吃了两个鸡蛋",
          "provider": "dashscope_recording"
        }
      ]
    }
  }
}
```

重要字段：

| 字段 | 含义 |
| --- | --- |
| `status=transcribed` | 语音已成功转写，LLM 可以使用 `transcript` |
| `status=described` | 图片已成功理解，LLM 可以使用 `description` |
| `status=unprocessed` | 媒体未处理成功，LLM 不得猜测媒体内容 |
| `warnings` | ASR/图片理解失败原因，例如 mock、403、超时 |
| `server_accessible` | 后端是否可以访问该媒体文件 |

## 3. 当前 LLM prompt payload 结构

当前 `build_extraction_user_prompt_payload` 生成的 user prompt 是一个 JSON 对象：

```json
{
  "current_time": "2026-05-03T15:39:19.024124+08:00",
  "input_types": ["text", "audio"],
  "message_content": [],
  "conversation_context": {},
  "output_language": "zh-CN",
  "instruction": "请按 JSON schema 输出结构化提取结果。"
}
```

字段说明：

| 字段 | 当前含义 |
| --- | --- |
| `current_time` | 本次模型调用时间，用于理解“今天、早上、刚刚”等相对时间 |
| `input_types` | 本次归一化后输入类型集合 |
| `message_content` | 当前用户消息和派生文本，是本轮任务的最高优先级输入 |
| `conversation_context` | 由后端构造的历史、档案、记录、待确认动作上下文 |
| `output_language` | 回复语言 |
| `instruction` | 要求模型按结构化 schema 输出 |

## 4. 当前 conversation_context 结构

当前 `ConversationContextBuilder.build` 返回：

```json
{
  "memory_policy": {},
  "policy": {},
  "ephemeral_state": {},
  "durable_context": {},
  "profile": {},
  "latest_conversation_summary": {},
  "conversation_summary": {},
  "recent_messages": [],
  "short_term_messages": [],
  "active_pending_actions": [],
  "recent_records": {
    "meals": [],
    "body_metrics": []
  },
  "input_normalization": {}
}
```

### 4.1 memory_policy

`memory_policy` 是新的上下文策略字段：

```json
{
  "summary_mode": "async_rolling",
  "short_term_full_turns": 4,
  "short_term_message_limit": 8,
  "recent_preview_message_limit": 8
}
```

`policy` 暂时保留用于兼容旧调试输出。

### 4.2 ephemeral_state / durable_context

`ephemeral_state.active_offer` 是上一轮助手提出的通用一次性承接令牌，例如“需要我帮你规划晚餐吗？”。它不使用固定业务枚举，而是保存助手原话和通用 referent：

```json
{
  "kind": "assistant_offer",
  "surface_text": "需要我帮你规划晚餐吗？",
  "referent": {
    "topic": "晚餐方案",
    "user_goal": "基于今日记录安排晚餐",
    "expected_followup": "用户同意时直接生成晚餐方案"
  }
}
```

它只允许在用户下一条消息明确接受或继续该提议时使用；无论用户接茬、拒绝还是转移话题，本轮结束后旧 `active_offer` 都会失效。新 offer 由 LLM 输出 `dialogue_state_patch.new_active_offer`，后端只做结构校验和一回合生命周期管理。

更长期的主题线索放在 `durable_context`，例如 `last_topic`。这类信息只能帮助理解上下文，不能自动消费用户的“好的/可以”。

### 4.3 legacy policy

```json
{
  "summary_mode": "rolling",
  "recent_message_limit": 8
}
```

| 字段 | 含义 |
| --- | --- |
| `summary_mode` | 兼容字段；新逻辑使用 `memory_policy.summary_mode=async_rolling` |
| `recent_message_limit` | 每次最多带入多少条未被摘要覆盖的最近消息 |

### 4.4 profile

来自 `user_profiles`，用于长期稳定的用户档案。

```json
{
  "age": 30,
  "sex": "male",
  "height_cm": 175,
  "current_weight_kg": 72.4,
  "target_weight_kg": 68,
  "activity_level": "moderate",
  "goal_type": "fat_loss",
  "profile_completed": true
}
```

`profile` 是正式用户档案，可信度高于普通历史对话。

### 4.5 latest_conversation_summary / conversation_summary

来自 `conversation_summaries`，用于压缩旧对话。

```json
{
  "id": "conv_sum_...",
  "from_message_id": "msg_...",
  "to_message_id": "msg_...",
  "summary_text": "滚动摘要，用于后续模型上下文；正式事实以档案和记录表为准。",
  "token_estimate": 200,
  "created_at": "2026-05-03T10:00:00"
}
```

注意：摘要只是上下文线索，不能当作正式记录。正式事实必须来自 `profile`、`recent_records` 或当前 `active_pending_actions`。

`latest_conversation_summary` 是新字段，只读取 `status=succeeded` 的最新摘要。`conversation_summary` 暂时作为兼容别名保留。

### 4.6 recent_messages / short_term_messages

最近消息来自 `conversation_messages`。当前消息会通过 `exclude_message_id` 排除，因此 `recent_messages` 表示本轮之前的历史消息。

```json
{
  "id": "msg_...",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "已整理出一条早餐记录草稿，待您确认。"
    }
  ],
  "content_preview": "已整理出一条早餐记录草稿，待您确认。",
  "intent": "fitness_record",
  "requires_review": true,
  "created_at": "2026-05-03T07:22:53.981769"
}
```

当前风险：

- 历史 assistant 回复可能说“待您确认”，但该 pending action 后来可能已经被确认或丢弃。
- 如果没有上下文契约，LLM 可能把旧 assistant 文案当成当前事实。
- 当用户输入“你好”或新话题时，LLM 可能延续上一轮问题，而不是先理解当前输入。

`short_term_messages` 保存最近若干轮完整 `content_json`，用于解决“可以”“好的”“帮我规划一下”这类承接和指代问题。`recent_messages` 继续保留 preview 形态，主要用于低成本调试和兼容。

### 4.7 active_pending_actions

来自 `agent_pending_actions`，只包含当前仍可处理的动作：

```text
needs_clarification
pending_confirmation
```

```json
{
  "pending_action_id": "pa_...",
  "type": "create_meal_record",
  "status": "pending_confirmation",
  "draft_payload": {},
  "warnings": []
}
```

这是“当前仍待用户处理”的权威来源。如果这里为空，就不能因为历史消息里出现“待确认”而认为当前仍有待确认动作。

### 4.8 recent_records

来自正式记录表：

- `meal_records`
- `body_metric_records`

只读取 `deleted_at is null` 的记录，默认各取最近 5 条。

```json
{
  "meals": [
    {
      "id": "meal_...",
      "recorded_at": "2026-05-03T00:00:00",
      "local_date": "2026-05-03",
      "meal_type": "breakfast",
      "total_calories": null,
      "total_protein_g": null
    }
  ],
  "body_metrics": [
    {
      "id": "bm_...",
      "recorded_at": "2026-05-03T08:00:00",
      "local_date": "2026-05-03",
      "weight_kg": 76,
      "body_fat_percentage": null
    }
  ]
}
```

`recent_records` 是已经确认写入后的正式事实，可信度高于 `recent_messages` 和 `conversation_summary`。

当前限制：

- 餐食上下文只带总热量、蛋白质、餐次，不带 `meal_items` 明细。
- 如果用户确认的是一条缺少热量或食物明细的记录，LLM 只能看到 `total_calories=null`，应说明“记录不完整”，不能自行补全。
- 当前未把 `daily_archives` 或 `daily_summaries` 加入对话上下文。

## 5. 上下文压缩机制

压缩触发由 `ConversationSummaryService.enqueue_if_needed` 完成。用户消息链路只创建 `status=pending` 的摘要任务，不同步生成摘要文本；后台 worker 后续把任务更新为 `succeeded`。

当前配置：

```env
CONVERSATION_CONTEXT_RECENT_MESSAGES=8
CONVERSATION_SUMMARY_TRIGGER_MESSAGES=16
CONVERSATION_SUMMARY_MAX_CHARS=2000
```

压缩规则：

1. 查找当前会话最新一条 `conversation_summary`。
2. 取该摘要之后的所有消息。
3. 如果消息数量不超过 `CONVERSATION_SUMMARY_TRIGGER_MESSAGES`，不入队。
4. 如果超过阈值，则保留最近 `CONVERSATION_CONTEXT_RECENT_MESSAGES` 条原始消息。
5. 更早的消息范围写入 `conversation_summaries(status=pending)`。
6. 后台 worker 生成摘要后更新为 `status=succeeded`，后续上下文只读取最新成功摘要。

当前摘要格式：

```text
滚动摘要，用于后续模型上下文；正式事实以档案和记录表为准。
此前摘要: ...
用户: 今天午餐吃了鸡胸肉；需用户确认
助手: 我整理成一条餐食草稿，请确认。
```

关键约束：

- 摘要不会删除原始消息，只是后续构造上下文时不再重复带入旧消息。
- 摘要本身不是正式记录。
- 摘要中出现的食物、体重、待确认状态，都不能直接覆盖正式记录表。

## 6. 待确认动作与已确认内容管理

### 6.1 LLM 输出

LLM 输出经 `ExtractionOutput` schema 校验后，如果包含写入动作，会创建：

- `agent_extractions`
- `agent_pending_actions`

动作类型当前包括：

```text
create_meal_record
create_body_metric_record
```

### 6.2 pending action 生命周期

```text
pending_confirmation / needs_clarification
  -> 用户编辑 update_action
  -> pending_confirmation
  -> 用户确认 confirm_action
  -> committed

pending_confirmation / needs_clarification
  -> 用户丢弃 discard_action
  -> discarded
```

只有以下状态会进入 `active_pending_actions`：

```text
needs_clarification
pending_confirmation
```

`committed` 和 `discarded` 不应继续作为当前待办进入上下文。

### 6.3 确认后写入正式记录

确认 `create_meal_record`：

```text
AgentPendingAction.draft_payload_json
  -> MealCreateRequest
  -> meal_records + meal_items
  -> pending_action.status = committed
  -> pending_action.committed_record_type = meal
  -> pending_action.committed_record_id = meal_id
```

确认 `create_body_metric_record`：

```text
AgentPendingAction.draft_payload_json
  -> BodyMetricCreateRequest
  -> body_metric_records
  -> pending_action.status = committed
  -> pending_action.committed_record_type = body_metric
  -> pending_action.committed_record_id = body_metric_id
```

正式记录会写入 `source_pending_action_id`，用于追溯这条记录来自哪个待确认动作。

### 6.4 下一次对话如何加入已确认内容

下一次发送消息时，`ConversationContextBuilder` 会重新查询数据库：

```text
meal_records
body_metric_records
```

然后把最近记录放入：

```json
{
  "conversation_context": {
    "recent_records": {
      "meals": [],
      "body_metrics": []
    }
  }
}
```

因此，确认后的内容不是通过历史 assistant 回复变成事实，而是通过正式记录表进入下一次上下文。

## 7. 当前暴露出的问题

从测试返回可以看到一个典型问题：

```text
用户当前输入: nihao
模型回复: 我无法判断您今天是否吃得太多...
```

这说明模型被 `recent_messages` 中的历史问题“我今天吃的多吗”带偏了。

根因不是单一字段错误，而是上下文契约不清楚：

1. `message_content` 没有被明确标记为最高优先级。
2. `recent_messages` 没有被明确标记为历史背景，不能代表当前用户意图。
3. `active_pending_actions=[]` 时，模型仍可能从历史 assistant 文案推断“仍有待确认记录”。
4. `recent_records` 是正式事实，但当前 prompt 没有明确它比历史对话更权威。
5. 历史消息重复出现相同问答，会放大模型的延续倾向。

## 8. 建议的上下文权威级别

后续应在 prompt payload 中明确加入 `context_contract`，固定权威顺序：

```text
1. 当前 message_content
2. 正式数据：profile、recent_records
3. 当前仍活跃的 active_pending_actions
4. conversation_summary
5. recent_messages
6. input_normalization 作为当前媒体处理证据
```

解释：

- `message_content` 是本轮任务本身。
- `profile` 与 `recent_records` 是后端正式数据，可信度最高。
- `active_pending_actions` 表示当前仍需要用户处理的草稿。
- `conversation_summary` 和 `recent_messages` 只是帮助理解上下文，不能覆盖正式数据。
- 旧 assistant 文案不能作为 pending action 是否存在的依据。

建议写入 prompt 的契约：

```json
{
  "context_contract": {
    "current_message_priority": "message_content is the user's current request. Do not answer a previous topic unless the current message clearly refers to it.",
    "official_facts": "profile and recent_records are confirmed backend facts.",
    "pending_actions": "Only active_pending_actions represents currently unresolved drafts.",
    "history_role": "recent_messages and conversation_summary are non-authoritative conversation history.",
    "media_rule": "Only use media content when input_normalization status is transcribed or described."
  }
}
```

## 9. 建议的上下文结构 v1.1

建议下一步把 LLM user prompt 调整为：

```json
{
  "current_time": "...",
  "context_contract": {
    "authority_order": [
      "message_content",
      "profile",
      "recent_records",
      "active_pending_actions",
      "conversation_summary",
      "recent_messages"
    ],
    "rules": [
      "当前消息优先于历史消息。",
      "正式记录优先于历史对话文本。",
      "只有 active_pending_actions 表示当前仍待确认。",
      "如果当前消息是问候、无关输入或新问题，不要延续上一轮话题。",
      "不要从 unprocessed 媒体中猜测内容。"
    ]
  },
  "message_content": [],
  "conversation_context": {
    "profile": {},
    "official_recent_records": {},
    "active_pending_actions": [],
    "conversation_summary": {},
    "recent_messages": [],
    "input_normalization": {}
  },
  "output_language": "zh-CN",
  "instruction": "请按 JSON schema 输出结构化提取结果。"
}
```

字段命名建议：

| 当前字段 | 建议 |
| --- | --- |
| `recent_records` | 可保留，也可改为 `official_recent_records` 强化语义 |
| `recent_messages.content` | 建议裁剪或只保留 `content_preview` |
| `conversation_summary.summary_text` | 保留，但继续声明“非正式事实” |
| `active_pending_actions` | 保留，这是 pending 状态的唯一权威来源 |

## 10. 静态测试页展示规则

为了调试清楚，测试页应分开展示：

1. 最近响应
   - `assistant_text`
   - `intent`
   - `requires_review`
   - `pending_actions`
   - `message_id`
   - `request_id`

2. LLM 上下文
   - `debug_context.llm_user_prompt_payload`

3. 原始响应
   - 必要时再看完整 JSON

这样可以避免“业务响应”和“调试上下文”混在一个框里，降低排查成本。

## 11. 当前结论

当前机制已经具备 V1 所需的基本闭环：

```text
消息 -> 多模态归一化 -> 上下文构造 -> LLM 提取 -> 后端规则判定 -> 自动保存/用户确认 -> 正式记录 -> 下一次上下文
```

但上下文语义需要补强。最关键的修正不是增加更多历史，而是让模型明确知道每类上下文的权威级别：

- 已确认记录才是事实
- 当前 pending action 才是待确认事实
- 历史消息只是背景
- 当前用户消息必须优先

在这个规则确定前，不建议继续扩大上下文字段，否则会把“历史误导”问题放大。
