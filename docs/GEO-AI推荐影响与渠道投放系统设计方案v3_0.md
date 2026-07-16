# GEO AI 推荐影响与渠道投放系统设计方案 v3.0

> 文档状态：Implementation Baseline
>
> 设计日期：2026-07-13
>
> 本文替代 `GEO-文案生成系统最终设计方案v2_0.md` 作为后续 GEO 领域实现合同。v2.0 保留为历史记录。

## 1. 产品目标

系统的目标是提升目标品牌和产品在消费者使用 ChatGPT Search、Google 搜索或 Google AI Overview 时的可见性、引用概率和被推荐比例。

```text
产品 Campaign
-> 已批准消费者查询
-> AI/搜索回答与引用观测
-> 可投放来源与渠道资格审核
-> 特定网站的内容包和人工提交
-> 已发布 URL 验证
-> 同口径复测和趋势报告
```

系统不承诺任何平台必然优先推荐某个产品。它只报告可复核的推荐、提及、引用和投放覆盖变化，不将相关性表述为因果关系。

## 2. 首个客户与通用边界

首个客户为 ADVINSYS AU。首轮同时建立三个完全独立的 Campaign：

- TerraMow V600 机器人割草机；
- TerraMow V1000 机器人割草机；
- Seauto SAT30 无线机器人泳池清洁机。

每个 Campaign 固定一个主产品、AU 市场和 `en-AU` 外部投放语言。`zh-CN` 只用于客户审核、运营说明和报告。

系统必须通用于未来商品、国家和渠道；ADVINSYS 的产品、域名、品牌和查询均为项目配置，不能硬编码。

## 3. 渠道政策

下列对象必须分开建模：

```text
Observed Source
= AI/Google 已引用或发现的网站，不代表可投放

Evidence Source
= 支撑产品事实的资料，不代表可公开引用

Publication Destination
= 已审核且可实际提交或发布的具体网站、栏目、账号或商品页

Placement
= 对一个具体 Destination 的一次投稿、资料提交、发布或验证工作
```

首批 ADVINSYS 渠道策略：

| 渠道 | 策略 | 可创建提交包 |
| --- | --- | --- |
| `advinsys.com.au` | 自有 Shopify 网站，人工发布 | 是 |
| `amazon.com.au` | 已授权卖家资料和商品页，人工维护 | 是，需确认权限 |
| `youtube.com` | 官方视频或免费创作者合作，人工发布/发送 | 是 |
| TikTok、Instagram | 官方内容或免费创作者素材，人工发布 | 是 |
| `productreview.com.au` | 商家资料、已验证购买上下文中的官方回复；禁止伪造消费者评价 | 资格与上下文审核通过后是 |
| `reddit.com` | 明确披露品牌关系的官方参与；遵守具体 Subreddit 规则 | 身份与社区政策审核通过后是 |
| `ozbargain.com.au` | 真实优惠的商家提交；明确披露关联关系 | 商家资格和优惠证据审核通过后是 |
| Quora | 明确披露品牌关系的专业回答 | 身份、主题和来源审核通过后是 |
| 竞品网站、Wikipedia | 竞争或引用观察 | 否，除非另行人工审核 |

正式 Placement 流程禁止生成、安排或代发伪装消费者的推广、虚假评价、隐蔽商业关系内容和未经授权账号发布。独立的 `TEST ONLY Prompt Simulation` 是唯一例外：它可以生成 `fake_persona` 或 `synthetic_testimonial` 测试文案，但结果不可进入正式 Package、Review、Export、Publication 或 Submission，且永远 `publication_eligible=false`。

每个被运营人员选中的渠道都必须创建持久 `Placement` 任务。渠道未审核、受限、禁止，或缺少账号授权、优惠、原始问题/评价上下文时，任务仍然存在并展示明确的阻断原因，不得被静默省略；只有 Destination Policy、身份、披露和证据门禁均通过后，任务才可进入 Brief、生成、审核和人工提交。任务存在不等于平台允许发布，也不等于系统自动发布。

## 4. 数据与领域对象

复用 Schema v2 已实现的 `product_entities`、`monitoring_queries`、Collection、`answer_runs`、`answer_citations`、Source Graph、Source Gap、Knowledge、Reports、Notifications 和 Portal。

新增 GEO Placement Domain：

```text
geo_campaigns
geo_campaign_query_clusters
geo_campaign_queries
publisher_catalog
project_destinations
destination_policy_versions
placement_opportunities
placement_briefs / placement_brief_versions
placement_packages
placement_submissions
placement_verification_runs
placement_measurements
```

所有 project-owned 关系使用 `(id, project_id)` 复合外键、`UNIQUE(id, project_id)`、`ENABLE/FORCE RLS` 和受限 command function。任何 Observation Source 都不能自动成为 Destination；`observed_only` Destination 可以形成可见的阻断任务，但不能创建 Package 或 Submission。

ADVINSYS 官网、Amazon 商品页和已授权社媒页面自动导入为 `brand_authored` Knowledge Source，可直接进入生成输入，但必须带精确 URL、版本、hash 和来源类别。品牌自述不能被改写成独立评测、客观排名或消费者体验；认证、比较、价格和安全 Claim 必须由对应来源明确支持。

## 5. 查询、观测与衡量

查询由系统从产品、竞品、历史回答、搜索词和 Source Gap 提出建议，运营批准后才进入 Campaign KPI。观察面固定为 ChatGPT Search 与 Google。

第一版全部采用人工 Observation Import。每条导入保存查询、平台、结果面、AU 市场、语言、设备、时间、原始回答、引用 URL、截图/导出工件及可见模型信息，并复用 B2 的 Answer/Citation 真源。

默认协议：

- 每个批准查询、每个平台每次采集 3 个样本；
- 发布前连续 28 天按周采集并冻结 baseline；
- 验证 URL 发布后第 28、56、84 天按同一协议复测；
- 查询、地区、语言、设备、样本数、录入方式被冻结；
- 平台界面、模型、价格、库存、季节或竞品明显变化时标记 `confounded`。

核心指标：

```text
recommendation_share
product_mention_share
placement_citation_share
qualified_destination_coverage
verified_placement_coverage
competitive_delta
```

## 6. 内容、提示词与提交

业务代码只调用按投放形式划分的 Task Key：

```text
placement.owned.product_page
placement.owned.faq
placement.marketplace.listing
placement.youtube.video_script
placement.youtube.description
placement.editorial.pitch
placement.editorial.contributed_article
placement.creator.brief
```

每个不可变 Prompt Bundle 固化 Campaign、查询、产品事实、Destination Policy Snapshot、内容形式、披露/CTA/链接规则与 Prompt/Skill/Output Schema Release。提示词可独立版本化、测试、灰度和回滚，但无法绕过渠道政策、事实边界、权限或提交门禁。

`placement_packages` 是投稿或发布的不可变交付物，可包含正文、标题、metadata、图片需求、引用、披露、CTA 和人工提交说明。`placement_submissions` 只记录人工提交；只有 URL 经验证后才记为已发布和有效覆盖。

第一版只支持免费投稿和人工发布，不管理付款、采购、合同签署或自动浏览器发帖。

## 7. API 与前端

新接口统一使用 `/v1/geo`：

```text
POST /campaigns
GET  /campaigns/{id}/query-suggestions
POST /campaigns/{id}/queries/{query_id}/approve
POST /observations/manual-imports
GET  /publisher-catalog
POST /destinations
POST /placement-opportunities
POST /placement-opportunities/{id}/qualify
POST /placement-opportunities/{id}/briefs
POST /placement-packages
POST /placement-submissions
POST /placement-submissions/{id}/published-url
POST /placement-verifications
GET  /campaigns/{id}/measurements
```

Admin Web 提供 Campaign、Observations、Destinations & Opportunities、Placement Workspace 四个工作区。客户门户第一版只读展示 Campaign 状态、已验证 URL、推荐/引用趋势和待补充资料。

## 8. 实施与验收

实施顺序：

1. GEO Placement Domain、Capability、RLS、复合 FK 与系统级渠道目录。
2. Campaign、查询建议/批准、人工 Observation Import 与 Measurement。
3. 自动品牌资料导入、Destination-specific Brief、Evidence、Prompt Bundle 和 Package。
4. 人工 Submission、URL 回填、公开页面验证、通知、报告和客户只读视图。
5. 闭环稳定后才评估 Shopify/Amazon/社媒 connector；第三方社区继续采用人工、明确披露身份的任务和提交，不建设自动发帖 connector。

验收至少覆盖跨项目 FK/RLS、所有选定渠道均有持久任务、阻断任务不可生成或提交、`observed_only` 禁止提交、事实与来源类型约束、不可变 Package、人工 Observation 可重放、URL 验证失败不计入 KPI、28/56/84 测量冻结、以及报告不输出未经支持的因果结论。
