# LetMeFit 微信小程序

原生微信小程序 + TypeScript 客户端，UI 按 `figma-share-links.txt` 中的 Figma 页面实现。

## 本地调试

默认 API 地址：

```text
见 `config/env.ts` 中的 `DEFAULT_API_BASE_URL`
```

如需连接局域网或测试环境后端，可在开发者工具 Storage 中设置：

```text
LETMEFIT_API_BASE_URL = http://你的后端地址/v1
```

如果线上语音或媒体接口已经切换地址但小程序仍访问旧服务，先检查并清除开发者工具 Storage 里的 `LETMEFIT_API_BASE_URL`，因为它会覆盖代码中的默认地址。

## 主要目录

- `pages/`：欢迎、登录、onboarding、今日、记录、Agent、总结、我的。
- `components/pending-action-card/`：AI 待确认动作卡片。
- `services/`：后端 REST API 封装。
- `utils/request.ts`：统一响应结构、JWT 和 refresh token 处理。
- `assets/`：Figma 原型使用的 Agent 与聊天背景素材。
