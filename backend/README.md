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

## Bailian LLM

Local development defaults to `AI_PROVIDER=mock`.

To call Alibaba Cloud Bailian / DashScope through the OpenAI-compatible API:

```env
AI_PROVIDER=bailian
BAILIAN_API_KEY=your-api-key
BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
BAILIAN_MODEL=qwen-plus
AI_SCHEMA_REPAIR_RETRIES=1
```

`DASHSCOPE_API_KEY` is also supported as a fallback API key variable.
LLM output is validated against the backend extraction schema before any pending action is created.

## Conversation Context

The backend builds model context dynamically before extraction. It includes the latest rolling summary, recent messages, active pending actions, profile fields, and recent formal records.

```env
CONVERSATION_CONTEXT_RECENT_MESSAGES=8
CONVERSATION_SUMMARY_TRIGGER_MESSAGES=16
CONVERSATION_SUMMARY_MAX_CHARS=2000
CONVERSATION_SUMMARY_WORKER_LIMIT=10
CONVERSATION_SUMMARY_WORKER_INTERVAL_SECONDS=5
CONVERSATION_SUMMARY_RUNNING_TIMEOUT_SECONDS=600
```

Older messages are compressed into `conversation_summaries`; summaries are context only and are not treated as formal records.
Run `scripts/process_conversation_summaries.py --loop` as a separate worker in server deployments.

## Multimodal Input

Audio and image message parts go through `InputNormalizer` before extraction. The default providers are placeholders:

```env
ASR_PROVIDER=mock
VISION_PROVIDER=mock
```

The mock providers record media status and warnings but do not pretend to transcribe audio or understand images. Real ASR and vision providers can later be added behind the same adapter interfaces without changing the conversation API.

To use Alibaba Cloud Bailian / DashScope Paraformer recording-file ASR:

```env
ASR_PROVIDER=dashscope_recording
DASHSCOPE_API_KEY=your-api-key
DASHSCOPE_ASR_MODEL=paraformer-v2
DASHSCOPE_ASR_LANGUAGE_HINTS=zh,en
```

DashScope recording-file ASR requires a public HTTP/HTTPS audio URL or supported OSS URL. `client_local` audio remains unprocessed until the client uploads a server-accessible temporary file.

For the first WeChat Mini Program voice flow, upload microphone recordings to the backend as temporary local-server files:

```env
MEDIA_UPLOAD_DIR=./var/uploads
MEDIA_PUBLIC_BASE_URL=https://www.letmefit.cloud
MEDIA_MAX_UPLOAD_BYTES=10485760
```

The client sends `POST /v1/uploads/local-file` as multipart form data. The backend stores the file under `MEDIA_UPLOAD_DIR`, exposes it from `/media/...`, saves an `upload_files` row with `storage_provider=local_server`, and passes the public media URL to DashScope during message normalization. In local development, real ASR needs a public tunnel URL for `MEDIA_PUBLIC_BASE_URL`; `http://127.0.0.1:8000` is only useful for exercising the upload path.

First-stage OSS URL smoke test:

```bash
cd backend
ASR_PROVIDER=dashscope_recording uv run python scripts/asr_smoke_from_csv.py ../sounds/export_urls.csv
```

The CSV must contain `object,url` columns. The script does not print signed URLs; it prints each object name, ASR status, and transcript or warning reason.

Server API smoke test, after deploying the backend:

```bash
cd backend
LETMEFIT_API_BASE_URL=https://www.letmefit.cloud/v1 \
uv run python scripts/api_asr_smoke_from_csv.py ../sounds/export_urls.csv
```

By default this logs in with the mock SMS code `123456`. For an environment that uses real SMS, pass an existing JWT:

```bash
uv run python scripts/api_asr_smoke_from_csv.py ../sounds/export_urls.csv \
  --base-url https://www.letmefit.cloud/v1 \
  --access-token "$LETMEFIT_ACCESS_TOKEN"
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

On the Tencent Cloud Ubuntu server, use Docker Compose for MySQL/Redis, systemd for FastAPI, and Nginx for HTTPS:

```bash
cp .env.production.example .env.production
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

For `www.letmefit.cloud`, install the Nginx config from `deploy/nginx/letmefit.cloud.conf.example` and place the SSL certificate files at:

```text
/etc/nginx/ssl/letmefit.cloud/fullchain.pem
/etc/nginx/ssl/letmefit.cloud/privkey.pem
```

Full server deployment guide: `../docs/backend-deployment-tencent-cloud.md`.
