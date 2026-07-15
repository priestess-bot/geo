# GEO Platform

GEO Platform 是一个以证据为基础的 AI 搜索监测与内容投放系统。它帮助团队识别消费者在 ChatGPT、Google 等 AI 搜索工具中的商品咨询问题，分析模型实际引用的信源，为目标网站生成适配渠道的投放内容，并持续验证公开 URL 和推荐结果变化。

当前稳定合同由双 API、Admin/Customer Web、PostgreSQL Durable Job、MinIO 工件和 GEO Placement 领域组成。历史阶段实现不属于公共合同。

## 应用入口

| 应用 | 用途 | 开发地址 |
|---|---|---|
| Admin Web | 项目配置、证据治理、GEO 投放、审核和 Development Board | `http://localhost:3001` |
| Customer Web | 客户只读仪表盘、报告、投放结果和溯源 | `http://localhost:3000` |
| Internal API | 内部管理和工程接口 | `http://localhost:8000` |
| Customer API | 客户最小权限投影 | `http://localhost:8001` |

## 开发启动

环境要求：Docker Compose、uv、Node.js 22 和 Corepack。

```bash
make install
test -f deepseek_api_key.txt
chmod 600 deepseek_api_key.txt
make dev-up
```

`make dev-up` 会构建并启动 PostgreSQL、迁移、MinIO、Valkey、双 API、Durable Worker 和双 Web。查看日志使用 `make dev-logs`，停止使用 `make dev-down`。进行客户演示或生产验收前，仍必须使用独立生产配置并完成空库迁移、Secret、DeepSeek 和浏览器全流程门禁。

## 质量检查

```bash
uv run ruff check apps/api/geo_api packages/geo_core/geo_core
uv run pytest
corepack pnpm typecheck
corepack pnpm build
```

付费或对外模型调用不属于普通 PR 测试。DeepSeek 实际生成测试必须显式提供 Key，并保存 Prompt Bundle、Evidence Pack、模型调用日志和生成结果。

## 项目结构

```text
apps/
  api/             Internal API 与 Customer API
  admin-web/       内部管理端
  customer-web/    客户门户
packages/
  geo_core/        领域、应用服务、Port 和 Adapter
  web/             共享 auth、types、API client 和 UI
workers/           Durable Job 执行入口
infra/
  db/              Alembic 数据库基线与迁移
  compose.prod.yml 独立生产部署
contracts/         两套 OpenAPI 及生成合同
tests/             单元、集成、架构、浏览器和 live 测试
docs/              架构、运行手册、ADR、工程治理与历史归档
```

详细边界见 [文档索引](docs/README.md) 和 [系统架构](docs/architecture/system-overview.md)。

## 核心约束

- Router 只能调用 Application Service，Domain 不依赖 FastAPI、psycopg、HTTP 或环境变量。
- PostgreSQL 是业务状态和 Durable Job 真源；Valkey/Dramatiq 只负责唤醒。
- 项目数据同时由复合外键和 RLS 隔离，不能把 RLS 当作关系完整性替代品。
- Prompt/Skill 可独立发布；每次生成冻结 Prompt Bundle、Evidence Pack、模型策略和调用预算。
- Export、Delivery、Publication Request、Submission 和 Verification 是不同事件。
- Customer API 不注册内部路由，Dev Tools 在关闭时必须是 404。
- 通用 HTTP 日志不保存正文；敏感业务操作使用显式 AuditEvent。

## 生产与备份

生产环境使用 [独立 Compose](infra/compose.prod.yml)，不得叠加开发 Compose。配置方法见 [生产运行手册](docs/operations/production-runbook.md)。

```bash
docker compose --env-file infra/production.env -f infra/compose.prod.yml config
docker compose --env-file infra/production.env -f infra/compose.prod.yml up -d
```

备份采用每日 PostgreSQL dump 和 MinIO 镜像，保留 7 个日备和 4 个周备，并定期执行隔离恢复冒烟。详见 [备份与恢复](docs/operations/backup-restore.md)。
