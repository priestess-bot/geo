# GENO SaaS 澳大利亚首发 · 项目管理计划（PROJECT-PLAN）

本文件是**待办层**：把 `docs/` 里的规格拆成可追踪、可增量交付、可验收的里程碑与任务。规格变动时，改代码 + 改 `docs/` + 回写 `decisions/` ADR 在同一个 PR 内完成。

- 规格源（不动）：[docs/GENO-SaaS-AU-首发技术落地路径.md](docs/GENO-SaaS-AU-首发技术落地路径.md)、[docs/GENO-SaaS-MVP-一期需求拆解表.md](docs/GENO-SaaS-MVP-一期需求拆解表.md)、[docs/GENO-SaaS-MVP-技术设计文档.md](docs/GENO-SaaS-MVP-技术设计文档.md)
- 三层对应：`docs/`（规格）→ 本文件（待办）→ 代码（分模块）→ 分支/PR/验收（节奏）

## 0. 使用约定

**状态标记**：`[ ]` 待办 · `[~]` 进行中 · `[x]` 完成（用 issue 时以 issue 状态为准，本文件做总览）

**优先级**（沿用 AU 路径 §4 分层，覆盖需求表中偏国内口径）：

| 级别 | 含义 |
| --- | --- |
| P0a | 稳定证据链 MVP，缺则不能进入 design partner 试点 |
| P0b | Google AIO / AI Mode 高风险 spike，必须限时出结论但不阻塞 P0a |
| P0c | 客户可交付证据报告，组合 P0a 数据与 P0b 结论形成可售 MVP |
| P1 | 第二阶段，影响交付效率与客户体验 |
| P2 | 验证市场后再做（内容生成、集成、更广平台） |

**完成定义（DoD）**：每条验收勾选框来自 AU 路径 §9 与需求表各 Epic 的「验收标准」列。任务勾完 + 该里程碑 DoD 勾完 = 里程碑达成。

**任务来源标注**：`Step N` = AU 路径实施步骤；`§8.x` = AU 路径数据模型；`EN-xx` = MVP 需求表 Epic 条目。

### 0.1 范围对齐说明（重要，防止把旧流程带回来）

本计划以 **AU 首发技术路径**为准，对通用《MVP 一期需求拆解表》做三处覆盖：

1. **流程证据优先**：主线是「证据 → 信源图谱 → 竞品差距 → 行动 → 报告 → 复测 → 内容」，不是「配置 → 采集 → 评分 → 知识库 → 内容生成 → 分发」。
2. **平台换成澳洲**：P0a 稳定链路先做 `chatgpt`、`perplexity`；P0b 单独验证 `google_aio`、`google_ai_mode`；需求表中 DeepSeek/豆包/Kimi/元宝/文小言等国内平台**不在 AU 首发范围**。
3. **内容/知识库/分发降级**：需求表的 E6 知识库、E7 内容工作台、E8 分发在 AU 首发里整体降到 **P2（M7）**；P0a/P0b/P0c/P1 只做证据、评分、信源、竞品、报告、行动、复测。

确定性口径（与规格一致，不再浮动）：**1 个行业**首发、**100 条** prompt（上限 200）、P0a 稳定平台每条重复采样 **k=3**、Google spike **30 条 prompt / Australia + Sydney / k=2**、**3–5 个**竞品、默认评分公式 `au_visibility_v1`（8 项权重和 1.00，候选公式 `au_visibility_v1_1_local_boost` 通过 registry 管理）、平台权重 Google 45 / ChatGPT 30 / Perplexity 25。Google 权重最高，但进入全量评分必须先通过 P0b 健康闸门。

## 1. 里程碑总览

里程碑 = AU 路径 §7 的 8 个阶段。**平台评分权重与采集构建顺序是两回事**：权重 Google 最高，但构建先做 Perplexity + OpenAI 稳定证据链，Google AIO / AI Mode 当 P0b 独立 spike。

| 里程碑 | 阶段 | 覆盖 Epic | 出口标准（一句话） | P 级 | 状态 |
| --- | --- | --- | --- | --- | --- |
| **M0** | 接口契约与轻量开源底座 | E10（部分） | 核心依赖一键起，8 个接口有 stub，P0a/P0b/P0c 表可迁移，CI 绿 | P0a | `[~]` |
| **M1** | AU MarketProfile + 行业模板 + Prompt Pack | E1、E2 | 能建 market=AU 项目，配 1 行业 + 100 prompt + 3–5 竞品 | P0a | `[~]` |
| **M2a** | Stable AI Answer Runner + Raw Evidence Store | E3 | Perplexity + OpenAI 可采，证据全留，含触发状态、k=3、成本 | P0a | `[~]` |
| **M2b** | Google AIO / AI Mode Spike | E3 | Google 自建/第三方/人工路径限时对比，输出 pass/fail gate | P0b | `[~]` |
| **M3** | Answer Parser + AUVisibilityScore | E4 | 自动解析 + 可拆解可版本化评分 + 双分母 | P0a | `[~]` |
| **M4** | Citation Graph + Competitor Benchmark | E5 | 信源图谱 + source gap + 3–5 竞品对标 | P0c | `[~]` |
| **M5** | Evidence Report Export | E9（部分） | 导出含方法说明、Google spike 结论与证据附录的 PDF/CSV | P0c | `[~]` |
| **M6** | Action Plan + 复测 | E9（部分） | 缺口转任务 + T+7/14/30 复测前后对比 | P1 | `[~]` |
| **M7** | Knowledge Facts + Content Engine + Integrations | E6、E7、E8 | 本地事实库 + 证据驱动内容 + 集成 | P2 | `[~]` |

**P0a design partner 试点 = M0 + M1 + M2a + M3**。

**P0 可售 MVP = M0 + M1 + M2a + M2b + M3 + M4 + M5**，其中 M2b 若未过健康闸门，Google 数据只能进入 limited coverage 附录，不进入主评分分母。

## 2. 全局完成定义（通用 DoD）

每个任务合并前都要满足：

- `[~]` 代码有单测；关键路径有集成测试（fixture/API/core 已覆盖；真实外部采集 E2E 待接）
- `[~]` 通过 CI（lint + 测试 + 迁移可起）（本地 `make test` / `make docker-config` 通过；完整 lint/真实迁移起服待接）
- `[x]` 若改了行为/口径，同 PR 更新对应 `docs/`，必要时加 `decisions/` ADR
- `[~]` P0a/P0b/P0c 数据写入可追溯：能点回 `PromptQuestion -> AnswerRun` / `answer_run_ids`（runtime project create/read API、runtime project `project_id` 过滤、可配置 AU/DTC 客户项目创建、runtime prompt API、runtime prompt CSV import API、fixture TraceabilityBundle、worker `--persist` 写 AU 启动包/prompt 元数据、evidence 与 `CollectionRunSummary`，runtime project/prompt/evidence/collection run/manual backfill/entity alias API 已读回项目、竞品、prompt 计数、prompt 文本、prompt metadata、采集批次成功率/触发率、回答率、成本/耗时/失败摘要与别名确认审计；worker `--persist-analysis` 已读取确认后的 `entity_aliases`、项目级 `score_weight_configs` 和 `--score-formula-version`，并保存 alias-aware `AnswerAnalysis`、parser A/B comparison、公式版本化 `VisibilityScoreSnapshot` 与 TraceabilityBundle，runtime traceability API 可按 `project_id` 读回报告/评分/证据/图谱/action/content/audit/evidence link 聚合详情；Runtime Console 已展示 Project Bootstrap 客户配置表单、项目下拉、Entity Alias、Runtime Filters、Evidence Sort、Saved Views、筛选后 Evidence CSV 导出、筛选/排序后的报告 artifact 下载、Report History、Prompt Pack、Prompt CSV Import、Manual Backfill、Latest Evidence、Collection Run Quality、Evidence Runs 明细、Score Weights 公式目录/版本选择、Score Contributions 完整解释包、parser A/B agreement、Citation Graph & Competitors 明细、Citation Graph Map、Report Method & Evidence Appendix、Action Plan & Retest Detail、Content Engine Detail、Traceability Detail、Traceability Map、节点级 details 钻取和页面内锚点深链路；独立详情页与完整交互式图谱仍待接）
- `[~]` 关键动作写入 `AuditEvent`；关键输出能生成 provenance 链路和解释包（采集/采集批次摘要/评分/报告/action/content fixture、人工补录最小路径、实体别名确认最小路径与计算型 alias candidates 已落；批量实体消歧审核队列待接）
- `[~]` 有一次可演示（API fixture endpoints 与 Runtime Console MVP 已可演示；真实 design partner 数据演示待接）

**P0a 稳定链路验收门槛**（M0 + M1 + M2a + M3 全绿才算可进入 design partner 试点）：

- `[~]` 可创建 `market=AU` 项目，配 1 行业模板 + 100 条澳洲问题集 + 3–5 竞品（可配置客户项目 API/控制台已落；权限/RLS、真实客户数据验收待接）
- `[~]` 完成 Perplexity Sonar + OpenAI web search 两个平台采集，每条有 answer + citation + 截图/HTML（fixture k=3 可通过 `P0ACollectionReadinessGate`；真实 Perplexity/OpenAI API 凭证联调与官方 API 截图/HTML 补充策略待验证）
- `[~]` 每条采集记录 platform/surface/access_method/city/language/device/collected_at/collector_version/collector_backend_id（`P0ACollectionReadinessGate` 已自动检查必备元数据；真实外部批次待跑）
- `[~]` 每条采集记录 `answer_present`/`surface_triggered`；P0a 每 prompt 重复采样 k=3（worker 输出 readiness gate；默认 sample-size=1 会 fail，`--sample-size 3` fixture 会 pass；真实外部批次待跑）
- `[~]` 采集、采集批次摘要、解析、评分、人工补录、实体确认、报告导出均写入 `AuditEvent`（runtime `collection_run_summarized`、`manual_backfill_recorded` 与 `entity_alias_confirmed` 已落；真实外部解析/采集链路仍需凭证联调）
- `[~]` 每个 collector_backend 写入 CollectionCost；可估算 planned_runs、成功率、触发率、回答率、失败摘要、单位成本和平均耗时（真实外部采集凭证联调待接）
- `[~]` 自动解析品牌提及/推荐/排名/竞品/引用/本地相关性（rule parser、confirmed alias-aware parser、本地 judge fixture A/B、`LiteLLMGateway` adapter、`llm_call_logs` 调用日志与 `human_review_records` 复核留痕已落；真实 LiteLLM 服务联调、抽样复核队列和校准流程待接）
- `[x]` 生成可拆解、公式版本化的 `AUVisibilityScore`，能点回原始 answer run
- `[x]` 生成 `ScoreContribution` 分数解释包，展示子指标贡献、权重、分母、正负证据和局限
- `[x]` 报告区分 Trigger Rate 与 Mention/Recommendation Rate（`report_exports.method_disclosure.score_rate_denominators` 已冻结三类 rate 的 numerator/denominator/formula；Markdown/PDF/白标 artifact 与 Runtime Console 均展示 Trigger 使用 all attempted evidence records，Mention/Recommendation 使用 surface_triggered 子集）

**P0b Google spike 验收门槛**：

- `[ ]` 对 30 条高意图 prompt 跑 Google AIO / AI Mode，地理范围 Australia + Sydney，k=2
- `[~]` 至少对比自建浏览器、第三方 SERP API、人工补录中的两条路径（`GoogleSpikeReadinessGate` 已自动检查 access method 路径数；browser-only fixture 会 fail，browser+third_party fixture 可 pass；真实路径待跑）
- `[~]` 输出 pass/fail gate：成功率、触发率、失败原因、截图/HTML 证据、成本/耗时估算（`GoogleSpikeGateResult` + `GoogleSpikeReadinessGate` 已落；真实 spike 待跑）
- `[~]` 未通过健康闸门时，Google 只进入 limited coverage 附录，不进入主评分分母（`score_input_policy` 已在分析/评分层硬性排除未同时通过 `GoogleSpikeGateResult` 与 `GoogleSpikeReadinessGate` 的 Google answer runs，并写入评分审计与报告 Method Disclosure；真实 spike 待跑）

**P0c 可售报告验收门槛**：

- `[ ]` 生成 Citation Graph，识别 source gap，输出 3–5 竞品 Benchmark
- `[ ]` 导出含方法说明（含 API/消费者界面差异抽检结论、Google spike 结论、平台覆盖/降级口径）、审计摘要、分数解释包与原始证据附录的 PDF/CSV
- `[~]` 任意报告数值可沿 `ReportExport -> VisibilityScoreSnapshot -> ScoreContribution -> AnswerAnalysis -> PromptQuestion -> AnswerRun -> RawAnswer/AnswerCitation/EvidenceAsset -> SourceGraph/SourceGap/CompetitorBenchmark` 追溯（fixture TraceabilityBundle、prompt-linked runtime evidence API、runtime score API、runtime citation graph API、runtime report API、runtime report artifact API、runtime traceability detail API 与 Runtime Console Evidence Runs、Score Contributions、Citation Graph & Competitors、Citation Graph Map、Report History、Traceability Detail / Traceability Map / node drilldown / anchor deep links 已落；基础 PDF artifact、MinIO/S3-compatible artifact 归档、附录级筛选/排序 artifact 下载与最小白标 PDF 模板已落，独立详情页和完整交互式图谱待接）

**架构验收门槛**（开源·可插拔，搬自 AU 路径 §9）：

- `[x]` P0a 完成接口级可插拔：CollectorBackend、ParserEngine、ScoringFormula、ReportExporter 均有 stub 与至少一个工作实现（`NotConfigured*` stubs、fixture/规则/registry/Markdown-PDF-CSV 工作实现和 runtime-checkable Protocol 合约测试已落）
- `[~]` 向量库 pgvector ↔ Qdrant 切换后业务不变（pgvector runtime knowledge search 已落；Qdrant/Milvus adapter 切换回归待接，P0c/P1 前完成）
- `[ ]` 图库 PG 邻接表 ↔ Neo4j 切换后 citation graph 查询不变（P0c/P1 前完成，不阻塞 P0a）
- `[~]` LLM 供应商经 LiteLLM 切换，解析与生成不改（adapter、parser 注入、失败降级、retry/backoff 与响应 cost 读取已可测；真实 LiteLLM 服务编排和供应商联调仍待接）
- `[~]` 解析器规则实现与 LLM-as-judge 实现可对同一答案并行对比并保留版本（本地 judge fixture 已通过 `LLMGateway` 写入 `parser_comparison.llm_call_log` 与 `llm_call_logs`；LiteLLM adapter 已可注入同一路径；真实 LiteLLM 服务联调待接）
- `[x]` 评分公式可升级到新版本，历史分数仍可按旧版本重算（`SCORE_FORMULA_REGISTRY` 已管理 active/candidate 公式，`rescore_snapshot_with_formula()` 可用指定历史 `AnswerAnalysis` 重放，runtime API 暴露公式目录，worker 支持 `--score-formula-version`；批量重算 UI/审批流待接）

## 3. 里程碑与任务拆解

### M0 · Phase 0：接口契约与轻量开源底座（P0a）

> 出口标准：`docker-compose up` 起核心依赖；8 个接口有 stub + 类型；P0a/P0b/P0c 相关表可迁移可回滚；CI 绿。ClickHouse/Temporal/Langfuse/promptfoo/SearXNG 保留接口和接入点，不作为 P0a 阻塞项。

任务：

- `[x]` (P0a) 仓库骨架：`apps/`、`packages/`、`workers/`、`infra/`、`tests/`、`decisions/`
- `[x]` (P0a/P0b/P0c) 数据契约：优先实现 MarketProfile、IndustryProfile、PromptQuestion、GeoSample、AnswerRun、RawAnswer、AnswerCitation、AnswerAnalysis、SourceGraph、CompetitorBenchmark、VisibilityScoreSnapshot、BrandEntity/CompetitorEntity/EntityAlias、CollectionCost、AuditEvent、ReportExport、ScoreContribution、EvidenceLink、TraceabilityBundle 关联表；P1/P2 表可延后 — `§8`
- `[x]` (P0a) 接口契约 stub（先定义不实现）：CollectorBackend、LLMGateway、ParserEngine、VectorStore、GraphStore、GeoProvider、ScoringFormula、ReportExporter — `Step3.2`（P0a 四个关键工作流接口已用 runtime-checkable Protocol 对齐真实实现，并有 `NotConfigured*` stub + 至少一个工作实现的合约测试）
- `[~]` (P0a) `infra/docker-compose.yml` 核心底座：PostgreSQL+pgvector、MinIO、FastAPI、Next.js、LiteLLM、simple worker/cron — `§6`（已落 PostgreSQL+pgvector、MinIO、API、Web、repository 映射、`DATABASE_URL` connection factory、S3-compatible object store client、AU 启动包/prompt 元数据持久化、worker `--persist` / `--persist-analysis`、runtime project/prompt/evidence/collection run/evidence CSV export/saved views/score API、runtime citation graph API、runtime report API、runtime action plan API、runtime content engine API、runtime knowledge fact search API、runtime traceability API 与 Runtime Console Project Bootstrap/Runtime Filters/Prompt Pack/Collection Run Quality/Evidence Runs/Score Contributions/Citation Graph & Competitors/Citation Graph Map/Report Method & Evidence Appendix/Action Plan & Retest Detail/Content Engine Detail/pgvector Knowledge Search/Traceability Map/MVP；LiteLLM adapter、retry/backoff、响应 cost 读取、可选 `llm-gateway` Compose profile、`litellm` proxy config 和 `collector-worker-litellm` 已可测；连接池、独立详情页和完整交互式图谱待接）
- `[x]` (P0c/P1) 重组件接入点：ClickHouse、Temporal、Langfuse、promptfoo、SearXNG、Metabase 写 ADR 和接口适配计划，但不阻塞 P0a — `§6`
- `[~]` (P0a) 空 CI：lint + 测试 + 迁移起服（已落 contract tests、Compose config、repository mapping/runtime tests；lint 与真实迁移起服待补）
- `[~]` (P0a) LLM 网关配置 + 调用日志 + 对象存储配置 — `E10-01 / E10-03 / E10-05`（已落 LLMGateway 接口、`FixtureLLMGateway`、`LiteLLMGateway` HTTP adapter、`llm_call_logs` 运行时调用日志与对象存储配置；worker `--judge-gateway litellm` 可把 parser judge 切到 LiteLLM adapter；retry/backoff、失败调用审计、上游响应 cost 读取、LiteLLM Compose profile 和 env-secret config 已落；真实 provider key 联调、供应商账单 reconciliation 待接）

DoD：

- `[~]` 一键起核心依赖；P0a/P0b/P0c 相关表可建可回滚；8 接口 stub + CI 绿（本地配置、repository runtime mapping、AU 启动包持久化、prompt-linked runtime evidence、runtime collection run summary、runtime score/runtime citation graph/runtime report/runtime traceability read model 和 Docker 写库验证已完成；完整 CI 起服待补）
- `[x]` 三个可插拔点（向量库/图库/LLM）已留好接口，替换演示排入 P0c/P1
- `[x]` AuditEvent / ReportExport / ScoreContribution / EvidenceLink / TraceabilityBundle 相关表可建可回滚

### M1 · Phase 1：AU MarketProfile + 行业模板 + Prompt Pack（P0a）

> 出口标准：能创建 market=AU 项目，配 1 行业模板、100 条 AU prompt、3–5 竞品，且平台/城市/语言/货币/权重全部从 MarketProfile 读取。

任务：

- `[~]` (P0a) 租户/项目/品牌/竞品/角色权限 — `E1-01..05`（已落契约、启动包、PostgreSQL 幂等持久化、runtime AU/DTC 项目创建 API 与项目聚合读取 API；API/控制台已支持 tenant/project/brand/category/brand domains/product lines/3-5 competitors 客户配置创建，通用项目编辑/删除、RLS/鉴权待接）
- `[x]` (P0a) AU MarketProfile 固定值（locale/timezone/currency/cities/平台权重/信源分类）— `Step1`
- `[x]` (P0a) 1 个 IndustryProfile 行业模板 — `Step2`
- `[x]` (P0a) Prompt Pack：100 条 AU 英文问题集（上限 200），每条绑 intent_type/city/prompt_version，并可通过 runtime prompt API 分页/过滤读回 — `Step3 / E2-03..05`
- `[x]` (P0a/P0b) 平台字典（P0a：chatgpt/perplexity；P0b：google_aio/google_ai_mode）+ 平台权重 + build_stage — `E2-01..02`
- `[~]` (P1) 批量导入 prompt（CSV/XLSX）— `E2-06`（CSV 文本导入 API 与 Runtime Console 表单已落，写入 `runtime_prompts_imported`；XLSX 文件上传/解析待接）
- `[~]` (P1) 操作审计日志 — `E1-06`（启动包创建已生成 `project_bootstrap_created`；prompt CSV 导入已生成 `runtime_prompts_imported`；用户级 CRUD 审计待接）

DoD：

- `[~]` 可创建 market=AU 项目，配 3–5 竞品（启动包/API 已可生成，worker `--persist` 已可写入 tenant/project/brand/competitor/prompt；控制台客户配置创建流和 prompt CSV 导入已接入，完整 CRUD、权限和 XLSX 文件导入待接）
- `[x]` 可选 1 行业模板并生成 100 条澳洲问题集
- `[x]` 平台、城市、语言、货币、权重无写死，全部来自 MarketProfile

### M2a · Phase 2a：Stable AI Answer Runner + Raw Evidence Store（P0a，第一条垂直切片）

> 出口标准：Perplexity Sonar + OpenAI web search 均可采到 answer+citation+证据；每条记录触发状态、采集元数据、成本与 k=3；后续新增 Google 后端不改业务代码。

任务（构建顺序：稳定 API → 证据 → 成本 → 地理）：

- `[~]` (P0a) CollectorBackend 接口落地 + **Perplexity Sonar 后端**（最易采，先打通全链路）— `Step4`（fixture + 真实 API adapter shell 已落；真实凭证联调待验证）
- `[~]` (P0a) **OpenAI web search / ChatGPT Search** 官方 API 后端 — `Step4`（fixture + 真实 API adapter shell 已落；真实凭证联调待验证）
- `[x]` (P0a) Raw Evidence Store：AnswerRun/RawAnswer/AnswerCitation/EvidenceAsset/CollectorLog，含 `answer_present`/`surface_triggered`/`sample_index`/`sample_size`/`access_method`，并有 PostgreSQL repository 写入映射、JSONB/UUID runtime adapter、worker `--persist` 写库开关、AU 启动包/prompt 元数据先写入和 prompt-linked runtime evidence 查询 API — `Step5 / §8.5..8.7`
- `[~]` (P0a) Audit / Provenance 基础：采集开始/完成/失败、采集批次摘要、原始证据入库、人工补录和实体别名确认写 `AuditEvent`；`ReportEvidence` / `ScoreSnapshotRun` / `SourceGraphEvidence` 关联表先建表 — `Step5.1 / §8.16..8.19`（采集完成/失败审计、批次级 `collection_run_summarized`、人工补录最小路径 `manual_backfill_recorded` 与实体别名确认最小路径 `entity_alias_confirmed` 已落；批量消歧队列待接）
- `[x]` (P0a) P0a 采样量闸门：100 prompts × 2 platforms × 4 geo × k=3 = 2400 planned_runs，可配置降级 prompt/geo 但不降级证据字段 — `Step9.3`
- `[x]` (P0a) GeoProvider 抽象 + 城市采样（Australia/Sydney/Melbourne/Brisbane）— `Step6 / §8.4`
- `[x]` (P0a) 截图/HTML 快照 + `raw_payload_hash` — `E3-05`
- `[~]` (P0a) CollectionCost、CollectionRunSummary 与 P0ACollectionReadinessGate 记录（从首个采集器起），输出 planned/attempted/success/failure、成功率、触发率、回答率、失败摘要、单位成本、平均耗时和 P0a 采集门禁 pass/fail/reasons — `§8.15`
- `[~]` (P0c/P1) 保真度抽检：同批 prompt 跑 官方 API vs 浏览器 两后端，量化差异率并入报告 — `Step4`（`api_browser_fidelity_checks` 表、runtime GET/POST API、worker `--persist-analysis` 自动生成、报告 Method Disclosure 复用、Runtime Console 展示 status/mismatch/difference/payload hash 和 `api_browser_fidelity_checked` 审计事件已落；`--include-browser-fidelity-fixture` 已可生成同 prompt/city 的 official_api + browser fixture 配对样本并得到 `sampled`，browser fidelity samples 通过 `score_input_policy` 排除出主评分分母；真实 browser collector 后端和定期抽检调度待接）
- `[~]` (P1) 定时采集（Temporal）/复杂失败重试/限流/人工补录工作台 — `E3-03/06/07/08`（worker CLI 与 `--persist` 已落；Runtime Console 已有最小人工补录表单；复杂调度/限流/批量文件补录待接）

DoD：

- `[~]` Perplexity + OpenAI 两个平台均能采到 answer+citation+截图/HTML（fixture k=3 可由 `P0ACollectionReadinessGate` 验证通过；真实外部 API 待接，官方 API 截图/HTML 需浏览器抽检或 artifact 策略补足）
- `[x]` 每条记录平台/surface/access_method/city/language/device/时间/collector_version/collector_backend_id
- `[x]` 记录 answer_present/surface_triggered；P0a 每 prompt k=3
- `[~]` 采集事件、采集批次摘要、人工补录事件和实体别名确认事件写 AuditEvent；原始证据能通过 EvidenceLink 关联到后续报告和评分（采集完成/失败审计、`CollectionRunSummary` 与 `collection_run_summarized` 审计、人工补录写入 `AnswerRun/RawAnswer/AnswerCitation/EvidenceAsset/CollectorLog/CollectionCost/AuditEvent` 已落；实体别名确认写入 `EntityAlias/AuditEvent` 已落；confirmed alias 已进入 `rule_based_v2_aliases` parser 和 `AnswerAnalysis`；批量消歧队列待接）
- `[~]` 每个采集器写 CollectionCost，并有 CollectionRunSummary 估算单项目 2400 planned_runs 的成功率、触发率、回答率、失败摘要、总成本、单位成本、总耗时和平均耗时（真实外部采集凭证联调待接）
- `[x]` 采集后端可插拔：新增后端只实现 CollectorBackend，不改业务代码

### M2b · Phase 2b：Google AIO / AI Mode Spike（P0b，高风险限时）

> 出口标准：对 Google AIO / AI Mode 输出明确 pass/fail gate。通过后进入 P0c 主评分；未通过时只进入 limited coverage 附录，不阻塞 P0a 和 P0c 报告链。

任务：

- `[~]` (P0b·spike) `PlaywrightGoogleAIOCollector`：SERP 内嵌 AIO 采集，记录触发状态、截图/HTML、失败原因 — `Step4`（shell + fixture 已落；真实浏览器运行待接）
- `[~]` (P0b·spike) `PlaywrightAIModeCollector`：AI Mode 独立界面采集，记录账号状态、地理、设备、失败原因 — `Step4`（shell + fixture 已落；真实浏览器运行待接）
- `[~]` (P0b·spike) `ThirdPartySerpCollector`：至少接入一个第三方 SERP/AI-answer 供应商做对照 — `Step4`（shell + candidate 已落；供应商 API 待接）
- `[~]` (P0b·spike) `ManualBackfillCollector`：人工补录最小路径，保证样本可审计 — `Step4`（shell + candidate + runtime manual backfill API + 控制台最小表单已落；批量文件流待接）
- `[x]` (P0b·spike) Google spike 采样：30 prompts × 2 surfaces × 2 geo（Australia + Sydney）× k=2 = 240 planned_runs — `Step4 / Step9.3`
- `[x]` (P0b·spike) 失败分类：not_triggered / layout_changed / blocked / timeout / geo_mismatch / account_state — `Step4`
- `[~]` (P0b·spike) pass/fail gate 报告：成功率、触发率、截图/HTML 样本、成本/耗时、推荐路径 — `Step4 / Step13`（`GoogleSpikeGateResult` 与 `GoogleSpikeReadinessGate` 已落；browser-only fixture 会通过 AIO 成功率 gate 但 fail 两路径 readiness gate，真实 spike 报告待跑）

DoD：

- `[~]` 至少两条 Google 采集路径完成对照（自建浏览器、第三方 API、人工补录三选二）（readiness gate 已可执行；browser+third_party fixture 可 pass，真实路径待跑）
- `[x]` 每条结果可靠记录 surface_triggered / answer_present
- `[x]` 至少一个 google_aio 后端在同一窗口完成 >= 80% 计划样本，才允许进入主评分
- `[x]` 未达标时，Google 只进 limited coverage 附录，报告明确标注不进入主评分分母（评分层 `score_input_policy` 会把未同时通过成功率 gate 与两路径 readiness gate 的 Google run 排除出 `VisibilityScoreSnapshot.answer_run_ids`）

### M3 · Phase 3：Answer Parser + AUVisibilityScore（P0a）

> 出口标准：自动解析六要素 + 生成可拆解可版本化评分 + 双分母口径 + 能点回 AnswerRun。

任务：

- `[x]` (P0a) ParserEngine 接口 + 规则解析实现（brand/competitor/recommend/rank/sentiment/local_relevance/citations…）— `Step7 / E4-01..06`
- `[~]` (P0a) 实体/别名表 + 同名消歧人工确认 — `§8.14 / Step7`（实体契约、runtime entity alias confirm API、计算型 alias candidate API、控制台最小确认表单、候选确认按钮、`entity_alias_confirmed` 审计和 `rule_based_v2_aliases` parser 使用 confirmed aliases 已落；批量审核队列和证据驱动自动候选推荐待接）
- `[x]` (P0a) ScoringFormula 接口 + `SCORE_FORMULA_REGISTRY`：active `au_visibility_v1` 与 candidate `au_visibility_v1_1_local_boost`（8 项，权重和 1.00，版本化，可按旧版本重算）— `Step9 / E4-08`
- `[x]` (P0a) 双分母：Trigger Rate vs Mention/Recommendation Rate — `Step9.2`
- `[x]` (P0a) k 次聚合 + 均值/离散度；P0a k=3，Google spike k=2 且单独标注 — `Step9.3`
- `[x]` (P0a) VisibilityScoreSnapshot 聚合表（project/platform/city/intent/prompt），并支持 worker `--persist-analysis` 写库与 runtime score API 查询 — `§8.13`
- `[x]` (P0a) ScoreContribution 分数解释包：子指标贡献、权重、分母、正负证据、局限说明；runtime score API 可读回贡献项、关联 prompt/answer run/analysis/audit，Runtime Console 已展示完整评分解释包、parser A/B agreement 和权重快照 — `Step5.1 / §8.18`
- `[~]` (P1) LLM-as-judge 解析实现（与规则 A/B）— `Step7`（`llm_judge_fixture_v1` 本地 judge、`ComparativeAnswerParser`、`parser_ab_compare_v1` payload、`llm_judge_prompt_v1`、`llm_call_logs` 调用日志和 `LiteLLMGateway` adapter 已落；LiteLLM retry/backoff、响应 cost 读取和 `llm-gateway` Compose profile 已可测；真实 provider key 联调、供应商账单 reconciliation 和人工抽检待接）
- `[~]` (P1) 评分权重可配置 + 审计；人工复核留痕 — `E4-10/11`（项目级 `score_weight_configs`、runtime GET/POST API、`score_weight_config_saved` 审计、`/v1/score-formulas/runtime` 公式目录、Runtime Console 公式版本选择、worker `--persist-analysis --score-formula-version` 读取配置和 `VisibilityScoreSnapshot.component_weights_snapshot` 冻结已落；通用 `human_review_records`、runtime GET/POST API、`human_review_recorded` 审计和 Runtime Console Human Review Trail 已落；复核队列、审批流和抽样校准待接）

DoD：

- `[x]` 自动解析提及/推荐/排名/竞品/引用/本地相关性
- `[x]` 生成可拆解、公式版本化的 AUVisibilityScore，能点回 AnswerRun
- `[x]` 任意总分/平台分/城市分/intent 分都有 ScoreContribution 解释包
- `[x]` 报告能区分 Trigger Rate 与 Mention/Recommendation Rate
- `[x]` 评分公式可升级，历史分数按旧版本可重算
- `[~]` 规则解析与 judge 解析可对同一答案并行对比并保留版本（fixture judge + gateway 调用日志 + LiteLLM adapter + 人工复核记录已落；真实 LiteLLM 服务联调、抽样复核队列与解析器校准待接）

### M4 · Phase 4：Citation Graph + Competitor Benchmark（P0c）

> 出口标准：生成信源图谱与 source gap，输出 3–5 竞品对标，每个数字可追溯原始回答。

任务：

- `[x]` (P0c) GraphStore 接口 + PG 邻接表实现 + SourceGraph/SourceGap 表，并支持 runtime citation graph API 查询 — `Step8 / §8.9`
- `[x]` (P0c) Citation Graph 输出：常被引/竞品独占/过旧/本地缺失信源；worker `--persist-analysis` 已写入 source graph evidence 与 source gaps — `Step8`
- `[x]` (P0c) CompetitorBenchmark（3–5 竞品：mention/recommend/position/citation overlap/local relevance…），并支持 runtime citation graph API 读回 — `Step10 / §8.10`
- `[~]` (P0c) 监测看板：总览/平台对比/竞品对比/问题明细/风险 — `E5-01..05`（Runtime Console 已展示 Project Bootstrap、Runtime Filters、Prompt Pack、Evidence Runs 明细、Score Contributions 完整解释包、Citation Graph & Competitors 明细、Citation Graph Map、source gaps、actions、Content Engine Detail、Traceability Detail、Traceability Map、节点级 details 钻取和页面内锚点深链路；完整问题明细 UI 待接）
- `[~]` (P1) 看板筛选与导出 — `E5-06`（platform/evidence city/intent_type URL 查询筛选已接入 evidence runtime API 与控制台，prompt runtime API 同步按 intent_type 筛选；evidence 支持 `collected_at/cost/citation/audit` 受控排序；筛选后 evidence CSV 导出已落并带 hash/sort header；Runtime Saved Views 已可保存筛选、排序、query/export path 并写入审计事件；Report Snapshot 与 Report History 的 Markdown/CSV/PDF/White-label PDF artifact 下载已继承当前筛选/排序并返回 filter hash、template hash、sort、row/total count header；项目级 Brand Kit 白标默认值已接入，Logo 上传与高级主题编辑待接）
- `[ ]` (P1) GraphStore 切 Neo4j 验证可插拔 — `架构验收`

DoD：

- `[x]` 生成 Citation Graph，识别 source gap
- `[x]` 输出 3–5 竞品 Benchmark
- `[x]` 每个分数/引用可点回原始回答

### M5 · Phase 5：Evidence Report Export（P0c）

> 出口标准：导出客户可审计 PDF/CSV，含方法说明与原始证据附录，每个数字可追溯。

任务：

- `[~]` (P0c) ReportExporter 接口 + Markdown/CSV/PDF 导出（方法说明 + 证据附录）、runtime report API、Markdown/CSV/PDF artifact 下载、附录级筛选/排序下载、项目级 Brand Kit 默认值、白标 PDF 模板 renderer 与 MinIO/S3-compatible artifact 归档；品牌资产上传/高级主题编辑待接 — `Step13`
- `[x]` (P0c) ReportExport 快照：冻结 score_snapshot_ids、answer_run_ids、prompt_version、公式版本、平台权重、采样窗口；worker `--persist-analysis` 已写入不可覆盖版本，runtime report API 可读回 — `Step5.1 / §8.17`
- `[~]` (P0c) 报告展示：采集窗口/平台覆盖/access_method/样本量(k)/离散度/双分母/公式版本/API-界面差异抽检结论/Google spike pass/fail/limited coverage/审计摘要/分数解释包/非确定性说明 — `Step13`（Runtime Console 已展示 Report Snapshot、Report History 与 Report Method & Evidence Appendix：冻结 methodology hash、采样窗口、平台/access method/city 覆盖、样本量、双分母评分、离散度、公式版本、平台权重、Method Disclosure、证据附录、citation/audit 摘要、历史 report version/exported_at/object store URL/artifact path、白标 PDF template path 与项目级 Brand Kit 默认值；标准/运行时报告 artifact 已写入 Google gate/limited coverage/API-vs-browser fidelity/access distribution/score rate denominators 方法披露，`report_exports.method_disclosure` 已冻结同一快照供 runtime artifact/console 复用；核心方法/分数/证据/source gap/competitor/report snapshot、基础 PDF artifact 与项目级白标 PDF artifact 已落；真实 Google 运行结论和真实 API-vs-browser 抽检数据待接）
- `[~]` (P1) 代理商工作流：多客户/多项目/白标/导出历史 — `Step13`（当前已接入 Runtime Console 项目下拉/URL `project_id` 选择，并把 brand kit/prompt/evidence/export/alias/saved view/score/graph/report/action/content/traceability read path 收敛到选中项目；已接入客户项目创建表单、项目级 Brand Kit 表单、Report History/导出历史只读面板和 `template=white_label` PDF 下载，按 `project_id` 读取最近 5 个 `ReportExport` 并展示冻结 URL、artifact 下载、白标 artifact path 和报告审计摘要；品牌资产上传、高级主题编辑、导出历史管理、权限/账单隔离与客户级授权流转待接）

DoD：

- `[~]` 可导出含方法说明和证据附录的 Markdown/CSV/PDF，并通过 runtime report API 读取冻结快照和项目内报告历史、通过 artifact API 下载 Markdown/CSV/PDF/White-label PDF；artifact API 支持按当前 `project_id/platform/city/intent_type/status/sort` 即时过滤/排序证据附录并返回 hash、template hash 与 row count，不改写冻结报告；白标 PDF 可从项目级 Brand Kit 默认读取客户名、服务商名、Logo URL、主题色和页脚；worker 可把 Markdown/CSV/PDF 归档到 MinIO/S3-compatible bucket；Runtime Console 已展示项目级查询路径、Brand Kit 表单、报告方法说明、证据附录详情、Report History 和白标 PDF 下载；品牌资产上传/高级主题编辑待接
- `[x]` 报告每个数字可追溯 answer_run_ids、prompt metadata、score snapshot 和 citation graph
- `[x]` 报告导出写 AuditEvent；重复导出生成新 ReportExport 版本，不覆盖旧报告

### M6 · Phase 6：Action Plan + 复测（P1）

> 出口标准：缺口转可执行任务；按 T+7/14/30 复测并展示前后变化。

任务：

- `[x]` (P1) ActionRecommendation：缺口转任务，绑 evidence/source_gap/related_runs/owner/next_check — `Step11 / §8.11`
- `[~]` (P1) 复测调度 T0/T+7/T+14/T+30（Temporal 可重放，同 prompt_version、同 k）— `Step14`（同口径 RetestSchedule 已落，worker `--persist-analysis` 可写入并通过 runtime action plan API 读回；Runtime Console 已展示 Action Plan & Retest Detail，包括 offsets、scheduled dates、sample size 与 evidence answer runs；Temporal 可重放调度待接）
- `[x]` (P1) 前后窗口对比 + 趋势聚合，保留全部 raw runs；worker `--persist-analysis` 已保存 RetestComparison，runtime action plan API 可读回 comparison、prompt metadata 与 action/retest audit events，Runtime Console 已展示 baseline/retest score、score delta、trend 和 action/retest audit trail — `Step14`
- `[~]` (P1) 预警：负面/品牌缺失/竞品压制 — `E9-04/05/06`（source gap、低 mention rate、低 recommendation rate 已转 action；实时预警/竞品压制规则待接）

DoD：

- `[x]` 基于 source gap 生成 Action Plan
- `[x]` 任务有 owner/status/next_check_date
- `[~]` 按 T+7/14/30 复测，报告展示前后变化（runtime action plan API 已返回 RetestSchedule、RetestComparison、关联 AnswerRun/PromptQuestion 与 audit events；Runtime Console 已展示 Action Plan & Retest Detail；Temporal 调度、报告模板正式嵌入待接）

### M7 · Phase 7：Knowledge Facts + Content Engine + Integrations（P2）

> 出口标准：本地事实库可检索；内容生成绑证据并过审核；接入主要英语市场工具。

任务：

- `[~]` (P2) LocalizedKnowledgeFact 本地事实库 + VectorStore 检索（AU 优先，回退 global 标记）— `Step12 / §8.12 / E6`（内存检索 fixture 已落；worker `--persist-analysis` 已写入 PostgreSQL，保存内容引擎时同步 upsert `knowledge_fact_embeddings`，使用 `fixture-knowledge-embedding-v1` 写入 pgvector 并生成 `knowledge_fact_embeddings_indexed` 审计事件；runtime content engine API 可读回 facts，`/v1/knowledge-facts/runtime/search` 可按 project/query/market/city 做 pgvector `<=>` 检索并返回 AU/global fallback 标记，Runtime Console Content Engine Detail 已展示 pgvector Knowledge Search；真实 embedding provider、Qdrant/Milvus adapter 和在线内容 RAG 策略待接）
- `[~]` (P2) Content Engine：基于 source/prompt gap 生成 FAQ/comparison/schema/landing outline，绑 evidence 并过人工审核 — `Step15 / E7`（证据绑定草稿已落，worker 可持久化并通过 runtime content engine API 读回 draft -> fact/action/prompt/answer_run/manual distribution，Runtime Console 已展示草稿、target questions、evidence runs、source action 与人工分发记录；Human Review Trail 已可对 content draft 记录审核状态、decision 和审计事件；LLMGateway 真实生成、专用审核工作台和发布审批流待接）
- `[~]` (P2) Integrations：GSC/GA4/Shopify/WordPress/Webflow/HubSpot/Cloudflare — `Step15`（connector 计划对象已落，worker 可写入并通过 runtime content engine API 读回，Runtime Console 已展示 provider/status/auth/capabilities；真实 OAuth/API 接入待接）
- `[ ]` (P2) 更广平台：Gemini/Copilot/Claude/YouTube/Reddit/ProductReview — `§4.3`
- `[x]` (P2) Manual Distribution Record（仅记录 URL/状态，不自动发布）— `E8`

DoD：

- `[~]` 内容生成绑 evidence/source_gap/knowledge_fact，过人工审核（runtime content engine API 已读回 evidence/fact/action/prompt/manual distribution 关联，Runtime Console 已展示证据绑定细节，草稿默认 `pending_human_review`；Human Review Trail 已可记录 content draft 的人工审核留痕；专用审核工作台、状态回写和审批流待接）
- `[~]` 本地事实库可检索、可回退标记（内存检索和 global fallback 标记已落，facts 可持久化读回并在 Runtime Console 展示；pgvector runtime search、`knowledge_fact_embeddings` 和 `knowledge_fact_embeddings_indexed` 审计已落；真实 embedding provider、Qdrant/Milvus 切换和内容生成在线检索待接）

## 4. 风险登记册

源自《首发技术路径》复核，按"何时必须处理"排期，逐条给出口判据。

| 风险 | 何时处理 | 缓解动作 | 出口判据 |
| --- | --- | --- | --- |
| 采集保真度：API ≠ 消费者界面 | M2a 起，M5 披露 | 接口化采集；官方 API 默认交付，浏览器抽检放入 P0c/P1 | `api_browser_fidelity_checks` 已作为独立运行时对象落库，冻结 status、official_api/browser 记录数、comparable pairs、mismatch count、difference rate、payload hash 和 `api_browser_fidelity_checked` 审计事件；报告 Method Disclosure 与 Runtime Console 已展示该对象；`--include-browser-fidelity-fixture` 已可生成 paired fixture sampled 数据，且 browser fidelity samples 不进入主评分分母；真实浏览器后端和定期抽检调度待接 |
| Google AIO / AI Mode 选择性触发与采集脆弱 | M2b（spike） | 拆 AIO/AI Mode 两后端；建模 answer_present；自建/第三方/人工补录限时对比 | pass/fail gate、两路径 readiness gate、limited coverage 与 `score_input_policy` 已进入评分审计和报告 Method Disclosure；真实 Google gate 待跑 |
| AI 非确定性导致评分噪声 | M2a–M3 | P0a k=3；Google spike k=2 单独标注；报告展示离散度；parser A/B agreement 进入评分解释 | 同 prompt 多次采样 + 置信展示 + parser agreement |
| 架构可插拔是否为真 | M0 起持续 | 接口先行；P0a 先完成接口级可插拔，深度切换演示排到 P0c/P1 | P0a Collector/Parser/Scoring/Report 已有 runtime-checkable Protocol、`NotConfigured*` stubs 和工作实现合约测试；parser rule + judge fixture 已可并行；ScoringFormula registry、候选公式、旧版本重算和 worker 公式参数已落；pgvector runtime knowledge search 已落；LiteLLM adapter、parser 注入、retry/backoff、响应 cost 读取与可选 Compose profile 已可测；Qdrant/Milvus、图库和真实 LLM provider 联调待接 |
| 城市级地理定位实现成本 | M2a/M2b | GeoProvider 抽象（uule/代理池/供应商可换）；P0a 四地理样本可降级但保留字段 | 地理样本可区分且成本可控 |
| 单位经济不透明 | M2a 起 | CollectionCost 从首个采集器记录；CollectionRunSummary 汇总批次 planned/attempted/success/failure、触发率、回答率、失败摘要、总成本、单位成本、总耗时和平均耗时；P0a planned_runs 默认 2400，Google spike 默认 240 | 每份采集批次的成本、成功率、触发率、回答率、失败摘要、单位成本和平均耗时可估算；真实外部采集凭证联调待接 |
| 审计链/解释链断裂 | M0 起，M5/M6 验收 | AuditEvent、CollectionRunSummary、ReportExport、ScoreContribution、EvidenceLink 从 P0 建表并写入关键事件 | TraceabilityBundle fixture 已证明报告可追到原始证据；runtime project API 已支持 `project_id` 过滤；project brand kit API 已保存项目级白标默认值并写入 `project_brand_kit_saved` 审计事件；runtime prompt import API 已写入项目级 prompt 并生成 `runtime_prompts_imported` 审计事件；runtime evidence API 已读回 prompt 文本并支持 `project_id`、platform/evidence city/intent_type 过滤、受控排序和即时 CSV 导出；runtime collection run API 已读回采集批次 planned/attempted/success/failure、成功率、触发率、回答率、失败摘要、总成本、单位成本、总耗时、平均耗时和 `collection_run_summarized` 审计事件；runtime fidelity check API 已读回 `api_browser_fidelity_checks` 并生成 `api_browser_fidelity_checked` 审计事件；runtime manual backfill API 已把人工答案写入标准 RawEvidence 表并生成 `manual_backfill_recorded`；runtime entity alias API 已把品牌/竞品别名确认写入 `entity_aliases` 并生成 `entity_alias_confirmed`，runtime alias candidate API 已生成可确认候选，confirmed aliases 已进入 `rule_based_v2_aliases` parser 与重跑后的 `AnswerAnalysis`；runtime saved views API 已保存项目级筛选/排序/query/export path 并写入 `runtime_saved_view_saved` 审计事件；runtime score weight config API 已保存项目级评分权重并生成 `score_weight_config_saved`，评分历史快照冻结 `component_weights_snapshot`；runtime human reviews API 已追加 `human_review_records` 并生成 `human_review_recorded`；runtime score API 已读回评分解释包；runtime graph API 已读回 source gap/竞品对标；runtime report API 已读回报告快照和项目内报告历史，且 `report_exports.method_disclosure.score_rate_denominators` 冻结 Trigger/Mention/Recommendation 三类 rate 的分母口径；runtime report artifact API 已支持附录级筛选/排序与项目级白标 PDF 下载并返回 filter hash、template hash、sort、row/total count；runtime action plan API 已读回 action/retest audit events；runtime content engine API 已读回 fact/draft/connector/manual distribution/audit；runtime knowledge fact search API 已通过 `knowledge_fact_embeddings` 和 `knowledge_fact_embeddings_indexed` 读回 pgvector 检索结果与索引审计事件；runtime traceability API 已按 `project_id` 聚合报告/评分/证据/图谱/action/content/audit/evidence link；Runtime Console 已展示 Project Bootstrap、项目下拉、Brand Kit、Score Weights、Human Review Trail、Prompt CSV Import、Entity Alias Candidates、Runtime Filters、Evidence Sort、Saved Views、Manual Backfill、筛选后 Evidence CSV 导出、Collection Run Quality、API-browser Fidelity、筛选/排序后报告 artifact 下载、Report History、White-label PDF 下载、Evidence Runs 明细、Score Contributions 完整解释包、Citation Graph & Competitors 明细、Citation Graph Map、Report Method & Evidence Appendix、Action Plan & Retest Detail、Content Engine Detail、pgvector Knowledge Search、Traceability Detail、Traceability Map、节点级 details 钻取和页面内锚点深链路；独立详情页/完整交互式图谱、复核队列和审批流待接 |
| 打不过 Semrush/Ahrefs 数据规模 | 全程定位 | 押证据链/本地信源/代理商工作流，不拼分数广度 | design partner 认可证据价值 |
| 评分构念效度未验证 | M6 后 | 复测展示变化；拿到客户转化数据再做相关性 | 报告标注 MVP 阶段不声称强因果 |

## 5. 工作流与约定

### 5.1 分支与提交

- `main` 受保护；每个任务开短命 feature 分支 → PR → 合并（建议 squash）。
- 分支名：`m2a/perplexity-collector`、`m2b/google-aio-spike`、`m3/scoring-v1`。
- 提交/PR 关联 issue 号；PR 模板含「关联任务、DoD 勾选、是否回写 docs/ADR」。

### 5.2 issue 命名与标签体系（建议）

> 本地无远程时，用本文件的勾选框即可；推到 GitHub/GitLab 时按下表建 Milestone + Label。

- **Milestone**：`M0`、`M1`、`M2a`、`M2b`、`M3`…`M7`（对应本文件里程碑）
- **issue 标题**：`[M2a][collector] Perplexity Sonar 采集后端`
- **标签**：

| 维度 | 标签 |
| --- | --- |
| 优先级 | `P0a` `P0b` `P0c` `P1` `P2` |
| 类型 | `type:feature` `type:infra` `type:spike` `type:test` `type:docs` `type:bug` |
| 区域 | `area:collector` `area:evidence` `area:parser` `area:scoring` `area:citation` `area:benchmark` `area:report` `area:console` `area:platform` |
| 状态 | `status:blocked` `status:in-progress`（用看板列时可省） |
| 特殊 | `risk`（对应第 4 节）`good-first-slice`（垂直切片起步任务） |

### 5.3 ADR（架构决策记录）

- 位置：`decisions/NNNN-title.md`，每动一个可插拔点选型记一条（为什么 pgvector 起步、为什么 simple worker/cron 先于 Temporal、为什么 Perplexity 先建、Google spike 是否过闸）。
- 换实现时新开一条 ADR `supersede` 旧条。这是"文档保持活规格"的机制。

### 5.4 节奏

- **一周一个垂直切片 + 一次自演示**；P0a/P0b/P0c 阶段每周推进一个里程碑出口标准。
- **尽快锁定一个澳洲 design partner 品牌**：它的真实 prompt 既是验收场景，也是最好的测试数据。
- 每周回顾：勾选本文件进度，更新里程碑状态列。

## 6. 立即可做的下一步（建 issue 用）

1. `[M0][infra]` 仓库骨架 + 轻量 docker-compose 核心底座 + 空 CI（`risk`、`good-first-slice`）
2. `[M0][platform]` P0a/P0b/P0c 表迁移 + 8 个接口 stub
3. `[M1][platform]` MarketProfile=AU 固定配置 + 1 行业模板
4. `[M1][console]` 项目/品牌/竞品/prompt pack 最小后台
5. `[M2a][collector]` Perplexity Sonar 后端 + Raw Evidence Store（打通第一条垂直切片）
6. `[M2a][collector]` OpenAI web search 后端 + CollectionCost
7. `[M2b][collector]` Google AIO / AI Mode 采集 spike（限时，`risk`、`type:spike`）
8. `[M3][scoring]` ScoreContribution 分数解释包 + 报告追溯链

---

维护：本文件随里程碑推进更新状态列与勾选框；规格变更先改 `docs/` 再回链本文件。
