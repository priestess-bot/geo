# GENO SaaS 澳大利亚首发技术落地路径

版本日期：2026-06-09

## 1. 核心判断

澳大利亚首发不复制完整 GENO 闭环，也不优先做内容生成、自动分发或多模态资产，而是先做一个 **Evidence-first AI Search Visibility MVP**：

> 先证明 AI 如何看见品牌、引用哪些来源、推荐哪些竞品、哪些澳洲本地信源缺失，再把证据转成可执行任务和复测报告。

原因：

- 澳大利亚是 Google 强势市场，Google Search / AI Overviews / AI Mode 必须优先监测。
- 澳大利亚客户更容易接受可审计报告、原始证据、引用来源和行动清单，不容易接受黑箱"投喂大模型"。
- Semrush、Ahrefs、HubSpot 等 SEO 工具会是强竞品，单纯做一个 AI visibility 分数不够，需要把 raw evidence、citation graph 和 agency report 做深。
- 一期最重要的是建立数据口径、采样方法和客户信任，而不是先追求自动化内容生产。

因此，澳洲首发主流程从原来的：

```text
项目配置 -> 问题集 -> AI回答采集 -> 可见性评分 -> 知识库 -> 内容生成审核 -> 分发记录 -> 报表预警
```

调整为：

```text
AU Market Profile
  -> ICP/行业 Prompt Pack
  -> AI Answer Runner
  -> Raw Evidence Store
  -> Answer Parser
  -> Citation Graph
  -> Visibility Score
  -> Competitor Benchmark
  -> Action Plan
  -> Evidence Report Export
  -> 7/14/30 天复测
  -> P2 Content Engine / Integrations
```

这不是放弃 GENO 闭环，而是把闭环拆成更容易落地和验收的顺序：

```text
证据 -> 信源图谱 -> 竞品差距 -> 行动建议 -> 报告 -> 复测 -> 内容和分发自动化
```

### 1.1 工程取向：三条架构硬约束

本次 MVP 在工程实现上明确三条硬约束，贯穿全文（详见第 3 章）：

1. **开源优先**：每一个能力优先采用成熟、可自托管的开源组件，避免一开始被单一商业 SaaS 或单一模型供应商锁定。
2. **模块化、松耦合**：采集、存储、解析、评分、信源图谱、报告各自是独立模块，模块之间只通过明确的接口契约和数据契约通信，不互相反向依赖内部实现。
3. **可插拔替换**：任一采集后端、向量库、图数据库、LLM 供应商、解析器、评分公式，都可以在不改动其他模块业务代码的前提下替换或并存。

### 1.2 两个必须正视的现实

- **采集是第一难题，不是附属字段。** 这类产品的真正壁垒在"能不能稳定、保真地把 AI 答案采到手"，而不在采到之后的解析和出图。两个具体问题必须在架构层解决：一是 **API 返回的答案不保证与真实用户在消费者界面看到的一致**（保真度缺口）；二是 **Google AI Overviews 是选择性触发的**，很多 prompt 根本不触发 AIO，"没触发"和"触发了但没提品牌"是两种完全不同的状态。这两点直接决定评分是否可信，必须在采集和数据模型里原生处理（见第 3、5、8 章）。
- **数据规模这一仗打不赢 Semrush/Ahrefs，护城河得换地方。** 它们已有亿级 prompt 库和澳洲区域数据，一个几百条 prompt 的 MVP 在"AI 可见性分数"广度上无法对抗。差异化必须押在它们做不深的地方：可点回原始回答的证据链、澳洲本地 citation graph 与信源图谱、代理商白标工作流、以及可解释可复盘的口径。这是产品定位，也是下面所有取舍的前提。

### 1.3 可行性修正：P0 分级交付，而不是一个大爆炸 P0

澳洲首发仍然把 Google AI Overviews / AI Mode 作为最高权重目标面，但工程上不能让 Google 采集阻塞整个 MVP。P0 拆成三层：

| 层级 | 目标 | 交付状态 | 失败时处理 |
| --- | --- | --- | --- |
| **P0a Stable Evidence Chain** | 先用稳定 API 平台跑通证据链：Perplexity Sonar、OpenAI web search、Raw Evidence Store、Parser、Score、基础报告 | 内部 demo / design partner 试点必须达成 | 无降级，未达成则不能进入客户试点 |
| **P0b Google High-risk Spike** | 独立验证 Google AIO / AI Mode 的浏览器采集、第三方 SERP 供应商、人工补录三条路径 | P0 高权重 spike，必须有结论 | 若未过健康闸门，Google 以抽样附录/第三方/人工补录交付，不阻塞 P0a/P0c |
| **P0c Customer Evidence Report** | 把 P0a 证据和 P0b 结论组合成可售报告：Citation Graph、Competitor Benchmark、PDF/CSV、方法说明 | 可售 MVP 必须达成 | Google 覆盖范围在方法说明里明确标注，不把未稳定的 Google 数据混入同一分母 |

因此，**平台权重、产品重要性、工程构建顺序是三件事**：

- 权重上：Google 仍然最高，决定报告解读和后续投入优先级。
- 构建上：先做 Perplexity / OpenAI API，保证证据链和报告链路可交付。
- 风险上：Google AIO / AI Mode 用限时 spike 和健康闸门管理，过闸后再进入全量 P0 评分。

## 2. 一期产品定位

一期产品定位为：

> 面向澳大利亚品牌和代理商的 AI Search Visibility & GEO Evidence Platform。

核心交付物不是"自动生成一堆内容"，而是一份可审计 AI 可见性报告：

- AI 是否提到品牌。
- AI 是否推荐品牌。
- 品牌在推荐列表中的位置。
- AI 是否引用品牌官网或澳洲本地信源。
- AI 引用了哪些竞品信源。
- 竞品在哪些 prompt/topic/source 上压制品牌。
- 品牌事实是否缺少澳洲本地化信息。
- 下一步需要修补哪些网页、FAQ、Schema、评价源、对比页、本地媒体或行业目录。
- 发布或修补后，7/14/30 天是否发生变化。

## 3. 架构原则与开源技术选型（模块化·松耦合·可插拔）

本章是本次 MVP 的工程主线。后面的 Step、数据模型、验收标准都以本章定义的接口和选型为准。

### 3.1 分层与模块边界

```text
控制台层      Next.js 控制台（项目/问题/证据/报告/任务）
应用服务层    FastAPI：项目编排、评分编排、报告编排、任务编排
能力模块层    Collector | EvidenceStore | Parser | CitationGraph
              | ScoringEngine | CompetitorBenchmark | ActionPlanner | ReportExporter
基础设施层    关系库 | 向量库 | 图库 | 指标库 | 对象存储 | 任务编排 | LLM 网关 | 观测评测
```

模块边界规则：

- 上层只依赖下层暴露的**接口**，不依赖其实现。例如评分引擎只读 `EvidenceStore` 的数据契约，不关心答案是 Playwright 采的还是官方 API 采的。
- 模块之间用**数据契约**（稳定的表结构/事件结构）通信，不共享内部对象。
- 采集层与主业务进程隔离（独立 worker），避免一个脆弱的浏览器自动化拖垮整个服务。

### 3.2 接口契约（必须先定义，再写实现）

采集后端统一接口，使任意平台/任意采集方式都能挂进来：

```text
CollectorBackend（接口）
  id() -> str                      # 如 google_aio.playwright / perplexity.sonar
  capabilities() -> {
    platform, surface,             # google_aio | google_ai_mode | chatgpt | perplexity ...
    supports_geo,                  # 是否支持城市级地理
    supports_citation,             # 是否返回引用链接
    access_method                  # browser | official_api | third_party_api | manual
  }
  collect(prompt, market, city, language, device) -> RawCollectResult
  health() -> status

RawCollectResult（数据契约）
  answer_present        # 关键：该界面/答案是否出现（AIO 是否触发）
  surface_triggered     # 目标生成式界面是否被触发
  answer_text
  citations[]           # url, domain, position
  screenshot, html_snapshot, raw_payload
  model_or_surface, account_state, collector_version
```

其他需要先定义接口、后填实现的可插拔点：

```text
LLMGateway       chat()/embed()，统一多模型，路由/重试/成本/日志；P0a 先用 FixtureLLMGateway 写 llm_call_logs，后续替换为 LiteLLM
ParserEngine     parse(RawAnswer) -> AnswerAnalysis（实现：规则 + LLM-as-judge，二者可切换/并存）
VectorStore      upsert()/search()（实现：pgvector / Qdrant / Milvus）
GraphStore       upsert_node()/query()（实现：Neo4j / Apache Jena / 纯 SQL 邻接表）
GeoProvider      resolve(city) -> 地理参数/出口（实现：uule 参数 / 代理池 / 第三方供应商，见 Step 6）
ScoringFormula   score(AnswerAnalysis, weights) -> 分数（公式版本化，可整体替换，见 Step 9）
ReportExporter   export(snapshot) -> PDF/CSV（实现：模板引擎 / Metabase 导出）
```

### 3.3 开源优先选型映射

| 能力 | 模块/接口 | 开源优先选型 | 可替换后端 |
| --- | --- | --- | --- |
| 控制台前端 | 控制台层 | Next.js | 任意 SPA 框架 |
| 应用服务/API | 应用服务层 | FastAPI + OpenAPI | NestJS |
| 主数据/多租户 | 关系库 | PostgreSQL（+ RLS） | 任意兼容 PG 的库 |
| 向量检索 | VectorStore | pgvector（起步，少引一个组件） | Qdrant、Milvus |
| 信源/知识图谱 | GraphStore | 起步用 PostgreSQL 邻接表 | Neo4j、Apache Jena、RDFLib |
| 指标事件 | 指标库 | ClickHouse | DuckDB（小规模）、PG 分区表 |
| 对象存储 | 对象存储 | MinIO（S3 兼容） | 任意 S3 兼容存储 |
| 网页/AI 界面采集 | CollectorBackend | Playwright、Crawlee、Scrapy | 第三方 SERP/AI-answer API |
| 传统结果基线 | CollectorBackend | SearXNG、SerpBear | 商业 SERP API |
| LLM 统一网关 | LLMGateway | LiteLLM | 直连各家 SDK |
| 自托管模型（降本期） | LLMGateway | vLLM / Ollama + Qwen/DeepSeek | 商业 API |
| RAG/编排 | Parser/Planner | LlamaIndex、LangChain | 自写最小编排 |
| NLP/实体/聚类 | ParserEngine | spaCy、Sentence-Transformers、BERTopic、KeyBERT | scikit-learn 流水线 |
| Prompt 追踪/评测 | 观测评测 | Langfuse、promptfoo、Ragas | OpenTelemetry + 自建评测集 |
| 任务编排/复测调度 | 任务编排 | Temporal、Airflow、n8n | Celery/RQ + cron |
| 看板/报表 | ReportExporter | Metabase、Grafana、Superset | 自写报表 + 模板 |
| 身份/多租户认证 | 基础设施 | Keycloak + PG RLS | 自建 JWT |
| 容器与部署 | 基础设施 | Docker Compose 起步 → K8s | 单机 systemd |

> 选型纪律：MVP 阶段能用一个组件覆盖就不引第二个（如向量先用 pgvector、图先用 PG 邻接表）；但**接口必须按"将来要换"来设计**，这样换 Qdrant、换 Neo4j、换第三方采集后端时只新增一个适配器实现，不动业务代码。许可证（如 MinIO AGPLv3、Redis/Valkey、n8n 商用条款）在选定时逐项核查。

### 3.4 必须可插拔的关键点清单

| 可插拔点 | 为什么必须能换 | 验收方式 |
| --- | --- | --- |
| 采集后端（每个平台） | 平台改版/失效时要能换实现或换供应商而不停服 | 同一平台至少跑通"开源自建"和"官方/第三方 API"两种后端 |
| 向量库 | 规模增长后可从 pgvector 迁 Qdrant/Milvus | 切换后端，检索结果一致性可回归 |
| 图库 | 关系复杂度上来后从 SQL 邻接表迁 Neo4j | 切换后端，citation graph 查询不变 |
| LLM 供应商/模型 | 成本/质量/可用性变化时切换 | 通过 LiteLLM 切换供应商，解析与生成不改 |
| 解析器实现 | 规则与 LLM 判定要能 A/B 和回退 | 同一答案两种解析器可对比，保留版本 |
| 评分公式 | 公式要随校准迭代且可复现历史 | 公式版本化，历史分数按旧版本可重算 |

## 4. MVP 范围分层

### 4.1 P0：必须做（分级交付）

| 层级 | 模块 | 目标 |
| --- | --- | --- |
| P0a | AU Market Profile | 固定澳大利亚市场配置、平台权重、语言、城市和信源分类 |
| P0a | Prompt Pack | 生成 100 条澳洲英文问题集（上限 200），覆盖品牌、品类、竞品、口碑、价格、本地服务 |
| P0a | AI Answer Runner（API-first） | 先跑通 Perplexity Sonar 与 OpenAI web search 两个稳定 API 后端，打通 answer/citation/evidence 全链路 |
| P0a | Raw Evidence Store | 保存 prompt、平台、城市、时间、原始回答、引用 URL、截图/HTML 快照、是否触发、采样序号 |
| P0a | Audit & Provenance Trail | 记录采集、解析、评分、人工修正、报告导出的审计事件；建立报告数值到原始证据的可追溯关系 |
| P0a | Answer Parser | 解析品牌提及、推荐、排名、竞品、引用、情绪和本地相关性 |
| P0a | Visibility Score | 计算可解释、公式版本化的 AU Visibility Score，支持拆分指标和双分母 |
| P0b | Google AIO / AI Mode Spike | 独立验证 Google AIO / AI Mode 的浏览器采集、第三方 SERP API、人工补录路径，并输出健康闸门结论 |
| P0c | Citation Graph | 统计 AI 引用源、竞品来源、source type、topic 和本地权重 |
| P0c | Competitor Benchmark | 对比 3-5 个竞品的提及、推荐、引用和 source overlap |
| P0c | Evidence Report Export | 输出客户可审计报告，支持 PDF/CSV，明确披露平台覆盖、采样量、Google spike 结果、降级口径和分数解释包 |

P0b 不是 P1，也不是可忽略功能。它是 P0 内的高风险技术验证，但其验收方式是"限时出结论 + 可降级交付"，不是"必须全量稳定后才能发布 P0a/P0c"。

### 4.2 P1：第二阶段做

| 模块 | 目标 |
| --- | --- |
| Action Plan | 把证据和信源缺口转成可执行任务 |
| Localized Knowledge Facts | 维护澳洲本地品牌事实、价格、配送、服务、城市覆盖和证据 URL |
| Agency Workflow | 多客户、多项目、白标报告、任务 owner 和复测窗口 |
| 7/14/30 天复测 | 发布前后窗口对比，展示指标变化和原始证据 |
| Manual Distribution Record | 只记录人工发布 URL 和状态，不做自动发布 |

### 4.3 P2：验证市场后再做

| 模块 | 目标 |
| --- | --- |
| Content Engine | 基于 prompt gap、source gap 和知识库事实生成 FAQ、comparison、schema、landing page outline |
| Integrations | GA4、Google Search Console、Shopify、WordPress、Webflow、HubSpot、Cloudflare |
| Broader Platform Coverage | Gemini、Bing Copilot、Claude、YouTube、Reddit、ProductReview 深度采集 |
| Workflow Automation | 自动创建 CMS 草稿、自动提醒、自动复测、API 输出 |
| Multi-market Expansion | 从 AU 扩展到 NZ、UK、US、SG 等英语市场 |

## 5. Step-by-step 实施方案

### Step 1：建立 AU Market Profile

新增 `MarketProfile = AU`，把澳洲市场配置从业务逻辑中抽离出来。

市场配置（固定值）：

```text
market: Australia
market_code: AU
locale: en-AU
timezone: Australia/Sydney
currency: AUD
primary_language: Australian English
cities: Australia, Sydney, Melbourne, Brisbane, Perth, Adelaide
```

P0 AI 平台配置：

```text
P0a stable:
  ChatGPT Search / browsing（OpenAI web search API）
  Perplexity（Sonar API）

P0b high-risk spike:
  Google AI Overviews
  Google AI Mode
```

说明：Google 仍然是澳洲报告中最高权重平台族，但采集实现先走独立 spike。`MarketProfile` 必须把 `platform_weight` 与 `build_stage` 分开存储，避免"权重最高"被误读成"第一个上线且必须全量稳定"。

P1/P2 平台扩展：

```text
Bing Copilot
Gemini
Claude
YouTube
Reddit
ProductReview
```

澳洲信源分类：

```text
official_site
google_business
review_site
reddit
youtube
local_media
industry_site
comparison_site
marketplace
government_or_regulator
association
```

技术要求：

- 平台、城市、语言、货币、采样权重、评分权重均从 `MarketProfile` 读取。
- 不把澳洲平台、城市或权重写死在采集、评分、报表代码里。
- 为后续 NZ、UK、US、SG 扩展保留同一配置模型。

### Step 2：确定 ICP 和首批行业模板

不要一开始泛化到所有行业。澳洲首发 P0 固定先做 1 个易验证行业（从下表 4 个候选中选定）。

优先行业判断：

| 行业 | 适合原因 |
| --- | --- |
| DTC / e-commerce | Shopify/WordPress 使用广，评价和 comparison 信源明显，复测周期较短 |
| 本地服务 | Google Business Profile、Google Reviews、城市维度强，容易展示 local relevance |
| B2B SaaS / agency 客户 | 能接受报告和数据产品，容易形成代理商工作流 |
| 教育培训 | prompt 明确、对比和口碑强，但转化归因较慢 |

每个行业建立独立 `IndustryProfile`：

```text
industry_code
default_prompt_templates
source_type_weights
competitor_fields
required_local_facts
report_template
```

### Step 3：生成澳洲 Prompt Pack

一期每个项目 P0 固定配置 100 条 prompt（上限 200），不做国内问题集直译。

问题类型：

```text
品牌认知类：Is [brand] good in Australia?
品类推荐类：Best [category] in Australia
城市场景类：Best [category] in Sydney / Melbourne
竞品对比类：[brand] vs [competitor]
购买决策类：Is [brand] worth it?
评价口碑类：[brand] reviews Australia
价格类：[product] price Australia
服务覆盖类：Does [brand] ship to Australia?
本地可信类：Is [brand] legit in Australia?
替代方案类：Alternatives to [competitor] in Australia
```

数据字段：

```text
question_id
project_id
market_code = AU
industry_code
text
intent_type
city
language = en-AU
target_brand
competitors
priority
intent_weight
prompt_version
status
```

Prompt Pack 生成原则：

- 每条 prompt 必须绑定 intent_type。
- 每个 intent_type 至少有品牌、品类、竞品和本地化变体。
- 城市类 prompt 不全量复制：P0 只覆盖 Sydney、Melbourne、Brisbane 三个城市，且只取品类推荐、竞品对比、购买决策三类高意图问题。
- prompt 版本必须保留，复测时使用同一版本。

### Step 4：开发 AI Answer Runner（可插拔采集后端）

采集层是本 MVP 的工程重心，按第 3 章的 `CollectorBackend` 接口实现，**每个平台、每种采集方式都是一个可热插拔的后端**，由 `MarketProfile` 的平台配置决定启用哪些。

P0 目标界面分为稳定链路与高风险 spike。注意：AI Overviews 与 AI Mode 是两个不同界面，拆成两个独立后端。

```text
P0a stable:
  chatgpt          ChatGPT Search / browsing（OpenAI web search API）
  perplexity       Perplexity（引用透明，官方 Sonar API 友好）

P0b high-risk spike:
  google_aio       Google AI Overviews（内嵌 SERP，可从 SERP HTML/截图解析）
  google_ai_mode   Google AI Mode（独立对话界面，交互式，触发和采集机制不同）
```

采集构建顺序（P0）：

```text
1. Perplexity Sonar：最稳定、引用透明，先打通证据链
2. OpenAI web search：补齐 ChatGPT Search / browsing 口径
3. Google AIO / AI Mode spike：限时验证自建浏览器、第三方 SERP、人工补录
4. 过健康闸门后，Google 数据进入全量评分；未过闸时仅进入抽样附录或单独 Google section
```

**为什么 Perplexity 进 P0、Copilot 暂列 P1 之首**：按澳洲 AI chatbot 份额，Copilot（约 11.6%）高于 Perplexity（约 5.4%），但 Perplexity 引用透明、有官方 API、对 citation graph 的信号价值最高，最契合"证据型平台"的 P0 目标；Copilot 份额有相当部分来自 Windows/Edge 默认分发，且基于 Bing 检索，可在 P1 用 Bing 通道补齐。这个取舍是有意为之，不是按份额排序。若客户行业的 Copilot 实际使用高，可在 `MarketProfile` 里把它提到 P0——平台是配置，不是写死。

每个平台至少提供两类可替换后端，避免单点失效：

```text
google_aio   ：PlaywrightGoogleAIOCollector（开源自建） | ThirdPartySerpCollector（第三方 SERP API）
google_ai_mode：PlaywrightAIModeCollector（开源自建） | ManualBackfillCollector（人工补录）
chatgpt      ：OpenAIWebSearchCollector（官方 API） | PlaywrightChatGPTCollector（浏览器）
perplexity   ：PerplexitySonarCollector（官方 API） | PlaywrightPerplexityCollector（浏览器）
baseline     ：SearxngBaselineCollector（开源 SearXNG，传统结果基线，辅助信源对照）
```

Google spike 健康闸门（P0b 必须输出结论）：

```text
spike_scope:
  prompts: 30 条高意图 prompt
  geo: Australia + Sydney
  sample_size: k=2
  surfaces: google_aio, google_ai_mode
  candidates:
    - browser: PlaywrightGoogleAIOCollector / PlaywrightAIModeCollector
    - third_party_api: ThirdPartySerpCollector
    - manual: ManualBackfillCollector

pass_gate:
  - 至少一个 google_aio 后端可在同一窗口完成 >= 80% 计划样本
  - 每条结果能可靠记录 surface_triggered / answer_present
  - 有截图或 HTML 快照作为证据
  - 失败原因可分类：not_triggered / layout_changed / blocked / timeout / geo_mismatch / account_state
  - 单项目 Google 采集成本、耗时和失败率可估算

fail_gate:
  - 若未达到 pass_gate，Google 不进入 P0a 主评分分母
  - 报告保留 Google spike 附录：触发率、样本截图、失败原因、下一步方案
  - 客户交付主报告使用 Perplexity + OpenAI 稳定链路，Google section 明确标注为 limited coverage
```

两个采集保真度问题必须在后端处理：

- **API ≠ 消费者界面**：官方 API（如 ChatGPT web search、Perplexity Sonar）便于稳定采集，但其答案组装、模型版本、引用与个性化不保证与消费者界面一致。默认走 API 是"用稳定性换保真度"的有意取舍，必须配一个**抽检环节**：定期对同一批 prompt 用官方 API 后端与浏览器后端各采一次，量化差异率并在报告方法说明里披露。`access_method` 字段全程记录，便于区分。
- **AIO 选择性触发**：Google AI Overviews 不是每个 query 都出现。后端必须如实返回 `answer_present / surface_triggered`，把"AIO 没触发"与"触发了但没提品牌"区分开（影响 Step 9 的分母口径）。

采集服务要求：

- 与主业务服务隔离，作为独立 worker 运行。
- 支持失败重试、平台级限流、`collector_version`、手动补录。
- 支持截图和 HTML 快照留存、`raw_payload_hash` 完整性校验。
- 记录账号状态、地区、设备、采集方式（`access_method`）。
- 同一 prompt 的多次重复采样用 `sample_index` 区分（见 Step 9 非确定性处理）。

### Step 5：建立 Raw Evidence Store

这是澳洲首发 MVP 的核心，不是附属字段。

每次采集必须保存：

```text
prompt
prompt_version
answer
answer_present        # 该生成式界面/答案是否出现（AIO 是否触发）
surface_triggered     # 目标界面是否被触发
platform
surface               # aio / ai_mode / search / browsing
access_method         # browser / official_api / third_party_api / manual
market_code
city
language
device
model_or_surface
citations
screenshot_url
html_snapshot_url
account_state
collector_version
sample_index          # 同一 prompt 第几次重复采样
collected_at
raw_payload_hash
```

数据模型：

```text
AnswerRun
RawAnswer
AnswerCitation
EvidenceAsset
CollectorLog
```

证据留存规则：

- 每一个 score 都必须能追溯到 `AnswerRun`。
- 每一个 citation 都必须能追溯到原始回答。
- 每一次报告导出都记录所用 answer_run_ids。
- 同一 prompt 的复测和重复采样必须保留历史版本，不能覆盖。

### Step 5.1：建立 Audit / Provenance / Explanation 机制

当前的 Raw Evidence Store 已经能保存原始回答和采集元数据，但还不够。P0 必须把"可审计、可溯源、可解释"作为独立能力实现，避免报告只是展示结论、无法复盘计算过程。

三类能力边界：

```text
Audit Trail        记录谁/哪个系统在何时做了什么，输入输出是什么版本
Provenance Trail   记录每个报告数值、图表、建议来自哪些 answer_run / citation / analysis
Explanation Bundle 记录分数为什么这样算：子指标、权重、分母、证据、局限和置信度
```

P0 审计事件必须覆盖：

```text
project_created
market_profile_changed
prompt_pack_generated
prompt_pack_modified
collector_run_started
collector_run_completed
collector_run_failed
manual_backfill_created
raw_evidence_stored
parser_run_completed
score_snapshot_created
source_graph_updated
competitor_benchmark_created
report_exported
score_formula_changed
entity_alias_confirmed
```

审计事件字段：

```text
event_id
event_type
project_id
actor_type          # user / system / worker / api
actor_id
target_type         # project / prompt / answer_run / score_snapshot / report
target_id
before_hash
after_hash
input_refs          # prompt_question_ids / answer_run_ids / source_ids
output_refs         # analysis_ids / score_snapshot_ids / report_export_id
method_version      # collector_version / parser_version / scoring_formula_version
created_at
```

可溯源链路要求：

```text
ReportExport
  -> VisibilityScoreSnapshot
  -> AnswerAnalysis
  -> AnswerRun
  -> RawAnswer / AnswerCitation / EvidenceAsset

SourceGap / ActionRecommendation
  -> SourceGraph
  -> AnswerCitation
  -> AnswerRun
```

实现规则：

- `ReportExport` 必须冻结 `score_snapshot_ids`、`answer_run_ids`、`prompt_version`、`scoring_formula_version`、`platform_weights_snapshot`、`sample_size`、`window_start/window_end`，导出后不允许重写，只能重新生成新版本。
- `VisibilityScoreSnapshot.answer_run_ids` 在 P0 可先用数组保存，但必须同时预留 `ScoreSnapshotRun` 关联表，避免后续大样本查询困难。
- `SourceGraph.answer_run_ids` 在 P0 可先用数组保存，但必须同时预留 `SourceGraphEvidence` 关联表，用于追踪某个 source gap 来自哪些引用。
- `raw_payload_hash`、`html_snapshot_url`、`screenshot_url` 不可覆盖；同一采集重跑必须生成新的 `AnswerRun`。
- 人工补录、实体别名确认、评分权重修改都必须写 `AuditEvent`，并在报告方法说明中披露是否存在人工介入。

分数解释包（Explanation Bundle）：

```text
score_snapshot_id
scope_type / scope_value
final_score
formula_version
platform_weights_snapshot
component_contributions:
  - component_name
  - component_score
  - weight
  - weighted_contribution
  - denominator
  - evidence_answer_run_ids
  - explanation_text
uncertainty:
  - sample_size
  - stddev
  - confidence_note
limitations:
  - API != consumer UI
  - Google limited coverage / not triggered
  - AI answer non-determinism
```

验收口径：

- 任意报告总分、平台分、城市分、intent 分都能点开解释包。
- 解释包能列出贡献最大的 3 个正向证据、3 个负向/缺口证据和对应原始回答。
- 任意人工修改都能在 `AuditEvent` 中看到 actor、时间、前后 hash、原因或备注。
- 重新导出同一报告不会覆盖旧版本；两次报告的差异能通过 `ReportExport` 和 `AuditEvent` 复盘。

### Step 6：做地理采样机制（GeoProvider 抽象）

澳洲结果需要区分全国表现和城市表现。城市级地理定位的实现方式需保持可替换，因此抽象成可插拔的 `GeoProvider`：

```text
GeoProvider（接口）
  resolve(city) -> {geo_params, egress}   # 给采集后端注入地理信号
实现可选：
  UuleGeoProvider          # 通过 Google uule / near 等地理参数
  ProxyPoolGeoProvider     # 通过城市出口的代理池
  VendorGeoProvider        # 通过第三方供应商的地理定位能力
```

采集后端通过 `GeoProvider` 拿到地理信号，本身不关心地理是怎么实现的。这样从"参数注入"换到"代理池"再换到"供应商"，采集逻辑不动。

P0 地理范围：

```text
Australia
Sydney
Melbourne
Brisbane
```

P1 扩展：

```text
Perth
Adelaide
```

`GeoSample` 配置：

```text
market_code = AU
country = AU
city
language = en-AU
device = desktop/mobile
geo_provider          # 使用哪个 GeoProvider 实现
sampling_weight
status
```

评分和报告需要支持：

- 全国总览。
- 城市对比。
- 城市问题明细。
- 城市级竞品压制。
- 本地相关性不足提示。

### Step 7：改造澳洲答案解析器（可切换实现）

`ParserEngine` 按接口实现，规则解析与 LLM-as-judge 两种实现可切换或并存（A/B），保留 `analysis_version`。澳洲英文回答需要单独做实体识别、推荐判断和本地相关性判断。

解析字段：

```text
brand_mentioned
brand_recommended
brand_rank
competitors_mentioned
competitor_rank
recommendation_strength
sentiment
local_relevance
citation_sources
review_sources
price_mentions
availability_mentions
negative_mentions
uncertainty_flags
```

`local_relevance` 是澳洲首发关键字段，用来判断 AI 是否真的把品牌识别为澳洲可用方案，而不是泛泛介绍。

判断依据：

```text
是否提到 Australia / Australian customers
是否提到澳洲城市
是否提到 AUD 价格
是否提到澳洲配送或服务范围
是否提到澳洲客服、门店或本地团队
是否引用澳洲本地信源
是否使用澳洲相关术语
```

实体识别要求：

- 支持品牌别名、域名、产品名、母公司名（实体与别名表见 8.14）。
- 支持竞品别名和产品线。
- 对同名品牌做人工确认机制。
- 保存解析置信度和规则/模型版本（`analysis_version`）。

### Step 8：建立 Citation Graph

Citation Graph 在内容生成之前上线。底层存储通过 `GraphStore` 接口实现：MVP 起步用 PostgreSQL 邻接表，关系复杂后可平滑替换为 Neo4j / Apache Jena，查询接口不变。

数据字段：

```text
source_id
source_url
source_domain
source_type
market_code = AU
topic
intent_type
brand_mentioned
competitors_mentioned
citation_count
ai_platform_seen
answer_run_ids
authority_score
freshness_score
local_relevance_score
source_gap_type
last_seen_at
```

系统应自动输出：

```text
哪些信源经常被 AI 引用
哪些信源有竞品但没有我方品牌
哪些信源内容过旧
哪些信源适合补充内容
哪些信源对某类问题影响最大
哪些澳洲本地信源缺失
```

澳洲高价值信源层：

| 信源层 | 代表 |
| --- | --- |
| 官方/监管 | gov.au、ACCC、ASIC、ATO、TGA、ACMA、州政府网站 |
| 品牌自有 | `.com.au` 官网、AU landing page、FAQ、shipping/returns、pricing AUD |
| 消费评价 | ProductReview.com.au、Google Reviews、Trustpilot、Reddit AU threads |
| 独立评测 | CHOICE、Canstar、Finder、WhistleOut、Mozo |
| 本地媒体 | ABC、SBS、The Guardian Australia、SMH/The Age、AFR、news.com.au |
| 视频/社媒 | YouTube、TikTok、Instagram、LinkedIn |
| B2B/软件 | G2、Capterra、GetApp、行业协会、案例页、白皮书 |

### Step 9：计算 AU Visibility Score

评分必须可解释、公式版本化（`ScoringFormula` 可整体替换，历史分数按旧版本可重算），不输出单一总分。

#### 9.1 子指标与公式

评分子指标（固定 8 项）：

```text
MentionScore：品牌是否出现
RecommendationScore：是否被明确推荐
PositionScore：在推荐列表中的位置
CitationScore：是否引用澳洲本地或高权重信源
LocalRelevanceScore：回答是否体现澳洲可购买、可服务、可交付
SentimentScore：描述是否正向、中性、负向
FreshnessScore：引用信息是否较新
CompetitorShareScore：竞品共现和压制程度
```

评分公式 `au_visibility_v1`（8 项权重之和为 1.00）：

```text
AUVisibilityScore =
  MentionScore * 0.18 +
  RecommendationScore * 0.22 +
  PositionScore * 0.12 +
  CitationScore * 0.16 +
  LocalRelevanceScore * 0.14 +
  SentimentScore * 0.08 +
  FreshnessScore * 0.05 +
  CompetitorShareScore * 0.05
```

P0 平台权重（固定默认值，可在 MarketProfile 调整）：

```text
Google AI Overviews / AI Mode: 45%
ChatGPT Search / browsing: 30%
Perplexity: 25%
```

P1/P2 平台扩展权重（默认值，可在 MarketProfile 调整）：

```text
Google AI Overviews / AI Mode: 35%
ChatGPT Search / browsing: 25%
Perplexity: 15%
Gemini: 10%
Bing Copilot: 10%
Claude: 5%
```

#### 9.2 分母口径（必须区分"没触发"和"没提到"）

由于 Google AIO 选择性触发，各比率必须明确分母，避免把"AIO 没出现"误算成"品牌缺失"：

```text
Trigger Rate      = surface_triggered 次数 / 采集尝试次数
Mention Rate      = 提及品牌次数 / surface_triggered 次数      # 分母是触发子集，不是全部尝试
Recommendation Rate = 明确推荐次数 / surface_triggered 次数
```

报告中两个分母都要展示：既看"AI 答案出现的概率"（Trigger Rate），也看"出现时品牌的表现"（Mention/Recommendation Rate）。

#### 9.3 非确定性与重复采样

AI 答案非确定性强，单次采样（N=1）评分噪声大。要求：

```text
每条 prompt 在每个平台、每个城市重复采样 k 次（P0a stable 固定 k=3，用 sample_index 区分）
Google spike 固定 k=2 起步，通过健康闸门后再提升到 k=3
分数按 k 次聚合，报告展示均值与离散度（标准差或置信区间）
样本量、采集时间窗口、平台覆盖范围在报告中显示
明确提示 AI 答案非确定性，不做绝对排名承诺
```

P0 采样量闸门：

```text
P0a stable 默认上限:
  prompts: 100
  platforms: 2（chatgpt, perplexity）
  geo: Australia + Sydney + Melbourne + Brisbane
  k: 3
  planned_runs: 100 * 2 * 4 * 3 = 2400

P0b Google spike 默认上限:
  prompts: 30
  platforms/surfaces: 2（google_aio, google_ai_mode）
  geo: Australia + Sydney
  k: 2
  planned_runs: 30 * 2 * 2 * 2 = 240

cost_gate:
  - 每个 collector_backend 必须写入 CollectionCost
  - 单项目 planned_runs、成功率、平均耗时、API/代理/LLM 成本必须在报告方法页展示
  - 若 P0a 2400 runs 的耗时或成本不可控，优先降级城市数或 prompt 数，不降级证据字段
```

#### 9.4 评分要求与局限

- 总分必须能拆到平台、intent、city、prompt，每个分数能点回原始 answer run。
- 公式版本化；调整权重或公式时不覆盖历史，旧分数可用旧公式重算。
- **构念效度局限要写进方法说明**：T+7/14/30 复测能展示"分数变化"，但本期不声称"分数高 = 业务结果好"。后续若拿到客户转化/咨询数据，再做相关性验证。

### Step 10：做 Competitor Benchmark

P0 每个项目支持 3-5 个竞品。

对比维度：

```text
brand mention rate
recommendation rate
average answer position
citation count
source overlap
unique competitor sources
sentiment
local relevance
city-level advantage
intent-level advantage
```

输出内容：

- 哪些 prompt 竞品出现而我方没有。
- 哪些 source 只覆盖竞品。
- 竞品在哪些城市或意图中更强。
- 竞品被推荐时 AI 使用了什么理由。
- 我方需要补哪些事实、页面或第三方信源。

### Step 11：输出 Action Plan

P0 报告给轻量建议；完整 Action Plan 自 P1 起做。

行动建议类型：

```text
更新 AU landing page
新增 FAQ
新增 comparison page
补充 Schema.org 结构化数据
补充 AUD 价格、配送、售后、城市覆盖
修复品牌事实不一致
建立或更新 ProductReview / Google Reviews / Trustpilot
监测 Reddit 讨论
创建 YouTube explanation / review 内容
补充本地媒体或行业目录资料
补充 B2B 案例页或白皮书
```

每条建议必须绑定：

```text
action_id
source_gap_id
related_prompt_ids
related_answer_run_ids
evidence_summary
target_source_type
expected_impact
effort_level
owner
status
next_check_date
```

原则：

- 不输出没有证据支撑的泛泛建议。
- 不承诺强因果。
- 用任务状态和复测窗口展示变化。

### Step 12：本地化品牌知识事实

知识库在 P1 做轻量版本，不作为 P0 的阻塞项。

字段：

```text
AU product availability
AUD price range
delivery coverage
local support hours
Australian customer cases
city coverage
local competitors
local FAQs
local terminology
local source references
```

知识库检索规则（通过 `VectorStore` 接口，pgvector 起步）：

```text
生成澳洲内容或建议时，优先检索 market = AU 的事实
AU 事实不足时，允许回退到 global 事实
回退事实必须标记为 global_source
内容和建议需要提示本地化缺口
```

### Step 13：报告导出和代理商工作流

报告导出是 P0/P1 的关键能力，通过 `ReportExporter` 接口实现。

报告结构：

```text
Executive Summary
Methodology
Audit & Provenance Summary
Platform Coverage
Prompt Coverage
AU Visibility Score
Score Explanation Bundle
Platform Breakdown
City Breakdown
Intent Breakdown
Competitor Benchmark
Citation Graph
Source Gaps
Raw Evidence Appendix
Manual Intervention Log
Action Plan
Next Check Schedule
```

代理商工作流：

```text
multi_client
multi_project
white_label_report
report_template
assignee
task_status
monthly_snapshot
export_history
```

报告必须展示：

- 采集时间窗口。
- 平台覆盖与采集方式（`access_method`）。
- prompt 数量。
- 城市覆盖。
- 样本量（含每 prompt 重复次数 k）与离散度。
- Trigger Rate 与 Mention/Recommendation Rate 两类口径。
- 原始证据链接。
- 评分公式版本摘要。
- 分数解释包：每个总分/平台分/城市分/intent 分的子指标贡献、权重、分母、证据 answer_run_ids。
- 审计摘要：报告版本、导出时间、导出人/系统、score_snapshot_ids、answer_run_ids、是否存在人工补录或人工实体确认。
- API 与消费者界面差异抽检结论。
- AI 答案非确定性说明。

### Step 14：做发布前后复测

复测节奏：

```text
T0：行动前基线
T+7 days：第一次复测
T+14 days：第二次复测
T+30 days：月度复测
```

复测指标：

```text
品牌是否开始出现
品牌推荐率是否上升
平均位置是否上升
引用源是否变化
竞品是否下降
回答是否更本地化
LocalRelevanceScore 是否提升
CitationScore 是否提升
```

效果归因口径：

```text
不做强因果归因
做前后窗口对比
展示行动任务与指标变化的时间线
对同类问题聚合计算趋势
保留所有原始 answer runs
复测沿用同一 prompt_version 和同一 k 次采样口径
```

复测调度通过任务编排（Temporal / Airflow）实现，T0/T+7/T+14/T+30 作为可重放的工作流。

### Step 15：P2 内容生成和集成

内容生成必须建立在 evidence 和 source gap 上，生成链路复用 `LLMGateway` 与 `VectorStore` 接口。

P2 内容模板：

```text
Best [category] in Australia
[brand] review Australia
[brand] vs [competitor]
How to choose [category] in Australia
[city] guide for [category]
FAQ for Australian customers
Comparison table
Schema.org structured data draft
YouTube script
Reddit-style answer draft
ProductReview response draft
```

生成链路：

```text
source gap / prompt gap
  -> 查 AU 知识事实（VectorStore）
  -> 查 Citation Graph（GraphStore）
  -> 选择 AU 内容模板
  -> 生成内容（LLMGateway）
  -> 人工审核
  -> 创建发布任务或 CMS 草稿
  -> 复测
```

内容生成结果必须关联：

```text
target_question_ids
target_city
target_platform
target_source_type
used_knowledge_fact_ids
source_gap_ids
content_template_id
review_status
```

P2 集成优先级：

```text
Google Search Console
GA4
Shopify
WordPress
Webflow
HubSpot
Cloudflare
Looker Studio / CSV export
```

## 6. 最小可落地版本

最快澳洲首发 MVP 压缩为 3 层、10 个交付项：

```text
P0a Stable Evidence Chain:
1. AU MarketProfile
2. 1 个行业模板 + 100 条 AU Prompt Pack
3. Perplexity Sonar + OpenAI web search 两个稳定采集后端
4. Raw Evidence Store（含 answer_present、surface_triggered、sample_index、CollectionCost）
5. Answer Parser
6. AUVisibilityScore（公式版本化，含 Trigger/Mention 双分母）

P0b Google High-risk Spike:
7. Google AIO / AI Mode 采集 spike（30 prompts、Australia + Sydney、k=2、自建/第三方/人工三路径对比）

P0c Customer Evidence Report:
8. Citation Graph
9. Competitor Benchmark
10. Evidence Report Export（含 Google spike 结论、平台覆盖和降级说明）
```

P0a 开源底座（一键起服）：

```text
PostgreSQL(+pgvector) + MinIO + FastAPI + Next.js
+ LiteLLM + Playwright + simple worker/cron
（Docker Compose 起步，组件按 3.3 选型，接口保留可替换）
```

P0 可延后但保留接口的组件：

```text
ClickHouse：P0a 可先用 PostgreSQL 分区表记录指标；采集量稳定后再迁移
Temporal：P0a 可先用 simple worker/cron；复测和大规模重试进入 P1
Langfuse/promptfoo：P0a 可先用结构化日志和小型评测集；解析器校准期再接入
SearXNG：仅作为传统结果基线，不阻塞 P0a
Metabase：P0c 可用模板导出优先，Metabase 不阻塞报告
```

这个版本不要求：

- 自动生成内容。
- 自动发布。
- 完整知识图谱（用 PG 邻接表起步即可）。
- 多模态素材。
- 全平台采集。
- Google AIO / AI Mode 全量稳定采集（P0b 先给 spike 结论）。
- 强因果归因。

## 7. 研发顺序

| 阶段 | 重点 | 产出 | 主要开源组件 |
| --- | --- | --- | --- |
| 第 0 阶段 | 接口契约与轻量开源底座 | CollectorBackend/ParserEngine/VectorStore 等接口定义、核心 Compose 起服；重组件只保留接口和迁移路径 | FastAPI、PostgreSQL、MinIO、Docker |
| 第 1 阶段 | AU MarketProfile、行业模板、Prompt Pack | 市场配置、1 个行业、100 条问题 | PostgreSQL |
| 第 2a 阶段 | P0a 稳定 AI Answer Runner 和 Raw Evidence Store | Perplexity Sonar + OpenAI web search 两个后端、截图/HTML/引用/触发状态留存、CollectionCost | LiteLLM、MinIO、Playwright、simple worker/cron |
| 第 2b 阶段 | P0b Google AIO / AI Mode spike | 自建浏览器、第三方 SERP、人工补录三路径对比，输出 pass/fail gate | Playwright、第三方 SERP API、MinIO |
| 第 3 阶段 | Answer Parser 和 AUVisibilityScore | 提及/推荐/排名/竞品/引用/本地相关性、双分母、重复采样 | spaCy、Sentence-Transformers、Langfuse、promptfoo |
| 第 4 阶段 | Citation Graph 和 Competitor Benchmark | 信源图谱、竞品压制、source gap | PostgreSQL 邻接表（后续 Neo4j）、ClickHouse |
| 第 5 阶段 | Evidence Report Export | PDF/CSV 报告、证据附录、方法说明 | Metabase、模板引擎 |
| 第 6 阶段 | Action Plan 和复测 | 任务建议、T+7/T+14/T+30 复测 | Temporal/Airflow |
| 第 7 阶段 | Knowledge Facts、Content Engine、Integrations | 本地事实库、内容生成、GSC/GA4/Shopify/WordPress | pgvector、LlamaIndex/LangChain |

## 8. 数据模型增量

> 所有表设计遵循第 3 章的数据契约原则：业务模块只依赖这些表结构，不依赖具体采集/存储实现。

### 8.1 MarketProfile

```text
id
market_code
market_name
locale
timezone
currency
primary_language
platform_weights
city_samples
source_type_weights
status
```

### 8.2 IndustryProfile

```text
id
industry_code
market_code
default_prompt_templates
source_type_weights
competitor_fields
required_local_facts
report_template_id
status
```

### 8.3 PromptQuestion

```text
id
project_id
market_code
industry_code
text
intent_type
city
language
target_brand
competitors
priority
intent_weight
prompt_version
status
```

### 8.4 GeoSample

```text
id
market_code
country
city
language
device
geo_provider
sampling_weight
status
```

### 8.5 AnswerRun

```text
id
project_id
prompt_question_id
platform
surface                 # aio / ai_mode / search / browsing
access_method           # browser / official_api / third_party_api / manual
market_code
city
language
device
model_or_surface
account_state
collector_version
collector_backend_id    # 使用了哪个采集后端实现
answer_present          # 该答案/界面是否出现
surface_triggered       # 目标生成式界面是否触发
sample_index            # 同一 prompt 第几次重复采样
sample_size             # 本轮计划重复次数 k
collected_at
raw_payload_hash
status
```

### 8.6 RawAnswer

```text
id
answer_run_id
answer_text
answer_html_snapshot_url
screenshot_url
raw_payload_url
created_at
```

### 8.7 AnswerCitation

```text
id
answer_run_id
source_url
source_domain
source_title
citation_position
source_type
market_code
created_at
```

### 8.8 AnswerAnalysis

```text
id
answer_run_id
brand_mentioned
brand_recommended
brand_rank
competitors_mentioned
competitor_rank
recommendation_strength
sentiment
local_relevance_score
citation_score
freshness_score
competitor_share_score
au_visibility_score
scoring_formula_version   # 使用的评分公式版本
uncertainty_flags
analysis_version          # 解析器实现/模型版本
parser_engine_id          # 规则 / LLM-as-judge 等实现标识
diagnosis
```

### 8.9 SourceGraph

```text
id
project_id
market_code
source_url
source_domain
source_type
topic
intent_type
brand_mentioned
competitors_mentioned
citation_count
ai_platform_seen
answer_run_ids
authority_score
freshness_score
local_relevance_score
source_gap_type
last_seen_at
```

### 8.10 CompetitorBenchmark

```text
id
project_id
market_code
competitor_name
intent_type
city
mention_rate
recommendation_rate
average_position
citation_count
source_overlap
unique_sources
sentiment_score
local_relevance_score
snapshot_at
```

### 8.11 ActionRecommendation

```text
id
project_id
market_code
source_gap_id
related_prompt_ids
related_answer_run_ids
action_type
evidence_summary
target_source_type
expected_impact
effort_level
owner_id
status
next_check_date
created_at
```

### 8.12 LocalizedKnowledgeFact

```text
id
project_id
market_code
fact_type
subject
predicate
object
city
evidence_source_id
confidence
status
valid_from
valid_until
```

### 8.13 VisibilityScoreSnapshot（聚合分数，新增）

单条答案分数在 `AnswerAnalysis`；项目/平台/城市/意图维度的加权汇总单独落表，保证报告可复现。

```text
id
project_id
market_code
scope_type            # project / platform / city / intent / prompt
scope_value
scoring_formula_version
platform_weights_snapshot
sample_size           # 该范围聚合用到的采样总数
trigger_rate
mention_rate
recommendation_rate
au_visibility_score_mean
au_visibility_score_stddev
answer_run_ids
window_start
window_end
created_at
```

### 8.14 BrandEntity / CompetitorEntity / EntityAlias（实体消歧，新增）

支撑解析器做品牌/竞品识别与同名消歧，避免实体误判。

```text
BrandEntity / CompetitorEntity
  id
  project_id
  canonical_name
  official_domains
  parent_company
  product_lines
  status

EntityAlias
  id
  entity_id
  entity_kind           # brand / competitor
  alias
  alias_type            # 别名 / 域名 / 产品名 / 母公司名
  confidence
  confirmed_by          # 同名消歧的人工确认
```

### 8.15 CollectionCost（单位经济，新增）

跟踪每次采集与分析的成本，支撑定价与 unit economics。

```text
id
answer_run_id
project_id
collector_backend_id
llm_provider
llm_tokens
llm_cost
proxy_or_vendor_cost
compute_cost
total_cost
created_at
```

### 8.16 AuditEvent（审计事件，新增）

记录系统、用户、worker 对关键对象的修改和运行事件，支撑客户质询、内部排障和报告复盘。

```text
id
event_type
project_id
actor_type              # user / system / worker / api
actor_id
target_type             # project / prompt / answer_run / analysis / score_snapshot / report
target_id
before_hash
after_hash
input_refs              # prompt_question_ids / answer_run_ids / source_ids
output_refs             # analysis_ids / score_snapshot_ids / report_export_id
method_version          # collector_version / parser_version / scoring_formula_version
reason
created_at
```

### 8.17 ReportExport（报告版本快照，新增）

报告导出是不可覆盖的版本快照。每次导出生成一条新记录，保证同一客户在不同时间看到的数字可以复盘。

```text
id
project_id
market_code
report_version
report_type             # internal_demo / design_partner / customer
score_snapshot_ids
answer_run_ids
prompt_version
scoring_formula_version
platform_weights_snapshot
sample_size
window_start
window_end
methodology_hash
pdf_url
csv_url
exported_by
exported_at
```

### 8.18 ScoreContribution（分数解释贡献，新增）

保存每个聚合分数的子指标贡献，避免报告只给总分、无法解释"为什么是这个分"。

```text
id
score_snapshot_id
component_name           # Mention / Recommendation / Position / Citation / LocalRelevance ...
component_score
weight
weighted_contribution
denominator
evidence_answer_run_ids
positive_evidence_summary
negative_evidence_summary
confidence_note
created_at
```

### 8.19 EvidenceLink（证据关联表，新增）

替代大数组的长期方案。P0 可以先保留 `answer_run_ids` 数组，但必须同步设计关联表，便于后续查询、分页和审计。

```text
SourceGraphEvidence
  id
  source_graph_id
  answer_run_id
  answer_citation_id
  relation_type          # cited_by_ai / competitor_only / source_gap / stale_source
  created_at

ScoreSnapshotRun
  id
  score_snapshot_id
  answer_run_id
  contribution_role      # numerator / denominator / excluded / google_limited_coverage
  created_at

ReportEvidence
  id
  report_export_id
  answer_run_id
  evidence_role          # score_input / appendix / google_spike / manual_backfill
  created_at
```

## 9. 一期验收标准

澳洲首发 P0 技术验收：

- 可创建 `market = AU` 的 GEO 项目。
- 可选择 1 个行业模板并生成 100 条澳洲问题集。
- 可配置 3-5 个竞品。
- **P0a 稳定链路**：可完成 Perplexity Sonar 与 OpenAI web search 两个平台采集，每条有 answer、citation、screenshot 或 HTML 快照。
- **P0b Google spike**：可完成 Google AIO / AI Mode 的限时采集验证，输出 pass/fail gate、触发率、失败原因、成本/耗时估算和样本证据。
- **每个平台的采集后端可插拔**：P0a 至少两个官方 API 后端可工作；P0b 至少对比自建浏览器、第三方 SERP API、人工补录中的两条路径；新增后端不改业务代码。
- 每条采集结果有 answer、citation、screenshot 或 HTML 快照。
- 每条采集结果记录平台、surface、access_method、城市、语言、设备、采集时间、collector_version 和 collector_backend_id。
- **每条采集结果记录 `answer_present` / `surface_triggered`**，报告能区分 Trigger Rate 与 Mention/Recommendation Rate。
- **审计链路可用**：采集、解析、评分、人工补录、实体确认、报告导出都写入 `AuditEvent`。
- **溯源链路可用**：任意报告数值都能从 `ReportExport -> VisibilityScoreSnapshot -> ScoreContribution -> AnswerAnalysis -> AnswerRun -> RawAnswer/AnswerCitation/EvidenceAsset` 追溯。
- **解释包可用**：任意总分/平台分/城市分/intent 分都能展示子指标贡献、权重、分母、正负证据和局限说明。
- P0a 每条 prompt 支持 k=3 重复采样（`sample_index`），评分展示均值与离散度；P0b Google spike 可先用 k=2，通过健康闸门后再升到 k=3。
- 每个 collector_backend 写入 `CollectionCost`；报告能展示 planned_runs、成功率、平均耗时和单位成本。
- 可自动解析品牌提及、推荐、排名、竞品、引用源和本地相关性。
- 可生成可拆解、公式版本化的 `AUVisibilityScore`。
- 可生成 Citation Graph。
- 可输出 3-5 个竞品的 Benchmark。
- 可识别 source gap。
- 可导出包含方法说明（含 API/消费者界面差异抽检结论、Google spike 结论、平台覆盖/降级口径）、审计摘要、分数解释包和原始证据附录的 PDF/CSV 报告。

架构验收（开源·可插拔）：

- P0a 必须完成接口级可插拔：CollectorBackend、ParserEngine、ScoringFormula、ReportExporter 均有 stub 与至少一个工作实现。
- 向量库、图库、LLM 供应商的替换演示不阻塞 P0a 客户试点；P0c/P1 前至少各演示一次"替换/切换后业务不变"：向量库 pgvector ↔ Qdrant、图库 PG 邻接表 ↔ Neo4j、LLM 供应商经 LiteLLM 切换。
- 解析器规则实现与 LLM-as-judge 实现可对同一答案并行对比并保留版本。
- 评分公式可升级到新版本，历史分数仍可按旧版本重算。

P1 技术验收：

- 可基于 source gap 生成 Action Plan。
- 可维护 AU 本地化知识事实。
- 可创建任务 owner、状态和 next_check_date。
- 可按 T+7/T+14/T+30 复测。
- 可在报告中展示前后窗口变化。

## 10. 结论

澳大利亚首发仍然复用 GENO 的底层逻辑，但落地顺序要调整：

```text
先做证据平台
再做信源图谱
再做竞品差距
再做行动建议
再做复测报告
最后再做内容生成、自动分发和集成
```

工程实现上，最关键的不是先把内容生成做完整，而是把以下能力做扎实：

- `AU Market Profile`
- `Prompt Pack`
- `AI Answer Runner`（可插拔采集后端，AIO/AI Mode 分离，记录触发状态）
- `Raw Evidence Store`
- `Answer Parser`
- `Citation Graph`
- `Competitor Benchmark`
- `Evidence Report Export`

并且全程坚持三条架构硬约束——**开源优先、模块化松耦合、可插拔替换**：每个能力对应一个明确接口和一套开源选型，采集后端、向量库、图库、LLM 供应商、解析器、评分公式都能独立替换。这样既能在 MVP 阶段用最小开源底座快速跑通，又能在平台改版、规模增长或商业化降本时逐块替换而不重写系统。

这条路径更适合澳大利亚首发，因为它能更快形成客户可验证价值，也能为后续内容生成、分发和多市场扩展打下可审计、可替换的数据与工程基础。
