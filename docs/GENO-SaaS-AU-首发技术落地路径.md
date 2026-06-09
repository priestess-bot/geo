# GENO SaaS 澳大利亚首发技术落地路径

版本日期：2026-06-09

## 1. 核心判断

澳大利亚首发不建议一开始复制完整 GENO 闭环，也不建议优先做内容生成、自动分发或多模态资产。更优路径是先做一个 **Evidence-first AI Search Visibility MVP**：

> 先证明 AI 如何看见品牌、引用哪些来源、推荐哪些竞品、哪些澳洲本地信源缺失，再把证据转成可执行任务和复测报告。

原因：

- 澳大利亚是 Google 强势市场，Google Search / AI Overviews / AI Mode 必须优先监测。
- 澳大利亚客户更容易接受可审计报告、原始证据、引用来源和行动清单，不容易接受黑箱“投喂大模型”。
- Semrush、Ahrefs、HubSpot 等 SEO 工具会是强竞品，单纯做一个 AI visibility 分数不够，需要把 raw evidence、citation graph 和 agency report 做深。
- 一期最重要的是建立数据口径、采样方法和客户信任，而不是先追求自动化内容生产。

因此，澳洲首发主流程建议从原来的：

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

## 2. 一期产品定位

一期产品建议定位为：

> 面向澳大利亚品牌和代理商的 AI Search Visibility & GEO Evidence Platform。

核心交付物不是“自动生成一堆内容”，而是一份可审计 AI 可见性报告：

- AI 是否提到品牌。
- AI 是否推荐品牌。
- 品牌在推荐列表中的位置。
- AI 是否引用品牌官网或澳洲本地信源。
- AI 引用了哪些竞品信源。
- 竞品在哪些 prompt/topic/source 上压制品牌。
- 品牌事实是否缺少澳洲本地化信息。
- 下一步应该修补哪些网页、FAQ、Schema、评价源、对比页、本地媒体或行业目录。
- 发布或修补后，7/14/30 天是否发生变化。

## 3. MVP 范围分层

### 3.1 P0：必须做

| 模块 | 目标 |
| --- | --- |
| AU Market Profile | 固定澳大利亚市场配置、平台权重、语言、城市和信源分类 |
| Prompt Pack | 生成 100-200 条澳洲英文问题集，覆盖品牌、品类、竞品、口碑、价格、本地服务 |
| AI Answer Runner | 采集 Google AI Overviews / AI Mode、ChatGPT、Perplexity 的答案 |
| Raw Evidence Store | 保存 prompt、平台、城市、时间、原始回答、引用 URL、截图/HTML 快照 |
| Answer Parser | 解析品牌提及、推荐、排名、竞品、引用、情绪和本地相关性 |
| Citation Graph | 统计 AI 引用源、竞品来源、source type、topic 和本地权重 |
| Visibility Score | 计算可解释的 AU Visibility Score，支持拆分指标 |
| Competitor Benchmark | 对比 3-5 个竞品的提及、推荐、引用和 source overlap |
| Evidence Report Export | 输出客户可审计报告，支持 PDF/CSV |

### 3.2 P1：第二阶段做

| 模块 | 目标 |
| --- | --- |
| Action Plan | 把证据和信源缺口转成可执行任务 |
| Localized Knowledge Facts | 维护澳洲本地品牌事实、价格、配送、服务、城市覆盖和证据 URL |
| Agency Workflow | 多客户、多项目、白标报告、任务 owner 和复测窗口 |
| 7/14/30 天复测 | 发布前后窗口对比，展示指标变化和原始证据 |
| Manual Distribution Record | 只记录人工发布 URL 和状态，不做自动发布 |

### 3.3 P2：验证市场后再做

| 模块 | 目标 |
| --- | --- |
| Content Engine | 基于 prompt gap、source gap 和知识库事实生成 FAQ、comparison、schema、landing page outline |
| Integrations | GA4、Google Search Console、Shopify、WordPress、Webflow、HubSpot、Cloudflare |
| Broader Platform Coverage | Gemini、Bing Copilot、Claude、YouTube、Reddit、ProductReview 深度采集 |
| Workflow Automation | 自动创建 CMS 草稿、自动提醒、自动复测、API 输出 |
| Multi-market Expansion | 从 AU 扩展到 NZ、UK、US、SG 等英语市场 |

## 4. Step-by-step 实施方案

### Step 1：建立 AU Market Profile

新增 `MarketProfile = AU`，把澳洲市场配置从业务逻辑中抽离出来。

建议配置：

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
Google AI Overviews / AI Mode
ChatGPT Search / browsing
Perplexity
```

P1/P2 平台扩展：

```text
Gemini
Bing Copilot
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

不要一开始泛化到所有行业。澳洲首发建议先选择 1-2 个易验证行业。

优先行业判断：

| 行业 | 适合原因 |
| --- | --- |
| DTC / e-commerce | Shopify/WordPress 使用广，评价和 comparison 信源明显，复测周期较短 |
| 本地服务 | Google Business Profile、Google Reviews、城市维度强，容易展示 local relevance |
| B2B SaaS / agency 客户 | 能接受报告和数据产品，容易形成代理商工作流 |
| 教育培训 | prompt 明确、对比和口碑强，但转化归因可能较慢 |

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

一期每个项目配置 100-200 条 prompt，不做国内问题集直译。

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
- 城市类 prompt 不要全量复制，P0 只覆盖核心城市和高价值问题。
- prompt 版本必须保留，复测时使用同一版本。

### Step 4：开发 AI Answer Runner

P0 只做三个平台：

```text
Google AI Overviews / AI Mode
ChatGPT Search / browsing
Perplexity
```

采集优先级：

```text
1. Google AI Overviews / AI Mode
2. ChatGPT Search / browsing
3. Perplexity
```

采集方式建议：

```text
Google AI Overviews / AI Mode：浏览器自动化 + 澳洲地区参数 + SERP HTML/截图留存
ChatGPT：API/可用搜索接口优先，必要时浏览器采集
Perplexity：浏览器采集或 API，重点解析引用链接
```

采集服务要求：

- 与主业务服务隔离。
- 支持失败重试。
- 支持平台级限流。
- 支持 collector_version。
- 支持手动补录。
- 支持截图和 HTML 快照留存。
- 记录账号状态、地区、设备和采集方式。

### Step 5：建立 Raw Evidence Store

这是澳洲首发 MVP 的核心，不是附属字段。

每次采集必须保存：

```text
prompt
prompt_version
answer
platform
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
collected_at
raw_payload_hash
```

建议数据模型：

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
- 同一 prompt 的复测必须保留历史版本，不能覆盖。

### Step 6：做地理采样机制

澳洲结果需要区分全国表现和城市表现。

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

新增 `GeoSample` 配置：

```text
country = AU
city
language = en-AU
device = desktop/mobile
sampling_weight
status
```

评分和报告需要支持：

- 全国总览。
- 城市对比。
- 城市问题明细。
- 城市级竞品压制。
- 本地相关性不足提示。

### Step 7：改造澳洲答案解析器

澳洲英文回答需要单独做实体识别、推荐判断和本地相关性判断。

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

- 支持品牌别名、域名、产品名、母公司名。
- 支持竞品别名和产品线。
- 对同名品牌做人工确认机制。
- 保存解析置信度和规则/模型版本。

### Step 8：建立 Citation Graph

Citation Graph 应该早于内容生成上线。

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
last_seen_at
authority_score
freshness_score
local_relevance_score
source_gap_type
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

评分必须可解释，不建议只给一个总分。

建议拆分指标：

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

建议公式：

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

P0 平台权重建议：

```text
Google AI Overviews / AI Mode: 45%
ChatGPT Search / browsing: 30%
Perplexity: 25%
```

P1/P2 平台扩展权重：

```text
Google AI Overviews / AI Mode: 35%
ChatGPT Search / browsing: 25%
Perplexity: 15%
Gemini: 10%
Bing Copilot: 10%
Claude: 5%
```

评分要求：

- 总分必须能拆到平台、intent、city、prompt。
- 每个分数必须能点回原始 answer run。
- 报告里显示样本量、采集时间窗口和平台覆盖范围。
- 明确提示 AI 答案非确定性，不做绝对排名承诺。

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

P1 开始做 Action Plan，但 P0 报告中可以给轻量建议。

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

建议字段：

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

知识库检索规则：

```text
生成澳洲内容或建议时，优先检索 market = AU 的事实
AU 事实不足时，允许回退到 global 事实
回退事实必须标记为 global_source
内容和建议需要提示本地化缺口
```

### Step 13：报告导出和代理商工作流

报告导出是 P0/P1 的关键能力。

报告结构：

```text
Executive Summary
Methodology
Platform Coverage
Prompt Coverage
AU Visibility Score
Platform Breakdown
City Breakdown
Intent Breakdown
Competitor Benchmark
Citation Graph
Source Gaps
Raw Evidence Appendix
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
- 平台覆盖。
- prompt 数量。
- 城市覆盖。
- 样本量。
- 原始证据链接。
- 评分公式摘要。
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
```

### Step 15：P2 内容生成和集成

内容生成必须建立在 evidence 和 source gap 上。

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
  -> 查 AU 知识事实
  -> 查 Citation Graph
  -> 选择 AU 内容模板
  -> 生成内容
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

## 5. 最小可落地版本

最快澳洲首发 MVP 建议压缩为 9 个交付项：

```text
1. AU MarketProfile
2. 1 个行业模板 + 100 条 AU Prompt Pack
3. Google / ChatGPT / Perplexity 三个平台采集
4. Raw Evidence Store
5. Answer Parser
6. AUVisibilityScore
7. Citation Graph
8. Competitor Benchmark
9. Evidence Report Export
```

这个版本不要求：

- 自动生成内容。
- 自动发布。
- 完整知识图谱。
- 多模态素材。
- 全平台采集。
- 强因果归因。

## 6. 建议研发顺序

| 阶段 | 重点 | 产出 |
| --- | --- | --- |
| 第 1 阶段 | AU MarketProfile、行业模板、Prompt Pack | 市场配置、1 个行业、100 条问题 |
| 第 2 阶段 | AI Answer Runner 和 Raw Evidence Store | Google/ChatGPT/Perplexity 采集、截图/HTML/引用留存 |
| 第 3 阶段 | Answer Parser 和 AUVisibilityScore | 品牌提及、推荐、排名、竞品、引用、本地相关性 |
| 第 4 阶段 | Citation Graph 和 Competitor Benchmark | 信源图谱、竞品压制、source gap |
| 第 5 阶段 | Evidence Report Export | PDF/CSV 报告、证据附录、方法说明 |
| 第 6 阶段 | Action Plan 和复测 | 任务建议、T+7/T+14/T+30 复测 |
| 第 7 阶段 | Knowledge Facts、Content Engine、Integrations | 本地事实库、内容生成、GSC/GA4/Shopify/WordPress |

## 7. 数据模型增量

### 7.1 MarketProfile

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

### 7.2 IndustryProfile

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

### 7.3 PromptQuestion

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

### 7.4 GeoSample

```text
id
market_code
country
city
language
device
sampling_weight
status
```

### 7.5 AnswerRun

```text
id
project_id
prompt_question_id
platform
market_code
city
language
device
model_or_surface
account_state
collector_version
collected_at
raw_payload_hash
status
```

### 7.6 RawAnswer

```text
id
answer_run_id
answer_text
answer_html_snapshot_url
screenshot_url
raw_payload_url
created_at
```

### 7.7 AnswerCitation

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

### 7.8 AnswerAnalysis

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
uncertainty_flags
analysis_version
diagnosis
```

### 7.9 SourceGraph

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

### 7.10 CompetitorBenchmark

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

### 7.11 ActionRecommendation

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

### 7.12 LocalizedKnowledgeFact

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

## 8. 一期验收标准

澳洲首发 P0 技术验收：

- 可创建 `market = AU` 的 GEO 项目。
- 可选择 1 个行业模板并生成 100 条澳洲问题集。
- 可配置 3-5 个竞品。
- 可完成 Google、ChatGPT、Perplexity 三个平台采集。
- 每条采集结果有 answer、citation、screenshot 或 HTML 快照。
- 每条采集结果记录平台、城市、语言、设备、采集时间和 collector version。
- 可自动解析品牌提及、推荐、排名、竞品、引用源和本地相关性。
- 可生成可拆解的 `AUVisibilityScore`。
- 可生成 Citation Graph。
- 可输出 3-5 个竞品的 Benchmark。
- 可识别 source gap。
- 可导出包含方法说明和原始证据附录的 PDF/CSV 报告。

P1 技术验收：

- 可基于 source gap 生成 Action Plan。
- 可维护 AU 本地化知识事实。
- 可创建任务 owner、状态和 next_check_date。
- 可按 T+7/T+14/T+30 复测。
- 可在报告中展示前后窗口变化。

## 9. 结论

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
- `AI Answer Runner`
- `Raw Evidence Store`
- `Answer Parser`
- `Citation Graph`
- `Competitor Benchmark`
- `Evidence Report Export`

这条路径更适合澳大利亚首发，因为它能更快形成客户可验证价值，也能为后续内容生成、分发和多市场扩展打下可审计的数据基础。
