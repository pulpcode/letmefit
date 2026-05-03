# LetMeFit WeChat Mini Program

原生微信小程序 + TypeScript 客户端，用于跑通 V1 核心闭环：

```text
短信登录 -> 创建档案 -> 今日首页 -> Agent 记录 -> 待确认卡片 -> 确认保存 -> 每日总结
```

## Open in WeChat DevTools

1. 打开微信开发者工具。
2. 导入 `miniprogram/` 目录。
3. 在 `config/env.ts` 中按环境调整 `API_BASE_URL`。
4. 本地后端默认地址为 `http://localhost:8000/v1`。

## Backend Contract

客户端按 `../docs/backend-api-v1.md` 对接后端。所有响应经过 `utils/request.ts` 解包，业务代码只处理 `data`。

## Media Strategy

V1 测试阶段使用 `client_local` 上传记录：小程序保留图片/音频临时路径，后端只保存本地引用、媒体类型、来源和结构化结果。

