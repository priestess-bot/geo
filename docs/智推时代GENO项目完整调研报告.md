# 智推时代 GENO 项目完整调研报告

生成日期：2026-06-08

关联材料：`docs/智推时代-全球GEO业务介绍.pdf`

本报告性质：基于已完成并落盘的分项调研，对智推时代公司、行业背景、GENO 方法论、技术栈、合作案例、竞品格局、澳大利亚首发差异和可落地技术路径做一次完整复盘。本文不替代法律、财务或合同尽调，重点聚焦技术与产品可行性。

## 1. 结论先行

智推时代是一家围绕 GEO（Generative Engine Optimization，生成式引擎优化）提供服务与 SaaS 产品叙事的早期公司。公开材料显示，它试图解决的问题是：当用户从 Google 蓝链、社媒内容进一步迁移到 ChatGPT、Gemini、Perplexity、DeepSeek、豆包、Kimi、文小言等 AI 问答/AI 搜索入口后，品牌如何被 AI 正确识别、推荐、引用，并持续优化可见性。

对这个项目的技术判断可以概括为四句话：

1. **赛道逻辑成立**：搜索行为确实从“找链接”走向“看摘要、问 AI、追问和验证来源”；GEO 是 SEO 在生成式答案环境里的上层扩展，而不是简单替代 SEO。
2. **智推时代的产品叙事完整**：PDF 披露了 GENO 四大模块和“四阶闭环”：意图分析、品牌知识库、内容结构化/分发、监测复测迭代。
3. **公开证据不足以证明 GENO 系统成熟度**：目前能看到的是产品能力、方法论、案例叙事和行业报告背书，未看到公开 API、试用入口、系统后台、评分公式、采样方法、真实数据样例或第三方技术评测。
4. **如果我们做澳大利亚首发，应把产品定位为“AI Search Visibility & GEO Evidence Platform”**：先做可审计采样、原始回答保存、引用图谱、竞品对比和行动建议，再逐步做内容生成、分发和自动化优化。

最重要的产品原则是：

> 不要把 GEO 做成“黑箱投喂大模型”的服务，而要做成“可复盘的 AI 答案证据平台”。每一个分数、建议和优化效果，都必须能点回原始 prompt、平台、地区、时间、答案、引用 URL 和截图/快照。

## 2. 已落盘证据总览

本次完整报告复用了以下已落盘文件。

| 类型 | 文件 |
| --- | --- |
| 公司调研 | `docs/智推时代公司-可审计调研复盘.md` |
| 用户搜索习惯变迁 | `docs/全球互联网用户搜索习惯变迁-可审计调研复盘.md` |
| SEO 到 GEO 转变 | `docs/SEO到GEO时代转变-可审计调研复盘.md` |
| 搜索引擎与 AI 搜索占比、内容偏好、信源偏好 | `docs/搜索引擎AI搜索占比内容偏好信源偏好-可审计调研复盘.md` |
| GENO 四阶闭环技术栈与开源替代 | `docs/智推时代GENO四阶闭环技术栈与开源替代-可审计调研复盘.md` |
| 合作案例 | `docs/智推时代合作案例-可审计调研复盘.md` |
| 相似服务与竞争企业 | `docs/智推时代相似服务与竞争企业-可审计调研复盘.md` |
| MVP 技术设计 | `docs/GENO-SaaS-MVP-技术设计文档.md` |
| 一期需求拆解 | `docs/GENO-SaaS-MVP-一期需求拆解表.md` |
| 澳大利亚首发技术路径 | `docs/GENO-SaaS-AU-首发技术落地路径.md` |

主要证据目录：

| 目录 | 内容 |
| --- | --- |
| `docs/research_sources/智推时代公司调研/` | 公司官网、融资聚合页、艾瑞报告、媒体转载、PDF 摘要 |
| `docs/research_sources/全球互联网用户搜索习惯变迁/` | Gartner、World Bank、DataReportal、Pew、Google、OpenAI、StatCounter、SparkToro 等摘要 |
| `docs/research_sources/SEO到GEO时代转变/` | Google SEO/AI 搜索文档、OpenAI ChatGPT Search、GEO 论文、Pew/SparkToro 等摘要 |
| `docs/research_sources/搜索引擎AI搜索占比内容偏好信源偏好/` | 全球、中国、澳大利亚搜索与 AI 数据源摘要 |
| `docs/research_sources/GENO四阶闭环技术栈开源替代/` | GENO PDF 摘录、69 个开源技术资料摘要、网页快照 |
| `docs/research_sources/智推时代合作案例调研/` | 合作案例 PDF 摘录、客户候选网页和媒体网页快照 |
| `docs/research_sources/智推时代相似服务竞品调研/` | 竞品网页快照、逐来源摘要、PDF 竞品对照摘录 |

证据等级口径：

| 等级 | 含义 | 本报告使用方式 |
| --- | --- | --- |
| A | 客户/官方/权威原始资料，可直接核验 | 可作为事实基础 |
| B | 主流媒体、行业报告、工商/融资聚合页、第三方资料 | 可作为公开线索，但关键事实需回源 |
| C | 公司官网、公司 PDF、企业访谈、营销稿 | 可作为公司自述，不直接当作独立事实 |
| D | 无法访问、二级转述、身份不明或缺少原文 | 只作为待补证据 |

## 3. 公司复盘

### 3.1 基本信息

公开资料显示，智推时代的主要主体和品牌信息如下：

| 项目 | 调研结果 | 证据等级 |
| --- | --- | --- |
| 中文主体 | 上海智推时代科技有限公司 | B |
| 品牌名 | 智推时代 | C |
| 英文/产品品牌 | GenOptima | B/C |
| 统一社会信用代码 | 91310113MAEHJPYX6X | B |
| 法定代表人 | 陈缪喆 | B |
| 成立日期 | 2025-05-12 | B |
| 注册资本 | 100 万人民币 | B |
| 注册地址 | 上海市宝山区沪太路 8885 号 6 幢 | B |
| 官网 | `https://zhituishidai.com/` | C |
| 业务定位 | AI 搜索生态优化 / GEO 解决方案 | C |

需要注意一个时间线问题：公开工商聚合信息显示公司主体成立于 2025-05-12，但官网或传播材料中出现“2023 年布局生成式搜索优化方向”“200+ 客户”等叙述。合理解释可能是团队早于公司主体探索，或客户口径包含前身业务、合作生态、历史服务项目。但在正式材料中，应区分“公司法人主体成立时间”和“团队业务探索时间”。

### 3.2 业务定位

智推时代的核心定位是帮助品牌提升 AI 搜索和 AI 问答平台中的可见性、推荐率、引用质量和事实准确性。PDF 中提到服务行业包括教育、汽车、企业服务、金融、游戏、大健康、新零售等，并将服务对象分为 KA 定制化、MB 半定制、SB 标准化和海外市场。

公开材料中较一致的业务关键词包括：

- AI Visibility / AI 可见性。
- 生成式引擎优化 / GEO。
- 多平台 AI 搜索监测。
- 用户意图分析。
- 品牌知识库和知识图谱。
- 内容结构化和多模态生成。
- 信源漏洞扫描。
- 复测和迭代闭环。

### 3.3 融资与背书

公开材料中出现“千万级种子轮融资”“投资方包括三七互娱、趣睡科技”等线索；艾瑞《2026 年 GEO 生成式引擎优化行业研究报告》中也有智推时代 GenOptima 案例页。但这些信息仍需要进一步补强：

- 未在本次调研中找到三七互娱或趣睡科技直接披露投资智推时代的完整上市公司公告链。
- 艾瑞报告案例页来源包含企业专家访谈、智推时代官网和艾瑞自主研究，具有行业报告背书价值，但不等于完全独立审计。
- 部分媒体稿件营销属性较强，适合证明“市场传播活跃”，不适合单独证明技术成熟度、客户效果或融资真实性。

因此，现阶段对公司最稳妥的判断是：

> 智推时代是一个在 2025-2026 年快速推进 GEO 服务与产品化叙事的早期品牌，已形成较完整的方法论、模块命名、案例包装和行业曝光，但公开证据尚不足以完全验证全球布局、客户规模、融资细节和 GENO 系统真实成熟度。

## 4. 背景复盘：为什么会出现 GEO

### 4.1 用户搜索习惯的变化

PDF 将搜索变迁概括为“从索引、种草到生成”。这个方向总体成立，但部分预测数据需要校准。PDF 提到“到 2028 年，50% 的搜索引擎流量将被 AI 搜索蚕食”，标注 Gartner；本次公开核验到的 Gartner 原始口径是 2024-02-19 发布的预测：“到 2026 年，传统搜索引擎量将下降 25%，原因是 AI 聊天机器人和其他虚拟代理”。因此，2028/50% 的精确表达应列为待补证据。

更可审计的趋势是五段变化：

1. **互联网普及**：2005 年全球互联网使用人口占比约 15.6%，2020 年超过 60%，到 2026 年 DataReportal 估计全球互联网用户约 61.2 亿。
2. **蓝链搜索成为默认入口**：Pew 2012 年数据显示，美国在线成年人中 91% 使用搜索引擎，59% 在任意一天使用搜索引擎。
3. **移动搜索把行为切碎成即时任务**：Google 2015 年称美国、日本等 10 个国家移动搜索量超过桌面；StatCounter 2016 年显示移动和平板互联网使用量超过桌面。
4. **社媒和短视频成为体验型搜索入口**：用户在 TikTok、Instagram、YouTube、Reddit、小红书、知乎、ProductReview 等平台查体验、教程、评价和避坑。
5. **AI 答案搜索改变结果页行为**：OpenAI 推出 ChatGPT Search；Google AI Overviews 覆盖范围快速扩大；Pew 2025 年数据显示，Google 结果出现 AI 摘要时，用户点击传统搜索结果链接的比例低于没有 AI 摘要时。

这意味着品牌不再只争夺“网页排名和点击”，还要争夺“AI 是否提及、是否推荐、引用谁、是否准确描述品牌事实”。

### 4.2 SEO 到 GEO 的关系

本次复盘建议采用如下定义：

> SEO 是让网页更容易被搜索引擎抓取、理解、索引和呈现；GEO 是面向生成式搜索、AI 问答和答案引擎的品牌可见性优化，通过问题集监测、AI 答案采集、实体与信源治理、结构化事实建设、内容修复和复测闭环，提升品牌在 AI 答案中的提及率、推荐率、引用率和事实准确率。

因此，“GEO 替代 SEO”的说法过于粗糙。更准确的关系是：

- SEO 是 GEO 的底层信源工程。
- AEO 是 SEO 到 GEO 的中间层，关注答案型结果、精选摘要、FAQ、语音助手和知识面板。
- GEO 是面向 AI 答案系统的上层扩展，关注答案中的品牌呈现、推荐、引用和事实准确性。

技术含义是：如果一个品牌官网不可抓取、事实不一致、结构化数据缺失、第三方信源薄弱，那么直接做 GEO 内容生成或“投喂”很难稳定生效。

### 4.3 当前搜索和 AI 搜索格局

截至 2026 年 5 月，传统搜索仍由 Google 主导：

| 市场 | 搜索引擎格局 |
| --- | --- |
| 全球 | Google 约 90.39%，Bing 约 5.03% |
| 中国 | StatCounter 网页侧 Baidu 约 47.16%，Bing 约 20.19%，Haosou 约 15.03%；但中国大量搜索发生在 App、短视频、电商、本地生活和 AI App 内 |
| 澳大利亚 | Google 约 87.97%，Bing 约 9.09% |

AI chatbot / AI 搜索相关份额口径需要谨慎解释。StatCounter 2026 年 5 月显示：

| 市场 | AI chatbot 份额概览 |
| --- | --- |
| 全球 | ChatGPT 约 79.08%，Perplexity 约 7.67%，Gemini 约 7.03%，Copilot 约 3.23%，Claude 约 2.98% |
| 澳大利亚 | ChatGPT 约 70.70%，Copilot 约 11.62%，Gemini 约 6.16%，Claude 约 6.08%，Perplexity 约 5.44% |
| 中国 | StatCounter 结果不适合代表本土 AI App 格局；QuestMobile 2026Q1 显示中国 AI 原生 App 月活约 4.4 亿，豆包、千问、DeepSeek 领先 |

对澳大利亚首发尤其重要的是：Google 在澳洲搜索份额接近 88%，且 Google AI Mode 已在澳大利亚推出。因此，澳洲 GEO 不能只监测 ChatGPT，还必须把 Google AI Overviews / AI Mode 作为核心平台。

## 5. GENO 系统复盘

### 5.1 PDF 披露的四大产品矩阵

PDF 将 GENO 描述为全栈自研 SaaS 平台，并拆成四个模块：

| 模块 | 英文名 | PDF 能力描述 | 工程解读 |
| --- | --- | --- | --- |
| 星枢监测系统 | Gen-Centric Sentinel | AI 搜索排名、负面舆情、信源漏洞、竞品镜像、品牌 GEO 指数 | AI 平台回答采集、解析、评分、告警 |
| 星图决策引擎 | Gen-Carto Nexus | 意图解析、需求图谱、画像融合、信源权重策略 | Prompt/关键词扩展、意图聚类、竞品和信源机会分析 |
| 星核创生平台 | Gen-Genesis Forge | 文本/图像/音频/视频生成、信源匹配、自动分发、数字人 | 内容生成工作台、结构化内容、发布任务、内容资产库 |
| 星穹智脑系统 | Gen-Cosmos CogniCore | 权威数据库、本体构建、政策模拟器、信源漏洞扫描、知识关系 | 品牌知识库、行业本体、知识图谱、RAG 和信源治理 |

### 5.2 四阶闭环方法论

PDF 第 25 页的“四阶闭环”可重构为：

```text
问题/关键词/场景词
  -> 星图决策引擎：意图分析
  -> 星穹智脑系统：品牌知识库创建
  -> 星核创生平台：内容结构化、目标模型适配、平台分发
  -> 星枢监测系统：检测结果、迭代新意图
  -> 回到问题集和内容/信源任务
```

这套方法论的核心不是“写文章”，而是一个数据闭环：

- AI 是否能正确识别品牌实体。
- AI 是否在目标问题中推荐该品牌。
- AI 引用了哪些来源。
- 竞品为什么被推荐而品牌没有。
- 哪些品牌事实、内容结构或第三方信源缺口导致答案变化。

### 5.3 技术成熟度判断

公开材料能确认的，是 GENO 的产品能力叙事和合理技术方向；不能确认的，是具体系统实现和运行质量。

已能确认的方向：

- AI 平台回答采集。
- 多平台 AI 可见性监测。
- 用户意图分析。
- 品牌知识库/知识图谱。
- 内容生成和多模态适配。
- 信源漏洞扫描。
- 分发和复测闭环。

未能公开确认的内容：

- 后端语言、前端框架、数据库、队列、向量库、图数据库和调度系统。
- AI 平台采集方式，是官方 API、浏览器自动化、第三方 API 还是人工录入。
- AI 可见性评分公式、样本量、抽样频率、模型版本控制和地理位置控制。
- 知识图谱本体设计、实体消歧、事实校验和引用来源评级方法。
- 自动分发覆盖平台、发布回执、失败重试、审批机制和版本回滚。
- SaaS 试用入口、公开 API 文档、系统后台截图、演示视频、客户验收报告。

因此，若要评估智推时代 GENO 系统是否可用，应要求 Demo 或技术尽调，而不是只依据 PDF。

建议 Demo 验证清单：

1. 创建新品牌项目，配置市场、语言、竞品和 AI 平台。
2. 批量导入 50-100 个 Prompt。
3. 真实采集 ChatGPT、Gemini、Perplexity、Google AI Overviews 或 DeepSeek 的回答。
4. 展示原始回答、截图、时间、地区、账号状态、模型版本。
5. 自动解析品牌提及、推荐位置、引用源、负面描述和竞品共现。
6. 生成 GEO 分数，并解释评分公式和权重。
7. 找出信源缺口并生成内容/信源任务。
8. 发布或记录分发任务。
9. 7 天或 14 天后复测，并展示前后变化和原始证据。

## 6. 技术栈与开源替代方案

GENO 公开披露的是方法论层，不是工程栈层。若要复刻类似系统，可以按以下技术组合落地：

| 能力 | 推荐开源/可自托管组合 |
| --- | --- |
| Web/AI 页面采集 | Playwright、Crawlee、Scrapy |
| 搜索基线和传统排名 | SearXNG、SerpBear |
| LLM API 网关 | LiteLLM |
| LLM 应用编排 | LlamaIndex、LangChain |
| Prompt 追踪与观测 | Langfuse |
| Prompt/LLM 评测 | promptfoo、Ragas |
| 语义向量 | Sentence Transformers |
| 向量库 | pgvector、Qdrant、Milvus |
| 关系库 | PostgreSQL |
| 图数据库/知识图谱 | Neo4j、Apache Jena、RDFLib、Microsoft GraphRAG |
| 文档解析 | Apache Tika、Unstructured |
| 主题聚类和 NLP | BERTopic、spaCy、KeyBERT、scikit-learn |
| 全文检索 | OpenSearch、Meilisearch |
| 自托管模型推理 | vLLM、Ollama、llama.cpp、Transformers |
| 开权模型 | Qwen、DeepSeek 等，需单独核查许可证 |
| 多模态生成 | Diffusers、ComfyUI、Whisper、Piper |
| 工作流调度 | Airflow、Temporal、n8n、Node-RED |
| 指标和日志 | ClickHouse、OpenTelemetry |
| 看板和报表 | Grafana、Metabase、Superset |
| 前后端 | FastAPI、Next.js |
| CMS/内容管理 | Strapi、Directus |
| 对象存储和基础设施 | MinIO、Docker、Kubernetes、Traefik、Keycloak |

最可行的工程骨架是：

```text
Next.js 前端
  -> FastAPI 后端
  -> PostgreSQL 主数据
  -> pgvector/Qdrant 向量检索
  -> Playwright/Crawlee 采集服务
  -> LiteLLM 模型网关
  -> LlamaIndex/LangChain RAG 和任务编排
  -> Neo4j/Jena 知识图谱
  -> ClickHouse 指标事件
  -> Langfuse/promptfoo 观测与评测
  -> Metabase/Grafana/Superset 报表
```

这套开源组合可以覆盖 GENO 方法论 70%-85% 的工程骨架。真正的差距不在组件，而在：

- 平台采集稳定性。
- Prompt 样本库。
- 行业意图库。
- 评分方法。
- 竞品和信源数据资产。
- 多市场本地化经验。
- 内容分发网络。
- 客户可验收的证据链。

## 7. 合作案例复盘

PDF 第 38-45 页列出 8 个合作案例。调研结论是：案例叙事丰富，但多数为匿名或半匿名表达；公开网页能支撑部分客户身份推断和业务背景，但很少能独立证明“客户与智推时代合作”和“效果指标真实因果”。

| PDF 案例 | 客户识别 | PDF 声称效果 | 审计判断 |
| --- | --- | --- | --- |
| 国内知名游戏公司旗下少儿编程 | 高度匹配妙小程 | 主动注册转化率 3% 到 11%，月均 60 单到 250+ 单 | 客户身份和业务背景可核验；合作与效果需客户授权/后台数据 |
| 某数据应用技术研究院 | PDF 点名中经数（北京）数据应用技术研究院 | AI 推荐贡献 70% 报名量，总招生超过 1000 人 | 主体可核验；效果需招生和归因数据 |
| 国内 ESG 教育领先品牌 | PDF 点名探潜 ESG 学堂 | AI 推荐贡献 60% 销售线索，销售周期 12 天到 5 天，获客成本 300 到 70，ROI 14 | 主体可核验；效果需 CRM 和 ROI 口径 |
| 全球领先跨境支付平台 | 匿名，Airwallex/空中云汇和 Payssion 为候选 | 主流 AI 平台全面推荐，品牌信息改善 | 无法确认客户身份 |
| 国内领先职业发展平台 | 高度匹配智联招聘/智联校园 | “招聘软件”“实习平台”“简历”等关键词 TOP1，露出智联校园小程序 | 业务背景可核验；合作和排名需截图/Prompt |
| 国际领先素质教育机构 | 高度匹配犀牛国际教育 | 物理碗竞赛等关键词 TOP1 | 身份可推断；合作和效果需补证 |
| 中国领先智能家居品牌 | 高度匹配趣睡科技/8H | 品类关键词 TOP1，专利技术/米家生态链等提及提升 | 业务背景可核验；效果需补证 |
| 全球领先机器人企业 | 高度匹配智平方 | 人形机器人、VLA、具身大模型等关键词超过竞品居首 | 身份可推断；效果需补证 |

本报告建议把这些案例分成三种使用方式：

- **可用于市场理解**：说明智推时代希望覆盖教育、职业发展、支付、智能家居、机器人等高价值行业。
- **可用于产品需求推导**：说明 GEO 客户关心转化、报名、线索、获客成本、AI 推荐贡献、品类关键词推荐等指标。
- **不宜直接用于事实背书**：除非补充客户授权、合同/验收摘要、优化前后截图、采样 Prompt、平台、时间、地区和后台转化数据。

## 8. 竞品格局复盘

智推时代的竞争对手不只是国内 GEO 服务商，而是三个圈层：

| 圈层 | 代表企业 | 竞争威胁 | 原因 |
| --- | --- | --- | --- |
| 海外 AI Search Visibility / GEO SaaS | Profound、Peec、OtterlyAI、AthenaHQ、Scrunch、Evertune、Brandlight、Gumshoe、Bluefish、ZipTie、Writesonic GEO | 高 | 产品化程度高，强调真实 AI answer 采集、引用、竞品差距、行动建议、API 和企业级看板 |
| 传统 SEO 平台 AI 化 | Semrush、Ahrefs、BrightEdge、Conductor、HubSpot | 极高，尤其澳大利亚 | 拥有关键词库、国家/地区数据库、SEO 客户基础、品牌信任和报告工作流 |
| 国内/跨境 GEO 服务商 | 泓动数据、百付科技、百搜、趣搜、冠一、源易、智鸥、智搜未来、森辰、光引、Global Gravity、XOOER、百分点 Generforce 等 | 中到高 | 服务叙事和 GENO 类似，强调系统、知识库、投喂、分发、监测闭环 |

对我们最值得学习的竞品能力：

- Profound：AI visibility、引用、情感、竞品、Agent Analytics。
- Peec：把监测数据转成 source/content/action 优先级。
- OtterlyAI：日频监测、平台差异和 prompt research。
- Scrunch：Query API、source URL、persona、country、AI agent 访问。
- Gumshoe：跨模型、persona、非确定性采样方法论。
- Semrush/Ahrefs：Prompt database、国家库、SEO 数据迁移、客户报告体验。
- Writesonic/GEOly/AIPO：从监测到内容和工作流闭环。

对澳大利亚首发而言，最强竞争并不一定来自智推时代，而是 Semrush、Ahrefs、HubSpot 这类英语市场客户已经熟悉的工具。一款新 GENO SaaS 如果只给“AI visibility 分数”，很容易被这些平台的免费工具或现有模块覆盖。

## 9. 澳大利亚首发差异

澳大利亚首发与智推时代 PDF 中偏中国/全球泛化的流程相比，最大的不同在平台、信源、客户工作流和证据表达。

### 9.1 平台不同

国内 GEO 常围绕 DeepSeek、豆包、腾讯元宝、Kimi、文心、通义等平台叙事。澳大利亚应优先覆盖：

- Google AI Overviews / AI Mode。
- ChatGPT Search / ChatGPT browsing。
- Perplexity。
- Gemini。
- Microsoft Copilot。
- Claude 作为补充。

采样必须包含：

- market = AU。
- language = en-AU。
- city = Australia / Sydney / Melbourne / Brisbane / Perth / Adelaide。
- device = desktop/mobile。
- model_or_surface。
- collected_at。
- prompt_version。

### 9.2 信源不同

澳洲 AI 答案更可能引用或受以下信源影响：

| 信源层 | 澳洲代表 |
| --- | --- |
| 官方/监管 | gov.au、ACCC、ASIC、ATO、TGA、ACMA、州政府网站 |
| 品牌自有 | `.com.au` 官网、AU landing page、FAQ、shipping/returns、pricing AUD、store locator |
| 消费评价 | ProductReview.com.au、Google Reviews、Trustpilot、Reddit AU threads |
| 独立评测 | CHOICE、Canstar、Finder、WhistleOut、Mozo |
| 本地媒体 | ABC、SBS、The Guardian Australia、SMH/The Age、AFR、news.com.au |
| 视频/社媒 | YouTube、TikTok、Instagram、LinkedIn |
| B2B/软件 | G2、Capterra、GetApp、行业协会、案例页、白皮书 |

因此，澳洲 MVP 必须内置本地 source graph，而不是只做中文媒体投放清单。

### 9.3 客户工作流不同

澳大利亚客户更可能接受：

- 免费 AI visibility audit。
- 可导出的 evidence report。
- prompt/topic/source/action 四维看板。
- 与 GA4、Google Search Console、Shopify、WordPress、Webflow、HubSpot、Semrush/Ahrefs 工作流对接。
- 代理商多客户管理、白标报告、CSV/PDF 导出。

相对不容易接受：

- 不展示 raw response/citation 的黑箱分数。
- 无采样口径的“首屏曝光率保证”。
- 只强调“投喂大模型”，但无法解释 AI 引用和推荐变化。

## 10. 推荐技术落地路径

建议把澳大利亚首发 MVP 做成一个证据型平台，而不是先做大而全的内容自动化系统。

### 10.1 一期目标

一期只解决一个核心问题：

> 给澳大利亚品牌和代理商一份可审计的 AI 搜索可见性报告：AI 如何回答你的核心业务问题、是否提到你、是否推荐你、引用谁、竞品为什么出现、你下一步应该修补哪些内容和信源。

### 10.2 Step-by-step 路径

1. **建立 AU Market Profile**

配置 `market=AU`、`locale=en-AU`、`timezone=Australia/Sydney`、`currency=AUD`、重点城市、平台权重、信源分类和评分权重。所有平台、城市、语言、货币、评分逻辑都从 MarketProfile 读取，避免写死。

2. **生成行业 Prompt Pack**

每个项目先配置 100-200 个 prompt，覆盖品牌认知、品类推荐、城市场景、竞品对比、购买决策、评价口碑、价格、服务覆盖和替代方案。

示例：

```text
Best [category] in Australia
[brand] reviews Australia
[brand] vs [competitor] Australia
Is [brand] legit in Australia?
Where to buy [product] in Sydney?
Does [brand] ship to Australia?
```

3. **开发 AI Answer Runner**

优先采集 Google AI Overviews / AI Mode、ChatGPT、Perplexity、Gemini、Bing Copilot。每次采集保存 prompt、platform、market、city、language、answer、citations、screenshot、HTML snapshot、collector version、collected_at。

4. **做 Raw Evidence Store**

建立不可省略的证据表：`answer_run`、`raw_answer`、`citation`、`screenshot_asset`、`html_snapshot_asset`。所有评分和建议必须能追溯到原始回答。

5. **做英文答案解析器**

解析字段包括：brand_mentioned、brand_recommended、brand_rank、competitors_mentioned、competitor_rank、recommendation_strength、citation_sources、negative_mentions、price_mentions、availability_mentions、local_relevance。

6. **建立 AU Source Graph**

按 domain、source_type、topic、brand、competitor、citation_count、authority_level、local_relevance 存储引用源，识别哪些本地来源帮助竞品进入 AI 答案。

7. **计算 AU Visibility Score**

不要只给一个总分。至少拆成：

- Mention Rate。
- Recommendation Rate。
- Average Answer Position。
- Citation Rate。
- Local Relevance。
- Sentiment / Risk。
- Competitor Share of Answer。
- Source Quality。

8. **输出 Action Plan**

把缺口转成任务，而不是泛泛建议。任务类型包括：

- 新建/更新 AU landing page。
- 增加 FAQ 和 comparison 页面。
- 增加 Schema.org 结构化数据。
- 修复品牌事实不一致。
- 补充 AUD 价格、澳洲配送、售后和城市服务信息。
- 建立 ProductReview / Google Reviews / Reddit / CHOICE / 行业目录等信源策略。
- 更新帮助中心和案例页。

9. **生成客户报告**

报告必须包含：评分总览、平台明细、prompt 明细、原始答案摘要、引用源列表、竞品差距、行动任务、复测计划和证据附件。

10. **7/14/30 天复测**

每个任务完成后按固定采样方法复测，展示前后变化。复测数据必须继续保留 raw evidence，避免只展示趋势图。

### 10.3 一期不建议做的功能

一期不建议过早做：

- 数字人视频。
- 大规模自动媒体分发。
- 复杂知识本体。
- 完全自动化“投喂”。
- 多国家同时上线。
- 过度承诺排名保证。

原因是这些功能在早期消耗大，且很难快速证明客户价值。澳洲首发最重要的是建立可信的数据口径和可复盘证据链。

## 11. 建议 MVP 模块

| 优先级 | 模块 | 核心价值 |
| --- | --- | --- |
| P0 | Brand AI Visibility Audit | 输入品牌、域名、竞品、行业和地区，生成初始 AI 可见性报告 |
| P0 | Prompt/Topic Runner | 批量运行 AU English prompt pack |
| P0 | Raw Evidence Store | 保存原始回答、引用、截图、HTML 快照和采样元数据 |
| P0 | Answer Parser | 解析品牌提及、推荐、排名、竞品、引用和本地相关性 |
| P0 | Citation Graph | 识别 AI 引用了哪些 source、竞品在哪些 source 占优 |
| P1 | Competitor Benchmark | 支持 3-5 个竞品的 visibility、position、sentiment、citation overlap |
| P1 | Action Recommendations | 把内容和信源缺口转成可执行任务 |
| P1 | Report Export | 支持 PDF/CSV 导出，服务代理商交付 |
| P2 | Content Engine | 生成 FAQ、comparison、schema、landing page outline |
| P2 | Integrations | GA4、GSC、Shopify、WordPress、Webflow、HubSpot、Cloudflare |

## 12. 主要风险与待补证据

### 12.1 对智推时代的待补证据

| 问题 | 当前状态 | 建议补证 |
| --- | --- | --- |
| 公司成立与业务历史 | 工商成立 2025-05-12，传播材料有 2023 布局 | 区分团队历史和公司主体历史 |
| 客户数量和全球节点 | 多数来自公司自述 | 补客户名单、授权案例、办公地址、团队和合同主体 |
| 融资信息 | 有聚合页和媒体线索 | 补投资方公告、工商股权变更、融资新闻原发稿 |
| GENO 系统成熟度 | 公开材料主要是方法论 | 补 Demo、API 文档、试用入口、后台截图、采样数据 |
| 案例效果 | 多数为匿名/半匿名，缺少客户官方确认 | 补合同/验收、客户授权、Prompt、截图、后台数据、归因口径 |
| 评分方法 | 未公开 | 补指标公式、样本量、平台权重、复测周期和统计方法 |

### 12.2 对我们产品的技术风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| AI 答案非确定性 | 同一 prompt 在不同时间、地区、模型下答案不同 | 固定采样参数，保留原始证据，做多次采样和置信区间 |
| 平台采集不稳定 | UI 改版、反爬、验证码、登录态影响采集 | API 优先，浏览器自动化隔离，采集器版本化，允许手动补录 |
| Google AI 结果地理差异 | 澳洲城市结果不同 | 引入 city sampling 和 AU MarketProfile |
| 评分黑箱 | 客户不信任总分 | 拆分指标并可追溯到 raw answer/citation |
| 内容建议泛化 | LLM 给出空泛建议 | 每条建议绑定 evidence、source gap、expected lift、next check |
| 竞品数据误判 | 同名品牌、实体消歧错误 | 建品牌实体表、别名、域名、产品名和人工确认机制 |
| 过早做大而全 | 工程成本高，客户价值验证慢 | 一期聚焦 Audit、Runner、Evidence、Citation、Action、Report |

## 13. 最终判断

智推时代这个项目的核心价值在于，它抓住了 SEO 到 GEO 迁移中的一个真实问题：品牌在 AI 答案中的可见性、推荐权和事实解释权正在变成新的增长入口。它的 GENO 方法论从产品叙事上是完整的，也能映射到一套可实现的软件系统。

但从技术审计角度看，智推时代公开材料还停留在“能力描述和案例叙事”层。我们不能直接假设其 GENO 系统已经具备成熟 SaaS 所需的采集稳定性、评分可信度、知识图谱质量、内容分发闭环和客户可验收数据。后续如果要合作、对标或竞争，都应要求 Demo 和原始数据验证。

如果我们自己落地澳大利亚首发，建议不要复制国内 GEO 服务商的“全案投喂”话术，而是建立一个面向澳洲市场的 AI 搜索可见性证据平台：

```text
AU Market Profile
  -> Prompt Pack
  -> AI Answer Runner
  -> Raw Evidence Store
  -> Answer Parser
  -> Citation Graph
  -> Competitor Benchmark
  -> Action Plan
  -> Report Export
  -> 7/14/30 天复测
```

这条路线技术上可控、客户容易验收，也更符合澳大利亚英语市场对数据、证据和工具工作流的预期。后续再扩展内容生成、CMS 分发、GA4/GSC/Shopify/HubSpot 集成和多市场复制，会比一开始做大而全更稳。
