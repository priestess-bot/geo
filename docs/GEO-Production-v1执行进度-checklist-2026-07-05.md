# GEO Production v1 执行进度 Checklist

生成日期：2026-07-05

对照规划：[GEO-Production-v1完整规划-2026-07-05.md](./GEO-Production-v1完整规划-2026-07-05.md)

测试流程：[GEO-可复用测试流程-2026-07-06.md](./GEO-可复用测试流程-2026-07-06.md)

本 checklist 是执行进度唯一看板。后续每完成一个工作包，必须更新状态、验收命令、证据路径和 commit hash。

状态口径：

| 状态 | 含义 |
| --- | --- |
| Not started | 尚未开始 |
| In progress | 已开始实现 |
| Blocked | 被外部凭据、环境或上游任务阻塞 |
| Verifying | 实现已完成，正在跑验收 |
| Done | 代码、测试、证据和提交均完成 |
| Deferred upgrade | 明确不属于本次 Production v1 完成门槛，只保留扩展边界 |

## 1. 本次完成门槛

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C00 | 13 / 14 / 20 | 建立本 checklist 与 gate 骨架 | 无 | Done | `make test` | 本文件；`scripts/verify_production_v1_gate.py` | 待填 | 第一批工作包 |
| C01 | 0 / 1 / 5 | 生产路径禁止 demo/fixture fallback | C00 | Done | `make no-fixture-production-smoke` | `scripts/verify_production_v1_gate.py`; focused unittest suite | 待填 | 生产默认路径改为真实 API/手工补录；fixture 端点仅开发工具开关可用 |
| C02 | 13 / 15 | provider key、session token、invite token 不泄露 | C00 | Done | `python3 scripts/verify_production_v1_gate.py security-smoke`; focused auth/session tests | `scripts/verify_production_v1_gate.py`; `tests/test_api_contracts.py`; `apps/api/geno_api/main.py` | 待填 | security-smoke 已无 pending；Provider secret storage 专项仍在 W3-I00 |
| C03 | 14 | Production v1 E2E 从空环境跑通 | C01-C18 | Done | `PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_production_v1_gate.py production-v1-e2e` | `scripts/verify_runtime_e2e.py`; `scripts/verify_production_v1_gate.py`; `packages/geno_core/geno_core/action_plan.py`; `tests/test_core_contracts.py`; `docs/GEO-Production-v1执行进度-checklist-2026-07-05.md` | 待填 | 真实报告生产闭环 gate 已 23 pass / 0 pending；真实 provider 子集在 staging/production-internal 仍需外部 key |
| C04 | 14 | Enablement v1 E2E 跑通 | C19-C21 | Done | `PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_production_v1_gate.py enablement-v1-e2e` | `packages/geno_core/geno_core/knowledge.py`; `packages/geno_core/geno_core/repository.py`; `apps/api/geno_api/main.py`; `tests/test_core_contracts.py`; `tests/test_api_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | KB/Content/Distribution 薄闭环 gate 已 20 pass / 0 pending；自动发布和额外平台保留为升级项 |
| C05 | 20 | Final Gate 全部通过 | C01-C24 | Done | `make production-v1-final-gate` | `Makefile`; `scripts/verify_production_v1_gate.py`; Docker `db-smoke` / `runtime-e2e` 输出 | 待填 | 最终验收已通过 |

## 2. Foundation

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W10-I01 | 16 / 14 | `production-v1-e2e` 骨架 | 无 | Done | `make production-v1-e2e` | `scripts/verify_production_v1_gate.py` | 待填 | 严格模式按 pending 失败，进度模式可观察未完成项 |
| W1-I03 | 16 | 清除生产路径 demo fallback | W10-I01 | Done | `make no-fixture-production-smoke` | `scripts/verify_production_v1_gate.py`; `tests/test_admin_customer_web_contracts.py`; `tests/test_infra_contracts.py`; `tests/test_api_contracts.py`; `tests/test_worker_cli.py` | 待填 | 新建项目/启动配置/worker 默认真实 API；fixture collection/report 仅开发工具开关可用 |
| W1-I01 | 16 / 6 | FastAPI domain route 边界 | W10-I01 | Done | `python3 -m compileall apps/api/geno_api`; focused API/router tests | `apps/api/geno_api/ops_routes.py`; `tests/test_infra_contracts.py` | 待填 | 建立 ops domain router 模式；后续 domain router 按此迁移 |
| W1-I02 | 16 / 6 | Repository 拆分边界 | W1-I01 | Done | `PYTHONPATH=packages/geno_core:apps/api python3 -m unittest tests.test_repository_boundaries`; `make test` | `packages/geno_core/geno_core/repositories/*`; `tests/test_repository_boundaries.py` | 待填 | 已冻结 audit/project/access_control repository 边界并验证现有 `PostgresEvidenceRepository` 兼容；后续物理拆分按该契约迁移 |

## 3. Identity / Access

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W2-I01a | 16 / 7.1 | AuthContext contract/types/dependency | W1-I01 | Done | `python3 -m compileall apps/api/geno_api`; `make security-smoke --allow-pending` equivalent; focused auth tests | `apps/api/geno_api/auth_context.py`; `tests/test_auth_context_contracts.py` | 待填 | header/jwt/jwks actor 已统一到 AuthContext；session/RBAC rollout 由后续项完成 |
| W2-I01b | 16 | sessions table + session repository | W2-I01a | Done | `python3 -m compileall packages/geno_core/geno_core apps/api/geno_api scripts/verify_db_smoke.py`; focused session tests | `infra/db/migrations/up/0016_runtime_sessions.sql`; `packages/geno_core/geno_core/runtime_project_access_repository.py`; `tests/test_core_contracts.py` | 待填 | server-side session hash、TTL、validate、revoke 基线完成；cookie/API rollout 后续完成 |
| W2-I01c | 16 | protected API dependency rollout | W2-I01a/W2-I01b/W2-I03a/W2-I03b | Done | `python3 -m unittest tests.test_auth_context_contracts`; `make security-smoke --allow-pending` equivalent | `apps/api/geno_api/main.py`; `tests/test_auth_context_contracts.py` | 待填 | protected API 依赖已支持 session AuthContext 与 project scope；邀请兑换设置 cookie 由 W2-I02 完成 |
| W2-I01d | 16 | system actor contract | W2-I01a | Done | `python3 -m unittest tests.test_auth_context_contracts`; `make security-smoke --allow-pending` equivalent | `apps/api/geno_api/auth_context.py`; `tests/test_auth_context_contracts.py` | 待填 | system actor 默认必须带 tenant/project scope 与 explicit permissions；maintenance 需显式 `allow_unscoped` |
| W2-I01e | 16 / 7.11 | auth audit events | W2-I01a | Done | `python3 -m unittest tests.test_core_contracts.CoreContractsTest.test_auth_audit_event_vocabulary_rejects_raw_secret_refs`; `make security-smoke --allow-pending` equivalent | `packages/geno_core/geno_core/audit.py`; `tests/test_core_contracts.py` | 待填 | auth/authz/invitation/system_actor 事件词表完成，禁止 raw token/secret refs |
| W2-I02 | 16 | Invitation token 一次性兑换 | W2-I01a/W2-I01b/W2-I03a/W2-I03b | Done | focused auth/session unittest suite; `python3 scripts/verify_production_v1_gate.py security-smoke` | `apps/api/geno_api/main.py`; `tests/test_api_contracts.py` | 待填 | `/v1/auth/invitations/redeem` 创建一次性 httpOnly session cookie 与 CSRF cookie；`/v1/auth/me` 与 CSRF-protected `/v1/auth/logout` 完成 |
| W2-I03a | 16 / 7.2 | RBAC matrix contract | W2-I01a | Done | `python3 -m unittest tests.test_rbac_contracts`; `make security-smoke --allow-pending` equivalent | `packages/geno_core/geno_core/rbac.py`; `tests/test_rbac_contracts.py` | 待填 | permission vocabulary 与 role matrix 已成为核心契约；路由全面接入由 W2-I01c 完成 |
| W2-I03b | 16 | membership schema + scope repository | W2-I01b/W2-I03a | Done | `python3 -m unittest tests.test_membership_scope_contracts`; `make security-smoke --allow-pending` equivalent | `infra/db/migrations/up/0017_tenant_membership_scope.sql`; `packages/geno_core/geno_core/runtime_project_access_repository.py`; `tests/test_membership_scope_contracts.py` | 待填 | `tenant_members` 与 scope repository 完成；RLS `app.*` 升级由 W2-I03c 完成 |
| W2-I03c | 16 / 8.2 | RLS smoke for core tables | W2-I03b | Done | `python3 scripts/verify_production_v1_gate.py security-smoke`; `make rls-smoke` equivalent | `infra/db/migrations/up/0010_runtime_project_rls.sql`; `scripts/verify_db_smoke.py`; `packages/geno_core/geno_core/repository.py` | 待填 | RLS helper 优先读取 `app.actor_id/app.project_id/app.project_ids/app.roles`，旧 `geno.runtime_*` 保留 fallback |

## 4. Collection / Evidence

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W3-I00 | 16 / 2.5 | Provider secret storage and redaction baseline | W2-I01a/W2-I03a | Done | `python3 scripts/verify_production_v1_gate.py no-secret-leak-smoke --allow-pending`; focused secret/API tests | `infra/db/migrations/up/0018_connector_secret_refs.sql`; `packages/geno_core/geno_core/security/secrets.py`; `apps/api/geno_api/main.py`; `tests/test_api_contracts.py`; `tests/test_core_contracts.py` | `17ab1d1` | DB encrypted column + SecretStore adapter + API masked metadata + access-log body redaction |
| W3-I01 | 16 / 7.3 | Connector contract + recorded harness | W1-I01/W3-I00 | Done | `PYTHONPATH=packages/geno_core:apps/api python3 -m unittest tests.test_connector_contracts`; `python3 scripts/verify_production_v1_gate.py connector-real-smoke` | `packages/geno_core/geno_core/connector_contract.py`; `tests/test_connector_contracts.py`; `scripts/verify_production_v1_gate.py` | `f0c889e` | Local/CI 无 key 可跳过真实子集；因现有 `contracts.py` 文件避免 import 冲突，实际契约落点为 `connector_contract.py` |
| W3-I02 | 16 | OpenAI 真实采集闭环 | W3-I01/W4-I01a | Done | focused OpenAI connector tests; `python3 scripts/verify_production_v1_gate.py connector-real-smoke` | `packages/geno_core/geno_core/collectors.py`; `packages/geno_core/geno_core/production_connectors.py`; `tests/test_connector_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Responses API web_search collector is exposed through `ProductionConnectorBackend`; success/citation/cost/failure classification covered with fake HTTP client |
| W3-I03 | 16 | Perplexity 真实采集闭环 | W3-I00/W3-I01/W4-I01a | Done | focused Perplexity connector tests; `python3 scripts/verify_production_v1_gate.py connector-real-smoke` | `packages/geno_core/geno_core/collectors.py`; `packages/geno_core/geno_core/production_connectors.py`; `tests/test_connector_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Sonar collector is exposed through `ProductionConnectorBackend`; normalized citation/title/cost/provider_request_id/rate-limit failure covered |
| W3-I04 | 16 | Google manual backfill 生产路径 | W4-I01a | Done | focused Google manual connector tests; `python3 scripts/verify_production_v1_gate.py connector-real-smoke` | `packages/geno_core/geno_core/production_connectors.py`; `tests/test_connector_contracts.py`; `apps/api/geno_api/main.py`; `scripts/verify_production_v1_gate.py` | 待填 | Official P0 Google path is manual JSONL/API backfill；browser/SERP remains Go/No-Go and does not block this delivery |
| W4-I01a | 16 / 7.4 | EvidenceAsset schema + repository | W2-I01a | Done | focused evidence repository tests; `python3 scripts/verify_production_v1_gate.py report-traceability-smoke` | `infra/db/migrations/up/0019_evidence_asset_metadata.sql`; `packages/geno_core/geno_core/models.py`; `packages/geno_core/geno_core/repository.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | `1bc137e` | Additive metadata/hash/scope/visibility schema；raw evidence save path writes scoped assets and evidence links |
| W4-I01b | 16 / 2.5 | S3-compatible storage adapter | W4-I01a | Done | focused object store tests; `python3 scripts/verify_production_v1_gate.py report-traceability-smoke` | `packages/geno_core/geno_core/object_store.py`; `tests/test_core_contracts.py`; `infra/docker-compose.yml`; `tests/test_infra_contracts.py`; `scripts/verify_production_v1_gate.py` | `5dee9d4` | S3-compatible upload/download/hash check；archive helper returns `RuntimeEvidenceAssetInput`；MinIO local stack uses same interface |
| W4-I01c | 16 | EvidenceAsset permission proxy | W2-I03a/W4-I01a/W4-I01b | Done | focused evidence asset API tests; `python3 scripts/verify_production_v1_gate.py customer-access-negative-smoke` | `apps/api/geno_api/main.py`; `packages/geno_core/geno_core/repository.py`; `tests/test_api_contracts.py`; `scripts/verify_production_v1_gate.py` | `081422b` | Summary hides direct bucket URL；raw download uses API/object-store proxy；customer viewer and cross-project raw access denied |
| W4-I01d | 16 | Traceability chain smoke | W4-I01a | Done | focused traceability smoke test; `python3 scripts/verify_production_v1_gate.py report-traceability-smoke` | `packages/geno_core/geno_core/traceability.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Executable smoke verifies Report -> ScoreContribution -> AnswerAnalysis -> RawAnswer -> EvidenceAsset and fails on broken links |

## 5. Intelligence / Delivery

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W5-I01 | 16 / 7.9 | AnswerAnalysis baseline parser | W3-I02/W3-I03/W4-I01a | Done | focused analysis contract tests; `python3 scripts/verify_production_v1_gate.py report-traceability-smoke` | `packages/geno_core/geno_core/parser.py`; `packages/geno_core/geno_core/analysis_contract.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Existing deterministic parser is locked behind Production v1 output contract；human override preserves original parser output and writes `analysis.reviewed` audit |
| W5-I02a | 16 / 7.5 | Scoring profile schema + formula contract | W5-I01 | Done | focused scoring formula test; `python3 scripts/verify_production_v1_gate.py report-traceability-smoke` | `packages/geno_core/geno_core/scoring.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | `visibility_v1.0` is an exact active formula version with frozen weights and denominator rules；existing score_weight_configs remain compatible |
| W5-I02b | 16 | VisibilityScoreSnapshot calculator | W5-I02a | Done | focused score snapshot traceability test; `python3 scripts/verify_production_v1_gate.py report-traceability-smoke` | `packages/geno_core/geno_core/scoring.py`; `packages/geno_core/geno_core/analysis_pipeline.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Existing calculator now covered under `visibility_v1.0` aggregate snapshot path |
| W5-I02c | 16 | ScoreContribution traceability | W5-I02b/W4-I01d | Done | focused score contribution traceability test; `python3 scripts/verify_production_v1_gate.py report-traceability-smoke` | `packages/geno_core/geno_core/scoring.py`; `packages/geno_core/geno_core/traceability.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Every component contribution links to snapshot id and all evidence answer_run_ids；broken traceability fails smoke |
| W6-I01a | 16 / 7.6 | ReportExport schema + immutable repository | W4-I01d/W5-I02c/W2-I03a | Done | focused report export snapshot tests; `python3 scripts/verify_production_v1_gate.py report-traceability-smoke` | `packages/geno_core/geno_core/models.py`; `packages/geno_core/geno_core/repository.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | `ReportExport` immutable insert path is locked by `ON CONFLICT (id) DO NOTHING`; repeated export of the same snapshot yields stable report id and methodology hash |
| W6-I01b | 16 / 12 | Markdown/CSV generation from fixed snapshot | W6-I01a | Done | focused report export snapshot tests; `python3 scripts/verify_production_v1_gate.py report-traceability-smoke` | `packages/geno_core/geno_core/report.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Markdown and CSV are generated from the same frozen `ReportExport`/score snapshot and remain deterministic under repeated export |
| W6-I01c | 16 / 2.5 | PDF generation and asset storage | W6-I01b/W4-I01b | Done | focused report artifact archive tests; `python3 scripts/verify_production_v1_gate.py report-traceability-smoke` | `packages/geno_core/geno_core/report.py`; `packages/geno_core/geno_core/object_store.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | PDF bytes are generated from the same Markdown snapshot and all Markdown/PDF/CSV artifacts archive to S3-compatible storage with content hashes |
| W6-I01d | 16 | Approval/publish/revoke lifecycle | W6-I01a/W2-I03a | Done | focused report lifecycle tests; `python3 scripts/verify_production_v1_gate.py customer-access-negative-smoke` | `apps/api/geno_api/main.py`; `packages/geno_core/geno_core/repository.py`; `tests/test_api_contracts.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | API/Repository accept Production wording `approved/published/revoked` and normalize to existing management statuses `internal_review/client_ready/archived`; customer visibility still requires `client_ready` |
| W6-I01e | 16 | Customer report center + permissioned download | W6-I01c/W6-I01d/W4-I01c | Done | focused report artifact tests; `python3 scripts/verify_production_v1_gate.py customer-access-negative-smoke` | `apps/customer-web/app/portal/[module]/page.tsx`; `apps/customer-web/app/api/report-artifact/route.ts`; `apps/api/geno_api/main.py`; `tests/test_api_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Customer report center lists reports and exposes Markdown/CSV/PDF artifact links through portal proxy；API denies unpublished/revoked/cross-project access |
| W6-I01f | 16 | Report security tests | W6-I01e | Done | focused report artifact unittest suite; `python3 scripts/verify_production_v1_gate.py security-smoke` | `tests/test_api_contracts.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Report lifecycle alias tests, published allow test, unpublished/revoked/cross-project deny tests, and raw evidence/provider key gates all pass under security-smoke |

## 6. Optimization / Enablement

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W7-I01 | 16 | Action Plan 最小闭环 | W5-I02c/W6-I01f | Done | focused action plan P0 tests; `python3 scripts/verify_production_v1_gate.py production-v1-e2e --allow-pending` | `packages/geno_core/geno_core/action_plan.py`; `packages/geno_core/geno_core/models.py`; `packages/geno_core/geno_core/repository.py`; `infra/db/migrations/up/0020_action_recommendation_contract.sql`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Generates 3 deterministic P0 action types: brand not mentioned, competitor outranks brand, missing/weak citation source；actions default customer_visible=false and link to evidence plus score contributions |
| W7-I02 | 16 | Retest 最小闭环 | W7-I01/W3-I02/W3-I03/W5-I02c/W6-I01f | Done | focused retest P0 tests; `python3 scripts/verify_production_v1_gate.py production-v1-e2e --allow-pending` | `packages/geno_core/geno_core/action_plan.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Retest schedule reuses same prompt/answer-run set and comparison exposes before_score, after_score, delta, trend with audit event |
| W8-I01 | 16 | Knowledge Base 薄闭环 | W4-I01a/W2-I03a | Done | focused enablement tests; `PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_production_v1_gate.py enablement-v1-e2e` | `packages/geno_core/geno_core/knowledge.py`; `packages/geno_core/geno_core/repository.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Knowledge facts default to `approved`; runtime search and content engine loads filter out draft/archived facts |
| W8-I02 | 16 | Content Workbench 薄闭环 | W7-I01/W8-I01 | Done | focused enablement tests; `PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_production_v1_gate.py enablement-v1-e2e` | `packages/geno_core/geno_core/knowledge.py`; `apps/api/geno_api/main.py`; `packages/geno_core/geno_core/repository.py`; `tests/test_core_contracts.py`; `tests/test_api_contracts.py` | 待填 | Content drafts are generated from Action + approved knowledge + evidence and stay `pending_human_review` |
| W8-I03 | 16 | Distribution task 回填 | W8-I02/W7-I02 | Done | focused enablement tests; `PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_production_v1_gate.py enablement-v1-e2e` | `packages/geno_core/geno_core/knowledge.py`; `packages/geno_core/geno_core/models.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Distribution stays manual: records start `awaiting_url_backfill`, URL/proof can be backfilled, automatic publishing remains deferred |

## 7. Ops / QA

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W9-I01 | 16 / 2.5 | Observability 最小生产门禁 | W10-I01 | Done | `python3 scripts/verify_ops_smoke.py`; `python3 scripts/verify_production_v1_gate.py ops-smoke` | `apps/api/geno_api/ops_routes.py`; `apps/api/geno_api/runtime_metrics.py`; `infra/prometheus/prometheus.yml`; `infra/grafana/provisioning/datasources/prometheus.yml`; `infra/docker-compose.yml`; `scripts/verify_ops_smoke.py`; `scripts/verify_production_v1_gate.py` | 待填 | Health/ready/metrics endpoints, Prometheus/Grafana profile, runtime alert APIs and alert workers are covered by executable ops smoke |
| W9-I02 | 16 / 2.5 | Backup / restore 演练 | W4-I01a | Done | `python3 scripts/verify_backup_smoke.py`; `python3 scripts/verify_production_v1_gate.py backup-smoke` | `infra/docker-compose.yml`; `infra/db/migrations/up/0020_action_recommendation_contract.sql`; `scripts/verify_backup_smoke.py`; `scripts/verify_production_v1_gate.py`; `Makefile` | 待填 | Postgres/MinIO named volumes, latest additive migration, and backup manifest round-trip are covered by executable backup smoke |
| Q01 | 13.9 | customer negative access | W2/W4/W6 | Done | `python3 scripts/verify_production_v1_gate.py customer-access-negative-smoke` | `apps/api/geno_api/main.py`; `apps/customer-web/app/portal/[module]/page.tsx`; `tests/test_api_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | report artifact 的未发布/撤回/跨项目已覆盖；raw evidence customer/cross-project deny 已覆盖 |
| Q02 | 13.9 | no secret leak | W3/W6/W9 | Done | `python3 scripts/verify_production_v1_gate.py security-smoke` | `scripts/verify_production_v1_gate.py`; `tests/test_api_contracts.py`; `tests/test_core_contracts.py` | 待填 | auth/session/invite token、provider secret storage、access-log redaction、report artifact customer gating all pass |
| Q03 | 13.9 | report traceability | W4/W5/W6 | Done | `python3 scripts/verify_production_v1_gate.py report-traceability-smoke` | `packages/geno_core/geno_core/traceability.py`; `packages/geno_core/geno_core/report.py`; `tests/test_core_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | Executable smoke verifies Report -> ScoreContribution -> AnswerAnalysis -> RawAnswer -> EvidenceAsset; fixed snapshot report artifacts are now included in gate |

## 8. 本次不做完、但保留扩展边界的升级项

| 编号 | 对照章节 | 升级项 | 状态 | 本次要求 |
| --- | --- | --- | --- | --- |
| U01 | 2.3 / 2.7 | Gemini / Bing Copilot / Claude / DeepSeek / 豆包 / Kimi / 腾讯元宝 / 百度文小言等额外平台 | Deferred upgrade | 保留 connector adapter 边界，不进入本次验收 |
| U02 | 2.3 / 2.7 | 所有渠道自动发布 | Deferred upgrade | 本次只做 Distribution task 人工回填 |
| U03 | 2.3 / 2.7 | Neo4j / OpenSearch / ClickHouse 高级图谱 | Deferred upgrade | 本次使用 Postgres/现有 graph baseline |
| U04 | 2.3 / 2.7 | 复杂组织级 SSO / SAML | Deferred upgrade | 本次保留 OIDC/JWKS 边界，复杂 SSO 后续升级 |
| U05 | 2.3 / 2.7 | 多 SERP vendor 自动比较 | Deferred upgrade | 本次 Google browser/SERP 只做 Go/No-Go 决策 |
| U06 | 2.3 / 2.7 | 高级统计显著性模型 | Deferred upgrade | 本次使用 versioned scoring formula |
