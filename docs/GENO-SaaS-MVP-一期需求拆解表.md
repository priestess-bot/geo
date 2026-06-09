# GENO SaaS MVP 一期需求拆解表

> **状态说明（2026-06-09）**：本文保留为通用 GENO SaaS 需求拆解参考。当前澳大利亚首发工程交付以 [GENO-SaaS-AU-首发技术落地路径](GENO-SaaS-AU-首发技术落地路径.md)、[PROJECT-PLAN](../PROJECT-PLAN.md) 和 [ARCHITECTURE](../ARCHITECTURE.md) 为准。
>
> **AU 首发覆盖规则**：通用需求中的知识库、内容工作台、分发任务不是 AU 首发 P0。AU 首发 P0 拆为 **P0a Stable Evidence Chain**、**P0b Google High-risk Spike**、**P0c Customer Evidence Report**，主线为“证据 -> 信源图谱 -> 竞品差距 -> 行动建议 -> 报告 -> 复测”，内容生成和集成后移到 P2。

## 1. 一期目标

一期目标是完成 GEO 业务最小闭环：

```text
项目配置 -> 问题集 -> AI回答采集 -> 可见性评分 -> 知识库 -> 内容生成审核 -> 分发记录 -> 报表预警
```

一期优先保证可用、可解释、可复盘，不追求全平台自动化和复杂归因。

澳大利亚首发目标覆盖为：

```text
AU MarketProfile -> 100 条 AU Prompt Pack -> Perplexity/OpenAI 稳定采集
  -> Google AIO / AI Mode spike
  -> Raw Evidence Store + Audit/Provenance
  -> Answer Parser -> AUVisibilityScore + ScoreContribution
  -> Citation Graph -> Competitor Benchmark
  -> Evidence Report Export -> 7/14/30 天复测
```

## 2. 角色定义

| 角色 | 说明 |
| --- | --- |
| 系统管理员 | 管理租户、平台、模型、全局配置 |
| 项目负责人 | 管理项目、成员、交付节奏和客户报表 |
| 数据分析师 | 配置问题集、查看监测结果、复核分析 |
| 知识库架构师 | 导入资料、审核事实、维护知识库 |
| 内容运营 | 生成内容、创建发布任务、回填发布结果 |
| 审核人 | 审核知识事实和内容资产 |
| 客户只读用户 | 查看项目看板和报告 |

## 3. 需求优先级

| 优先级 | 定义 |
| --- | --- |
| P0 | MVP 必须具备，没有则闭环不可用 |
| P1 | 一期重要能力，影响交付效率或客户体验 |
| P2 | 可延后能力，适合二期优化 |

AU 首发使用以下优先级覆盖通用 P0/P1/P2：

| AU 级别 | 含义 |
| --- | --- |
| P0a | 稳定证据链：AU MarketProfile、Prompt Pack、Perplexity/OpenAI 采集、Raw Evidence Store、Parser、Score、Audit/Provenance |
| P0b | Google AIO / AI Mode 高风险 spike：限时验证浏览器/第三方/人工路径，输出 pass/fail gate |
| P0c | 客户可售证据报告：Citation Graph、Competitor Benchmark、Evidence Report、ReportExport 快照 |
| P1 | Action Plan、7/14/30 天复测、代理商工作流 |
| P2 | 知识库、内容生成、分发、集成和更多平台 |

## 4. Epic 拆解

### Epic 1：租户、项目与权限

| 编号 | 需求 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| E1-01 | 创建和管理租户 | P0 | 管理员可创建、禁用、编辑租户；租户数据相互隔离 |
| E1-02 | 创建 GEO 项目 | P0 | 可配置项目名称、行业、市场、语言、服务周期、状态；AU 首发必须支持 `market=AU` |
| E1-03 | 品牌档案管理 | P0 | 可配置品牌名称、别名、官网、介绍、核心产品 |
| E1-04 | 竞品管理 | P0 | 每个项目可维护多个竞品及别名；AU 首发固定 3-5 个竞品 |
| E1-05 | 成员和角色权限 | P0 | 可按项目分配负责人、分析师、内容运营、审核人、客户只读角色 |
| E1-06 | 操作审计日志 | P0a | 关键操作写入 `AuditEvent`，记录 actor、时间、对象、前后 hash、输入输出引用 |

### Epic 2：平台与问题集管理

| 编号 | 需求 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| E2-01 | AI 平台字典 | P0a/P0b | AU 首发 P0a 支持 ChatGPT/OpenAI web search、Perplexity；P0b 支持 Google AIO / AI Mode；国内平台不进入 AU P0 |
| E2-02 | 平台权重配置 | P0a | 项目内可配置平台评分权重；AU 默认 Google 45 / ChatGPT 30 / Perplexity 25，Google 入主分母需过 P0b gate |
| E2-03 | 问题集管理 | P0a | 可新增、编辑、导入、停用问题；AU 首发 100 条英文 prompt，上限 200，绑定 `prompt_version` |
| E2-04 | 问题意图分类 | P0 | 支持品牌认知、品类推荐、场景需求、竞品对比、购买决策、负面风险、权威背书 |
| E2-05 | 问题优先级配置 | P0 | 可设置问题优先级和意图权重 |
| E2-06 | 批量导入问题 | P1 | 支持 CSV/XLSX 导入问题、关键词、意图、语言、市场 |
| E2-07 | 行业问题模板 | P0a | AU 首发至少支持 1 个行业模板；更多行业模板 P2 |

### Epic 3：AI 回答采集

| 编号 | 需求 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| E3-01 | 创建监测任务 | P0 | 可选择项目、平台、问题集、执行时间和频率 |
| E3-02 | 手动触发采集 | P0 | 用户可对单个平台或全部平台立即执行采集 |
| E3-03 | 定时采集 | P1 | P0a 可用 simple worker/cron 或手动批跑；复杂定时调度进入 P1 |
| E3-04 | 采集结果保存 | P0a | 保存 prompt、answer、平台、surface、access_method、地区、语言、时间、引用链接、`answer_present`、`surface_triggered`、`sample_index/sample_size` |
| E3-05 | 证据留存 | P0a | 每条回答支持保存截图或 HTML 快照 URL、raw_payload_hash、collector_backend_id、collector_version |
| E3-06 | 采集失败重试 | P1 | 失败任务可自动重试并记录错误原因 |
| E3-07 | 采集频率限制 | P1 | 可按平台配置限流，避免异常高频请求 |
| E3-08 | 人工采集回填 | P0b | Google spike 至少保留人工补录路径，写入 `AuditEvent` 并标记 `access_method=manual` |
| E3-09 | Google AIO / AI Mode spike | P0b | 30 prompts × 2 surfaces × Australia/Sydney × k=2；输出成功率、触发率、失败原因、成本/耗时和 pass/fail gate |

### Epic 4：回答解析与可见性评分

| 编号 | 需求 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| E4-01 | 品牌提及识别 | P0 | 自动判断回答是否提及品牌及别名 |
| E4-02 | 竞品提及识别 | P0 | 自动识别回答中出现的竞品 |
| E4-03 | 推荐语义判断 | P0 | 自动判断品牌是否被明确推荐、中性提及或未出现 |
| E4-04 | 排名位置解析 | P0 | 对列表型回答解析品牌和竞品位置 |
| E4-05 | 情感与风险识别 | P0 | 自动识别正向、中性、负面和风险等级 |
| E4-06 | 引用源归类 | P0 | 对引用链接进行官网、媒体、社区、视频、百科、未知等分类 |
| E4-07 | 信息准确性标注 | P1 | 支持自动建议和人工标注事实是否准确 |
| E4-08 | 单条回答评分 | P0a | AU 首发使用 `au_visibility_v1`，按 8 项指标生成可解释分数 |
| E4-09 | 项目可见性总分 | P0a | 按问题权重和平台权重汇总项目总分；区分 Trigger/Mention/Recommendation 分母 |
| E4-10 | 评分权重配置 | P1 | 项目负责人可调整评分权重，并写入 `AuditEvent`，历史分数按旧版本可复算 |
| E4-11 | 人工复核 | P1 | 分析师可修改自动解析结果，系统记录修改前后差异 |
| E4-12 | 分数解释包 | P0a | 任意总分/平台分/城市分/intent 分都有 `ScoreContribution`，展示子指标贡献、权重、分母、正负证据和局限 |

### Epic 5：监测看板

| 编号 | 需求 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| E5-01 | 项目总览 | P0 | 展示总分、趋势、平台表现、问题覆盖、风险数量 |
| E5-02 | 平台对比 | P0 | 按平台展示品牌提及率、推荐率、平均排名、负面率 |
| E5-03 | 竞品对比 | P0c | 展示 3-5 个竞品在核心问题上的出现率、推荐率、排名、citation overlap、本地相关性 |
| E5-04 | 问题明细 | P0 | 可查看每个问题的原始回答、解析结果、截图和引用源 |
| E5-05 | 风险列表 | P0 | 汇总负面回答、信息错误、品牌未出现、竞品压制问题 |
| E5-06 | 筛选和导出 | P1 | 支持按平台、意图、时间、风险等级筛选并导出 |
| E5-07 | Citation Graph / Source Gap | P0c | 展示 AI 常引用源、竞品独占源、过旧源、澳洲本地信源缺失和可追溯 answer_run_ids |

### Epic 6：知识库

| 编号 | 需求 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| E6-01 | 文件导入 | P2 | 支持上传 PDF、DOCX、TXT、Markdown、CSV；AU 首发 P0 不阻塞 |
| E6-02 | URL 导入 | P2 | 支持导入官网、新闻稿、FAQ 页面链接 |
| E6-03 | 文档解析 | P2 | 系统可提取标题、正文、段落和来源信息 |
| E6-04 | 事实抽取 | P2 | 自动抽取品牌、产品、案例、资质、卖点、适用场景 |
| E6-05 | 证据链绑定 | P2 | 每条事实可关联来源文档或 URL；AU P0 的证据链优先来自 AnswerRun/Citation |
| E6-06 | 事实审核 | P2 | 未审核事实不得进入正式内容生成 |
| E6-07 | 事实状态管理 | P2 | 支持 draft、approved、deprecated、forbidden |
| E6-08 | 禁用口径 | P2 | 可维护不能生成或不能外发的表达 |
| E6-09 | 知识检索 | P2 | 支持按关键词、事实类型、状态检索 |
| E6-10 | 向量检索 | P2 | 内容生成时可基于问题语义检索相关事实 |

### Epic 7：内容工作台

| 编号 | 需求 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| E7-01 | 从问题缺口创建内容任务 | P2 | 可从品牌未出现、竞品压制、信息错误等问题生成任务；AU P1 先输出轻量 Action Plan |
| E7-02 | 内容类型选择 | P2 | 支持 FAQ、品牌介绍、产品介绍、竞品对比、行业科普、案例稿、新闻稿、社区问答、短视频脚本 |
| E7-03 | 基于知识库生成草稿 | P2 | 草稿必须引用 approved 状态事实和 evidence/source_gap |
| E7-04 | 内容模板 | P2 | 支持按内容类型维护生成模板 |
| E7-05 | 事实引用展示 | P2 | 内容页面展示使用了哪些知识事实和证据来源 |
| E7-06 | 风险检查 | P2 | 检测禁用口径、敏感词、绝对化表述、无证据主张 |
| E7-07 | 内容审核流 | P2 | 内容需审核通过后才能创建发布任务 |
| E7-08 | 版本管理 | P2 | 内容每次修改形成版本，可回溯 |
| E7-09 | 多语言内容 | P2 | 支持中文和英文内容生成与审核 |

### Epic 8：分发任务

| 编号 | 需求 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| E8-01 | 创建分发任务 | P2 | 可选择内容、目标信源、负责人、计划发布时间；AU 首发 P0 不做分发任务 |
| E8-02 | 发布状态流转 | P2 | 支持待发布、发布中、已发布、失败、取消 |
| E8-03 | 发布链接回填 | P2 | 已发布任务必须记录发布 URL 和发布时间 |
| E8-04 | 渠道分类 | P2 | 目标信源可归类为官网、媒体、社区、视频、百科、其他 |
| E8-05 | 分发台账 | P2 | 可按项目查看所有发布任务和结果 |
| E8-06 | 自动发布接口预留 | P2 | 数据模型预留 external_post_id、api_status 等字段 |

### Epic 9：报表与预警

| 编号 | 需求 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| E9-01 | 周报生成 | P0c | 自动生成本周可见性趋势、风险、source gap、竞品差距、下周建议 |
| E9-02 | 月报生成 | P0c | 自动生成月度总览、平台对比、竞品对比、优化效果；AU P0c 必须披露 Google spike 结论 |
| E9-03 | 报表导出 | P0c | 支持导出 PDF/CSV；生成不可覆盖 `ReportExport`，包含方法说明、审计摘要、分数解释包、原始证据附录 |
| E9-04 | 负面风险预警 | P0 | 重点问题出现负面回答时触发预警 |
| E9-05 | 品牌缺失预警 | P0 | P0 问题连续多次未出现品牌时触发预警 |
| E9-06 | 竞品压制预警 | P1 | 竞品排名连续高于品牌时触发预警 |
| E9-07 | 采集失败预警 | P1 | 平台采集连续失败时触发运维预警 |
| E9-08 | 报告追溯链 | P0c | 任意报告数值可沿 `ReportExport -> VisibilityScoreSnapshot -> ScoreContribution -> AnswerAnalysis -> AnswerRun -> RawAnswer/AnswerCitation/EvidenceAsset` 追溯 |

### Epic 10：系统管理与模型网关

| 编号 | 需求 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| E10-01 | LLM 供应商配置 | P0 | 支持配置不同模型供应商、API Key、默认模型 |
| E10-02 | Prompt 模板管理 | P1 | 支持管理回答解析、事实抽取、内容生成、风险审核模板 |
| E10-03 | 调用日志 | P0a | 保存模型、输入摘要、输出、耗时、token、成本，并能关联 `AuditEvent` |
| E10-04 | 成本统计 | P0a | 可按租户、项目、任务、collector_backend 统计模型/代理/供应商成本 |
| E10-05 | 对象存储配置 | P0 | 支持配置截图、原始文件、HTML 快照存储 |
| E10-06 | 任务队列监控 | P1 | 可查看采集、分析、生成任务状态和失败原因 |

## 5. MVP 里程碑

### M1：项目配置和问题集（AU = M1 / P0a）

目标：完成 AU 项目初始化能力。

范围：

- 租户/项目/品牌/竞品。
- AU MarketProfile、平台字典、平台权重和 build_stage。
- 1 个行业模板。
- 100 条 AU 英文 prompt（上限 200），绑定 intent/city/prompt_version。
- 角色权限基础能力。

验收：

- 能创建 `market=AU` 的客户项目。
- 能配置 1 个行业、3-5 个竞品、100 条 AU prompt。
- 平台、城市、语言、货币、权重全部从 MarketProfile 读取。

### M2：AI 监测和评分（AU = M2a/M2b/M3 / P0a+P0b）

目标：完成稳定证据链、Google spike 和 AU 可见性评分。

范围：

- Perplexity Sonar + OpenAI web search 稳定采集。
- Google AIO / AI Mode spike。
- 原始回答和证据保存，含触发状态、k、成本和 hash。
- 自动解析。
- `AUVisibilityScore` 与 `ScoreContribution`。
- 监测看板。

验收：

- 能跑完一次 P0a 基线采集。
- 能输出平台对比、竞品对比和风险问题列表。
- 能输出 Google spike pass/fail gate。
- 任意分数可点回原始 AnswerRun。

### M3：Citation Graph、竞品对标和 Evidence Report（AU = M4/M5 / P0c）

目标：完成可售、可审计证据报告。

范围：

- Citation Graph。
- Source gap。
- 3-5 竞品 Benchmark。
- Evidence Report PDF/CSV。
- `ReportExport` 不可覆盖快照。
- 审计摘要、分数解释包、原始证据附录。

验收：

- 能生成 Citation Graph 和 source gap。
- 能输出 3-5 竞品 Benchmark。
- 能导出包含方法说明、审计摘要、分数解释包、原始证据附录的 PDF/CSV。
- 任意报告数值可追溯到原始 `AnswerRun`。

### M4：Action Plan、复测、知识库/内容/分发（AU = P1/P2）

目标：完成复测闭环，并在市场验证后扩展内容和分发。

范围：

- P1：Action Plan、T+7/14/30 复测、前后窗口对比。
- P2：知识库、内容工作台、分发任务、自动发布接口预留。

验收：

- 能基于 source gap 生成 Action Plan。
- 能按同一 prompt_version、同一 k 复测。
- P2 启用后，内容生成必须绑定 evidence/source_gap/knowledge_fact 并过人工审核。

## 6. 一期验收清单

| 类别 | 验收项 |
| --- | --- |
| 项目配置 | 支持多租户、多项目、品牌、竞品、平台、问题集；AU 首发支持 `market=AU`、1 行业、100 prompt、3-5 竞品 |
| 监测采集 | P0a 支持 Perplexity + OpenAI 稳定采集，保存回答、引用、截图/HTML、触发状态、k、成本和 hash |
| Google spike | P0b 支持 Google AIO / AI Mode 浏览器/第三方/人工路径验证，输出 pass/fail gate |
| 自动分析 | 支持提及、推荐、排名、竞品、情感、风险、引用源解析 |
| 评分 | 支持 `au_visibility_v1`、平台评分、项目总分、双分母和 `ScoreContribution` 解释包 |
| 信源图谱 | 支持 Citation Graph、source gap、3-5 竞品 Benchmark |
| 报表 | 支持 Evidence Report PDF/CSV，包含方法说明、Google spike 结论、审计摘要、分数解释包、原始证据附录 |
| 追溯 | 任意报告数值可沿 `ReportExport -> VisibilityScoreSnapshot -> ScoreContribution -> AnswerAnalysis -> AnswerRun` 追溯 |
| 知识库 | P2 支持文件导入、事实抽取、证据链、审核状态 |
| 内容 | P2 支持基于知识库生成草稿、风险检查、审核流 |
| 分发 | P2 支持发布任务、负责人、状态、发布 URL 回填 |
| 安全 | 支持租户隔离、角色权限、`AuditEvent` |
| 运维 | 支持任务状态、失败原因、模型调用日志、CollectionCost、审计链断裂监控 |

## 7. 建议研发排期

| 周期 | 重点 | 主要产出 |
| --- | --- | --- |
| 第 1-2 周 | 接口契约、数据模型、AU MarketProfile | P0a/P0b/P0c 表、8 个接口 stub、AU 配置、1 行业模板 |
| 第 3-5 周 | Prompt Pack、稳定采集、Raw Evidence Store | 100 条 AU prompt、Perplexity/OpenAI 采集、证据留存、AuditEvent 基础 |
| 第 6-8 周 | Google spike、解析和评分 | Google AIO/AI Mode pass/fail gate、Answer Parser、AUVisibilityScore、ScoreContribution |
| 第 9-11 周 | Citation Graph、竞品对标、Evidence Report | Source gap、3-5 竞品 Benchmark、ReportExport、PDF/CSV |
| 第 12-13 周 | Action Plan 和复测 | T+7/14/30 复测、前后窗口对比、方法说明完善 |
| 第 14 周 | Design partner 试点和修复 | 试点报告、问题修复、上线验收 |

## 8. 数据埋点与运营指标

| 指标 | 说明 |
| --- | --- |
| 采集成功率 | 成功采集问题数 / 应采集问题数 |
| 自动解析准确率 | 人工复核通过的解析结果比例 |
| 品牌提及率 | 提及品牌的问题比例 |
| 品牌推荐率 | 明确推荐品牌的问题比例 |
| 平均排名 | 品牌在列表回答中的平均位置 |
| 负面率 | 存在负面表达的问题比例 |
| 内容审核通过率 | 审核通过内容 / 提交审核内容 |
| 发布完成率 | 已发布任务 / 应发布任务 |
| 报表生成成功率 | 成功生成报表 / 应生成报表 |
| 单项目模型成本 | 项目维度 LLM 调用成本 |
| 审计事件写入率 | 成功写入 AuditEvent 的关键动作 / 应写入关键动作 |
| 证据链完整率 | 可追溯报告数值 / 全部报告数值 |
| Google spike 触发率 | Google AIO / AI Mode 触发样本 / 尝试样本 |

## 9. 待确认问题

| 问题 | 建议 |
| --- | --- |
| 一期首批客户行业 | 选择教育、企业服务、跨境支付等资料较丰富且合规边界相对清晰的行业 |
| 首批 AI 平台 | AU 首发 P0a 选 Perplexity + OpenAI web search；P0b 验证 Google AIO / AI Mode |
| 采集方式 | API 优先；Google 用浏览器、第三方 SERP、人工补录三路 spike |
| 报表格式 | AU P0c 做 Evidence Report PDF/CSV，冻结 ReportExport 快照 |
| 内容发布 | AU 首发不进 P0；P2 只做任务和回填，不做违规自动发布 |
| 评分权重 | AU 默认 Google 45 / ChatGPT 30 / Perplexity 25；Google 未过 gate 不进主分母 |
| 审计溯源 | P0 起必须落 `AuditEvent / EvidenceLink / ScoreContribution / ReportExport` |
