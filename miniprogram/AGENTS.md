# LetMeFit Miniprogram

WeChat Mini Program client — TypeScript, native WXML/WXSS. Builds and runs in WeChat DevTools.

## Source Of Truth

When documents conflict, this order wins:

1. `../AGENTS.md` — project-level safety boundaries and core invariants
2. `../docs/backend-api-v1.md` — API contracts the client must follow
3. `../docs/agent-tool-call-design.md` — pending action confirmation flow
4. This file

## Commands

```bash
# from the miniprogram/ directory
npx tsc --noEmit    # type check only, no output
```

Runtime testing requires WeChat DevTools.

## Rules

- All API requests must go through `utils/request.ts` — handles response envelope, JWT, and token refresh.
- AI extraction results must be presented as `pending_action` confirmation cards. The user must confirm or edit before the commit API is called.
- UI must follow Figma designs. Complex pages without Figma sign-off do not enter implementation.
- `client_local` audio cannot be transcribed by the backend directly. Upload via `POST /v1/uploads/local-file` first to get a server-accessible URL.

## Change Scope

| Area | Required reading |
|------|-----------------|
| Pending action card behavior or confirmation flow | `../docs/agent-tool-call-design.md` |
| API request/response handling or error codes | `../docs/backend-api-v1.md` |

## Directory

- `pages/` — welcome, login, onboarding, home, record, agent, summary, profile
- `components/pending-action-card/` — AI pending action confirmation card
- `services/` — backend REST API wrappers
- `utils/request.ts` — response envelope, JWT, token refresh
- `config/` — environment config
- `types/` — API and miniprogram type supplements
