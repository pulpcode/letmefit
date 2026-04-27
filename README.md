# LetMeFit

LetMeFit 是一个面向健身管理与生活方式建议的健康 Agent 项目。

当前仓库主要用于沉淀产品定义、原型设计和后续的跨平台开发资料，目标支持 Windows 与 macOS 协作开发：

- Windows 侧适合承担产品设计、后端、AI 编排与通用工程开发
- macOS 侧适合承担 iOS 客户端、Xcode 调试、签名与发布

## 当前内容

- [V1 中文 PRD](docs/prd-v1-zh.md)
- [V1 英文草稿](docs/prd-v1-health-agent.md)

## 建议的后续目录结构

后续可以按实际开发进度逐步扩展：

```text
docs/           产品文档、原型说明、接口设计
ios/            iOS 客户端工程
backend/        后端服务
infra/          部署与环境配置
scripts/        工具脚本
```

## 协作建议

- 先冻结 PRD，再进入 Figma 原型阶段
- 原型确认后，再拆分 iOS、后端、AI 能力与数据库设计
- 统一通过 git 协作，避免 Windows 与 macOS 本地临时文件进入版本库
