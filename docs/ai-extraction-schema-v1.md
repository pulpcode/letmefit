# LetMeFit V1 AI Extraction Schema

## Purpose

LLM output is only used to create backend-validated candidate record actions. It must not write formal records directly.

The backend stores LLM output in `agent_extractions`, then applies backend commit rules. Clear low-risk actions may be committed automatically; ambiguous or low-confidence actions become `agent_pending_actions` and require user confirmation.

## Provider

V1 uses a replaceable provider adapter.

Current supported providers:

- `mock`: deterministic local provider for development and tests
- `bailian`: Alibaba Cloud Bailian / DashScope OpenAI-compatible Chat Completions

Bailian default endpoint:

```text
https://dashscope.aliyuncs.com/compatible-mode/v1
```

Bailian JSON Mode uses:

```json
{
  "response_format": {
    "type": "json_object"
  }
}
```

The prompt must contain the word `JSON`, otherwise JSON Mode may be rejected by the provider.

Backend validation:

- The provider must parse the model response with `json.loads`.
- The parsed object must pass the backend Pydantic `ExtractionOutput` schema.
- If JSON parsing or schema validation fails, the provider may issue one repair request.
- Invalid model output must not create `agent_extractions`, `agent_pending_actions`, or formal records.
- If `conversation_context.input_normalization.media[].status` is `unprocessed`, the provider must not infer media contents from the file reference alone.

## Top-Level Output

The model must return one JSON object:

```json
{
  "assistant_text": "我整理出一条待确认记录，请确认或修改后再保存。",
  "intent": "fitness_record",
  "requires_review": true,
  "confidence": 0.82,
  "warnings": [],
  "dialogue_state_patch": null,
  "pending_actions": []
}
```

Fields:

- `assistant_text`: user-facing response text
- `intent`: one of `fitness_record`, `answer_fitness_question`, `out_of_scope`
- `requires_review`: model-side hint; backend makes the final confirmation decision
- `confidence`: 0-1 model confidence
- `warnings`: low-confidence or missing-field warnings
- `dialogue_state_patch`: optional one-turn dialogue-state hint; does not write formal facts
- `pending_actions`: candidate write actions; backend may auto-commit clear actions or create pending actions

## Dialogue State Patch

When the assistant response creates a proposal that the next user turn may accept or continue, the model may return:

```json
{
  "dialogue_state_patch": {
    "new_active_offer": {
      "kind": "assistant_offer",
      "surface_text": "需要我帮您规划一份适合的晚餐方案吗？",
      "referent": {
        "topic": "晚餐方案",
        "user_goal": "基于今日记录和减脂目标安排晚餐",
        "expected_followup": "用户同意时直接生成晚餐方案"
      }
    }
  }
}
```

Rules:

- `new_active_offer.kind` must be `assistant_offer`.
- `surface_text` must come from the current `assistant_text`.
- `referent` may only describe `topic`, `user_goal`, and `expected_followup`.
- It must not contain profile, records, pending actions, draft payloads, or formal facts.
- The backend treats it as a one-user-turn token and clears it after the next user message.

## Pending Action Types

Supported V1 action types:

```text
create_meal_record
create_body_metric_record
```

Planned but not yet committed through LLM:

```text
generate_daily_summary
```

## Meal Record Draft

```json
{
  "type": "create_meal_record",
  "confidence": 0.78,
  "draft_payload": {
    "recorded_at": "2026-05-01T12:30:00+08:00",
    "source_type": "text",
    "meal_type": "lunch",
    "items": [
      {
        "name": "鸡胸肉",
        "portion_text": "约120g",
        "portion_grams": 120,
        "calories": 198,
        "protein_g": 37,
        "carbs_g": 0,
        "fat_g": 4,
        "confidence": 0.86,
        "user_corrected": false
      }
    ],
    "confidence": 0.78
  },
  "warnings": []
}
```

Allowed values:

- `source_type`: `photo`, `voice`, `text`, `manual`, `mixed`
- `meal_type`: `breakfast`, `lunch`, `dinner`, `snack`, `unknown`

Rules:

- Do not invent nutrition values if they are not present or reasonably inferable.
- Use warnings for uncertain food names, portions, calories, or macros.
- If the meal exists but key fields are uncertain, still create a pending action with warnings.

## Body Metric Draft

```json
{
  "type": "create_body_metric_record",
  "confidence": 0.82,
  "draft_payload": {
    "recorded_at": "2026-05-01T08:10:00+08:00",
    "source_type": "text",
    "weight_kg": 72.4,
    "body_fat_percentage": 18.6,
    "bmi": 23.1,
    "confidence": 0.82
  },
  "warnings": []
}
```

Allowed values:

- `source_type`: `scale_photo`, `voice`, `text`, `manual`

Rules:

- Convert Chinese jin to kg when explicit, e.g. `144斤` -> `72kg`.
- Do not infer missing body fat, BMI, muscle mass, or water percentage.
- Missing optional fields should be omitted, not set to fake values.

## Safety

The model must return `out_of_scope` with no pending actions for:

- medical diagnosis
- treatment advice
- medication advice
- disease diet management
- pregnancy, minors, or other high-risk scenarios
- extreme calorie restriction

Example:

```json
{
  "assistant_text": "这个问题可能涉及医疗诊断或治疗建议，我不能替你判断。可以聊聊一般健身记录、饮食习惯和训练安排。",
  "intent": "out_of_scope",
  "requires_review": false,
  "confidence": 0.9,
  "warnings": [],
  "pending_actions": []
}
```
