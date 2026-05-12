# LetMeFit

Health fitness management agent — general fitness and lifestyle advice only, not medical.

## Repo Layout

- `backend/` → `backend/AGENTS.md`
- `miniprogram/` → `miniprogram/AGENTS.md`
- `docs/` — design docs, API specs, known issues

## Decision Priority

When rules or documents conflict, this order wins:

1. **Safety Boundaries** (below) — no exceptions
2. **`docs/backend-api-v1.md`** — API contracts are stable; breaking changes require doc update first
3. **`docs/agent-tool-call-design.md`** — pending action semantics and grounding rules
4. Sub-module `AGENTS.md` for module-specific behavior
5. This file for cross-cutting defaults

## Core Invariants

- AI extraction → pending action → user confirmation → formal record. No shortcuts.
- Backend is the only trusted entry point. Clients never connect directly to DB, storage, SMS, or AI.
- All private APIs require JWT. Refresh sessions are revocable server-side.

## Safety Boundaries

Absolute — no exceptions regardless of user request:
- No medical diagnosis, treatment advice, or disease management
- No extreme calorie restriction recommendations
- No high-risk scenarios: pregnancy, minors, clinical diet management

All suggestions must be dismissible, editable, and regenerable by the user.

## Change Scope

Before touching these areas, read the listed doc first:

| Area | Required reading |
|------|-----------------|
| Agent loop, pending actions, context building | `docs/agent-tool-call-design.md` + `docs/backend-design-problems.md` |
| Database schema | `docs/database-design-v1.md` — use Alembic only |
| API response contracts | `docs/backend-api-v1.md` — update doc before changing behavior |
| Tech stack | `docs/technical-architecture.md` — update doc before changing code |
| LLM output schema | `docs/ai-extraction-schema-v1.md` |

## Document Index

| Doc | Purpose |
|-----|---------|
| `docs/technical-architecture.md` | Tech stack, deployment, module layout |
| `docs/backend-api-v1.md` | REST API contracts, response schemas, error codes |
| `docs/agent-tool-call-design.md` | ReAct loop, tools, pending action semantics, grounding |
| `docs/conversation-context-design.md` | Context window, rolling summary |
| `docs/ai-extraction-schema-v1.md` | LLM structured output schema |
| `docs/database-design-v1.md` | DB schema |
| `docs/backend-design-problems.md` | Known bugs and deferred design issues |
| `docs/backend-deployment-tencent-cloud.md` | Server deployment |
| `docs/prd-v1-zh.md` | Product requirements |
