# `codex/durable-leases` 执行计划

## 目标

完成设计方案 §14.4 和 `CG-PROD-009`：

- Knowledge 8 类 Job 和 `collection_jobs` 能接管过期 `running/finalizing` 租约；
- heartbeat、随机 fencing token、cancel 线性化、retry 和 DLQ 闭合；
- Knowledge 使用 expired-first、逐表公平 recovery pass；
- `knowledge_pipeline_runs` 仍只从 `queued` 启动，不参与子 Job reclaim；
- 旧 worker、过期 token 或 cancel 后 worker 不能提交结果；
- Collection 阻塞子进程可续租、可终止；
- 真实 PostgreSQL 并发及 actor/container kill 测试生成 `tmp/durable-job-lease-recovery/latest.json`。

## 文件所有权

可修改：

```text
infra/db/migrations/up/0029_durable_job_lease_recovery.sql
infra/db/migrations/down/0029_durable_job_lease_recovery.down.sql
packages/geno_core/geno_core/durable_jobs.py                    # 新增
packages/geno_core/geno_core/knowledge_pipeline.py
packages/geno_core/geno_core/collection_jobs.py
workers/knowledge_worker/run_knowledge_pipeline.py
workers/collector_worker/run_collection_slice.py
workers/task_queue/tasks.py
workers/task_queue/run_recovery_dispatcher.py
apps/api/geno_api/runtime_metrics.py                            # 按需新增
scripts/verify_durable_job_lease_recovery.py                    # 新增
tests/test_durable_job_lease_contracts.py                       # 新增
tests/test_durable_job_lease_postgres.py                        # 新增
tests/test_knowledge_pipeline_contracts.py
tests/test_production_runtime_contracts.py
infra/docker-compose.durable-leases.test.yml                    # 只用于 live test
```

禁止修改：

- `infra/docker-compose.yml`、`infra/docker-compose.production.yml`；
- `Makefile`、总 Gate 脚本和总 Gate 测试；
- Auth/API 主入口、前端、对象存储模块；
- `0001` 至 `0028` migration 及 `0030` 以后 migration；
- 设计方案和其他 worktree plan。

Compose/Makefile/总 Gate 接线写入 handoff，由集成 session 完成。

## 1. `0029` Schema

覆盖：

```text
knowledge_import_jobs
crawl_jobs
knowledge_parser_runs
chunk_jobs
embedding_jobs
fact_extraction_jobs
prompt_generation_jobs
content_generation_jobs
collection_jobs
```

Knowledge 增加：

```text
lease_token uuid
lease_reclaimed_count integer NOT NULL DEFAULT 0
last_reclaimed_at timestamptz
last_reclaimed_from text
dead_lettered_at timestamptz
cancel_requested_at timestamptz
```

Collection 还必须增加 `heartbeat_at`。需要恢复 artifact finalize 时，将幂等恢复描述符持久化，不只放进程内存。

逐表重建 status CHECK，必须保留各表现有合法状态：

- Import 保留 `draft/ready`；
- Parser 保留 `fallback_succeeded`；
- 合法 batch Knowledge 和 Collection 保留 `partial_succeeded`；
- 单 Asset Content Generation 禁止 `partial_succeeded`。

全部追加 `retry_wait/dead_letter`，有 artifact finalize 的表追加 `finalizing`。不得用一个全局 status 枚举覆盖各表原有合同。

active-lease CHECK：`running/finalizing` 时 `locked_by/locked_at/lease_token/lease_expires_at/heartbeat_at` 全部非空。

迁移前提是旧 consumer 已 drain。遗留 active row：

- cancel requested -> `cancelled`；
- attempt 未耗尽 -> `retry_wait`；
- attempt 已耗尽 -> `dead_letter`。

Partial index 必须与实际 predicate 一致，predicate 中不能使用 `now()`：

```text
Knowledge fresh:   (next_run_at, priority DESC, created_at)
Knowledge expired: (lease_expires_at, priority DESC, created_at)
Collection fresh:  (next_attempt_at, created_at)
Collection expired:(lease_expires_at, created_at)
```

down migration 必须先拒绝仍有 active token owner 的回滚，再将新状态映射为旧 binary 可识别状态，最后撤销约束/索引/新列。

## 2. 共享租约组件

`durable_jobs.py` 至少包含：

```text
DurableJobSpec
LeaseClaim
LeaseGuard
LostLeaseError
ClaimOutcome
```

`DurableJobSpec` 使用静态 table allowlist，不得从 API/payload 插入表名。

Claim/reclaim 使用单个短事务和 `FOR UPDATE SKIP LOCKED`：

- fresh：`queued/retry_wait`、已到期、attempt 未耗尽、未 cancel；
- recovery：租约过期的 `running/finalizing`；
- 每次 claim 都产生新 UUID token；
- 只有 reclaim 增加 reclaimed count；
- expired `finalizing` 保持 `finalizing`；
- attempt 耗尽直接 DLQ；
- cancel-requested expired row 直接 cancelled；
- 只用 PostgreSQL `now()`；
- 外部模型/crawler/subprocess 期间不持有行锁。

Heartbeat 返回 `id/cancel_requested_at/lease_expires_at`。Heartbeat、complete、fail、finalize 全部以 `id + status + locked_by + lease_token + unexpired lease` 做 CAS；terminal promotion 另要求 `cancel_requested_at IS NULL`。0-row 抛 `LostLeaseError`并丢弃本地结果。

token 只进入内部 DTO/LeaseGuard，不进 API、普通日志或 artifact；audit 只写 fingerprint。

## 3. Knowledge Worker

1. 每个 interval 先对 8 张表各执行至少一个 expired recovery slot。
2. recovery slot 不被 fresh `max_jobs` 消耗。
3. fresh claim 按持久化 round-robin cursor 分配。
4. 前序表持续 fresh backlog 时，后序表 expired row 仍在两个 interval 内接管。
5. `run_ready_pipeline_once()` 保持 queued-only。

LeaseGuard 使用独立 PostgreSQL connection，设置与 owner 相同的 maintenance/RLS context，间隔不超过 `lease_seconds / 3`。

handler 提交结果的短事务必须先验证 token。MinIO/Qdrant 副作用使用 attempt-scoped key 或自然键/content hash 幂等。Content Job 模型结果持久化即 `succeeded`，QA blocked 不写 Job `partial_succeeded`。

## 4. Collection Worker

- 实现同样的 claim/reclaim/heartbeat/CAS/cancel/DLQ。
- retryable -> `retry_wait`，non-retryable -> `failed`，attempt 耗尽 -> `dead_letter`。
- queued/retry_wait cancel 直接 terminal；active cancel 只设 request。
- complete 和 cancel 只能有一方线性化成功。
- 将 `subprocess.run()` 改为可轮询 `Popen`；LeaseGuard 后台续租。
- lost lease/cancel 时 terminate，超时后 kill；stdout/stderr 不得因 pipe 填满死锁。
- child subprocess 异常进正常 retry/DLQ，不得冒充 actor crash 测试。
- 保留 Answer/Raw/Citation 稳定 ID 和 `ON CONFLICT` 幂等。

## 5. 指标与 Verifier

按 queue/job type 输出无敏感聚合值：

```text
queue depth / oldest queued age
expired active count / oldest expired age
reclaimed / dead-letter / lease-lost / stale completion
heartbeat success/failure / cancelled
recovery cursor / recovery slots used / worker heartbeat age
```

recovery dispatcher 只做逐表公平 wakeup/recovery pass 和指标，不得批量把 expired row 重置为 queued。

Verifier 生成 `tmp/durable-job-lease-recovery/latest.json`，包含标准 run/commit/input/output hash 和逐项检查，不提交运行产物。

## 6. 测试要求

单元/合同：

- 逐表状态保留，Content 禁止 `partial_succeeded`；
- active-lease CHECK 和 partial index；
- fresh active 不可领，expired running/finalizing 可接管；
- heartbeat 返回 cancel；旧 token 的所有 CAS 为 0-row；
- cancel/terminal 竞态只有一个终态；
- attempt 上限 DLQ；
- pipeline aggregate 不 reclaim；
- token 不进 API/list/log/artifact。

真实 PostgreSQL：

- 两独立连接 + Barrier 竞争同一 expired row，只有一个 owner；
- token 旋转且 attempt 只 +1；
- 前序表持续 fresh backlog + 受限 `max_jobs`，后序表无 starvation；
- `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` 证明 fresh/recovery 使用对应 partial index。

Live：

- after-claim failpoint 只在 test environment 启用；
- kill 实际 Knowledge worker/container 和 Collection Dramatiq actor/container；
- DB 保留 running，到期后重启，token 在 2 interval 内转移；
- 另测只 kill Collection child subprocess 进正常 fail/retry。

## 7. 执行命令

```bash
export PYTHONPATH="$PWD/packages/geno_core:$PWD/apps/api:$PWD"

python3 -m pytest -q \
  tests/test_durable_job_lease_contracts.py \
  tests/test_knowledge_pipeline_contracts.py \
  tests/test_production_runtime_contracts.py
```

真实 DB：

```bash
export COMPOSE_PROJECT_NAME=geo-durable-leases
export GENO_POSTGRES_HOST_PORT=55432

docker compose \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.durable-leases.test.yml \
  up -d postgres valkey db-migrate

GENO_DURABLE_JOB_TEST_DATABASE_URL=postgresql://geno:geno@127.0.0.1:55432/geno \
python3 -m pytest -q tests/test_durable_job_lease_postgres.py
```

Live actor kill：

```bash
docker compose \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.durable-leases.test.yml \
  up -d --build task-worker-runtime task-worker-knowledge task-recovery-dispatcher

python3 scripts/verify_durable_job_lease_recovery.py \
  --database-url postgresql://geno:geno@127.0.0.1:55432/geno \
  --compose-project geo-durable-leases \
  --artifact-path tmp/durable-job-lease-recovery/latest.json \
  --run-actor-kill-tests

python3 -m compileall packages/geno_core/geno_core workers scripts tests
git diff --check
```

## 提交与 Handoff

一个或多个聚焦提交，最终信息建议：

```text
fix(jobs): recover expired durable job leases
```

新增并提交 `docs/worktree-results/durable-leases.md`，列出集成 session 需添加到 Compose 的 lease/heartbeat/recovery env、Makefile targets、总 Gate artifact 检查和 Prometheus/Grafana alerts。

