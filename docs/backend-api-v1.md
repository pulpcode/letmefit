# LetMeFit V1 后端 API 文档

- 文档状态：V1 API 初稿
- 版本：0.1
- 更新时间：2026-05-01
- 认证方式：JWT Bearer Token

## 1. 基础约定

### 1.1 Base URL

```text
https://api.letmefit.example.com/v1
```

本地开发：

```text
http://localhost:8000/v1
```

### 1.2 认证头

除短信发送、短信校验、刷新登录态和健康检查外，业务 API 都需要：

```http
Authorization: Bearer <access_token>
```

### 1.3 响应结构

成功响应：

```json
{
  "data": {},
  "request_id": "req_..."
}
```

错误响应：

```json
{
  "error": {
    "code": "AUTH_INVALID_TOKEN",
    "message": "登录状态已失效",
    "details": {}
  },
  "request_id": "req_..."
}
```

## 2. 错误码

```text
AUTH_SMS_RATE_LIMITED
AUTH_SMS_INVALID_CODE
AUTH_SMS_EXPIRED_CODE
AUTH_REQUIRED
AUTH_INVALID_TOKEN
AUTH_EXPIRED_TOKEN
AUTH_FORBIDDEN
VALIDATION_ERROR
RESOURCE_NOT_FOUND
AI_EXTRACTION_FAILED
AI_LOW_CONFIDENCE
INTERNAL_ERROR
```

## 3. 健康检查

### GET /health

返回服务状态。

```json
{
  "data": {
    "status": "ok"
  },
  "request_id": "req_..."
}
```

## 4. 认证 API

短信验证码服务基于阿里云号码认证服务 Dypnsapi：

- 发送验证码：`SendSmsVerifyCode`
- 校验验证码：`CheckSmsVerifyCode`
- 发送时 `TemplateParam` 使用 `{"code":"##code##","min":"5"}`，验证码由阿里云生成
- 生产环境 `ReturnVerifyCode=false`
- 后端只有在校验接口返回 `Code=OK`、`Success=true` 且 `Model.VerifyResult=PASS` 时，才签发 JWT

### POST /auth/sms/send

发送短信验证码。

请求：

```json
{
  "phone_number": "+8613800000000",
  "purpose": "login"
}
```

响应：

```json
{
  "data": {
    "cooldown_seconds": 60,
    "expires_in_seconds": 300
  },
  "request_id": "req_..."
}
```

后端调用阿里云发送接口时的默认参数：

```text
CountryCode=86
CodeType=1
CodeLength=6
ValidTime=300
Interval=60
DuplicatePolicy=1
TemplateParam={"code":"##code##","min":"5"}
ReturnVerifyCode=false
```

### POST /auth/sms/verify

校验验证码并登录。首次登录自动创建用户。

请求：

```json
{
  "phone_number": "+8613800000000",
  "code": "123456"
}
```

后端会调用阿里云 `CheckSmsVerifyCode`，传入同一 `PhoneNumber`、`CountryCode`、`SchemeName` 和用户输入的 `VerifyCode`。

响应：

```json
{
  "data": {
    "access_token": "jwt...",
    "refresh_token": "rt_...",
    "token_type": "bearer",
    "expires_in_seconds": 1800,
    "user": {
      "id": "user_...",
      "phone_number": "+8613800000000",
      "profile_completed": false
    }
  },
  "request_id": "req_..."
}
```

### POST /auth/refresh

刷新 access token。

请求：

```json
{
  "refresh_token": "rt_..."
}
```

响应：

```json
{
  "data": {
    "access_token": "jwt...",
    "expires_in_seconds": 1800
  },
  "request_id": "req_..."
}
```

### POST /auth/logout

退出登录并撤销 refresh session。

请求：

```json
{
  "refresh_token": "rt_..."
}
```

响应：

```json
{
  "data": {
    "success": true
  },
  "request_id": "req_..."
}
```

## 5. 用户档案 API

### GET /profile

获取当前用户档案。

响应：

```json
{
  "data": {
    "profile": null,
    "profile_completed": false
  },
  "request_id": "req_..."
}
```

已有档案时：

```json
{
  "data": {
    "profile": {
      "id": "profile_...",
      "age": 30,
      "sex": "male",
      "height_cm": 175,
      "current_weight_kg": 72.4,
      "target_weight_kg": 68,
      "activity_level": "moderate",
      "goal_type": "fat_loss",
      "completed_at": "2026-05-01T10:00:00"
    },
    "profile_completed": true
  },
  "request_id": "req_..."
}
```

### PUT /profile

创建或更新当前用户档案。

请求：

```json
{
  "age": 30,
  "sex": "male",
  "height_cm": 175,
  "current_weight_kg": 72.4,
  "target_weight_kg": 68,
  "activity_level": "moderate",
  "goal_type": "fat_loss"
}
```

字段约束：

- `age`：18-100
- `sex`：`male`、`female`、`other`、`unspecified`
- `height_cm`：80-250
- `current_weight_kg`、`target_weight_kg`：25-300
- `activity_level`：`sedentary`、`light`、`moderate`、`active`、`very_active`
- `goal_type`：`fat_loss`、`muscle_gain`、`maintenance`、`fitness`

当 `age`、`sex`、`height_cm`、`current_weight_kg`、`activity_level`、`goal_type` 均存在时，后端将档案标记为已完成；`target_weight_kg` 可为空。

响应同 `GET /profile`。

## 6. 餐食记录 API

### GET /meals

查询餐食记录。

查询参数：

```text
date=2026-05-01
```

响应：

```json
{
  "data": {
    "meals": [
      {
        "id": "meal_...",
        "recorded_at": "2026-05-01T04:30:00",
        "recorded_tz": "Asia/Shanghai",
        "local_date": "2026-05-01",
        "source_type": "manual",
        "meal_type": "lunch",
        "total_calories": 198,
        "total_protein_g": 37,
        "total_carbs_g": 0,
        "total_fat_g": 4,
        "confidence": 0.9,
        "source_pending_action_id": null,
        "notes": null,
        "items": [
          {
            "id": "mi_...",
            "name": "鸡胸肉",
            "alias": null,
            "portion_text": "约120g",
            "portion_grams": 120,
            "calories": 198,
            "protein_g": 37,
            "carbs_g": 0,
            "fat_g": 4,
            "confidence": 0.9,
            "user_corrected": false
          }
        ]
      }
    ]
  },
  "request_id": "req_..."
}
```

### POST /meals

保存已确认的餐食记录。

请求：

```json
{
  "recorded_at": "2026-05-01T12:30:00+08:00",
  "source_type": "photo",
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
  ]
}
```

字段约束：

- `recorded_at`：支持带时区 ISO8601；后端按 UTC 存储，并根据 `recorded_tz` 计算 `local_date`
- `recorded_tz`：可选，默认 `Asia/Shanghai`
- `source_type`：`photo`、`voice`、`text`、`manual`、`mixed`
- `meal_type`：`breakfast`、`lunch`、`dinner`、`snack`、`unknown`
- `items`：1-50 项
- 营养值与置信度允许为空；总营养值由后端根据明细求和

响应同单条餐食记录结构。

### GET /meals/{meal_id}

获取单条餐食记录。

只能获取当前登录用户自己的未删除记录；不存在或不属于当前用户时返回 `RESOURCE_NOT_FOUND`。

### PATCH /meals/{meal_id}

修改餐食记录。

请求字段同 `POST /meals`，全部可选；如果传入 `items`，后端会整体替换餐食明细并重新计算总营养值。

### DELETE /meals/{meal_id}

删除餐食记录。

软删除当前登录用户自己的餐食记录。

响应：

```json
{
  "data": {
    "success": true
  },
  "request_id": "req_..."
}
```

## 7. 身体指标 API

### GET /body-metrics

查询身体指标记录。

查询参数：

```text
date_from=2026-04-01
date_to=2026-05-01
```

响应：

```json
{
  "data": {
    "body_metrics": [
      {
        "id": "bm_...",
        "recorded_at": "2026-05-01T00:10:00",
        "recorded_tz": "Asia/Shanghai",
        "local_date": "2026-05-01",
        "source_type": "manual",
        "weight_kg": 72.4,
        "body_fat_percentage": 18.6,
        "bmi": 23.1,
        "muscle_mass_kg": null,
        "water_percentage": null,
        "confidence": 0.8,
        "source_pending_action_id": null
      }
    ]
  },
  "request_id": "req_..."
}
```

### POST /body-metrics

保存已确认的身体指标记录。

请求：

```json
{
  "recorded_at": "2026-05-01T08:10:00+08:00",
  "source_type": "scale_photo",
  "weight_kg": 72.4,
  "body_fat_percentage": 18.6,
  "bmi": 23.1,
  "confidence": 0.82
}
```

字段约束：

- `recorded_at`：支持带时区 ISO8601；后端按 UTC 存储，并根据 `recorded_tz` 计算 `local_date`
- `recorded_tz`：可选，默认 `Asia/Shanghai`
- `source_type`：`scale_photo`、`voice`、`text`、`manual`
- `weight_kg`：25-300
- `body_fat_percentage`：1-80
- `bmi`：10-80
- `muscle_mass_kg`：1-200
- `water_percentage`：1-90
- `confidence`：0-1

### GET /body-metrics/{body_metric_id}

获取单条身体指标记录。只能获取当前登录用户自己的未删除记录。

### PATCH /body-metrics/{body_metric_id}

修改身体指标记录。请求字段同 `POST /body-metrics`，全部可选。

### DELETE /body-metrics/{body_metric_id}

软删除当前登录用户自己的身体指标记录。

响应：

```json
{
  "data": {
    "success": true
  },
  "request_id": "req_..."
}
```

## 8. 每日归档与总结 API

### GET /daily-archives/{date}

获取某天的归档数据。

### POST /summaries/generate

生成或刷新每日总结。

请求：

```json
{
  "date": "2026-05-01"
}
```

响应：

```json
{
  "data": {
    "date": "2026-05-01",
    "calorie_total": 1620,
    "protein_total_g": 96,
    "summary_text": "今天记录较完整，蛋白质摄入不错。",
    "suggestions": [
      "晚餐可以优先选择高蛋白、低油烹饪方式。",
      "如果还觉得饿，优先补充蔬菜或无糖酸奶。"
    ],
    "completeness_score": 0.8
  },
  "request_id": "req_..."
}
```

## 9. Agent 对话与 AI 提取 API

V1 的交互形式是通用 Agent 对话。用户可以发送文本、图片、拍照图片或语音，后端只在健身管理边界内处理能力。

Agent 接口可以返回自然语言回复，也可以返回结构化待确认动作。只要动作会产生餐食、身体指标、每日总结等实质业务记录，后端必须先生成 `pending_action`，由客户端在对话中展示确认卡片。用户确认或修改后，后端才写入正式记录。

### POST /conversations

创建会话。

请求：

```json
{
  "title": "今天记录"
}
```

响应：

```json
{
  "data": {
    "conversation_id": "conv_...",
    "conversation": {
      "id": "conv_...",
      "title": "今天记录",
      "status": "active",
      "created_at": "2026-05-01T12:00:00",
      "updated_at": "2026-05-01T12:00:00"
    }
  },
  "request_id": "req_..."
}
```

### GET /conversations

查询当前用户的会话列表。

响应：

```json
{
  "data": {
    "conversations": [
      {
        "id": "conv_...",
        "title": "今天记录",
        "status": "active",
        "created_at": "2026-05-01T12:00:00",
        "updated_at": "2026-05-01T12:00:00"
      }
    ]
  },
  "request_id": "req_..."
}
```

### POST /conversations/{conversation_id}/messages

发送一条用户消息。

图片和音频 part 必须引用已创建且属于当前用户的 `file_id`；后端会写入 `message_attachments`。成本敏感测试阶段，`file_id` 可以来自 `client_local` 上传记录。

请求：

```json
{
  "content": [
    {
      "type": "text",
      "text": "这是我今天的午餐，帮我记录一下"
    },
    {
      "type": "image",
      "file_id": "file_...",
      "source": "camera"
    },
    {
      "type": "audio",
      "file_id": "file_...",
      "duration_seconds": 8
    }
  ]
}
```

响应：

```json
{
  "data": {
    "message_id": "msg_...",
    "assistant_message_id": "msg_...",
    "assistant_text": "我识别到这可能是一份午餐记录，请确认下面的食物和份量。",
    "intent": "fitness_record",
    "requires_review": true,
    "pending_actions": [
      {
        "pending_action_id": "pa_...",
        "type": "create_meal_record",
        "status": "pending_confirmation",
        "confidence": 0.78,
        "draft_payload": {
          "meal_type": "lunch",
          "items": []
        },
        "warnings": [
          {
            "field": "portion_grams",
            "reason": "low_confidence"
          }
        ]
      }
    ]
  },
  "request_id": "req_..."
}
```

V1 当前实现先使用 mock extraction 打通确认闭环；真实 LLM、ASR 和图片理解模型后续通过 adapter 替换。

### GET /conversations/{conversation_id}/messages

查询会话消息。只能查询当前登录用户自己的会话。

响应：

```json
{
  "data": {
    "messages": [
      {
        "id": "msg_...",
        "conversation_id": "conv_...",
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "今天午餐吃了鸡胸肉"
          }
        ],
        "intent": "fitness_record",
        "requires_review": true,
        "created_at": "2026-05-01T12:00:00"
      }
    ]
  },
  "request_id": "req_..."
}
```

### GET /conversations/{conversation_id}/pending-actions

查询某个会话下的待确认动作，包括已提交或已放弃动作，客户端可用它恢复 Review/Edit 卡片状态。

响应：

```json
{
  "data": {
    "pending_actions": [
      {
        "pending_action_id": "pa_...",
        "type": "create_meal_record",
        "status": "pending_confirmation",
        "confidence": 0.78,
        "draft_payload": {},
        "warnings": [],
        "created_at": "2026-05-01T12:00:00",
        "updated_at": "2026-05-01T12:00:00"
      }
    ]
  },
  "request_id": "req_..."
}
```

### POST /agent/extractions

对文本、图片、音频进行一次性结构化提取。该接口主要供对话接口内部调用；如果外部直接调用，也只生成待确认动作，不直接写入正式记录。

V1 第一阶段可先不开放该接口；对外主入口是 `POST /conversations/{conversation_id}/messages`。

通用响应：

```json
{
  "data": {
    "extraction_id": "ext_...",
    "input_types": ["text", "image"],
    "intent": "fitness_record",
    "confidence": 0.78,
    "requires_confirmation": true,
    "pending_actions": [],
    "warnings": [
      {
        "field": "portion_grams",
        "reason": "low_confidence"
      }
    ]
  },
  "request_id": "req_..."
}
```

V1 支持的待确认动作类型：

```text
create_meal_record
create_body_metric_record
generate_daily_summary
answer_fitness_question
out_of_scope
```

`out_of_scope` 用于医疗诊断、疾病管理、无关闲聊或无法安全处理的请求。

### PATCH /agent/pending-actions/{pending_action_id}

修改待确认动作的草稿字段。客户端结构化编辑和用户自然语言修正后，都可以收敛到该接口。

请求：

```json
{
  "draft_payload": {},
  "user_note": "鸡胸肉不是120g，是180g"
}
```

响应：

```json
{
  "data": {
    "pending_action_id": "pa_...",
    "type": "create_meal_record",
    "status": "pending_confirmation",
    "confidence": 0.78,
    "draft_payload": {},
    "warnings": []
  },
  "request_id": "req_..."
}
```

### POST /agent/pending-actions/{pending_action_id}/confirm

确认待执行动作并写入正式记录。

当前支持：

- `create_meal_record`：写入 `meal_records` / `meal_items`
- `create_body_metric_record`：写入 `body_metric_records`

确认成功后，`agent_pending_actions.status` 更新为 `committed`，并写入 `committed_record_type` 和 `committed_record_id`。正式记录会写入 `source_pending_action_id`，用于从记录反查来源确认动作。

响应：

```json
{
  "data": {
    "pending_action_id": "pa_...",
    "status": "committed",
    "record_type": "meal",
    "record_id": "meal_..."
  },
  "request_id": "req_..."
}
```

### POST /agent/pending-actions/{pending_action_id}/discard

放弃待确认动作。

响应：

```json
{
  "data": {
    "pending_action_id": "pa_...",
    "status": "discarded"
  },
  "request_id": "req_..."
}
```

## 10. 文件上传与媒体引用

V1 后端支持多种媒体策略：

- 本地开发：服务端本地文件存储
- 成本敏感的服务器测试：App 保留图片/音频原始文件在本地，后端只保存 `client_local_ref`、元数据和结构化结果；需要重新识别时由 App 再次临时上传
- 公开测试/生产：腾讯云 COS、阿里云 OSS 或其他 S3 兼容对象存储

### POST /uploads

创建上传记录或返回预签名上传信息。

V1 第一阶段先支持 `client_local` 上传记录：原始图片/音频保留在 App 本地，后端保存 `client_local_ref`、媒体类型和结构化引用。对象存储预签名上传后续再接入。

请求：

```json
{
  "storage_provider": "client_local",
  "client_local_ref": "local://camera/2026-05-01/abc.jpg",
  "mime_type": "image/jpeg",
  "size_bytes": 345678,
  "source": "camera",
  "retention_policy": "transient"
}
```

字段约束：

- `storage_provider`：`client_local`、`local_server`、`cos`、`oss`、`s3`
- `client_local` 必须提供 `client_local_ref`
- `source`：`camera`、`album`、`microphone`、`upload`
- `retention_policy`：`transient`、`retained`

响应：

```json
{
  "data": {
    "file": {
      "id": "file_...",
      "storage_provider": "client_local",
      "client_local_ref": "local://camera/2026-05-01/abc.jpg",
      "bucket": null,
      "object_key": null,
      "mime_type": "image/jpeg",
      "size_bytes": 345678,
      "source": "camera",
      "retention_policy": "transient",
      "status": "local_only",
      "created_at": "2026-05-01T12:00:00",
      "deleted_at": null
    },
    "upload_url": null,
    "upload_headers": {}
  },
  "request_id": "req_..."
}
```

### GET /uploads/{file_id}

获取当前用户自己的上传记录。

### DELETE /uploads/{file_id}

软删除当前用户自己的上传记录。已生成的正式结构化记录不依赖原始媒体继续存在。

响应：

```json
{
  "data": {
    "success": true
  },
  "request_id": "req_..."
}
```

## 11. 后续补充

- 分页规范
- 排序规范
- OpenAPI schema 导出流程
- AI JSON Schema
- Agent 消息 schema
- 文件上传大小限制
- 客户端错误提示映射
