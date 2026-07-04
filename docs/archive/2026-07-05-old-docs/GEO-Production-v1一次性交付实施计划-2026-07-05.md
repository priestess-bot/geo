# GEO Production v1 一次性交付实施计划

生成时间：2026-07-05 Asia/Shanghai

关联总规划：[GEO完整投产实现规划-2026-07-05.md](GEO完整投产实现规划-2026-07-05.md)

关联选型：[GEO技术选型与复用策略-2026-07-05.md](GEO技术选型与复用策略-2026-07-05.md)

历史草案：[GEO投产实施计划-2026-07-05.md](archive/2026-07-05-old-docs/GEO投产实施计划-2026-07-05.md)

本文是当前唯一执行口径：目标不是 MVP、试点、原型或分阶段对外发布，而是一次开发到真实客户可使用、内部团队可运营、生产环境可维护的 **GEO Production v1**。

对外只交付一个完整可用版本；对内按依赖并行施工，并通过内部门禁减少 Auth、RLS、采集、证据链、评分、报告、客户门户和运维能力之间的返工。内部门禁不代表阶段发布，不代表可以把半成品交付给客户。

## 1. 执行口径

GEO Production v1 的开发口径如下：

1. 不做 MVP，不做试点，不做 demo 版。
2. 所有工作都归入同一个 GEO Production v1 scope。
3. 不允许用 fixture/demo 数据冒充生产能力。
4. 所有核心模块必须接真实数据库、真实权限、真实审计、真实对象存储。
5. 外部能力通过 adapter 接入，避免业务代码绑定供应商 SDK。
6. 前端页面可以并行开发，但必须接真实 API 后才算完成。
7. 最终只做一次 Production v1 总验收和一次正式上线。

## 2. Production v1 范围

GEO Production v1 必须一次性包含以下能力。缺少其中任何核心闭环能力，都不能标记为完成。

1. 多租户、登录、邀请、RBAC、RLS。
2. Admin Web 内部运营后台。
3. Customer Web 客户门户。
4. 项目、品牌、竞品、Prompt、市场配置。
5. OpenAI 真实采集。
6. Perplexity 真实采集。
7. Google manual backfill。
8. Google browser/SERP 可选生产路径。
9. 证据链：RawAnswer / Citation / EvidenceAsset / AuditEvent。
10. AnswerAnalysis 自动解析 + 人工修正。
11. VisibilityScoreSnapshot / ScoreContribution。
12. ReportExport：Markdown / PDF / CSV。
13. 客户安全查看和下载报告。
14. Action Plan。
15. Retest。
16. Knowledge Base。
17. Content Workbench。
18. Distribution task 回填。
19. 监控、告警、备份、恢复、安全扫描、部署手册。

## 3. 执行层级

采用以下层级管理实现：

```text
GEO Production v1
  -> Workstream
    -> Epic
      -> Feature
        -> Task
          -> Migration / API / UI / Worker / Permission / Audit / Test / Doc / Rollback
```

每个 Task 必须写清：

- 目标。
- 依赖。
- 涉及模块。
- 数据库变更。
- API 变更。
- 前端变更。
- worker 变更。
- 权限规则。
- 审计事件。
- 测试用例。
- 验收方式。
- 回滚方式。

未满足上述字段的事项只算想法，不允许进入开发排期。

## 4. 并行施工原则

Production v1 是一个版本目标，不是多个外部发布阶段。开发方式是：

```text
一个版本目标
多条工作流并行
强依赖先行
统一最终验收
```

知识库、内容生成、分发自动化可以并行做基础设施和 UI，但不得绕过真实采集、证据链、评分、报告闭环独立投产。

推荐并行关系：

- W1、W2、W3、W4、W9、W10 从第一天启动。
- W5 在 W3/W4 的数据契约冻结后进入核心实现。
- W6 在 W2/W5 的权限和评分契约冻结后进入核心实现。
- W7 在 W5/W6 的报告和评分链路可用后进入核心实现。
- W8 的基础表、对象存储导入、UI shell 可以提前做；知识事实、内容建议、分发回填必须和真实报告、行动计划、复测闭环打通后才算完成。

## 5. Production v1 工作流

| 工作流 | 名称 | 内容 | 是否可以并行 | 完成判定 |
| --- | --- | --- | --- | --- |
| W1 | 架构与工程基线 | FastAPI 边界、Repository 拆分、测试修复、demo fallback 清理、端口和文案口径 | 必须最先启动 | 工程基线可信，生产路径不依赖 demo fallback |
| W2 | Auth / Tenant / RBAC / RLS | Keycloak/OIDC、session、邀请、权限矩阵、RLS、越权测试 | 必须最先启动 | 真实用户、租户、角色、项目授权可用 |
| W3 | Connector / Collection | OpenAI、Perplexity、Google manual、Google browser/SERP、调度、限流、成本 | 可与 W2 并行 | 真实采集可运行、可重试、可计费、可解释失败 |
| W4 | Evidence / Audit | RawAnswer、Citation、EvidenceAsset、对象存储、traceability、AuditEvent | 必须和 W3 并行 | 任意采集和报告可追溯到原始证据 |
| W5 | Analysis / Scoring | AnswerAnalysis、ScoreContribution、评分公式、人工复核 | 依赖 W3/W4 数据结构 | 报告数字可解释，可人工修正和复算 |
| W6 | Report / Customer Portal | 报告生成、发布、撤回、客户安全查看和下载 | 依赖 W2/W5 | 客户只能访问授权且已发布的报告 |
| W7 | Action / Retest | 行动建议、任务、复测、趋势、告警 | 依赖 W5/W6 | 从报告进入持续优化闭环 |
| W8 | Knowledge / Content / Distribution | 知识库、内容生成、审核、分发回填 | 可提前做基础设施和 UI，业务闭环依赖 W7 | 内容建议和分发结果能反哺复测 |
| W9 | Observability / Ops | Prometheus、Grafana、Sentry、备份恢复、部署、告警、secret 管理 | 从第一天开始 | 生产运行可观测、可恢复、可交接 |
| W10 | QA / Security / Release | 测试矩阵、越权测试、压测、安全扫描、上线演练 | 全程伴随 | 最终 Production v1 总验收通过 |

## 6. Workstream 任务边界

### W1 架构与工程基线

目标：让工程基线可信，消除会污染后续实现的阻断。

必须完成：

- FastAPI domain route 边界冻结：auth、tenants、projects、prompts、connectors、collection、evidence、analysis、scoring、reports、audit。
- Repository 拆分边界冻结，禁止继续扩大巨型 repository。
- Connector interface ADR 和 evidence chain contract ADR 接受。
- Auth、队列、对象存储、监控、向量/搜索、图存储、文档解析、报告渲染、前端组件 ADR 与本计划一致。
- 全量 Python lint/compile/unit、Next.js typecheck/build、db-smoke、runtime-e2e 可重复通过。
- `db-smoke` 和 observability 默认端口不与常见本机服务冲突。
- 用户可见文案统一 GEO 口径。
- 生产项目创建路径不再使用 `ExampleBrand`、`AU GEO Pilot` 等 demo fallback。
- 历史脏数据清理，并在前后端加入校验避免再次写入。

W1 不交付客户价值，但它阻塞所有依赖它的合并。

### W2 Auth / Tenant / RBAC / RLS

目标：真实用户和租户边界可用，不靠临时 actor 或 URL token 访问客户数据。

必须完成：

- OIDC-compatible auth provider boundary，生产优先 Keycloak 或托管 OIDC。
- 用户、租户成员、项目成员、邀请、session、外部身份映射表。
- httpOnly secure session cookie。
- 客户邀请 token 只用于一次性兑换，不作为长期访问凭据。
- 角色 x 资源 x 动作权限矩阵。
- 所有受保护 API 从可信 session 或 system actor 推导 tenant/project scope。
- PostgreSQL RLS 对租户级、项目级核心表生效。
- Client Viewer、Analyst、Reviewer、Project Owner、Tenant Admin、Super Admin 的 allow/deny 契约测试。
- 越权访问必须返回 403，并写入审计事件。

### W3 Connector / Collection

目标：真实外部采集可运行、可审计、可重试、可计费。

必须完成：

- `ConnectorBackend` / `LLMGateway` / `CollectionTask` 统一接口。
- connector_configs 表和密钥引用模型，provider key 不明文出现在 API response、日志或报告。
- OpenAI 真实采集：至少 10 个真实 Prompt，保存 payload、回答、引用、成本、失败分类。
- Perplexity 真实采集：同 OpenAI，保留 citation 结构。
- Google manual backfill：结构化补录、来源说明、证据资产、方法披露。
- Google browser/SERP 可选生产路径：至少完成一个可投入生产的路径或形成明确 No-Go 风险决策。
- 调度、限流、预算、重试、取消、dead-letter、成本归因。
- 采集 run、answer run、provider request 的状态机。

### W4 Evidence / Audit

目标：任意客户报告数字都能追溯到原始证据和审计事件。

必须完成：

- RawAnswer / AnswerCitation / EvidenceAsset / AuditEvent / EvidenceLink 数据契约。
- 对象存储统一 S3-compatible，dev/staging MinIO，production 可替换 S3/R2/MinIO。
- evidence asset hash、content type、storage key、project scope、retention policy。
- 采集、解析、人工修正、评分、报告生成、报告发布、客户访问全部写审计。
- API 只返回权限允许的 evidence 摘要；原始证据和附件走权限代理或短期签名 URL。
- Traceability Bundle 可从 ReportExport 追溯到 answer run、raw answer、citation、asset 和 audit event。

### W5 Analysis / Scoring

目标：把真实回答变成可解释、可复核、可复算的 GEO 指标。

必须完成：

- AnswerAnalysis parser，覆盖品牌提及、竞品提及、推荐状态、排名、引用域名、情绪/风险、地理相关性。
- parser version、input hash、output schema、失败原因。
- 人工复核和修正，保留 reviewer、修正原因、前后差异。
- VisibilityScoreSnapshot 公式版本化。
- ScoreContribution 解释每一个分数来源。
- 评分配置必须指向具体配置文件或版本化 profile，不只显示名字。
- 回归测试覆盖典型回答、无触发、触发但无回答、引用缺失、竞品强推荐、品牌错误描述。

### W6 Report / Customer Portal

目标：把真实证据和评分交付成客户可安全查看、下载、撤回的正式报告。

必须完成：

- 最小正式报告模板冻结：项目摘要、采样范围、平台说明、时间窗、总体分数、平台分数、Prompt 明细、证据摘要、方法说明、局限说明、审计摘要。
- ReportExport 不可覆盖，发布新版本必须生成新 export。
- Markdown / PDF / CSV 导出。
- 报告发布、审批、撤回、重新发布状态机。
- Customer Web 仅展示授权项目和已发布报告。
- 报告撤回后客户不可继续下载。
- 下载事件、查看事件、拒绝访问事件写审计。
- 客户入口不暴露内部调试信息、provider key、未脱敏原始 payload。

### W7 Action / Retest

目标：从报告进入持续优化闭环，而不是停留在一次性诊断。

必须完成：

- Action Plan 从 Source Gap、AnswerAnalysis、ScoreContribution 生成建议。
- 行动项分配、状态、优先级、证据链接、预期影响。
- Retest 计划：观察窗口、平台、Prompt、竞品、预算、对比基线。
- 复测运行写入新的 collection / analysis / score / report 链路。
- 趋势视图展示前后变化和局限说明。
- 告警规则覆盖采集失败、评分大幅下降、竞品快速上升、成本超阈值。

### W8 Knowledge / Content / Distribution

目标：补齐 GEO 服务链中的知识事实、内容建议、审核和分发结果回填。

必须完成：

- Knowledge Base：文件/URL 导入、对象存储归档、解析、chunk、事实抽取、事实审核、向量检索。
- Approved facts 才能进入客户可见内容建议。
- Content Workbench：内容 brief、草稿、引用证据、审核、版本、导出。
- Distribution task：渠道、URL、负责人、状态、发布时间、回填结果、关联 action 和 retest。
- 内容和分发必须关联证据、行动项和复测，不能成为孤立内容生成工具。
- UI 可提前搭建，但未接真实 API、真实权限、真实审计前不得标记完成。

### W9 Observability / Ops

目标：Production v1 可观测、可恢复、可安全运维。

必须完成：

- Prometheus 指标：API、worker、provider、cost、queue、object store、audit、auth denial、report job。
- Grafana dashboard 和 alert rule。
- OpenTelemetry trace，包含 request、collection、parser、score、report、customer access。
- Sentry 或同类错误追踪，包含 release、tenant/project tags 和 PII 脱敏。
- Secret 管理路径：本地 env/gitignored files 到生产 Vault/云 secret manager。
- 备份和恢复演练：PostgreSQL、对象存储、配置、密钥轮换。
- 部署手册、迁移手册、回滚手册、故障处理手册。
- 日志脱敏、成本告警、限流策略。

### W10 QA / Security / Release

目标：把所有工作流合到一次 Production v1 总验收。

必须完成：

- 单元、契约、集成、E2E、浏览器、迁移、权限、安全、性能、恢复测试矩阵。
- 越权测试覆盖 tenant/project/report/evidence/provider key/customer portal。
- 安全扫描覆盖依赖、镜像、secret、header、cookie、CORS、SQL 注入、SSRF、文件上传。
- 压测覆盖项目创建、Prompt 导入、采集调度、报告导出、客户下载。
- 上线演练：全新环境部署、迁移、创建租户、邀请用户、配置 connector、真实采集、报告发布、客户下载、撤回、恢复。
- 所有文档更新：用户手册、运营手册、部署手册、API 申请清单、数据口径说明。

## 7. 内部依赖门禁

内部依赖门禁用于降低返工，不是外部发布阶段。任何门禁失败，只阻塞依赖它的工作流合并或标记完成，不改变“只交付一个 Production v1”的口径。

### Gate W1：工程基线可信

必须通过：

```bash
python3 -m ruff check apps/api/geno_api packages/geno_core/geno_core workers scripts tests
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall apps/api/geno_api packages/geno_core/geno_core workers scripts tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/geno_core:apps/api python3 -m unittest discover -s tests
npm --prefix apps/admin-web run typecheck
npm --prefix apps/customer-web run typecheck
npm --prefix apps/dashboard-web run typecheck
npm --prefix apps/admin-web run build
npm --prefix apps/customer-web run build
npm --prefix apps/dashboard-web run build
make docker-config
make docker-config-observability
make db-smoke
make runtime-e2e
git diff --check
```

阻断条件：

- 全量测试失败。
- 生产路径仍能写入 demo fallback。
- 权限、connector、evidence chain、核心选型 ADR 未冻结。
- Admin/Web/Dashboard 仍在核心入口混用旧 GENO/AU/试点口径。

### Gate W2：权限边界可信

必须通过：

- 登录、退出、邀请兑换、session 过期测试。
- RBAC allow/deny 合同测试。
- RLS smoke 覆盖新增租户、成员、项目、报告、证据表。
- Customer portal 不再依赖长期 query token。

阻断条件：

- API 允许绕过 actor/project scope。
- Client Viewer 可越权访问其他项目、未发布报告或 provider key。
- provider key、session、邀请 token 明文出现在普通 response、日志或报告中。

### Gate W3/W4：真实采集和证据链可信

必须通过：

- OpenAI 和 Perplexity 至少各完成一个真实项目 10 Prompt 采集。
- Google manual backfill 完成结构化证据录入。
- Google browser/SERP 至少一个路径完成生产可行性决策。
- RawAnswer、AnswerCitation、EvidenceAsset、CollectionCost、AuditEvent 写入完整。
- 失败重试、取消、dead-letter 和错误分类测试通过。

阻断条件：

- 采集结果不能追溯到 evidence asset。
- Google 数据来源和局限没有方法披露。
- 多平台数据混入同一分母但无法区分 access_method 和 sample window。

### Gate W5/W6：评分和报告可信

必须通过：

- ScoreContribution 能解释报告中的总分、平台分、Prompt 明细。
- 最小客户报告模板冻结。
- ReportExport 不可覆盖。
- 客户只可安全查看已发布报告。
- 报告撤回后客户不可下载。

阻断条件：

- 报告数字无法追溯到 answer run 和 evidence asset。
- 客户可查看未发布报告。
- 人工修正覆盖原始解析且无法审计。

### Gate W7/W8：优化闭环可信

必须通过：

- Action Plan 可从真实 score/source gap 生成。
- Retest 可复用真实采集、解析、评分和报告链路。
- Knowledge Base 只允许 approved facts 进入内容建议。
- Distribution task 回填结果能关联 action 和 retest。

阻断条件：

- 知识库、内容或分发绕过真实证据链独立生成客户可见结论。
- 复测不能和上一轮报告形成可解释对比。

### Gate W9/W10：生产运行可信

必须通过：

- 监控、告警、trace、错误追踪、日志脱敏可用。
- PostgreSQL 和对象存储备份恢复演练通过。
- 安全扫描和越权测试通过。
- 上线演练从空环境跑完整 Production v1 链路。

阻断条件：

- 关键生产故障无法定位。
- 备份不可恢复。
- secret、token、provider key 泄露到仓库、日志、报告或前端 bundle。

## 8. Production v1 总验收

GEO Production v1 只在最终做一次总验收。总验收不是某个 workstream 的局部验收，而是从空环境到真实客户使用的完整演练。

### 8.1 客户侧完成定义

真实客户必须能够：

- 登录客户门户。
- 查看授权项目。
- 查看真实 OpenAI / Perplexity / Google 数据。
- 查看 AI 可见性评分。
- 下载正式 PDF/CSV 报告。
- 查看证据摘要和方法说明。
- 查看行动计划。
- 查看复测结果。

### 8.2 内部团队完成定义

内部团队必须能够：

- 创建租户。
- 邀请用户。
- 配置项目。
- 配置 connector。
- 运行采集。
- 查看失败和成本。
- 修正解析结果。
- 生成、审批、发布、撤回报告。
- 管理知识库。
- 生成和审核内容建议。
- 创建分发任务。
- 回填发布结果。
- 触发复测。
- 查看审计日志、监控和告警。

### 8.3 最终验收命令

最终验收至少包含：

```bash
python3 -m ruff check apps/api/geno_api packages/geno_core/geno_core workers scripts tests
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall apps/api/geno_api packages/geno_core/geno_core workers scripts tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/geno_core:apps/api python3 -m unittest discover -s tests
npm --prefix apps/admin-web run typecheck
npm --prefix apps/customer-web run typecheck
npm --prefix apps/dashboard-web run typecheck
npm --prefix apps/admin-web run build
npm --prefix apps/customer-web run build
npm --prefix apps/dashboard-web run build
make docker-config
make docker-config-observability
make db-smoke
make runtime-e2e
make security-smoke
make production-v1-e2e
git diff --check
```

如果当前仓库还没有 `make security-smoke` 或 `make production-v1-e2e`，W10 必须新增这些目标或等价脚本。

## 9. Issue 拆分模板

每个可执行 issue 必须使用以下模板：

```text
Workstream:
Epic:
Task:
Owner:
Priority:
Size:
Can Parallelize:

Goal:
Dependencies:
Affected modules:
Database changes:
API changes:
Frontend changes:
Worker changes:
Permission rules:
Audit events:
Test cases:
Acceptance:
Rollback:
```

## 10. 第一批可开工 Backlog

第一批不是“阶段 1”，而是 Production v1 中最先启动的一组强依赖任务。

| ID | Workstream | 任务 | 验收 |
| --- | --- | --- | --- |
| W1-I01 | W1 | FastAPI domain route 边界 ADR 对齐现有代码 | 新 route 不继续堆进巨型 `main.py` |
| W1-I02 | W1 | Repository 拆分边界 ADR 对齐现有 repository | 项目、权限、证据、报告 repository 职责清晰 |
| W1-I03 | W1 | Connector interface ADR | OpenAI/Perplexity/Google 都通过 adapter |
| W1-I04 | W1 | Evidence chain contract ADR | RawAnswer/Citation/EvidenceAsset/AuditEvent 链路冻结 |
| W1-I05 | W1 | 清除生产路径 demo fallback | 创建项目和报告不再写入示例品牌 |
| W1-I06 | W1 | 修复全量测试和端口冲突 | Gate W1 命令通过 |
| W2-I01 | W2 | Auth provider boundary 与 schema | OIDC-compatible，session 和邀请表可迁移 |
| W2-I02 | W2 | RBAC matrix 与 allow/deny tests | Client Viewer 越权返回 403 并审计 |
| W2-I03 | W2 | RLS 覆盖核心表 | tenant/project scope smoke 通过 |
| W3-I01 | W3 | Connector SDK spike | OpenAI/Perplexity/Google 返回结构、成本、失败分类样本落档 |
| W3-I02 | W3 | OpenAI 真实采集闭环 | 10 Prompt 真实采集写入证据链 |
| W3-I03 | W3 | Perplexity 真实采集闭环 | 10 Prompt 真实采集写入证据链 |
| W4-I01 | W4 | MinIO/S3 evidence asset 代理访问 | 客户仅能访问授权证据摘要或签名附件 |
| W5-I01 | W5 | AnswerAnalysis schema 和 parser baseline | parser output 可人工修正并审计 |
| W6-I01 | W6 | 最小正式报告模板 ADR | Markdown/PDF/CSV 字段和追溯口径冻结 |
| W9-I01 | W9 | Observability 基础 dashboard | API/worker/provider/cost/audit 指标可见 |
| W10-I01 | W10 | Production v1 E2E 脚本骨架 | 从空环境跑完整链路的脚本入口存在 |

## 11. 技术选型约束

本计划默认采用 [GEO技术选型与复用策略-2026-07-05.md](GEO技术选型与复用策略-2026-07-05.md) 和已接受 ADR 的结论：

- 身份认证：OIDC-compatible，生产优先 Keycloak 或托管 OIDC。
- 队列/工作流：近期统一 Python worker interface，生产长流程优先 Temporal。
- 对象存储：S3-compatible，dev/staging MinIO，production 可替换 S3/R2/MinIO。
- 向量和文本搜索：PostgreSQL + pgvector/full-text 起步。
- 图存储：PostgreSQL 邻接表起步，复杂后迁移 Neo4j/Jena。
- 文档解析：unstructured/Tika/PyMuPDF/docling 等 parser adapter。
- 报告渲染：Playwright HTML print 起步，必要时切换 WeasyPrint/Chromium service。
- 前端组件：Next.js/React/TypeScript，优先 shadcn/Radix、React Hook Form/Zod、TanStack Table、ECharts/Recharts、React Flow/Cytoscape。

自研范围只放在 GEO 业务契约、证据链、采集归一化、评分解释、报告口径、客户/运营工作流和审计语义。
