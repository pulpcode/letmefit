# LetMeFit Backend

FastAPI backend for LetMeFit.

## Local Setup

```bash
cp .env.example .env
docker compose up -d mysql redis
uv sync --group dev
uv run pytest
uv run uvicorn app.main:app --reload
```

Health check:

```bash
curl http://localhost:8000/v1/health
```

## Database Services

```bash
cp .env.example .env
docker compose up -d mysql redis
```

MySQL and Redis are bound to localhost only:

```text
127.0.0.1:3306
127.0.0.1:6379
```

The FastAPI backend runs on the host with uv, not in Docker.

## Alembic

```bash
uv run alembic revision --autogenerate -m "message"
uv run alembic upgrade head
```

## Server Deployment

On the Tencent Cloud Ubuntu server, use Docker Compose for MySQL/Redis and systemd for FastAPI:

```bash
cp .env.example .env.production
docker compose --env-file .env.production up -d mysql redis
uv sync --frozen --no-dev
uv run alembic upgrade head
```

Install the systemd unit from `deploy/systemd/letmefit-backend.service.example`, then start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable letmefit-backend
sudo systemctl start letmefit-backend
```
