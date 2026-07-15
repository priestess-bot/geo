# 代码质量与测试

## Python

使用 Python 3.12 和 uv。依赖只在 `pyproject.toml`/`uv.lock` 管理，旧 requirements 仅在镜像迁移期间临时保留。

```bash
uv sync
uv run ruff check apps/api/geo_api packages/geo_core/geo_core
uv run mypy apps/api/geo_api packages/geo_core/geo_core
uv run pytest
```

新增模块必须通过 Ruff 和 mypy；旧模块按迁移切片逐步纳入严格检查。测试分为 unit、integration、browser、live。真实 PostgreSQL 集成测试在 CI 中不能静默跳过；DeepSeek live 测试不在普通 PR 执行。

## 前端

前端使用单一 pnpm workspace 和根 lockfile。

```bash
corepack pnpm install --frozen-lockfile
corepack pnpm typecheck
corepack pnpm build
```

Admin 路由最多读取 5 个领域资源，Customer 模块最多 2 个或一个组合投影。Customer 代码不得导入 internal types/client。

## 架构门禁

- API 新模块不能导入 `scripts`、`workers` 或 legacy `main`。
- Domain 不能导入 FastAPI、psycopg、httpx 或环境变量。
- Repository 不能调用 commit、模型、HTTP 或对象存储。
- 非归档源码不得出现旧产品名或阶段路径。
- 新增/修改行覆盖率至少 90%；认证、RLS、任务和投放状态机分支覆盖率至少 90%。

公共类型、Port、状态转换和安全不变量需要简洁 docstring。普通赋值、显然的 UI 结构和自解释代码不添加叙述性注释。
