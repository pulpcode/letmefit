# LetMeFit Backend Tencent Cloud Deployment

目标环境：

- 云服务器：Tencent Cloud Ubuntu
- 公网 IP：`49.232.156.14`
- 域名：`www.letmefit.cloud`
- HTTPS：Nginx 终止 SSL，反向代理到本机 FastAPI
- 后端运行：uv + systemd
- MySQL / Redis：Docker Compose，仅绑定 `127.0.0.1`

## 1. DNS

在域名解析中添加：

```text
www.letmefit.cloud  A  49.232.156.14
```

如果需要根域名跳转，也添加：

```text
letmefit.cloud  A  49.232.156.14
```

## 2. Security Group

腾讯云安全组建议只开放：

```text
22/tcp    SSH
80/tcp    HTTP
443/tcp   HTTPS
```

不要对公网开放：

```text
8000/tcp  FastAPI internal port
3306/tcp  MySQL
6379/tcp  Redis
```

## 3. Server Packages

```bash
sudo apt update
sudo apt install -y nginx git curl ca-certificates
curl -LsSf https://astral.sh/uv/install.sh | sh
```

安装 Docker 与 Docker Compose plugin 后确认：

```bash
docker --version
docker compose version
```

## 4. App User And Code

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin letmefit
sudo mkdir -p /opt/letmefit
sudo chown -R letmefit:letmefit /opt/letmefit
```

部署代码：

```bash
sudo -u letmefit git clone <your-repo-url> /opt/letmefit
cd /opt/letmefit/backend
```

如果代码已存在：

```bash
cd /opt/letmefit
sudo -u letmefit git pull
```

## 5. Production Environment

```bash
cd /opt/letmefit/backend
sudo -u letmefit cp .env.production.example .env.production
sudo -u letmefit chmod 600 .env.production
sudo -u letmefit nano .env.production
```

必须替换：

- `MYSQL_PASSWORD`
- `MYSQL_ROOT_PASSWORD`
- `REDIS_PASSWORD`
- `DATABASE_URL`
- `REDIS_URL`
- `JWT_SECRET_KEY`
- `ALIYUN_ACCESS_KEY_ID`
- `ALIYUN_ACCESS_KEY_SECRET`
- `ALIYUN_SMS_SCHEME_NAME`
- `ALIYUN_SMS_SIGN_NAME`
- `ALIYUN_SMS_TEMPLATE_CODE`
- `BAILIAN_API_KEY`
- `MEDIA_PUBLIC_BASE_URL`

语音识别测试阶段建议设置：

```env
ASR_PROVIDER=dashscope_recording
DASHSCOPE_API_KEY=replace-with-dashscope-api-key
MEDIA_UPLOAD_DIR=./var/uploads
MEDIA_PUBLIC_BASE_URL=https://www.letmefit.cloud
MEDIA_MAX_UPLOAD_BYTES=10485760
```

摘要 worker 默认配置：

```env
CONVERSATION_SUMMARY_WORKER_LIMIT=10
CONVERSATION_SUMMARY_WORKER_INTERVAL_SECONDS=5
CONVERSATION_SUMMARY_RUNNING_TIMEOUT_SECONDS=600
```

## 6. MySQL And Redis

```bash
cd /opt/letmefit/backend
sudo -u letmefit docker compose --env-file .env.production up -d mysql redis
sudo -u letmefit docker compose ps
```

数据库与缓存只监听本机：

```text
127.0.0.1:3306
127.0.0.1:6379
```

## 7. Python Environment And Migrations

```bash
cd /opt/letmefit/backend
sudo -u letmefit uv sync --frozen --no-dev
sudo -u letmefit uv run alembic upgrade head
```

本机验证：

```bash
sudo -u letmefit uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/v1/health
```

验证后停止临时 uvicorn。

## 8. systemd

```bash
sudo cp /opt/letmefit/backend/deploy/systemd/letmefit-backend.service.example \
  /etc/systemd/system/letmefit-backend.service
sudo cp /opt/letmefit/backend/deploy/systemd/letmefit-summary-worker.service.example \
  /etc/systemd/system/letmefit-summary-worker.service
sudo systemctl daemon-reload
sudo systemctl enable letmefit-backend
sudo systemctl enable letmefit-summary-worker
sudo systemctl start letmefit-backend
sudo systemctl start letmefit-summary-worker
sudo systemctl status letmefit-backend
sudo systemctl status letmefit-summary-worker
```

查看日志：

```bash
sudo journalctl -u letmefit-backend -f
sudo journalctl -u letmefit-summary-worker -f
```

## 9. SSL Certificate

将证书放到：

```text
/etc/nginx/ssl/letmefit.cloud/fullchain.pem
/etc/nginx/ssl/letmefit.cloud/privkey.pem
```

如果云厂商下载的文件名是 `.crt` / `.key`，可以复制或重命名到上述路径。

```bash
sudo mkdir -p /etc/nginx/ssl/letmefit.cloud
sudo chmod 700 /etc/nginx/ssl/letmefit.cloud
sudo chmod 600 /etc/nginx/ssl/letmefit.cloud/*
```

## 10. Nginx

```bash
sudo cp /opt/letmefit/backend/deploy/nginx/letmefit.cloud.conf.example \
  /etc/nginx/sites-available/letmefit.cloud.conf
sudo ln -s /etc/nginx/sites-available/letmefit.cloud.conf \
  /etc/nginx/sites-enabled/letmefit.cloud.conf
sudo nginx -t
sudo systemctl reload nginx
```

公网验证：

```bash
curl -i https://www.letmefit.cloud/v1/health
```

期望响应：

```json
{
  "data": {
    "status": "ok"
  },
  "request_id": "req_..."
}
```

## 11. Release Update

```bash
cd /opt/letmefit
sudo -u letmefit git pull
cd /opt/letmefit/backend
sudo -u letmefit uv sync --frozen --no-dev
sudo -u letmefit uv run alembic upgrade head
sudo systemctl restart letmefit-backend
sudo systemctl restart letmefit-summary-worker
sudo nginx -t
sudo systemctl reload nginx
```

## 12. Production Notes

- `.env.production` must not be committed.
- Keep MySQL and Redis ports bound to `127.0.0.1`.
- Keep FastAPI bound to `127.0.0.1:8000`; public traffic enters through Nginx.
- Run `letmefit-summary-worker` as a separate systemd service; it handles SIGTERM gracefully and finishes the current claimed summary job before exit.
- Back up Docker volumes before destructive operations.
- Public beta should add database backup, log rotation, and certificate renewal reminders.
