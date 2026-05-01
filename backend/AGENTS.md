# LetMeFit Backend Instructions

## Source Of Truth

Backend work must follow these documents:

- `../AGENTS.md`
- `../docs/technical-architecture.md`
- `../docs/backend-api-v1.md`

If instructions conflict, prefer the more specific backend API document, then the technical architecture document, then the root `AGENTS.md`.

## Stack

- Python + FastAPI
- Python environment and dependency management with uv
- MySQL 8.4 LTS
- SQLAlchemy + Alembic + PyMySQL
- Redis
- Aliyun Dypnsapi SMS verification
- JWT access token + refresh token
- uv for running the FastAPI backend on the host
- Docker Compose only for local/small-server MySQL and Redis

Do not introduce a Java backend in V1.

## Backend Rules

- Keep route handlers thin.
- Put business logic in service modules.
- Put request and response contracts in Pydantic schemas.
- All private APIs must validate JWT.
- All private user data must be isolated by `user_id`.
- API response format must follow `../docs/backend-api-v1.md`.
- All database schema changes must use Alembic migrations.
- Do not commit secrets, access keys, tokens, or production `.env` files.
- Use `uv sync` and `uv run` for local backend development.
- Keep `uv.lock` committed when Python dependencies change.
- Do not add a backend Dockerfile as the default deployment path.
- Bind Dockerized MySQL and Redis to `127.0.0.1`; do not expose database ports publicly.

## Auth And SMS

- SMS verification must use Aliyun Dypnsapi:
  - `SendSmsVerifyCode`
  - `CheckSmsVerifyCode`
- Do not return SMS verification codes in production.
- Treat SMS verification as successful only when Aliyun verification result is `PASS`.
- Use Redis only for rate limits, anti-abuse, failed attempt counters, short locks, and short-lived task state.
- Redis must not be the primary store for Aliyun-generated SMS verification codes.

## Agent Rules

- Use conversation/message based APIs for user interaction.
- AI outputs that would create business records must become pending actions in the conversation before they can be committed.
- Do not create narrow multimodal endpoints such as `meal-photo`, `meal-voice`, or `scale-photo`.
- V1 Agent pipeline is lightweight and self-built:
  - `InputNormalizer`
  - `IntentRouter`
  - `ExtractionService`
  - `RuleEngine`
  - `ResponseComposer`
- Do not introduce LangChain, LangGraph, or Deep Agents unless the architecture document is explicitly changed.
- Model providers must be replaceable through adapters.

## Testing

- Add tests for meaningful backend behavior.
- Mock external services in tests.
- Minimum expected test areas:
  - health check
  - response envelope
  - validation errors
  - JWT-protected routes
  - SMS send/verify adapter
  - profile APIs
  - Alembic migration import or smoke test
