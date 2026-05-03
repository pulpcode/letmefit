# LetMeFit 项目 AGENTS 指南

## 项目方向

LetMeFit 是一个健康健身管理 Agent。V1 的核心闭环是：

```text
短信登录 -> 创建档案 -> 记录饮食/身体指标 -> AI 提取 -> 用户确认 -> 每日归档 -> 总结与建议
```

产品边界：只提供一般健身管理与生活方式建议，不提供医疗诊断、治疗建议或疾病管理。

## 当前执行顺序

1. 完成技术选型与架构设计
2. 完成项目级 `AGENTS.md`
3. 完成后端 API 文档
4. 优先实现后端
5. 基于 Figma 设计实现首个客户端
6. iOS App 与微信小程序只先实现一个，另一个在核心闭环稳定后再启动

## 架构原则

- 项目采用前后端分离架构
- 后端部署在云服务器上，通过 REST/JSON API 对外提供能力
- 客户端不得直接连接数据库、私有对象存储、短信服务或 AI 模型服务
- 成本敏感的服务器测试阶段，图片/音频原始文件可只保留在客户端本地；后端只保存必要引用、元数据和结构化结果
- 手机号短信验证码用于注册/登录
- JWT access token 用于业务 API 认证
- refresh session 必须可由后端撤销
- AI 提取结果必须先成为对话中的待确认动作，用户确认或修改后才能写入正式记录

## 技术选型

默认技术路线：

- 后端：Python + FastAPI
- Python 环境与依赖管理：uv
- 数据库：MySQL 8.4 LTS
- ORM 与迁移：SQLAlchemy + Alembic
- MySQL 驱动：PyMySQL
- 缓存与限流：Redis
- 短信：阿里云号码认证服务 Dypnsapi
- 部署：腾讯云 4 核 4G 云服务器；后端用 uv + systemd 运行，MySQL/Redis 用 Docker Compose；Nginx 可选
- 媒体存储：本地开发/测试可用客户端本地或服务端本地存储，生产建议 S3 兼容对象存储
- Agent 框架：V1 自研轻量编排，暂不引入 LangChain/LangGraph/Deep Agents
- API 文档：OpenAPI 自动文档 + `docs/backend-api-v1.md`

如需替换技术栈，先更新 `docs/technical-architecture.md`，再改代码。

V1 不采用 Python + Java 双后端。除非有明确的高并发、强事务、企业集成或既有 Java 团队资产，否则后端统一使用 Python + FastAPI，避免过早增加服务拆分和跨语言维护成本。

## 后端开发约束

- 先实现 `auth`、`profile`、`meals`、`body-metrics`、`daily-archives`、`summaries`
- 所有用户私有数据必须按 `user_id` 隔离
- 所有业务接口必须校验 JWT
- 短信验证码由阿里云 `SendSmsVerifyCode` 生成，由 `CheckSmsVerifyCode` 校验
- 后端不保存验证码明文，Redis 只保存频控、防刷、失败次数和短期锁定状态
- 生产环境不得设置返回验证码给后端或客户端
- 数据库结构必须通过迁移脚本变更
- API 响应结构遵循 `docs/backend-api-v1.md`
- 业务规则放在 `services/` 或 `rules/`，不要塞进路由函数
- AI 外部接口按会话消息和待确认动作设计，不按 `meal-photo`、`meal-voice`、`scale-photo` 设计
- 多模态输入统一经过 `InputNormalizer -> IntentRouter -> ExtractionService -> RuleEngine -> ResponseComposer`
- V1 至少需要文本 LLM、语音转文字模型和图片理解模型；TTS 暂不需要
- MiniMax 可作为文本对话候选，但不作为 V1 唯一模型供应商

## 客户端开发约束

- 客户端 UI 以 Figma 为准
- 没有 Figma 确认的复杂页面，不进入正式实现
- iOS App 与微信小程序不并行启动
- 当前首个客户端为微信小程序，基于 Figma Make 原型实现；iOS App 在核心闭环稳定后再启动
- 客户端只通过后端 API 读写数据
- 对话中的 Review/Edit 确认状态或确认卡片是所有 AI 结果进入正式记录前的必经步骤

## 文档优先级

后续文档按以下顺序补齐：

1. `docs/technical-architecture.md`
2. `docs/backend-api-v1.md`
3. AI JSON Schema 文档
4. Figma 页面流说明
5. 后端部署说明
6. 首个客户端实现说明

## 安全边界

- 不输出医疗诊断
- 不建议极端热量限制
- 不支持孕期、未成年人、疾病饮食管理等高风险场景
- 数据置信度低时优先要求用户确认
- 所有建议都应允许用户忽略、修改记录或重新生成
