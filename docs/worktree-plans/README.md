# Phase 0 并行 Worktree 协调说明

## 基线

当前 `main` 指向 `edc7dba`，但主工作区中已有大量未提交的 API、worker、Compose、前端和测试改动。所有并行分支必须从 `codex/parallel-base-20260712` 创建，不得从裸 `main` 创建。

`codex/parallel-base-20260712` 是当前工作区的独立快照提交。它不移动 `main`、不清理主工作区、不改动主工作区 index。

## 分支与责任

| 分支 | 任务书 | 主要所有权 |
| --- | --- | --- |
| `codex/storage-hardening` | `docs/worktree-plans/storage-hardening.md` | MinIO、对象存储客户端、production overlay、backup/restore |
| `codex/durable-leases` | `docs/worktree-plans/durable-leases.md` | `0029`、Knowledge/Collection lease、LeaseGuard、recovery dispatcher |
| `codex/auth-core` | `docs/worktree-plans/auth-core.md` | `0030`、Invitation/Member/Grant/Session v2、Auth API/RLS |
| `codex/auth-web` | `docs/worktree-plans/auth-web.md` | Admin/Customer 登录 BFF、recovery cookie、surface project selector |
| `codex/phase0-integration` | `docs/worktree-plans/integration.md` | 合并、总 Gate、Makefile、跨分支联调与最终验收 |

## 冲突预防

以下热点文件由集成分支独占，功能分支不得修改：

- `Makefile`
- `scripts/verify_production_v1_gate.py`
- `tests/test_production_v1_gate_contracts.py`
- `docs/GEO-文案生成系统设计方案v1_0.md`

`infra/docker-compose.yml` 和 `infra/docker-compose.production.yml` 由 storage 分支优先拥有。lease/auth 分支若需要新环境变量或服务接线，必须写入自己的 handoff，由集成分支统一加入 Compose。

数据库 migration 编号冻结：

- `0029_durable_job_lease_recovery.sql`：只属于 `codex/durable-leases`。
- `0030_auth_session_scope_v2.sql`：只属于 `codex/auth-core`。

功能分支优先新增专用测试文件，不把大量新断言堆入共享的超大 contract test。

## 所有 Codex 的通用规则

1. 开始时完整阅读本文件、自己的任务书和设计方案中被引用的章节。
2. 不要 merge、rebase、cherry-pick 其他功能分支；不要改分支名。
3. 只修改任务书授权的文件。若必须跨界，不直接修改，而是在 handoff 中写出精确变更建议。
4. 不得回退基线中已有改动，不得用“顺手重构”扩大范围。
5. 不在外部模型/子进程/网络调用期间持有数据库锁。
6. PostgreSQL queue 使用短事务和 `FOR UPDATE SKIP LOCKED`；RLS 必须 `ENABLE` + `FORCE`，关联完整性不能只靠 RLS。
7. 新 FK 必须有引用侧索引；高频状态查询使用与 predicate 一致的 composite/partial index。
8. 不提交 secret、真实凭据、`tmp/` 运行产物、本地 env 文件或生成缓存。
9. 必须执行任务书中的测试；无法执行的 live 测试要如实写入 handoff，不能用 source-string test 冒充。
10. 完成后将所有实现和专属 handoff 提交到当前分支，并保持 `git status --short` 为空。

## Handoff 合同

每个功能分支在完成时新增并提交：

```text
docs/worktree-results/<task-name>.md
```

handoff 至少记录：

- 最终 commit SHA 和提交列表；
- 改动文件；
- 数据库/状态/API/环境变量合同；
- 已执行测试及结果；
- 未执行的 live 测试及原因；
- 需要集成分支完成的 Compose/Makefile/Gate/OpenAPI 接线；
- 已知风险和回滚注意事项。

## 集成顺序

`codex/phase0-integration` 由当前主 session 操作，默认顺序：

1. `codex/storage-hardening`
2. `codex/durable-leases`
3. `codex/auth-core`
4. `codex/auth-web`
5. 阅读四份 handoff，补 Compose/Makefile/总 Gate/OpenAPI 接线。
6. 运行全量 contract、migration、RLS、Docker、frontend 和 live smoke。

不在当前脏 `main` 工作区直接 merge。先在干净的 `codex/phase0-integration` 中完成集成和验收，再决定如何与 `main` 对账。
