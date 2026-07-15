# `codex/phase0-integration` 集成计划

本分支由当前主 session 操作，不交给任一功能 worktree 的 Codex。

## 目标

在干净、独立的集成 worktree 中合并：

```text
codex/storage-hardening
codex/durable-leases
codex/auth-core
codex/auth-web
```

然后统一完成 Compose、Makefile、Production Final Gate、OpenAPI/generated types、migration、RLS、Docker 和前端 live E2E 接线。

## 合并前置

每个功能分支都必须：

- 基于 `codex/parallel-base-20260712`；
- 至少有一个实现提交；
- 工作区干净；
- 存在并已提交自己的 `docs/worktree-results/*.md`；
- 不包含 secret、`tmp/` artifact、本地 env 或其他分支的 merge。

阅读四份 handoff 后再 merge。如果 handoff 声称的测试和实际 commit 不一致，先退回功能 worktree 修正，不在集成分支替它隐藏缺口。

## 合并顺序

```bash
git merge --no-ff codex/storage-hardening
git merge --no-ff codex/durable-leases
git merge --no-ff codex/auth-core
git merge --no-ff codex/auth-web
```

不用 `-X ours/-X theirs`，不对冲突文件整体 checkout 一侧。逐段核对语义后解决。

## 集成分支独占文件

```text
Makefile
scripts/verify_production_v1_gate.py
tests/test_production_v1_gate_contracts.py
```

合并后可按所有权规则对以下共享文件做小范围联调：

```text
infra/docker-compose.yml
infra/docker-compose.production.yml
apps/api/geo_api/main.py
apps/*/app/runtime.ts
```

不做无关重构。

## 跨分支接线

### Compose 与 Secrets

以 storage 分支的 production overlay/root-app-backup 隔离为真源，在不破坏 external secret/_FILE 模型的前提下增加：

- Knowledge/Collection lease duration、heartbeat interval、recovery interval/batch/slots、worker time limit；
- `GEO_AUTH_DELIVERY_MASTER_KEY/GEO_AUTH_DELIVERY_KEY_ID`，只进 API/Auth cleanup consumer；
- `GEO_AUTH_RECOVERY_COOKIE_SECRET`，只进 Admin/Customer BFF；
- Auth rollback write kill switch 和专用 DB role/privilege 路径；
- `0029 -> 0030` migration 顺序；
- Auth cleanup job 和逐表公平 recovery dispatcher。

non-consumer 不得因合并获得 object-store/Auth secret。merged config/artifact 不记录 raw secret。

### Makefile

增加独立 targets：

```text
test-production-object-store
test-durable-leases
test-auth-core
test-auth-web
smoke-production-object-store
smoke-durable-lease-recovery
smoke-auth-session-v2
```

再把它们纳入 Base / Content v0 Gate，但不允许 source-string-only 测试替代 DB/live 检查。

### Production Final Gate

总 Gate 注册并验证：

```text
tmp/production-object-store-credentials/latest.json
tmp/durable-job-lease-recovery/latest.json
tmp/auth-invitation-surface/latest.json
tmp/auth-session-project-scope/latest.json
```

每份 artifact 都必须 status pass、commit 匹配、时间新鲜、input/output hash 有效。不得使用旧 artifact 或 `--skip-live` 声称 production pass。

### Auth Wire/OpenAPI

- 以 auth-core OpenAPI 为语义真源，与冻结 wire contract 对账。
- 重新生成 Admin/Customer TypeScript DTO，不手工维护两套差异定义。
- 对账 route、enum、stable error、Cookie 和 surface projection。
- 后端对 `accepted_by` 严格 422，前端不发该字段。

## Migration/RLS 验收

1. 空库从 `0001` 到 `0030` 安装。
2. 从真实 `0028` 基线升级 `0029/0030`。
3. 注入大小写重复、role 冲突、pending Invitation 冲突、active lease、v1 Session 的 dirty upgrade。
4. 验证 count/hash 对账、人工队列、Session revoke 和无自动提权。
5. 真实 app role + FORCE RLS 执行 CRUD 正向/跨 project/跨 tenant negative。
6. 验证 FK 引用侧索引、partial index 和 `EXPLAIN` 路径。
7. 演练 lease rollback drain 和 Auth old-binary/new-schema 双层禁写。

## 最终测试

基础：

```bash
python3 -m compileall apps/api/geo_api packages/geo_core/geo_core workers scripts tests
npm --prefix apps/admin-web run typecheck
npm --prefix apps/customer-web run typecheck
npm --prefix apps/admin-web run build
npm --prefix apps/customer-web run build
git diff --check
```

Python 全量：

```bash
PYTHONPATH=packages/geo_core:apps/api python3 -m unittest discover -s tests
```

按四份 handoff 运行专项 unit/PG/live 命令，然后运行：

```bash
docker compose --profile "*" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.production.yml \
  config --format json

PYTHONPATH=packages/geo_core:apps/api \
  python3 scripts/verify_production_v1_gate.py checklist
```

还必须完成：

- non-default embedded MinIO live put/get/head/hash、policy negative、backup/restore；
- Knowledge/Collection actor/container kill + fair reclaim；
- Auth PostgreSQL concurrency/RLS/response-loss replay；
- Admin/Customer Playwright desktop/mobile、wrong-surface、lost-response、mixed-role selector；
- 日志、Compose artifact、浏览器 payload 的 secret/token 泄漏扫描。

## 完成标准

- 四个功能分支的 handoff 全部对账；
- 没有未解决冲突、未提交修改、secret 或过期 artifact；
- 四个独立 Gate 和 Base Gate 全部 Green；
- 新增一份 `docs/worktree-results/phase0-integration.md`，记录 merge commit、所有测试、artifact hash、剩余风险和回滚步骤；
- 设计文档仍保持 `Draft for Review`，直到真实生产 Gate 证据齐全且必需评审人签署。

## 与当前 `main` 对账

当前 `main` 工作区仍保留原始未提交改动。集成完成后，先向用户报告 `codex/phase0-integration` 的最终 SHA 和与主工作区的 tree diff。不对当前 `main` 执行 reset/checkout/clean；只在确认主工作区处理方式后才推进 main。
