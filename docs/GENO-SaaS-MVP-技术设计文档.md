# GENO SaaS MVP 技术设计文档

> **状态说明（2026-06-09）**：本文保留为通用 GENO SaaS MVP 技术参考。当前工程交付以 [GENO-SaaS-AU-首发技术落地路径](GENO-SaaS-AU-首发技术落地路径.md)、[PROJECT-PLAN](../PROJECT-PLAN.md) 和 [ARCHITECTURE](../ARCHITECTURE.md) 为准。
>
> **AU 首发覆盖规则**：澳大利亚首发不是先做完整“知识库 -> 内容生成 -> 分发”闭环，而是先做 **Evidence-first AI Search Visibility MVP**：`AU MarketProfile -> Prompt Pack -> AI Answer Runner -> Raw Evidence Store -> Answer Parser -> Citation Graph -> AUVisibilityScore -> Competitor Benchmark -> Evidence Report -> 复测`。知识库、内容生成、自动分发和复杂集成整体后移到 P2，避免旧通用方案误导首发排期。

## 1. 背景与目标

GENO SaaS MVP 面向品牌方和 GEO 交付团队，目标是把 GEO 服务从人工调研型交付升级为可配置、可监测、可复盘的 SaaS 工作台。

MVP 不承诺直接训练第三方大模型，也不承诺全平台实时可控排名。MVP 的可落地目标是：

- 持续采集主流 AI 平台在目标问题下的回答表现。
- 量化品牌在 AI 答案中的可见性、推荐度、信息准确性和舆情风险。
- 建立品牌知识库，把客户资料整理为可复用的结构化事实资产。
- 基于知识库生成 GEO 内容建议和待发布内容。
- 记录内容分发动作，并追踪后续 AI 回答变化。
- 形成周报、月报和优化任务闭环。

澳大利亚首发的可落地目标收敛为：

- 生成 100 条澳洲英文 prompt（上限 200），绑定 intent、city、prompt_version。
- 先跑通 Perplexity Sonar 与 OpenAI web search 两条稳定 API 证据链。
- 独立做 Google AIO / AI Mode spike，输出 pass/fail gate；未过闸时只进入 limited coverage 附录。
- 保存原始回答、引用、截图/HTML、`answer_present`、`surface_triggered`、`sample_index`、`raw_payload_hash`。
- 生成 `AUVisibilityScore`、`Citation Graph`、`Competitor Benchmark` 和可审计 Evidence Report。
- 从 P0 开始建立 `AuditEvent / EvidenceLink / ScoreContribution / ReportExport`，保证任意报告数字可追溯、可解释、可复盘。

## 2. MVP 范围

### 2.1 一期覆盖平台

通用方案建议一期优先覆盖 3 类平台：

- 国内 AI 问答平台：DeepSeek、豆包、Kimi、腾讯元宝、百度文小言，先以人工账号加浏览器自动化/半自动采集为主。
- 海外 AI 问答平台：ChatGPT、Perplexity、Gemini，优先使用官方 API 或合规检索能力。
- 搜索与信源平台：官网、新闻稿、百科/媒体页面、Reddit/Quora/YouTube/小红书/知乎等作为信源记录，不在一期做全自动发布。

通用方案一期重点是“监测 + 分析 + 知识库 + 内容工作台 + 分发记录”，不是全渠道自动营销系统。

AU 首发覆盖以 `MarketProfile=AU` 为准：

| 层级 | 平台 / surface | 工程处理 |
| --- | --- | --- |
| P0a stable | Perplexity Sonar、OpenAI web search / ChatGPT Search | 先打通稳定 answer/citation/evidence 全链路，进入主报告分母 |
| P0b spike | Google AI Overviews、Google AI Mode | 独立验证浏览器、第三方 SERP API、人工补录路径，过健康闸门后再进入主评分 |
| P1/P2 | Gemini、Bing Copilot、Claude、YouTube、Reddit、ProductReview 等 | 市场验证后扩展，不阻塞 AU 首发 |
| 不在 AU 首发 | DeepSeek、豆包、Kimi、腾讯元宝、百度文小言等国内平台 | 仅作为通用 GENO 能力参考，不进入 AU P0 |

### 2.2 一期不做

- 不做对第三方 AI 模型的直接训练。
- 不做大规模账号池、绕过验证码、规避平台风控。
- 不做所有社媒平台的一键发布。
- 不做强归因的广告投放 ROI 系统。
- 不做完整舆情系统，只做和 GEO 问答结果相关的负面风险监测。

## 3. 可行技术落地路径

### 阶段 0：基础配置和样本体系（AU 首发 = M1）

建立租户、品牌、竞品、平台、关键词、问题集、目标信源等基础配置。交付团队先用行业模板初始化 50-200 个问题，覆盖品牌词、品类词、场景词、对比词、负面词和转化词。

AU 首发固定为：1 个行业模板、100 条澳洲英文 prompt（上限 200）、3-5 个竞品、Australia/Sydney/Melbourne/Brisbane 城市样本，所有平台、城市、语言、权重从 `MarketProfile` 读取。

输出物：

- 品牌/竞品档案。
- GEO 问题集。
- 信源清单。
- 基线采集计划。

### 阶段 1：AI 回答采集和基线评估（AU 首发 = M2a/M2b）

按平台和问题集定时采集 AI 回答。每次采集保存原始问题、回答文本、引用链接、截图或 HTML 证据、模型/平台版本、采集时间、地区和语言。

通过 LLM + 规则解析回答：

- 是否提及品牌。
- 是否推荐品牌。
- 排名位置。
- 是否提及竞品。
- 是否存在负面描述。
- 信息是否错误或过期。
- 引用源是否来自目标信源。

输出物：

- 品牌 AI 可见性基线。
- 竞品对比表。
- 风险问题清单。
- 信源缺口清单。

AU 首发采集拆成两条路线：

- **P0a Stable Evidence Chain**：Perplexity Sonar + OpenAI web search，默认每 prompt/platform/geo 重复采样 k=3。
- **P0b Google Spike**：Google AIO / AI Mode 用 30 条高意图 prompt、Australia + Sydney、k=2 验证浏览器/第三方/人工路径；不通过健康闸门则不进入主评分分母。

采集结果必须原生记录 `answer_present` 与 `surface_triggered`，用于区分“界面没触发”和“触发后没提品牌”。

### 阶段 2：信源图谱、竞品差距和证据报告（AU 首发 = M3/M4/M5）

AU 首发不先做内容生成，而是先把证据转成可审计报告：

- Answer Parser：解析品牌提及、推荐、排名、竞品、引用、情绪和澳洲本地相关性。
- AUVisibilityScore：使用 `au_visibility_v1`，公式版本化，展示 Trigger/Mention/Recommendation 双分母。
- ScoreContribution：每个总分、平台分、城市分、intent 分都保留子指标贡献、权重、分母、正负证据和局限。
- Citation Graph：统计 AI 引用源、竞品独占信源、source gap、澳洲本地信源缺失。
- Competitor Benchmark：对比 3-5 个竞品的 mention/recommend/position/citation overlap/local relevance。
- Evidence Report Export：导出方法说明、Google spike 结论、审计摘要、分数解释包、原始证据附录。

### 阶段 3：品牌知识库和内容资产整理（AU 首发 = P2）

导入客户官网、FAQ、产品资料、案例、新闻稿、资质、白皮书、报告、社媒素材和音视频脚本。系统自动抽取实体、事实、卖点、证明材料和适用场景，人工审核后进入知识库。

知识库不是单纯向量库，还需要保留结构化事实：

- 品牌事实：名称、定位、行业、服务区域、资质。
- 产品事实：产品线、功能、价格区间、适用人群。
- 证明事实：客户案例、奖项、认证、媒体报道、数据来源。
- 对比事实：和竞品的差异点。
- 禁用口径：不能生成或不能外发的表述。

输出物：

- 品牌事实库。
- 内容素材库。
- 证据链和引用源映射。
- 禁用口径库。

### 阶段 4：GEO 内容生成和审核（AU 首发 = P2）

系统基于问题缺口、信源缺口和知识库生成内容建议，包括 FAQ、对比稿、行业白皮书段落、新闻稿、长图文、短视频脚本、问答内容、社区帖子草稿等。

所有生成内容必须走审核：

- 事实校验：是否有知识库证据支持。
- 品牌审核：是否符合品牌口径。
- 合规审核：是否涉及虚假宣传、绝对化用语、医疗/金融/教育敏感表述。
- 发布审核：是否适合目标渠道。

输出物：

- 内容建议清单。
- 待审核内容。
- 已审核内容。
- 发布任务。

### 阶段 5：分发记录和效果追踪（AU 首发 = P2/P1 复测）

一期以“分发任务管理 + 人工发布回填”为主。每个分发任务记录目标信源、内容版本、发布时间、发布 URL、负责人和审核状态。后续监测任务自动关联发布时间前后的 AI 回答变化。

输出物：

- 分发台账。
- 信源覆盖变化。
- AI 回答变化趋势。
- 周报/月报。

### 阶段 6：闭环优化（AU 首发 = P1 复测）

系统基于监测结果自动生成下一轮优化建议：

- 哪些问题仍未提及品牌。
- 哪些问题被竞品压制。
- 哪些回答存在错误或负面。
- 哪些信源被 AI 引用但内容缺失。
- 哪些已发布内容可能产生正向变化。

输出物：

- 优化任务池。
- 迭代效果报告。
- 客户可视化报表。

## 4. 总体架构

```text
用户层
  品牌客户门户 / 交付运营后台 / 管理后台

应用层
  项目管理 / 问题集管理 / AI监测 / 可见性分析 / Citation Graph / Evidence Report / 复测
  P2: 知识库 / 内容工作台 / 分发任务 / 报表预警

智能服务层
  LLM网关 / 回答解析器 / 意图分类器 / 信源图谱 / 竞品对标 / 评分引擎 / 分数解释包
  P2: 事实抽取器 / 内容生成器 / 风险审核器

数据层
  PostgreSQL / 对象存储 / 向量库 / 图存储 / 任务队列 / 审计日志 / ReportExport 快照

采集与集成层
  AI平台API / 浏览器自动化采集 / 搜索抓取 / 网站导入 / 文件导入 / 第三方指标导入
```

## 5. 核心模块设计

### 5.1 租户与项目管理

支持多租户，每个租户可创建多个 GEO 项目。项目绑定品牌、行业、目标市场、目标平台、竞品和问题集。

关键能力：

- 租户隔离。
- 项目看板。
- 角色权限。
- 客户可见范围控制。

### 5.2 问题集与意图管理

问题是 GEO 监测的最小单元。问题集按意图分类管理。

建议一期内置意图类型：

- 品牌认知：某品牌怎么样。
- 品类推荐：某类产品/服务推荐。
- 场景需求：某人群/场景适合什么方案。
- 竞品对比：A 和 B 哪个好。
- 购买决策：价格、效果、适用人群、服务范围。
- 负面风险：投诉、骗局、差评、安全性。
- 权威背书：资质、案例、奖项、媒体报道。

### 5.3 AI 监测采集

采集任务按平台、问题、地区、语言、频率执行。

采集结果必须保留证据：

- 原始 prompt。
- 原始 answer。
- 引用链接。
- 平台名称。
- 模型名称或平台版本。
- 采集时间。
- 地区、语言、账号类型。
- 截图或 HTML 快照。
- 采集状态和错误信息。
- `answer_present` 与 `surface_triggered`。
- `sample_index / sample_size`。
- `collector_backend_id / collector_version / access_method`。
- `raw_payload_hash`。

对于没有稳定 API 的平台，一期采用半自动采集或受控浏览器自动化，并设置频率限制和人工复核。

### 5.4 AI 可见性分析

采集完成后进入分析流水线：

1. 文本清洗和结构化。
2. 品牌、竞品、产品、实体识别。
3. 推荐语义判断。
4. 排名位置解析。
5. 情感和风险识别。
6. 引用源归类。
7. 信息准确性校验。
8. 生成评分和诊断。

### 5.5 评分引擎

一期建议使用可解释的加权评分，不直接使用黑盒总分。

单条回答评分：

```text
AnswerScore =
  MentionScore * 0.20 +
  RecommendationScore * 0.25 +
  PositionScore * 0.15 +
  AccuracyScore * 0.15 +
  SourceScore * 0.15 +
  SentimentScore * 0.10
```

字段定义：

- MentionScore：品牌是否被提及，0 或 100。
- RecommendationScore：是否被明确推荐，0/50/100。
- PositionScore：排名位置，第一名 100，第二名 80，第三名 60，提及但靠后 30，未出现 0。
- AccuracyScore：事实准确率，人工标注或自动校验。
- SourceScore：是否引用目标权威信源。
- SentimentScore：正向 100，中性 60，负面 0。

项目级可见性分数：

```text
ProjectVisibilityScore =
  sum(AnswerScore * IntentWeight * PlatformWeight) / sum(IntentWeight * PlatformWeight)
```

权重需要在后台可配置，并在报表中展示，避免客户无法理解分数来源。

AU 首发使用 `au_visibility_v1`，替代上述通用公式作为 P0 公式：

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

AU 评分必须额外满足：

- 平台权重 P0 口径：Google 45 / ChatGPT 30 / Perplexity 25，但 Google 进入主分母必须通过 P0b 健康闸门。
- 区分 Trigger Rate、Mention Rate、Recommendation Rate，不能把 Google AIO 未触发误算为品牌缺失。
- 每个 `VisibilityScoreSnapshot` 必须有关联的 `ScoreContribution` 解释包。
- 历史分数必须按旧公式版本可复算。

### 5.6 知识库

知识库分为结构化事实库、文档库和向量检索库。

结构化事实库用于事实校验和内容生成约束。文档库保存原始材料。向量库用于语义检索和 RAG。

知识库条目需要状态：

- draft：系统抽取或人工录入，未审核。
- approved：已审核，可用于生成。
- deprecated：过期，不再用于生成。
- forbidden：禁用口径，不得生成。

### 5.7 内容工作台

内容工作台根据监测缺口生成内容任务。

内容类型：

- FAQ。
- 品牌介绍。
- 产品介绍。
- 竞品对比。
- 行业科普。
- 案例稿。
- 新闻稿。
- 社区问答。
- 短视频脚本。
- 白皮书片段。

内容生成必须关联：

- 目标问题。
- 目标平台。
- 目标信源。
- 使用的知识库事实。
- 风险检查结果。
- 审核人。

### 5.8 分发任务

一期不强求全自动发布。系统提供发布任务流：

- 选择内容版本。
- 选择目标信源。
- 指派负责人。
- 记录发布链接。
- 记录发布时间。
- 关联后续监测结果。

后续可逐步接入官网 CMS、微信公众号、小红书、知乎、YouTube、LinkedIn 等平台 API。

### 5.9 报表与预警

报表分为客户报表和运营报表。

客户报表：

- 总体 AI 可见性趋势。
- 各平台表现。
- 重点问题表现。
- 竞品对比。
- 负面风险。
- 本期内容动作和效果。
- 下期优化建议。

运营报表：

- 采集成功率。
- 分析成功率。
- 内容生产效率。
- 审核通过率。
- 发布完成率。
- 任务逾期情况。

预警规则：

- 重点问题品牌未出现。
- 负面回答出现。
- 竞品排名超过品牌。
- 核心事实错误。
- 采集连续失败。

## 6. 关键数据模型

### 6.1 Tenant

```text
id
name
status
created_at
updated_at
```

### 6.2 Project

```text
id
tenant_id
brand_id
name
industry
markets
languages
status
created_at
updated_at
```

### 6.3 Brand

```text
id
tenant_id
name
aliases
official_website
description
status
```

### 6.4 Competitor

```text
id
project_id
name
aliases
website
notes
```

### 6.5 PromptQuestion

```text
id
project_id
text
intent_type
keywords
language
market
priority
status
```

### 6.6 Platform

```text
id
name
type
access_method
region
status
```

### 6.7 MonitorRun

```text
id
project_id
platform_id
run_type
scheduled_at
started_at
finished_at
status
error_message
```

### 6.8 AnswerSnapshot

```text
id
monitor_run_id
question_id
platform_id
prompt_text
answer_text
citations
screenshot_url
html_snapshot_url
model_name
region
language
collected_at
status
```

### 6.9 AnswerAnalysis

```text
id
answer_snapshot_id
brand_mentioned
brand_recommended
brand_position
competitors_mentioned
sentiment
risk_level
accuracy_score
source_score
answer_score
diagnosis
created_at
```

### 6.10 KnowledgeFact

```text
id
project_id
fact_type
subject
predicate
object
evidence_source_id
confidence
status
valid_from
valid_until
created_by
reviewed_by
```

### 6.11 ContentAsset

```text
id
project_id
content_type
title
body
target_questions
target_platforms
target_sources
used_fact_ids
risk_check_result
status
created_by
reviewed_by
```

### 6.12 DistributionTask

```text
id
project_id
content_asset_id
target_source
assignee_id
publish_url
planned_at
published_at
status
notes
```

### 6.13 AU 首发新增/优先数据模型

以下模型在 AU 首发 P0a/P0b/P0c 中优先级高于通用知识库/内容/分发模型，详见 [GENO-SaaS-AU-首发技术落地路径](GENO-SaaS-AU-首发技术落地路径.md) 第 8 章：

```text
MarketProfile
IndustryProfile
GeoSample
AnswerRun
RawAnswer
AnswerCitation
EvidenceAsset
CollectorLog
CollectionCost
SourceGraph
CompetitorBenchmark
VisibilityScoreSnapshot
BrandEntity / CompetitorEntity / EntityAlias
AuditEvent
ReportExport
ScoreContribution
EvidenceLink:
  SourceGraphEvidence
  ScoreSnapshotRun
  ReportEvidence
```

AU 首发命名约束：通用 `AnswerSnapshot` 可作为旧名参考，实现时应使用 `AnswerRun + RawAnswer + AnswerCitation + EvidenceAsset` 组合，避免把截图、HTML、raw payload、引用和触发状态混在一个不可追溯快照里。

## 7. 技术选型建议

### 7.1 后端

- 语言/框架：Python FastAPI 或 Node.js NestJS。
- 主库：PostgreSQL。
- 缓存：Redis。
- 任务队列：Celery/RQ 或 BullMQ。
- 搜索：OpenSearch 或 PostgreSQL full-text。
- 向量库：pgvector 或 Milvus，MVP 优先 pgvector。
- 对象存储：S3 兼容存储或云厂商 OSS。

### 7.2 前端

- React + TypeScript。
- 管理后台优先，不做营销页。
- 核心页面：项目看板、问题集、采集运行、原始证据、解析结果、Citation Graph、竞品对标、分数解释包、Evidence Report。知识库、内容工作台、分发任务在 AU 首发中属于 P2 页面。

### 7.3 LLM 网关

统一封装模型调用：

- OpenAI、DeepSeek、豆包、通义、Gemini 等。
- 支持模型路由、重试、成本统计、调用日志、脱敏。
- 所有 LLM 输出必须保存 prompt 版本和解析结果。

### 7.4 采集

- API 优先。
- 无 API 的平台采用浏览器自动化或人工辅助采集。
- 采集服务与主业务服务隔离。
- 加入速率限制、失败重试、证据留存和合规开关。

## 8. 核心流程

### 8.1 基线监测流程

```text
创建项目
  -> 配置品牌/竞品/平台/问题集
  -> 创建基线监测任务
  -> 采集 AI 回答
  -> 保存原始证据
  -> 自动分析
  -> 人工抽样复核
  -> 生成基线报告
```

### 8.2 知识库创建流程

```text
导入资料
  -> 文档解析
  -> 事实抽取
  -> 证据链绑定
  -> 人工审核
  -> 入库
  -> 向量索引更新
```

### 8.3 内容优化流程

```text
识别问题缺口
  -> 选择内容模板
  -> RAG 检索知识事实
  -> 生成内容草稿
  -> 风险检查
  -> 人工审核
  -> 创建发布任务
```

### 8.4 效果追踪流程

```text
发布内容
  -> 回填发布链接
  -> 设置观察窗口
  -> 再次采集相关问题
  -> 对比前后表现
  -> 生成优化建议
```

## 9. 权限设计

角色建议：

- Super Admin：系统管理员。
- Tenant Admin：租户管理员。
- Project Owner：项目负责人。
- Analyst：数据分析师。
- Knowledge Architect：知识库架构师。
- Content Operator：内容运营。
- Reviewer：审核人。
- Client Viewer：客户只读角色。

权限原则：

- 客户只能看到所属租户和授权项目。
- 未审核知识不得用于正式内容。
- 未审核内容不得进入发布任务。
- 敏感行业内容必须二次审核。
- 所有评分权重调整必须记录审计日志。

## 10. 安全与合规

### 10.1 数据安全

- 多租户数据隔离。
- 客户文件加密存储。
- 敏感字段脱敏。
- 操作审计。
- 文件访问签名 URL。
- LLM 调用前可配置脱敏策略。

### 10.2 内容合规

- 禁止生成虚假资质、虚假案例、虚假排名。
- 医疗、金融、教育等行业使用专门审核规则。
- 禁止冒充真实用户发布内容。
- 社区内容必须符合平台规则。
- 对外内容必须保留证据来源和审核记录。

### 10.3 采集合规

- 优先使用官方 API。
- 控制采集频率。
- 不绕过平台安全机制。
- 不使用违规账号池。
- 对无法稳定合规采集的平台，降级为人工采集或抽样监测。

## 11. 运维与监控

核心监控指标：

- 采集任务成功率。
- 单平台失败率。
- LLM 调用成功率。
- LLM 成本。
- 分析任务耗时。
- 报表生成耗时。
- 队列积压。
- 内容审核积压。

AU 首发还必须监控：

- planned_runs / completed_runs / failed_runs。
- collector_backend 成功率、平均耗时、单位成本。
- `answer_present` / `surface_triggered` 覆盖率。
- Google spike 触发率、失败分类、pass/fail gate。
- `AuditEvent` 写入成功率。
- `ReportExport` 导出版本数和导出失败率。
- 证据链断裂数：有报告数字但无法追溯到 `AnswerRun` 的数量必须为 0。

告警：

- 采集连续失败。
- LLM 成本异常。
- 队列积压超过阈值。
- 核心任务超时。
- 对象存储上传失败。

## 12. MVP 成功标准

通用一期上线后，应能完成以下验收：

- 一个项目可配置至少 5 个平台、100 个问题、5 个竞品。
- 能按计划采集 AI 回答并保存证据。
- 能自动生成品牌可见性评分和竞品对比。
- 能导入客户资料并形成审核后的知识事实。
- 能基于知识库生成内容草稿并完成审核流。
- 能创建分发任务并回填发布 URL。
- 能生成周报/月报。
- 能对重点负面和品牌未出现问题发出预警。

AU 首发上线验收以以下口径覆盖上面的通用清单：

- 可创建 `market=AU` 项目，配置 1 个行业、100 条 AU prompt、3-5 个竞品。
- P0a 完成 Perplexity Sonar + OpenAI web search 采集，每条有 answer、citation、截图/HTML、`answer_present`、`surface_triggered`、`sample_index`、`raw_payload_hash`。
- P0b 完成 Google AIO / AI Mode spike，并输出 pass/fail gate；未通过时 Google 只进 limited coverage 附录。
- 自动解析提及、推荐、排名、竞品、引用、本地相关性，并生成 `AUVisibilityScore`。
- 任意总分、平台分、城市分、intent 分都有 `ScoreContribution` 解释包。
- 生成 Citation Graph、source gap 和 3-5 个竞品 Benchmark。
- Evidence Report 导出为不可覆盖 `ReportExport` 版本快照，包含方法说明、审计摘要、分数解释包和原始证据附录。
- 任意报告数字可沿 `ReportExport -> VisibilityScoreSnapshot -> ScoreContribution -> AnswerAnalysis -> AnswerRun -> RawAnswer/AnswerCitation/EvidenceAsset` 追溯。
- 采集、解析、评分、人工补录、实体确认、报告导出都写入 `AuditEvent`。

## 13. 主要风险与应对

| 风险 | 说明 | 应对 |
| --- | --- | --- |
| AI 平台回答不稳定 | 同一问题多次回答可能不同 | 多次采样、保存时间窗、展示趋势而非单点结果 |
| 平台采集受限 | 部分平台无 API 或有风控 | API 优先，无法 API 则半自动采集，明确合规边界 |
| 评分争议 | 客户可能质疑可见性分数 | 使用可解释权重，展示原始证据和分析依据 |
| 内容合规 | 生成内容可能夸大或错误 | 知识库约束、事实校验、人工审核、禁用口径 |
| 归因不清 | GEO 优化与转化之间难强因果 | 一期只做相关性和前后对比，不承诺广告级归因 |
| 成本失控 | 大量采集和 LLM 分析成本高 | 任务频率限制、缓存、批处理、模型路由 |
| Google AIO / AI Mode 采集不稳定 | 澳洲首发 Google 权重最高，但 AIO 选择性触发且界面易变 | P0b 独立 spike；未过闸只进 limited coverage 附录，不阻塞 P0a/P0c |
| 审计链/解释链断裂 | 报告数字若不能追溯，会削弱客户信任 | P0 起建 `AuditEvent / EvidenceLink / ScoreContribution / ReportExport`，M5 验收任意数字可追溯 |
