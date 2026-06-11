# 智推时代 GEO / GENO 调研与 SaaS 落地文档库

本仓库是围绕 **智推时代（GenOptima）** 及其 **GEO（Generative Engine Optimization，生成式引擎优化）** 业务的一次完整调研与产品落地规划。内容包括：公司与行业可审计调研复盘、GENO 方法论与技术栈拆解、竞品格局、合作案例核查，以及面向**澳大利亚首发**的 GENO SaaS MVP 技术设计与需求拆解。

本库已从文档与规划进入工程实现：除调研文档外，当前已包含 FastAPI API、Next.js Runtime Console、Python 核心契约、P0a runtime-checkable plugin contracts 与 `NotConfigured*` stubs、AU 项目启动包、DTC 电商行业模板、100 条 Prompt Pack、M2a evidence chain、M2a Collection Run Summary、M2b Google spike gate fixture、M3 comparative parser（rule primary + judge fixture）+ AUVisibilityScore、ScoringFormula registry（active `au_visibility_v1` + candidate `au_visibility_v1_1_local_boost`）、项目级 Score Weight Config、Human Review Records、M4 Citation Graph + Competitor Benchmark、M5 Markdown/CSV/PDF Evidence Report Export 与 MinIO/S3-compatible artifact 归档、API-vs-browser Fidelity Check、M6 Action Plan + Retest comparison、M7 Knowledge Facts + Content Draft + Integrations fixture、KnowledgeFactEmbedding pgvector runtime search、Traceability Bundle、PostgreSQL repository 映射、`DATABASE_URL` runtime connection、runtime API PostgreSQL connection pool、runtime readiness/diagnostics 与 Prometheus 文本格式 `/metrics`、AU 项目启动包 runtime 创建/读取 API、AU 启动包/prompt 元数据持久化、worker `--persist` / `--persist-analysis` / `--score-formula-version` 写库开关、runtime project / project brand kit / project brand logo upload / score weight config / score formula catalog / human review / prompt / prompt CSV/file import / prompt import history / evidence / collection run summary / fidelity check / manual backfill / entity alias confirmation / entity alias candidates / evidence CSV export / saved views / score / citation graph / report / report artifact / action plan / content engine / knowledge fact search / traceability 查询 API、Runtime Console Project Bootstrap / Brand Kit / Logo Upload / Score Weights / Score Formula selector / Human Review Trail / Entity Alias Candidates / Runtime Filters / Evidence Sort / Saved Views / Prompt Pack / Prompt CSV Import / Prompt File Import / Prompt Import History / Manual Backfill / Latest Evidence / Collection Run Quality / Evidence Runs / Score Contributions / Citation Graph & Competitors / Citation Graph Map / Report Snapshot / Report History / Report Method & Evidence Appendix / API-browser Fidelity / Action Plan & Retest Detail / Content Engine Detail / pgvector Knowledge Search / Traceability Detail、Traceability Map、节点级 details 钻取与锚点深链路面板、SQL 迁移、PostgreSQL RLS/GUC 项目隔离、Docker Compose、CI、ADR 与工程实施审计日志。真实 provider preflight 已支持 `preflight_summary`、`preflight_audit_checklist`、`preflight_payload_hash`、`make verify-api-preflight` 离线复核、`make preflight-manifest` 证据索引和 `make au-p0a-runbook` 真实批次命令计划。报告 artifact 下载已可继承当前 Runtime Filters/Sort，只过滤导出的证据附录，不改写冻结 `ReportExport`、`report_exports.method_disclosure` 与评分快照；`report_exports.method_disclosure.score_rate_denominators` 会冻结 Trigger/Mention/Recommendation 三类 rate 的 numerator、denominator、formula 和本报告证据行分母计数；PDF artifact 支持 `template=white_label` 白标模板，优先从项目级 Brand Kit 读取客户名、服务商名、Logo URL、主题色和页脚，URL query 可显式覆盖客户名/服务商名，响应头会返回 template 与 template hash；Logo Upload 会把图片 raw body 归档到 MinIO/S3-compatible `brand-assets/<project_id>/...`，再把 `s3://...` URI 写回 Brand Kit 并生成 `project_brand_logo_uploaded` 审计事件；Report History 会按当前 AU runtime project 读取最近 5 个冻结 `ReportExport`，展示版本、导出时间、方法 hash、Method Disclosure、对象存储 URL、即时 artifact 下载入口、白标 PDF 下载入口和报告审计摘要。核心原则仍是**可审计**：每一个调研结论尽量回指原始来源（PDF、网页快照、行业报告），每一个工程输出逐步建立 `AuditEvent / EvidenceLink / ScoreContribution / CollectionRunSummary / ReportExport / ApiBrowserFidelityCheck / ActionRecommendation / RetestComparison / ContentDraft / KnowledgeFactEmbedding / HumanReviewRecord / TraceabilityBundle` 溯源链。

当前代理商工作流已推进到项目级 read path、客户项目创建、项目级白标配置、项目成员管理和最小运行时项目访问控制：Runtime Console 可通过 URL/下拉选择 `project_id`，并让 brand kit、prompt、evidence、alias、saved view、score、graph、report、action、content、traceability 查询收敛到同一个 runtime project；Project Bootstrap 面板可提交 tenant/project/brand/category/brand domains/product lines/3-5 competitors，生成新的 AU/DTC 客户项目、100 条 prompt 和启动审计事件；Project Members 面板可读取 `project_members`，通过 `POST /v1/project-members/runtime` upsert owner/admin/analyst/viewer 成员并写入 `project_member_saved`，也可通过 `DELETE /v1/project-members/runtime` 删除成员并写入 `project_member_deleted`，repository 会阻止删除或降级最后一个 owner；Brand Kit 表单可保存 `client_name/prepared_by/logo_url/primary_color/secondary_color/footer_text`，生成 `project_brand_kit_saved` 审计事件，并成为白标 PDF 的项目默认值；Logo Upload 表单可上传 PNG/JPEG/WebP/SVG/GIF 到对象存储，写回 Brand Kit 的 `logo_url`，并生成 `project_brand_logo_uploaded` 审计事件。API 可通过 `GENO_RUNTIME_PROJECT_ACCESS_CONTROL=1` 开启项目成员门禁和最小角色矩阵：runtime project 列表按 `project_members` 过滤，项目创建 owner 绑定当前 actor，项目级读接口要求成员关系；默认 demo 模式仍从 `X-GENO-Actor-Id` 取 actor，设置 `GENO_RUNTIME_AUTH_MODE=jwt` 后会要求 `Authorization: Bearer <JWT>` 并用 `GENO_RUNTIME_JWT_SECRET` 校验 HS256 签名；设置 `GENO_RUNTIME_AUTH_MODE=jwks` 后会优先用 `GENO_RUNTIME_JWKS_JSON` 中的 inline JWKS 校验 RS256 签名，也可用 `GENO_RUNTIME_JWKS_URL` 拉取远端 JWKS 并按 `GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS` 缓存；若未配置显式 JWKS URL，可通过 `GENO_RUNTIME_OIDC_DISCOVERY_URL` 或 URL-form `GENO_RUNTIME_JWT_ISSUER` 拉取 OIDC discovery document 并发现 `jwks_uri`，discovery document 按 `GENO_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS` 缓存；生产兜底默认关闭，只有显式设置 `GENO_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS` 或 `GENO_RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS` 为正数时，远端 refresh 失败才会在对应 stale 窗口内继续使用同 URL 的过期缓存；JWT/JWKS 模式都会从 `sub` 或 `GENO_RUNTIME_JWT_ACTOR_CLAIM` 解析 actor，并支持 issuer/audience/clock skew 校验；成员维护、prompt 导入、saved view 保存、Brand Kit/Logo、Score Weights 等管理写操作要求 owner/admin；entity alias confirm、manual backfill、human review、fidelity check 等分析复核写操作允许 owner/admin/analyst；viewer 只读。报告 artifact、traceability 等对象级入口会先反查所属项目再校验。数据库层已通过 `0010_runtime_project_rls` 增加 `geno_runtime_app` 非 bypass 运行时角色、PostgreSQL RLS policy 和 `geno.runtime_*` session GUC 上下文，Compose runtime 服务默认使用 app role，并由 runtime E2E 验证 actor 只能看见自己项目；API 常驻服务默认启用进程内 PostgreSQL connection pool（`GENO_RUNTIME_DB_POOL_ENABLED=1`、`GENO_RUNTIME_DB_POOL_MAX_SIZE=10`、`GENO_RUNTIME_DB_POOL_TIMEOUT_SECONDS=5`），每次请求归还连接时会 rollback 业务事务、清空 RLS session GUC 并提交清理，避免 actor/project 上下文跨请求泄漏。该能力用于可审计复盘、多项目操作演示和最小跨客户隔离，但仍不等同于完整 Keycloak/OIDC login/session 与前端 SSO 登录流、邀请邮件、真实用户目录、账单隔离、高级主题编辑或完整多租户授权后台。

人工复核已从单纯留痕推进到最小队列与内容草稿状态投影：`GET /v1/human-reviews/runtime/queue` 会从 `visibility_score_snapshots` 与 `content_drafts` 聚合待审对象，返回 `target_type/target_id/title/queue_status/priority/reason/latest_review/evidence_refs`，并在 Runtime Console 的 Human Review 面板展示 Review Queue。对 `target_type=content_draft` 的 `POST /v1/human-reviews/runtime` 会先追加 `human_review_records`，再把同项目 `content_drafts.review_status` 投影为本次复核状态，并写入 `content_draft_review_status_updated` 审计事件；评分、原始草稿正文和证据绑定仍保持不可变。分配、通知、权限、复杂审批流和抽样校准仍放在后续阶段。

运行时预警已补成只读解释模型：`GET /v1/runtime-alerts` 会基于最新 `VisibilityScoreSnapshot`、`ScoreContribution`、`AnswerAnalysis`、`SourceGap`、`CompetitorBenchmark` 和 `ActionRecommendation` 派生 `brand_absent`、`low_recommendation_rate`、`negative_sentiment`、`source_gap`、`competitor_pressure` 五类 alert，返回 severity、阈值、指标值、证据 refs、相关 action 和评分审计 refs。Runtime Console 的 Runtime Alerts 面板会展示这些预警与证据链；当前不新增告警表，不做实时推送、通知、SLA 或订阅策略。

> 🛠 **开发与管理入口**：[PROJECT-PLAN.md](PROJECT-PLAN.md) —— 把澳大利亚首发规格拆成 8 个里程碑、任务清单与验收标准（DoD），是从 `docs/` 规格走向工程交付的待办层。
>
> 🗺 **架构图**：[ARCHITECTURE.md](ARCHITECTURE.md) —— GENO SaaS 澳洲首发系统的分层结构、可插拔点、证据优先数据流水线，以及 `AuditEvent / EvidenceLink / ScoreContribution / ReportExport` 审计、溯源、解释链（Mermaid）；出版级图注与设计规范见 [docs/figure-specs.md](docs/figure-specs.md)。

## 目录结构

```
.
├── README.md                           # 本文件：项目导航
├── PROJECT-PLAN.md                     # 开发与管理：里程碑 / 任务 / 验收(DoD)
├── ARCHITECTURE.md                     # 系统架构图（分层 / 可插拔 / 数据流，Mermaid）
├── apps/
│   ├── api/                            # FastAPI API 壳
│   └── web/                            # Next.js Runtime Console
├── packages/
│   └── geno_core/                      # 核心契约、AU 启动包、Prompt Pack、审计与评分模型
├── infra/
│   ├── docker-compose.yml              # PostgreSQL+pgvector、MinIO、API、Web
│   └── db/migrations/                  # up/ 初始化迁移，down/ 回滚脚本
├── workers/                            # 采集 worker 入口预留
├── tests/                              # 核心契约测试
├── decisions/                          # ADR 架构决策记录
├── .github/workflows/                  # CI
└── docs/                               # 规格源、调研报告、审计日志
    ├── 智推时代-全球GEO业务介绍.pdf        # 智推时代官方商业介绍（公司自述原始材料）
    ├── 智推时代GENO项目完整调研报告.md       # ★ 总报告：整合下列全部分项调研
    ├── *-可审计调研复盘.md                  # 7 份分项调研复盘
    ├── GENO-SaaS-*.md                       # 3 份 SaaS 产品落地文档
    ├── figure-specs.md                      # 架构图出版级图注与设计规范
    └── research_sources/                    # 逐来源证据（摘要 + 原始网页快照 + 报告 PDF）
```

## 本地验证

推荐先跑与 GitHub Actions 对齐的聚合门禁：

```bash
make ci-local
```

该目标会依次执行静态质量门禁、Python 合约/运行时测试、Runtime Console production build、默认/LLM/scheduler/observability/db-smoke 五组 Compose config 静态校验、临时 PostgreSQL schema smoke，以及 Postgres+MinIO runtime E2E。需要拆开排障时可单独执行：

```bash
make quality
make test
make web-build
make docker-config
make docker-config-llm
make docker-config-scheduler
make docker-config-observability
make docker-config-db-smoke
make db-smoke
make runtime-e2e
```

`make db-smoke` 会用独立 Compose project 启动临时 PostgreSQL+pgvector 新卷，让 `/docker-entrypoint-initdb.d` 执行全部 `infra/db/migrations/up/`，随后运行 `scripts/verify_db_smoke.py` 检查 `uuid-ossp`/`vector` 扩展、核心表和关键列、`geno_runtime_app` 非 bypass runtime role、RLS helper functions/policies，并用 admin/runtime 两个连接证明开启 `geno.runtime_*` GUC 后 actor 只能读取授权项目；结束时自动 `down -v` 清理容器和卷。

`make runtime-e2e` 会用独立 Compose project 启动临时 PostgreSQL+pgvector 与 MinIO，构建 `runtime-e2e` 容器，跑 fixture worker `--persist --persist-analysis`，验证 Postgres 中的 answer/score/report/traceability 行、MinIO 中的 Markdown/PDF/CSV report artifact，并用 fake official API response 验证 `geno-api-snapshot://...` 会归档为 `s3://...` EvidenceAsset 和 `api_snapshot_assets_archived` 审计事件；结束时自动 `down -v` 清理容器和卷。

真实 Perplexity/OpenAI key 到位后，用 `make api-preflight` 跑 AU P0a 最小官方 API smoke（1 个 prompt × Sydney × k=3 × 2 平台）。该目标会先检查 collector health，再要求 `P0ACollectionReadinessGate` 通过；缺 key 时底层 worker 以退出码 `3` 在采集前失败，避免把配置缺失误判为真实采集结论。

预检 JSON 会默认写入 `docs/runtime_preflight/api-preflight-latest.json`（可用 `GENO_API_PREFLIGHT_OUTPUT_PATH` 覆盖），内容与 stdout 一致，包含 `collector_health`、`collector_health_gate`、可选 `p0a_readiness_gate`、`preflight_summary`、`preflight_audit_checklist`、`preflight_payload_hash` 和 `preflight_output_path`。`preflight_summary` 会给出本次预检 phase、exit code、是否可进入 design partner、失败原因摘要和建议下一步；`preflight_audit_checklist` 会把 collector health、P0a readiness、collection failures、output path 和 replay args 折叠成可审计 checklist，便于复盘是否可扩大到 design partner；`preflight_payload_hash` 是剔除自身字段后的 canonical JSON sha256，可用于复算 stdout/落盘文件是否一致。

`make verify-api-preflight` 会离线复算该文件的 hash、summary/checklist 版本和必备字段，缺 key 失败预检只要结构完整也会通过审计校验；`make preflight-manifest` 会生成 `docs/runtime_preflight/api-preflight-manifest-latest.json`，记录 preflight 文件 sha256、verifier 结果、run summary、blocking reasons、worker args 和 manifest 自身 hash，方便后续交付包索引。`make au-p0a-runbook` 会生成从 preflight 到 5 prompt 小批次再到 100 prompt × 4 geo 完整批次的机器可读执行计划，`make verify-au-p0a-runbook` 会复算 runbook hash、步骤顺序、planned runs 和 gate 命令；`make au-p0a-runbook-dry-run` 会把 9 个步骤、预计产物、外部 API 调用风险、必需环境缺口和 `execution_payload_hash` 写入 `docs/runtime_preflight/au-p0a-runbook-execution-latest.json`，默认不执行任何命令；`make verify-au-p0a-runbook-execution` 会离线复算 execution hash、步骤计数和 dry-run 不执行命令等 invariant；`make au-p0a-readiness` 会把 runbook 校验、必需环境变量、preflight/small batch JSON 与 manifest 的 design-partner gate 状态合并成 `docs/runtime_preflight/au-p0a-readiness-latest.json`，并可用 `GENO_AU_P0A_READINESS_PHASE=preflight|small_batch|full_batch` 切换阶段。readiness 默认只确认 `DATABASE_URL` 是否存在，不主动连接数据库；真实执行前可设置 `GENO_AU_P0A_REQUIRE_DB_CHECK=1` 或直接运行 `python3 scripts/verify_au_p0a_readiness.py --require-db-check`，用只读 `SELECT 1` 验证 PostgreSQL 可连。`make au-p0a-package` 会生成 `docs/runtime_preflight/au-p0a-evidence-package-latest.json`，汇总 runbook、readiness、preflight/small/full JSON 和 manifest 的存在状态、file sha256、payload hash、ready 状态和缺口；`make verify-au-p0a-package` 会复算 package hash 并校验 summary 与 artifacts 是否一致。`make au-p0a-status` 会生成 `docs/runtime_preflight/au-p0a-status-latest.json`，把 runbook、三阶段 readiness、证据包 verifier、completion percent、design-ready percent、remaining blockers 和 next action 合成一份总控进度报告；`make verify-au-p0a-status` 会离线复算 status report hash、completion、remaining blockers 与 next action。提交版说明见 [AU-P0a-真实批次运行手册.md](/home/ymm/ym/gz/20260608-geo/docs/AU-P0a-真实批次运行手册.md)。需要试点准入时可直接运行 `python3 scripts/verify_preflight_payload.py --require-design-partner-ready`；该目录下的运行时 JSON 已被 gitignore，适合保留本地审计证据但不提交凭证相关上下文。

核心服务一键启动入口：

```bash
docker compose -f infra/docker-compose.yml up --build
```

LiteLLM proxy 作为可选 profile 接入，默认不会随核心服务启动。需要用真实 LLM judge 时，先提供供应商 key 和 master key，再启动 profile；`collector-worker-litellm` 会把 `--judge-gateway litellm --judge-model geno-gpt-4.1-mini` 走到同一个 `LiteLLMGateway` adapter：

```bash
OPENAI_API_KEY=... LITELLM_MASTER_KEY=... \
docker compose -f infra/docker-compose.yml --profile llm-gateway up --build litellm

OPENAI_API_KEY=... LITELLM_MASTER_KEY=... \
docker compose -f infra/docker-compose.yml --profile llm-gateway run --rm collector-worker-litellm
```

默认地址：API `http://localhost:8000/health`，控制台 `http://localhost:3000`。控制台会读取 runtime project / project brand kit / project brand logo upload / score weight config / score formula catalog / human review / prompt / prompt CSV/file import / prompt import history / evidence / collection run summary / fidelity check/trend / entity alias / entity alias candidates / saved views / score / graph / report / report artifact / action / content / knowledge fact search / traceability API；Runtime Filters 支持通过 URL 查询参数按 `project_id`、`platform`、evidence `city`、`intent_type` 筛选 evidence，并用 `intent_type` 同步筛选 prompt 列表；Evidence Sort 支持 `collected_at_desc`、`collected_at_asc`、`cost_desc`、`cost_asc`、`citation_count_desc`、`audit_count_desc` 受控排序；Saved Views 可把当前筛选、排序、evidence query path 与 export path 保存到 PostgreSQL，并写入 `runtime_saved_view_saved` 审计事件；控制台同时展示实际 API 查询路径和筛选后 Evidence CSV 下载入口，CSV 响应含 `X-GENO-Evidence-Export-Hash` 与 `X-GENO-Evidence-Export-Sort`；Project Bootstrap 面板可创建并读回可配置 AU/DTC 客户启动包，输入 tenant、project、brand、category、brand domains、product lines 和 3-5 competitors 后生成 100 条 prompt、品牌/竞品实体和 `project_bootstrap_created` 审计事件，并提供 Brand Kit 表单保存项目级白标默认值、Logo Upload 表单归档品牌图片、Score Weights 表单读取 `/v1/score-formulas/runtime`、选择评分公式版本并保存项目级 AUVisibilityScore 组件权重、Entity Alias 表单和候选列表；Logo Upload 通过 `POST /v1/project-brand-kits/runtime/logo` 发送图片 raw body，先校验项目存在，再归档到对象存储，最后把 `s3://...` 写入 `project_brand_kits.logo_url` 并生成 `project_brand_logo_uploaded` 审计事件，审计 `input_refs/output_refs` 包含 filename、content type、content hash 和 logo URI；Score Weight Config 会写入 `score_weight_configs` 并生成 `score_weight_config_saved` 审计事件，后续 worker `--persist-analysis --score-formula-version ...` 会读取该配置并把本次使用的 `formula_version` 与 `component_weights_snapshot` 冻结到 `visibility_score_snapshots`；Human Review Trail 可对 score snapshot、content draft、answer analysis/run、score weight config 或 project 记录复核状态、decision、reviewer、notes 和 payload，写入 `human_review_records` 并生成 `human_review_recorded` 审计事件。Prompt Pack 面板展示 100 条 AU prompt 的总数、intent/city 覆盖和样本文本，提供 Prompt CSV Import 表单把 `text,intent_type,city,priority,intent_weight` 等字段导入为项目级 `PromptQuestion`，也提供 Prompt File Import 表单把 `.csv/.txt` UTF-8 文件或 `.xlsx` 第一工作表通过 raw-body endpoint 导入为同一套 `PromptQuestion` 和 `runtime_prompts_imported` 审计链路，并展示 Prompt Import History，按项目读回每次导入的 source format、filename、content type、hash、prompt count、method version 和审计事件，同时提供 Manual Backfill 表单，把人工答案、citation、截图/HTML URL 写成标准 `RawEvidenceRecord` 与 `manual_backfill_recorded` 审计事件；Collection Run Quality 面板展示最近批次的 planned/attempted/success/failure、success rate、trigger rate、answer rate、总成本、单次平均成本、总耗时、单次平均耗时、平台/access method 分布、失败摘要和 `collection_run_summarized` 审计事件数；Evidence Runs 面板展示每条 answer run 的 prompt、平台、城市、access method、触发状态、采样、collector、cost、duration、raw hash、citation、asset 和 audit；Score Contributions 面板展示 8 个评分组件的原始分、权重、加权贡献、分母、正负证据、confidence note、parser A/B agreement、冻结权重快照和关联 answer run，并能从组件跳到相关 answer run；Citation Graph & Competitors 面板展示 Citation Graph Map、source nodes、source gaps、graph evidence links 和竞品 benchmark，并能从 source node / graph link 跳到 answer run；Report Snapshot 面板提供 Markdown/CSV/PDF/White-label PDF 下载入口，并把当前 `platform/city/intent_type/sort` 传给 artifact API，白标 PDF 会优先使用当前项目 Brand Kit，响应头返回 `X-GENO-Report-Artifact-Hash`、`X-GENO-Report-Artifact-Filter-Hash`、`X-GENO-Report-Artifact-Template`、`X-GENO-Report-Artifact-Template-Hash`、`X-GENO-Report-Artifact-Sort`、row count 与 total count；Report History 面板按当前 runtime project 查询最近 5 个 `ReportExport`，逐条展示版本、导出时间、样本量、score snapshot 数、审计事件数、methodology hash、冻结对象存储 URL和继承当前筛选/排序的 Markdown/CSV/PDF/White-label PDF 下载入口；Report Method & Evidence Appendix 面板展示冻结 methodology hash、采样窗口、平台/access method/city 覆盖、双分母评分、平台权重、Method Disclosure（Google coverage/gate、limited coverage、API/browser fidelity、access/platform distribution）、API-vs-browser fidelity check 的 status、mismatch count、difference rate、payload hash、查询路径和 `api_browser_fidelity_checked` 审计事件，并展示最近已落库 check 的趋势方向、sampled/total、平均/峰值差异率、趋势窗口和趋势查询路径；Action Plan & Retest Detail 面板展示任务 owner/status/next check/source gap/evidence runs、T+0/7/14/30 复测计划、前后分数对比和 action/retest audit trail；Content Engine Detail 面板展示本地 facts、pgvector Knowledge Search、证据绑定草稿、target questions/evidence runs、source action、connector 计划、manual distribution records 与 content/embedding audit trail，知识检索使用 `/v1/knowledge-facts/runtime/search`，按 `project_id/query/market_code/city` 查询 `knowledge_fact_embeddings`，并展示 `fixture-knowledge-embedding-v1` 与 `knowledge_fact_embeddings_indexed`；Traceability Detail 面板展示 Traceability Map、报告到评分、证据、图谱、行动、内容、审计事件和 evidence links 的聚合链路；节点级 details 区可展开查看 score components、answer evidence、citation/asset nodes、actions/content drafts 和 audit event nodes，页面内锚点深链路会高亮被跳转节点。如果还没有数据，先运行 worker profile 写入一批 fixture runtime 数据。

运行时健康检查分两层：`/health` 只证明 API 进程可响应；`/ready` 会执行 PostgreSQL `SELECT 1`，DB 不可用时返回 503；`/v1/runtime-diagnostics` 返回 database/object_store/runtime_auth 三类诊断，包含连接池配置快照、对象存储配置完整性和 runtime auth/JWT/JWKS/OIDC discovery 配置状态。对象存储诊断默认只做配置检查，不主动访问 MinIO/S3，避免健康检查产生副作用：

```bash
curl http://localhost:8000/ready
curl http://localhost:8000/v1/runtime-diagnostics
```

运行时指标导出使用 Prometheus 文本格式 `/metrics`，当前覆盖 API 请求总量、按 route template 聚合的状态码、请求延迟 histogram，以及 runtime PostgreSQL connection pool 的 enabled/max size/timeout/created/available 快照；`/metrics` 自身不计入请求指标，避免抓取放大时序。API 还会为每个非 `/metrics` 请求回传 `X-GENO-Request-Id`，接受调用方传入的安全 request id，或自动生成 32 位 hex id，并向 `geno_api.access` logger 输出 `runtime_api_request` JSON access log，包含 request id、method、path、route、status、duration_ms 和 client_host；日志不写 query string，避免把筛选参数或潜在敏感上下文放进低层 access log。该端点与 access log 是 MVP 轻量可观测入口，不替代 Prometheus/Grafana/OpenTelemetry、集中式日志采集、慢查询追踪或告警订阅：

```bash
curl http://localhost:8000/metrics
```

可选 `observability` profile 会启动 Prometheus `http://localhost:9090` 和 Grafana `http://localhost:3001`，Prometheus 通过 `infra/prometheus/prometheus.yml` 抓取 `api:8000/metrics`，Grafana 通过 provisioning 自动配置 `GENO Prometheus` datasource。默认账号密码为 `admin/admin`，可用 `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` 覆盖：

```bash
docker compose -f infra/docker-compose.yml --profile observability up --build prometheus grafana
```

采集 worker 默认只输出 JSON；显式启用持久化时会先把 AU `ProjectBootstrap`、品牌/竞品和 100 条 `PromptQuestion` 写入 PostgreSQL，再把成功的 `RawEvidenceRecord`、失败的 `CollectionFailureRecord` 和本次批次级 `CollectionRunSummary` 写入 PostgreSQL。`CollectionCost.duration_ms` 会记录每条采集的 collector wall-clock 耗时；`CollectionRunSummary` 会记录 planned/attempted/success/failure、success rate、trigger rate、answer rate、总成本、单次平均成本、总耗时、单次平均耗时、平台/城市/access method 分布、失败原因分布和关联 `answer_run_ids`，并追加 `collection_run_summarized` 审计事件。`make worker-fixture-persist` 还会启用 `--persist-analysis`，继续写入分析、评分、图谱、报告、action/content/traceability，并在配置 `OBJECT_STORE_ENDPOINT` 时把 Markdown/CSV/PDF 报告 artifact 归档到 MinIO/S3-compatible bucket；若成功记录包含官方 API `geno-api-snapshot://...` HTML snapshot，也会在落库前归档到 `evidence/<project_id>/<answer_run_id>/<asset_id>.html`，用实际 `s3://...` 与 content hash 更新 `EvidenceAsset`，并追加 `api_snapshot_assets_archived` 审计事件：

```bash
DATABASE_URL=postgresql://geno_runtime_app:geno_runtime_app@localhost:5432/geno make worker-fixture-persist
```

worker 输出会包含 `p0a_readiness_gate`。默认 fixture slice 的 `--sample-size 1` 只用于 smoke test，会因 P0a k=3 要求 fail；`--mode fixture --prompt-limit 1 --sample-size 3` 会通过本地 gate。真实 `--mode api` 必须同样通过 required platforms、必备元数据、`answer_present/surface_triggered`、citation、screenshot/HTML 和 k=3 检查后，才可把该批次视为 design partner 试点证据；`--preflight-output-path` 可把同一份 worker JSON 落盘，`make api-preflight` 默认写到 `docs/runtime_preflight/api-preflight-latest.json`，即使 collector health 失败也会先写入失败原因。worker 同时输出 `preflight_summary`，把 `collector_health`、P0a gate、collection failure 和最终 exit code 折叠成稳定摘要，供自动化审计判断 `ready_for_design_partner` 与 `recommended_next_action`；`preflight_audit_checklist` 会进一步列出阻塞原因、证据字段引用、运行总量和可复跑 CLI 参数；`preflight_payload_hash` 会对剔除自身后的 canonical JSON payload 计算 sha256，便于复算 stdout、落盘文件和审计留档是否一致；`scripts/verify_preflight_payload.py` / `make verify-api-preflight` 提供独立复算入口，区分“可审计”和“可进入 design partner”；`scripts/build_preflight_manifest.py` / `make preflight-manifest` 会把 preflight 文件 hash、verifier 输出和关键 gate 摘要固化为可索引 manifest；`scripts/verify_au_p0a_runbook.py` / `make verify-au-p0a-runbook` 会校验真实批次命令计划本身没有漂移。采集执行可通过 `--collection-max-retries`、`--collection-retry-backoff-seconds` 和 `--collection-rate-limit-delay-seconds` 启用 worker 内重试/backoff/节流；默认不重试不等待，启用后每个计划样本仍只产出一个最终成功或失败记录，并在 collector log / audit event 中保留 `attempt_count`、`retry_errors` 和 `collection_execution_policy`。Perplexity/OpenAI 官方 API adapter 会把 API response 冻结成 `geno-api-snapshot://...` HTML snapshot asset，并把 snapshot hash 写入 `EvidenceAsset.content_hash`；`--persist` 且配置 `OBJECT_STORE_ENDPOINT` 时，worker 会在落库前把该 snapshot 归档为 `s3://...` EvidenceAsset 并写 `api_snapshot_assets_archived` 审计事件，未配置对象存储时则保留 `geno-api-snapshot://...` 可复盘引用。这是原始 API 响应证据，不等同于消费者界面截图，后者仍靠 browser fidelity 抽检披露。`--include-browser-fidelity-fixture` 会在 stable fixture 批次里额外加入同 prompt/city 的 `chatgpt_search.browser.fixture` 浏览器抽检样本，用于 `ApiBrowserFidelityCheck` 与 Report Method Disclosure；这些 browser fidelity samples 会保留为原始证据和审计输入，但通过 `score_input_policy.excluded_fidelity_sample_answer_run_ids` 排除出主评分分母。`make browser-fidelity-plan` / `--plan-browser-fidelity-sampling` 会按 run date/cadence/seed 从 100 条 prompt 和 AU 城市中确定性抽样，输出 `BrowserFidelitySamplingPlan`、`browser_fidelity_sampling_planned` 审计事件和可复跑的 `recommended_worker_args`；`scripts/run_browser_fidelity_scheduler.py` 与 Compose `scheduler` profile 会把“生成计划 -> 可选执行推荐 worker 参数”包成 cron/K8s CronJob 友好的 JSON wrapper，本地脚本默认只输出计划，Compose 默认持久化计划审计，只有设置 `GENO_BROWSER_FIDELITY_EXECUTE=1` 或传 `--execute` 才执行真实采集。真实浏览器抽检执行入口为 `--include-browser-fidelity-playwright` / `make api-browser-fidelity-preflight`：它在 `--mode api` 中额外选择 `chatgpt_search.browser.playwright`，要求 `GENO_BROWSER_COLLECTOR_ENABLED=1`、Playwright、prompt/answer selector、可选 storage state 与 artifact dir 就绪；未就绪时 `--require-ready-collectors` 会在采集前 exit 3 并输出 `not_configured`、`selector_missing`、`session_state_missing` 或 `playwright_missing`；health 通过后若浏览器启动、登录态、selector 交互或官方 API 调用失败，`--require-no-collection-failures` 会在输出 JSON 后 exit 5。成功 browser capture 会把 screenshot 与 HTML snapshot hash 写入标准 RawEvidence 链；配置 `GENO_BROWSER_ARTIFACT_DIR` 且 `OBJECT_STORE_ENDPOINT` 可用时，worker 会把本地 `file://` browser HTML/PNG 在落库前归档为 `s3://...` EvidenceAsset，并写 `browser_capture_assets_archived` 审计事件；未落本地文件的 `geno-browser-*://` 引用不会被伪装成 durable object。真实账号/selector 联调、分布式失败重试队列和 Temporal 深度编排仍待接。Google spike worker 会同时输出 `google_spike_gate` 与 `google_spike_readiness_gate`：前者检查 Google AIO 成功率，后者检查 browser / third_party_api / manual 中是否至少有两条采集路径；`--persist-analysis` 还会把 `score_input_policy` 写入评分审计和报告 Method Disclosure，只有两个 gate 同时通过时 Google answer runs 才能进入主评分分母。默认 browser-only fixture 会通过成功率 gate 但失败两路径 readiness gate，因此只进入 limited coverage 证据附录。

缺少 `DATABASE_URL` 时，`--persist` 会直接失败并提示配置缺失，避免误以为证据已经落库。若设置了 `OBJECT_STORE_ENDPOINT`，但 `OBJECT_STORE_ACCESS_KEY` / `OBJECT_STORE_SECRET_KEY` 或 bucket 配置错误，API snapshot 或报告 artifact 归档会失败并让 worker 退出，避免 `s3://...` URL 与真实对象不一致。

如需把同一批成功采集记录继续解析、评分，并保存 `AnswerAnalysis`、`VisibilityScoreSnapshot`、`ScoreContribution`、Citation Graph、ReportExport、ApiBrowserFidelityCheck、ActionRecommendation、RetestSchedule、RetestComparison、Knowledge Facts、KnowledgeFactEmbedding、Content Drafts、Integration Connectors、Manual Distribution Records 与 Traceability Bundle：`--persist-analysis` 会读取当前项目已确认的 `entity_aliases`、项目级 `score_weight_configs` 和 `--score-formula-version` 指定的 `SCORE_FORMULA_REGISTRY` 公式，让 `ComparativeAnswerParser` 以 `rule_based_v2_aliases` 作为主解析器、`llm_judge_fixture_v1` 作为本地 judge 对照，用品牌/竞品 alias、域名、产品名或母公司名参与品牌提及、推荐、排名和竞品识别，并通过 `FixtureLLMGateway` 生成可审计的 judge 调用日志；也可用 `--judge-gateway litellm --judge-model <model>` 切到 `LiteLLMGateway`，通过 `LITELLM_BASE_URL` / `LITELLM_API_KEY` 调用 OpenAI-compatible LiteLLM `/chat/completions`。`LiteLLMGateway` 的 chat 路径具备 bounded exponential backoff、重试次数/错误留痕和上游响应 cost 优先读取；失败调用同样保留 request/response hash、latency、attempts、retry errors 和 error message，并以 `llm_gateway_failed` uncertainty flag 降级继续解析。`parser_ab_compare_v1` 的 agreement、mismatch fields、judge result 与 `llm_call_log` 会写入 `answer_analyses.payload.parser_comparison`，同一调用日志同步 upsert 到 `llm_call_logs`，记录 purpose、provider、model、prompt_version、request/response hash、tokens、estimated cost、latency 和 status；评分会把本次使用的 `formula_version`、组件权重和 `score_input_policy` 写入评分审计与报告方法说明，`VisibilityScoreSnapshot.answer_run_ids` 只包含主评分允许的 answer runs，同一 `answer_run_id` 的分析重跑会更新 `answer_analyses` payload 与 parser 版本。核心包提供 `rescore_snapshot_with_formula()`，可用历史 `AnswerAnalysis` 和指定公式版本重放旧口径或候选口径，生成 `visibility_score_snapshot_rescored` 审计事件；批量重算 UI 和审批流仍待后续产品化。内容引擎保存时会把 `LocalizedKnowledgeFact` 的规范文本写入 8 维 deterministic fixture embedding，upsert 到 `knowledge_fact_embeddings`，并追加 `knowledge_fact_embeddings_indexed` 审计事件；运行时可通过 `/v1/knowledge-facts/runtime/search` 用 pgvector `<=>` 检索 AU facts，并在 AU facts 不足时保留 global fallback 标记。生成报告时会把 Google spike gate、limited coverage、`score_input_policy`、API-vs-browser fidelity、score rate denominators、access/platform distribution 和截图/HTML 覆盖率写入 `report_exports.method_disclosure` 冻结快照，同时把同批 `AnswerRun` 生成独立的 `api_browser_fidelity_checks` 运行时对象，冻结 status、official_api/browser 记录数、可比较 prompt-city 对、mismatch count、difference rate、payload hash 和 `api_browser_fidelity_checked` 审计事件；若启用 `--include-browser-fidelity-fixture`，报告分母和证据附录仍只使用 `score_input_records`，但 Method Disclosure 的 fidelity payload 使用全量 official_api + browser 抽检样本，因此可得到 `sampled` 且不会污染评分分母；未跑真实浏览器后端时该对象会如实显示 `not_run`。runtime Markdown/PDF artifact 与 Runtime Console 复用这些快照；未跑真实 Google 双 gate 时，Google 明确标注为 limited coverage，不进入主评分分母；Trigger Rate 使用本报告窗口全部 attempted evidence records 作分母，Mention/Recommendation Rate 使用 surface_triggered 子集作分母。

```bash
DATABASE_URL=postgresql://geno_runtime_app:geno_runtime_app@localhost:5432/geno \
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py --mode fixture --prompt-limit 1 --persist --persist-analysis
```

Docker worker profile：

```bash
docker compose -f infra/docker-compose.yml --profile worker run --rm collector-worker
docker compose -f infra/docker-compose.yml --profile e2e run --rm runtime-e2e
docker compose -f infra/docker-compose.yml --profile scheduler run --rm browser-fidelity-scheduler
OPENAI_API_KEY=... LITELLM_MASTER_KEY=... docker compose -f infra/docker-compose.yml --profile llm-gateway run --rm collector-worker-litellm
```

Runtime Console 默认读取最近 20 个 AU runtime project 作为项目下拉选项；如果 URL 带 `?project_id=...` 且该项目不在第一页，控制台会额外按 `project_id + market_code=AU` 读取一次选中项目，再用同一个 `project_id` 构造 prompts/evidence/export/alias/saved views/scores/graphs/reports/actions/content/traceability 查询路径。Saved Views 链接也会保留 `project_id`，避免跨客户或跨项目复盘时误读最新项目。

运行时证据查询 API：

```bash
curl -X POST "http://localhost:8000/v1/projects/runtime/au/dtc-ecommerce"
curl -X POST "http://localhost:8000/v1/projects/runtime/au/dtc-ecommerce" -H "content-type: application/json" -d '{"tenant_name":"Agency Client AU","project_name":"Koala Mattress GEO Pilot","target_brand":"Koala","category":"mattresses","competitors":["Emma Sleep","Sleeping Duck","Ecosa"],"brand_official_domains":["koala.com"],"brand_product_lines":["Mattress","Sofa Bed"],"owner_user_id":"agency-owner"}'
curl "http://localhost:8000/v1/projects/runtime?market_code=AU&limit=20"
curl "http://localhost:8000/v1/projects/runtime?project_id={project_id}&market_code=AU&limit=1"
curl "http://localhost:8000/v1/entity-aliases/runtime?project_id={project_id}&entity_kind=brand&limit=20"
curl "http://localhost:8000/v1/entity-aliases/runtime/candidates?project_id={project_id}&entity_kind=brand&limit=20"
curl -X POST "http://localhost:8000/v1/entity-aliases/runtime/confirm" -H "content-type: application/json" -d '{"entity_id":"{brand_or_competitor_entity_id}","entity_kind":"brand","alias":"ExampleBrand Australia","alias_type":"alias","confidence":1.0,"confirmed_by":"runtime-console","notes":"Runtime entity alias confirmation"}'
curl "http://localhost:8000/v1/prompts/runtime?project_id={project_id}&market_code=AU&intent_type=brand_awareness&limit=20"
curl -X POST "http://localhost:8000/v1/prompts/runtime/import.csv" -H "content-type: application/json" -d '{"project_id":"{project_id}","csv_content":"text,intent_type,city,priority,intent_weight\nIs ExampleBrand visible in Sydney AI recommendations?,brand_awareness,Sydney,1,0.9\nBest DTC ecommerce products for Melbourne shoppers,category_recommendation,Melbourne,2,1.0\n","imported_by":"runtime-console","max_rows":100}'
curl -X POST "http://localhost:8000/v1/prompts/runtime/import.file?project_id={project_id}&filename=prompts.xlsx&imported_by=runtime-console&max_rows=100" -H "content-type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" --data-binary @prompts.xlsx
curl "http://localhost:8000/v1/evidence-runs/runtime?project_id={project_id}&platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc&limit=20"
curl "http://localhost:8000/v1/collection-runs/runtime?project_id={project_id}&run_type=p0a_slice&limit=20"
curl "http://localhost:8000/v1/fidelity-checks/runtime?project_id={project_id}&status=not_run&limit=20"
curl "http://localhost:8000/v1/fidelity-checks/runtime/trend?project_id={project_id}&limit=20"
curl -X POST "http://localhost:8000/v1/fidelity-checks/runtime" -H "content-type: application/json" -d '{"project_id":"{project_id}","report_export_id":"{report_export_id}","checked_by":"runtime-console"}'
curl -X POST "http://localhost:8000/v1/evidence-runs/runtime/manual-backfill" -H "content-type: application/json" -d '{"prompt_question_id":"{prompt_question_id}","platform":"google","surface":"google_ai_mode","answer_text":"Manual Google AI Mode answer for audit backfill.","citation_urls":["https://examplebrand.example/au/manual-backfill"],"screenshot_url":"s3://manual-backfill/examplebrand-google-ai-mode.png","html_snapshot_url":"s3://manual-backfill/examplebrand-google-ai-mode.html","submitted_by":"runtime-console","notes":"Google spike manual backfill"}'
curl -D - "http://localhost:8000/v1/evidence-runs/runtime/export.csv?project_id={project_id}&platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc&limit=200"
curl "http://localhost:8000/v1/runtime-saved-views?project_id={project_id}&view_type=runtime_evidence&limit=20"
curl -X POST "http://localhost:8000/v1/project-brand-kits/runtime" -H "content-type: application/json" -d '{"project_id":"{project_id}","client_name":"Koala AU","prepared_by":"Partner Agency","logo_url":"https://koala.example/logo.png","primary_color":"#0f766e","secondary_color":"#111827","footer_text":"Prepared for Koala AU board review","updated_by":"runtime-console"}'
curl -X POST "http://localhost:8000/v1/project-brand-kits/runtime/logo?project_id={project_id}&filename=logo.png&uploaded_by=runtime-console" -H "content-type: image/png" --data-binary @logo.png
curl "http://localhost:8000/v1/project-brand-kits/runtime?project_id={project_id}"
curl "http://localhost:8000/v1/human-reviews/runtime?project_id={project_id}&target_type=content_draft&limit=20"
curl "http://localhost:8000/v1/human-reviews/runtime/queue?project_id={project_id}&queue_status=pending_review&limit=20"
curl -X POST "http://localhost:8000/v1/human-reviews/runtime" -H "content-type: application/json" -d '{"project_id":"{project_id}","target_type":"visibility_score_snapshot","target_id":"{score_snapshot_id}","review_status":"approved","decision":"approved_for_report","reviewer_id":"runtime-console","notes":"Reviewed score evidence and traceability bundle","payload":{"source":"runtime-console"}}'
curl "http://localhost:8000/v1/visibility-scores/runtime?project_id={project_id}&limit=20"
curl "http://localhost:8000/v1/citation-graphs/runtime?project_id={project_id}&limit=20"
curl "http://localhost:8000/v1/reports/runtime?project_id={project_id}&limit=20"
curl -D - "http://localhost:8000/v1/reports/runtime/{report_export_id}/artifact?type=markdown&platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc"
curl -D - "http://localhost:8000/v1/reports/runtime/{report_export_id}/artifact?type=csv&platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc"
curl -D - "http://localhost:8000/v1/reports/runtime/{report_export_id}/artifact?type=pdf&platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc"
curl -D - "http://localhost:8000/v1/reports/runtime/{report_export_id}/artifact?type=pdf&template=white_label&client_name=ExampleBrand%20AU&prepared_by=Partner%20Agency&platform=perplexity&sort=cost_desc"
curl -D - "http://localhost:8000/v1/reports/runtime/{report_export_id}/artifact?type=pdf&template=white_label&platform=perplexity&sort=cost_desc"
curl "http://localhost:8000/v1/score-formulas/runtime"
curl "http://localhost:8000/v1/action-plans/runtime?project_id={project_id}&limit=20"
curl "http://localhost:8000/v1/runtime-alerts?project_id={project_id}&limit=10"
curl "http://localhost:8000/v1/content-engines/runtime?project_id={project_id}&limit=20"
curl "http://localhost:8000/v1/knowledge-facts/runtime/search?project_id={project_id}&query=Australia%20shipping%20returns&market_code=AU&city=Sydney&limit=5"
curl "http://localhost:8000/v1/traceability/runtime?project_id={project_id}"
```

这些接口从 PostgreSQL 读取 `Project -> Tenant/Brand/Competitor/PromptQuestion/AuditEvent` 项目启动页、`ProjectBrandKit -> AuditEvent` 白标配置页、`HumanReviewRecord -> AuditEvent` 人工复核留痕页、`EntityAlias -> BrandEntity/CompetitorEntity -> AuditEvent` 别名确认页、`PromptQuestion` 分页、`AnswerRun -> PromptQuestion -> RawAnswer -> Citation/Asset/Log/Cost/Audit` 聚合页、`CollectionRunSummary -> AuditEvent` 批次级采集质量/成本/耗时摘要页、`ApiBrowserFidelityCheck -> AuditEvent` 保真度抽检页、`ApiBrowserFidelityCheck -> RuntimeFidelityTrend` 趋势读模型、`VisibilityScoreSnapshot -> ScoreContribution -> ScoreSnapshotRun -> AnswerRun/PromptQuestion -> AnswerAnalysis/AuditEvent` 评分解释页、`SourceGraph -> SourceGraphEvidence -> SourceGap -> CompetitorBenchmark` 图谱/竞品页、`ReportExport -> ReportEvidence -> ScoreSnapshot -> CitationGraph` 报告快照与历史列表、`RetestSchedule -> ActionRecommendation -> RetestComparison -> AnswerRun/PromptQuestion -> AuditEvent` 行动与复测页、`ContentDraft -> LocalizedKnowledgeFact -> ActionRecommendation -> AnswerRun/PromptQuestion -> ManualDistributionRecord/IntegrationConnector/AuditEvent` 内容引擎页、`LocalizedKnowledgeFact -> KnowledgeFactEmbedding -> AuditEvent` pgvector 知识检索页，以及 `TraceabilityBundle -> ReportExport -> VisibilityScoreSnapshot -> RuntimeEvidenceRun -> CitationGraph -> ActionRecommendation -> ContentDraft -> AuditEvent/EvidenceLink` 溯源详情页；未配置 `DATABASE_URL` 时返回 503。Citation Graph 的 `GraphStore` 可插拔验证已覆盖本地 PG adjacency projection 与 Neo4j node/relation projection，二者写入同一 `CitationGraphResult` 后通过统一 summary 查询得到一致 source nodes/evidence links/source gaps/competitor benchmark 口径；真实 Neo4j 服务联调仍待后续。知识检索的 `VectorStore` 可插拔验证已覆盖本地 pgvector projection 与 Qdrant projection，二者写入同一批 deterministic knowledge fact embeddings 后通过统一 search summary 得到一致 top-k id/score 排序；真实 Qdrant/Milvus 服务联调仍待后续。保真度抽检 API 可按 `project_id/report_export_id/status` 查询已冻结的 check，也可用 POST 对某个 report 或项目最新 report 重新生成 check；`GET /v1/fidelity-checks/runtime/trend` 会基于最近已落库 checks 返回 sampled/total、latest/earliest/average/max difference rate、趋势窗口和 `improving/worsening/flat/insufficient_sampled_data/no_data` 方向；当前差异率来自同批 prompt-city 的 `official_api` 与 `browser` answer run 对比，真实浏览器 collector 待接时会保持 `not_run` 或 `no_overlap`，不伪造 sampled。知识检索 API 会校验 `project_id/query`，用 `fixture-knowledge-embedding-v1` 生成查询向量，通过 `knowledge_fact_embeddings.embedding <=> query_vector` 排序，优先返回 `market_code=AU` 且匹配城市或全局城市的 active facts，再返回 global fallback，并读回 `knowledge_fact_embeddings_indexed` 审计事件；真实 embedding provider、Qdrant/Milvus 切换和内容生成时的在线 RAG 策略仍待后续产品化。实体别名候选是计算型 read model，不新增表，会从 canonical name、官方域名、产品线和母公司字段生成待确认项并排除已确认 alias；实体别名确认只接收已有 `BrandEntity` 或 `CompetitorEntity`，后端会使用稳定 alias id 幂等写入 `entity_aliases`，追加 `entity_alias_confirmed` 审计事件，并在后续 `--persist-analysis` 中参与 alias-aware parser 识别。Prompt CSV Import 和 Prompt File Import 会以稳定 prompt id upsert 到 `prompt_questions`，不删除已有 prompt，保存时追加 `runtime_prompts_imported` 审计事件；JSON CSV endpoint 接收 CSV 文本，raw-body 文件 endpoint 支持 `.csv/.txt` UTF-8 和 `.xlsx` 第一工作表，并在审计 `input_refs` 记录 `csv_sha256/source_format/source_filename/source_content_type`；`GET /v1/prompts/runtime/imports` 会从同一批 `AuditEvent` 读回项目级导入历史，不新增表，返回 source、hash、prompt count、method version 和审计行。项目级 Brand Kit 会写入 `project_brand_kits`，保存时追加 `project_brand_kit_saved` 审计事件；Logo Upload 会把图片上传到配置的 MinIO/S3-compatible bucket 后更新 `project_brand_kits.logo_url` 并追加 `project_brand_logo_uploaded` 审计事件，未配置对象存储或上传失败时返回 503 且不写假的 `s3://` 引用；白标 PDF 若未传 `client_name/prepared_by`，会读取当前 report 所属项目的 Brand Kit 作为默认客户名、服务商名、Logo URL、主题色和页脚。人工复核会追加写入 `human_review_records`，不覆盖原始 score/content/analysis 对象，审计事件为 `human_review_recorded`，用于记录 reviewer、review status、decision、notes 和被复核对象引用；复核队列会从 `visibility_score_snapshots` 与 `content_drafts` 聚合待审对象，返回 priority、reason、latest review 和 evidence refs；content draft 复核会把同项目草稿 `review_status` 投影为本次复核状态，并写入 `content_draft_review_status_updated`，但不改写评分、草稿正文或证据绑定；分配、通知、权限、复杂审批流和抽样校准仍待后续产品化。人工补录只接收已有 `PromptQuestion` 的答案证据，后端会用 prompt 元数据生成 `AnswerRun.access_method=manual`、`RawAnswer.raw_payload_hash`、citation/asset/cost/log 和 `manual_backfill_recorded` 审计事件。报告历史读取使用 `project_id` 约束当前项目；报告 artifact 的筛选下载只作用于即时渲染的 Markdown/CSV/PDF 证据附录，白标 PDF 使用 `template=white_label` 生成客户版标题页/执行摘要/页脚说明，并返回独立 `template_hash`；冻结 `ReportExport.answer_run_ids`、`score_snapshot_ids`、methodology hash、fidelity check payload hash 与对象存储 URL 不会被改写。

Runtime Alerts 是只读派生层，不新增事实表：后端用最新评分快照和贡献项判断品牌缺失、推荐率过低，用 answer analysis 的 `sentiment_score` 判断负面情绪风险，用 source gaps 输出信源缺口风险，用 competitor benchmarks 对比竞品提及率并识别竞品压制；每条 alert 都返回 `rule_version=runtime_alerts_v1`、`evidence_refs`、`related_actions` 和评分审计事件，便于从预警一路回查到分数、answer analysis、信源缺口、竞品 benchmark、answer run 和 action/retest 链路。

运行时项目访问控制默认关闭，便于本地 fixture 和 demo 无鉴权运行；设置 `GENO_RUNTIME_PROJECT_ACCESS_CONTROL=1` 后，主要 runtime API 需要可信 actor。默认 `GENO_RUNTIME_AUTH_MODE=header` 时仍读取请求头 `X-GENO-Actor-Id`；设置 `GENO_RUNTIME_AUTH_MODE=jwt` 后会要求 `Authorization: Bearer <JWT>`，用 `GENO_RUNTIME_JWT_SECRET` 校验 HS256；设置 `GENO_RUNTIME_AUTH_MODE=jwks` 后会要求 Bearer JWT，并优先用 `GENO_RUNTIME_JWKS_JSON` inline JWKS 校验 RS256，也可用 `GENO_RUNTIME_JWKS_URL` 拉取远端 JWKS，按 `GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS` 缓存，拉取超时由 `GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS` 控制；若未配置显式 JWKS URL，可通过 `GENO_RUNTIME_OIDC_DISCOVERY_URL` 或 URL-form `GENO_RUNTIME_JWT_ISSUER` 拉取 OIDC discovery document 并发现 `jwks_uri`，discovery document 按 `GENO_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS` 缓存。生产兜底默认关闭：只有显式设置 `GENO_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS` 或 `GENO_RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS` 为正数时，远端 refresh 失败才会在对应 stale 窗口内继续使用同 URL 的过期缓存。JWT/JWKS 模式共同支持 `GENO_RUNTIME_JWT_ACTOR_CLAIM`、`GENO_RUNTIME_JWT_ISSUER`、`GENO_RUNTIME_JWT_AUDIENCE` 和 `GENO_RUNTIME_JWT_CLOCK_SKEW_SECONDS`。`GET /v1/projects/runtime` 会把 actor 作为 `project_members.user_id` 过滤条件；`POST /v1/projects/runtime/au/dtc-ecommerce` 会把当前 actor 写为项目 owner/member；prompt、evidence、collection run、saved view、brand kit、score weight、human review、score、graph、report、fidelity、action、alert、content、knowledge search 和 traceability 等项目级接口会要求 `project_id` 并执行成员校验；`report_export_id` 或 entity id 入口会先反查所属项目后再校验。最小角色矩阵已接入 API 层：任意成员可读；owner/admin 可维护成员、导入 prompt、保存 saved view、修改 Brand Kit/Logo 和 Score Weights；owner/admin/analyst 可确认 entity alias、人工补录、记录 human review、创建 fidelity check；viewer 不允许执行写操作。拒绝语义为：缺 actor 或缺 Bearer token 返回 401，缺 JWT secret/JWKS JSON/JWKS URL/OIDC discovery source/不支持的 auth mode 返回 503，远端 JWKS/OIDC discovery 拉取失败或签名 key 配置坏返回 503，签名错误或 issuer/audience/时间窗不合法返回 401，开启访问控制后项目级接口缺 `project_id` 返回 400，actor 不是成员或角色不足返回 403，删除/降级最后一个 owner 返回 400，未配置持久化仍返回 503。`/v1/runtime-diagnostics` 只校验 JWKS JSON/URL/OIDC discovery URL/TTL/stale-if-error/timeout 配置形态，不主动访问远端 JWKS 或 OIDC discovery document，避免 readiness 产生外部网络副作用。数据库级最小隔离已接入 PostgreSQL RLS：迁移会创建 `geno_runtime_app` app role，Compose 的 API/worker/scheduler/e2e runtime 连接默认使用该 role；API 在校验 actor 成员关系后通过 `set_runtime_project_access_context()` 写入 `geno.runtime_project_access_control`、`geno.runtime_actor_id` 和 `geno.runtime_project_id` session GUC，让同一请求内的写后读路径在 commit 后仍受同一 RLS 上下文约束。API 连接池默认仅在常驻 API 服务启用，请求结束归还连接时会 rollback、清空上述 session GUC 并提交清理；worker、scheduler 和 runtime E2E 默认保持短生命周期直连。Keycloak/OIDC login/session、前端 SSO 登录流、邀请邮件、真实用户目录、跨租户管理员授权、完整权限后台和生产压测仍是下一阶段增强。

项目成员管理使用既有 `project_members` 表，不新增用户目录：`GET /v1/project-members/runtime?project_id=...` 读回成员和 `project_member_saved/project_member_deleted` 审计历史，`POST /v1/project-members/runtime` 按 `project_id + user_id` 幂等新增或更新 `owner/admin/analyst/viewer` 角色，`DELETE /v1/project-members/runtime` 按 `project_id + user_id` 删除成员；两类写操作都会记录 before/after hash、actor、reason 和 member id。开启访问控制时，成员列表允许项目内任意成员读取；成员 upsert/delete 只允许 owner/admin。repository 会阻止删除最后一个 owner，也阻止把最后一个 owner 降级成非 owner。邀请邮件、真实用户资料、成员邀请流和完整 IAM 仍待后续补齐。

## 核心文档

| 文档 | 内容 |
| --- | --- |
| [完整调研报告](docs/智推时代GENO项目完整调研报告.md) | 总报告，整合公司、行业、GENO 方法论、技术栈、案例、竞品、澳洲首发差异与落地路径 |

### 可审计调研复盘（7 份）

| 主题 | 文档 |
| --- | --- |
| 公司 | [智推时代公司](docs/智推时代公司-可审计调研复盘.md) |
| 用户搜索习惯变迁 | [全球互联网用户搜索习惯变迁](docs/全球互联网用户搜索习惯变迁-可审计调研复盘.md) |
| SEO → GEO 转变 | [SEO到GEO时代转变](docs/SEO到GEO时代转变-可审计调研复盘.md) |
| 搜索/AI 占比、内容与信源偏好 | [搜索引擎AI搜索占比内容偏好信源偏好](docs/搜索引擎AI搜索占比内容偏好信源偏好-可审计调研复盘.md) |
| GENO 四阶闭环技术栈与开源替代 | [智推时代GENO四阶闭环技术栈与开源替代](docs/智推时代GENO四阶闭环技术栈与开源替代-可审计调研复盘.md) |
| 合作案例核查 | [智推时代合作案例](docs/智推时代合作案例-可审计调研复盘.md) |
| 竞品格局 | [智推时代相似服务与竞争企业](docs/智推时代相似服务与竞争企业-可审计调研复盘.md) |

### GENO SaaS 产品落地（3 份）

| 文档 | 内容 |
| --- | --- |
| [MVP 技术设计文档](docs/GENO-SaaS-MVP-技术设计文档.md) | 通用 GENO SaaS 技术参考；已标注 AU 首发覆盖规则 |
| [MVP 一期需求拆解表](docs/GENO-SaaS-MVP-一期需求拆解表.md) | 通用 Epic/需求参考；AU 首发优先级以 P0a/P0b/P0c 覆盖 |
| [澳大利亚首发技术落地路径](docs/GENO-SaaS-AU-首发技术落地路径.md) | AU 首发规格真源：Evidence-first MVP、15 步实施方案与数据模型增量 |

## 证据目录 `research_sources/`

每个主题一个子目录，内含：编号化的逐来源摘要（`*.md`）、原始网页快照（`raw_pages/*.html`）、本地抽取（`local_extracts/`）、来源索引（`README.md`）。

| 子目录 | 编号 | 内容 |
| --- | --- | --- |
| `智推时代公司调研/` | C | 官网、融资聚合页、艾瑞 GEO 行业报告、媒体转载 |
| `全球互联网用户搜索习惯变迁/` | S | Gartner、World Bank、DataReportal、Pew、Google、OpenAI、StatCounter、SparkToro |
| `SEO到GEO时代转变/` | G | Google SEO/AI 官方文档、GEO 学术论文、零点击研究 |
| `搜索引擎AI搜索占比内容偏好信源偏好/` | H | 全球/中国/澳洲搜索与 AI 数据源 |
| `GENO四阶闭环技术栈开源替代/` | T | GENO 摘录 + 69 个开源技术资料 + 网页快照 |
| `智推时代合作案例调研/` | K | 合作案例 PDF 摘录、客户候选与媒体快照 |
| `智推时代相似服务竞品调研/` | V | 海外/国内竞品官网与文档快照、逐来源摘要 |

## 证据等级口径

| 等级 | 含义 |
| --- | --- |
| A | 客户/官方/权威原始资料，可直接核验 |
| B | 主流媒体、行业报告、工商/融资聚合页、第三方资料 |
| C | 公司官网、公司 PDF、企业访谈、营销稿（公司自述） |
| D | 无法访问、二级转述、身份不明或缺少原文（待补证据） |

## 核心判断（摘自总报告）

- **赛道逻辑成立**：搜索行为从"找链接"走向"看摘要、问 AI、追问验证来源"；GEO 是 SEO 在生成式答案环境中的上层扩展，而非替代。
- **智推时代产品叙事完整、公开技术证据不足**：能看到方法论、案例叙事与行业背书，未见公开 API、试用入口、评分公式、采样方法或第三方技术评测。
- **澳洲首发应做"证据型平台"**：先把 AU Market Profile → Prompt Pack → AI Answer Runner → Raw Evidence Store → Answer Parser → Citation Graph → Competitor Benchmark → Evidence Report 做扎实，再扩展内容生成、分发与集成。

> 产品第一原则：不要把 GEO 做成"黑箱投喂大模型"的服务，而要做成"可复盘的 AI 答案证据平台"——每个分数、建议和优化效果都能点回原始 prompt、平台、地区、时间、答案、引用 URL 和截图/快照。

---

生成日期：2026-06-08 起持续更新。本库不替代法律、财务或合同尽调，重点聚焦技术与产品可行性。
