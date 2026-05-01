# LetMeFit

LetMeFit 是一个面向健身管理与生活方式建议的健康 Agent 项目。

当前仓库主要用于沉淀产品定义、技术选型、架构设计、API 设计和后续开发资料。项目采用前后端分离架构，后端部署在云服务器上并提供统一 API。

V1 客户端规划覆盖 iOS App 与微信小程序，但开发节奏采用“先完成一个客户端验证核心闭环”的方式推进，不并行启动两个客户端。

## 当前内容

- [V1 中文 PRD](docs/prd-v1-zh.md)
- [V1 实施计划](docs/v1-implementation-plan.md)
- [技术选型与架构设计](docs/technical-architecture.md)
- [后端 API 文档](docs/backend-api-v1.md)
- [V1 数据库表设计](docs/database-design-v1.md)
- [项目 AGENTS 指南](AGENTS.md)

## 建议的后续目录结构

后续可以按实际开发进度逐步扩展：

```text
docs/           产品文档、原型说明、接口设计
ios/            iOS 客户端工程
miniprogram/    微信小程序工程
backend/        后端服务
infra/          部署与环境配置
scripts/        工具脚本
```

## 协作建议

- 先完成技术选型、架构设计和项目 `AGENTS.md`
- 再完成后端 API 文档，并优先实现后端
- iOS App 与微信小程序先选择一个客户端实现，另一个客户端在核心闭环稳定后再启动
- 客户端 UI 设计以 Figma 为准
- 客户端统一通过后端 API 访问数据和 AI 能力，不直接连接数据库或模型服务
- V1 账号体系采用手机号短信注册/登录，接口认证采用 JWT
- 统一通过 git 协作，避免本地临时文件进入版本库
