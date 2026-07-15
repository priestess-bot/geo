# 本地开发运行手册

## 1. 准备环境

需要 Docker Compose、uv、Node.js 22 和 Corepack。首次执行：

```bash
uv sync
corepack pnpm install
cp .env.example .env
chmod 600 deepseek_api_key.txt
```

DeepSeek Key 不得写入 `.env`、命令历史、测试输出或 Git；使用 `GEO_DEEPSEEK_API_KEY_FILE` 指向 mode 0600 文件。

## 2. 启动基础设施

```bash
docker compose -f infra/docker-compose.yml up -d postgres minio valkey
docker compose -f infra/docker-compose.yml ps
```

数据库整改完成后，空库只通过 Alembic 建立。不要对旧测试库执行 stamp；旧测试数据可以删除并重新 seed。

## 3. 启动 API

```bash
uv run uvicorn geo_api.internal_app:app --app-dir apps/api --reload --port 8000
uv run uvicorn geo_api.customer_app:app --app-dir apps/api --reload --port 8001
```

检查：

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8001/health
curl -i http://localhost:8001/v1/engineering/status
```

最后一个请求必须为 404，证明 Customer API 没有注册内部工程路由。

## 4. 启动前端

```bash
corepack pnpm --filter geo-production-admin-web dev -- --port 3001
corepack pnpm --filter geo-production-customer-web dev -- --port 3000
```

访问 Admin `http://localhost:3001` 和 Customer `http://localhost:3000`。Development Board 在工程适配器未连接时显示 unavailable/unknown，不应显示伪造完成率。

## 5. 停止

停止前台开发进程后执行：

```bash
docker compose -f infra/docker-compose.yml down
```

删除测试数据库卷必须是显式操作，只允许在确认没有真实数据的开发环境执行。
