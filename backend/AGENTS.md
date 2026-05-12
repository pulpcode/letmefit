# LetMeFit Backend

## Source Of Truth

When documents conflict, this order wins:

1. `../docs/backend-api-v1.md` — API contracts and response schemas
2. `../docs/agent-tool-call-design.md` — pending action semantics and grounding rules
3. `../docs/technical-architecture.md` — tech choices and module layout
4. `../docs/conversation-context-design.md` — context window composition and rolling summary
5. `../AGENTS.md` — project-level constraints

## Commands

```bash
# from the backend/ directory
uv run pytest                          # run all tests
uv run ruff check .                    # lint
uv run ruff format --check .           # format check
uv run uvicorn app.main:app --reload   # dev server
uv run alembic upgrade head            # apply migrations
```

All changes must pass `uv run pytest` and `uv run ruff check .` before done.

## Change Scope

Before touching these areas, read the listed doc first:

| Area | Required reading |
|------|-----------------|
| Agent loop, pending actions, context building | `../docs/agent-tool-call-design.md` + `../docs/backend-design-problems.md` |
| LLM output or extraction schema | `../docs/ai-extraction-schema-v1.md` |
| Database schema | `../docs/database-design-v1.md` — Alembic only, no manual table edits |
| API response contracts | `../docs/backend-api-v1.md` — update doc before changing behavior |
| System prompts | Re-check if model role, safety boundaries, tool-call contract, or context authority changed |

## Backend Rules

- Keep route handlers thin; business logic in service modules.
- Request and response contracts in Pydantic schemas.
- All private APIs must validate JWT.
- All private user data must be isolated by `user_id`.
- API response format must follow `../docs/backend-api-v1.md`.
- Do not commit secrets, access keys, tokens, or production `.env` files.
- Use `uv sync` and `uv run` for local development. Keep `uv.lock` committed.
- Bind Dockerized MySQL and Redis to `127.0.0.1`; do not expose database ports publicly.
- Do not add a backend Dockerfile as the default deployment path.

## Auth And SMS

- Do not return SMS verification codes in production.
- Redis is for rate limits, anti-abuse, failed attempt counters, and short locks only — not primary SMS code storage.

## Agent Rules

- AI outputs that would create business records must become pending actions before they can be committed.
- Model providers must be replaceable through adapters.
- Keep `AI_PROVIDER=mock` as the default for tests and local development.
- Build model context through `ConversationContextBuilder`; do not send full conversation history to the model.
- Treat `conversation_summaries` as rolling context only, not as formal user facts.
- Run multimodal message parts through `InputNormalizer` before extraction.
- Keep ASR and image understanding behind replaceable adapters; `mock` providers must not pretend to read media content.
- DashScope recording-file ASR requires server-accessible audio URLs; do not treat `client_local` audio as readable by the backend.

## Testing

- Mock external services in tests.
- Minimum expected test areas:
  - health check and response envelope
  - validation errors
  - JWT-protected routes
  - SMS send/verify adapter
  - profile APIs
  - Alembic migration import or smoke test
