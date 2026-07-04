# GEO Production v1 可执行工程规划 v2

生成日期：2026-07-05

---

## 0. Scope Control Summary

Production v1 不是“功能完整的 GEO 平台”，而是一个**安全、可追溯、可采集、可评分、可报告、客户可访问、可运维的生产闭环**。

默认规则：

1. 任何不能直接改善安全、租户隔离、真实采集、证据链、评分解释、报告交付、客户访问或生产运维的能力，默认归为 P2。
2. P0 只能包含“不做就不能安全上线或产品不成立”的最小能力。
3. P1 只能包含“真实可用但可薄实现”的闭环能力。
4. P2 可以预留 schema、adapter 和 UI 入口，但不能阻塞 P0/P1。
5. Google browser/SERP、知识库、内容、分发、图谱高级可视化、额外平台都不能拖垮 P0 报告闭环。
6. Action Plan 和 Retest 放入 P0 的原因是为了闭环成立，但 P0 只能做极薄版本。
7. `make production-v1-e2e` 只覆盖 P0；KB / Content / Distribution 由 `make enablement-v1-e2e` 覆盖，不作为 P0 上线红线。

## 1. 总体执行原则

### 1.1 对外一个版本，对内多个生产切片

Production v1 对外只有一次正式上线，但内部必须拆成 8 个可运行生产切片：

1. Foundation Slice：工程基线、领域边界、测试、端口、文案、demo fallback 清理。
2. Identity Slice：Auth、Tenant、RBAC、RLS、Session、Invitation。
3. Collection Slice：OpenAI、Perplexity、Google manual、Google browser/SERP 决策、采集任务。
4. Evidence Slice：RawAnswer、Citation、EvidenceAsset、AuditEvent、Traceability。
5. Intelligence Slice：AnswerAnalysis、Human Review、Scoring、ScoreContribution、Citation Graph baseline。
6. Delivery Slice：ReportExport、PDF/CSV/Markdown、Report Approval、Customer Portal。
7. Optimization Slice：Action Plan、Retest、Alert、Trend。
8. Enablement Slice：Knowledge Base、Content Workbench、Distribution 回填。

这些不是外部发布阶段，而是内部施工单元。每个切片必须做到：

* 有真实数据库表。
* 有真实 API。
* 有真实权限检查。
* 有真实审计事件。
* 有真实对象存储或明确不需要对象存储。
* 有最小 UI 或 CLI / API 验证路径。
* 有自动化测试。
* 有可复现验收命令。
* 失败时可以定位到具体模块，而不是全局模糊失败。

### 1.2 Contract-first 强制优先

以下契约必须先冻结，再允许下游实现：

1. Auth Context Contract。
2. Tenant / Project Scope Contract。
3. RBAC Permission Contract。
4. Connector Backend Contract。
5. Collection Run State Contract。
6. Evidence Chain Contract。
7. AnswerAnalysis Output Contract。
8. Scoring Formula Contract。
9. ReportExport Contract。
10. Customer Portal Visibility Contract。
11. Audit Event Contract。
12. Worker Job Contract。

Codex 执行时，必须先改 schema、types、接口、测试，再改业务实现。禁止先堆页面或先堆临时 API。

### 1.3 垂直闭环优先于横向铺满

每个能力先做一个真实、薄、完整的生产闭环，再扩展广度。

错误做法：

```text
先把所有页面画完
先把所有平台字段建完
先把所有报告模板列完
先把所有知识库格式支持完
最后再接真实链路
```

正确做法：

```text
一个真实租户
  -> 一个真实用户
  -> 一个真实项目
  -> 10 个真实 Prompt
  -> OpenAI / Perplexity 真实采集
  -> RawAnswer / Citation / EvidenceAsset / AuditEvent
  -> AnswerAnalysis
  -> VisibilityScoreSnapshot / ScoreContribution
  -> ReportExport
  -> Customer Portal 已发布报告下载
  -> Action Plan
  -> Retest
```

闭环跑通后再扩展平台数、Prompt 数、竞品数、报告类型、内容类型和分发渠道。

---

## 2. Production v1 范围重定义

为避免 scope 爆炸，Production v1 仍保留完整目标，但按上线阻塞级别分为 P0、P1、P2。

这不是分版本发布，而是投产验收强弱分层。

### 2.1 P0：Production v1 必须完成，否则不得上线

P0 是 GEO Production v1 的硬核心。

P0 继续分为 P0-A / P0-B / P0-C / P0-D。四类都是上线硬门槛，但失败定位不同：

```text
P0-A 失败 = 系统不安全，不能继续扩大功能。
P0-B 失败 = 产品核心不成立，不能对客户交付报告。
P0-C 失败 = 上线不可运维，不能进入 production-internal。
P0-D 失败 = 优化闭环不成立，只允许缩到极薄版本，不允许拖垮 P0-B。
```

#### P0-A：不可没有，否则系统不安全

必须包含：

1. 真实 Auth / Tenant / RBAC / RLS。
2. AuthContext。
3. Session。
4. Tenant / Project scope。
5. Provider key protection。
6. AuditEvent。
7. EvidenceAsset permission proxy。
8. Customer portal 不依赖长期 URL query token。

#### P0-B：不可没有，否则产品不成立

必须包含：

1. Admin Web 内部项目和采集运营。
2. Customer Web 安全客户门户。
3. 项目、品牌、竞品、市场、Prompt 配置。
4. OpenAI 真实采集。
5. Perplexity 真实采集。
6. Google manual backfill 生产路径。
7. Google browser 或 SERP provider 至少完成一个 Go / No-Go 决策；如果 No-Go，必须以 manual backfill 作为 v1 官方 Google 路径，并在报告方法说明中披露。
8. RawAnswer / AnswerCitation / EvidenceAsset / AuditEvent。
9. AnswerAnalysis 自动解析。
10. Human Review 人工修正。
11. VisibilityScoreSnapshot / ScoreContribution。
12. Markdown / PDF / CSV ReportExport。
13. 报告审批、发布、撤回。
14. 客户安全查看和下载已发布报告。

#### P0-C：不可没有，否则上线不可运维

必须包含：

1. monitoring baseline。
2. alert baseline。
3. backup / restore smoke。
4. security-smoke。
5. production-v1-e2e。
6. 部署手册和回滚手册。

#### P0-D：可薄到极限，但必须闭环

Action Plan P0 minimal：

1. 至少生成 3 类确定性建议：
   * brand not mentioned。
   * competitor outranks brand。
   * missing / weak citation source。
2. 每条 action 必须链接到 score contribution 或 evidence。
3. customer visibility 默认 false。
4. 只要求人工 owner/status update，不要求复杂 workflow。

Retest P0 minimal：

1. 可对同一 prompt set 重新运行一个平台或选定平台。
2. 创建新的 score snapshot。
3. 对比展示 `before_score`、`after_score`、`delta`。
4. Retest report section 初始允许 Markdown-only。
5. 不要求复杂 durable workflow，不要求多轮统计显著性。

### 2.2 P1：Enablement v1 增强闭环，不阻塞 P0 正式上线

P1 不允许是假页面，不允许 fixture，但不作为 P0 上线红线。P1 是否完成由 `make enablement-v1-e2e` 单独验收。

必须包含薄闭环：

1. Knowledge Base：

   * 支持 Markdown / TXT / PDF 至少一种文件导入。
   * 支持 URL 手动录入或页面文本导入。
   * 支持 knowledge_facts。
   * 支持 fact 状态：draft / approved / deprecated / forbidden。
   * 只有 approved facts 能进入内容建议。

2. Content Workbench：

   * 支持从 Action Plan 创建 content task。
   * 支持基于 approved facts 生成 brief 或 draft。
   * 支持人工审核。
   * 支持版本记录。
   * 支持导出 Markdown。

3. Distribution task：

   * 支持人工分发任务。
   * 支持渠道、负责人、计划发布时间、发布 URL 回填。
   * 支持发布证明附件或 URL。
   * 支持关联 Action Plan 和 Retest。

P1 的目标不是做全自动内容营销平台，而是在 P0 报告闭环稳定后证明：

```text
报告发现问题
  -> 生成行动项
  -> 进入知识事实
  -> 生成内容建议
  -> 人工审核
  -> 人工发布回填
  -> 关联复测
```

### 2.3 P2：Post-GA 扩展项，不阻塞 P0/P1

以下能力不阻塞 P0 正式上线，也不阻塞 P1 Enablement 薄闭环：

1. 所有渠道自动发布。
2. Gemini / Bing Copilot / Claude / DeepSeek / 豆包 / Kimi / 腾讯元宝 / 百度文小言等额外平台。
3. Neo4j / OpenSearch / ClickHouse 等中期架构替换。
4. 高级 Citation Graph 可视化。
5. 多报告模板全面铺开。
6. 全格式文档解析。
7. 多语言内容工作台深度能力。
8. 高级统计显著性模型。
9. 全自动 SERP vendor 多供应商比较。
10. 复杂组织级 SSO 策略。

P2 可以预留 schema 和 adapter，但不能影响 P0 / P1 的稳定交付。

---

## 2.4 Slice Completion Matrix

8 个生产切片是内部施工单元；W1-W10 是工程工作流；Gate 是验收命令和阻断条件。任何任务必须能落到下表之一。

| Slice | 主工作流 | 横切工作流 | 完成条件 |
| --- | --- | --- | --- |
| Foundation | W1 | W10 | W1-I01 done；W1-I02 done；W1-I03 done；W10-I01 skeleton exists；`make runtime-e2e` 在 production config 下不依赖 fixture production path |
| Identity | W2 | W1/W10 | W2-I01a / W2-I01b / W2-I01c / W2-I01d / W2-I01e done；W2-I02 done；W2-I03a / W2-I03b / W2-I03c done；`make rls-smoke` passes；`make security-smoke` identity subset passes |
| Collection | W3 | W4/W9/W10 | W3-I00 done；W3-I01 done；W3-I02 done；W3-I03 done；W3-I04 done；staging `make connector-real-smoke` passes；provider failure classification exists；provider secret never appears in API/log/frontend/report |
| Evidence | W4 | W2/W10 | W4-I01a / W4-I01b / W4-I01c / W4-I01d done；EvidenceAsset proxy enforces scope；Traceability chain tests pass；audit required tests pass |
| Intelligence | W5 | W4/W10 | W5-I01 done；W5-I02a / W5-I02b / W5-I02c done；AnswerAnalysis review tests pass；ScoreContribution traceability tests pass |
| Delivery | W6 | W2/W4/W5/W10 | W6-I01a / W6-I01b / W6-I01c / W6-I01d / W6-I01e / W6-I01f done；published report download succeeds；revoked/unpublished report denied；report security tests pass |
| Optimization | W7 | W5/W6/W10 | W7-I01 P0 minimal done；W7-I02 P0 minimal done；action links to evidence/score contribution；retest creates before/after/delta |
| Enablement | W8 | W4/W7/W10 | W8-I01 done；W8-I02 done；W8-I03 done；approved facts only；distribution links forward to retest |

Ops 不是单独 slice，而是每个 slice 的横切门禁。W9 的监控、备份、告警、secret、部署手册必须从第一天开始，且在 Final Gate 前全部通过。

QA 也不是单独 slice，而是每个 slice 的验收机制。W10-I01 `production-v1-e2e` skeleton 必须最早创建，后续每完成一个 slice 就把 pending step 变成真实断言。

### 2.5 P0 前必须冻结的技术决策

以下技术点在 W1/W2 可以边做边验证，但进入 W3/W4/W5 前必须冻结；否则真实采集、证据链、评分和报告会互相返工。

| 编号 | 技术点 | P0 冻结决策 | 不进入 P0 的内容 |
| --- | --- | --- | --- |
| TD-01 | Deployment target | P0 默认部署目标是 single VM / small VM group 上的 Docker Compose：API、Admin Web、Customer Web、Dashboard Web、workers、Valkey、observability 同栈运行；PostgreSQL 和对象存储可用 compose 本地服务或托管等价服务，但必须走同一 adapter。入口建议用 Traefik/Caddy/Nginx 反代，admin/customer/dashboard/api 使用同一 parent domain 的子域。 | Kubernetes、ECS/Fargate、Vercel split hosting、multi-region HA 不阻塞 P0。 |
| TD-02 | Worker queue | P0 使用 Dramatiq + Valkey 作为生产队列；保留现有 Python CLI worker 作为 local/dev/manual entrypoint。必须支持 retry、idempotency lock、provider concurrency limit、failure category、dead-letter equivalent failed job table。 | Temporal 不作为 P0 依赖；等 Retest/Distribution 需要长流程补偿时再评估。 |
| TD-03 | Provider secret storage | P0 使用 DB encrypted column + `connector_config_ref` + `secret_ref` + app-level redaction；raw key 只允许以加密密文进入 DB，不允许进入 API response、日志、前端 bundle、报告或 audit payload。`SecretStore` 必须是 adapter，预留外部 secret manager。 | 重型外部 secret manager 不阻塞 P0；env var 只允许作为 dev/test 或少量内部 bootstrap key。 |
| TD-04 | Object storage | P0 使用 S3-compatible adapter：local/staging 默认 MinIO，production 可接 S3/R2/MinIO 等兼容后端。DB 存 metadata/hash/visibility，客户下载走 backend permission proxy；内部大文件可由 API 授权后签发短期 signed URL。 | 直接把 bucket URL 暴露给客户、绕过 API 权限代理不允许。 |
| TD-05 | Session / Cookie / CSRF | P0 使用 server-side session hash；cookie 必须 `httpOnly + secure + sameSite=Lax`；session TTL 默认 7 days；invitation token one-time use；所有 unsafe mutation 请求要求 CSRF header；session revoke 必须实时生效；默认允许多设备登录但必须可按 session revoke。 | 长期 URL query token、localStorage token、无 CSRF 的跨子域 mutation 不允许。 |
| TD-06 | RLS scope injection | P0 使用单 app DB role + request transaction 内 `SET LOCAL app.actor_id / app.tenant_id / app.project_ids / app.roles / app.is_system_actor`；RLS policy 读取 `current_setting()`；maintenance migration/backfill 使用独立 maintenance role。system actor 默认也必须带 tenant/project scope，只有审计过的 maintenance job 例外。 | DB role per tenant 不作为 P0；全局关闭 RLS 跑测试不允许。 |
| TD-07 | PDF renderer | P0 使用 HTML template + Playwright/Chromium 生成 PDF；Markdown/CSV/PDF 必须来自同一 ReportExport snapshot。Docker 镜像必须固定中文字体，默认 Noto Sans CJK；渲染时禁止外部网络依赖。 | WeasyPrint、ReportLab、Pandoc 可以作为后续替代方案，不阻塞 P0。 |
| TD-08 | AnswerAnalysis parser | P0 优先 deterministic parser；可选 LLM structured extraction，但必须有 versioned schema、raw output hash、audit event 和 human review override。`wrong facts` / `negative sentiment` 没有可靠 extraction 时只能 human-review-only 或 P1/P2。 | 不允许用不可复盘的 LLM 文本直接写正式报告数字。 |
| TD-09 | Scoring formula v1.0 | P0 固定 `formula_version=visibility_v1.0`：Trigger 20%，Brand Mention 30%，Recommendation 30%，Citation Strength 10%，Competitor Relative Position 10%。平台默认等权；Prompt intent 默认等权，除非 prompt_version 明确配置权重。 | 高级统计显著性、多模型动态权重不阻塞 P0。 |
| TD-10 | Observability / Alert | P0 使用 structured JSON logs、health endpoints、Prometheus-style `/metrics`、OpenTelemetry instrumentation points、Slack webhook/email alert baseline。Sentry 可以接入但不是 P0 阻塞。 | 全链路 tracing、Langfuse、复杂 incident platform 不阻塞 P0。 |
| TD-11 | Backup / Restore | P0 备份范围包含 PostgreSQL、object storage evidence/report/upload assets、encrypted secret material 所需的 master key ref/runbook。默认 RPO <= 24h，production-internal RTO <= 4h。必须有 restore smoke。 | 多区域热备不阻塞 P0。 |
| TD-12 | Google Browser / SERP | P0 不依赖 Google automated collection，只依赖 Go/No-Go 决策报告。官方 Google 路径是 manual backfill；browser/SERP 通过 Go 条件后才能成为 production path。 | 不能因为 browser/SERP No-Go 阻塞 P0 报告闭环。 |

### 2.6 P0 默认参数和接口口径

这些默认值可以通过配置调整，但必须有 config version、audit event 和回滚说明。

1. OpenAI connector：
   * 默认 endpoint：Responses API。
   * 默认能力：`web_search` tool。
   * 默认 citation 解析：`web_search_call` output item + message content annotations 中的 `url_citation`。
   * 推荐初始模型：`gpt-5.5`，但不在业务代码硬编码；由 `connector_configs.model` 指向当前批准的 OpenAI web-search capable model。首次部署必须在 config 中显式写入，并由 connector health 验证 citation shape。
2. Perplexity connector：
   * 默认 endpoint：`POST https://api.perplexity.ai/v1/sonar`。
   * 默认 model：`sonar-pro`。
   * 默认 citation 解析：response `citations[]`、`search_results[]`、`usage.cost`。
   * 如果 provider 返回 cost，使用 provider cost；否则使用 connector rate card 估算并标记 `cost_method=estimated`。
3. Google manual backfill：
   * 必填：prompt、answer text、surface_triggered、answer_present、screenshot or URL、reviewer、access_method、collected_at。
   * Google automated No-Go 时，报告必须披露 manual structured backfill 方法和局限。
4. CSV schema：
   * Prompt import CSV：`prompt_text, intent, market, city, language, device, weight, tags`。
   * Report CSV：`prompt_id, prompt_text, platform, answer_present, brand_mentioned, competitor_mentions, recommendation_state, citation_count, score_contribution_ids`。
5. Retention：
   * ReportExport assets 默认保留 24 months。
   * EvidenceAsset 默认保留 24 months；客户合同要求更短时以 tenant policy 覆盖。
   * AuditEvent 默认保留 36 months。
6. Upload limits：
   * Google manual screenshot 单文件默认 20 MB。
   * Knowledge import P1 默认 50 MB。
   * 超限必须走对象存储 direct upload + backend metadata commit。
7. URL import security：
   * 默认禁止 private IP、localhost、link-local、metadata service、file scheme。
   * 只允许 `http` / `https`。
   * 必须有 SSRF blocklist + tenant allowlist。
8. Prompt versioning：
   * Prompt 文本、intent、market/city/language/device、weight 任一变化，创建新 `prompt_version_id`。
   * 历史 report 固定引用旧 prompt_version，不随当前 prompt 修改。
9. Retest：
   * 默认复用同一 prompt_version_id。
   * 默认比较 total_score、platform_score、prompt-level contribution delta。
   * 城市 / intent delta 在数据存在时展示，否则显示 limitation。
10. Human Review override：
    * 每次 override 创建新 review version。
    * 允许二次修改，但必须保留旧值、修改人、修改原因、audit event。

### 2.6.1 P0 部署拓扑默认值

P0 默认 runtime 拓扑：

```text
edge proxy: Traefik/Caddy/Nginx
api: FastAPI
admin-web: Next.js
customer-web: Next.js
dashboard-web: Next.js
workers: Dramatiq workers
queue: Valkey
db: PostgreSQL
object-storage: MinIO locally, S3-compatible production
observability: Prometheus-style metrics + Grafana dashboard + JSON logs
```

默认域名关系：

```text
admin.<root-domain>
customer.<root-domain>
dashboard.<root-domain>
api.<root-domain>
```

如果本地开发使用 localhost 多端口，必须在 staging / production-internal 再跑一次真实 cookie/CORS/CSRF smoke。生产部署不得依赖浏览器访问 `localhost`。

### 2.7 不阻塞 P0 的技术点

以下内容只能作为 P1/P2 设计边界，不能作为 P0 阻塞项：

1. Knowledge Base 的 PDF 解析深度。
2. Content Workbench 具体生成模型。
3. Distribution 是否接 CMS / social API。
4. Citation Graph 是否升级到 Neo4j / OpenSearch / ClickHouse。
5. 高级统计显著性模型。
6. 多 SERP vendor 自动比较。
7. 复杂 SSO。
8. 额外平台 Gemini / Claude / DeepSeek / 豆包 / Kimi / 腾讯元宝 / 百度文小言等。

## 3. 可行性提升目标

### 3.1 工程可行性从 6.5 提升到 9 的方法

必须做到：

1. 每个 workstream 都有 contract。
2. 每个 contract 都有 contract test。
3. 每个核心 API 都从 AuthContext 推导 tenant/project scope。
4. 每个核心写操作都有 audit event。
5. 每个客户可见数字都能追溯到 Evidence。
6. 每个外部 connector 都通过统一 adapter。
7. 每个 worker job 都有 idempotency key。
8. 每个 report export 都不可覆盖。
9. 每个对象存储 asset 都有 hash、content_type、size、scope、policy。
10. 每个 gate 都有自动化命令。

工程可行性达到 9 的判定：

```text
新工程师或 Codex 只看本规划，即可按 issue 顺序推进；
每个 issue 的输入、输出、依赖、验收、回滚都明确；
失败时能定位到具体 slice / contract / test；
不会因为一个模块未完成导致全局无法验证。
```

### 3.2 交付可行性从 4 提升到 9 的方法

必须做到：

1. 对外仍是一个 Production v1，但内部每天都能跑局部闭环。
2. P0 明确是上线硬门槛。
3. P1 明确是薄闭环，不无限扩展。
4. P2 明确不阻塞上线。
5. Google browser/SERP 不确定性被 Go / No-Go 隔离。
6. Knowledge / Content / Distribution 不拖垮核心报告闭环。
7. 每个切片都有演示脚本。
8. 每个切片都有红线条件。
9. 最终验收是组合已有切片，而不是首次整体集成。

交付可行性达到 9 的判定：

```text
任何时点都知道当前离投产还差哪些明确 gate；
任何未完成项都能判断是否阻塞上线；
任何阻塞项都有 owner、修复范围、验收命令；
最终上线演练不是第一次跑全链路。
```

---

## 4. 目标系统最小生产闭环

Production v1 必须优先跑通以下链路：

```text
Super Admin 创建租户
  -> Tenant Admin 邀请用户
  -> 用户兑换邀请并登录
  -> Project Owner 创建项目
  -> 配置品牌、竞品、市场、语言、城市、Prompt
  -> 配置 OpenAI / Perplexity connector
  -> 执行真实采集
  -> 写入 RawAnswer / Citation / EvidenceAsset / AuditEvent
  -> parser 生成 AnswerAnalysis
  -> Analyst 人工修正
  -> scoring worker 生成 VisibilityScoreSnapshot / ScoreContribution
  -> report worker 生成 Markdown / PDF / CSV
  -> Reviewer 审批报告
  -> Project Owner 发布报告
  -> Client Viewer 登录 Customer Portal
  -> 客户查看并下载已发布报告
  -> 系统记录访问审计
  -> 生成 Action Plan
  -> 触发 Retest
  -> 生成复测报告
```

这条链路不完整，不允许宣称 Production v1 完成。

---

## 5. Codex 执行规则

### 5.1 每次 Codex 任务只允许触碰有限范围

单个 Codex 任务默认只允许修改：

* 一个 domain。
* 一个 schema / migration。
* 一组 tests。
* 一个 UI surface。
* 一个 worker。
* 一个 doc。

如需跨多个 domain，必须在任务中明确列出 affected modules。

### 5.2 Codex Task Size Policy

任务必须按可控变更规模拆分：

| Size | 文件数量上限 | 允许范围 | 规则 |
| --- | --- | --- | --- |
| S | <= 5 files | 单一 contract、单一 repository、单一测试组、小 UI 修正 | 默认优先 |
| M | <= 12 files | 一个 domain 的 schema/API/repository/tests，或一个窄 worker | 可以直接执行 |
| L | <= 25 files | 一个完整薄闭环，但必须有明确 contract 和测试边界 | 需要在任务说明中列出 affected modules |
| XL | > 25 files 或跨 3 个以上 domain | 报告全链路、Auth 全链路、采集全链路等 | 默认禁止，必须拆分；除非用户明确批准 |

拆分原则：

1. 先 contract/types/schema，再 repository，再 API，再 worker，再 UI，再 e2e。
2. 每个任务最多引入一个 migration。
3. 每个任务最多改变一个主要业务状态机。
4. 任一任务如果同时包含 DB、API、worker、Admin UI、Customer UI、security tests，必须拆。
5. XL 任务不能直接交给 Codex 执行，只能先拆成 S/M/L 子任务。

### 5.3 每次 Codex 任务必须输出

每个任务必须完成：

1. 代码修改。
2. 测试修改。
3. 文档修改。
4. 验收命令。
5. 回滚说明。
6. 已知风险。
7. 未完成项。

### 5.4 禁止行为

Codex 不允许：

1. 用 fixture 伪装生产链路。
2. 为了测试通过删除测试。
3. 跳过 RLS / RBAC 检查。
4. 在 API response 中返回 provider key。
5. 在日志中打印 token、session、provider key。
6. 把新业务继续堆进巨型 main.py。
7. 把所有 repository 写进单一 repository.py。
8. 写只有 UI 无真实 API 的“完成项”。
9. 生成不可追溯报告数字。
10. 让客户通过长期 query token 访问报告。

---

## 6. 领域架构落地顺序

### 6.1 目录目标

后端目标结构：

```text
apps/api/geno_api/
  domains/
    auth/
    tenants/
    projects/
    prompts/
    connectors/
    collection/
    evidence/
    analysis/
    scoring/
    reports/
    actions/
    knowledge/
    content/
    distribution/
    alerts/
    audit/
    admin/
  core/
    auth_context.py
    permissions.py
    rls.py
    database.py
    settings.py
    errors.py
  schemas/
  main.py
```

核心包目标结构：

```text
packages/geno_core/geno_core/
  repositories/
    tenant_repository.py
    access_control_repository.py
    project_repository.py
    prompt_repository.py
    connector_repository.py
    collection_repository.py
    evidence_repository.py
    analysis_repository.py
    scoring_repository.py
    report_repository.py
    action_repository.py
    knowledge_repository.py
    content_repository.py
    distribution_repository.py
    audit_repository.py
  contracts/
    auth_context.py
    connector.py
    collection.py
    evidence.py
    analysis.py
    scoring.py
    reporting.py
    audit.py
  services/
```

### 6.2 拆分顺序

不要一次性重构所有 repository。按以下顺序拆：

1. audit_repository。
2. access_control_repository。
3. tenant_repository。
4. project_repository。
5. connector_repository。
6. collection_repository。
7. evidence_repository。
8. analysis_repository。
9. scoring_repository。
10. report_repository。
11. action_repository。
12. knowledge_repository。
13. content_repository。
14. distribution_repository。

每拆一个 repository，必须有：

* 原测试迁移。
* 新单元测试。
* 至少一个 integration test。
* SQL 参数化检查。
* actor / scope 参数检查。
* audit context 传递检查。

---

## 7. 核心契约定义

### 7.1 AuthContext Contract

所有受保护 API 必须使用统一 AuthContext：

```text
AuthContext:
  actor_id
  actor_type: user | system | service
  tenant_id
  project_ids
  roles
  permissions
  session_id
  request_id
  ip_hash
  user_agent_hash
```

规则：

1. 普通用户不能从 request body 指定 tenant_id 来越权。
2. project_id 必须通过 membership 或 system permission 校验。
3. system actor 必须有 service name 和 reason。
4. 所有写操作必须携带 request_id。
5. 审计事件必须记录 actor、scope、action、target、outcome。

验收测试：

```text
tests/auth/test_auth_context.py
tests/security/test_scope_derivation.py
tests/audit/test_auth_context_audit.py
```

### 7.2 Permission Contract

权限格式：

```text
resource.action
```

示例：

```text
tenant.create
tenant.read
tenant.update
tenant.disable
member.invite
project.create
project.read
project.update
project.archive
prompt.import
collection.run
evidence.read_summary
evidence.read_raw
analysis.review
score.read
score.configure
report.read
report.generate
report.approve
report.publish
report.revoke
report.download
action.manage
action.read
retest.run
retest.read
knowledge.read
knowledge.import
knowledge.review
knowledge.read_approved
content.read
content.update
content.generate
content.review
distribution.read
distribution.create
distribution.update
audit.read
connector.manage
system.admin
```

规则：

1. 角色只能引用 permission vocabulary 中已声明的权限。
2. `published-only`、`customer-visible`、`internal-only` 是权限条件，不是独立 permission。
3. 新增 API 前必须先补 permission vocabulary 和 RBAC matrix test。
4. 未声明 permission 一律视为 deny。

角色默认权限：

```text
Super Admin:
  all permissions

Tenant Admin:
  tenant.read
  tenant.update
  member.invite
  project.create
  project.read
  project.update
  report.read
  audit.read tenant-scoped

Project Owner:
  project.read
  project.update
  prompt.import
  collection.run
  evidence.read_summary
  analysis.review
  score.read
  report.generate
  report.publish
  action.manage
  retest.run

Analyst:
  project.read
  prompt.import
  collection.run
  evidence.read_summary
  evidence.read_raw internal-only
  analysis.review
  score.read
  report.generate
  action.manage

Reviewer:
  project.read
  report.read
  report.approve
  report.revoke
  content.review

Knowledge Architect:
  project.read
  knowledge.import
  knowledge.review
  content.read

Content Operator:
  project.read
  knowledge.read_approved
  content.generate
  content.update
  distribution.create

Client Viewer:
  project.read customer-visible
  score.read published-only
  report.download published-only
  action.read customer-visible
  retest.read published-only
```

验收测试：

```text
tests/security/test_rbac_matrix.py
tests/security/test_customer_portal_access.py
tests/security/test_provider_key_access_denied.py
```

### 7.3 Connector Contract

所有 connector 必须实现：

```text
ConnectorBackend:
  health(config_ref) -> ConnectorHealth
  validate_config(config_ref) -> ValidationResult
  estimate_cost(collection_request) -> CostEstimate
  collect(collection_request) -> CollectionResult
  normalize_response(raw_provider_response) -> NormalizedAnswer
  archive_evidence(normalized_answer) -> EvidenceArchiveResult
```

CollectionRequest：

```text
tenant_id
project_id
platform
surface
access_method
prompt_id
prompt_version_id
prompt_text
market
city
language
device
sample_index
sample_size
connector_config_ref
run_id
idempotency_key
```

CollectionResult：

```text
status: succeeded | failed | skipped | cancelled
answer_present
surface_triggered
raw_text
citations
raw_payload_hash
evidence_asset_refs
cost
duration_ms
failure_category
failure_message_sanitized
provider_request_id
collector_version
```

失败分类：

```text
auth_failed
quota_exceeded
rate_limited
timeout
network_error
provider_5xx
provider_4xx
parse_failed
no_answer
surface_not_triggered
blocked_by_policy
manual_required
unknown
```

验收测试：

```text
tests/connectors/test_connector_contract.py
tests/connectors/test_openai_connector_real_or_recorded.py
tests/connectors/test_perplexity_connector_real_or_recorded.py
tests/connectors/test_google_manual_backfill.py
```

真实外部调用测试必须允许在无 key 环境下 skip，但 staging / production-internal gate 必须运行真实采集验收。

### 7.3.1 Connector 默认实现口径

OpenAI connector：

1. P0 默认使用 Responses API。
2. P0 默认启用 `web_search` tool。
3. citation 解析必须支持：
   * `web_search_call` output item。
   * message content annotations 中的 `url_citation`。
   * cited URL、title、start/end location。
4. 默认模型不写死在代码里，必须来自 `connector_configs.model`。
5. 推荐初始模型是 `gpt-5.5`；如改用其他 OpenAI web-search capable model，必须更新 connector config version 和 audit event。
6. connector health 必须验证返回结构是否含可解析 citation shape。

Perplexity connector：

1. P0 默认 endpoint：`POST https://api.perplexity.ai/v1/sonar`。
2. P0 默认 model：`sonar-pro`，可通过 connector config 覆盖。
3. citation 解析必须支持 response `citations[]`、`search_results[]` 和 provider request id。
4. cost 优先使用 provider 返回值；缺失时用 connector rate card 估算，并设置 `cost_method=estimated`。
5. rate limit 必须归类为 `rate_limited`，不得混入 unknown。

Google manual connector：

1. P0 是官方 Google 路径。
2. 必填字段：prompt、answer text、surface_triggered、answer_present、screenshot or URL、reviewer、access_method、collected_at。
3. manual backfill 必须写 `manual_required` 或 `manual_backfill` access marker。
4. Browser/SERP No-Go 时，报告必须披露 manual structured backfill 方法和局限。

OpenAI web search citation shape 以 OpenAI 官方文档为准：Responses API web search 输出包含 `web_search_call`，最终 message content annotations 包含 URL citation；UI 展示 web results 时必须让 inline citations 清晰可见、可点击。

### 7.4 Evidence Chain Contract

证据链必须支持：

```text
ReportExport
  -> VisibilityScoreSnapshot
  -> ScoreContribution
  -> AnswerAnalysis
  -> AnswerRun
  -> RawAnswer
  -> AnswerCitation
  -> EvidenceAsset
  -> AuditEvent
```

核心字段：

```text
raw_answers:
  id
  tenant_id
  project_id
  answer_run_id
  platform
  surface
  access_method
  prompt_version_id
  raw_text
  raw_payload_hash
  created_at

answer_citations:
  id
  tenant_id
  project_id
  raw_answer_id
  url
  domain
  title
  snippet
  position
  source_type
  normalized_url_hash

evidence_assets:
  id
  tenant_id
  project_id
  related_type
  related_id
  storage_uri
  storage_key
  sha256
  size_bytes
  content_type
  access_policy
  retention_policy
  created_by
  created_at

audit_events:
  id
  tenant_id
  project_id nullable
  actor_id
  actor_type
  action
  target_type
  target_id
  outcome
  request_id
  metadata_sanitized
  created_at
```

验收测试：

```text
tests/evidence/test_traceability_chain.py
tests/evidence/test_evidence_asset_permissions.py
tests/audit/test_audit_event_required.py
```

### 7.5 Scoring Contract

评分必须输出：

```text
VisibilityScoreSnapshot:
  id
  tenant_id
  project_id
  formula_version
  scoring_profile_id
  sample_window_start
  sample_window_end
  total_score
  platform_scores
  city_scores
  intent_scores
  sample_counts
  limitations
  created_at
```

ScoreContribution：

```text
id
snapshot_id
answer_analysis_id
metric
weight
raw_value
normalized_value
contribution
positive_evidence
negative_evidence
explanation
```

评分规则：

1. Trigger、Mention、Recommendation 分母必须分离。
2. 无触发和触发无回答不能混为一类。
3. 平台、城市、intent、竞品必须可 drill down。
4. 每个分数必须能解释来源。
5. 公式变更必须产生新 formula_version。
6. 报告必须固定引用某一个 snapshot，不能动态变动。

P0 固定公式 `formula_version=visibility_v1.0`：

```text
total_score =
  trigger_score * 0.20
  + brand_mention_score * 0.30
  + recommendation_score * 0.30
  + citation_strength_score * 0.10
  + competitor_relative_position_score * 0.10
```

默认计算口径：

1. 平台默认等权；Google manual 与 OpenAI / Perplexity 同权，但报告必须披露 access_method。
2. 城市默认等权；如果项目配置 city weight，必须写入 scoring_profile。
3. Prompt intent 默认等权；如果 prompt_version 配置 weight，必须固定到 snapshot。
4. `surface_not_triggered` 进入 trigger 分母，但不进入 answer_present 后续指标分母。
5. `answer_present=false` 时，mention / recommendation / citation_strength 记为不可计算，不得当成 0 混入错误分母。
6. `no_answer` 与 `surface_not_triggered` 必须分开统计。
7. competitor_relative_position 只有在 `recommended_entities_ordered[]` 或 `entity_positions[]` 可追溯时计算；否则权重重分配到 recommendation_score，并在 limitations 披露。

验收测试：

```text
tests/scoring/test_score_formula_version.py
tests/scoring/test_score_contributions_traceable.py
tests/scoring/test_trigger_mention_recommendation_denominators.py
```

### 7.6 Report Contract

ReportExport：

```text
id
tenant_id
project_id
report_type
status: draft | pending_review | approved | published | revoked | failed
version
snapshot_id
methodology_version
markdown_asset_id
pdf_asset_id
csv_asset_id
evidence_appendix_asset_id internal-only
published_at
revoked_at
created_by
approved_by
```

规则：

1. ReportExport 不可覆盖。
2. 重新生成必须创建新 version。
3. 客户只能访问 published 且未 revoked 的报告。
4. 下载必须走后端权限代理。
5. 每次查看和下载都写 audit event。
6. 报告中不得包含 provider key、内部 actor、未脱敏 raw payload。
7. Markdown / PDF / CSV 必须来自同一 ReportExport snapshot。
8. PDF 使用 HTML template + Playwright/Chromium 渲染，Docker 镜像必须固定中文字体，默认 Noto Sans CJK。
9. PDF 渲染禁止依赖外部网络资源；图表、字体、样式必须随 artifact 或镜像固定。
10. CSV schema 必须稳定，字段新增只能 additive。

验收测试：

```text
tests/reports/test_report_export_immutable.py
tests/reports/test_report_publish_revoke.py
tests/customer/test_customer_report_download_permissions.py
```

### 7.7 Tenant / Project Scope Contract

所有核心数据访问必须明确 scope：

```text
Scope:
  tenant_id
  project_id nullable
  actor_id
  actor_type
  roles
  permissions
  source: session | system_actor | service_job
```

规则：

1. `tenant_id` 只能来自 session、membership、system actor 或可信 job，不允许来自未校验 request body。
2. 项目级 API 必须同时校验 tenant membership 和 project membership。
3. system actor 必须携带 reason、job_id 或 service_name。
4. Repository 方法必须接受 scope 或显式 system scope，不能隐式跨租户查询。
5. scope derivation 失败必须返回 401/403 并写 audit event。

### 7.8 Collection Run State Contract

collection run 状态：

```text
collection_run.status:
  draft
  queued
  running
  partially_succeeded
  succeeded
  failed
  cancelled

answer_run.status:
  queued
  running
  succeeded
  failed
  skipped
  cancelled
```

规则：

1. retry 必须使用 idempotency_key，不允许重复写同一 prompt/sample 的成功结果。
2. 部分 prompt 成功、部分失败时，collection_run 必须是 `partially_succeeded`。
3. `failed` 必须有 sanitized failure_category 和 failure_message。
4. `cancelled` 不允许继续写新的 answer_run。
5. Google manual backfill 进入 scoring 前必须经过 review/approval。
6. 每个状态变化必须写 audit event。

### 7.9 AnswerAnalysis Output Contract

P0 parser 输出必须覆盖报告和 Action Plan 所需字段：

```text
AnswerAnalysis:
  id
  answer_run_id
  parser_version
  brand_mentions[]
  competitor_mentions[]
  entity_positions[]
  recommendation_state
  recommended_entities_ordered[]
  citation_domains[]
  citation_strength
  unsupported_claims[]
  sentiment_label optional
  fact_risk_label optional
  local_relevance_label optional
  limitations[]
```

P0 报告只允许使用上述字段中可追溯、可计算的指标。`average position`、`share of voice`、`wrong facts`、`negative sentiment` 等字段如果缺少足够输入，必须展示为 limitation 或进入 P1/P2，不允许伪造。

### 7.10 Customer Portal Visibility Contract

客户可见性由资源状态、项目授权和字段脱敏共同决定：

```text
CustomerVisible(resource):
  tenant_id matches session
  project_id in viewer projects
  resource.status is published/customer_visible
  resource.revoked_at is null
  field policy allows customer
```

规则：

1. Client Viewer 只能看到 published 且未 revoked 的 report。
2. Client Viewer 只能看到 customer-safe evidence summary，不能看 raw provider payload。
3. Action 默认 customer_visible=false。
4. Retest result 只有在 linked report published 后客户可见。
5. 拒绝访问必须写 `customer.access_denied` audit event。

### 7.11 Audit Event Contract

AuditEvent 是 P0-A 基础设施，必须第一批迁移落地。

```text
AuditEvent:
  id
  tenant_id
  project_id nullable
  actor_id
  actor_type
  action
  target_type
  target_id
  outcome: allowed | denied | succeeded | failed
  request_id
  job_id nullable
  metadata_sanitized
  created_at
```

规则：

1. audit metadata 不允许包含 provider key、session token、invitation token、raw credential。
2. Auth、RBAC deny、connector config、collection state change、evidence access、analysis review、score snapshot、report lifecycle、customer download、action/retest 都必须写 audit。
3. audit 写失败时，安全敏感操作必须 fail closed。
4. 客户只能看到脱敏访问摘要，不能看到内部 actor 细节。

---

## 8. 数据库落地策略

### 8.1 Migration 分批顺序

不要一次 migration 创建所有表。按依赖顺序：

1. users / tenants / tenant_members / project_members / invitations / sessions / audit_events。
2. projects / brands / brand_aliases / competitors / competitor_aliases / market_profiles。
3. platforms / connector_configs。
4. prompt_questions / prompt_versions / prompt_imports。
5. collection_plans / collection_runs / answer_runs / collection_costs。
6. raw_answers / answer_citations / evidence_assets / evidence_links / collector_logs。
7. answer_analyses / human_review_records / entity_aliases。
8. scoring_profiles / visibility_score_snapshots / score_contributions。
9. source_graphs / source_nodes / source_gaps / competitor_benchmarks。
10. report_tasks / report_exports。
11. action_recommendations / action_tasks / retest_runs。
12. knowledge_documents / knowledge_facts。
13. content_assets / content_reviews。
14. distribution_tasks。
15. alert_rules / runtime_notifications / runtime_http_access_logs。
16. reserved for later cross-cutting indexes, retention jobs, or audit/evidence backfills only.

### 8.2 RLS 策略

所有 tenant-scoped 表必须有：

```sql
tenant_id UUID NOT NULL
```

所有 project-scoped 表必须有：

```sql
tenant_id UUID NOT NULL
project_id UUID NOT NULL
```

RLS 原则：

1. 普通用户只能访问自己的 tenant。
2. 项目表必须同时校验 tenant_id 和 project membership。
3. Client Viewer 只能访问 customer-visible 数据。
4. provider key 表默认仅 system / connector.manage 可访问。
5. audit_events 默认仅内部角色访问，客户只能看到脱敏访问摘要。
6. API request 必须在单个 DB transaction 内设置：
   * `SET LOCAL app.actor_id`
   * `SET LOCAL app.tenant_id`
   * `SET LOCAL app.project_ids`
   * `SET LOCAL app.roles`
   * `SET LOCAL app.is_system_actor`
7. RLS policy 只读取 `current_setting()` 和行内 tenant/project 字段，不读取未校验 request body。
8. maintenance migration/backfill 使用独立 maintenance role；不能借 system actor 绕过业务审计。
9. system actor 默认仍需要 tenant/project scope，只有明确标记、审计过的 maintenance job 可以跨 scope。

验收：

```bash
make db-smoke
make rls-smoke
```

如果当前没有 `make rls-smoke`，必须新增。

### 8.3 Migration Safety Policy

现有系统已经有表和历史数据，迁移必须优先安全增量，不允许为了新规划直接重排或破坏旧数据。

迁移规则：

1. Prefer additive migrations：优先新增表、列、索引、约束，不直接删除或重命名生产字段。
2. No destructive migration without backup and rollback plan：任何删除、重命名、类型收窄、数据清理都必须有备份、回滚方案和单独验收。
3. New NOT NULL columns must use expand/backfill/contract：
   * expand：先新增 nullable 列或默认值。
   * backfill：幂等脚本回填历史数据。
   * validate：验证无 null、无脏数据。
   * contract：最后再加 NOT NULL / FK / strict constraint。
4. `tenant_id UUID NOT NULL`、`project_id UUID NOT NULL` 这类字段不能直接加到有历史数据的表上。
5. RLS policies must roll out safely：能 monitor mode 就先记录 would-deny；不能 monitor 的，先在 staging 和 production-internal 跑 `rls-smoke`，再 enforce。
6. Dirty demo data cleanup must be idempotent and separately runnable：清理 KoalaHome、ExampleBrand、AU GEO Pilot、fixture report 这类数据必须单独脚本化，重复运行无副作用。
7. Every migration must have downgrade or documented irreversible reason：无法 downgrade 的迁移必须写明原因、备份位置、恢复方式。
8. Migration PR 必须包含：
   * schema change。
   * backfill/cleanup 脚本，如需要。
   * smoke test。
   * rollback note。
   * 对现有数据的影响说明。

---

## 9. Worker 与任务系统落地策略

### 9.1 v1 队列选择

Production v1 P0 固定使用 Dramatiq + Valkey 作为生产队列。现有 Python CLI workers 只作为 local/dev/manual entrypoint，不能作为唯一生产任务系统。

P0 队列必须支持：

```text
delayed retry
job cancellation request
idempotency lock
dead-letter equivalent failed job table
concurrency limit per provider
concurrency limit per tenant/project
sanitized failure category
```

Temporal 暂不作为 P0 强依赖，除非现有 worker 无法满足：

* 跨小时 durable workflow。
* 人工介入后恢复。
* 复杂取消 / 补偿。
* 强一致长流程状态机。

### 9.2 Job Contract

所有 worker job 必须包含：

```text
job_id
job_type
tenant_id
project_id
requested_by
idempotency_key
input_hash
status
attempt
max_attempts
created_at
started_at
finished_at
failure_category
failure_message_sanitized
audit_event_id
```

### 9.3 Worker 顺序

1. collector worker。
2. parser worker。
3. scoring worker。
4. report worker。
5. notification worker。
6. knowledge worker。
7. content worker。
8. distribution worker。
9. retest worker。

每个 worker 必须有：

* happy path test。
* retry test。
* idempotency test。
* cancellation test。
* audit event test。
* sanitized error test。

---

## 10. UI 落地策略

### 10.1 Admin Web P0 页面

必须优先完成：

1. Login / session 状态。
2. Tenant list / tenant detail。
3. User invitation / member management。
4. Project list / project create / project detail。
5. Project configuration：

   * brand
   * competitors
   * market
   * city
   * language
   * prompts
6. Connector configuration：

   * OpenAI
   * Perplexity
   * Google manual
7. Collection runs：

   * run list
   * run detail
   * failure reason
   * retry
   * cost
8. Evidence view：

   * answer
   * citation
   * asset summary
   * traceability
9. Analysis review：

   * parser output
   * manual correction
10. Scoring view：

* total score
* platform score
* score contribution

11. Reports：

* generate
* preview
* approve
* publish
* revoke

12. Action Plan：

* recommendation
* task
* status

13. Retest：

* create retest
* result comparison

14. Audit log：

* filter by project
* filter by action
* filter by actor

### 10.2 Customer Web P0 页面

必须优先完成：

1. Login / invitation redemption。
2. Project list。
3. Project overview。
4. Visibility score。
5. Prompt detail read-only。
6. Report center。
7. PDF / CSV download。
8. Evidence summary。
9. Action Plan customer-visible view。
10. Retest result。
11. Access denied / revoked report state。

### 10.3 Dashboard Web P0 页面

Dashboard 只做只读运维，不做业务操作：

1. API health。
2. DB health。
3. Worker queue。
4. Connector health。
5. Collection success rate。
6. Provider cost。
7. Report job status。
8. RLS smoke status。
9. Backup status。
10. Alert status。

---

## 11. Google AI Mode / AIO 风险隔离

Google 是 Production v1 最大不确定项，必须单独处理。

### 11.1 三条路径

Production v1 支持三条路径：

1. Manual backfill：P0 必须完成。
2. Browser collection：P0 做 Go / No-Go 决策。
3. SERP provider：P0 做 Go / No-Go 决策。

### 11.2 Go 条件

Browser 或 SERP provider 满足以下条件才允许作为 production path：

1. 测试样本不少于 50 条 prompt，覆盖目标 market / city / language / device。
2. successful collection rate 默认不少于 80%。
3. evidence completeness 默认不少于 95%，必须包含 screenshot / html / payload evidence 中配置要求的字段。
4. `surface_triggered` / `answer_present` 分类经人工抽检准确率默认不少于 95%。
5. 能记录 `access_method`、provider_request_id、采集时间、失败原因。
6. median run duration 不超过配置阈值；默认阈值必须写入 connector config。
7. cost per 100 prompts 不超过配置阈值；默认阈值必须写入 connector config。
8. 能在报告中披露方法和局限，披露文本已审核。
9. 不存在未批准的合规风险。

P0 默认上限：

1. 单 prompt automated Google collection cost <= 0.20 USD。
2. 50 prompt Go/No-Go 批次总成本 <= 10 USD。
3. 单 prompt median duration <= 30 seconds。
4. 50 prompt 批次 wall-clock duration <= 45 minutes。
5. 合规审批人：Project Owner + Reviewer + Security/Ops Owner；任一拒绝即 No-Go。

阈值可以通过配置调整，但必须由 Project Owner + Reviewer + Security/Ops Owner 审批，并写入 audit event。未配置阈值时使用上述默认值。

### 11.3 No-Go 条件

出现以下任一情况，browser / SERP 不进入 Production v1 P0：

1. selector 极不稳定。
2. 账号状态影响无法解释。
3. 成本不可控。
4. 合规风险不可接受。
5. 无法稳定获取 evidence。
6. 无法明确 answer_present。
7. 无法在报告中解释采样方法。

No-Go 不阻塞 Production v1。此时 Google 以 manual backfill 作为 v1 官方路径，并在报告中显示：

```text
Google data access method: manual structured backfill
Limitations: browser/SERP automated path not enabled for this report
Evidence: uploaded screenshot / URL / structured record
Reviewer: human reviewer
```

---

## 12. Report 最小正式模板

Production v1 最小正式报告必须包含：

1. Cover：

   * 项目名称
   * 客户名称
   * 报告类型
   * 时间窗
   * 版本
2. Executive Summary：

   * 总体 AI 可见性评分
   * 主要机会
   * 主要风险
   * 关键竞品
3. Methodology：

   * 平台
   * access_method
   * sample window
   * Prompt 数量
   * 城市 / 市场 / 语言
   * Google 方法披露
   * 评分公式版本
   * 局限说明
4. Visibility Score：

   * total score
   * platform score
   * trigger / mention / recommendation
   * sample count
5. Prompt Detail：

   * prompt
   * platform
   * answer_present
   * brand_mentioned
   * competitor_mentioned
   * recommendation_state
   * citation count
6. Competitor Benchmark：

   * mention rate
   * recommendation rate
   * entity position，仅在 `entity_positions[]` 可追溯时展示
   * recommended_entities_ordered 排序摘要
   * share of voice basis，仅在采样口径和计算公式明确时展示；否则作为 limitation
7. Citation Summary：

   * top sources
   * source type
   * source gap
8. Risk / Error Findings：

   * unsupported claims，仅在 `unsupported_claims[]` 存在或人工复核确认时展示
   * missing / weak source
   * negative sentiment，仅在 `sentiment_label` 可追溯或人工复核确认时展示
   * wrong facts 不作为 P0 自动指标；只能来自人工复核或 P1/P2 fact-risk parser
9. Action Plan：

   * recommendation
   * priority
   * evidence source
   * owner
   * expected impact
10. Evidence Appendix：

* internal full appendix
* customer-safe summary

11. Audit Summary：

* generated_at
* approved_by
* published_at
* report_export_id

P0 报告字段必须和 `AnswerAnalysis Output Contract` 对齐：

1. `competitor outranks brand` 只有在 `recommended_entities_ordered[]` 或 `entity_positions[]` 能证明时生成。
2. `share of voice`、`average position`、`wrong facts`、`negative sentiment` 不得凭空生成；缺少输入时必须显示为 limitation 或延期到 P1/P2。
3. 客户可见的每个数字都必须能追溯到 `ScoreContribution -> AnswerAnalysis -> RawAnswer -> EvidenceAsset`。

PDF、Markdown、CSV 三种导出必须来自同一 ReportExport snapshot。

---

## 13. 测试矩阵

### 13.1 必须新增或稳定的 Make targets

最终需要这些命令，其中 P0 Gate 必须运行主命令组；P1 Enablement 声明完成时再运行 P1 命令组。

```bash
make lint
make typecheck
make test
make db-smoke
make rls-smoke
make runtime-e2e
make security-smoke
make production-v1-e2e
make no-fixture-production-smoke
make no-secret-leak-smoke
make report-traceability-smoke
make customer-access-negative-smoke
make connector-real-smoke
make ops-smoke
make backup-smoke
make docker-config
make docker-config-observability
```

P1 Enablement 命令：

```bash
make enablement-v1-e2e
```

如果当前已有部分命令，则对齐现有命名；如果没有，新增等价命令。

### 13.2 Gate W1 命令

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

### 13.3 Gate W2 命令

```bash
make rls-smoke
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/geno_core:apps/api python3 -m unittest \
  tests/security/test_rbac_matrix.py \
  tests/security/test_customer_portal_access.py \
  tests/security/test_scope_derivation.py
```

### 13.4 Gate W3/W4 命令

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/geno_core:apps/api python3 -m unittest \
  tests/connectors/test_connector_contract.py \
  tests/connectors/test_google_manual_backfill.py \
  tests/evidence/test_traceability_chain.py \
  tests/evidence/test_evidence_asset_permissions.py \
  tests/audit/test_audit_event_required.py
```

staging / production-internal 额外运行：

```bash
make connector-real-smoke
```

### 13.5 Gate W5/W6 命令

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/geno_core:apps/api python3 -m unittest \
  tests/analysis \
  tests/scoring \
  tests/reports \
  tests/customer
```

### 13.6 Gate W7/W8 命令

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/geno_core:apps/api python3 -m unittest \
  tests/actions \
  tests/retest \
  tests/knowledge \
  tests/content \
  tests/distribution
```

### 13.7 Final Gate 命令

```bash
make lint
make typecheck
make test
make db-smoke
make rls-smoke
make runtime-e2e
make security-smoke
make production-v1-e2e
make no-fixture-production-smoke
make no-secret-leak-smoke
make report-traceability-smoke
make customer-access-negative-smoke
make connector-real-smoke
make ops-smoke
make backup-smoke
make docker-config
make docker-config-observability
git diff --check
```

P1 Enablement Gate：

```bash
make enablement-v1-e2e
```

Local/CI 可以 skip `connector-real-smoke` 的真实 provider 子集，但 staging 和 production-internal 不允许 skip。`enablement-v1-e2e` 是 P1 gate，不阻塞 P0 production-v1-e2e，但如果声明 P1 已完成则必须通过。

---

### 13.8 Test Tier Matrix

真实外部调用测试必须按环境分层。`skip if no key` 只能用于 Local/CI，不能成为 staging 或 production-internal 的逃生通道。

| Tier | Provider key 要求 | 必跑内容 | 不允许 |
| --- | --- | --- | --- |
| Local | 不要求真实 key | unit、contract、recorded connector tests、no-fixture production path tests | 把 fixture 当 production 成功 |
| CI | 默认不要求真实 key | lint、typecheck、contract tests、security-smoke 可运行子集、recorded connector tests | 因无 key 跳过权限/证据/报告安全测试 |
| Staging | 要求 OpenAI/Perplexity 可用 key；Google manual evidence 可用 | OpenAI real 10 prompt smoke；Perplexity real 10 prompt smoke；Google manual backfill；connector failure classification；report traceability smoke | 真实 connector 全部 skip |
| Production-internal | 要求真实生产等价配置 | production-v1-e2e；security-smoke；connector-real-smoke；ops-smoke；backup-smoke；no fixture；no secret leak；customer negative access | 存在 pending P0 step |

### 13.9 GEO 反验收 Smoke Targets

必须新增或等价实现以下命令：

```bash
make no-fixture-production-smoke
make no-secret-leak-smoke
make report-traceability-smoke
make customer-access-negative-smoke
```

语义：

```text
no-fixture-production-smoke:
验证 production config 下不会创建 demo brand / demo competitor / fixture report。

no-secret-leak-smoke:
扫描 API response、logs、frontend bundle、report assets，确认无 provider key、session token、invitation token。

report-traceability-smoke:
随机抽取报告里的 5 个数字，验证能追溯到 ScoreContribution -> AnswerAnalysis -> RawAnswer -> EvidenceAsset。

customer-access-negative-smoke:
客户尝试访问未发布报告、已撤回报告、跨项目报告、raw evidence、provider key，全部失败并写审计。
```

---

## 14. Production v1 E2E 脚本定义

`make production-v1-e2e` 必须从空环境完成 P0 报告生产闭环：

1. 创建 Super Admin。
2. 创建 tenant。
3. 邀请 Tenant Admin。
4. 兑换邀请。
5. 创建 project。
6. 配置 brand。
7. 配置 competitors。
8. 配置 market / city / language。
9. 导入 10 个 prompts。
10. 配置 OpenAI connector。
11. 配置 Perplexity connector。
12. 执行 OpenAI collection。
13. 执行 Perplexity collection。
14. 执行 Google manual backfill。
15. 验证 RawAnswer。
16. 验证 AnswerCitation。
17. 验证 EvidenceAsset。
18. 验证 AuditEvent。
19. 执行 AnswerAnalysis。
20. 执行 Human Review。
21. 执行 Scoring。
22. 验证 ScoreContribution。
23. 生成 Markdown / PDF / CSV ReportExport。
24. 审批 report。
25. 发布 report。
26. 邀请 Client Viewer。
27. Client Viewer 登录。
28. Client Viewer 查看 report。
29. Client Viewer 下载 PDF / CSV。
30. 撤回 report。
31. 验证 Client Viewer 不可再次下载。
32. 生成 Action Plan。
33. 创建 Retest。
34. 执行 Retest collection。
35. 生成 Retest Markdown report section。
36. 验证 audit log。
37. 验证 dashboard health。
38. 验证无 secret 泄露。

`make enablement-v1-e2e` 覆盖 P1 Enablement 薄闭环：

1. 从 Action Plan 创建 knowledge/content 入口。
2. 导入 knowledge facts。
3. 审核 approved facts。
4. 从 action 创建 content asset。
5. 生成 content brief 或 draft。
6. 人工审核 content。
7. 创建 Distribution task。
8. 回填 URL 或发布证明。
9. Distribution task 关联 Action Plan 和 Retest。
10. 验证未审核 facts/content 不进入客户可见内容。

---

## 15. Security Smoke 定义

`make security-smoke` 必须覆盖：

1. Client Viewer 不能访问其他 tenant。
2. Client Viewer 不能访问其他 project。
3. Client Viewer 不能访问未发布 report。
4. Client Viewer 不能访问 revoked report。
5. Client Viewer 不能访问 raw provider payload。
6. Client Viewer 不能访问 provider key。
7. Analyst 不能管理 connector secret，除非有 connector.manage。
8. Content Operator 不能审批 report。
9. 未登录不能访问受保护 API。
10. 过期 session 不能访问。
11. invitation token 只能使用一次。
12. token 不出现在 URL query。
13. session cookie 必须 httpOnly / secure / sameSite。
14. CORS 不允许任意 origin。
15. 文件上传限制 content_type 和 size。
16. SSRF 防护覆盖 URL import。
17. SQL 注入基本用例不成功。
18. 日志中无 provider key / session token / invitation token。
19. 前端 bundle 中无 provider key。
20. report export 中无 provider key。

---

## 16. 第一批 Codex Backlog

第一批任务不是阶段一，也不是可发布 MVP，而是 Production v1 的强依赖施工入口。

### W1-I01：冻结 FastAPI domain route 边界

```text
Workstream: W1 Foundation
Epic: API domain boundary
Task: Move or route new API endpoints behind domain routers; prevent further growth of giant main.py
Owner: Codex
Priority: P0
Size: M
Can Parallelize: No

Goal:
Establish stable API domain routing so future work does not continue accumulating in main.py.

Dependencies:
None

Affected modules:
apps/api/geno_api/main.py
apps/api/geno_api/domains/*
tests/api/*

Database changes:
None

API changes:
No functional behavior change unless existing routes need path normalization.

Frontend changes:
None

Worker changes:
None

Permission rules:
Existing behavior preserved.

Audit events:
None required for pure routing refactor.

Test cases:
- Existing API tests still pass.
- Route registration snapshot test added if feasible.
- OpenAPI generation still works.

Acceptance:
- main.py only performs app setup and router registration.
- New domain routers exist for at least auth, tenants, projects, prompts, connectors, collection, evidence, analysis, scoring, reports, actions, audit.
- Existing runtime-e2e still passes.

Validation:
make test
make runtime-e2e

Rollback:
Revert router registration changes.
```

### W1-I02：冻结 Repository 拆分边界

```text
Workstream: W1 Foundation
Epic: Repository boundary
Task: Create repository module structure and move audit/project/access-control read paths first
Owner: Codex
Priority: P0
Size: M
Can Parallelize: No

Goal:
Prevent business logic and SQL from expanding inside a single repository.py.

Dependencies:
W1-I01 preferred

Affected modules:
packages/geno_core/geno_core/repository.py
packages/geno_core/geno_core/repositories/*
tests/repositories/*

Database changes:
None

API changes:
None

Frontend changes:
None

Worker changes:
Potential imports only

Permission rules:
No permission behavior change

Audit events:
Existing audit writes preserved

Test cases:
- repository import compatibility test
- audit repository test
- project repository test
- access control repository test

Acceptance:
- New repositories package exists.
- At least audit, project, access_control repositories are split.
- Old imports either remain compatible or are updated safely.
- Unit tests pass.

Validation:
make test

Rollback:
Revert repository split.
```

### W1-I03：清除生产路径 demo fallback

```text
Workstream: W1 Foundation
Epic: Production data hygiene
Task: Remove demo fallback from production project creation and report generation paths
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes

Goal:
Ensure production project creation never writes ExampleBrand, AU GEO Pilot, KoalaHome dirty competitor names, or fixture defaults.

Dependencies:
None

Affected modules:
apps/api/geno_api/domains/projects/*
packages/geno_core/geno_core/repositories/project_repository.py
apps/admin-web/*
tests/projects/*

Database changes:
Optional cleanup migration for known dirty data

API changes:
Project creation returns validation error instead of inserting fallback data

Frontend changes:
Project create form shows validation errors

Worker changes:
None

Permission rules:
Existing project.create required

Audit events:
project.validation_failed
project.created

Test cases:
- Empty brand rejected
- Empty competitor rejected
- Invalid competitor name rejected
- No demo fallback inserted
- Cleanup migration idempotent

Acceptance:
- Creating project with missing required fields fails.
- Valid project contains only user-provided or explicitly configured values.
- Existing dirty data cleanup script is present.

Validation:
make test
make runtime-e2e

Rollback:
Revert validation and cleanup migration if necessary.
```

### W2-I01a：AuthContext contract / types / dependency

```text
Workstream: W2 Identity
Epic: Auth boundary
Task: Define AuthContext contract, types, and FastAPI dependency boundary
Owner: Codex
Priority: P0
Size: S
Can Parallelize: No

Goal:
Make AuthContext the only accepted source for actor, tenant, project, and role scope.

Dependencies:
W1-I01

Affected modules:
apps/api/geno_api/core/auth_context.py
apps/api/geno_api/domains/auth/*
tests/auth/*
tests/security/*

Database changes:
None

API changes:
Protected route dependency shape defined, but rollout can remain partial

Frontend changes:
None

Worker changes:
None

Permission rules:
AuthContext must include actor_id, actor_type, tenant_id, project_ids, roles, session_id, auth_method

Audit events:
None

Test cases:
- AuthContext cannot be built from request body tenant_id
- Missing context returns 401/403 through dependency
- System actor shape explicit and typed

Acceptance:
- AuthContext is the only accepted source for actor/scope.
- Contract tests exist before broad rollout.

Validation:
make test

Rollback:
Revert dependency introduction before rollout.
```

### W2-I01b：sessions table + session repository

```text
Workstream: W2 Identity
Epic: Auth boundary
Task: Add sessions schema and repository behind AuthContext
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W2-I01a

Goal:
Persist user sessions without exposing raw session identifiers.

Dependencies:
W2-I01a

Affected modules:
db/migrations/*
packages/geno_core/geno_core/repositories/access_control_repository.py
packages/geno_core/geno_core/repositories/session_repository.py
tests/auth/*

Database changes:
users
sessions
external_identity_mappings optional

API changes:
None or internal auth repository only

Frontend changes:
None

Worker changes:
None

Permission rules:
Session repository only validates token hash, expiry, revocation, and actor identity. Tenant/project scope mapping is owned by W2-I03b membership schema.

Audit events:
auth.session_created
auth.session_expired

Test cases:
- Session token hash stored
- Expired session rejected
- Revoked session rejected
- Session returns actor identity only
- Session TTL defaults to 7 days
- Cookie policy is httpOnly + secure + sameSite=Lax
- Unsafe mutation without CSRF header rejected

Acceptance:
- sessions table and repository exist.
- No raw session token is stored or returned.
- Session revocation is effective immediately.

Validation:
make test

Rollback:
Drop additive session objects before route rollout if needed.
```

### W2-I01c：protected API dependency rollout

```text
Workstream: W2 Identity
Epic: Auth boundary
Task: Roll AuthContext dependency onto protected API routes
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W2-I01a/W2-I01b/W2-I03a/W2-I03b

Goal:
Protected APIs derive actor, tenant, and project scope from trusted session context.

Dependencies:
W2-I01a
W2-I01b
W2-I03a
W2-I03b

Affected modules:
apps/api/geno_api/domains/*
tests/security/*

Database changes:
None

API changes:
Protected routes return 401/403 when session/scope is missing

Frontend changes:
Admin/Customer must handle 401

Worker changes:
None

Permission rules:
No protected endpoint trusts tenant_id/project_id from request body without permission check

Audit events:
auth.denied

Test cases:
- Missing session -> 401
- Wrong tenant -> 403
- Wrong project -> 403
- Valid session -> allowed

Acceptance:
- Core protected routes require AuthContext.
- Existing public health endpoints remain public.

Validation:
make test
make security-smoke

Rollback:
Feature flag protected route enforcement if needed, but do not reintroduce URL token access.
```

### W2-I01d：system actor contract

```text
Workstream: W2 Identity
Epic: Auth boundary
Task: Define explicit system actor contract for workers and internal jobs
Owner: Codex
Priority: P0
Size: S
Can Parallelize: Yes after W2-I01a

Goal:
Workers can act without user sessions while still producing scoped, auditable actions.

Dependencies:
W2-I01a

Affected modules:
apps/api/geno_api/core/auth_context.py
workers/*
tests/auth/*

Database changes:
None

API changes:
None

Frontend changes:
None

Worker changes:
Workers must request explicit system actor context

Permission rules:
System actor cannot bypass scope unless job type explicitly grants it

Audit events:
system_actor.used

Test cases:
- System actor requires job/service identity
- System actor carries tenant/project scope
- System actor writes audit context

Acceptance:
- Worker paths do not invent ad hoc actor ids.

Validation:
make test

Rollback:
Revert worker actor changes before connector rollout.
```

### W2-I01e：auth audit events

```text
Workstream: W2 Identity
Epic: Auth boundary
Task: Add auth audit event vocabulary and required writes
Owner: Codex
Priority: P0
Size: S
Can Parallelize: Yes after W2-I01a

Goal:
Authentication and authorization failures are auditable from the first protected route rollout.

Dependencies:
W2-I01a

Affected modules:
packages/geno_core/geno_core/repositories/audit_repository.py
apps/api/geno_api/domains/auth/*
tests/audit/*

Database changes:
audit_events additive fields only if needed

API changes:
None

Frontend changes:
None

Worker changes:
None

Permission rules:
Audit writes must not expose raw token/session

Audit events:
auth.login
auth.logout
auth.session_expired
auth.denied
authz.denied

Test cases:
- denied access writes audit
- audit payload is sanitized
- auth failure does not leak token

Acceptance:
- Auth audit event names and payload rules are stable.

Validation:
make test
make security-smoke

Rollback:
Revert event emission only if blocking; keep payload contract.
```

### W2-I02：Invitation token 一次性兑换

```text
Workstream: W2 Identity
Epic: Invitation flow
Task: Replace long-lived URL query access with one-time invitation redemption and httpOnly session
Owner: Codex
Priority: P0
Size: L
Can Parallelize: Yes

Goal:
Customer access must not rely on persistent query token.

Dependencies:
W2-I01a
W2-I01b
W2-I03a
W2-I03b

Affected modules:
apps/api/geno_api/domains/auth/*
apps/customer-web/*
packages/geno_core/geno_core/repositories/access_control_repository.py
tests/customer/*
tests/security/*

Database changes:
invitations
sessions

API changes:
POST /auth/invitations/redeem
POST /auth/logout
GET /auth/me

Frontend changes:
Customer invitation redemption page
Customer session handling

Worker changes:
None

Permission rules:
Invitation token only creates membership/session

Audit events:
invitation.created
invitation.redeemed
invitation.failed
auth.login

Test cases:
- Token hash stored, raw token shown once
- Token can be redeemed once
- Reused token rejected
- Expired token rejected
- Customer receives httpOnly session cookie
- Report access no longer accepts long-lived query token

Acceptance:
- Customer portal uses session cookie.
- URL token access removed from production path.

Validation:
make security-smoke
make customer-e2e

Rollback:
Do not rollback to long-lived token; fix session flow.
```

### W2-I03a：RBAC matrix contract

```text
Workstream: W2 Identity
Epic: RBAC/RLS
Task: Define role-permission matrix and permission evaluator tests
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes

Goal:
Make role-resource-action decisions explicit and testable before RLS rollout.

Dependencies:
W2-I01a

Affected modules:
apps/api/geno_api/core/permissions.py
packages/geno_core/geno_core/repositories/access_control_repository.py
tests/security/*

Database changes:
None

API changes:
403 returned for denied access

Frontend changes:
Show access denied states

Worker changes:
System actor bypass only through explicit permission

Permission rules:
Implement role matrix

Audit events:
authz.denied
authz.allowed optional

Test cases:
- Client Viewer cannot access other project
- Analyst cannot manage provider key
- Reviewer cannot run connector unless permission granted
- Super Admin can access system resources

Acceptance:
- RBAC allow/deny tests pass.
- Denials write audit events.

Validation:
make security-smoke

Rollback:
Revert permission evaluator changes before route rollout.
```

### W2-I03b：membership schema + scope repository

```text
Workstream: W2 Identity
Epic: RBAC/RLS
Task: Add tenant/project membership schema and scoped access repository
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W2-I03a

Goal:
Persist tenant/project membership used by AuthContext and RBAC checks.

Dependencies:
W2-I01b
W2-I03a

Affected modules:
db/migrations/*
packages/geno_core/geno_core/repositories/access_control_repository.py
tests/security/*

Database changes:
tenant_members
project_members

API changes:
None

Frontend changes:
None

Worker changes:
None

Permission rules:
Membership lookups must be tenant scoped

Audit events:
membership.created
membership.updated

Test cases:
- user can belong to tenant
- user can belong to project
- cross-tenant membership query denied

Acceptance:
- AuthContext can be built from membership records.

Validation:
make test

Rollback:
Revert additive membership migration before RLS rollout.
```

### W2-I03c：RLS smoke for core tables

```text
Workstream: W2 Identity
Epic: RBAC/RLS
Task: Add RLS policies and smoke tests for core tenant/project tables
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W2-I03b

Goal:
Tenant/project boundaries must be enforced at database level.

Dependencies:
W2-I03b

Affected modules:
db/migrations/*
scripts/rls_smoke.py
tests/security/*

Database changes:
RLS policies for core tables

API changes:
None

Frontend changes:
None

Worker changes:
System actor bypass only through explicit DB role or scoped setting

Permission rules:
RLS checks tenant_id and project membership

Audit events:
authz.denied optional at API layer

Test cases:
- RLS blocks direct cross-tenant query
- RLS blocks direct cross-project query
- Client Viewer cannot read provider key

Acceptance:
- make rls-smoke passes.
- RLS is not disabled globally to make tests pass.

Validation:
make rls-smoke
make security-smoke

Rollback:
Revert specific policy only if broken; do not remove RLS globally.
```

### W3-I00：Provider secret storage and redaction baseline

```text
Workstream: W3 Collection
Epic: Connector security
Task: Implement provider secret storage, rotation, and redaction baseline
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes

Goal:
Provider keys must be stored, used, rotated, audited, and redacted without leaking into API responses, logs, frontend bundles, reports, or evidence assets.

Dependencies:
W2-I01a preferred
W2-I03a preferred

Affected modules:
apps/api/geno_api/domains/connectors/*
apps/api/geno_api/core/redaction.py
packages/geno_core/geno_core/repositories/connector_repository.py
packages/geno_core/geno_core/security/secrets.py
tests/security/*
tests/connectors/*

Database changes:
connector_configs secret_ref / encrypted_secret metadata
connector_secret_rotations optional

API changes:
POST /connectors/{id}/secrets
PATCH /connectors/{id}/secrets
GET endpoints return only masked secret metadata

Frontend changes:
Connector UI shows configured / last_rotated / health status, never raw secret after save

Worker changes:
Collector resolves secret through secret_ref or encrypted store at execution time

Permission rules:
connector.manage required to create/update/rotate secret
connector.read can only see masked metadata
Client Viewer cannot see connector config or secret metadata

Audit events:
connector.secret_created
connector.secret_rotated
connector.secret_deleted
connector.secret_access_denied

Test cases:
- API never returns raw provider key
- logs redact provider key/session/invitation token
- frontend bundle contains no provider key
- report assets contain no provider key
- config_ref is not equal to secret value
- connector.manage required for secret mutation
- rotation invalidates old secret reference

Acceptance:
- Provider key protection is implemented before real connectors.
- `make no-secret-leak-smoke` passes for API/log/frontend/report surfaces.

Validation:
make security-smoke
make no-secret-leak-smoke

Rollback:
Disable connector secret mutation endpoint; do not revert to plaintext API responses.
```

### W3-I01：Connector contract 和 fake-recorded harness

```text
Workstream: W3 Collection
Epic: Connector interface
Task: Implement ConnectorBackend contract and recorded test harness
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes

Goal:
OpenAI, Perplexity, and Google manual must use one connector abstraction.

Dependencies:
W1-I01
W3-I00

Affected modules:
packages/geno_core/geno_core/contracts/connector.py
apps/api/geno_api/domains/connectors/*
workers/collector*
tests/connectors/*

Database changes:
connector_configs

API changes:
Connector health and validate endpoints

Frontend changes:
Connector config UI can consume health endpoint later

Worker changes:
collector uses ConnectorBackend

Permission rules:
connector.manage required for key/config changes
collection.run required for collection

Audit events:
connector.config_created
connector.health_checked
connector.validation_failed

Test cases:
- Contract conformance
- Sanitized failures
- Cost estimate shape
- No provider key in response/log

Acceptance:
- OpenAI/Perplexity/manual connectors can be registered behind same interface.
- Tests pass without real provider keys using recorded fixtures.
- Real-key smoke is supported but skipped if env missing.

Validation:
make test

Rollback:
Revert connector abstraction only before W3-I02 starts.
```

### W3-I02：OpenAI 真实采集闭环

```text
Workstream: W3 Collection
Epic: OpenAI connector
Task: Implement OpenAI production collection path for 10 prompt batch
Owner: Codex
Priority: P0
Size: L
Can Parallelize: Yes after W3-I01

Goal:
Collect real OpenAI answers with citations/evidence/cost/failure classification.

Dependencies:
W3-I01
W4-I01a preferred

Affected modules:
connectors/openai*
workers/collector*
apps/api/geno_api/domains/collection/*
tests/connectors/test_openai*
tests/evidence/*

Database changes:
collection_runs
answer_runs
raw_answers
answer_citations
collection_costs

API changes:
POST /projects/{id}/collection-runs
GET /collection-runs/{id}

Frontend changes:
Run status can show OpenAI collection

Worker changes:
collector executes OpenAI job

Permission rules:
collection.run required
connector config hidden from non-authorized users

Audit events:
collection.started
collection.completed
collection.failed
evidence.created

Test cases:
- Single prompt success
- Batch 10 prompts
- Citation normalization
- Cost recorded
- Failure sanitized
- Retry idempotent

Acceptance:
- In real-key environment, 10 prompts complete and write full evidence chain.
- In no-key environment, tests skip real call but contract tests pass.

Validation:
make test
make connector-real-smoke

Rollback:
Disable OpenAI connector via config flag, not by deleting schema.
```

### W3-I03：Perplexity 真实采集闭环

```text
Workstream: W3 Collection
Epic: Perplexity connector
Task: Implement Perplexity production collection path for 10 prompt batch
Owner: Codex
Priority: P0
Size: L
Can Parallelize: Yes after W3-I01

Goal:
Collect real Perplexity answers with provider_request_id, normalized citations, cost, failure classification, rate limit handling, and evidence archiving.

Dependencies:
W3-I00
W3-I01
W4-I01a preferred

Affected modules:
connectors/perplexity*
workers/collector*
apps/api/geno_api/domains/collection/*
packages/geno_core/geno_core/contracts/connector.py
tests/connectors/test_perplexity*
tests/evidence/*

Database changes:
collection_runs
answer_runs
raw_answers
answer_citations
collection_costs
connector_request_logs optional

API changes:
POST /projects/{id}/collection-runs
GET /collection-runs/{id}
GET /answer-runs/{id}

Frontend changes:
Run detail can show Perplexity status, normalized citations, cost, and sanitized failure reason

Worker changes:
collector executes Perplexity job through ConnectorBackend
rate-limit retry uses idempotency key
raw provider payload archived through EvidenceAsset policy

Permission rules:
collection.run required
connector.read can see masked config metadata only
connector.manage required for secret mutation
Client Viewer cannot access raw provider payload unless explicitly exposed through customer-safe summary

Audit events:
collection.started
collection.completed
collection.failed
collection.rate_limited
evidence.created
connector.request_failed

Test cases:
- Single prompt success
- Batch 10 prompts
- Perplexity citation shape normalized into answer_citations
- provider_request_id recorded when available
- Cost recorded or estimated with explicit method
- Rate limit classified and retried safely
- Provider errors sanitized
- Evidence asset stores raw payload without leaking secret
- Retry idempotent

Acceptance:
- In real-key staging, 10 prompts complete and write full evidence chain.
- Perplexity citations can be traced from report field to raw evidence.
- In no-key local/CI, recorded contract tests pass and real call is explicitly skipped.

Validation:
make test
make connector-real-smoke
make report-traceability-smoke

Rollback:
Disable Perplexity connector via config flag, not by deleting shared schema.
```

### W3-I04：Google manual backfill 生产路径

```text
Workstream: W3 Collection
Epic: Google manual path
Task: Implement structured Google manual backfill with evidence upload and reviewer audit
Owner: Codex
Priority: P0
Size: L
Can Parallelize: Yes

Goal:
Provide a reliable Google Production v1 path independent of browser/SERP uncertainty.

Dependencies:
W4-I01a

Affected modules:
apps/api/geno_api/domains/collection/google_manual*
apps/admin-web/*
packages/geno_core/geno_core/repositories/evidence_repository.py
tests/connectors/test_google_manual_backfill.py

Database changes:
collection_runs
answer_runs
raw_answers
answer_citations
evidence_assets
human_review_records

API changes:
POST /projects/{id}/google-manual-backfills
POST /google-manual-backfills/{id}/approve

Frontend changes:
Admin manual backfill form
Evidence attachment upload
Reviewer approval UI

Worker changes:
Optional parser trigger after approval

Permission rules:
Analyst can submit
Reviewer can approve
Client cannot see unapproved manual records

Audit events:
google_manual.submitted
google_manual.approved
google_manual.rejected
evidence.created

Test cases:
- Valid JSONL/CSV/manual payload accepted
- Evidence attachment required
- surface_triggered required
- answer_present required
- Reviewer approval required before scoring
- Report methodology includes manual access method

Acceptance:
- Google manual data can enter scoring only after review.
- Evidence and methodology are traceable.

Validation:
make test
make production-v1-e2e

Rollback:
Disable Google manual scoring inclusion via feature flag.
```

### W4-I01a：EvidenceAsset schema + repository

```text
Workstream: W4 Evidence
Epic: Evidence storage
Task: Add EvidenceAsset / EvidenceLink schema and repository
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes

Goal:
Persist evidence metadata with hash, scope, and traceability references.

Dependencies:
W2-I01a preferred

Affected modules:
packages/geno_core/geno_core/repositories/evidence_repository.py
db/migrations/*
tests/evidence/*

Database changes:
evidence_assets
evidence_links

API changes:
None

Frontend changes:
None

Worker changes:
None

Permission rules:
Repository requires tenant/project scope

Audit events:
evidence.created

Test cases:
- Hash calculated
- Content type stored
- Size stored
- Project scope stored
- EvidenceLink connects source object to asset

Acceptance:
- Evidence assets are traceable to project and related object.

Validation:
make test

Rollback:
Revert additive schema before storage rollout if needed.
```

### W4-I01b：S3-compatible storage adapter

```text
Workstream: W4 Evidence
Epic: Evidence storage
Task: Implement MinIO/S3 storage adapter for evidence assets
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W4-I01a

Goal:
Store and retrieve evidence bytes through an S3-compatible adapter.

Dependencies:
W4-I01a

Affected modules:
storage/*
packages/geno_core/geno_core/contracts/evidence.py
tests/evidence/*

Database changes:
None

API changes:
None

Frontend changes:
None

Worker changes:
Collector/report workers can archive assets through adapter

Permission rules:
Adapter does not decide authorization

Audit events:
evidence.created

Test cases:
- Upload stores bytes
- Download reads bytes
- Hash mismatch rejected
- Content type preserved
- MinIO local/staging and S3-compatible production use same interface
- Customer download uses backend permission proxy
- Internal signed URL expires and is issued only after API authorization

Acceptance:
- MinIO dev/staging works through same interface as S3-compatible production.
- Direct bucket URL is never returned to customer-facing clients.

Validation:
make test

Rollback:
Disable storage adapter usage via config flag.
```

### W4-I01c：EvidenceAsset permission proxy

```text
Workstream: W4 Evidence
Epic: Evidence storage
Task: Add permissioned evidence summary/download API proxy
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W4-I01a/W4-I01b

Goal:
Expose evidence summaries and downloads without leaking direct bucket access.

Dependencies:
W2-I03a
W4-I01a
W4-I01b

Affected modules:
apps/api/geno_api/domains/evidence/*
tests/evidence/*
tests/security/*

Database changes:
None

API changes:
POST /evidence-assets
GET /evidence-assets/{id}/summary
GET /evidence-assets/{id}/download

Frontend changes:
Evidence summary/download UI later

Worker changes:
None

Permission rules:
evidence.read_summary
evidence.read_raw
customer-safe access only for published report-linked summaries

Audit events:
evidence.downloaded
evidence.access_denied

Test cases:
- Cross-project download denied
- Customer raw download denied
- Revoked report evidence denied
- Short-lived URL or proxy enforced

Acceptance:
- No direct bucket URL exposed without permission.

Validation:
make security-smoke

Rollback:
Disable direct download endpoint if needed; keep metadata schema.
```

### W4-I01d：Traceability chain smoke

```text
Workstream: W4 Evidence
Epic: Evidence storage
Task: Add traceability chain smoke from report number back to evidence asset
Owner: Codex
Priority: P0
Size: S
Can Parallelize: Yes after W4-I01a

Goal:
Make report traceability testable before full reporting is built.

Dependencies:
W4-I01a

Affected modules:
tests/evidence/*
tests/reports/*
scripts/report_traceability_smoke.py

Database changes:
None

API changes:
None

Frontend changes:
None

Worker changes:
None

Permission rules:
Traceability checks must not bypass project scope

Audit events:
None

Test cases:
- RawAnswer -> EvidenceAsset link exists
- ScoreContribution can link to AnswerAnalysis source
- ReportExport placeholder can link to score snapshot

Acceptance:
- `make report-traceability-smoke` has an executable skeleton and fails on broken links.

Validation:
make report-traceability-smoke

Rollback:
Revert smoke script only.
```

### W5-I01：AnswerAnalysis baseline parser

```text
Workstream: W5 Intelligence
Epic: Answer parser
Task: Implement baseline AnswerAnalysis parser with human review override
Owner: Codex
Priority: P0
Size: L
Can Parallelize: Yes after W3/W4 contract

Goal:
Convert raw answers into structured GEO signals.

Dependencies:
W3-I02
W3-I03
W4-I01a

Affected modules:
workers/parser*
packages/geno_core/geno_core/contracts/analysis.py
packages/geno_core/geno_core/repositories/analysis_repository.py
apps/admin-web/analysis/*
tests/analysis/*

Database changes:
answer_analyses
human_review_records
entity_aliases

API changes:
GET /answer-analyses/{id}
PATCH /answer-analyses/{id}/review

Frontend changes:
Analysis review UI

Worker changes:
parser worker

Permission rules:
analysis.review required for manual correction

Audit events:
analysis.created
analysis.reviewed
analysis.review_failed

Test cases:
- Brand mention detected
- Competitor mention detected
- Recommendation state detected
- Citation domains extracted
- No-answer handled
- Human override preserves original parser output
- Review writes audit

Acceptance:
- Parser outputs versioned schema.
- Human corrections feed scoring.
- Original parser output remains auditable.

Validation:
make test
```

### W5-I02a：Scoring profile schema + formula contract

```text
Workstream: W5 Intelligence
Epic: Scoring engine
Task: Add scoring profile schema and formula-versioned contract
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W5-I01

Goal:
Freeze scoring formula inputs, denominator rules, and versioned profile storage.

Dependencies:
W5-I01

Affected modules:
packages/geno_core/geno_core/contracts/scoring.py
packages/geno_core/geno_core/repositories/scoring_repository.py
tests/scoring/*

Database changes:
scoring_profiles

API changes:
None or read-only profile endpoint

Frontend changes:
None

Worker changes:
None

Permission rules:
score.configure optional

Audit events:
score.formula_changed

Test cases:
- Formula version fixed
- Trigger/Mention/Recommendation denominators defined
- Profile is immutable once used by snapshot

Acceptance:
- Scoring profiles can be referenced by exact id/version, not only by display name.

Validation:
make test
```

### W5-I02b：VisibilityScoreSnapshot calculator

```text
Workstream: W5 Intelligence
Epic: Scoring engine
Task: Implement scoring calculator and immutable score snapshots
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W5-I02a

Goal:
Generate immutable GEO score snapshots from AnswerAnalysis.

Dependencies:
W5-I02a

Affected modules:
workers/scoring*
packages/geno_core/geno_core/repositories/scoring_repository.py
apps/api/geno_api/domains/scoring/*
tests/scoring/*

Database changes:
visibility_score_snapshots

API changes:
POST /projects/{id}/score-snapshots
GET /score-snapshots/{id}

Frontend changes:
Score detail and contribution view

Worker changes:
scoring worker

Permission rules:
score.read

Audit events:
score.snapshot_created

Test cases:
- Trigger/Mention/Recommendation denominators separated
- Platform score calculated
- Empty sample handled with limitation
- Historical snapshot immutable

Acceptance:
- Snapshot does not change after report generation.

Validation:
make test
```

### W5-I02c：ScoreContribution traceability

```text
Workstream: W5 Intelligence
Epic: Scoring engine
Task: Link every score component to AnswerAnalysis and evidence source
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W5-I02b

Goal:
Make every reportable score explainable and traceable.

Dependencies:
W5-I02b
W4-I01d

Affected modules:
workers/scoring*
packages/geno_core/geno_core/repositories/scoring_repository.py
tests/scoring/*
tests/evidence/*

Database changes:
score_contributions

API changes:
GET /score-snapshots/{id}/contributions

Frontend changes:
Score contribution view

Worker changes:
scoring worker writes contributions

Permission rules:
score.read

Audit events:
score.contribution_created

Test cases:
- ScoreContribution links to AnswerAnalysis
- Contribution links to raw answer/evidence path
- Missing traceability fails report-traceability-smoke

Acceptance:
- Every reportable score can be traced to contributions.

Validation:
make test
make report-traceability-smoke
```

### W6-I01a：ReportExport schema + immutable repository

```text
Workstream: W6 Delivery
Epic: Report workflow
Task: Add ReportExport schema and immutable report repository
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W5-I02c

Goal:
Persist immutable report snapshots and generation tasks.

Dependencies:
W4-I01d
W5-I02c
W2-I03a

Affected modules:
apps/api/geno_api/domains/reports/*
packages/geno_core/geno_core/repositories/report_repository.py
tests/reports/*

Database changes:
report_tasks
report_exports

API changes:
POST /projects/{id}/reports
GET /reports/{id}

Frontend changes:
None

Worker changes:
None

Permission rules:
report.generate

Audit events:
report.generated

Test cases:
- New generation creates new version
- ReportExport immutable
- Snapshot references score snapshot and evidence summary

Acceptance:
- ReportExport immutable.

Validation:
make test
```

### W6-I01b：Markdown/CSV generation from fixed snapshot

```text
Workstream: W6 Delivery
Epic: Report workflow
Task: Generate Markdown and CSV from immutable ReportExport snapshot
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W6-I01a

Goal:
Generate text and tabular report artifacts from one fixed snapshot.

Dependencies:
W6-I01a

Affected modules:
workers/report*
tests/reports/*

Database changes:
None

API changes:
None

Frontend changes:
None

Worker changes:
report worker

Permission rules:
report.generate

Audit events:
report.artifact_created

Test cases:
- Markdown generated
- CSV generated
- Both artifacts use same snapshot id
- Methodology included
- Score contribution summary included

Acceptance:
- Markdown and CSV are deterministic for the same snapshot.

Validation:
make test
```

### W6-I01c：PDF generation and asset storage

```text
Workstream: W6 Delivery
Epic: Report workflow
Task: Generate PDF from report HTML/Markdown and store as EvidenceAsset/report asset
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W6-I01b/W4-I01b

Goal:
Create downloadable PDF report artifact without hand-writing PDF layout engine.

Dependencies:
W6-I01b
W4-I01b

Affected modules:
workers/report*
storage/*
tests/reports/*

Database changes:
None

API changes:
None

Frontend changes:
None

Worker changes:
report worker uses Playwright/Chromium HTML-to-PDF renderer

Permission rules:
report.generate

Audit events:
report.artifact_created

Test cases:
- PDF generated
- PDF stored through storage adapter
- PDF linked to report export
- Chinese font renders in Docker, default Noto Sans CJK
- PDF generation does not require external network resources
- Markdown/CSV/PDF content hashes point to the same ReportExport snapshot

Acceptance:
- PDF is generated from same ReportExport snapshot as Markdown/CSV.
- Playwright/Chromium renderer is pinned in Docker image.

Validation:
make test
```

### W6-I01d：Approval / publish / revoke lifecycle

```text
Workstream: W6 Delivery
Epic: Report workflow
Task: Implement report approval, publish, and revoke lifecycle
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W6-I01a

Goal:
Control customer visibility through explicit lifecycle states.

Dependencies:
W6-I01a
W2-I03a

Affected modules:
apps/api/geno_api/domains/reports/*
apps/admin-web/reports/*
tests/reports/*

Database changes:
report_exports status fields if not present

API changes:
POST /reports/{id}/approve
POST /reports/{id}/publish
POST /reports/{id}/revoke

Frontend changes:
Admin report workflow

Worker changes:
None

Permission rules:
report.approve
report.publish
report.revoke

Audit events:
report.approved
report.published
report.revoked

Test cases:
- Draft not visible to customer
- Approved not visible until published
- Published visible
- Revoked inaccessible

Acceptance:
- Report customer visibility is entirely state-driven.

Validation:
make test
```

### W6-I01e：Customer report center + permissioned download

```text
Workstream: W6 Delivery
Epic: Report workflow
Task: Implement customer report center and permissioned report download
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes after W6-I01c/W6-I01d

Goal:
Customers can securely view and download only authorized published reports.

Dependencies:
W6-I01c
W6-I01d
W4-I01c

Affected modules:
apps/api/geno_api/domains/reports/*
apps/customer-web/reports/*
tests/customer/*

Database changes:
None

API changes:
GET /customer/reports/{id}
GET /customer/reports/{id}/download

Frontend changes:
Customer report center

Worker changes:
None

Permission rules:
report.download published-only

Audit events:
report.downloaded
report.access_denied

Test cases:
- Published report visible to customer
- Revoked report inaccessible
- Cross-project report denied
- Download writes audit

Acceptance:
- Customer can securely download published PDF/CSV.
- Revoked reports cannot be downloaded.

Validation:
make test
make customer-access-negative-smoke
```

### W6-I01f：Report security tests

```text
Workstream: W6 Delivery
Epic: Report workflow
Task: Add report security tests for secrets, raw payload, revoked access, and traceability
Owner: Codex
Priority: P0
Size: S
Can Parallelize: Yes after W6-I01e

Goal:
Block report leaks and untraceable customer-visible numbers.

Dependencies:
W6-I01e

Affected modules:
tests/reports/*
tests/customer/*
scripts/*

Database changes:
None

API changes:
None

Frontend changes:
None

Worker changes:
None

Permission rules:
report.download published-only

Audit events:
report.access_denied

Test cases:
- No provider key in report
- No raw secret in report assets
- Revoked download denied
- report-traceability-smoke passes

Acceptance:
- `make no-secret-leak-smoke`, `make report-traceability-smoke`, and `make customer-access-negative-smoke` pass for reports.

Validation:
make no-secret-leak-smoke
make report-traceability-smoke
make customer-access-negative-smoke
```

### W7-I01：Action Plan 最小闭环

```text
Workstream: W7 Optimization
Epic: Action Plan
Task: Generate and manage action recommendations from score/source gaps
Owner: Codex
Priority: P0
Size: L
Can Parallelize: Yes after W5-I02c

Goal:
Turn diagnosis into executable actions.

Dependencies:
W5-I02c
W6-I01f preferred

Affected modules:
apps/api/geno_api/domains/actions/*
packages/geno_core/geno_core/repositories/action_repository.py
apps/admin-web/actions/*
apps/customer-web/actions/*
tests/actions/*

Database changes:
action_recommendations
action_tasks

API changes:
POST /projects/{id}/action-plans/generate
PATCH /action-tasks/{id}

Frontend changes:
Admin action plan UI
Customer action read-only UI

Worker changes:
Optional action generation worker

Permission rules:
action.manage internal
action.read customer-visible

Audit events:
action.generated
action.updated
action.customer_visible_changed

Test cases:
- Missing brand mention creates action
- Source gap creates action
- Competitor pressure creates action
- Evidence link required
- Customer visibility respected
- Customer visibility defaults to false
- Manual owner/status update works

Acceptance:
- At least 3 deterministic action types generated from real scoring/evidence data:
  1. brand not mentioned
  2. competitor outranks brand
  3. missing / weak citation source
- Each action links to score contribution or evidence.
- Customer sees only customer-visible actions.
- P0 does not require complex workflow, automation, or multi-step approvals.

Validation:
make test
```

### W7-I02：Retest 最小闭环

```text
Workstream: W7 Optimization
Epic: Retest
Task: Implement retest run linked to action and baseline report
Owner: Codex
Priority: P0
Size: L
Can Parallelize: Yes after W7-I01

Goal:
Run post-action collection/scoring/reporting comparison.

Dependencies:
W7-I01
W3-I02
W3-I03
W5-I02c
W6-I01f

Affected modules:
apps/api/geno_api/domains/actions/*
apps/api/geno_api/domains/collection/*
apps/api/geno_api/domains/reports/*
workers/retest*
tests/retest/*

Database changes:
retest_runs

API changes:
POST /action-tasks/{id}/retest-runs
GET /retest-runs/{id}

Frontend changes:
Admin retest UI
Customer retest result UI

Worker changes:
retest worker or orchestration script

Permission rules:
retest.run internal
retest.read published/customer-visible

Audit events:
retest.created
retest.started
retest.completed
retest.failed

Test cases:
- Retest links to baseline snapshot
- Retest can rerun same prompt set for one platform or selected platforms
- Retest creates a new score snapshot
- Retest comparison includes before_score, after_score, delta
- Customer only sees published result

Acceptance:
- Retest can compare before/after scores and produce Markdown-only report section.
- P0 does not require complex durable workflow or statistical significance model.

Validation:
make test
make production-v1-e2e
```

### W8-I01：Knowledge Base 薄闭环

```text
Workstream: W8 Enablement
Epic: Knowledge Base
Task: Implement minimal KB import and approved facts flow
Owner: Codex
Priority: P1
Size: L
Can Parallelize: Yes after W4-I01a

Goal:
Allow approved customer facts to support content recommendations.

Dependencies:
W4-I01a
W2-I03a

Affected modules:
apps/api/geno_api/domains/knowledge/*
packages/geno_core/geno_core/repositories/knowledge_repository.py
apps/admin-web/knowledge/*
tests/knowledge/*

Database changes:
knowledge_documents
knowledge_facts

API changes:
POST /projects/{id}/knowledge-documents
POST /knowledge-documents/{id}/extract-facts
PATCH /knowledge-facts/{id}

Frontend changes:
KB import/review UI

Worker changes:
knowledge worker optional

Permission rules:
knowledge.import
knowledge.review
knowledge.read_approved

Audit events:
knowledge.document_imported
knowledge.fact_created
knowledge.fact_approved
knowledge.fact_deprecated
knowledge.fact_forbidden

Test cases:
- Import text/markdown
- Extract draft facts
- Approve fact
- Deprecated fact excluded
- Forbidden fact excluded
- Customer visibility controlled

Acceptance:
- Approved facts are queryable for content workbench.
- Non-approved facts cannot enter customer-visible content.

Validation:
make test
```

### W8-I02：Content Workbench 薄闭环

```text
Workstream: W8 Enablement
Epic: Content
Task: Generate content brief/draft from action plan and approved facts
Owner: Codex
Priority: P1
Size: L
Can Parallelize: Yes after W8-I01

Goal:
Create evidence-grounded content suggestions without becoming a generic content platform.

Dependencies:
W7-I01
W8-I01

Affected modules:
apps/api/geno_api/domains/content/*
packages/geno_core/geno_core/repositories/content_repository.py
apps/admin-web/content/*
tests/content/*

Database changes:
content_assets
content_reviews

API changes:
POST /action-tasks/{id}/content-assets
PATCH /content-assets/{id}
POST /content-assets/{id}/review

Frontend changes:
Content task/draft/review UI

Worker changes:
content worker optional

Permission rules:
content.generate
content.review

Audit events:
content.created
content.updated
content.reviewed
content.exported

Test cases:
- Content created from action
- Approved facts included
- Draft facts excluded
- Forbidden facts blocked
- Review required before export

Acceptance:
- Content asset links to action, evidence, and approved facts.
- Markdown export works.

Validation:
make test
```

### W8-I03：Distribution task 回填

```text
Workstream: W8 Enablement
Epic: Distribution
Task: Implement manual distribution task and URL/proof backfill
Owner: Codex
Priority: P1
Size: M
Can Parallelize: Yes after W8-I02

Goal:
Close the loop from content/action to external publication evidence and retest.

Dependencies:
W8-I02
W7-I02 preferred

Affected modules:
apps/api/geno_api/domains/distribution/*
packages/geno_core/geno_core/repositories/distribution_repository.py
apps/admin-web/distribution/*
tests/distribution/*

Database changes:
distribution_tasks

API changes:
POST /content-assets/{id}/distribution-tasks
PATCH /distribution-tasks/{id}

Frontend changes:
Distribution task UI

Worker changes:
Optional notification/retest trigger

Permission rules:
distribution.create
distribution.update

Audit events:
distribution.created
distribution.updated
distribution.url_backfilled
distribution.completed

Test cases:
- Create manual distribution task
- Assign owner
- Backfill URL
- Attach proof
- Link to retest

Acceptance:
- Distribution task can be tied back to action and forward to retest.

Validation:
make test
```

### W9-I01：Observability 最小生产门禁

```text
Workstream: W9 Ops
Epic: Observability
Task: Implement production observability baseline
Owner: Codex
Priority: P0
Size: L
Can Parallelize: Yes

Goal:
Make API, worker, connector, report, audit, auth denial, and cost observable.

Dependencies:
None

Affected modules:
apps/api/geno_api/core/metrics.py
apps/api/geno_api/core/logging.py
workers/*
docker-compose*
observability/*
tests/ops/*

Database changes:
Optional runtime_notifications

API changes:
GET /health
GET /metrics

Frontend changes:
Dashboard Web health cards

Worker changes:
Emit structured JSON logs, metrics, and OTel spans/events at job boundaries

Permission rules:
Metrics endpoint protected or internal-only in production

Audit events:
ops.alert_triggered optional

Test cases:
- API latency metric emitted
- Worker job metric emitted
- Connector failure metric emitted
- Cost metric emitted
- Auth denial metric emitted
- Report job metric emitted
- Structured JSON logs contain request_id / tenant_id / project_id where safe
- Logs redact provider key, session token, invitation token
- Slack webhook/email alert can be triggered in smoke mode
- Sentry integration is optional and cannot be a P0 blocker

Acceptance:
- Prometheus scrapes API/worker metrics.
- Grafana dashboard loads.
- Port conflicts resolved.
- `/health` and `/metrics` are available in production topology.
- Alert baseline covers connector failure spike, job failure, auth denial spike, backup failure.

Validation:
make docker-config-observability
make ops-smoke
```

### W9-I02：Backup / restore 演练

```text
Workstream: W9 Ops
Epic: Backup and restore
Task: Implement PostgreSQL and object storage backup/restore smoke
Owner: Codex
Priority: P0
Size: M
Can Parallelize: Yes

Goal:
Ensure production data can be recovered.

Dependencies:
W4-I01a preferred

Affected modules:
scripts/backup*
scripts/restore*
docs/ops/*
tests/ops/*

Database changes:
None

API changes:
None

Frontend changes:
Dashboard backup status optional

Worker changes:
None

Permission rules:
Ops-only

Audit events:
backup.started
backup.completed
restore.started
restore.completed optional

Test cases:
- DB backup creates artifact
- Object storage backup creates artifact
- Restore into empty environment succeeds
- Restored evidence hash matches
- Report artifact restore succeeds
- Uploaded evidence restore succeeds
- Encrypted secret material restore runbook exists without exposing raw key
- RPO <= 24h documented
- production-internal RTO <= 4h documented

Acceptance:
- Backup/restore runbook exists.
- Smoke script passes locally/staging.
- Backup covers PostgreSQL and object storage evidence/report/upload assets.

Validation:
make backup-smoke
```

### W10-I01：production-v1-e2e 骨架

```text
Workstream: W10 QA
Epic: End-to-end release
Task: Implement production-v1-e2e script skeleton with fixture-free production path checks
Owner: Codex
Priority: P0
Size: L
Can Parallelize: Yes

Goal:
Create the final release rehearsal entrypoint early.

Dependencies:
W1 baseline

Affected modules:
scripts/production_v1_e2e.py
Makefile
tests/e2e/*
docs/release/*

Database changes:
None directly

API changes:
None

Frontend changes:
None initially

Worker changes:
None initially

Permission rules:
Must assert correct permissions

Audit events:
Must assert audit existence

Test cases:
- Script fails if fixture mode used
- Script creates tenant/project/prompts
- Script can run partial dry-run until later slices fill in
- Script reports missing capabilities clearly

Acceptance:
- `make production-v1-e2e` exists.
- Early versions may mark not-yet-implemented steps as explicit pending, not silent pass.
- By final gate, no pending P0 step remains.

Validation:
make production-v1-e2e
```

---

## 17. 执行顺序建议

### 17.1 第一执行波：降低最大返工风险

必须先做：

1. W10-I01 production-v1-e2e skeleton。
2. W1-I03 demo fallback cleanup。
3. W1-I01 FastAPI domain route。
4. W1-I02 Repository boundary。
5. W2-I01a AuthContext contract。
6. W3-I00 Provider secret storage and redaction baseline。
7. W3-I01 Connector contract。
8. W4-I01a EvidenceAsset storage。
9. W9-I01 Observability skeleton。
10. W9-I02 Backup / restore skeleton。

原因：

这些任务定义了后续所有模块的边界。如果先做页面或业务功能，后续 Auth/RLS/Evidence 接入会大面积返工。

### 17.2 第二执行波：真实生产核心

并行做：

1. W2-I02 Invitation/session。
2. W2-I03a RBAC matrix。
3. W2-I03b membership schema。
4. W2-I03c RLS smoke。
5. W3-I02 OpenAI collection。
6. W3-I03 Perplexity collection。
7. W3-I04 Google manual backfill。
8. W9-I01 接真实 API / worker / connector metrics。
9. W9-I02 接真实 DB / object storage backup smoke。

### 17.3 第三执行波：智能和交付闭环

依赖真实采集和证据链后做：

1. W5-I01 AnswerAnalysis。
2. W5-I02a Scoring profile。
3. W5-I02b Score snapshot calculator。
4. W5-I02c ScoreContribution traceability。
5. W6-I01a ReportExport schema。
6. W6-I01b Markdown/CSV generation。
7. W6-I01c PDF generation。
8. W6-I01d Approval / publish / revoke。
9. W6-I01e Customer report center。
10. W6-I01f Report security tests。
11. W7-I01 Action Plan。
12. W7-I02 Retest。

### 17.4 第四执行波：Enablement 薄闭环

在核心报告链路稳定后做：

1. W8-I01 Knowledge Base。
2. W8-I02 Content Workbench。
3. W8-I03 Distribution task。
4. Final security-smoke。
5. Final production-v1-e2e。
6. Final enablement-v1-e2e，如果声明 P1 完成。

---

## 18. 每日工程节奏

每个工作日必须保持：

1. main branch 可启动。
2. lint / typecheck 不长期红。
3. 已完成 slice 的 e2e 不回退。
4. 新增 schema 必有 migration。
5. 新增 API 必有权限测试。
6. 新增客户可见数据必有审计测试。
7. 新增 report 字段必有 traceability 测试。
8. 新增 connector 行为必有 failure category 测试。
9. 新增 UI 页面必须接真实 API 或明确标记为 shell，不得标记完成。
10. demo / fixture 只能在 dev/test 环境出现。

---

## 19. 投产红线

出现以下任一情况，Production v1 不允许上线：

1. 生产环境仍默认使用 fixture。
2. 新建真实项目仍写入 demo fallback。
3. OpenAI 真实采集未通过。
4. Perplexity 真实采集未通过。
5. Google manual backfill 未通过。
6. Google browser/SERP 未形成 Go/No-Go 决策。
7. 报告数字不能追溯到 evidence。
8. ReportExport 可被覆盖。
9. 客户可以访问未发布或已撤回报告。
10. 客户可以跨 tenant/project 访问数据。
11. provider key 出现在 API response、日志、前端 bundle 或报告中。
12. invitation token 可重复使用。
13. 客户访问依赖长期 URL query token。
14. RLS smoke 失败。
15. security-smoke 失败。
16. production-v1-e2e P0 步骤仍 pending。
17. 备份恢复演练失败。
18. 安全扫描发现高危问题未处理。
19. 监控无法显示 API/worker/connector/report/auth denial 状态。
20. 运维手册、部署手册、恢复手册缺失。

---

## 20. 最终验收定义

Production v1 最终验收不是看页面数量，而是看完整生产链路。

最终验收必须证明：

```text
真实用户
真实租户
真实权限
真实项目
真实配置
真实采集
真实证据
真实解析
真实评分
真实报告
真实客户访问
真实行动计划
真实复测
真实审计
真实监控
真实备份恢复
```

最终命令：

```bash
make lint
make typecheck
make test
make db-smoke
make rls-smoke
make runtime-e2e
make security-smoke
make production-v1-e2e
make no-fixture-production-smoke
make no-secret-leak-smoke
make report-traceability-smoke
make customer-access-negative-smoke
make connector-real-smoke
make ops-smoke
make backup-smoke
make docker-config
make docker-config-observability
git diff --check
```

如果同时声明 P1 Enablement 完成，还必须运行：

```bash
make enablement-v1-e2e
```

Local/CI 可以 skip `connector-real-smoke` 的真实 provider 子集；staging / production-internal 不允许 skip。

最终人工验收：

1. Super Admin 创建 tenant。
2. Tenant Admin 邀请 Project Owner / Analyst / Reviewer / Client Viewer。
3. Project Owner 创建项目。
4. Analyst 配置 prompts 和 connectors。
5. 系统完成 OpenAI / Perplexity / Google manual 采集。
6. Reviewer 审核 Google manual 和报告。
7. Project Owner 发布报告。
8. Client Viewer 登录客户门户并下载报告。
9. Admin 撤回报告。
10. Client Viewer 再次下载失败。
11. Analyst 查看 evidence traceability。
12. Analyst 生成人工修正。
13. Scoring 重新生成 snapshot。
14. Report 生成新版本。
15. Action Plan 生成。
16. Retest 生成对比结果。
17. Dashboard 显示运行状态。
18. Backup / restore smoke 通过。

P1 Enablement 人工验收单独执行：

1. Content task 从 action 创建。
2. Knowledge facts 通过审核。
3. Content asset 基于 approved facts 生成。
4. Content review 通过。
5. Distribution task 回填 URL 或发布证明。
6. Distribution task 可关联 Action Plan 和 Retest。

---

## 21. 给 Codex 的全局指令模板

每次让 Codex 执行任务时，使用以下模板：

```text
You are working on GEO Production v1.

Follow docs/GEO_PRODUCTION_V1_EXECUTION_PLAN.md.

Task:
<填入具体 task id 和描述>

Hard rules:
- Do not introduce fixture/demo fallback into production paths.
- Do not bypass AuthContext, RBAC, or RLS.
- Do not expose provider keys, session tokens, or invitation tokens.
- Do not put new domain logic into giant main.py.
- Do not mark UI complete unless it talks to real API.
- Every reportable customer-facing value must be traceable to evidence.
- Every protected write must emit an audit event.
- Add or update tests.
- Update docs if behavior changes.

Before coding:
1. Identify affected modules.
2. Identify database migrations.
3. Identify permission rules.
4. Identify audit events.
5. Identify tests.

After coding:
1. Run the narrow test set.
2. Run the relevant make target.
3. Report changed files.
4. Report validation commands and results.
5. Report remaining risks.
```

---

## 22. 本版规划的成功标准

本版规划成功，不是因为内容更多，而是因为它让项目变成可执行系统：

1. Codex 能按 task 修改代码，不会乱扩范围。
2. 人类能按 gate 判断是否可合并。
3. 每个核心能力都能被自动化测试证明。
4. 每个客户可见结果都能追溯。
5. 每个生产风险都有红线。
6. Google 风险不会拖死整个项目。
7. KB / Content / Distribution 有真实闭环但不无限扩展。
8. 最终 Production v1 是组合已有可运行切片，而不是第一次整体拼装。

目标可行性评分：

```text
产品可行性：9/10
工程可行性：9/10
交付可行性：9/10
```
