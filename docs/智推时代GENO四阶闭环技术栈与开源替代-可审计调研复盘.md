# 智推时代 GENO 四阶闭环技术栈与开源替代可审计调研复盘

生成日期：2026-06-08  
本地 PDF：`/home/ymm/ym/gz/20260608-geo/docs/智推时代-全球GEO业务介绍.pdf`  
PDF 摘录：`docs/research_sources/GENO四阶闭环技术栈开源替代/local_extracts/PDF_GENO四阶闭环与技术实现摘录.txt`  
外部网页快照目录：`docs/research_sources/GENO四阶闭环技术栈开源替代/raw_pages/`  
来源索引：`docs/research_sources/GENO四阶闭环技术栈开源替代/README.md`

## 1. 结论先行

智推时代 PDF 对“自研 GENO 系统”的公开披露属于产品能力和方法论层，而不是完整工程实现层。它明确披露了：

- 全栈自研 SaaS 平台 GENO。
- 四大产品矩阵：GEO 智能监测与舆情预警、用户意图深度分析与精准推荐、多模态内容智能生成与分发、智能知识图谱增强。
- “四阶闭环”方法论：星图决策引擎做意图分析，星穹智脑系统创建品牌知识库，星核创生平台做内容结构化、目标模型适配和平台分发，星枢监测系统检测结果并迭代新意图。
- 云端部署架构：智能监测层、意图分析层、多模态内容生成及知识图谱优化层。
- 技术实现口径：使用 GPT-4 等 LLM、定制提示工程、AI 平台交互数据、网站访问数据、第三方指标、内部 AI 可见性评分、内容模板、一键发布和 API 集成。

但 PDF 没有披露：

- 后端语言、前端框架、数据库、队列、向量库、图数据库、调度系统。
- AI 平台问答数据的采集方式，是官方 API、浏览器自动化、第三方 SERP/API，还是人工录入。
- “AI 可见性”评分公式、评测样本量、抽样频率、模型版本控制和地理位置控制。
- 知识图谱的本体设计、实体消歧、事实校验、引用来源评级方法。
- 自动分发覆盖哪些平台、是否有发布回执、失败重试、版本回滚和审批机制。

因此，本文把技术栈分为三类：

| 类型 | 含义 | 本文处理方式 |
| --- | --- | --- |
| PDF 明示技术 | PDF 直接写出的能力或技术词 | 作为事实引用 |
| 工程推断技术 | 要实现这些能力通常必须具备的系统组件 | 标记为“合理推断” |
| 开源替代方案 | 可用于复刻类似能力的开源/可自托管组件 | 标记许可和成熟度风险 |

最可行的开源复刻路径是：

> 用 `FastAPI + Next.js + PostgreSQL/pgvector + Playwright/Crawlee + LiteLLM + LlamaIndex/LangChain + Qdrant/Milvus + Neo4j/Jena + ClickHouse + Langfuse + promptfoo + Grafana/Superset/Metabase + Airflow/Temporal` 组成一个“AI 可见性监测、意图分析、知识库、内容生成、分发、复测”的 GEO SaaS。

这个开源方案可以覆盖 GENO 方法论的 70%-85% 工程骨架。差距主要不在组件，而在数据资产、平台采集稳定性、评分方法、模型适配经验、行业词库和信源网络。

## 2. PDF 中 GENO 四阶闭环的可审计证据

### 2.1 页码定位

| PDF 页码 | 内容 | 审计判断 |
| --- | --- | --- |
| 第 23 页 | 四大优势；技术内核称“全栈自研 SaaS 平台【GENO】” | 证明 GENO 是其核心产品叙事 |
| 第 24 页 | SaaS 产品矩阵：监测预警、意图分析、内容生成分发、知识图谱 | 证明四大模块 |
| 第 25 页 | 自研 GENO 系统“四阶闭环”方法论 | 证明闭环顺序 |
| 第 26 页 | 产品架构和技术实现 | 证明云端架构、LLM、Prompt、数据源、评分、发布/API |
| 第 27 页 | 星枢监测系统 Gen-Centric Sentinel | 证明监测与舆情能力 |
| 第 28 页 | 星图决策引擎 Gen-Carto Nexus | 证明意图分析能力 |
| 第 29 页 | 星核创生平台 Gen-Genesis Forge | 证明多模态生成和分发能力 |
| 第 30 页 | 星穹智脑系统 Gen-Cosmos CogniCore | 证明知识图谱增强能力 |

### 2.2 四阶闭环重构

PDF 第 25 页给出的闭环可以重构为：

1. 星图决策引擎：意图分析。
2. 星穹智脑系统：品牌知识库创建。
3. 星核创生平台：内容结构化、适配目标模型、平台分发。
4. 星枢监测系统：检测结果、迭代新意图。

工程上这不是一个线性内容生产流程，而是一个数据闭环：

```text
问题/关键词/场景词
  -> 意图聚类与机会识别
  -> 品牌事实库与信源图谱修补
  -> 内容生成、结构化、发布
  -> AI 平台与搜索平台复测
  -> 可见性评分、竞品对比、异常告警
  -> 新意图和新内容任务
```

这个闭环的核心不是“写文章”，而是持续回答三个问题：

- AI 是否能正确识别品牌实体？
- AI 是否在目标问题中推荐或引用该品牌？
- 哪些外部信源、内容结构、事实缺口导致推荐率变化？

## 3. GENO 技术栈拆解

### 3.1 总体架构拆解

PDF 第 26 页描述的整体架构可以拆成三层：

| PDF 描述 | 工程层解释 | 关键数据 |
| --- | --- | --- |
| 智能监测层，追踪 AI 平台问答数据 | AI 问答采集、SERP 采集、Prompt 采样、浏览器自动化/API 调用、结果解析 | prompt、平台、模型、地区、时间、回答、引用、排名、情绪 |
| 意图分析层，解析数据评估品牌可见性 | 意图聚类、关键词扩展、实体抽取、竞品对比、评分模型 | 查询簇、意图标签、品牌提及、竞品提及、引用域名、情感 |
| 多模态内容生成及知识图谱优化层 | RAG、品牌知识库、知识图谱、本体、内容生成、CMS/发布任务 | 品牌事实、产品属性、证据 URL、内容资产、发布记录 |

PDF 第 26 页描述的技术实现可以拆成六类：

| PDF 技术词 | 实际对应组件 | 是否 PDF 明示 |
| --- | --- | --- |
| GPT-4 等 LLM | 商业 LLM API 或自托管开源/开权模型 | 明示 GPT-4；未明示供应商组合 |
| 定制提示工程 | Prompt 模板、变量注入、版本管理、A/B 评测 | 明示 |
| AI 平台交互数据 | AI 回答采集器、Prompt Runner、平台适配器 | 明示数据源；未明示采集方式 |
| 网站访问数据 | Web analytics、日志、转化事件、页面抓取 | 明示数据源；未明示具体工具 |
| 第三方指标 | 搜索份额、SERP、反链、内容质量、社媒/评论数据 | 明示数据源；未明示供应商 |
| AI 可见性评分 | 指标计算、权重模型、趋势图、告警 | 明示评分；未明示公式 |

### 3.2 四大系统的技术栈推断

#### 星枢监测系统 Gen-Centric Sentinel

PDF 能力：

- 实时 AI 搜索排名。
- 负面舆情声量热力图与实时预警。
- 定位信源漏洞。
- 竞品 GEO 策略镜像系统。
- 品牌力 GEO 指数评估。
- 实时跟踪主流核心模型。

合理工程栈：

| 子能力 | 技术组件 | 数据产物 |
| --- | --- | --- |
| AI 平台问答采集 | Prompt Runner、LLM API 网关、浏览器自动化、请求队列 | `answer_run`、`raw_answer`、`citation` |
| 搜索排名监控 | SERP 抓取、搜索 API、排名任务调度 | `serp_result`、`rank_snapshot` |
| 舆情监控 | 情感分析、主题聚类、异常检测、热力图 | `sentiment_score`、`alert_event` |
| 信源漏洞扫描 | 引用域名分类、事实缺口检测、竞品信源对照 | `source_gap`、`missing_fact` |
| 竞品镜像 | 竞品品牌实体库、回答差异分析、提示词矩阵 | `competitor_mention`、`share_of_answer` |
| GEO 指数 | 归一化评分、趋势计算、分组看板 | `visibility_score_snapshot` |

开源替代重点：

- AI/API 统一：LiteLLM。
- 浏览器自动化：Playwright、Crawlee。
- 通用抓取：Scrapy。
- 搜索聚合基线：SearXNG。
- 排名监控原型：SerpBear。
- 调度：Airflow、Temporal。
- 指标存储：ClickHouse、PostgreSQL。
- 看板：Grafana、Metabase、Superset。
- LLM 观察与 Prompt 追踪：Langfuse。

#### 星图决策引擎 Gen-Carto Nexus

PDF 能力：

- 关键词搜索链意图解析。
- 预测行业意图迁移趋势，生成动态需求图谱。
- 按意图调整知识库结构，实时适配内容。
- 跨平台用户画像融合。
- 输出高潜场景词库、内容痛点及信源权重策略。

合理工程栈：

| 子能力 | 技术组件 | 数据产物 |
| --- | --- | --- |
| 关键词扩展 | 搜索日志、AI 问题采集、embedding 相似扩展、LLM 改写 | `query_variant` |
| 意图分类 | 规则 + embedding 聚类 + LLM 分类 | `intent_cluster`、`intent_label` |
| 趋势预测 | 时间序列、滑动窗口、异常检测 | `intent_trend` |
| 动态需求图谱 | 查询-意图-品牌-内容-信源关系图 | `demand_graph` |
| 用户画像融合 | 来源、地区、平台、场景、转化阶段标签 | `audience_segment` |
| 信源权重策略 | 引用频率、权威性、平台偏好、竞品覆盖 | `source_weight` |

开源替代重点：

- 向量与语义：Sentence Transformers。
- 主题聚类：BERTopic。
- NLP 基础处理：spaCy。
- 关键词提取：KeyBERT。
- 传统机器学习：scikit-learn。
- 检索：OpenSearch、Meilisearch。
- LLM 应用编排：LangChain、LlamaIndex。

#### 星穹智脑系统 Gen-Cosmos CogniCore

PDF 能力：

- 权威数据库搭建。
- 动态本体构建。
- 技术/政策模拟器。
- 信源漏洞扫描仪。
- 信源组合定价模型。
- 自动梳理行业知识关系。

合理工程栈：

| 子能力 | 技术组件 | 数据产物 |
| --- | --- | --- |
| 品牌知识库 | 文档解析、事实抽取、证据绑定、版本管理 | `brand_fact`、`evidence_url` |
| 权威数据库 | 官方网站、新闻稿、报告、产品页、FAQ、评论源 | `trusted_source` |
| 动态本体 | 行业概念、实体类型、属性、关系约束 | `ontology_class`、`relation_type` |
| 知识图谱 | 实体消歧、关系抽取、图查询 | `entity`、`relation` |
| RAG | 文档分块、embedding、向量检索、上下文组装 | `document_chunk`、`embedding` |
| 模拟器 | 规则引擎、政策/技术约束问答、场景推演 | `scenario_test` |
| 信源组合定价 | 优化求解、预算约束、边际收益估计 | `source_plan` |

开源替代重点：

- 结构化事实库：PostgreSQL。
- 向量检索：pgvector、Qdrant、Milvus。
- 知识图谱：Neo4j Community、Apache Jena、RDFLib、Microsoft GraphRAG。
- 文档解析：Apache Tika、Unstructured。
- RAG 编排：LlamaIndex、LangChain。
- 结构化数据规范：Schema.org、Google structured data 指南。
- 优化求解：Google OR-Tools。

#### 星核创生平台 Gen-Genesis Forge

PDF 能力：

- 自动生成文本、图像、音频、视频等多模态内容。
- 自动匹配高权重信源。
- 勾选发布信源后自动分发。
- 数字人播报与虚拟场景生成。
- 头部客户内容脱敏入库，累积数字资产。
- 生成行业内容公式。

合理工程栈：

| 子能力 | 技术组件 | 数据产物 |
| --- | --- | --- |
| 文本生成 | Prompt 模板、RAG、事实校验、审批流 | `content_draft` |
| 目标模型适配 | 按平台拆分内容结构、引用格式、问答格式 | `platform_content_variant` |
| 多模态生成 | 图像、视频、音频、TTS、ASR、数字人 | `media_asset` |
| 高权重信源匹配 | 信源评级、内容类型映射、预算与发布计划 | `distribution_plan` |
| 自动分发 | CMS、API 连接器、任务队列、回执 | `publish_task` |
| 内容资产沉淀 | 脱敏、标签、行业模板、复用评分 | `content_formula` |

开源替代重点：

- LLM 访问层：LiteLLM。
- 自托管 LLM：vLLM、Ollama、llama.cpp、Hugging Face Transformers。
- 开权模型：Qwen、DeepSeek。注意“开权模型”不必然等于 OSI 严格意义的开源 AI。
- 图像/视频生成：Diffusers、ComfyUI。
- 语音识别：Whisper。
- TTS：Piper。
- 数字人/口型同步研究项目：Wav2Lip、SadTalker。生产商用前必须单独核查模型权重和许可证。
- CMS：Strapi、Directus。
- 自动化流程：n8n、Node-RED、Huginn、Airflow、Temporal。
- 对象存储：MinIO。

## 4. 每类技术的开源替代矩阵

### 4.1 AI 平台采集与监控

| GENO 能力 | 可替代开源组件 | 推荐组合 | 技术注意事项 |
| --- | --- | --- | --- |
| 实时跟踪主流核心模型 | LiteLLM、Langfuse | LiteLLM 统一调用，Langfuse 记录 prompt、模型、成本、结果 | 只适合有 API 的模型；网页型 AI 搜索仍需浏览器自动化或人工采样 |
| AI 搜索排名检测 | Playwright、Crawlee、SerpBear、SearXNG | Playwright/Crawlee 采集，SerpBear 做传统搜索排名原型，SearXNG 做搜索聚合基线 | AI 回答有随机性，必须记录模型、地区、时间、账号状态、Prompt 版本 |
| AI 爬虫监控 | Scrapy、Crawlee、Playwright | 静态网页用 Scrapy，动态页面用 Playwright/Crawlee | 页面反爬、验证码、登录态、UI 改版会影响稳定性 |
| 负面舆情预警 | spaCy、Sentence Transformers、BERTopic、ClickHouse、Grafana | 文本入库后做情绪/主题/异常检测，Grafana 告警 | 中文和英文需要分语言模型；不能只靠单个情感模型 |
| 竞品 GEO 策略镜像 | LlamaIndex/LangChain、OpenSearch、Qdrant、Neo4j | 把竞品回答、引用源、内容结构转成对比图谱 | “镜像”实际是观测和归纳，不能证明竞品真实策略 |

### 4.2 意图分析与推荐

| GENO 能力 | 可替代开源组件 | 推荐组合 | 技术注意事项 |
| --- | --- | --- | --- |
| 关键词搜索链意图解析 | Sentence Transformers、BERTopic、KeyBERT、spaCy | embedding 聚类 + KeyBERT 提取关键词 + LLM 命名意图 | 必须保留原始查询，避免聚类标签不可审计 |
| 行业意图迁移趋势预测 | scikit-learn、ClickHouse、Grafana | 按周/月聚合意图簇，做趋势和异常检测 | 早期样本少，不适合过度建模 |
| 动态需求图谱 | Neo4j、Apache Jena、RDFLib、GraphRAG | 先用 property graph，复杂语义再引入 RDF/OWL | 图谱维护成本高，MVP 不要一次性追求完整本体 |
| 内容痛点输出 | LangChain/LlamaIndex、promptfoo | RAG 检索回答缺口，再用评测集校验建议质量 | LLM 建议必须绑定证据 URL 和样本回答 |
| 信源权重策略 | ClickHouse、Neo4j、OR-Tools | 引用频率 + 权威等级 + 预算约束 + 竞品差距 | 权重是策略模型，不是客观真相，需要人工校准 |

### 4.3 知识库、RAG 与知识图谱

| GENO 能力 | 可替代开源组件 | 推荐组合 | 技术注意事项 |
| --- | --- | --- | --- |
| 品牌知识库创建 | PostgreSQL、pgvector、Qdrant、LlamaIndex | PostgreSQL 管事实，pgvector/Qdrant 管向量，LlamaIndex 管索引和检索 | 品牌事实必须带来源、时间、责任人、有效期 |
| 权威数据库搭建 | Apache Tika、Unstructured、MinIO、PostgreSQL | 文件进 MinIO，Tika/Unstructured 解析，结构化入库 | PDF、网页、表格解析质量决定 RAG 上限 |
| 动态本体构建 | Neo4j、Apache Jena、RDFLib | 行业初期用 Neo4j，强语义约束用 Jena/RDFLib | 本体不是越复杂越好，要服务于问答和发布决策 |
| 信源漏洞扫描 | OpenSearch、Qdrant、Neo4j、ClickHouse | 统计 AI 引用和搜索结果里缺失/冲突事实 | 需要区分“没有被引用”和“事实不存在” |
| 技术/政策模拟器 | LlamaIndex、LangChain、promptfoo、Ragas | 建场景测试集，RAG 生成答案，再用 Ragas/promptfoo 评测 | 这属于决策支持，不应自动当成最终事实 |

### 4.4 内容生成、多模态与分发

| GENO 能力 | 可替代开源组件 | 推荐组合 | 技术注意事项 |
| --- | --- | --- | --- |
| GPT-4 等 LLM 生成 | LiteLLM、vLLM、Ollama、llama.cpp、Transformers、Qwen、DeepSeek | SaaS 初期用 LiteLLM 接商业模型；成本优化阶段引入 vLLM + Qwen/DeepSeek | GPT-4 不是开源；开权模型能力和许可证要逐项核对 |
| 定制提示工程 | Langfuse、promptfoo、LangChain | Prompt 模板版本化，promptfoo 做回归评测，Langfuse 追踪线上效果 | 不要把 Prompt 存在代码散落处 |
| 内容结构化 | LlamaIndex、LangChain、Schema.org | 从知识库生成 FAQ、HowTo、Product、Article、Review 等结构 | 结构化数据只提高可理解性，不保证 AI 引用 |
| 图像/视频/音频生成 | Diffusers、ComfyUI、Whisper、Piper | 文本和图片可先做 MVP；视频/数字人作为二期 | 多模态质量、成本和审核工作量大 |
| 数字人播报/虚拟场景 | Wav2Lip、SadTalker | 仅作研究原型或内部演示 | 商用许可证、肖像授权和模型质量需要单独核查 |
| 一键发布/API 集成 | Strapi、Directus、n8n、Node-RED、Huginn、Airflow/Temporal | CMS 管内容，workflow 管发布任务，API adapter 管渠道 | n8n 等部分工具不是 OSI 严格开源，需核查商业使用许可 |

### 4.5 AI 可见性评分与看板

| GENO 能力 | 可替代开源组件 | 推荐组合 | 技术注意事项 |
| --- | --- | --- | --- |
| 品牌力 GEO 指数 | ClickHouse、PostgreSQL、Metabase/Superset | 原始事件进 ClickHouse，指标快照进 PostgreSQL，BI 展示 | 必须公开公式版本，否则分数不可审计 |
| 回答质量评估 | Ragas、promptfoo、LLM-as-judge、人工复核 | 自动评测筛查，人工复核关键客户 | LLM-as-judge 会偏置，需要黄金样本 |
| Prompt/模型观测 | Langfuse、OpenTelemetry | Langfuse 观测 LLM 调用，OpenTelemetry 观测服务链路 | LLM 调用日志要脱敏 |
| 实时预警 | Prometheus、Grafana、ClickHouse | 指标阈值 + 异常检测 + 告警通道 | 告警要区分采集失败和业务下降 |
| 产品分析 | PostHog、Matomo | 记录用户操作、内容审批、看板访问 | 这是 SaaS 运营层，不是 AI 模型层 |

一个可审计的 AI 可见性评分可以先用如下结构：

| 指标 | 建议权重 | 说明 |
| --- | --- | --- |
| 品牌提及率 | 25% | 目标 Prompt 中品牌被提及的比例 |
| 推荐排名/位置 | 15% | 被推荐时的位置，第一推荐高于泛提及 |
| 答案占有率 | 15% | 品牌相关内容在回答中的信息量占比 |
| 引用质量 | 15% | 是否引用官方、权威第三方、行业媒体、社区评价等 |
| 情绪与准确性 | 15% | 正负面、事实错误、过时信息 |
| 新鲜度与一致性 | 10% | 跨平台事实是否一致，内容是否过期 |
| 竞品差距 | 5% | 与竞品在同 Prompt 下的相对表现 |

公式应版本化，例如：

```text
visibility_score_v1 =
  0.25 * mention_rate
+ 0.15 * rank_score
+ 0.15 * answer_share
+ 0.15 * citation_quality
+ 0.15 * sentiment_accuracy
+ 0.10 * freshness_consistency
+ 0.05 * competitor_gap
```

### 4.6 SaaS 工程基础设施

| SaaS 能力 | 可替代开源组件 | 推荐组合 | 技术注意事项 |
| --- | --- | --- | --- |
| 前端工作台 | Next.js | Next.js + 表格/看板组件 | GENO 类产品核心是密集运营界面，不适合营销页式 UI |
| 后端 API | FastAPI | FastAPI + PostgreSQL + OpenAPI | Python 生态适合 NLP/RAG，但高并发采集要拆 worker |
| 主数据库 | PostgreSQL | PostgreSQL + pgvector | 早期可以少引一个向量库 |
| 缓存/队列 | Valkey、Redis | 优先 Valkey；Redis 需核查新许可 | Redis 许可已变化，严格开源场景优先 Valkey |
| 身份和多租户 | Keycloak、PostgreSQL RLS | Keycloak 管认证，业务库管租户隔离 | B2B SaaS 必须一开始设计租户隔离 |
| 对象存储 | MinIO | 存 PDF、网页快照、图片、视频、导出报表 | MinIO 使用 AGPLv3，商用部署要核查义务 |
| 容器和部署 | Docker、Kubernetes、Traefik | 单机 Docker Compose 起步，后续 K8s | MVP 不应过早复杂化 |
| 数据同步 | Airbyte | 拉取第三方数据源、CRM、analytics | 许可证和 connector 质量需核查 |

## 5. 开源复刻 GENO 的推荐落地架构

### 5.1 MVP 架构

```text
Next.js 控制台
  -> FastAPI Backend
      -> PostgreSQL: 租户、品牌、Prompt、内容、评分
      -> pgvector/Qdrant: 文档向量
      -> MinIO: 原始网页、PDF、图片、导出件
      -> ClickHouse: 采集事件、回答事件、指标明细
      -> LiteLLM: 商业 LLM 和开权模型统一调用
      -> LlamaIndex/LangChain: RAG、工具调用、内容生成链
      -> Playwright/Crawlee/Scrapy: 搜索和网页采集
      -> Airflow/Temporal: 定时采样、发布、复测工作流
      -> Langfuse + promptfoo: Prompt 追踪和回归测试
      -> Grafana/Metabase/Superset: 指标看板
```

### 5.2 MVP 必做模块

1. 品牌和竞品配置。
2. 市场、语言、平台、Prompt 矩阵配置。
3. AI 回答采集与原始记录留存。
4. 品牌提及、竞品提及、引用 URL、情绪、事实错误抽取。
5. AI 可见性评分 v1。
6. 品牌事实库和证据 URL 管理。
7. RAG 内容建议和人工审批。
8. 发布任务记录，不急于做所有渠道自动发布。
9. 复测闭环：发布前后同一 Prompt 集合对比。
10. 审计日志：每次采集、生成、审批、发布、评分都可追溯。

### 5.3 二期增强模块

1. 知识图谱和动态本体。
2. 信源权重策略和预算优化。
3. 多模态内容生成。
4. 数字人播报。
5. 竞品 GEO 策略镜像。
6. 自动化分发到更多外部平台。
7. 行业模板和内容公式沉淀。
8. 客户级自定义评分模型。

## 6. 技术尽调清单

如果要验证智推时代 GENO 系统的真实技术成熟度，建议要求其现场演示或提供以下证据：

| 尽调问题 | 为什么重要 |
| --- | --- |
| 是否可以展示从 Prompt 配置到 AI 平台回答采集的完整链路？ | 验证监测不是人工截图或半人工交付 |
| 是否记录模型版本、地区、时间、账号状态、采样次数？ | AI 回答波动大，没有这些字段就不可复盘 |
| “AI 可见性”评分公式是什么？是否版本化？ | 没有公式就无法比较优化前后 |
| 是否保存原始回答、引用链接和截图？ | 防止只展示加工后的结论 |
| 知识库如何绑定证据 URL？过期事实如何处理？ | GEO 的核心是事实一致性 |
| 内容生成是否有事实校验和人工审批？ | 降低幻觉和错误分发 |
| 自动分发支持哪些平台？是否有发布回执和失败重试？ | 验证一键发布是真集成还是流程话术 |
| 竞品镜像的数据来源是什么？ | 避免把推断误认为竞品真实策略 |
| 是否有 Prompt 回归测试集？ | 模型和策略迭代需要可比较 |
| 是否能导出客户项目的全量审计日志？ | B2B SaaS 验收必须可审计 |

## 7. 与澳大利亚首发产品的关系

如果我们用这套开源替代方案做澳大利亚首发，核心架构不需要变，变的是采集适配器、信源图谱和评测 Prompt：

| 模块 | 澳洲需要调整的技术点 |
| --- | --- |
| 平台采集 | Google Search/AI Mode、ChatGPT Search、Perplexity、Bing/Copilot、Gemini 的英文澳洲区采样 |
| 地区控制 | prompt 中显式加入 Australia、city/state、AUD、澳洲监管/行业词；采集任务记录 `market=AU`、`language=en-AU` |
| 信源图谱 | 增加 `.com.au` 官网、Google Business Profile、ProductReview、CHOICE、澳洲主流媒体、gov.au、行业协会、Reddit 澳洲社区 |
| 内容模板 | 使用澳洲英语、澳元、当地配送/售后/认证/门店/服务范围字段 |
| 评分权重 | 本地权威信源和评论平台权重高于泛全球内容 |
| 复测机制 | 同一 Prompt 在 Sydney/Melbourne/Brisbane 等地区配置中做对比 |

也就是说，GENO 类系统的产品流程不必推翻，但澳洲版本必须在数据结构中原生支持：

- `market`
- `locale`
- `platform`
- `geo_location`
- `source_type`
- `citation_country`
- `regulatory_or_authority_source`
- `local_review_source`

## 8. 最终判断

智推时代 PDF 里的 GENO 四阶闭环，从工程角度看是一个合理的 GEO SaaS 闭环：

```text
意图发现 -> 知识库/图谱修补 -> 内容生成与分发 -> AI 可见性监测 -> 意图再发现
```

这套方法论可以用开源组件复刻出可运行的 MVP。真正难点不是“有没有开源替代”，而是：

1. 能否稳定采集 AI 平台和搜索平台结果。
2. 能否建立可审计的 Prompt 样本集和评分公式。
3. 能否把品牌事实、信源证据、内容发布、复测结果串成闭环。
4. 能否沉淀行业词库、信源权重和内容模板。
5. 能否在客户交付中证明优化前后的因果关系，而不是只展示单次截图。

从技术落地角度，建议我们不要试图一次性复刻 PDF 中全部“星枢、星图、星核、星穹”的完整叙事，而是先做：

1. 星枢监测的最小闭环。
2. 星图意图分析的轻量版本。
3. 星穹品牌事实库和证据库。
4. 星核内容建议和人工审批。
5. 复测评分和报告导出。

这五件事跑通后，再做知识图谱、多模态、数字人、自动分发和信源组合定价。
