# GEO 项目需求基线

> 状态：审计基线  
> 版本日期：2026-07-18  
> 适用范围：生成式引擎优化（Generative Engine Optimization，GEO）网站实施与 GEO 管理平台  
> 目的：作为本项目后续功能、架构、数据、界面、测试和运营能力复查的统一验收依据

## 1. 核心定义

GEO 不是 SEO 的替代品。成熟 GEO 应当包含：

> 完整 SEO 底座 + 可检索、可引用的内容工程 + 多引擎可见性监测 + 实验归因 + 内容治理 + Agent 可执行性

完整业务链路为：

```text
抓取 -> 索引 -> 检索入选 -> 引用选择 -> 答案吸收/品牌表述 -> 曝光 -> 点击 -> 转化
```

任何单独一环都不能代表完整 GEO 效果：

- 爬虫访问不等于被检索。
- 被检索不等于被引用。
- 被引用不等于用户看见或点击。
- 品牌被提及不等于表述正确或正面。
- AI referral 不等于 GEO 的全部影响。
- 可见性提升不等于收入增长。

## 2. 证据等级

所有产品判断、评分和优化建议必须标明证据等级：

| 等级 | 定义 | 可用于 |
|---|---|---|
| P：平台明确 | 搜索或 AI 平台官方文档明确说明 | 硬门槛、资格判断、平台配置 |
| R：研究支持 | 同行评审论文或可复核实验支持 | 优化假设、实验设计，不直接承诺业务结果 |
| I：工程推论 | 基于检索流程、平台限制和实践形成的合理推论 | 产品设计和待验证建议 |
| X：可选实验 | 尚未标准化或缺少主流平台支持 | 低成本试验，不得计入核心资格 |

不得把观察相关、内部模拟或行业营销结论包装为平台规则。

## 3. 总体验收原则

1. 传统 SEO 技术和内容能力是 GEO 的必要底座。
2. 项目必须覆盖从抓取到业务转化的分层数据，不得只给一个黑盒总分。
3. 官方平台数据、真实引擎抽样和内部模拟必须分别标识和存储。
4. 所有统计、引语、事实和引用必须可追溯，禁止虚构来源或数据。
5. 搜索收录、模型训练和用户实时取页必须分别配置授权策略。
6. 优化应以问题簇和业务目标为单位，并监测对非目标问题的负面影响。
7. 已经表现良好的内容必须允许“不修改”，不得为了生成优化建议而强制改写。
8. 最终目标必须包含合格线索、收入、留存或任务完成等业务指标。

## 4. 达到或超过传统 SEO 的能力要求

| ID | 能力层 | 达到传统 SEO 的要求 | GEO 增量要求 |
|---|---|---|---|
| CAP-01 | 技术资格 | HTTP 200、robots、canonical、sitemap、内链、可渲染、移动端和页面体验 | 按平台验证搜索爬虫、WAF/CDN、索引资格、snippet/引用权限 |
| CAP-02 | 需求研究 | 关键词、搜索量、排名、搜索意图 | Prompt 集、问题簇、query fan-out、多轮路径、人物、语言和地区 |
| CAP-03 | 内容质量 | 原创、完整、满足意图、用户体验良好 | 可验证定义、事实、数据、比较、步骤、边界条件、专家或亲历证据 |
| CAP-04 | 证据治理 | 权威来源和合理外链 | 论断到原始来源的追溯、引用蕴含检查、过期和冲突检测 |
| CAP-05 | 实体体系 | 品牌词、作者和适用的结构化数据 | 品牌、产品、人物、地点、别名及属性跨正文、Schema、Feed 和外部档案一致 |
| CAP-06 | 页面表达 | 清晰标题、正文、图片和结构化数据 | 关键事实使用公开文本；支持表格、字幕、transcript 和可访问语义结构 |
| CAP-07 | 分发时效 | Sitemap、Search Console、正常发现机制 | 真实 lastmod、IndexNow、垂直 Feed、更新/删除通知及重抓延迟监测 |
| CAP-08 | 站外权威 | 高质量链接、品牌需求和数字公关 | 真实媒体、社区、评测和行业资料中的一致品牌事实；禁止虚假提及 |
| CAP-09 | 可见性度量 | 排名、曝光、CTR 和自然流量 | 提及率、引用率、被引页面、引用位置、答案吸收、准确性和竞品份额 |
| CAP-10 | 业务结果 | Organic 转化和收入 | AI referral、辅助转化、线索质量、收入、留存和 Agent 任务完成率 |
| CAP-11 | 实验体系 | 页面、标题和转化实验 | 按引擎、模型、语言、地区重复采样，报告区间、最差结果和负收益 |
| CAP-12 | 治理安全 | SEO 发布规范和人工审核 | 反虚构、反低价值批量内容、版权、隐私、Prompt Injection 和用途授权 |

## 5. 平台接入要求

### 5.1 Google Search、AI Overviews 和 AI Mode

- 页面必须满足普通 Google Search 技术要求、已被索引并允许展示 snippet。
- 必须允许 Googlebot 访问，且 CDN、WAF 和 JavaScript 渲染不能隐藏关键内容。
- 必须支持 `noindex`、`nosnippet`、`max-snippet`、`data-nosnippet` 和非 HTML 资源的 `X-Robots-Tag` 审计。
- 必须校验 Sitemap 只包含 canonical URL，`lastmod` 只能反映真实实质更新。
- 必须校验结构化数据准确、完整、可抓取且与可见正文一致。
- 应接入 Search Console 的普通 Performance 数据、生成式 AI 资格控制和生成式 AI Performance 报告（在账号具备权限时）。
- 必须将 Google Search AI 资格与 Google-Extended 的训练/部分 Gemini grounding 控制分开。
- 不得把 `llms.txt`、内容强制切块、固定篇幅或专用 AI Schema 作为 Google GEO 门槛。

### 5.2 Microsoft Bing 和 Copilot

- 必须允许 Bingbot 抓取和渲染关键内容；不得假设存在独立 `CopilotBot`。
- Sitemap 用于完整 canonical URL 库，IndexNow 用于新增、实质更新和删除通知，两者应同时支持。
- 必须支持 Bing `NOINDEX`、`NOARCHIVE`、`NOCACHE`、`data-nosnippet` 等规则的差异化审计。
- 应接入 Bing Webmaster Tools AI Performance，包括 citations、cited pages、grounding queries、topics、intents、Citation Share 和趋势（以账号实际开放字段为准）。
- 必须明确 grounding query 不等于用户原始 Prompt，citation 不等于排名、点击或质量。
- 本地业务应支持 Bing Places 信息准确性检查。

### 5.3 OpenAI 和 ChatGPT Search

- 必须分别识别和配置：
  - `OAI-SearchBot`：搜索发现和引用。
  - `GPTBot`：潜在模型训练。
  - `ChatGPT-User`：用户触发的实时访问。
- 必须检查 robots、主机、CDN、WAF、限流和官方 IP 是否允许目标爬虫访问。
- 必须支持通过 `utm_source=chatgpt.com` 和一方分析数据归因 ChatGPT referral。
- 不得宣称 XML Sitemap、Schema.org、`llms.txt` 或 URL 提交是 ChatGPT Search 的官方通用准入要求。
- 电商场景可把 OpenAI 商品 Feed 作为受资格限制的垂直接入能力，不能当作所有站点的必需项。

### 5.4 Anthropic 和 Claude

- 必须分别识别 `Claude-SearchBot`、`ClaudeBot` 和 `Claude-User`。
- 搜索可见性、训练授权和用户实时访问必须允许分别设置。
- 应支持 robots 规则和抓取日志审计，不得把 ClaudeBot 训练抓取当作搜索引用证据。

### 5.5 Perplexity

- 必须检查 `PerplexityBot` 的 robots 和 WAF/IP 放行状态。
- 应分别识别用于索引的 `PerplexityBot` 和用户触发的 `Perplexity-User`。
- 不得承诺 robots 能绝对控制所有用户触发取页。
- 不得把 Sitemap 提交、Schema.org、URL 提交、站长后台或外部站点 `llms.txt` 标为 Perplexity 官方支持，除非后续官方规范发生变化。

## 6. 成熟 GEO 管理平台功能要求

### FR-01 项目与工作区

- 支持多项目、多域名、子域名、品牌、产品、语言、地区和竞品。
- 支持成员、角色、权限、审计日志和组织级数据隔离。
- 支持定义业务目标、目标市场、主要转化和目标生成式引擎。

### FR-02 数据连接器

- 接入 Google Search Console、Bing Webmaster Tools、GA4 和 Microsoft Clarity。
- 支持 CDN/server log、CMS、CRM、数据仓库和一方事件数据。
- 记录连接状态、权限范围、同步时间、失败原因和数据新鲜度。
- 不得在字段不可用时伪造或推算成官方数据。

### FR-03 逐 URL 技术审计

- 检查 HTTP 状态、重定向、canonical、robots、meta robots、X-Robots-Tag、Sitemap 和内链。
- 支持原始 HTML 与渲染后 DOM 对比，确认关键正文可见。
- 检查登录墙、付费墙、CAPTCHA、WAF、地域限制和速率限制。
- 检查重复内容、参数噪声、软 404、孤立页面和错误删除状态。
- 对每个目标引擎输出“可抓取、可索引、可摘要、可引用”的分层结论。

### FR-04 AI 爬虫与用途策略中心

- 按搜索、训练、用户实时读取三类用途维护爬虫矩阵。
- 生成并验证 robots/meta/WAF 配置，支持官方 IP 或 bot 验证机制。
- 检测冲突、过宽或过严规则，以及子域名规则遗漏。
- 保存策略版本、批准人、变更时间和影响范围。

### FR-05 Prompt 与意图库

- 从搜索查询、站内搜索、客服、销售、用户研究和业务知识构建问题集合。
- 按主题、意图、漏斗阶段、人物、地区、语言和业务价值分类。
- 支持问题簇、fan-out 子问题、多轮追问和品牌/非品牌问题。
- 支持版本、来源、优先级、启停和抽样权重。
- 不得声称固定 Prompt 集等同于全部真实用户需求。

### FR-06 内容库存与主题覆盖

- 抓取并维护页面、内容类型、主题、目标问题、作者、发布时间和更新时间。
- 识别主题缺口、重复内容、自相竞争、内容过期和意图不匹配。
- 区分原创研究、第一方数据、专家经验、汇总内容和商品化通用内容。
- 对内容建议标明证据等级、适用领域和预期影响环节。

### FR-07 实体与事实一致性

- 管理 Organization、Person、Product、Place、Service 等核心实体。
- 维护规范名称、别名、关系、属性、来源、有效期和冲突状态。
- 比较正文、Schema、Feed、商业档案及已接入外部来源的一致性。
- 支持价格、库存、地址、营业时间、版本等高时效事实的过期告警。

### FR-08 论断与证据治理

- 提取重要论断、统计、引语、比较和结论。
- 为每个论断保存原始来源、发布日期、访问时间和证据片段。
- 检查来源是否真实、是否过期，以及证据是否支持对应论断。
- 禁止自动发布虚构统计、虚构引用、伪造专家或无法追溯的事实。
- 对 YMYL、法律、医疗、金融等高风险内容设置加强审核流程。

### FR-09 跨引擎观测

- 支持目标生成式引擎的合规观测方式，并记录调用方式和限制。
- 每次观测必须保存 Prompt、回答、引用、时间、引擎、模型、语言、地区和运行参数。
- 支持重复运行和随机性度量，不得用单次结果代表稳定排名。
- 明确区分：官方平台数据、真实引擎抽样、代理/API 结果和内部模拟。
- 对不允许自动化采集的平台不得使用违规抓取。

### FR-10 答案、品牌和引用分析

- 提取品牌、产品、竞品、推荐、引用 URL、来源域和引用位置。
- 计算品牌提及率、引用率、本站引用率、来源多样性和答案吸收度。
- 分析品牌表述、情感、事实准确性、遗漏和错误归因。
- 检查引用是否真正支持对应回答内容。
- 保存可复核的原始回答和引用证据，不能只保留聚合分数。

### FR-11 竞品与来源缺口

- 比较竞品提及、推荐、引用、被引页面、来源类型和问题覆盖。
- 定位差距发生在抓取资格、索引、主题、证据、实体、站外权威还是转化阶段。
- 支持按问题簇、引擎、地区、语言和时间比较。
- 不得把竞品的所有外部提及自动解释为可复制的排名因素。

### FR-12 可解释建议与优先级

- 每条建议必须包含问题、证据、影响链路、适用页面、风险和验证方法。
- 建议按硬阻断、重要缺口、优化实验和可选实验分级。
- 支持影响、工作量、业务价值和置信度排序。
- 必须允许“无需修改”和“证据不足”结论。
- 不得用一个不透明 GEO 总分替代具体诊断。

### FR-13 内容工作流

- 支持内容 brief、责任人、草稿、事实审核、引用审核、合规审核和批准。
- 建议内容应优先服务真实用户，并包含必要背景、直接答案、证据和限制。
- 支持 CMS 草稿或发布集成，但默认保留人工批准。
- 具备重复、低价值批量生成、关键词堆砌、伪造 Schema 和 Prompt Injection 门禁。

### FR-14 发布与分发

- 发布后校验页面、Schema、canonical、Sitemap、robots 和渲染结果。
- 支持真实 `lastmod` 更新、IndexNow 提交、删除通知和失败重试。
- 支持适用的 Merchant、Business、Product、Local 或媒体 Feed。
- 记录发布版本、提交结果、首次抓取时间和首次可见时间。

### FR-15 实验与版本管理

- 保存页面基线、变更内容、变更原因、目标问题簇和发布时间。
- 支持对照组、前后对比、重复采样和分层分析。
- 至少报告均值、样本量、波动、胜/平/负率、最差结果和跨查询影响。
- 按引擎、模型、语言、地区和内容类型监测效果漂移。
- 不得把固定候选集实验直接解释为公网抓取、检索或收入提升。

### FR-16 看板与告警

- 分开展示技术资格、官方可见性、抽样观测、答案质量、流量和业务结果。
- 支持被引页面、问题簇、引擎、地区、语言、设备和时间趋势。
- 提供爬虫阻断、索引下降、引用下降、品牌误述、竞品反超、内容过期和同步失败告警。
- 不同平台分母、覆盖面不同的指标不得直接相加。

### FR-17 流量与业务归因

- 识别 AI assistant referrer、UTM、落地页、互动、转化和收入。
- 支持合格线索、客单价、留存、辅助转化和 CRM 结果。
- 明确 last-click 无法覆盖零点击、跨设备和上游 AI 影响。
- 业务结果必须能够回溯到内容、问题簇、引擎和实验版本。

### FR-18 治理、安全与合规

- 支持数据保留、隐私、版权、许可证、付费内容和训练授权策略。
- `robots.txt` 只能作为访问偏好，不能充当鉴权或机密保护。
- 敏感内容必须使用认证、授权、WAF 和真实访问控制。
- 检测隐藏 AI 指令、Prompt Injection、恶意 UGC 和 Schema 泄密风险。
- 保存配置、内容、实验和发布审计日志。

### FR-19 Agent 可执行性

- 检查语义 HTML、ARIA 名称/角色/状态、表单标签和键盘可用性。
- 关键产品、价格、库存、地址、时间和操作条件应机器可读且与界面一致。
- 检查登录、地区、弹窗、验证码和复杂交互是否阻断正常 Agent 工作流。
- 对预约、购买、申请等任务记录完成率、失败步骤和错误类型。

### FR-20 API、导出与可复核性

- 支持原始数据和聚合数据导出、API 或数据仓库同步。
- 所有分数必须能够追溯到输入数据、计算版本和原始证据。
- 支持删除、重新计算、版本迁移和数据质量检查。

## 7. 最低数据记录要求

每次生成式引擎观测至少保存：

- 项目、品牌、问题 ID 和问题簇。
- 原始 Prompt、后续追问及运行时间。
- 平台、产品界面、模型或可识别版本。
- 国家/地区、语言、设备或客户端条件。
- 是否启用搜索、是否为实时 Web 结果、调用方式。
- 完整原始回答。
- 引用 URL、规范化 URL、来源域、引用顺序和关联文本。
- 品牌与竞品提及、推荐语境和答案事实。
- 运行错误、限流、拒绝、超时和缺失字段。
- 分析器、评分器和规则版本。

不得只保存模型生成的摘要或单一分数。

## 8. KPI 分层

### 8.1 技术健康

- 目标搜索爬虫可访问 URL 覆盖率。
- 2xx 成功率、阻断率、4xx/5xx/429 比例。
- 可索引、可展示 snippet、可引用页面覆盖率。
- 内容更新到首次重抓、重新索引或重新引用的延迟。

### 8.2 官方可见性

- Google 生成式 AI impressions 和可见页面覆盖率。
- Bing citations、cited pages、Citation Share、topics 和 intents。
- 官方报告提供的国家、设备、页面和日期趋势。
- 各平台指标必须独立展示，不得直接合并分母。

### 8.3 固定 Prompt 抽样基准

- 品牌提及率、推荐率和目标属性关联率。
- 本站引用率、被引页面覆盖率和引用来源多样性。
- 引用准确率、答案事实正确率和重要事实遗漏率。
- 竞品 Share of Voice。
- 重复运行的一致性、置信区间和模型漂移。

固定 Prompt 结果只能标记为 synthetic/observational benchmark，不得冒充真实用户曝光。

### 8.4 流量和体验

- AI referral sessions、渠道占比和落地页。
- Engaged session、阅读深度、停留、回访和跳出情况。
- 按 assistant、来源、页面、问题簇和市场拆分。

### 8.5 业务结果

- AI referral 合格线索、CVR、收入和每次会话收入。
- 客单价、线索质量、留存及辅助转化。
- Agent 预约、购买、申请等任务完成率。

## 9. 硬门槛

以下任一项失败，都不得判定为“成熟 GEO”：

| ID | 硬门槛 |
|---|---|
| GATE-01 | 保留完整 SEO 技术底座，目标页面可抓取、可渲染并具备索引资格 |
| GATE-02 | 能分别管理搜索抓取、训练和用户实时读取策略 |
| GATE-03 | 重要内容真实、公开可见、以用户为先且不存在 cloaking 或批量低价值滥用 |
| GATE-04 | 所有重要统计、引语和引用可追溯，具备事实及引用准确性检查 |
| GATE-05 | 官方数据、真实抽样和模拟结果清晰分离，原始证据可复核 |
| GATE-06 | 使用多次、分层观测，不用单次回答宣称稳定排名 |
| GATE-07 | 指标覆盖至少一个业务转化结果，不只统计提及或引用 |
| GATE-08 | 具备权限、隐私、版权、安全和人工审核机制 |

## 10. 成熟度分级

| 等级 | 定义 | 判定标准 |
|---|---|---|
| L0：伪 GEO | 只有 `llms.txt`、Schema、文章改写或单次 Prompt 检查 | 不具备可验证闭环 |
| L1：SEO 等效 | 技术 SEO、内容、Search Console 和常规分析基本完整 | 可达到传统 SEO，但没有生成式可见性闭环 |
| L2：GEO 可用 | 增加爬虫矩阵、问题库、引用分析和跨引擎观测 | 能发现和解释主要 GEO 问题 |
| L3：成熟 GEO | 通过全部硬门槛，具备官方连接器、证据治理、实验、发布、告警和业务归因 | 能持续、可复核地优化并评估业务影响 |
| L4：领先 GEO | 具备多语言、多模态、垂直 Feed、实体/证据图谱、Agent 任务和长期因果实验 | 能覆盖发现、答案和行动三个阶段 |

成熟度不能仅由加权总分决定；所有硬门槛必须单独通过。

## 11. 不应作为核心验收要求的项目

- `llms.txt`、`llms-full.txt` 或 `.md` 镜像：当前属于可选内容地图，不是统一收录、授权或排名标准。
- “GEO 专用 Schema”：主流平台没有统一专用类型。
- 强制内容切块、固定字数、固定段落长度或特定 AI 写作腔调。
- 为每个 fan-out 或长尾变体批量生成近重复页面。
- FAQ 外壳本身、关键词堆砌或所谓权威语气。
- 购买虚假提及、伪造评论、统计、专家、引语或引用。
- 单次 Prompt 排名、爬虫请求量或内部 LLM 评分作为真实曝光。
- 把内容进入固定候选集后的提升解释为公网抓取或自然检索提升。
- 把 citation、mention、impression、click 和 conversion 相互替代。

## 12. 后续项目审计输出格式

后续复查本项目时，每项要求应使用以下状态：

- `PASS`：功能完整，存在代码、数据和可重复验证证据。
- `PARTIAL`：存在实现但覆盖不足、数据不完整或结论不可复核。
- `FAIL`：缺失、行为错误或违反硬门槛。
- `N/A`：经业务范围确认不适用。
- `UNVERIFIED`：仅有界面或声明，无法证明真实运行。

每条发现至少包含：

1. 需求 ID。
2. 当前状态。
3. 代码、配置、数据库或界面证据。
4. 实际运行或测试证据。
5. 风险和影响链路。
6. 修复建议、优先级和验收方法。

优先级建议：

- `P0`：安全、数据诚信或导致整体不可用。
- `P1`：硬门槛失败，阻止抓取、索引、观测或业务闭环。
- `P2`：成熟能力缺失，明显降低诊断或优化质量。
- `P3`：增强项、垂直能力或可选实验。

## 13. 主要参考资料

### 平台官方资料

- [Google：Optimizing your website for generative AI features](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide)
- [Google：AI features and your website](https://developers.google.com/search/docs/appearance/ai-features)
- [Google Search Console：Generative AI performance report](https://support.google.com/webmasters/answer/16984139)
- [Google：Structured data guidelines](https://developers.google.com/search/docs/appearance/structured-data/sd-policies)
- [Bing Webmaster Guidelines](https://www.bing.com/webmasters/help/webmaster-guidelines-30fba23a)
- [Bing：AI Performance](https://blogs.bing.com/webmaster/February-2026/Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview)
- [Bing：Sitemaps in AI-powered search](https://blogs.bing.com/webmaster/July-2025/Keeping-Content-Discoverable-with-Sitemaps-in-AI-Powered-Search)
- [IndexNow：Getting started](https://www.bing.com/indexnow/getstarted)
- [OpenAI：Crawler overview](https://developers.openai.com/api/docs/bots)
- [OpenAI：Publishers and Developers FAQ](https://help.openai.com/en/articles/12627856-publishers-and-developers-faq)
- [Anthropic：Web crawler controls](https://support.anthropic.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler)
- [Perplexity：Crawler documentation](https://docs.perplexity.ai/docs/resources/perplexity-crawlers)
- [RFC 9309：Robots Exclusion Protocol](https://www.rfc-editor.org/rfc/rfc9309.html)
- [`llms.txt` proposal](https://llmstxt.org/)

### 研究证据

- [Aggarwal et al.：GEO: Generative Engine Optimization，KDD 2024](https://arxiv.org/abs/2311.09735)
- [Liu et al.：Evaluating Verifiability in Generative Search Engines，EMNLP 2023](https://aclanthology.org/2023.findings-emnlp.467/)
- [Wan et al.：Web Content Influence Study，ACL 2024](https://aclanthology.org/2024.acl-long.403/)
- [Liu and Xu：Feature-Level GEO，ACL 2026](https://aclanthology.org/2026.acl-long.929/)
- [Zhou et al.：Cross-query GEO effects，Findings ACL 2026](https://aclanthology.org/2026.findings-acl.1373/)

原始 GEO 研究证明的主要是“内容已经进入候选来源后，表达和证据可能影响模型使用方式”，不能直接证明真实公网中的抓取、索引、检索、点击或收入提升。因此本规范始终把 SEO 资格、生成式引用和业务结果分层验收。
