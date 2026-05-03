# LetMeFit V1 实施计划

- 文档状态：V1 开发落地稿
- 版本：0.1
- 更新时间：2026-05-01
- 关联文档：[V1 中文 PRD](prd-v1-zh.md)

## 1. 实施目标

V1 的首要目标是做出一个可验证的端到端健康记录闭环，而不是一次性完成所有健康管理能力。

第一版应优先跑通：

`短信登录 -> 创建档案 -> 记录饮食/身体指标 -> AI 提取 -> 用户确认 -> 每日归档 -> 生成总结与建议`

只要这条链路稳定，后续可以逐步提高识别准确率、个体记忆质量和建议丰富度。

## 2. 总体架构

V1 采用前后端分离架构。客户端规划覆盖 iOS App 与微信小程序，但近期不并行开发两个客户端。项目先完成技术选型、架构设计和后端 API，再优先实现后端，随后选择一个客户端基于 Figma UI 跑通核心闭环。

后端统一负责账号认证、数据读写、AI 编排、规则计算、文件存储和建议生成。首个客户端通过云端后端 API 访问能力，第二客户端在核心闭环稳定后复用同一套 API。

```text
首个客户端
  iOS App 或微信小程序 -> HTTPS REST/JSON API -> 云端后端 -> 数据库
                                                -> 媒体存储适配层
                                                -> AI 服务
                                                -> 短信服务

后续客户端
  复用同一套 API 与核心业务状态机
```

架构原则：

- 客户端不直接访问数据库、模型服务或私有对象存储
- 成本敏感的服务器测试阶段，图片/音频原始文件可保留在客户端本地，后端只保存必要引用和结构化结果
- API 合约、字段命名和业务状态机应为后续第二客户端复用做好准备
- 后端以用户身份为核心隔离档案、记录和建议数据
- AI 输出必须先成为对话中的待确认动作，用户确认或修改后才能写入正式记录
- 短信验证码用于注册/登录，JWT 用于后续 API 认证
- UI 设计以 Figma 为准，客户端实现不得先于核心流程设计大幅发散

## 3. V1 最小闭环

### 3.1 必须完成

- 首个客户端核心闭环，当前为微信小程序，基于 Figma Make 原型实现
- 云端后端服务
- 手机号短信注册/登录
- JWT API 认证
- 用户基础档案创建与编辑
- 今日状态首页
- 餐食拍照记录
- 餐食语音记录
- 体重秤/体脂秤拍照记录
- AI 识别结果确认与字段级编辑
- 按天归档饮食与身体指标
- 每日总结生成
- 1 到 3 条轻量生活方式建议
- 用户纠错记忆的最小存储

### 3.2 延后处理

- Apple Health 或其他设备集成
- 蓝牙硬件直连
- 社区、排行榜、商城
- 教练端后台
- 复杂训练计划
- 独立 RAG 或向量数据库平台
- 复杂跨客户端同步与复杂离线策略
- 第二客户端完整实现

## 4. 核心页面流

### 4.1 Login/Register 登录注册

目标：让用户通过手机号快速进入产品，并建立后续云端档案归属。

关键流程：

- 输入手机号
- 获取短信验证码
- 输入验证码
- 后端校验成功后创建或识别账号
- 后端签发 JWT
- 客户端保存登录态并进入 Onboarding 或 Home

短信验证码必须有有效期、发送频率限制和错误次数限制。

### 4.2 Onboarding

目标：建立可用于推荐和估算的基础档案。

关键字段：

- 年龄
- 性别
- 身高
- 当前体重
- 目标体重
- 活动水平
- 主要目标：减脂、维持或轻量增肌

完成后进入今日首页。

### 4.3 Home 今日首页

目标：回答“我今天的状态如何”。

首屏应展示：

- 今日热量估算
- 今日蛋白质估算
- 最近一次体重/体脂记录
- 今日记录完整度
- 当前最重要的一条建议
- 快速记录入口：拍餐、语音、拍秤

### 4.4 Capture 记录入口

目标：降低记录摩擦。

入口分为三类：

- 餐食照片
- 餐食语音
- 体重秤/体脂秤照片

识别成功后在对话中生成 Review/Edit 确认卡片，不直接保存为正式记录。

### 4.5 对话式 Review/Edit 确认

目标：让用户在对话中快速确认或修正 AI 结果，类似计划模式中的“确认后再执行”。

餐食识别字段：

- 食物名称
- 份量
- 热量估算
- 蛋白质
- 碳水
- 脂肪
- 置信度

身体指标字段：

- 体重
- 体脂率
- BMI
- 肌肉量
- 水分率
- 记录时间
- 置信度

保存前必须允许用户编辑字段，或直接用自然语言补充修正。低置信度字段应更明显地提示确认。只有用户确认后，待确认动作才会写入正式记录表。

### 4.6 Daily Summary 每日总结

目标：把记录转成行动反馈。

每日总结包含：

- 当日摄入总量估算
- 蛋白质与主要营养素概览
- 记录完整度提示
- 近期体重趋势
- 1 到 3 条建议

建议必须短、具体、可执行，并保持非医疗建议边界。

## 5. 数据模型草案

### 5.1 AuthUser

```text
id
phone_number
phone_verified
status
last_login_at
created_at
updated_at
```

### 5.2 SmsVerification

```text
id
phone_number
code_hash
purpose: login | register
expires_at
attempt_count
sent_at
verified_at
created_at
```

### 5.3 AuthSession

```text
id
user_id
refresh_token_hash
expires_at
revoked_at
created_at
updated_at
```

### 5.4 UserProfile

```text
id
user_id
age
sex
height_cm
current_weight_kg
target_weight_kg
activity_level
goal_type
created_at
updated_at
```

### 5.5 MealRecord

```text
id
user_id
recorded_at
source_type: photo | voice | manual
meal_type: breakfast | lunch | dinner | snack | unknown
items[]
total_calories
total_protein_g
total_carbs_g
total_fat_g
confidence
raw_input_ref
created_at
updated_at
```

### 5.6 MealItem

```text
id
meal_record_id
name
alias
portion_text
portion_grams
calories
protein_g
carbs_g
fat_g
confidence
user_corrected
```

### 5.7 BodyMetricRecord

```text
id
user_id
recorded_at
source_type: scale_photo | manual
weight_kg
body_fat_percentage
bmi
muscle_mass_kg
water_percentage
confidence
raw_input_ref
created_at
updated_at
```

### 5.8 DailyArchive

```text
id
user_id
date
meal_record_ids[]
body_metric_record_ids[]
calorie_total
protein_total_g
carbs_total_g
fat_total_g
summary_text
suggestions[]
completeness_score
created_at
updated_at
```

### 5.9 UserMemory

```text
id
user_id
memory_type: food_alias | portion_preference | scale_correction | phrase_mapping
key
value
confidence
last_seen_at
created_at
updated_at
```

### 5.10 AgentPendingAction

```text
id
user_id
conversation_id
source_message_id
extraction_id
action_type: create_meal_record | create_body_metric_record | generate_daily_summary
status: needs_clarification | pending_confirmation | confirmed | discarded | committed | expired
draft_payload_json
warnings_json
confidence
confirmed_at
committed_record_type
committed_record_id
created_at
updated_at
```

### 5.11 ConversationSummary

```text
id
conversation_id
user_id
from_message_id
to_message_id
summary_text
token_estimate
created_at
```

## 6. API 与认证边界

### 6.1 认证方式

V1 使用手机号短信验证码完成注册/登录。登录成功后，后端返回访问令牌和刷新令牌。

建议策略：

- access token 使用 JWT，生命周期较短
- refresh token 使用服务端可撤销会话记录，生命周期较长
- 客户端请求业务 API 时通过 `Authorization: Bearer <token>` 携带 access token
- access token 过期后，客户端通过 refresh token 换取新的 access token
- 用户退出登录时，后端撤销对应 refresh token

### 6.2 API 分组

V1 后端 API 可以先按以下分组设计：

```text
/auth/sms/send
/auth/sms/verify
/auth/refresh
/auth/logout

/profile
/meals
/body-metrics
/daily-archives
/summaries
/suggestions

/conversations
/conversations/{conversation_id}/messages
/agent/extractions
/agent/pending-actions/{pending_action_id}
/agent/pending-actions/{pending_action_id}/confirm
/agent/pending-actions/{pending_action_id}/discard
```

除短信发送、短信校验和刷新登录态外，业务接口都需要 JWT。

### 6.3 客户端兼容约束

虽然后续只先实现一个客户端，但 API 设计应避免绑定某个特定客户端。iOS App 与微信小程序后续应共享：

- API 路径与响应结构
- 错误码
- 登录态刷新规则
- AI 识别结果状态
- 对话式 Review/Edit 确认卡片字段定义

## 7. Agent 与 AI 能力切分

### 7.1 通用对话入口

V1 交互形式应保持通用：用户可以用文字、图片、拍照图片和语音与 Agent 交流。能力边界则保持收敛：只处理健身管理、饮食记录、身体指标记录、每日总结和一般生活方式建议。

输入类型：

- 文本
- 图片
- 拍照图片
- 音频

输出类型：

- Agent 自然语言回复
- 结构化候选动作
- 对话式 Review/Edit 确认卡片所需字段
- 超出能力边界的拒答或引导

### 7.2 意图识别与路由

V1 只支持以下意图：

- `create_meal_record`
- `create_body_metric_record`
- `generate_daily_summary`
- `answer_fitness_question`
- `out_of_scope`

不再按 `meal-photo`、`meal-voice`、`scale-photo` 设计外部 API。外部 API 只表达“对话消息”和“结构化提取”，具体识别任务由后端 Agent 路由完成。

### 7.3 多模态处理链路

推荐流程：

`用户消息 -> 媒体引用或临时上传 -> 语音转写/图片理解 -> 意图识别 -> 待确认动作 -> 用户确认/修改 -> 正式保存`

语音处理：

- 先转写为文本
- 再与同条消息中的图片和文本一起交给 Agent 理解
- 原始音频只作为输入附件和审计上下文，不直接进入正式记录。成本敏感测试阶段可只保留在客户端本地，后端保存客户端本地引用和识别后的结构化结果。

图片处理：

- 餐食图片用于识别食物候选、份量、营养估算
- 秤照片用于识别体重、体脂率等数字字段
- 其他图片如与健身管理无关，应返回 `out_of_scope`

### 7.4 建议生成

建议生成不能只依赖大模型自由发挥，应先由规则层生成事实和边界，再由 LLM 组织自然语言。

推荐流程：

`结构化记录 -> 营养与趋势计算 -> 安全规则检查 -> 候选建议 -> LLM 表达 -> 输出`

## 8. 安全边界

V1 必须内置以下规则：

- 不输出医疗诊断或治疗建议
- 不支持孕期、未成年人、疾病饮食管理等场景
- 不建议极端热量限制
- 不用确定口吻判断健康风险
- 数据不足或置信度低时，优先提醒用户确认
- 所有建议都应允许用户忽略、修改记录或重新生成
- 所有用户私有数据接口必须校验 JWT
- 短信验证码必须限制频率、有效期和错误次数
- 客户端不得直接访问数据库、私有对象存储或模型服务

## 9. 技术路线建议

### 9.1 推荐开发顺序

1. 完成技术选型、架构设计和项目 `AGENTS.md`
2. 完成后端 API 文档
3. 搭建云端后端基础工程、数据库、短信服务和 JWT 认证
4. 基于 Figma 确认首个客户端 UI 与核心页面流
5. 实现微信小程序客户端
6. 接入最小 AI 提取链路
7. 跑通端到端记录闭环
8. 再优化识别质量、记忆和总结体验

### 9.2 初始模块

建议后续仓库结构：

```text
docs/
ios/
miniprogram/
backend/
infra/
scripts/
```

后端初始模块：

```text
backend/
  app/
    api/
    auth/
    models/
    services/
    ai/
    rules/
    storage/
    sms/
  tests/
```

iOS 初始模块：

```text
ios/
  LetMeFit/
    Features/
      Onboarding/
      Home/
      Capture/
      Review/
      Summary/
    Core/
      API/
      Models/
      DesignSystem/
```

微信小程序初始模块：

```text
miniprogram/
  pages/
    login/
    onboarding/
    home/
    records/
    chat/
    summary/
    profile/
  components/
  services/
  types/
  utils/
```

部署初始模块：

```text
infra/
  cloud/
  database/
  object-storage/
  env/
```

## 10. 里程碑

### M1：技术选型与架构设计

交付物：

- 技术选型文档
- 前后端分离架构说明
- 登录注册与 JWT 认证方案
- 项目 `AGENTS.md`
- V1 页面流
- 数据模型
- AI 输入输出格式
- 安全规则清单

完成标准：

- 可以明确后端、AI、客户端、部署的技术边界
- 可以判断每个功能是否属于 V1

### M2：后端 API 文档

交付物：

- 认证 API
- 用户档案 API
- 餐食记录 API
- 身体指标 API
- 每日归档与总结 API
- AI 提取 API
- 错误码与认证规范

完成标准：

- 后端可以按 API 文档实现
- 客户端可以基于 API 文档准备联调

### M3：云端后端基础闭环

交付物：

- 云端后端工程
- 短信验证码发送与校验
- JWT 签发、刷新与校验
- 用户档案 API
- 基础数据库迁移

完成标准：

- 客户端可通过手机号登录并调用受保护 API
- 用户数据按账号隔离

### M4：首个客户端核心闭环

交付物：

- 基于 Figma 的首个客户端 UI
- 登录注册
- 用户档案
- 餐食记录
- 身体指标记录
- 对话式 Review/Edit 确认卡片
- 每日归档与总结

完成标准：

- 首个客户端可以通过真实后端完成登录、记录、确认、归档和查看总结
- 不依赖真实 AI，也能通过模拟 AI 输出走通记录到总结

### M5：AI 提取接入

交付物：

- 餐食图片识别
- 语音转结构化餐食
- 秤照片数字识别
- 置信度与确认页联动

完成标准：

- AI 输出永远先进入确认页
- 用户修改后保存的是修正结果

### M6：第二客户端评估与启动

交付物：

- 首个客户端验证结果
- 第二客户端启动条件
- API 兼容性复盘
- Figma 适配说明

完成标准：

- 明确是否启动第二客户端
- 如启动，第二客户端复用统一 API 与核心业务状态机

### M7：用户记忆与建议优化

交付物：

- 常见食物别名记忆
- 常见份量偏好记忆
- 重复纠错记忆
- 更稳定的每日建议

完成标准：

- 重复记录的餐食能逐步减少修正成本
- 建议不会越过健康生活方式边界

## 11. 近期待办

建议下一批文档或任务按这个顺序推进：

1. 完成技术选型与架构设计
2. 编制项目 `AGENTS.md`
3. 输出账号注册/登录与 JWT 认证方案
4. 输出后端 API 文档
5. 输出 AI JSON Schema 草案
6. 实现后端工程骨架与核心 API
7. 基于 Figma 完成首个客户端 UI 设计确认
8. 实现微信小程序客户端
9. 第二客户端在核心闭环稳定后再评估启动

## 12. 当前优先级判断

最优先的是定义可开发边界，而不是立即优化 AI 效果。

原因：

- 识别模型可以替换，但确认、修正、归档和总结闭环是产品骨架
- 前后端分离、短信登录和 JWT 会影响所有客户端与后端 API，应尽早冻结
- iOS App 与微信小程序不应并行开工，先用一个客户端验证核心闭环
- V1 的关键假设是“用户愿意用拍照/语音持续记录”，需要尽快用原型验证
- 用户纠错记忆只有在真实记录流程跑通后才有价值

因此，下一步应优先完成技术选型、架构设计、项目 `AGENTS.md`、后端 API 文档和后端实现。
