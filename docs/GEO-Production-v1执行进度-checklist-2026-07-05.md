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
| C02 | 13 / 15 | provider key、session token、invite token 不泄露 | C00 | Verifying | `make no-secret-leak-smoke` | `scripts/verify_production_v1_gate.py` | 待填 | 静态生产面扫描已接入，后续扩展到日志/报告 artifact |
| C03 | 14 | Production v1 E2E 从空环境跑通 | C01-C18 | Not started | `make production-v1-e2e` | 待填 | 待填 | 真实报告生产闭环 |
| C04 | 14 | Enablement v1 E2E 跑通 | C19-C21 | Not started | `make enablement-v1-e2e` | 待填 | 待填 | KB/Content/Distribution 薄闭环 |
| C05 | 20 | Final Gate 全部通过 | C01-C24 | Not started | `make production-v1-final-gate` | 待填 | 待填 | 最终验收 |

## 2. Foundation

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W10-I01 | 16 / 14 | `production-v1-e2e` 骨架 | 无 | Verifying | `make production-v1-e2e` | `scripts/verify_production_v1_gate.py` | 待填 | 严格模式按 pending 失败，进度模式可观察未完成项 |
| W1-I03 | 16 | 清除生产路径 demo fallback | W10-I01 | Done | `make no-fixture-production-smoke` | `scripts/verify_production_v1_gate.py`; `tests/test_admin_customer_web_contracts.py`; `tests/test_infra_contracts.py`; `tests/test_api_contracts.py`; `tests/test_worker_cli.py` | 待填 | 新建项目/启动配置/worker 默认真实 API；fixture collection/report 仅开发工具开关可用 |
| W1-I01 | 16 / 6 | FastAPI domain route 边界 | W10-I01 | Not started | `make test` | 待填 | 待填 | 从 `main.py` 拆 domain router |
| W1-I02 | 16 / 6 | Repository 拆分边界 | W1-I01 | Not started | `make test` | 待填 | 待填 | 按 audit/access/project/connector 等顺序拆 |

## 3. Identity / Access

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W2-I01a | 16 / 7.1 | AuthContext contract/types/dependency | W1-I01 | Not started | `make security-smoke` | 待填 | 待填 | header/jwt/jwks/OIDC actor 统一 |
| W2-I01b | 16 | sessions table + session repository | W2-I01a | Not started | `make security-smoke` | 待填 | 待填 | server-side session hash、TTL、revoke |
| W2-I01c | 16 | protected API dependency rollout | W2-I01a/W2-I01b/W2-I03a/W2-I03b | Not started | `make security-smoke` | 待填 | 待填 | 所有受保护 API 不再依赖裸 actor header |
| W2-I01d | 16 | system actor contract | W2-I01a | Not started | `make security-smoke` | 待填 | 待填 | system actor 默认带 tenant/project scope |
| W2-I01e | 16 / 7.11 | auth audit events | W2-I01a | Not started | `make security-smoke` | 待填 | 待填 | login/logout/invite/session revoke |
| W2-I02 | 16 | Invitation token 一次性兑换 | W2-I01a/W2-I01b/W2-I03a/W2-I03b | Not started | `make security-smoke` | 待填 | 待填 | 不再长期依赖 URL query token |
| W2-I03a | 16 / 7.2 | RBAC matrix contract | W2-I01a | Not started | `make security-smoke` | 待填 | 待填 | permission vocabulary 唯一来源 |
| W2-I03b | 16 | membership schema + scope repository | W2-I01b/W2-I03a | Not started | `make rls-smoke` | 待填 | 待填 | tenant_members/project_members |
| W2-I03c | 16 / 8.2 | RLS smoke for core tables | W2-I03b | Not started | `make rls-smoke` | 待填 | 待填 | 需要升级到 `app.*` scope injection |

## 4. Collection / Evidence

| 编号 | 对照章节 | 工作项 | 依赖 | 状态 | 验收命令 | 证据路径 | Commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W3-I00 | 16 / 2.5 | Provider secret storage and redaction baseline | W2-I01a/W2-I03a | Not started | `make no-secret-leak-smoke` | 待填 | 待填 | DB encrypted column + SecretStore adapter |
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
| W6-I01d | 16 | Approval/publish/revoke lifecycle | W6-I01a/W2-I03a | Not started | `make customer-access-negative-smoke` | 待填 | 待填 | 已撤回不可下载 |
| W6-I01e | 16 | Customer report center + permissioned download | W6-I01c/W6-I01d/W4-I01c | Not started | `make customer-access-negative-smoke` | 待填 | 待填 | 客户门户安全查看 |
| W6-I01f | 16 | Report security tests | W6-I01e | Not started | `make no-secret-leak-smoke` | 待填 | 待填 | no raw payload / no secret / revoked denied |

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
| Q01 | 13.9 | customer negative access | W2/W4/W6 | Not started | `make customer-access-negative-smoke` | 待填 | 待填 | 跨租户/未发布/撤回/raw evidence/provider key |
| Q02 | 13.9 | no secret leak | W3/W6/W9 | Not started | `make no-secret-leak-smoke` | 待填 | 待填 | API/log/frontend/report |
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
