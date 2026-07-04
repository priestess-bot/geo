# GEO Production v1 执行进度 Checklist

生成日期：2026-07-05

对照规划：[GEO-Production-v1完整规划-2026-07-05.md](./GEO-Production-v1完整规划-2026-07-05.md)

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
| C00 | 13 / 14 / 20 | 建立本 checklist 与 gate 骨架 | 无 | Verifying | `make test` | 本文件；`scripts/verify_production_v1_gate.py` | 待填 | 第一批工作包 |
| C01 | 0 / 1 / 5 | 生产路径禁止 demo/fixture fallback | C00 | Done | `make no-fixture-production-smoke` | `scripts/verify_production_v1_gate.py`; focused unittest suite | 待填 | 生产默认路径改为真实 API/手工补录；fixture 端点仅开发工具开关可用 |
| C02 | 13 / 15 | provider key、session token、invite token 不泄露 | C00 | Verifying | `python3 scripts/verify_production_v1_gate.py security-smoke --allow-pending`; focused auth/session tests | `scripts/verify_production_v1_gate.py`; `tests/test_api_contracts.py`; `apps/api/geno_api/main.py` | 待填 | security-smoke 已无 pending；Provider secret storage 专项仍在 W3-I00 |
| C03 | 14 | Production v1 E2E 从空环境跑通 | C01-C18 | Not started | `make production-v1-e2e` | 待填 | 待填 | 真实报告生产闭环 |
| C04 | 14 | Enablement v1 E2E 跑通 | C19-C21 | Not started | `make enablement-v1-e2e` | 待填 | 待填 | KB/Content/Distribution 薄闭环 |
| C05 | 20 | Final Gate 全部通过 | C01-C24 | Not started | `make production-v1-final-gate` | 待填 | 待填 | 最终验收 |

## 2. Foundation

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W10-I01 | 16 / 14 | `production-v1-e2e` 骨架 | 无 | Verifying | `make production-v1-e2e` | `scripts/verify_production_v1_gate.py` | 待填 | 严格模式按 pending 失败，进度模式可观察未完成项 |
| W1-I03 | 16 | 清除生产路径 demo fallback | W10-I01 | Done | `make no-fixture-production-smoke` | `scripts/verify_production_v1_gate.py`; `tests/test_admin_customer_web_contracts.py`; `tests/test_infra_contracts.py`; `tests/test_api_contracts.py`; `tests/test_worker_cli.py` | 待填 | 新建项目/启动配置/worker 默认真实 API；fixture collection/report 仅开发工具开关可用 |
| W1-I01 | 16 / 6 | FastAPI domain route 边界 | W10-I01 | Done | `python3 -m compileall apps/api/geno_api`; focused API/router tests | `apps/api/geno_api/ops_routes.py`; `tests/test_infra_contracts.py` | 待填 | 建立 ops domain router 模式；后续 domain router 按此迁移 |
| W1-I02 | 16 / 6 | Repository 拆分边界 | W1-I01 | Not started | `make test` | 待填 | 待填 | 按 audit/access/project/connector 等顺序拆 |

## 3. Identity / Access

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W2-I01a | 16 / 7.1 | AuthContext contract/types/dependency | W1-I01 | Done | `python3 -m compileall apps/api/geno_api`; `make security-smoke --allow-pending` equivalent; focused auth tests | `apps/api/geno_api/auth_context.py`; `tests/test_auth_context_contracts.py` | 待填 | header/jwt/jwks actor 已统一到 AuthContext；session/RBAC rollout 由后续项完成 |
| W2-I01b | 16 | sessions table + session repository | W2-I01a | Done | `python3 -m compileall packages/geno_core/geno_core apps/api/geno_api scripts/verify_db_smoke.py`; focused session tests | `infra/db/migrations/up/0016_runtime_sessions.sql`; `packages/geno_core/geno_core/runtime_project_access_repository.py`; `tests/test_core_contracts.py` | 待填 | server-side session hash、TTL、validate、revoke 基线完成；cookie/API rollout 后续完成 |
| W2-I01c | 16 | protected API dependency rollout | W2-I01a/W2-I01b/W2-I03a/W2-I03b | Done | `python3 -m unittest tests.test_auth_context_contracts`; `make security-smoke --allow-pending` equivalent | `apps/api/geno_api/main.py`; `tests/test_auth_context_contracts.py` | 待填 | protected API 依赖已支持 session AuthContext 与 project scope；邀请兑换设置 cookie 由 W2-I02 完成 |
| W2-I01d | 16 | system actor contract | W2-I01a | Done | `python3 -m unittest tests.test_auth_context_contracts`; `make security-smoke --allow-pending` equivalent | `apps/api/geno_api/auth_context.py`; `tests/test_auth_context_contracts.py` | 待填 | system actor 默认必须带 tenant/project scope 与 explicit permissions；maintenance 需显式 `allow_unscoped` |
| W2-I01e | 16 / 7.11 | auth audit events | W2-I01a | Done | `python3 -m unittest tests.test_core_contracts.CoreContractsTest.test_auth_audit_event_vocabulary_rejects_raw_secret_refs`; `make security-smoke --allow-pending` equivalent | `packages/geno_core/geno_core/audit.py`; `tests/test_core_contracts.py` | 待填 | auth/authz/invitation/system_actor 事件词表完成，禁止 raw token/secret refs |
| W2-I02 | 16 | Invitation token 一次性兑换 | W2-I01a/W2-I01b/W2-I03a/W2-I03b | Done | focused auth/session unittest suite; `python3 scripts/verify_production_v1_gate.py security-smoke --allow-pending` | `apps/api/geno_api/main.py`; `tests/test_api_contracts.py` | 待填 | `/v1/auth/invitations/redeem` 创建一次性 httpOnly session cookie 与 CSRF cookie；`/v1/auth/me` 与 CSRF-protected `/v1/auth/logout` 完成 |
| W2-I03a | 16 / 7.2 | RBAC matrix contract | W2-I01a | Done | `python3 -m unittest tests.test_rbac_contracts`; `make security-smoke --allow-pending` equivalent | `packages/geno_core/geno_core/rbac.py`; `tests/test_rbac_contracts.py` | 待填 | permission vocabulary 与 role matrix 已成为核心契约；路由全面接入由 W2-I01c 完成 |
| W2-I03b | 16 | membership schema + scope repository | W2-I01b/W2-I03a | Done | `python3 -m unittest tests.test_membership_scope_contracts`; `make security-smoke --allow-pending` equivalent | `infra/db/migrations/up/0017_tenant_membership_scope.sql`; `packages/geno_core/geno_core/runtime_project_access_repository.py`; `tests/test_membership_scope_contracts.py` | 待填 | `tenant_members` 与 scope repository 完成；RLS `app.*` 升级由 W2-I03c 完成 |
| W2-I03c | 16 / 8.2 | RLS smoke for core tables | W2-I03b | Done | `python3 scripts/verify_production_v1_gate.py security-smoke --allow-pending`; `make rls-smoke` equivalent | `infra/db/migrations/up/0010_runtime_project_rls.sql`; `scripts/verify_db_smoke.py`; `packages/geno_core/geno_core/repository.py` | 待填 | RLS helper 优先读取 `app.actor_id/app.project_id/app.project_ids/app.roles`，旧 `geno.runtime_*` 保留 fallback |

## 4. Collection / Evidence

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W3-I00 | 16 / 2.5 | Provider secret storage and redaction baseline | W2-I01a/W2-I03a | In progress | `python3 scripts/verify_production_v1_gate.py no-secret-leak-smoke --allow-pending`; focused secret/API tests | `infra/db/migrations/up/0018_connector_secret_refs.sql`; `packages/geno_core/geno_core/security/secrets.py`; `apps/api/geno_api/main.py`; `tests/test_api_contracts.py`; `tests/test_core_contracts.py` | 待填 | DB encrypted column + SecretStore adapter + API masked metadata + access-log body redaction |
| W3-I01 | 16 / 7.3 | Connector contract + recorded harness | W1-I01/W3-I00 | Not started | `make connector-real-smoke` | 待填 | 待填 | Local/CI 无 key 可跳过真实子集 |
| W3-I02 | 16 | OpenAI 真实采集闭环 | W3-I01/W4-I01a | Not started | `make connector-real-smoke` | 待填 | 待填 | Responses API + web_search |
| W3-I03 | 16 | Perplexity 真实采集闭环 | W3-I00/W3-I01/W4-I01a | Not started | `make connector-real-smoke` | 待填 | 待填 | sonar adapter、citation、cost、failure |
| W3-I04 | 16 | Google manual backfill 生产路径 | W4-I01a | Not started | `make connector-real-smoke` | 待填 | 待填 | browser/SERP 只做 Go/No-Go，不阻塞本次 |
| W4-I01a | 16 / 7.4 | EvidenceAsset schema + repository | W2-I01a | Not started | `make report-traceability-smoke` | 待填 | 待填 | metadata/hash/visibility |
| W4-I01b | 16 / 2.5 | S3-compatible storage adapter | W4-I01a | Not started | `make report-traceability-smoke` | 待填 | 待填 | MinIO/S3-compatible |
| W4-I01c | 16 | EvidenceAsset permission proxy | W2-I03a/W4-I01a/W4-I01b | Not started | `make customer-access-negative-smoke` | 待填 | 待填 | 客户下载必须经 API 授权 |
| W4-I01d | 16 | Traceability chain smoke | W4-I01a | Not started | `make report-traceability-smoke` | 待填 | 待填 | Report -> Score -> Analysis -> RawAnswer -> Evidence |

## 5. Intelligence / Delivery

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W5-I01 | 16 / 7.9 | AnswerAnalysis baseline parser | W3-I02/W3-I03/W4-I01a | Not started | `make report-traceability-smoke` | 待填 | 待填 | deterministic parser 优先 |
| W5-I02a | 16 / 7.5 | Scoring profile schema + formula contract | W5-I01 | Not started | `make report-traceability-smoke` | 待填 | 待填 | `visibility_v1.0` |
| W5-I02b | 16 | VisibilityScoreSnapshot calculator | W5-I02a | Not started | `make report-traceability-smoke` | 待填 | 待填 | platform/prompt contribution |
| W5-I02c | 16 | ScoreContribution traceability | W5-I02b/W4-I01d | Not started | `make report-traceability-smoke` | 待填 | 待填 | 每个数字可追溯 |
| W6-I01a | 16 / 7.6 | ReportExport schema + immutable repository | W4-I01d/W5-I02c/W2-I03a | Not started | `make report-traceability-smoke` | 待填 | 待填 | fixed snapshot |
| W6-I01b | 16 / 12 | Markdown/CSV generation from fixed snapshot | W6-I01a | Not started | `make report-traceability-smoke` | 待填 | 待填 | 同一 snapshot 渲染 |
| W6-I01c | 16 / 2.5 | PDF generation and asset storage | W6-I01b/W4-I01b | Not started | `make report-traceability-smoke` | 待填 | 待填 | HTML + Playwright/Chromium |
| W6-I01d | 16 | Approval/publish/revoke lifecycle | W6-I01a/W2-I03a | In progress | `python3 scripts/verify_production_v1_gate.py customer-access-negative-smoke --allow-pending` | `apps/api/geno_api/main.py`; `packages/geno_core/geno_core/repository.py`; `tests/test_api_contracts.py` | 待填 | 客户下载已强制最新管理状态为 `client_ready`；完整审批 UI/生命周期仍待 W6 |
| W6-I01e | 16 | Customer report center + permissioned download | W6-I01c/W6-I01d/W4-I01c | In progress | `python3 scripts/verify_production_v1_gate.py customer-access-negative-smoke --allow-pending` | `apps/customer-web/app/api/report-artifact/route.ts`; `apps/api/geno_api/main.py`; `tests/test_api_contracts.py` | 待填 | customer-web artifact proxy 已显式标记 portal 下载并由 API 授权；完整报告中心仍待 W6 |
| W6-I01f | 16 | Report security tests | W6-I01e | In progress | focused report artifact unittest suite; `python3 scripts/verify_production_v1_gate.py security-smoke --allow-pending` | `tests/test_api_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | 未发布/撤回/跨项目 report artifact 负向测试完成；raw evidence/provider key 负向测试随 W4/W3 扩展 |

## 6. Optimization / Enablement

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W7-I01 | 16 | Action Plan 最小闭环 | W5-I02c/W6-I01f | Not started | `make production-v1-e2e` | 待填 | 待填 | 3 类确定性建议 |
| W7-I02 | 16 | Retest 最小闭环 | W7-I01/W3-I02/W3-I03/W5-I02c/W6-I01f | Not started | `make production-v1-e2e` | 待填 | 待填 | before/after/delta |
| W8-I01 | 16 | Knowledge Base 薄闭环 | W4-I01a/W2-I03a | Not started | `make enablement-v1-e2e` | 待填 | 待填 | approved facts only |
| W8-I02 | 16 | Content Workbench 薄闭环 | W7-I01/W8-I01 | Not started | `make enablement-v1-e2e` | 待填 | 待填 | 从 Action 创建 content asset |
| W8-I03 | 16 | Distribution task 回填 | W8-I02/W7-I02 | Not started | `make enablement-v1-e2e` | 待填 | 待填 | URL/proof 回填，关联 Retest |

## 7. Ops / QA

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W9-I01 | 16 / 2.5 | Observability 最小生产门禁 | W10-I01 | Not started | `make ops-smoke` | 待填 | 待填 | logs/health/metrics/alerts |
| W9-I02 | 16 / 2.5 | Backup / restore 演练 | W4-I01a | Not started | `make backup-smoke` | 待填 | 待填 | Postgres + object storage |
| Q01 | 13.9 | customer negative access | W2/W4/W6 | In progress | `python3 scripts/verify_production_v1_gate.py customer-access-negative-smoke --allow-pending` | `tests/test_api_contracts.py`; `scripts/verify_production_v1_gate.py` | 待填 | report artifact 的未发布/撤回/跨项目已覆盖；raw evidence/provider key 随 W4/W3 补齐 |
| Q02 | 13.9 | no secret leak | W3/W6/W9 | In progress | `python3 scripts/verify_production_v1_gate.py security-smoke --allow-pending` | `scripts/verify_production_v1_gate.py`; `tests/test_api_contracts.py` | 待填 | auth/session/invite token 与静态 provider secret 扫描已覆盖；日志/report artifact 深扫后续扩展 |
| Q03 | 13.9 | report traceability | W4/W5/W6 | Not started | `make report-traceability-smoke` | 待填 | 待填 | 抽样 5 个数字 |

## 8. 本次不做完、但保留扩展边界的升级项

| 编号 | 对照章节 | 升级项 | 状态 | 本次要求 |
| --- | --- | --- | --- | --- |
| U01 | 2.3 / 2.7 | Gemini / Bing Copilot / Claude / DeepSeek / 豆包 / Kimi / 腾讯元宝 / 百度文小言等额外平台 | Deferred upgrade | 保留 connector adapter 边界，不进入本次验收 |
| U02 | 2.3 / 2.7 | 所有渠道自动发布 | Deferred upgrade | 本次只做 Distribution task 人工回填 |
| U03 | 2.3 / 2.7 | Neo4j / OpenSearch / ClickHouse 高级图谱 | Deferred upgrade | 本次使用 Postgres/现有 graph baseline |
| U04 | 2.3 / 2.7 | 复杂组织级 SSO / SAML | Deferred upgrade | 本次保留 OIDC/JWKS 边界，复杂 SSO 后续升级 |
| U05 | 2.3 / 2.7 | 多 SERP vendor 自动比较 | Deferred upgrade | 本次 Google browser/SERP 只做 Go/No-Go 决策 |
| U06 | 2.3 / 2.7 | 高级统计显著性模型 | Deferred upgrade | 本次使用 versioned scoring formula |
