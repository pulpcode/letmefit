# LetMeFit V1 技术选型与架构设计

- 文档状态：V1 技术方案初稿
- 版本：0.1
- 更新时间：2026-05-01
- 关联文档：[V1 实施计划](v1-implementation-plan.md)

## 1. 决策摘要

V1 采用前后端分离架构，后端优先实现，客户端先实现一个。

当前推荐选型：

```text
后端：Python + FastAPI
数据库：MySQL 8.4 LTS
ORM 与迁移：SQLAlchemy + Alembic
MySQL 驱动：PyMySQL
缓存与限流：Redis
认证：手机号短信验证码 + JWT access token + 服务端 refresh session
短信：阿里云号码认证服务 Dypnsapi
部署：腾讯云 4 核 4G 云服务器；后端用 uv + systemd 运行，MySQL/Redis 用 Docker Compose，Nginx 可选
媒体存储：本地开发/测试可使用客户端本地或服务端本地存储，生产建议 S3 兼容对象存储
API 文档：OpenAPI 自动文档 + docs/backend-api-v1.md
首个客户端：微信小程序，基于 Figma Make 原型实现
Agent 框架：V1 自研轻量编排，暂不引入 LangChain/LangGraph/Deep Agents
```

## 2. 开发顺序

1. 完成技术选型与架构设计
2. 编制项目 `AGENTS.md`
3. 完成后端 API 文档
4. 实现后端核心 API
5. 基于 Figma 确认首个客户端 UI
6. 实现微信小程序客户端
7. 接入真实 AI 能力
8. 评估是否启动第二客户端

## 3. 总体架构

```text
首个客户端
  微信小程序
        |
        | HTTPS REST/JSON
        v
云服务器
  可选反向代理 Nginx
    -> FastAPI 后端
         -> MySQL
         -> Redis
         -> 媒体存储适配层
         -> 阿里云短信验证码服务
         -> AI 服务
```

后端是唯一可信业务入口。客户端不直接访问数据库、私有对象存储、短信服务或 AI 模型服务。成本敏感的服务器测试阶段，图片/音频原始文件可以只保留在客户端本地，后端保存客户端本地引用、必要元数据和结构化结果；需要 AI 识别时由客户端临时上传或发送待处理文件。

## 4. 后端选型

### 4.1 FastAPI

选择原因：

- 适合 REST/JSON API
- 基于类型标注，便于维护请求和响应模型
- 自动生成 OpenAPI 文档，方便客户端联调
- 适合逐步拆分 `auth`、`profile`、`record`、`ai`、`summary` 等模块
- Python 生态更贴近 AI 编排、图片/语音处理、营养计算和规则实验
- V1 团队可以用一套语言同时完成 API、AI 适配、规则引擎和数据处理

### 4.2 为什么 V1 不采用 Python + Java 双后端

V1 暂不引入 Java 服务。当前阶段的主要任务是验证“低摩擦记录 -> AI 提取 -> 用户确认 -> 每日建议”的产品闭环，而不是建设多语言微服务体系。

不采用 Python + Java 的原因：

- 会增加服务拆分、接口契约、部署、日志、链路追踪和故障定位成本
- 认证、用户隔离、错误码和数据模型需要跨语言重复维护
- V1 没有明确的高并发交易型核心服务，暂时不需要 Java 单独承载
- AI 编排与快速实验更适合先放在 Python 后端内聚实现

保留 Java 的后续可能性：

- 当出现高并发、强事务、复杂企业集成或已有 Java 团队资产时，再拆出 Java 服务
- 可拆分对象包括账号中心、支付/订阅、复杂报表或高吞吐任务服务
- 拆分前提是 FastAPI 单体已跑通核心闭环，并且瓶颈有监控数据支撑

### 4.3 MySQL

选择原因：

- 健康记录、用户档案、每日归档都属于强结构化业务数据
- 支持事务、索引、约束和 JSON 字段
- 云服务器和国内云厂商托管 MySQL 生态成熟，运维资料和团队熟悉度通常更高
- 后续可以承载统计查询和趋势分析

默认约束：

- 使用 MySQL 8.4 LTS
- 默认存储引擎使用 InnoDB
- 字符集使用 `utf8mb4`
- 所有表必须有主键、创建时间和更新时间
- 通过 Alembic 管理结构变更

### 4.4 Redis

V1 使用 Redis 承担：

- 短信发送频率限制
- 登录验证码错误次数、短期锁定和防刷状态
- API 限流
- 后续异步任务状态缓存

短信验证码本身由阿里云生成并校验，后端不保存验证码明文，也不把验证码哈希作为主校验依据。Redis 不作为验证码主存储。

### 4.5 SQLAlchemy 与 Alembic

SQLAlchemy 用于 ORM 和查询组织，Alembic 用于数据库迁移。数据库结构必须通过迁移脚本演进，不直接在生产环境手动改表。

V1 使用 SQLAlchemy 2.x + PyMySQL 连接 MySQL。早期先采用同步数据库访问模型，降低实现复杂度；如果后续接口压力明显增加，再评估异步驱动或读写分离。

## 5. 认证架构

V1 采用手机号短信验证码注册/登录，短信能力基于阿里云号码认证服务 Dypnsapi。

登录成功后：

- 后端签发短生命周期 JWT access token
- 后端创建可撤销的 refresh session
- 客户端通过 `Authorization: Bearer <access_token>` 访问业务 API
- access token 过期后，客户端调用刷新接口
- 用户退出登录时撤销 refresh session

短信验证码要求：

- 发送验证码调用阿里云 `SendSmsVerifyCode`
- 校验验证码调用阿里云 `CheckSmsVerifyCode`
- `TemplateParam` 使用 `{"code":"##code##","min":"5"}`，由阿里云动态生成验证码
- 生产环境不返回验证码给后端或客户端
- 后端仍需限制发送频率、失败次数和短期锁定状态
- 记录发送与校验日志

阿里云接口映射：

```text
发送：SendSmsVerifyCode
  PhoneNumber
  CountryCode=86
  SchemeName
  SignName
  TemplateCode
  TemplateParam={"code":"##code##","min":"5"}
  CodeType=1
  CodeLength=6
  ValidTime=300
  Interval=60
  DuplicatePolicy=1
  ReturnVerifyCode=false

校验：CheckSmsVerifyCode
  PhoneNumber
  CountryCode=86
  SchemeName
  VerifyCode
```

后端只有在阿里云返回 `Code=OK`、`Success=true` 且 `Model.VerifyResult=PASS` 时，才视为验证码通过。

## 6. 模块划分

```text
backend/
  app/
    api/
      auth.py
      profile.py
      meals.py
      body_metrics.py
      summaries.py
      ai_extractions.py
    auth/
      jwt.py
      passwordless.py
      sessions.py
    models/
    schemas/
    services/
    ai/
    rules/
    storage/
    sms/
    core/
  tests/
```

模块职责：

- `api/`：HTTP 路由与请求响应
- `schemas/`：Pydantic 请求和响应模型
- `models/`：数据库模型
- `services/`：业务服务
- `auth/`：JWT、短信登录、会话刷新
- `ai/`：图片、语音和建议生成适配层
- `rules/`：营养计算、安全边界、建议规则
- `storage/`：媒体存储适配，支持客户端本地引用、服务端本地存储和对象存储
- `sms/`：短信服务商适配

## 7. Agent 与模型选型

### 7.1 交互形态

V1 的产品交互是通用 Agent 对话。用户可以用文字、图片、拍照图片和语音与 Agent 交流，但 Agent 能力边界只覆盖健身管理。

外部 API 不按 `meal-photo`、`meal-voice`、`scale-photo` 暴露，而是按会话、消息和待确认动作暴露：

```text
/conversations
/conversations/{conversation_id}/messages
/agent/extractions
/agent/pending-actions/{pending_action_id}
/agent/pending-actions/{pending_action_id}/confirm
/agent/pending-actions/{pending_action_id}/discard
```

后端内部再根据输入模态和意图路由到餐食记录、身体指标记录、每日总结或健身问答。

AI 提取结果不直接写入正式记录。只要动作会产生餐食、身体指标、每日总结等实质业务记录，后端必须先在当前会话中生成 `pending_action`。客户端在对话框中展示确认卡片，用户可以确认、编辑字段、用自然语言补充修正或放弃。只有确认后的动作才写入正式记录表。

### 7.2 V1 需要准备的模型能力

V1 至少需要三类模型能力：

- 文本 LLM：负责对话、意图识别、结构化输出、建议表达和工具调用
- 语音转文字模型：负责把用户语音输入转成文本
- 图片理解模型：负责理解餐食图片、秤面板图片和其他健身相关图片

推荐把模型适配层做成 provider 接口，不把业务逻辑绑定到某一家模型厂商。

V1 文本 LLM 默认接入阿里云百炼 / DashScope，使用 OpenAI 兼容接口：

```text
https://dashscope.aliyuncs.com/compatible-mode/v1
```

后端通过 `AI_PROVIDER` 切换 provider：

- `mock`：本地开发和测试默认值，不调用外部模型
- `bailian`：调用百炼 OpenAI-compatible Chat Completions

LLM 结构化输出必须遵循 `docs/ai-extraction-schema-v1.md`。模型输出只能生成 `agent_pending_actions`，不能直接写入正式记录。

V1 不要求准备 TTS 文本转语音模型。除非产品明确要“Agent 语音回复”，否则先只做语音输入，输出仍以文本和对话式确认卡片为主。

### 7.3 MiniMax 判断

MiniMax 可以作为文本对话模型候选，也有语音合成、图片生成、视频生成等能力。但从当前官方 API 文档看，它不适合作为 LetMeFit V1 的唯一模型供应商：

- 语音能力更偏 TTS、声音克隆等输出能力，不是我们最需要的 ASR 语音转文字
- 图片能力主要是图片生成、图生图、视频生成，不是明确的餐食/秤面板图片理解 API
- V1 需要稳定的结构化抽取、图片理解和语音转写，最好选择能明确覆盖这些能力的供应商

因此，MiniMax 不是“不行”，而是“不建议作为唯一模型底座”。如果使用 MiniMax，建议只先用于文本对话或后续语音播报；语音转写和图片理解另选专门模型。

### 7.4 LangChain / LangGraph / Deep Agents

V1 暂不推荐直接引入 LangChain、LangGraph 或 Deep Agents 作为核心编排框架。

原因：

- 当前 Agent 流程较短，主要是输入归一化、意图识别、结构化抽取、规则校验和对话式 Review/Edit 确认
- LangGraph 更适合长任务、状态持久化、人类审批、多步骤工具链和复杂 Agent 编排
- Deep Agents 更适合研究、编码、长周期规划、多子代理等复杂任务
- 过早引入会增加依赖、状态管理、调试和安全审计成本

V1 先自研轻量编排层：

```text
InputNormalizer -> IntentRouter -> ExtractionService -> RuleEngine -> ResponseComposer
```

当前 `InputNormalizer` 已作为后端内部 adapter 层接入会话消息发送流程：

- 文本 part 原样进入 extraction provider。
- 音频 part 进入 ASR adapter；默认 `mock` 只返回未处理状态和警告，不生成假转写。
- 图片 part 进入图片理解 adapter；默认 `mock` 只返回未处理状态和警告，不生成假识别内容。
- 真实 ASR 或图片理解模型接入后，应通过同一 adapter 输出转写文本或图片描述，再与原始消息、上下文一起交给 extraction provider。

ASR 第一版真实 provider 使用百炼/DashScope Paraformer 录音文件识别 REST API，配置为 `ASR_PROVIDER=dashscope_recording`。由于该接口要求音频文件 URL 可被服务端公网访问，成本敏感测试阶段的 `client_local` 音频不会被后端直接识别；需要识别时，客户端应上传临时文件或提供对象存储临时 URL。

上下文由后端 `ContextBuilder` 动态组装，不等于把数据库中的全量消息都塞给模型。每次调用模型时只取当前消息、当前待确认动作、最近若干条消息、滚动摘要、用户档案、最近正式记录、相关用户记忆和安全规则。原始消息用于 UI 展示和审计，较早消息压缩到 `conversation_summaries`，正式事实仍以档案和记录表为准。

当前后端实现采用滚动摘要策略：

- `ConversationContextBuilder` 在调用 extraction provider 前组装上下文。
- `ConversationSummaryService` 在消息数量超过阈值后，将较早消息压缩为新的 `conversation_summaries` 记录。
- 摘要文本明确标注“正式事实以档案和记录表为准”，避免把未确认对话内容当作事实。
- 默认上下文保留最近 8 条消息，超过 16 条未压缩消息后触发压缩；阈值可通过环境变量调整。

当出现长流程、多工具、多轮任务恢复、人工审批节点或复杂记忆系统时，再评估 LangGraph。Deep Agents 暂不纳入 V1。

## 8. 客户端策略

iOS App 与微信小程序都在产品规划内，但 V1 不并行实现两个客户端。

当前首个客户端为微信小程序，原因：

- 已有 Figma Make 高保真小程序原型
- 适合低门槛传播和微信生态触达
- 可以先验证短信登录、记录、确认、总结的完整闭环

iOS App 在核心闭环稳定后再启动。无论后续是否启动第二客户端，后端 API 不应绑定具体客户端。

## 9. UI 与 Figma

客户端 UI 设计以 Figma 为准。

在开始客户端实现前，至少需要完成：

- Login/Register
- Onboarding
- Home
- Capture
- Review/Edit
- Daily Summary

客户端实现应遵循 Figma 的信息层级、页面流、组件状态和交互说明。没有 Figma 确认的复杂 UI，不进入正式开发。

## 10. 部署架构

你的当前云服务器为腾讯云 4 核 4G，公网 IP 为 `49.232.156.14`，域名为 `www.letmefit.cloud`，并且已申请 SSL 证书。进入域名 HTTPS 测试阶段后，推荐引入 Nginx 作为 HTTPS 终止和反向代理。默认部署方式为：FastAPI 后端直接运行在宿主机，由 uv 管理 Python 环境并由 systemd 守护；MySQL 和 Redis 使用 Docker Compose 部署，并只绑定到 `127.0.0.1`。

```text
云服务器
  Nginx
    HTTPS 443，域名 www.letmefit.cloud
    反向代理到 127.0.0.1:8000
  systemd
    FastAPI 后端，监听 127.0.0.1:8000
  Docker Compose
    MySQL，绑定 127.0.0.1:3306
    Redis，绑定 127.0.0.1:6379
```

后端不作为默认 Docker 服务运行。这样可以减少早期部署和排障复杂度，同时让数据库与缓存保持容器隔离和可迁移性。

Nginx 是否引入按阶段判断：

- 本地开发、内测 API、后端联调：暂不需要 Nginx
- 需要正式域名、HTTPS 证书、反向代理、请求体大小控制、访问日志或静态资源代理时：引入 Nginx
- 如果使用腾讯云负载均衡或其他网关完成 HTTPS 终止，也可以不在云服务器内运行 Nginx

4 核 4G 机器运行 Nginx 没有明显资源压力。当前已有域名和 SSL 证书，因此 V1 服务器测试阶段采用 Nginx 是更清晰的方案。部署细节见 `docs/backend-deployment-tencent-cloud.md`。

媒体文件存储按阶段选择：本地开发可用服务端本地存储；成本敏感的服务器测试可让 App 保留图片/音频原始文件在本地，后端只保存客户端本地引用与结构化结果；公开测试或生产建议使用腾讯云 COS 等对象存储。短信验证码使用阿里云号码认证服务。若进入公开测试，应将数据库迁移到托管数据库或至少独立磁盘和备份策略。

## 11. 后续待决

- 微信小程序首个客户端的真实设备联调与发布范围
- 媒体文件存储阶段策略与对象存储服务
- 营养数据源
- AI 服务商与模型调用策略，尤其是 ASR 与图片理解模型
- 是否需要异步任务队列
- 是否在公开测试前引入 Nginx、Caddy 或腾讯云负载均衡

## 12. 参考资料

- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [MySQL 官方文档](https://dev.mysql.com/doc/mysql/en/)
- [SQLAlchemy 官方文档](https://www.sqlalchemy.org/)
- [SQLAlchemy MySQL Dialect 文档](https://docs.sqlalchemy.org/20/dialects/mysql.html)
- [Alembic 官方文档](https://alembic.sqlalchemy.org/)
- [阿里云 SendSmsVerifyCode](https://next.api.aliyun.com/document/Dypnsapi/2017-05-25/SendSmsVerifyCode)
- [阿里云 CheckSmsVerifyCode](https://next.api.aliyun.com/document/Dypnsapi/2017-05-25/CheckSmsVerifyCode)
- [Uvicorn 部署文档](https://www.uvicorn.org/deployment/)
- [OpenAI Speech to Text](https://platform.openai.com/docs/guides/speech-to-text)
- [OpenAI Images and Vision](https://platform.openai.com/docs/guides/images-vision)
- [MiniMax API Overview](https://platform.minimax.io/docs/api-reference/api-overview)
- [LangGraph 官方文档](https://docs.langchain.com/oss/python/langgraph/overview)
- [Deep Agents 官方文档](https://docs.langchain.com/oss/python/deepagents/index)
- [Spring Framework Controller 文档](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller.html)
- [Apple SwiftUI 官方文档](https://developer.apple.com/documentation/SwiftUI)
- [微信小程序开发文档](https://developers.weixin.qq.com/miniprogram/dev/framework/)
