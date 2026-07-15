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
make dev-up
docker compose -f infra/docker-compose.yml --profile workers ps
```

`make dev-up` 会先检查 `deepseek_api_key.txt` 的存在性和权限，再启动基础设施、执行 Alembic、创建开发运行角色，并启动双 API、Worker 与双 Web。空库只通过 Alembic 建立；不要对旧测试库执行 stamp，旧测试数据可以删除并重新 seed。

## 3. 启动 API

完整 Compose 已启动 API。只在调试单个进程且已经显式设置宿主机 `GEO_DATABASE_URL`、对象存储和 Valkey 配置时，才使用 `make api-internal` 或 `make api-customer`。

检查：

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8001/health
curl -i http://localhost:8001/v1/engineering/status
```

最后一个请求必须为 404，证明 Customer API 没有注册内部工程路由。

## 4. 启动前端

完整 Compose 已启动两个前端。只在调试前端热更新时，才分别使用 `make admin-web` 和 `make customer-web`。

访问 Admin `http://localhost:3001` 和 Customer `http://localhost:3000`。Development Board 在工程适配器未连接时显示 unavailable/unknown，不应显示伪造完成率。

## 5. 停止

执行：

```bash
make dev-down
```

删除测试数据库卷必须是显式操作，只允许在确认没有真实数据的开发环境执行。
