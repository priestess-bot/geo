# 当前项目 GEO 全项目功能完整性审计

> 审计日期：2026-07-18  
> 审计 ID：`geo-requirements-audit-20260718T083249Z`  
> 需求基线：`GEO_REQUIREMENTS.md`  
> 代码基线：`main` / `ff992dc0ad96d838c14147f60ea970a4f89f9772`  
> 审计对象：当前包含 171 条变更记录的脏工作树，未回退或覆盖既有修改  
> 判定口径：成熟 GEO 严格基线；文档、界面文案和源码字符串本身不能构成 `PASS`

## 1. 审计结论

当前项目**不能满足成熟 GEO 要求，也尚未达到完整的传统 SEO 等效能力**。按 `GEO_REQUIREMENTS.md` 的严格成熟度定义，判定为 **L0（具备真实专项闭环的功能型原型）**，尚不能进入 L1。

这个 L0 结论不表示项目只有伪功能。项目已经具备一套较完整、可运行的证据驱动型内容投放子系统：多租户/RBAC/RLS、项目和实体目录、Knowledge 导入处理、监测协议、九类投放目的地、Evidence Pack、Prompt Bundle、真实模型生成、Claim 清单、Maker-checker 审批、导出、人工发布记录、URL 校验以及 T28/T56/T84 复测。隔离环境的受控仿真验收已完整通过，真实 DeepSeek 生成也成功。

阻止其成为成熟 GEO 的关键问题是产品边界仍集中在“内容生成、人工渠道投放和人工观测”，而需求基线要求覆盖：

```text
抓取 -> 索引 -> 检索入选 -> 引用选择 -> 答案吸收/品牌表述 -> 曝光 -> 点击 -> 转化
```

当前项目缺少前半段的技术 SEO/爬虫/索引资格能力，也缺少后半段的流量、转化和收入归因。Google Search Console、Bing Webmaster Tools、GA4、Clarity、CDN/server log、CMS、CRM 和数据仓库连接器均未实现。

### 1.1 需求状态汇总

| 范围 | PASS | PARTIAL | FAIL | UNVERIFIED | N/A | 合计 |
|---|---:|---:|---:|---:|---:|---:|
| CAP-01..12 | 0 | 9 | 3 | 0 | 0 | 12 |
| FR-01..20 | 0 | 14 | 6 | 0 | 0 | 20 |
| GATE-01..08 | 0 | 4 | 4 | 0 | 0 | 8 |
| **总计** | **0** | **27** | **13** | **0** | **0** | **40** |

复合要求没有 `PASS`，不代表所有子功能均失败；它表示每个复合条目至少仍有一个成熟度必需环节缺失。项目内已有多项通过实际测试的子系统，见第 6 节。

### 1.2 硬门槛

| ID | 状态 | 结论 |
|---|---|---|
| GATE-01 | FAIL | 没有逐 URL 的抓取、渲染、索引、snippet/citation 资格审计，SEO 技术底座不可证明 |
| GATE-02 | FAIL | 没有按搜索、训练、用户实时取页分别管理 bot/robots/WAF 的用途策略中心 |
| GATE-03 | FAIL | 有 Evidence/Review，但未检查 cloaking、公开可见性、重复/低价值批量内容和真实性 |
| GATE-04 | PARTIAL | Claim 可追溯到 Evidence，缺来源真实性、时效、冲突和独立蕴含检查 |
| GATE-05 | PARTIAL | 原始观测与模拟边界可保存，但来源类型主要藏在自由 JSON，不能可靠防止混用 |
| GATE-06 | PARTIAL | 有冻结样本和多时间窗，但允许单样本，缺置信区间、分层重复和负收益检查 |
| GATE-07 | FAIL | 没有线索、转化、收入、留存或 Agent 任务结果指标 |
| GATE-08 | PARTIAL | RBAC/RLS、权利、保密、人工审批已实现；安全、备份、最小权限和内容治理仍有严重缺口 |

只要任一硬门槛失败，就不能判定为成熟 GEO。本项目目前有 4 个硬门槛失败。

## 2. 审计范围与方法

本次复查覆盖：

- `apps/api`、`apps/admin-web`、`apps/customer-web`、`packages/geo_core`、数据库迁移、脚本、OpenAPI、Docker/生产 Compose、CI 和测试。
- 需求基线中的 12 项能力、20 项成熟平台功能、8 项硬门槛及 Google/Bing/OpenAI/Anthropic/Perplexity 平台要求。
- 静态代码追踪、数据库结构与授权、隔离 Docker 运行、迁移、集成测试、生产构建、覆盖率、真实模型调用和浏览器取证。
- 当前脏工作树，而不是仅审查 `HEAD`。审计期间没有回退用户修改。

证据规则：

- `PASS` 必须同时存在可识别实现、数据/接口契约和可重复运行证据。
- 源码字符串断言、说明文档、模拟数据和 UI 占位不单独升级为 `PASS`。
- 受控仿真只证明内部工作流，不证明公网抓取、平台索引、真实引用或业务效果。
- 本次仅允许并执行一次付费 DeepSeek 成功调用；没有向任何第三方渠道自动发布内容。

## 3. 逐项需求追踪

### 3.1 CAP-01..12

| ID | 状态 | 当前实现与主要缺口 | 优先级 |
|---|---|---|---|
| CAP-01 技术资格 | FAIL | 仅有发布 URL 正文/披露/链接校验；无 robots、canonical、Sitemap、渲染 DOM、内链、移动体验、WAF/CDN 和索引资格审计 | P1 |
| CAP-02 需求研究 | PARTIAL | 有 Query、类型、locale、冻结监测协议；缺关键词/搜索量/排名、问题簇、fan-out、人物、漏斗、多轮和权重 | P2 |
| CAP-03 内容质量 | PARTIAL | 有抽取、Evidence、Claim、人工审批；缺原创性、意图匹配、专家/亲历真实性、页面体验和低价值检测 | P2 |
| CAP-04 证据治理 | PARTIAL | 有权利、引用元数据、不可变快照和 hash；缺来源真实性、时效、冲突、Claim-citation 蕴含检查 | P1 |
| CAP-05 实体体系 | PARTIAL | 有品牌、产品、竞品和市场；缺 Person/Place/Service、别名、关系、有效期及正文/Schema/Feed 一致性 | P2 |
| CAP-06 页面表达 | PARTIAL | 能解析 HTML/PDF/DOCX 和公开 HTML 文本；缺渲染 DOM、结构化数据、语义/ARIA、表格、字幕和 transcript 审计 | P2 |
| CAP-07 分发时效 | FAIL | 无 Search Console、Sitemap、IndexNow、Feed、真实 lastmod、更新/删除通知和重抓延迟 | P1 |
| CAP-08 站外权威 | PARTIAL | 有九类 Destination、竞品实体和渠道 Prompt；无站外提及发现、来源权威分析和虚假提及检测 | P2 |
| CAP-09 可见性度量 | PARTIAL | 有提及、推荐、引用、竞品差值和原始回答；观测靠人工导入，缺引用位置/准确性/吸收度/来源多样性和官方指标 | P1 |
| CAP-10 业务结果 | FAIL | 无 AI referral、lead、conversion、revenue、retention 或 Agent completion 数据模型 | P1 |
| CAP-11 实验体系 | PARTIAL | 有冻结分母、样本量、baseline/T28/T56/T84；缺对照组、区间、胜平负、最差结果、跨查询负面影响和漂移 | P2 |
| CAP-12 治理安全 | PARTIAL | 有 RBAC/RLS、Evidence 权利、Maker-checker 和非发布模拟；缺 Prompt Injection、YMYL、恶意 UGC、版权/隐私保留策略和全域审计 | P1 |

### 3.2 FR-01..20

| ID | 状态 | 当前实现与主要缺口 | 优先级 |
|---|---|---|---|
| FR-01 项目与工作区 | PARTIAL | 多项目、成员、角色、市场、品牌/产品/竞品和 RLS 已有；缺多域名/子域名、集中目标引擎/业务目标及统一审计 | P2 |
| FR-02 数据连接器 | FAIL | GSC、Bing WMT、GA4、Clarity、日志、CMS、CRM、warehouse 连接器全部缺失 | P1 |
| FR-03 逐 URL 技术审计 | FAIL | 没有 URL 技术审计实体、队列、结果 schema 或分层资格结论 | P1 |
| FR-04 AI 爬虫策略中心 | FAIL | 无 bot/use-policy matrix、robots/meta/WAF 生成验证、官方 IP 校验和策略审批版本 | P1 |
| FR-05 Prompt 与意图库 | PARTIAL | Query 建议、审批、冻结和 Campaign 关联已实现；缺问题簇、fan-out、人物/漏斗/来源/权重、多轮版本 | P2 |
| FR-06 内容库存 | PARTIAL | Knowledge source/document/chunk/fact/finding 提供有限库存；不是站点页面库存，缺作者、时间、主题、重复/过期/蚕食/意图缺口 | P2 |
| FR-07 实体与事实一致性 | PARTIAL | 有 Catalog entity、canonical URL、属性和市场；缺关系图、别名、冲突、有效期和跨载体一致性检查 | P2 |
| FR-08 论断与证据治理 | PARTIAL | 有 Evidence hash/rights/confidentiality、Claim support 和双人审批；Fact 提取偏启发式，缺真实性/时效/蕴含和 YMYL 加强流程 | P1 |
| FR-09 跨引擎观测 | PARTIAL | 可保存回答、引用、模型、UI、时间并重复采样；无采集器，来源模式非一等字段，Bing/Claude 缺平台枚举 | P1 |
| FR-10 答案品牌引用分析 | PARTIAL | 有 mention/recommendation/product/competitor/citation 指标及原始回答；缺情感、事实准确性、遗漏、引用位置/蕴含、来源域和吸收度 | P2 |
| FR-11 竞品与来源缺口 | PARTIAL | 有 competitor boolean 和 competitive delta；缺竞品页面/来源类型/问题覆盖及抓取到转化分层定位 | P2 |
| FR-12 可解释建议 | FAIL | 无建议实体、证据等级、影响链路、工作量/价值/置信度排序和“无需修改/证据不足”结论 | P2 |
| FR-13 内容工作流 | PARTIAL | Brief、Evidence Pack、Prompt、Package、Claim、Maker-checker、人工批准完整；缺 CMS 草稿、重复/低价值/堆砌/伪 Schema/Injection/YMYL 门禁 | P1 |
| FR-14 发布与分发 | PARTIAL | 有人工 Publication/Submission、URL verification、重试和版本；无 CMS 真发布、Schema/canonical/Sitemap/robots 复验、IndexNow、Feed 和删除通知 | P1 |
| FR-15 实验与版本管理 | PARTIAL | 有不可变 package、baseline/多时间窗 snapshot 和 hash lineage；缺页面实验、对照组、统计区间、最差结果、跨查询影响和模型漂移 | P2 |
| FR-16 看板与告警 | PARTIAL | Admin/customer 指标、报告和 dashboard 已有；无告警，技术/官方/抽样/流量/业务层未完整分离 | P1 |
| FR-17 流量与业务归因 | FAIL | 无 referrer、UTM、session、conversion、revenue 或 CRM 结构 | P1 |
| FR-18 治理、安全与合规 | PARTIAL | OIDC/session/CSRF、RLS、权利/保密、SSRF 防护和人工审批已有；缺保留/版权策略、内容安全、Injection 和全域审计，且有 P0 基础设施问题 | P0 |
| FR-19 Agent 可执行性 | FAIL | 无 Agent 任务、步骤、错误分类或完成率；现有 URL verifier 不能替代 Agent 验收 | P2 |
| FR-20 API、导出与复核 | PARTIAL | 有 OpenAPI、Package JSON artifact、hash/method version 和 job replay；缺通用导出、warehouse sync、删除、重算和数据质量 API | P1 |

### 3.3 GATE-01..08

| ID | 状态 | 证据摘要 | 优先级 |
|---|---|---|---|
| GATE-01 | FAIL | 无完整 SEO crawl/render/index qualification 实现 | P1 |
| GATE-02 | FAIL | 无 Search/Training/User-fetch 三用途策略模型 | P1 |
| GATE-03 | FAIL | 内容审批未验证公开可见性、cloaking、重复/低价值滥用；真实性风险由调用方自报 | P1 |
| GATE-04 | PARTIAL | Claim 强制引用 Evidence，审批要求重要事实受支持；无独立来源与引用蕴含校验 | P1 |
| GATE-05 | PARTIAL | Observation 原文与 hash 可保留，simulation 明示 non-causal；来源模式缺结构化强约束 | P1 |
| GATE-06 | PARTIAL | 有冻结 protocol 和多窗口；`sample_size=1` 合法，未强制重复/区间/分层 | P2 |
| GATE-07 | FAIL | 业务转化指标完全缺失 | P1 |
| GATE-08 | PARTIAL | 权限、数据隔离和人工审核已有；备份、最小权限、内容安全和审计不足 | P0 |

## 4. 平台接入完整性

| 平台 | 状态 | 已有能力 | 核心缺口 |
|---|---|---|---|
| Google Search / AI | FAIL | 仅有 Google Search / AI Overview 平台枚举和人工观测 | 无 Googlebot/WAF、snippet 指令、canonical/Sitemap/渲染、GSC 普通及 AI 报表、Google-Extended 分离 |
| Bing / Copilot | FAIL | 无可复用平台实现 | 无 Bingbot、Bing 平台枚举、IndexNow、AI Performance、Places 和 robots 差异审计 |
| OpenAI / ChatGPT | FAIL | 有 `chatgpt_search` 人工观测类型 | 无 OAI-SearchBot/GPTBot/ChatGPT-User 用途策略、官方 IP/WAF 检查和 `utm_source=chatgpt.com` 归因 |
| Anthropic / Claude | FAIL | 无 | 无 Claude-SearchBot/ClaudeBot/Claude-User 平台、用途策略和日志审计 |
| Perplexity | FAIL | 有 `perplexity` 人工观测类型 | 无 PerplexityBot/User、IP/WAF、robots 限制声明和真实采集来源治理 |

当前平台枚举或 Prompt 模板不能作为平台接入完成的证据；必须有策略、采集/官方数据、错误和新鲜度记录及运行验收。

## 5. 详细发现与改进意见

### P0：安全、数据诚信或生产不可用

#### F-001 生产环境阻断必要外部访问

- 关联：`FR-09`、`FR-14`、`FR-18`、`GATE-08`
- 证据：`infra/compose.prod.yml:390` 将 `backend` 标为 `internal: true`；Internal API 和 Worker 只加入该网络。
- 运行证据：隔离复现中普通 bridge 访问 `https://example.com` 返回 HTTP 200，internal network DNS 失败且退出码为 1。
- 影响：OIDC discovery/JWKS、DeepSeek、Knowledge URL 导入和发布 URL 校验在生产拓扑中均无法工作。
- 改进：新增受控 egress 网络或代理，按 OIDC、模型供应商、目标抓取和 URL verifier 分别维护目的地 allowlist、DNS/IP 策略和审计日志。
- 验收：在与生产一致的 Compose 上分别完成 OIDC 登录、JWKS 轮换、一次模型调用、URL 导入和发布校验；未授权域名必须失败并可观测。

#### F-002 损坏备份可被恢复冒烟误判为成功

- 关联：`FR-18`、`FR-20`、`GATE-08`
- 证据：`scripts/restore_geo_backup_smoke.sh:26` 使用 `gunzip | docker compose exec`，`/bin/sh` 未启用 `pipefail`；未执行 `sha256sum -c`，只检查 `pg_catalog.pg_tables`。
- 运行证据：损坏 gzip 输出 `not in gzip format`，管道退出码仍为 0；catalog 检查为真，但 public tables 为 0。
- 影响：灾备演练可能报告成功而业务数据完全没有恢复；MinIO 也未恢复验证。
- 改进：恢复前验证签名清单；显式检查每段管道状态；校验 Alembic head、预期业务表、行数/FK/hash；逐对象恢复和核验 MinIO。
- 验收：正常备份恢复通过；截断 DB、篡改 checksum、缺 MinIO 对象、错密钥四种故障均必须非零退出并指出具体对象。

#### F-003 备份默认权限与加密不安全

- 关联：`FR-18`、`GATE-08`
- 证据：`scripts/backup_geo_data.sh:18`、`infra/backup/backup-object-store.sh:15` 未设置 `umask 077`、`chmod` 或加密。
- 运行证据：本地 `umask=0002` 时生成文件 mode 为 `664`。
- 影响：数据库和对象存储备份可能被同组用户读取，且没有覆盖 DB+MinIO 的签名完整性链。
- 改进：强制 `umask 077`，检查 owner/mode，使用 KMS/age/GPG 或加密备份存储，生成覆盖所有对象的签名 manifest。
- 验收：CI/运维测试断言文件不超过 `0600`、目录不超过 `0700`；未解密或 manifest 不匹配时无法恢复。

#### F-004 Knowledge URL 抓取存在 DNS rebinding TOCTOU

- 关联：`CAP-12`、`FR-18`、`GATE-08`
- 证据：`packages/geo_core/geo_core/knowledge/processing.py:199` 先调用 `_require_public_url()` 解析/校验，再让 `httpx` 对同一 hostname 独立解析连接。
- 影响：攻击者可在校验和连接之间改变 DNS 结果，访问内网、metadata endpoint 或 loopback。该模块当前还是未提交代码，风险容易绕过正式评审。
- 改进：复用 `placements/url_verifier.py` 的 IP pinning 思路；每次 redirect 重新校验并绑定已验证 IP，同时校验证书 hostname、响应 peer IP 和地址族。
- 验收：加入 rebinding、双栈、CNAME、redirect-to-private、decimal/IPv6 地址、metadata IP 和 DNS 变化测试；所有私网目标必须被阻断。

### P1：硬门槛或核心业务闭环

#### F-005 缺少传统 SEO 与逐 URL 技术资格底座

- 关联：`CAP-01`、`FR-03`、`GATE-01`
- 证据：`packages/geo_core/geo_core/placements/url_verifier.py` 仅验证发布 URL、可见文本、披露和链接；没有 crawler/render/index audit 模型与 API。
- 影响：无法回答页面是否可抓取、可渲染、可索引、可摘要、可引用，也就无法证明达到 SEO 等效。
- 改进：建设 URL inventory、raw/rendered fetch、robots/meta/X-Robots、canonical、Sitemap、内链、状态码、软 404、WAF/CAPTCHA 和移动体验审计。
- 验收：对至少一套包含 2xx/redirect/noindex/nosnippet/JS-only/canonical conflict/blocked bot 的 fixture site 输出分层资格结论并通过浏览器与 HTTP 双验收。

#### F-006 官方与一方数据连接器全部缺失

- 关联：`FR-02`、`CAP-07`、`CAP-09`
- 证据：依赖、源码、配置和 UI 中没有 GSC、Bing WMT、GA4、Clarity、CDN/server log、CMS、CRM 或 warehouse connector。
- 影响：系统只能依赖人工输入，无法提供官方可见性、流量、同步新鲜度和业务归因。
- 改进：建立统一 Connector 契约，保存授权范围、cursor、同步时间、watermark、失败原因、新鲜度和原始 payload hash；先实现 GSC、Bing WMT、GA4、server log。
- 验收：OAuth/权限失效、限流、增量同步、重复数据、时区、字段缺失和回填均有集成测试；官方数据与推算数据使用不同 schema/source type。

#### F-007 没有业务结果与 AI referral 归因

- 关联：`CAP-10`、`FR-17`、`GATE-07`
- 证据：数据库/API 无 referrer、UTM、session、lead、conversion、revenue、retention、CRM outcome 或 Agent completion 模型。
- 影响：最多证明提及/引用变化，不能证明合格线索、收入或任务完成，硬门槛直接失败。
- 改进：定义 first-party event、AI referrer normalization、UTM、landing page、conversion、CRM stage、revenue 和 assisted attribution；显式标注 last-click 局限。
- 验收：从 `utm_source=chatgpt.com`/referrer 到 session、lead、CRM outcome 和 campaign/content/version 可完整回溯；零点击影响不得伪造成转化。

#### F-008 缺少爬虫用途策略中心

- 关联：`CAP-12`、`FR-04`、`GATE-02`
- 证据：无 bot/use-policy matrix、robots/meta/WAF 生成器或版本审批模型。
- 影响：搜索收录、训练和用户实时读取无法独立授权；容易把训练 bot 当搜索可见性证据。
- 改进：为 Google/Bing/OpenAI/Anthropic/Perplexity 建立 bot identity、purpose、robots rule、WAF/IP、scope、approval 和 effective version 模型。
- 验收：同一域名可分别允许 SearchBot、拒绝 TrainingBot、允许/限制 User fetch；配置与实际 HTTP/WAF/log 结果一致并保留变更审计。

#### F-009 跨引擎观测依赖人工导入，来源边界不够强

- 关联：`CAP-09`、`FR-09`、`GATE-05`
- 证据：Monitoring 可保存 raw answer/citations/model/UI/time，但无真实 collector；measurement job 结束在 `awaiting_manual_samples`；平台枚举缺 Bing/Copilot 和 Claude。
- UI 证据：`ObservationWorkspace.tsx:38` 默认 eligible、URL 状态 unknown、模型默认 `deepseek-chat`，成功样本不强制完整原始回答。
- 影响：真实界面、API 代理、人工抄录和内部模拟可能被错误比较，单次或低质量样本可能进入报表。
- 改进：将 `official`、`real_ui_sample`、`provider_api`、`manual_import`、`simulation` 设为受约束一等字段；补齐模型/界面/地区/语言/搜索开关/引用顺序/采集器版本。
- 验收：缺原始回答、来源类型或运行参数时样本不得 eligible；各来源分母分开；模拟数据不能进入官方 KPI。

#### F-010 证据真实性、时效与 Claim-citation 蕴含检查不足

- 关联：`CAP-04`、`FR-08`、`GATE-03`、`GATE-04`
- 证据：Catalog/Evidence 保存 rights、hash、citation metadata，Claim 审批要求 supported；但 `validate_authenticity()` 忽略 consumer experience，风险由调用方自报。
- UI 证据：`BriefPromptPanel.tsx:38` 允许“无证据最高级表述”，消费者体验、来源和权利可自由文本录入；编辑 Claim 后可保留旧 support/evidence。
- 影响：真实来源不能保证支持对应表述，过期或冲突证据可能继续发布，存在虚假评价和不实宣传风险。
- 改进：增加 source fetch/identity/freshness/conflict、claim-evidence entailment、edited-claim invalidation、superlative policy 和 maker-checker 独立性规则。
- 验收：篡改 Claim、过期证据、冲突来源、伪造 URL、无直接支持和自审均被拒绝；审核界面显示原文、证据片段和差异。

#### F-011 发布链只记录人工提交，不具备真实分发闭环

- 关联：`CAP-07`、`FR-14`
- 证据：有 Publication Request、Submission、URL verification 和重试；无 CMS draft/publish、Schema/canonical/Sitemap/robots 复验、IndexNow、Feed 或删除通知。
- 运行证据：唯一一次 DeepSeek 调用成功并生成已批准 package，但后续 `publication.verify` 因 `required_disclosures` 缺失进入 `retry_wait`。
- 影响：成功生成不能保证成功发布、可抓取、可索引或可引用；当前 live 全链验收未完成。
- 改进：先修正 publication payload 契约和必填披露，再实现 CMS adapter、post-publish technical audit、IndexNow/Sitemap/feed submission 与首次抓取/可见时间。
- 验收：真实生成 package 在受控测试 CMS 中完成草稿、人工批准、发布、披露、canonical/Schema/Sitemap/robots 复验；缺披露必须在提交前阻断而不是异步重试。

#### F-012 多 Campaign 页面存在跨上下文串数据

- 关联：`FR-01`、`FR-15`、`FR-18`
- 证据：`data.ts:56` 分别取项目内第一条 Campaign/Protocol；`GeoShell.tsx:19` 切换 Campaign 保留旧 `protocol_id`、`destination_id`、Job、Publication 和 Submission。
- 运行证据：Playwright 切换 Campaign 后正文变化，但 URL 仍保留前一 Campaign 的 `destination_id`；截图为 `browser/admin-geo-campaign-switched-desktop.png`。
- 影响：操作者可能查看或修改错误 Campaign 的目的地、协议、任务或发布记录，造成审计链污染。
- 改进：以 Campaign 为根重新派生 protocol/destination/opportunity/job/publication；无效参数立即清除；所有 API 查询显式带并校验上下文。
- 验收：至少两 Campaign、各两目的地的浏览器 mutation 测试，切换后 URL、表格、动作 payload 和数据库写入均只属于目标 Campaign。

#### F-013 Knowledge 到正式 Evidence 的 UI 工作流断裂

- 关联：`FR-08`、`FR-13`
- 证据：`EvidencePanel`/`createEvidenceAction` 存在但 `WorkbenchShell.tsx:103` 未渲染；Knowledge 只批准/拒绝 Fact，不能在 UI 转正式 Evidence。
- 附加缺陷：`scripts/promote_approved_knowledge_fact.py` 接受 `public_domain`，而 Domain 枚举使用 `public_reference`。
- 影响：普通运营人员无法从导入知识闭合到 Evidence Pack，只能依赖脚本且脚本可能因枚举不一致失败。
- 改进：设计 Fact -> Evidence proposal -> rights/citation review -> Evidence approved 流程；复用一个共享枚举契约。
- 验收：浏览器从 URL/文件导入到 approved fact、evidence、pack、claim 全链通过；无权利或无可公开引用时阻断。

#### F-014 Prompt 与渠道绑定及完成度判断可能错误

- 关联：`FR-05`、`FR-13`、`GATE-05`
- 证据：`data.ts:61` 默认选项目第一条 Skill，`BriefPromptPanel.tsx:15` 取其最新 Release，而不是当前 Opportunity/channel binding；`GeoShell.tsx:57` 只以 `destinations.length >= 9` 判断渠道完成。
- 影响：正式 Bundle 可能使用错误渠道 Prompt；重复目的地也能让完成度虚高。
- 改进：从 Campaign Opportunity -> Destination policy -> Skill binding -> approved Release 单向解析；就绪度检查九个唯一渠道、政策状态、证据和阻断。
- 验收：为九渠道配置不同 Prompt release，逐一生成时 hash/版本与当前渠道一致；重复或 blocked destination 不计入完成度。

#### F-015 CI 可出现假绿，当前集成契约已有 3 个失败

- 关联：`FR-18`、`FR-20`、`GATE-08`
- 证据：`.github/workflows/ci.yml:45` 未提供 acceptance 所需三组 DB URL；`Makefile:135` 选择 `live` marker，但唯一 DeepSeek 测试没有该 marker，导致 0 collected/退出 5。
- 运行证据：隔离 PostgreSQL 执行 integration + engineering governance 为 `11 passed, 3 failed`：迁移 checksum 仍只期待 0001-0007；acceptance 仍期待 1 条成功 model log，实际为 10；worker outbox 批次受共享数据污染。
- 影响：CI 的“完整 integration/acceptance/live”标签不能证明真实覆盖，迁移、并发和模型日志回归可能进入主干。
- 改进：CI 创建独立 DB/Schema，每类测试使用唯一 project/tenant；禁止环境缺失时 skip-success；修正 marker、迁移 ledger 期望和 model log 契约。
- 验收：CI 明确显示 13 个 integration 均执行且 0 skip；live 测试在无密钥时显式“未请求”，在受控 job 中恰好收集 1 项；并行重复 10 次无污染。

#### F-016 Acceptance 脚本与真实 worker/relay 存在竞态

- 关联：`FR-15`、`FR-20`
- 运行证据：完整隔离栈运行 worker/relay 时，deterministic acceptance 报 `simulation artifact did not finalize`；停止二者后同一流程通过。脚本同步 dispatcher 与后台消费者争抢同一 artifact job。
- 影响：验收工具无法代表正常部署拓扑，可能随机失败或消费顺序不同，掩盖真实任务语义。
- 改进：接受两种明确模式：外部 worker 驱动并轮询，或 inline dispatcher 且禁用 worker；使用 run-scoped queue/project 和幂等结果等待。
- 验收：两种模式分别连续运行 20 次；无重复执行、丢 artifact、错误 claim 或跨 run outbox 消费。

#### F-017 数据库角色最小权限不足

- 关联：`FR-01`、`FR-18`、`GATE-08`
- 运行证据：`geo_app` 与 `geo_worker` 对 85 张表均有 SELECT/INSERT/UPDATE/DELETE，`geo_readonly` 对 85 张表均可 SELECT；worker 可改身份/会话/成员/审计，readonly 可读 session hash。86 张表中仅 80 张启用 RLS。
- 影响：服务被攻破后横向权限过大，客户会话和身份数据暴露面不必要。
- 改进：按服务和用例建立 table/function grant matrix，撤销 default blanket grants；敏感表隔离 schema，并为 runtime role 添加负向测试。
- 验收：worker 不能 CRUD tenant/identity/session/membership/audit；readonly 看不到 session secret/hash；每个角色的允许和禁止矩阵由 CI 实测。

#### F-018 可观测性、readiness 和生产预检不可信

- 关联：`FR-16`、`FR-18`
- 运行证据：两个 API `/health`、`/ready` 为 200，`/metrics` 为 404；`infra/prometheus/prometheus.yml:6` 抓取不存在的 `api:8000`；应用无 OTel/Prom instrumentation，collector 仅 debug。
- 附加问题：`/ready` 只证明 adapter 已构造；worker/relay/web 无 healthcheck；production config 可在缺 secrets、占位 digest 或 tag-only image 时通过。
- 影响：部署可能显示健康但 DB/MinIO/Valkey/OIDC 不可用；关键任务、同步和错误无告警。
- 改进：深度 readiness、正确 metrics endpoint/target、结构化日志、trace/correlation、队列/lease/outbox 指标、Alertmanager/Grafana；生产 preflight 强制 secret、digest、resource/log policy。
- 验收：逐一关闭 DB/MinIO/Valkey/OIDC 时 readiness/告警正确变化；Prometheus targets 全绿；任务失败能从 trace 定位到 project/job 且日志不泄露客户 URL/secret。

### P2：成熟能力和产品质量

#### F-019 问题体系、内容库存和实体图谱过薄

- 关联：`CAP-02`、`CAP-05`、`FR-05`、`FR-06`、`FR-07`
- 缺口：没有 query cluster/fan-out/persona/funnel/multiturn；Knowledge 不是站点 URL inventory；实体缺 Person/Place/Service、关系、别名、有效期和跨正文/Schema/Feed 一致性。
- 改进：统一 Query Graph、Content Inventory、Entity/Fact Graph，所有节点带来源、版本、市场、有效期和冲突状态。
- 验收：从一个业务目标可追踪到问题簇、页面、实体、事实、Evidence、观测和业务结果；冲突/过期会触发阻断或告警。

#### F-020 没有可解释建议与“不修改”机制

- 关联：`FR-11`、`FR-12`
- 缺口：当前指标和报告不能把差距定位到抓取、索引、主题、证据、实体、站外权威或转化，也没有 recommendation 数据模型。
- 改进：建议必须保存 issue、evidence level、impact chain、page/query cluster、risk、effort、business value、confidence、validation plan 和 decision。
- 验收：同一分析可产生 hard blocker、gap、experiment、optional、no-change、insufficient-evidence 六类结果；每条能回溯原始输入和规则版本。

#### F-021 实验统计、分层 KPI 与告警不完整

- 关联：`CAP-11`、`FR-15`、`FR-16`
- 缺口：允许 `sample_size=1`，没有置信区间、胜平负、最差结果、跨查询负收益和模型漂移；无 crawler/index/citation/misstatement/competitor/freshness/sync 告警。
- 改进：按 engine/model/locale/region/query cluster 分层重复；把技术、官方、观测、答案、流量和业务 KPI 拆表；建立阈值、基线、抑制和告警处置记录。
- 验收：不满足最小样本时禁止稳定性结论；报告展示区间和最差结果；模拟、官方和真实抽样不能合并分母。

#### F-022 Admin GEO 页面存在请求瀑布与整页重验证放大

- 关联：`FR-01`、`FR-16`
- 证据：`data.ts:35` 的完整项目渲染最多约 35 个 GEO 请求和 7 个基础请求，且有多轮串行依赖；mutation 后整页 revalidation 重复成本。
- 影响：数据增大或 API 延迟时运营页面响应恶化，后台接口被放大。
- 改进：按 workspace 聚合 BFF endpoint，并行独立 fetch，按 Campaign/阶段 lazy load；局部 mutation 更新和缓存失效。
- 验收：以完整数据 fixture 测量 TTFB/请求数；首屏请求降至可控常数，Campaign 切换和单一 mutation 不重新请求无关模块。

#### F-023 Customer 最新指标和 Campaign 上下文可能错误

- 关联：`FR-15`、`FR-16`
- 证据：客户摘要直接取后端未保证时间排序数组的 `[0]`；Campaign ID 在页面不可见且导航中丢失。
- 影响：客户可能看到旧指标却被标为“最新”，多 Campaign 数据语义不清。
- 改进：后端按明确时间/窗口排序并返回 `latest`，客户侧提供 Campaign selector/context，并在全部链接保留筛选。
- 验收：乱序插入多 Campaign/多窗口数据后，摘要、指标、投放和报告始终显示同一选定 Campaign 的最新有效版本。

#### F-024 移动端表格与可访问性仍不完整

- 关联：`CAP-06`、`FR-19`
- 运行证据：文档级无横向溢出且 focus outline 存在，但移动端 tabs 为 679/338 px、Campaign select 为 403/274 px、表格为 351/322 inside 278 px，后续内容缺少滚动提示，部分中文表头逐字换行。
- 改进：移动端使用可发现的横向滚动/固定首列或列表化布局；补齐表格 caption/header 关系、aria-live、键盘和屏幕阅读器验收。
- 验收：Chromium/Firefox/WebKit，390/768/1440，键盘、axe 和屏幕阅读器关键流通过；长中文/英文、空/错误/大数据状态无内容遮挡。

#### F-025 测试覆盖率和前端测试深度不足

- 关联：`FR-18`、`FR-20`
- 运行证据：综合 branch coverage 为 56.21%，statement 61.10%，branch 26.93%，缺 3498 行/1096 分支；33 个文件低于 50%，`membership_postgres.py`、`postgres_writes.py`、`knowledge/worker.py` 为 0%。
- 现状：前端多数测试是源码字符串断言；没有收集到 `browser` marker 测试。Knowledge 有 7 个单测，但无 PostgreSQL/worker/MinIO/API 集成测试。
- 改进：按风险设置真实 coverage gate；优先覆盖身份/权限、任务、Knowledge worker、发布、迁移、并发和失败补偿；加入组件/E2E/权限/错误/跨浏览器测试。
- 验收：关键模块 branch >=90%，全仓阈值逐步提高且 CI 失败生效；测试报告明确列出执行/跳过数，环境缺失不允许假绿。

#### F-026 Prompt Injection、YMYL、版权/保留策略不完整

- 关联：`CAP-12`、`FR-08`、`FR-13`、`FR-18`、`GATE-08`
- 缺口：没有隐藏 AI 指令、恶意 UGC、伪 Schema、低价值批量内容和 YMYL 专门门禁；缺统一数据保留、删除、版权和许可证策略。
- 改进：将 untrusted content 与 system/prompt 分隔，扫描/标记 injection 和 schema leakage；按内容风险决定 reviewer 资格、证据要求、保留和删除策略。
- 验收：建立攻击 corpus 和 YMYL fixture；模型、草稿、发布前各层都不能执行或传播隐藏指令，且删除/保留策略可审计。

#### F-027 通用导出、删除、重算和数据质量能力缺失

- 关联：`FR-20`
- 证据：目前主要导出 Package artifact；没有原始/聚合全域导出、warehouse sync、删除、重算和质量检查 API。
- 改进：建立 versioned export manifest、lineage、schema version、recompute job、tombstone/delete workflow 和 data quality result。
- 验收：任一 dashboard 数字可下载原始记录并复算；删除请求覆盖 DB、对象存储、缓存和下游导出；旧版本迁移可回滚并校验 hash。

## 6. 已验证的现有能力

以下结果证明项目有较强工程基础，但不能替代缺失的 GEO 业务能力：

| 验证 | 结果 |
|---|---|
| `make lint` 与扩展 Ruff | PASS |
| Python typecheck | PASS，122 个源文件 |
| pnpm typecheck | PASS，6 个 workspace |
| Admin/Customer production build | PASS，分别 12/7 个路由 |
| OpenAPI stable contract | PASS，2 个 surface、6 个测试 |
| Architecture/infra tests | 23 passed |
| 非 integration Pytest | 239 passed，2 skipped，13 deselected |
| Docker cold build | API/Admin/Customer 全部通过 |
| Alembic | 单 head：`0010_campaign_destinations`；当前 10 个 SQL checksum 与 ledger 一致 |
| 隔离 PostgreSQL integration | 11 passed，3 failed，0 skipped |
| 受控 simulation acceptance | PASS：9 渠道、9 任务、Claim 完整、双人审批、无外部自动发布、T28/T56/T84 完成 |
| DeepSeek 实调用 | PASS：恰好 1 次 provider success，`deepseek-v4-flash`，2030 prompt / 1422 completion tokens，2 个 supported claims，package approved |
| DeepSeek 后续发布链 | FAIL：`publication.verify` 因缺 `required_disclosures` 进入 `retry_wait`；未再次调用模型 |
| 浏览器静态 smoke | 13 路由 x 3 viewport，40 张截图；无 console/page/5xx/overlay/整页 overflow/focus 失败 |
| 带数据浏览器 runbook | 44 个 Admin/Customer 视图，0 failure；Chromium 桌面+移动 |

浏览器插件在本环境不可用，因此按测试技能的回退规则使用本地 Playwright。证据目录：

`artifacts/runs/geo-requirements-audit-20260718T083249Z/`

敏感的客户邀请令牌文件已在截图完成后删除。模型 API key 仅通过文件路径注入，未写入报告。

## 7. 建议整改路线

### 阶段 A：先消除生产和证据可信度风险

1. 修复受控 egress、DNS rebinding、备份权限和恢复校验。
2. 修复 CI 假绿、3 个 integration 失败、acceptance worker 竞态和 DeepSeek 发布披露契约。
3. 收紧数据库 runtime role，补深度 readiness、metrics、trace、告警和生产 preflight。

退出条件：P0 全部关闭；完整 integration 0 skip/0 fail；正常部署拓扑的 simulation/live-safe 工作流可重复；灾备故障注入全部正确失败。

### 阶段 B：达到 L1 SEO 等效

1. 建设站点 URL inventory 和逐 URL raw/rendered 技术审计。
2. 实现 robots/meta/WAF crawler purpose matrix。
3. 接入 GSC、Bing WMT、GA4、server logs，并实现 Sitemap/lastmod/IndexNow 生命周期。
4. 建设内容库存、Query cluster、实体/事实一致性基础模型。

退出条件：GATE-01、GATE-02 通过；至少一个真实站点能从 crawl 到官方 Search 数据完整复核；不得依靠人工 JSON 作为官方数据。

### 阶段 C：达到 L2 GEO 可用

1. 建设结构化真实抽样/代理/模拟来源边界及跨引擎观测。
2. 实现答案、引用位置/蕴含/准确性、来源多样性、品牌表述和竞品缺口分析。
3. 建设可解释 Recommendation 模型，允许 no-change/insufficient-evidence。
4. 完成 CMS 发布、post-publish 技术复验和首次抓取/可见时间。

退出条件：至少 Google/Bing/OpenAI 三个平台具备可复核的数据或合规抽样；一条建议可从原始证据追踪到发布后复测。

### 阶段 D：达到 L3 成熟 GEO

1. 接入 AI referral、转化、CRM、收入和留存。
2. 实现实验对照、重复采样、区间、最差结果、负收益和漂移。
3. 完成分层 KPI、告警、YMYL/Injection/版权/保留策略及统一审计。
4. 完成通用导出、重算、删除、warehouse sync 和 Agent 任务闭环。

退出条件：8 个硬门槛全部 `PASS`；40 项需求逐条有代码、数据和可重复运行证据；平台、真实抽样、模拟与业务数据严格分层。

## 8. 复查优先顺序

建议把下一轮复查设置为可执行门禁，而不是重新做宽泛打分：

1. `P0/security-recovery-egress`：F-001..F-004 全部关闭。
2. `P1/ci-runtime-integrity`：F-015..F-018 全部关闭。
3. `L1/seo-foundation`：CAP-01、CAP-07、FR-02、FR-03、FR-04、GATE-01、GATE-02。
4. `L2/observation-evidence`：FR-08..FR-14、GATE-03..GATE-06。
5. `L3/business-governance`：CAP-10、FR-16..FR-20、GATE-07、GATE-08。

只有在阶段退出条件实际通过后，才提升成熟度等级。不得用新页面数量、Prompt 数量、单次模型结果或内部模拟分数替代硬门槛。

## 9. 审计限制

- 未对真实 Google/Bing/OpenAI/Anthropic/Perplexity 站长账户执行授权和数据拉取，因为项目没有相应连接器和本次未提供账户授权。
- 没有向真实 CMS、社区、媒体或其他第三方渠道发布内容。
- 仅执行一次付费 DeepSeek 成功调用；发布校验失败后没有重试模型调用。
- 浏览器覆盖 Chromium；Firefox/WebKit、完整 screen reader、真实多角色 mutation 和大数据压力仍需后续补测。
- 结论针对审计开始时冻结的当前脏工作树；后续修改必须重新运行受影响门禁。

