# 智推时代 GEO / GENO 调研与 SaaS 落地文档库

本仓库是围绕 **智推时代（GenOptima）** 及其 **GEO（Generative Engine Optimization，生成式引擎优化）** 业务的一次完整调研与产品落地规划。内容包括：公司与行业可审计调研复盘、GENO 方法论与技术栈拆解、竞品格局、合作案例核查，以及面向**澳大利亚首发**的 GENO SaaS MVP 技术设计与需求拆解。

本库已从文档与规划进入工程实现：除调研文档外，当前已包含 FastAPI API、Next.js Runtime Console、Python 核心契约、AU 项目启动包、DTC 电商行业模板、100 条 Prompt Pack、M2a evidence chain、M2b Google spike gate fixture、M3 rule parser + AUVisibilityScore、M4 Citation Graph + Competitor Benchmark、M5 Markdown/CSV/PDF Evidence Report Export 与 MinIO/S3-compatible artifact 归档、M6 Action Plan + Retest comparison、M7 Knowledge Facts + Content Draft + Integrations fixture、Traceability Bundle、PostgreSQL repository 映射、`DATABASE_URL` runtime connection、AU 项目启动包 runtime 创建/读取 API、AU 启动包/prompt 元数据持久化、worker `--persist` / `--persist-analysis` 写库开关、runtime project / prompt / evidence / manual backfill / entity alias confirmation / evidence CSV export / saved views / score / citation graph / report / report artifact / action plan / content engine / traceability 查询 API、Runtime Console Project Bootstrap / Entity Alias / Runtime Filters / Evidence Sort / Saved Views / Prompt Pack / Manual Backfill / Evidence Runs / Score Contributions / Citation Graph & Competitors / Report Method & Evidence Appendix / Action Plan & Retest Detail / Content Engine Detail / Traceability Detail 与节点级 details 钻取面板、SQL 迁移、Docker Compose、CI、ADR 与工程实施审计日志。报告 artifact 下载已可继承当前 Runtime Filters/Sort，只过滤导出的证据附录，不改写冻结 `ReportExport` 与评分快照。核心原则仍是**可审计**：每一个调研结论尽量回指原始来源（PDF、网页快照、行业报告），每一个工程输出逐步建立 `AuditEvent / EvidenceLink / ScoreContribution / ReportExport / ActionRecommendation / RetestComparison / ContentDraft / TraceabilityBundle` 溯源链。

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

```bash
make test
make docker-config
```

核心服务一键启动入口：

```bash
docker compose -f infra/docker-compose.yml up --build
```

默认地址：API `http://localhost:8000/health`，控制台 `http://localhost:3000`。控制台会读取 runtime project / prompt / evidence / entity alias / saved views / score / graph / report / report artifact / action / content / traceability API；Runtime Filters 支持通过 URL 查询参数按 `platform`、evidence `city`、`intent_type` 筛选 evidence，并用 `intent_type` 同步筛选 prompt 列表；Evidence Sort 支持 `collected_at_desc`、`collected_at_asc`、`cost_desc`、`cost_asc`、`citation_count_desc`、`audit_count_desc` 受控排序；Saved Views 可把当前筛选、排序、evidence query path 与 export path 保存到 PostgreSQL，并写入 `runtime_saved_view_saved` 审计事件；控制台同时展示实际 API 查询路径和筛选后 Evidence CSV 下载入口，CSV 响应含 `X-GENO-Evidence-Export-Hash` 与 `X-GENO-Evidence-Export-Sort`；Project Bootstrap 面板可创建并读回固定 AU/DTC design partner 启动包，并提供 Entity Alias 表单，把品牌/竞品别名、域名、产品名或母公司名写入 `entity_aliases` 并生成 `entity_alias_confirmed` 审计事件；Prompt Pack 面板展示 100 条 AU prompt 的总数、intent/city 覆盖和样本文本，并提供 Manual Backfill 表单，把人工答案、citation、截图/HTML URL 写成标准 `RawEvidenceRecord` 与 `manual_backfill_recorded` 审计事件；Evidence Runs 面板展示每条 answer run 的 prompt、平台、城市、access method、触发状态、采样、collector、cost、raw hash、citation、asset 和 audit；Score Contributions 面板展示 8 个评分组件的原始分、权重、加权贡献、分母、正负证据、confidence note 和关联 answer run；Citation Graph & Competitors 面板展示 source nodes、source gaps、graph evidence links 和竞品 benchmark；Report Snapshot 面板提供 Markdown/CSV/PDF 下载入口，并把当前 `platform/city/intent_type/sort` 传给 artifact API，响应头返回 `X-GENO-Report-Artifact-Hash`、`X-GENO-Report-Artifact-Filter-Hash`、`X-GENO-Report-Artifact-Sort`、row count 与 total count；Report Method & Evidence Appendix 面板展示冻结 methodology hash、采样窗口、平台/access method/city 覆盖、双分母评分、平台权重、报告证据附录、citation/audit 摘要；Action Plan & Retest Detail 面板展示任务 owner/status/next check/source gap/evidence runs、T+0/7/14/30 复测计划、前后分数对比和 action/retest audit trail；Content Engine Detail 面板展示本地 facts、证据绑定草稿、target questions/evidence runs、source action、connector 计划、manual distribution records 与 content audit trail；Traceability Detail 面板展示报告到评分、证据、图谱、行动、内容、审计事件和 evidence links 的聚合链路；节点级 details 区可展开查看 score components、answer evidence、citation/asset nodes、actions/content drafts 和 audit event nodes。如果还没有数据，先运行 worker profile 写入一批 fixture runtime 数据。

采集 worker 默认只输出 JSON；显式启用持久化时会先把 AU `ProjectBootstrap`、品牌/竞品和 100 条 `PromptQuestion` 写入 PostgreSQL，再把成功的 `RawEvidenceRecord` 和失败的 `CollectionFailureRecord` 写入 PostgreSQL。`make worker-fixture-persist` 还会启用 `--persist-analysis`，继续写入分析、评分、图谱、报告、action/content/traceability，并在配置 `OBJECT_STORE_ENDPOINT` 时把 Markdown/CSV/PDF 报告 artifact 归档到 MinIO/S3-compatible bucket：

```bash
DATABASE_URL=postgresql://geno:geno@localhost:5432/geno make worker-fixture-persist
```

缺少 `DATABASE_URL` 时，`--persist` 会直接失败并提示配置缺失，避免误以为证据已经落库。若设置了 `OBJECT_STORE_ENDPOINT`，但 `OBJECT_STORE_ACCESS_KEY` / `OBJECT_STORE_SECRET_KEY` 或 bucket 配置错误，报告 artifact 归档会失败并让 worker 退出，避免 `s3://...` URL 与真实对象不一致。

如需把同一批成功采集记录继续解析、评分，并保存 `AnswerAnalysis`、`VisibilityScoreSnapshot`、`ScoreContribution`、Citation Graph、ReportExport、ActionRecommendation、RetestSchedule、RetestComparison、Knowledge Facts、Content Drafts、Integration Connectors、Manual Distribution Records 与 Traceability Bundle：

```bash
DATABASE_URL=postgresql://geno:geno@localhost:5432/geno \
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py --mode fixture --prompt-limit 1 --persist --persist-analysis
```

Docker worker profile：

```bash
docker compose -f infra/docker-compose.yml --profile worker run --rm collector-worker
```

运行时证据查询 API：

```bash
curl -X POST "http://localhost:8000/v1/projects/runtime/au/dtc-ecommerce"
curl "http://localhost:8000/v1/projects/runtime?market_code=AU&limit=20"
curl "http://localhost:8000/v1/entity-aliases/runtime?entity_kind=brand&limit=20"
curl -X POST "http://localhost:8000/v1/entity-aliases/runtime/confirm" -H "content-type: application/json" -d '{"entity_id":"{brand_or_competitor_entity_id}","entity_kind":"brand","alias":"ExampleBrand Australia","alias_type":"alias","confidence":1.0,"confirmed_by":"runtime-console","notes":"Runtime entity alias confirmation"}'
curl "http://localhost:8000/v1/prompts/runtime?market_code=AU&intent_type=brand_awareness&limit=20"
curl "http://localhost:8000/v1/evidence-runs/runtime?platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc&limit=20"
curl -X POST "http://localhost:8000/v1/evidence-runs/runtime/manual-backfill" -H "content-type: application/json" -d '{"prompt_question_id":"{prompt_question_id}","platform":"google","surface":"google_ai_mode","answer_text":"Manual Google AI Mode answer for audit backfill.","citation_urls":["https://examplebrand.example/au/manual-backfill"],"screenshot_url":"s3://manual-backfill/examplebrand-google-ai-mode.png","html_snapshot_url":"s3://manual-backfill/examplebrand-google-ai-mode.html","submitted_by":"runtime-console","notes":"Google spike manual backfill"}'
curl -D - "http://localhost:8000/v1/evidence-runs/runtime/export.csv?platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc&limit=200"
curl "http://localhost:8000/v1/runtime-saved-views?view_type=runtime_evidence&limit=20"
curl "http://localhost:8000/v1/visibility-scores/runtime?limit=20"
curl "http://localhost:8000/v1/citation-graphs/runtime?limit=20"
curl "http://localhost:8000/v1/reports/runtime?limit=20"
curl -D - "http://localhost:8000/v1/reports/runtime/{report_export_id}/artifact?type=markdown&platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc"
curl -D - "http://localhost:8000/v1/reports/runtime/{report_export_id}/artifact?type=csv&platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc"
curl -D - "http://localhost:8000/v1/reports/runtime/{report_export_id}/artifact?type=pdf&platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc"
curl "http://localhost:8000/v1/action-plans/runtime?limit=20"
curl "http://localhost:8000/v1/content-engines/runtime?limit=20"
curl "http://localhost:8000/v1/traceability/runtime"
```

这些接口从 PostgreSQL 读取 `Project -> Tenant/Brand/Competitor/PromptQuestion/AuditEvent` 项目启动页、`EntityAlias -> BrandEntity/CompetitorEntity -> AuditEvent` 别名确认页、`PromptQuestion` 分页、`AnswerRun -> PromptQuestion -> RawAnswer -> Citation/Asset/Log/Cost/Audit` 聚合页、`VisibilityScoreSnapshot -> ScoreContribution -> ScoreSnapshotRun -> AnswerRun/PromptQuestion -> AnswerAnalysis/AuditEvent` 评分解释页、`SourceGraph -> SourceGraphEvidence -> SourceGap -> CompetitorBenchmark` 图谱/竞品页、`ReportExport -> ReportEvidence -> ScoreSnapshot -> CitationGraph` 报告快照页、`RetestSchedule -> ActionRecommendation -> RetestComparison -> AnswerRun/PromptQuestion -> AuditEvent` 行动与复测页、`ContentDraft -> LocalizedKnowledgeFact -> ActionRecommendation -> AnswerRun/PromptQuestion -> ManualDistributionRecord/IntegrationConnector/AuditEvent` 内容引擎页，以及 `TraceabilityBundle -> ReportExport -> VisibilityScoreSnapshot -> RuntimeEvidenceRun -> CitationGraph -> ActionRecommendation -> ContentDraft -> AuditEvent/EvidenceLink` 溯源详情页；未配置 `DATABASE_URL` 时返回 503。实体别名确认只接收已有 `BrandEntity` 或 `CompetitorEntity`，后端会使用稳定 alias id 幂等写入 `entity_aliases`，并追加 `entity_alias_confirmed` 审计事件。人工补录只接收已有 `PromptQuestion` 的答案证据，后端会用 prompt 元数据生成 `AnswerRun.access_method=manual`、`RawAnswer.raw_payload_hash`、citation/asset/cost/log 和 `manual_backfill_recorded` 审计事件。报告 artifact 的筛选下载只作用于即时渲染的 Markdown/CSV/PDF 证据附录，冻结 `ReportExport.answer_run_ids`、`score_snapshot_ids`、methodology hash 与对象存储 URL 不会被改写。

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
