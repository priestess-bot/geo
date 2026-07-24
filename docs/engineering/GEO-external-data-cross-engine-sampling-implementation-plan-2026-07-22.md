# GEO 外部数据与跨引擎采样加速实施计划

> 计划日期：2026-07-22
> 修订日期：2026-07-24（第 3 次修订）
> 计划状态：`PLANNED`
> 执行周期：与[加速总路线图](GEO-next-phase-six-month-roadmap-2026-07-21.md)的 `T+0`--`T+5` 同步；`M0`--`M6` 仅为稳定 Gate 标签
> 专项范围：Connector Core、GSC、GA4、Google/Bing 官方报告、五类 Provider/Grounded API、消费者 AI 界面、澳洲代理、Sampling Core 和外部观测交付
> 上位合同：总路线图第 2、3、4、6.1、6.2、7.1、7.2、9、10、11 节
> 完成原则：真实账号、真实数据、真实页面和不可变证据；fixture 只用于确定性回归和 B 轨完成证据，不冒充 A 轨 live
> 第 2 次修订变更：Task 改用稳定 egress policy/cohort，实际出口验证下沉到 Attempt/Observation；live UI 强制先授权再 admission；增加 External Data Snapshot/Report/Approval；扩展单项 evidence manifest 与 DoR/DoD applicability
> 第 3 次修订变更：保持专项范围、来源、样本、授权、安全和验收合同不变，废止六个月/月度排期；所有可由 Agent 完成的实现与自动化验证纳入 `T+0`--`T+5` 连续窗口。真实凭据、授权决定、人工明审、独立 verifier 和 live evidence 于 `T+0` 并行开始，未就绪只阻断对应 Gate，绝不降低或伪造验收。

## 1. 目标、边界和文档职责

本专项在 `T+0`--`T+5` 内完成可由 Agent 交付的实现与自动化验证，并在真实依赖就绪后以原门槛验收一条外部观测链：

```text
授权/凭据/澳洲出口
  -> Connector、Provider 或消费者 UI 的冻结执行
  -> raw-first 不可变工件 + checkpoint/attempt
  -> typed projection / Parsed UI Observation
  -> 完整 SourceStratum + eligible 判定
  -> Sampling Run 完成度与独立分母
  -> Metric/Alert/Customer 的已批准真实输入
```

加速实施完成定义：

- GSC 和 GA4 在一个真实 property 上完成首次、增量、回刷、撤权恢复和 freshness 验收。
- Google/Bing 官方报告以真实文件完成 immutable import、schema version、typed projection 和重复检测；没有单次回答时不伪造 Observation。
- OpenAI Web Search、Gemini Grounding、Perplexity、Microsoft Grounding with Bing、Kimi API 五类 adapter 使用真实凭据完成独立 live canary；Kimi 的 Search 能力按发布时官方能力显式冻结，不能靠名称推断。
- Google AI Overviews、Google AI Mode、Bing Copilot 三个首批消费者 surface 各有独立 Surface Release；按授权结论完成 A 轨 live automated capture 或 B 轨 fixture + manual UI。
- 用户提供的澳洲代理/网关可通过 Secret Reference 使用；每次 eligible capture 都能证明目标页面与前后验证使用同一 sticky lease 的澳洲出口。
- `official_report_import`、`provider_api`、`proxy_grounded_api`、`manual_ui`、`automated_ui` 和 `synthetic` 始终保持不同身份、工件、资格规则和分母。
- 所有结果沿用现有 Durable Job、lease/fencing、broker outbox、MinIO、model call log、RLS/RBAC 和 Customer approved projection，不建立平行基础设施。

本专项不负责语义指标公式、归因账本或建议生成；它负责向这些模块交付版本化、可追踪、资格明确的外部输入。统计结论仍以总路线图第 7.3/7.4 节为准，Customer 可见性仍以总路线图为准。

## 2. Checklist 规则和验收角色

- `[ ]` 表示尚未被证据证明；代码合并、页面出现或 mock 通过不能自动勾选。
- `[x]` 只能在 engineering owner 和 independent verifier 都签字后使用。
- 每项必须按总路线图第 1.3 节先冻结 work package type、capability flags 和逐条 required/N/A，再映射 `check_id -> time/scope/commit/migration/OpenAPI/release -> test/live run -> artifact URI/hash -> verifier`；不适用项必须有独立批准，不能留空代替。
- 阻塞使用 `BLOCKED_EXTERNAL`，授权无依据时按 B 轨形成明确完成路径，不使用“暂时跳过”。
- `EXT-GATE-M*` 是总路线图对应 `GATE-M*` 的必要条件；任一专项 Gate 未过，整月不能 `ACCEPTED`。

| 范围 | Engineering owner | 必需 verifier | 业务/安全会签 |
|---|---|---|---|
| Connector Core / GSC / GA4 | Connector backend/data lead | QA + 非实现 data engineer | Property owner |
| 官方报告 | Connector backend | QA | 报告账号 owner |
| Provider/Grounded API | Sampling backend/ML lead | QA + 非实现 adapter reviewer | 预算/供应商 owner |
| Browser Capture / 代理 | Browser/backend lead | QA + Security | 授权 reviewer + 运营 |
| Sampling/SourceStratum | Monitoring/data lead | QA + statistics reviewer | Product/运营 |
| Customer 外部投影 | API/frontend lead | QA release owner | Product + Security |

开发者不能独立签字验证自己实现的 adapter、迁移或网络隔离；运营的页面复核不能替代自动化权限/网络/幂等测试。

## 3. 当前仓库基线和差距

实施从现有能力扩展，不新建第二套 Monitoring 或 Job 系统。

| 当前能力 | 现有落点 | 复用方式 | 必须补齐的差距 |
|---|---|---|---|
| SourceStratum v3 | `geo_core.monitoring.source_contract` / `source_registry` | 继续作为所有回答型样本的唯一分层身份 | 增加 `automated_ui`；增加 Kimi platform/surface；冻结 UI 特有 profile/egress/release 维度 |
| 官方报告 v1 | `geo_core.monitoring.official_reports` + PostgreSQL repository | 保留 typed import，不改造成回答 Observation | 增加 Google/Bing 真实 parser release、schema drift、raw manifest、Admin import workflow 和独立数据批准链 |
| Observation/Protocol/statistics | `geo_core.monitoring` | Sampling 终态投影到现有 Monitoring 合同 | 增加 Suite/Run/Task、planned denominator、有效性原因和 adapter release lineage |
| Durable Job | `geo_core.jobs`、`geo_worker.tasks`、Relay | 复用 lease、heartbeat、fencing、cancel、retry、outbox | 新 job kind/spec/repository；Browser Worker 独立 composition，不独立队列 |
| Model Gateway | `geo_core.model_gateway` | Provider adapter 复用调用日志/错误框架 | DeepSeek-only 基线扩展到五类采样 adapter，保留供应商差异和存储条款 |
| MinIO | `geo_core.object_store` + Compose policies | 保存内容寻址 raw/artifact/evidence manifest | 增加外部 raw 分类、tmpfs 落盘前清理、TTL 和逐 bundle manifest |
| Internal/Customer API | `apps/api/geo_api` | Internal 控制，Customer 只读 approved projection | 增加 connector/sampling/browser routes 和 External Data Report approval/latest；禁止 Customer 直读 raw projection/secret/debug 字段 |
| Admin/Customer Web | `apps/admin-web`、`apps/customer-web`、`packages/web` | 复用 BFF、项目/Campaign 上下文和稳定 client | 增加 Connection、Run、Egress、Surface、Evidence 和来源标签页面 |
| Production Compose | `infra/compose.prod.yml` | 复用 PostgreSQL/MinIO/Valkey/API/Worker/Relay | 增加隔离 browser-capture-worker、代理限定 egress、secret mount、readiness/heartbeat |

首个共享迁移必须明确处理：

1. `CaptureMethod.AUTOMATED_UI` 和 `SurfaceKind.CONSUMER_UI` 的映射。
2. `ObservationPlatform.KIMI`、`ObservationSurface.KIMI_API`；若后续增加 Kimi consumer UI，使用另一独立 surface。
3. SourceStratum UI extension：`surface_release_id/hash`、`browser_profile_version/hash`、`egress_policy_version/hash`、稳定的 `egress_cohort_key` 和 `account_cohort`。cohort 冻结预期地域、network type 与单 endpoint/版本化 endpoint pool；这些预建字段参与 UI 分层 canonical hash。执行后才生成的 `egress_verification_id` 只作 Attempt/Observation lineage，不参与 Task identity 或分母。
4. 既有 `unknown` 永远保持 ineligible；不得把历史 `manual_ui` 推断为 `automated_ui`。
5. 官方报告继续使用独立 projection，不进入回答型 SourceStratum 的 planned denominator。
6. GSC/GA4/official-report 的 External Data Snapshot/Report/Approval 是数据可见性真源；Adapter Release approval 与数据批准严格分离，现有 import/projection 不自动获得 Customer 可见性。

## 4. 来源清单和身份合同

### 4.1 首批来源矩阵

| 来源 | `capture_method` | platform/surface | 默认重复 | 真实验收 | 不代表什么 |
|---|---|---|---:|---|---|
| GSC | Connector typed projection | Google Search Console | 按日增量 | 真实 property 首次+增量+回刷 | 单次消费者 AI 回答 |
| GA4 Data API | Connector typed projection | GA4 report | 按冻结 report spec | 真实 property 首次+增量+回刷 | Session/Touch 实体真源 |
| Google AI 报告 | `official_report_import` | Google official report | 文件级 | 真实导出文件 | 单次 AIO/AI Mode 页面 |
| Bing AI 报告 | `official_report_import` | Bing official report | 文件级 | 真实导出文件 | 单次 Copilot 页面 |
| OpenAI Web Search | `provider_api` | `openai/openai_api` | 每题 10 | 真实 API live | ChatGPT consumer UI |
| Gemini Grounding | `provider_api` | `google/google_gemini_api` | 每题 10 | 真实 API live | Google AIO/AI Mode UI |
| Perplexity API | `provider_api` | `perplexity/perplexity_api` | 每题 10 | 真实 API live | Perplexity consumer UI |
| Microsoft Grounding with Bing | `proxy_grounded_api` | `microsoft/microsoft_foundry_bing_grounding` | 每题 10 | 真实 Foundry live | Bing Copilot consumer UI |
| Kimi API | `provider_api` | `kimi/kimi_api` | 每题 10 | 真实 API live；原生 Search 若不可证明则 `search_mode=disabled` | Kimi consumer UI 或自建检索结果 |
| Google AI Overviews | `automated_ui` 或 `manual_ui` | `google/google_ai_overviews` | auto 默认 5，manual 最低 3 | 按 A/B 轨逐 release | Gemini API |
| Google AI Mode | `automated_ui` 或 `manual_ui` | `google/google_ai_mode` | auto 默认 5，manual 最低 3 | 按 A/B 轨逐 release | Gemini API/AIO |
| Bing Copilot | `automated_ui` 或 `manual_ui` | `microsoft/bing_copilot` | auto 默认 5，manual 最低 3 | 按 A/B 轨逐 release | Bing Grounding API |

相同问题可以在多来源执行，但每一行都有独立 planned denominator、completion、interval 和 release lineage。跨来源对比是二级展示，不改变任何原始分母。

Kimi 当前发布合同以官方 Chat API 为最低可依赖能力。若目标账号/模型在实施时提供官方原生 Search，Adapter Release 必须保存官方依据、请求字段、tool event/citation 和 live 响应证据；若没有，则仍可作为 `provider_api + search_mode=disabled` 的独立模型分层采样。通过自定义 function tool 接入自建检索时必须另标实际检索 provider 和 `proxy_grounded_api`，不能命名为 Kimi Search。

### 4.2 Adapter Release 合同

每个 Connector、Provider 或 Surface adapter 都通过不可变 Adapter Release 发布，至少保存：

- `adapter_kind/name/version/hash`、owner、commit、dependency/SDK/connector/browser build。
- 支持的 platform/surface/capture method、输入 schema、输出 schema 和 parser schema。
- configured model 与 reported model 的提取规则；消费者 UI 未披露时必须为 `not_disclosed`。
- auth/secret type、必需 scope、地区/语言能力、并发/配额/`Retry-After` 策略。
- raw/derived 数据能否保存、允许保留时间、展示/引用要求、禁止字段及条款依据版本。
- error mapping、retryability、idempotency、timeout、取消和 partial-result 处理。
- fixture corpus hash、contract test result、live canary run、发布人和退役/撤销状态。

生命周期：

```text
draft -> fixture_ready -> live_candidate -> approved -> deprecated -> retired
                      \-> deferred_pending_authorization
approved -> suspended|revoked
```

- B 轨消费者 surface 最高只能到 `fixture_ready/deferred_pending_authorization`，不能产出 `automated_ui eligible=true`。
- 供应商条款禁止持久化 raw 时，release 必须冻结更短 TTL、加密引用或不落盘策略；无法满足可审计性与条款时不发布。
- SDK/API/DOM/浏览器 build/条款任一变化创建新 release；旧 Run 永远绑定旧 release，不原地重解释。

## 5. 领域和数据合同

### 5.1 Connector Core

计划表及关键约束：

| 对象 | 关键字段/身份 | 写入和状态约束 |
|---|---|---|
| Connector Definition | kind、adapter release、capability、config/schema hash | immutable release；固定 PyAirbyte/SDK 版本 |
| Connection | project、definition、secret ref/version、auth summary | 不保存 secret；test 只返回非敏感分类 |
| Scope | property/account/stream/report spec、locale、date policy | project scoped；只读最小权限 |
| Checkpoint | connection/scope、cursor/state、watermark、state hash | raw + projection 同成功后原子推进 |
| Sync Run | frozen definition/connection/scope/checkpoint、window、job | 重跑新 Run；终态不覆盖历史 |
| Raw Artifact | manifest URI/hash、schema fingerprint、record count | raw-first；内容寻址；分类/TTL |
| Schema Version | source fingerprint、compatibility、diff | breaking change 阻断 projection |
| Projection Batch | business key、source run、row/hash counts | 幂等 upsert，保留来源 lineage |
| Freshness | expected/observed watermark、lag、reason | 不以 Job success 代替 |
| Connector Error | auth/quota/rate/schema/revoked/transient/permanent | 明确 operator action/retryability |

Checkpoint 规则：

1. enqueue 冻结旧 checkpoint hash；同 Connection/Scope/window/release 生成稳定 idempotency key。
2. 外部读取不持有数据库事务；raw 临时流写受控工作区，完成分类/hash 后进入 MinIO。
3. projection 在 fenced transaction 内验证 lease、raw manifest、schema 和旧 checkpoint version。
4. projection 与新 checkpoint 一次提交；失败/取消/lease 丢失均不推进。
5. backfill 作为独立 Run 写同一 business key 时更新 lineage，不重复累计；增量 Run 不覆盖 backfill 证据。

### 5.2 Sampling Core

| 对象 | 责任 | 必需冻结内容 |
|---|---|---|
| Sampling Suite Version | 定义一次计划 | QuestionSet、SourceStratum inventory、repeats、valid threshold、budget、method |
| Sampling Run | 一个 Suite 的执行实例 | suite hash、requested_by、window、planned task count、adapter releases |
| Sampling Task | 最小租赁/重试单位 | stratum、question version、repetition、egress policy/cohort、not_before、deadline、idempotency |
| Sampling Attempt | 一次实际外部尝试 | lease/fence、provider/session、实际 endpoint、sticky lease、egress verification、timings、request/result class、cost |
| Observation Candidate | raw 解析结果 | answer、citation、identity、artifact、winning attempt/verification lineage、eligibility reasons |
| Run Completion | 计划与实际对账 | planned/valid/invalid/missing、80% 门槛、error composition |

Task 身份固定为：

```text
suite_version + platform + surface + capture_method
+ configured/reported model state + question_version + repetition
+ locale + region + language + device/client + search mode
+ adapter/surface release
+ browser profile + egress policy version + egress cohort key
+ account cohort (UI only)
```

- Provider API 默认 10 次；automated UI 默认 5 且不低于 3；manual UI 不低于 3。
- 计划 Task 全部进入完成度分母。删除失败项、缩小 denominator 或合并 SourceStratum 都是合同违规。
- 有效数低于冻结门槛或 valid completion <80%，该 stratum 只输出 `insufficient_evidence`。
- Retry 创建 Attempt，不创建新的计划槽；同一 repetition 最多一个 eligible winner，重复成功必须对账而非双计。
- `egress_policy_version` 和 `egress_cohort_key` 在 Suite/Task 创建前存在并参与幂等与分层；cohort 可冻结一个 Endpoint，或冻结具有同地域/network type 的 approved pool release。
- `egress_verification_id`、实际 Endpoint/lease/IP/ASN 在 Attempt 后产生，不能进入 Task idempotency key 或 SourceStratum canonical hash。每次 retry 生成新验证证据并链接到同一 planned slot；胜出 Observation 指向唯一 winning Attempt/Verification。
- pool 内 Endpoint 变化不拆分基础分母，但报告必须显示实际 Endpoint/network composition；实际地域或 network type 偏离 cohort 时 Attempt ineligible。需要按 Endpoint 比较时必须事前把 Endpoint ID 冻结为 cohort 维度并创建新版 Suite。

### 5.3 Raw Artifact 和派生投影

外部工件 manifest 至少包含：

`schema_version`、project/campaign、source identity、adapter release、run/task/attempt、capture time、classification、retention policy、file list、media type、byte size、SHA-256、record count、sanitizer release、encryption/key reference、producer commit 和 tombstone 状态。

工件类型：

- Connector raw record stream/file。
- Provider raw response（仅在供应商条款允许范围内）。
- Official report original file。
- Browser screenshot、DOM snapshot、HAR、final URL、console/network summary、parsed answer/citation。
- Manual UI screenshot/transcript、collector、time、profile 和 source URL。

写入顺序固定为 `tmpfs -> secret/PII scan -> redact/classify -> encrypt/hash -> MinIO -> manifest verification -> fenced DB commit`。Cookie、Authorization、password、完整 storage state 或无法可靠清理的工件为 `secret_bearing_rejected`，不得先落不可变 bucket 再删除。

### 5.4 外部投影的数据批准生命周期

Adapter Release 的 `approved` 只表示连接器/parser 代码可运行，不批准任何客户数据。GSC、GA4 和 official-report 的 Raw Artifact、Projection Batch/Row、Freshness 与 Sync/Import Run 始终是 Admin-only 内部数据，Customer API 不得直接查询这些表。回答型 Provider/UI Observation 继续使用现有 `monitoring_reports + immutable Metric Snapshot` 批准链；本节只为非回答型 Connector/official-report projection 建立独立数据批准链。

| 对象 | 冻结内容 | 可变状态/责任 |
|---|---|---|
| External Data Snapshot | project、显式 campaign（Customer 展示必需）、source kind、Connection/Scope、Sync Run/Import IDs、Projection Batch/Row 集合、schema/parser/adapter release、period/as_of、freshness、row count、dataset hash、Customer 字段白名单版本、rendered payload URI/hash | 创建后内容不可变；默认 `internal_only` |
| External Data Report | snapshot ID/hash、partition key、标题/摘要、approval policy/rubric version、Customer schema version、status 与状态时间 | `draft -> in_review -> approved`；approved 可转 stale/superseded/revoked，draft/in_review 可转 rejected |
| External Data Approval | report/snapshot exact version、decision、actor、reason、review evidence、decided_at、idempotency key | append-only；只有 owner/admin 审批，创建者不能独立自批 |

批准命令必须在一个 project-scoped transaction 中验证：

1. 所有源 Run/Import、raw manifest、projection counts/hash 和 lineage 完整，source kind 保持 GSC、GA4 或具体 official-report identity。
2. snapshot 显式绑定正确 Project；要进入 Customer 必须显式绑定 Campaign，不能回退到第一条/default Campaign。
3. freshness/period 达到冻结 approval policy，Customer 字段白名单与聚合规则通过，且无 raw、secret、PII、内部 actor/debug 字段。
4. snapshot/report hash 与审批提交值一致；审批后 payload、source rows、period、schema 和 lineage 不可修改。
5. approval 与同 partition 的旧 report supersede 在同一事务提交；重试使用 idempotency key，不重复批准或创建多个 latest。

数据刷新永远创建新的 Projection Batch、External Data Snapshot 和 draft Report，不修改已批准报告，也不自动批准。新 draft 未批准时，Customer 不会切换到它；旧 approved report 达到 freshness policy、源 lineage 被撤回或 approval policy 失效时持久化转为 `stale` 并退出 Customer latest。人工确认数据错误时转为 `revoked`；批准新版本时旧版本转为 `superseded`。`stale/revoked/superseded` 只保留内部历史审计，不能由 Customer API 读取。

Customer latest 只从 `approved` External Data Report 投影读取，按 `Project + Campaign + source kind + Connection/Scope + report period/partition` 分区，以 `approved_at DESC, report_id DESC` 确定全序。official-report 在页面/API/export 中继续显示 `official_report_import` 和具体 platform/surface；GSC/GA4 继续显示 connector projection，不伪造成 Observation 或与回答型分母合并。无 approved report 时返回明确空状态。

## 6. 澳洲代理和消费者界面采集

### 6.1 用户提供出口的输入合同

系统接受以下两类可用出口：

1. Playwright/Chromium 可连接的 HTTP CONNECT、HTTPS 或 SOCKS5 proxy：`protocol + host + port + optional username/password secret`。
2. 受控网络网关：由部署层把 browser-capture-worker 的 default route 送入该网关，并能提供连接/出口审计。

仅提供一个公网 IP 字符串、但没有监听的代理/隧道或路由能力，不构成可用出口。Admin 创建 Egress Endpoint 时必须记录：

- endpoint display name、operator、protocol、host/port、secret reference。
- expected country=`AU`、可选 state/city、network type 声明和供应商/线路标识。
- sticky 模式：fixed endpoint、username/session token、API lease 或 gateway connection lease。
- 最长 sticky duration、并发、配额、允许目标、到期日和停用原因。
- authorization 与 data-processing reference；代理可用不等于 surface 自动采集获准。

### 6.2 网络隔离和粘性会话

`browser-capture-worker` 使用现有 broker，但作为独立进程角色和 Compose service：

- 只挂载 worker DB、MinIO、Valkey、Secret Store 主密钥/所需 secret 和 tmpfs，不挂 Internal/Customer Web 凭据。
- 普通公网 direct egress 默认拒绝；只允许 proxy/gateway、最小地域验证源、对象存储/数据库/队列和内部控制端点。
- BrowserContext 的 proxy bypass 为空；目标 HTTP(S)、WebSocket 和可观察 DNS/CONNECT 流必须从所选出口离开。
- 通过 deny test、连接日志或网络 capture 证明断开代理后目标页无法访问；宿主机可直连不能成为容器旁路。
- Endpoint failure 只能由运营显式切换到另一个已批准 Endpoint。CAPTCHA、rate limit、ban 或 policy block 不触发自动换代理。

每个 Browser Session 申请一个 sticky lease，保存 lease ID、申请/到期、承诺出口和不含 secret 的配置 hash。一个 Capture Attempt 的顺序必须是：

```text
lease active
  -> pre-check source A + source B
  -> target page/query in same BrowserContext
  -> page artifacts complete
  -> post-check source A + source B
  -> optional provider connection-log match
  -> eligibility decision
  -> close context and lease
```

前后 public IP/ASN 必须一致，且至少两个独立地域源判断 country=`AU`。没有 sticky 能力时，只有可信代理侧日志能证明 pre/target/post hostname 使用同一澳洲出口，Attempt 才可 eligible。周期健康检查不能替代逐 Attempt 证明。

### 6.3 浏览器画像

Browser Profile Version 至少冻结：

- Playwright/Chromium release、OS/image digest、desktop/mobile、viewport、User-Agent。
- `locale=en-AU`、`Accept-Language`、澳洲 timezone、SafeSearch。
- geolocation、permission、坐标来源/精度和页面显示的 detected location。
- final domain/URL、region/location setting、Cookie/consent 状态。
- `clean_anonymous` 或 `managed_test_account`；后者冻结账号 region/language、个性化开关和 storage-state secret version。
- Search Labs/实验资格、登录状态、采集时间和页面披露的模式/模型。

匿名与 managed account 永远使用不同 SourceStratum。默认每 repetition 新建 clean anonymous BrowserContext；不能在运行中把匿名 context 升级为登录 context。

### 6.4 Surface adapter 和页面状态机

三个首批 adapter release 分开实现和发布：

- `google_ai_overviews`：识别普通 Google Search 已完成、AIO 容器/折叠展开、答案、引用卡和有效缺失。
- `google_ai_mode`：识别 AI Mode 入口/路由、回答完成、引用、follow-up 区域和 unavailable/eligibility 状态。
- `bing_copilot`：识别 Bing Search/Copilot 消费者入口、回答完成、引用、传统 SERP 与 Copilot 的边界。

禁止把 featured snippet、knowledge panel、传统结果摘要或其他 surface 的相似 DOM 标成目标 AI 回答。

```text
authorization gate
  -> egress/sticky pre-verification
  -> profile/location/consent verification
  -> normal UI submit frozen query
  -> documented ready condition
  -> screenshot + DOM + HAR + final URL
  -> parse and classify
  -> egress post-verification
     |- captured/eligible
     |- surface_not_present/eligible negative
     |- consent_required/ineligible
     |- login_required/ineligible
     |- access_blocked/ineligible
     |- geo_mismatch|geo_unverified|egress_changed/ineligible
     |- parser_failed|timeout/ineligible
```

`surface_not_present` 只有在普通页面完整加载、surface detector/parser health 正常、无阻断且前后地域证明有效时才是有效负样本。空文本、selector miss、timeout 或 CAPTCHA 不能转换为有效缺失。

### 6.5 逐 Surface Release 保真度

每个 `platform + surface + Surface Release + Playwright/Chromium release` 独立验收：

| 门槛 | A 轨 | B 轨 |
|---|---|---|
| 授权状态 | `approved` 且未过期 | `assessed_no_basis` / deferred 决策 |
| 页面集 | 每 release 至少 20 个 AU live | 每 release 至少 30 个 fixture |
| 成功页面 | 至少 10 个 `captured/eligible` | 至少 10 个成功 fixture |
| 有效缺失 | 适用时至少 5 个 | 适用时至少 5 个 fixture |
| 人工页面复核 | 全部 release set 逐字段 | 至少 10 个 `manual_ui` 页面逐字段对照 |
| 阻断 fixture | CAPTCHA/login/consent/rate/geo/egress/parser 各至少 2 | 同左 |
| surface 分类准确率 | `>=95%`，普通结果误标 0 | 同左（fixture） |
| visible answer 完整率 | `>=99%` | 同左（fixture/manual 对照） |
| citation URL/顺序/标题 | `100%` | `100%` |
| 可产出 `automated_ui eligible` | 是 | 否 |

任何 release 样本不足或自身门槛失败，只能保持 candidate/fixture_ready；不能借用 AIO 样本通过 AI Mode，不能借用旧 parser release 通过新 release，也不能用 Provider API/人工转录冒充 automated UI。

## 7. 安全、授权和保留

### 7.1 授权双轨

每个 surface 保存 `not_assessed/assessed_no_basis/approved/expired/revoked`、依据、批准人、用途、频率、到期和复评时间。

- A 轨：只在 `approved` 有效期内允许真实自动采集；超频、越用途或到期 fail closed。
- B 轨：允许 parser fixture、获准 PoC 和 `manual_ui`；禁止后台悄悄启动 browser capture。
- 三个首批 surface 必须先逐一决定 A/B 轨，再执行对应轨道。申请中等同未批准，只能走 B 轨允许的 fixture/manual 路径；最晚在 `M2` Gate（`T+2`）仍未获批准时记录 `assessed_no_basis`，不能无限期作为第三轨。
- live enqueue 在创建 Durable Job 与 outbox 的同一 fenced transaction 中要求有效 `approved`，并冻结 authorization ID/version/hash、surface/release、用途、频率和 expires_at。`not_assessed`、申请中、B 轨、expired 或 revoked 返回明确错误且零 Job/零 outbox。
- Worker 在 claim 后及目标页面导航前重新校验同一授权版本仍有效；过期/撤销时取消或终止 Attempt，不能先请求页面再补记失败。授权升轨或续期创建新 version，不能原地改写已冻结任务。
- 代理、账号、技术可行性和页面公开均不自动构成授权依据。

### 7.2 Secret 和敏感工件

- OAuth refresh token、service account key、Provider key、proxy auth、Browser account/storage state 只进入 Secret Store。
- Job/outbox 只保存 secret reference/version；运行时按 Project/用途最小解密，明文只驻留进程内存/tmpfs。
- HAR 清除 Cookie/Authorization/query/form secret；DOM/screenshot 检测账号名、头像、邮箱、账号链接和受限内容。
- `restricted_authenticated_raw` 使用 artifact 独立 DEK、受限 bucket/RBAC 和默认 30 天 TTL；public raw 默认 90 天。
- Customer、通用导出、Recommendation、训练/生成和普通运营角色不能读取受限 raw。
- adapter 条款要求更短 TTL/禁止持久化时使用更严格规则；删除后保留 hash/tombstone，不保留可恢复正文。

## 8. 分阶段实施 checklist

`M0` 为 `T+0` 的专项准备 Gate；`M1`--`M6` 与总路线图同名 Gate 同步，不能把 M0 未完成事项滚入 M1 后仍宣称按期启动。它们是稳定标签而非月份，时间映射如下：

| Gate 标签 | 连续窗口 | 说明 |
|---|---|---|
| M0 | `T+0` | 冻结来源、授权、预算、schema 和 evidence 基线 |
| M1 | `T+0--T+1` | 合同、迁移和骨架 |
| M2 | `T+1--T+2` | 真实 Connector、Sampling 和 Browser Beta |
| M3 | `T+2--T+3` | 五类 API 和三个 Surface Release |
| M4 | `T+3--T+4` | 观测交付、漂移和告警集成 |
| M5 | `T+4` | 批准投影和运营稳定化 |
| M6 | `T+5` | 生产等价和最终专项验收 |

### 8.1 M0：专项启动

- [ ] `EXT-M0-01` 建立来源 inventory，逐项记录账号/property/region、owner、secret type、预算、配额、授权和预计可用日。
- [ ] `EXT-M0-02` 对现有 SourceStratum/official report/Job/Monitoring/Compose 做差距审计，冻结复用点和新增目录。
- [ ] `EXT-M0-03` 冻结 Connector、Sampling、Adapter Release、Browser/Egress、Artifact manifest 和 error taxonomy schema。
- [ ] `EXT-M0-04` 冻结三个消费者 surface 的 A/B 轨评审计划、依据 owner 和 M2 决策日。
- [ ] `EXT-M0-05` 验证用户可提供的澳洲出口至少属于可连接 proxy 或可路由 gateway，而非裸 IP；记录 sticky 能力和 network type 待验证状态。
- [ ] `EXT-M0-06` 冻结真实/fixture/manual 数据集、live 调用预算和不会突破授权频率的验收日历。
- [ ] `EXT-M0-07` 冻结第 10 节 evidence manifest v1，逐 check 包含 type/flags/applicability、时间、commit/migration/OpenAPI、Project/Campaign/environment/脱敏 account scope、run/artifact 和独立 verifier。

**`EXT-GATE-M0`**

- [ ] `EXT-M0-AC-01` 所有首批来源都有 owner、轨道/授权计划、secret reference 计划、预算和阻塞处置。
- [ ] `EXT-M0-AC-02` 当前仓库差距表经 Connector/Sampling/Browser/Monitoring owner 会签，没有另建平行 Observation/Job 的方案。
- [ ] `EXT-M0-AC-03` 澳大利亚出口的连接方式、sticky 证明方式和失败边界可实施；裸 IP 不被误记为 ready。
- [ ] `EXT-M0-AC-04` 专项 schema 与总路线图 SourceStratum、Customer 和安全合同无冲突。
- [ ] `EXT-M0-AC-05` evidence manifest schema 拒绝缺失逐项溯源、未批准 N/A、错误 scope 或只依赖顶层 Git/environment 的记录。

### 8.2 M1：合同、迁移和骨架

- [ ] `EXT-M1-01` 在线 expand migration 增加 Connector/Sampling/Adapter Release/Authorization/Egress/Browser 及 External Data Snapshot/Report/Approval tables，与精确 project-scoped FK/RLS/index。
- [ ] `EXT-M1-02` 兼容扩展 `automated_ui`、Kimi platform/surface 和 UI SourceStratum 的 egress policy/cohort；实际 verification 仅作 Attempt/Observation lineage，旧 writer/reader 仍可运行，历史值不猜测回填。
- [ ] `EXT-M1-03` 实现 Connector Definition/Connection/Scope/Checkpoint/Run/Raw/Schema/Freshness/Error Domain + repository fixture path。
- [ ] `EXT-M1-04` 实现 Sampling Suite/Run/Task/Attempt/Completion Domain + repository；Task 冻结 egress policy/cohort，Attempt 保存实际 verification，planned task 不因重试或失败删除。
- [ ] `EXT-M1-05` 实现 Adapter Release registry、fixture-ready/live/approved/deferred/suspended 状态和条款/保留字段。
- [ ] `EXT-M1-06` 增加 `connector.sync`、`official_report.import`、`sampling.task.run`、`egress.verify`、`browser.capture` job spec 和现有 Worker/Relay composition。
- [ ] `EXT-M1-07` 增加隔离 browser-capture-worker Compose skeleton、readiness/heartbeat、tmpfs、最小 secret 和 direct-egress deny tests。
- [ ] `EXT-M1-08` 实现 Egress Endpoint/Secret Reference、sticky lease、双地域 pre/post fixture、Browser Profile/Session/Page Bundle contracts。
- [ ] `EXT-M1-09` 为 AIO、AI Mode、Copilot 建立独立 parser fixture corpus，覆盖 success/missing/CAPTCHA/login/consent/rate/geo/egress/parser drift。
- [ ] `EXT-M1-10` 实现 Internal API/Admin 最小 Connection、Egress、Surface Release、Run/Task 和 evidence 只读/控制界面。

**`EXT-GATE-M1`**

- [ ] `EXT-M1-AC-01` Alembic 单一 head；旧数据/reader/writer 兼容；`unknown` 不提升、manual 不迁成 automated。
- [ ] `EXT-M1-AC-02` Connector fixture 验证 initial/incremental/backfill/rate/schema/cancel/lease，checkpoint 只在 raw+projection 同成功后推进。
- [ ] `EXT-M1-AC-03` Sampling fixture 验证 planned denominator、attempt retry、cancel/fencing、低于 80% 和跨来源不混分母。
- [ ] `EXT-M1-AC-04` 断开 proxy/gateway 后 browser worker 无法直达目标；proxy secret 在所有工件/日志/API 中零明文命中。
- [ ] `EXT-M1-AC-05` 三个 surface fixture 能区分 AI/传统页面/有效缺失/阻断/parser drift，普通结果误标为 0。
- [ ] `EXT-M1-AC-06` Internal API/Admin 跨 Project、低权限、Customer raw/secret 访问均被拒绝且零写入。

### 8.3 M2：真实 Connector、Sampling 和 Browser Beta

- [ ] `EXT-M2-01` 固定 PyAirbyte 与 GSC connector release，完成真实只读 Connection、scope、initial、incremental、backfill 和 freshness。
- [ ] `EXT-M2-02` 固定 GA4 connector/report release，完成真实只读 Connection、scope、initial、incremental、backfill 和 freshness；明确只做聚合对账。
- [ ] `EXT-M2-03` 完成 Google/Bing 官方报告原文件上传、parser release、schema fingerprint、typed projection、duplicate/replay 和可解释空文件路径。
- [ ] `EXT-M2-04` 完成 Sampling Suite 冻结、Task admission/not_before、manual UI import、raw answer/citation 和 SourceStratum projection。
- [ ] `EXT-M2-05` 完成澳洲 proxy/gateway 连接、sticky lease、双源 pre/post、network type 和 browser profile Beta。
- [ ] `EXT-M2-07` 在任何 live UI enqueue 前完成 AIO/AI Mode/Copilot 授权决策，逐项记录 `approved` 或 `assessed_no_basis`、用途、频率、到期和后续证据门槛；申请中按 B 轨限制。
- [ ] `EXT-M2-06` 仅在 `EXT-M2-07` 完成并通过 admission 后，对 A 轨 surface 至少执行一个真实 AU successful capture；对 B 轨 surface 只完成全链 fixture + manual baseline。
- [ ] `EXT-M2-08` Admin 完成 Connection test/rotate/disable、checkpoint/freshness、Egress test/disable、Surface Run、阻断原因和受控证据查看。

**`EXT-GATE-M2`**

- [ ] `EXT-CONN-AC-01` GSC 真实首次+增量在同一 property 对账；相同 checkpoint 重试无重复，回刷不重复累计。
- [ ] `EXT-CONN-AC-02` GA4 真实首次+增量在同一 property 对账；report schema/version 可重算，无法创建 Session/Touch。
- [ ] `EXT-REPORT-AC-01` 两类真实报告均保存 original hash/parser/schema/row count；无数据文件得到可解释空 projection，不伪造 Observation。
- [ ] `EXT-SAMP-AC-01` Task 独立 retry/cancel；planned/valid/invalid/missing 对账；低于门槛只输出 `insufficient_evidence`。
- [ ] `EXT-EGR-AC-01` 同一 sticky lease 中 pre/target/post 的 IP/ASN 一致且双源 AU；direct egress、换 IP 或不一致结果 ineligible。
- [ ] `EXT-AUTH-AC-01` 三个 surface 均有 A/B 轨决定；无 `not_assessed`、无“申请中”第三轨、B 轨无法 enqueue automated capture。
- [ ] `EXT-AUTH-AC-02` 缺失/申请中/B 轨/expired/revoked authorization 的 live enqueue 返回明确错误且零 Job/零 outbox；claim 后或导航前失效的任务不发起页面请求。
- [ ] `EXT-UI-AC-01` 运营从同一 Page Bundle 逐项复核 answer/citation；CAPTCHA/传统 SERP/parser failure 不成为 success/valid missing。

### 8.4 M3：五类 API 和三个 Surface Release

- [ ] `EXT-M3-01` 发布 OpenAI Web Search adapter，冻结 response/citation/model/usage/error/retention 映射并完成 live canary。
- [ ] `EXT-M3-02` 发布 Gemini Grounding adapter，冻结 grounding metadata/citation/search mode/error/retention 映射并完成 live canary。
- [ ] `EXT-M3-03` 发布 Perplexity adapter，冻结实际 API 产品、citation/model/usage/error/retention 映射并完成 live canary。
- [ ] `EXT-M3-04` 发布 Microsoft Grounding with Bing adapter，使用 `proxy_grounded_api` 身份，冻结引用展示/保留要求并完成 live canary。
- [ ] `EXT-M3-05` 发布 Kimi API adapter，冻结 Kimi platform/surface、reported model、原生 search capability、citation/usage/error 映射并完成 live canary；不能证明原生 Search 时使用 `search_mode=disabled`。
- [ ] `EXT-M3-06` 每个 A 轨 Surface Release 独立完成至少 20 个 AU live 与阻断 fixture；每个 B 轨独立完成 30 fixture + 10 manual 对照。
- [ ] `EXT-M3-07` 完成三个 surface 的重复 Task 调度、clean anonymous cohort；managed account 如启用则独立 profile/denominator。
- [ ] `EXT-M3-08` 实现 selector/parser/浏览器 build drift detection、release suspend 和旧 release 可重放解析。
- [ ] `EXT-M3-09` 完成 Provider/API/automated/manual/official/synthetic 标签、API/UI/export 和 denominator 的跨类型负测。

**`EXT-GATE-M3`**

- [ ] `EXT-PROV-AC-01` 五类 adapter 各有真实 credential live run、provider request ID、configured/reported model、raw/retention 证据和完整错误分类。
- [ ] `EXT-PROV-AC-02` Provider/Grounded API 均不使用 ChatGPT/AIO/AI Mode/Copilot consumer UI 标签；Microsoft Grounding 不冒名 `provider_api`。
- [ ] `EXT-PROV-AC-03` auth/quota/rate/timeout/refusal/schema/partial/cancel 映射稳定；重试新 attempt，不重复有效样本。
- [ ] `EXT-UI-AC-02` 每个 Surface Release 自身达到分类 `>=95%`、传统结果误标 0、answer `>=99%`、citation `100%`。
- [ ] `EXT-UI-AC-03` A/B 轨各自达到规定样本构成；没有跨 surface/release 借样本，B 轨零 automated eligible。
- [ ] `EXT-EGR-AC-02` sticky 到期、Session 内换 IP、DNS/HTTP/WebSocket 旁路、AU datacenter 和 geo source 冲突均按合同 fail closed。
- [ ] `EXT-DRIFT-AC-01` selector/browser/API schema 变化能暂停对应 release、告警且不覆盖旧 Observation。

### 8.5 M4：观测交付、漂移和告警集成

- [ ] `EXT-M4-01` 把 Connector freshness/error、Provider model/schema、Surface parser/geo/access drift 投影为版本化 alert input。
- [ ] `EXT-M4-02` 为每个 Sampling Run 输出 frozen inventory、planned/valid/invalid/missing、原因构成、cost/latency 和 source composition。
- [ ] `EXT-M4-03` 证明所有 eligible Observation 都有 raw/derived evidence locator、adapter release、完整 SourceStratum 及 winning Attempt/Egress Verification lineage；缺任一项 fail closed，但 verification ID 不参与分母 hash。
- [ ] `EXT-M4-04` 实现 raw TTL/tombstone、authorization expiry、secret rotation 与运行中 reference version 的运维任务。
- [ ] `EXT-M4-05` 完成 connector/provider/browser 的 quota admission、日预算、`not_before`、暂停/恢复和队列年龄观测。

**`EXT-GATE-M4`**

- [ ] `EXT-HANDOFF-AC-01` Metric 层只收到冻结、eligible、来源完整的 Observation；invalid/missing 仍保留在 completion denominator。
- [ ] `EXT-HANDOFF-AC-02` model/source/surface release 构成变化与业务 metric 分开，旧 release 结果不被新 parser 原地重写。
- [ ] `EXT-ALERT-AC-01` connector auth/schema/freshness、provider model/quota、surface parser/geo/access drift 各有可去重告警和处置链接。
- [ ] `EXT-OPS-AC-01` authorization 到期、secret 撤销、quota exhaustion 和 adapter suspend 后，新任务无法开始，运行中任务按冻结规则终止/完成。

### 8.6 M5：批准投影和运营稳定化

- [ ] `EXT-M5-01` Admin 完成 Definition/Connection/Scope/Run/Checkpoint/Freshness/Error、Suite/Task、Adapter/Authorization、Egress/Session/Capture 的完整操作页。
- [ ] `EXT-M5-06` 实现第 5.4 节 External Data Snapshot/Report/Approval、人工 review/approve/reject、freshness stale、supersede/revoke、幂等 approval 和 latest projection；sync/import 不自动批准。
- [ ] `EXT-M5-02` Customer 只通过 approved `monitoring_reports` 或 approved External Data Report 投影读取；显示 capture/source kind、platform/surface、model state（适用时）、locale/region、sample/completion、release 和 evidence freshness 摘要。
- [ ] `EXT-M5-03` Customer/raw export/Recommendation 字段白名单和跨 Project/Campaign negative tests 全部完成。
- [ ] `EXT-M5-04` 完成 connection revoke/reauthorize、secret/provider/proxy rotate、schema drift、surface suspend、manual fallback 和 raw TTL runbook。
- [ ] `EXT-M5-05` 完成成本/配额/延迟 dashboard 和运营处置 SLA；不得因慢供应商自动混用 fallback 模型。

**`EXT-GATE-M5`**

- [ ] `EXT-ADMIN-AC-01` 运营可在不读取 secret 的情况下完成 test/pause/resume/rotate/reauthorize/retry/cancel 和证据复核。
- [ ] `EXT-DATA-APPROVAL-AC-01` GSC/GA4/official-report sync/import 只创建 internal projection 和 draft；没有 approval command 时 Customer 为空，Adapter Release approval 不能代替数据批准。
- [ ] `EXT-DATA-APPROVAL-AC-02` approve 冻结 exact snapshot/hash/Project/Campaign/source/period/schema/lineage；刷新创建新 draft，stale/supersede/revoke 退出 Customer 且历史不变。
- [ ] `EXT-DATA-APPROVAL-AC-03` 同 partition 并发/重试批准只有一个 latest；跨 Project/Campaign snapshot、创建者自批、过期 freshness 或字段白名单失败均零 Customer 写入。
- [ ] `EXT-CUST-AC-01` Customer 只见 approved Monitoring Report 或 approved External Data Report；synthetic、raw、invalid、未批准/stale/revoked、B 轨 fixture、secret/debug/actor 全不可见。
- [ ] `EXT-CUST-AC-02` 来源标签和 denominator 在 Customer/API/export 一致；Provider、UI、GSC、GA4、official report 不会因展示汇总而丢失身份或互相冒名。
- [ ] `EXT-RUNBOOK-AC-01` 新值班人员按 runbook 可处理至少一次 connector revoke、provider rate limit 和 surface drift 演练。

### 8.7 M6：生产等价和最终专项验收

- [ ] `EXT-M6-01` 以真实 GSC/GA4、两类真实官方报告、五类真实 API 和三个 surface 对应轨道执行统一 staging Suite。
- [ ] `EXT-M6-02` 使用真实澳洲 residential/ISP/mobile proxy/gateway 完成 A 轨 capture；B 轨执行冻结 fixture + manual 对照。
- [ ] `EXT-M6-03` 在生产等价拓扑执行 2 个并发 Connector x 250,000 raw records、4 个 Sampling Run x 1,000 Task 和至少 20 GiB page artifact 负载。
- [ ] `EXT-M6-04` 演练 auth revoke、quota/rate、schema/API/DOM drift、proxy expiry/IP change、Worker/Relay/DB/MinIO/Valkey failure、cancel/lease/fencing。
- [ ] `EXT-M6-05` 执行在线迁移追尾/对账/rollback window，旧 Observation/source label/hash 和 Customer projection 保持。
- [ ] `EXT-M6-06` 空环境恢复 Connector/Sampling/Browser、External Data Snapshot/Report/Approval、raw manifest、历史 keyring 和代表性 Connector/Provider/Egress secret。
- [ ] `EXT-M6-07` 汇总全部 adapter release、authorization、live run、manual review、test/perf/failure/restore 证据到最终 manifest。

**`EXT-GATE-M6`**

- [ ] `EXT-LIVE-AC-01` 每类真实来源均有正确账号/环境/release 的 live run；fixture 未被计为 live。
- [ ] `EXT-LIVE-AC-02` 三个消费者 surface 各自按当前轨道完成证据；每个 release 的准确率和样本构成独立计算。
- [ ] `EXT-PERF-AC-01` 完整冻结负载下达到总路线图第 10.7 节队列/API/同步/工件/正确性门槛。
- [ ] `EXT-FAIL-AC-01` 所有外部/基础设施故障都不推进错误 checkpoint、不产生 eligible 假样本、不重复终态、不泄漏 secret。
- [ ] `EXT-MIG-AC-01` 切换前两轮零差异、lag=0；rollback window 内可逆；历史 unknown/manual/provider/report 身份不改变。
- [ ] `EXT-RESTORE-AC-01` 恢复后 Run/Task/Attempt/Observation/Checkpoint、External Data Report 状态/approval/latest、manifest/hash 和代表性 secret connection test 全部可用。
- [ ] `EXT-EVID-AC-01` 最终 manifest 中每个 check/AC 都有 work package type/flags/applicability、开始/结束时间、commit/migration/OpenAPI、Project/Campaign/environment/脱敏 account scope、release/run/artifact/verifier，所有 URI/hash 可复核。
- [ ] `EXT-EVID-AC-02` 任一必需字段缺失、N/A 未独立批准、scope 与 run/artifact 不一致或顶层字段被用来代替单项映射时，manifest schema/verification 必须失败。

## 9. 逐领域验收 checklist

### 9.1 Connector

- [ ] `EXT-CONN-FINAL-01` GSC/GA4 各自覆盖 initial、incremental、same-checkpoint replay、backfill、late/fresh data 和 freshness。
- [ ] `EXT-CONN-FINAL-02` rate limit/`Retry-After`、auth expired/revoked、secret rotation、quota 和 transient outage 有分类与恢复路径。
- [ ] `EXT-CONN-FINAL-03` compatible schema 自动生成新 version；breaking schema 保存 raw、暂停 projection、触发告警。
- [ ] `EXT-CONN-FINAL-04` cancel/lease lost/worker restart 不推进 checkpoint；projection 与 raw counts/hash/lineage 一致。
- [ ] `EXT-CONN-FINAL-05` 两个 Project 使用相似 property/report spec 时零跨项目读取、写入或 idempotency collision。

### 9.2 Provider 和 Grounded API

- [ ] `EXT-PROV-FINAL-01` 五 adapter 都有 request/result/error contract、fixture、live canary、retention/display review 和 rollback release。
- [ ] `EXT-PROV-FINAL-02` citations 可回指 provider response 的 URL/title/order/span；不可获得的字段明确 unavailable，不猜测。
- [ ] `EXT-PROV-FINAL-03` configured/reported model、search mode、usage、provider request ID、latency 和 finish/refusal reason 完整。
- [ ] `EXT-PROV-FINAL-04` 供应商静默 model change、schema change 或 search tool 未实际调用可检测并形成 drift/eligibility 决定。
- [ ] `EXT-PROV-FINAL-05` 预算、并发、deadline、idempotency、retry/cancel 与 model call log 一致，调用失败不生成空成功样本。

### 9.3 消费者 UI 和代理

- [ ] `EXT-UI-FINAL-01` AIO、AI Mode、Copilot 的入口、surface detector、answer/citation parser 和 valid missing 条件独立。
- [ ] `EXT-UI-FINAL-02` 每 Attempt 的 screenshot/DOM/HAR/final URL/parsed locator 与 pre/post egress evidence 属于同一 Session/lease。
- [ ] `EXT-UI-FINAL-03` clean anonymous 与 managed account、desktop 与 mobile、profile/release/region 任一不同不会静默混分母。
- [ ] `EXT-UI-FINAL-04` CAPTCHA/login/consent/rate/ban/geo/parser/timeout 都是明确 ineligible reason，不触发 stealth、解码或代理轮换。
- [ ] `EXT-EGR-FINAL-01` HTTP CONNECT/HTTPS/SOCKS5 中实际启用的每种协议覆盖 success/auth failure/timeout/sticky expiry/IP change/direct deny。
- [ ] `EXT-EGR-FINAL-02` 双地域源、ASN、network type、页面 detected location 和代理连接日志（适用时）可交叉复核。
- [ ] `EXT-EGR-FINAL-03` datacenter 出口只能标 `au_geo_verified`；只有验证的 residential/ISP/mobile 才标消费者代表性。

### 9.4 Sampling 和来源隔离

- [ ] `EXT-SAMP-FINAL-01` API=10、automated UI 默认 5/最低 3、manual UI 最低 3；Protocol 提高后不能在运行中降低。
- [ ] `EXT-SAMP-FINAL-02` planned Task 为完成度分母；invalid/missing 保留原因；valid <80% 或样本不足只为 `insufficient_evidence`。
- [ ] `EXT-SAMP-FINAL-03` retry/reclaim 只产生 Attempt，不重复 planned slot/eligible Observation。
- [ ] `EXT-SAMP-FINAL-04` capture/model/locale/region/language/device/search/profile/egress policy/cohort/release 任一预冻结维度差异保持独立；实际 verification ID 不拆分分母，Endpoint composition 单独展示。
- [ ] `EXT-SAMP-FINAL-06` retry/reclaim 的新 Egress Verification 链接同一 planned slot；只有 winning Attempt 形成 Observation，3-5 次 repetition 可在同一稳定 egress cohort 达到样本门槛。
- [ ] `EXT-SAMP-FINAL-05` Suite 冻结 throughput/cost window；超预算只能创建新版缩小范围，不修改原 Suite denominator。

### 9.5 安全、Customer 和恢复

- [ ] `EXT-SEC-FINAL-01` secret/PII 注入测试覆盖 header/query/form/JSON/SDK exception/HAR/DOM/screenshot/log/job/outbox/export。
- [ ] `EXT-SEC-FINAL-02` restricted raw 的独立加密、RLS/RBAC、TTL/tombstone、双人 hold 和 Customer/普通运营拒绝通过。
- [ ] `EXT-SEC-FINAL-03` authorization expired/revoked 与 secret revoked 是独立门禁，任一失败都禁止新自动任务。
- [ ] `EXT-CUST-FINAL-01` Customer latest 只读取 approved Monitoring Report 或 approved External Data Report；无法直接读取 Connector/official raw projection、未批准 snapshot 或 raw evidence URI 的受限内容/签名下载链接。
- [ ] `EXT-CUST-FINAL-02` GSC/GA4/official-report 的 draft -> review -> approve -> stale/supersede/revoke 和并发幂等行为通过；Adapter Release approval 无法提升数据可见性。
- [ ] `EXT-RESTORE-FINAL-01` PostgreSQL、MinIO、历史 keyring 恢复后，不仅 row/hash 一致，而且 Connection/Provider/Egress 可以执行不泄密 canary。

## 10. Evidence manifest 模板

每个专项交付波次的 manifest 至少包含：

```json
{
  "schema_version": "geo-external-evidence-manifest-v1",
  "stage": "M2",
  "status": "READY_FOR_REVIEW",
  "manifest_created_at": "<ISO-8601 UTC>",
  "git_commit": "<sha>",
  "migration_head": "<revision>",
  "environment": {
    "name": "live-staging",
    "deployment_id": "<opaque-deployment-ref>",
    "fingerprint": "<sha256>"
  },
  "openapi_manifest": {
    "version": "<version>",
    "uri": "s3://...",
    "sha256": "<sha256>"
  },
  "checks": [
    {
      "check_id": "EXT-M2-06",
      "work_package_type": "external_integration",
      "capability_flags": {
        "changes_database": false,
        "changes_api": false,
        "has_customer_surface": false,
        "handles_sensitive_data": true,
        "has_runtime_operation": true,
        "calls_external_service": true,
        "requires_live_evidence": true
      },
      "applicability": {
        "required": [
          {"clause_id": "DOR-01", "result": "passed", "evidence_refs": ["s3://.../ownership.json"]},
          {"clause_id": "DOR-02", "result": "passed", "evidence_refs": ["s3://.../capture-contract.json"]},
          {"clause_id": "DOR-03", "result": "passed", "evidence_refs": ["s3://.../authorization-budget.json"]},
          {"clause_id": "DOR-05", "result": "passed", "evidence_refs": ["s3://.../acceptance-map.json"]},
          {"clause_id": "DOR-06", "result": "passed", "evidence_refs": ["s3://.../data-review.json"]},
          {"clause_id": "DOD-01", "result": "passed", "evidence_refs": ["s3://.../contract-conformance.json"]},
          {"clause_id": "DOD-02", "result": "passed", "evidence_refs": ["s3://.../behavior-tests.json"]},
          {"clause_id": "DOD-05", "result": "passed", "evidence_refs": ["s3://.../runtime-operations.json"]},
          {"clause_id": "DOD-06", "result": "passed", "evidence_refs": ["s3://.../live-review.json"]},
          {"clause_id": "DOD-07", "result": "passed", "evidence_refs": ["s3://.../evidence-verification.json"]},
          {"clause_id": "SCOPE-PROJECT", "result": "passed", "evidence_refs": ["s3://.../scope.json"]},
          {"clause_id": "SCOPE-CAMPAIGN", "result": "passed", "evidence_refs": ["s3://.../scope.json"]},
          {"clause_id": "SCOPE-CONNECTION", "result": "passed", "evidence_refs": ["s3://.../scope.json"]},
          {"clause_id": "SCOPE-ACCOUNT", "result": "passed", "evidence_refs": ["s3://.../scope.json"]},
          {"clause_id": "SCOPE-ENVIRONMENT", "result": "passed", "evidence_refs": ["s3://.../environment.json"]},
          {"clause_id": "EVIDENCE-LIVE", "result": "passed", "evidence_refs": ["s3://.../live-run.json"]}
        ],
        "not_applicable": [
          {
            "clause_id": "DOR-04",
            "reason": "This capture slice changes neither database schema nor API contract.",
            "basis": ["changes_database=false", "changes_api=false"],
            "decided_by": "<identity-ref>",
            "verified_by": "<independent-identity-ref>",
            "decided_at": "<ISO-8601 UTC>",
            "evidence_ref": "s3://.../applicability-dor04.json"
          },
          {
            "clause_id": "DOD-03",
            "reason": "No schema or data migration is part of this capture slice.",
            "basis": ["changes_database=false"],
            "decided_by": "<identity-ref>",
            "verified_by": "<independent-identity-ref>",
            "decided_at": "<ISO-8601 UTC>",
            "evidence_ref": "s3://.../applicability-dod03.json"
          },
          {
            "clause_id": "DOD-04",
            "reason": "This slice consumes frozen contracts and changes no API, Customer surface, or export.",
            "basis": ["changes_api=false", "has_customer_surface=false"],
            "decided_by": "<identity-ref>",
            "verified_by": "<independent-identity-ref>",
            "decided_at": "<ISO-8601 UTC>",
            "evidence_ref": "s3://.../applicability-dod04.json"
          }
        ]
      },
      "result": "passed",
      "started_at": "<ISO-8601 UTC>",
      "completed_at": "<ISO-8601 UTC>",
      "git_commits": ["<sha>"],
      "migration_revisions": [],
      "openapi_contracts": [],
      "web_build_ids": [],
      "scope": {
        "scope_kind": "project_campaign",
        "project_refs": ["project:<uuid>"],
        "campaign_refs": ["campaign:<uuid>"],
        "environment_name": "live-staging",
        "environment_fingerprint": "<sha256>",
        "connection_refs": ["connection:<opaque-id>"],
        "account_refs": ["redacted-account:<opaque-id>"]
      },
      "release_refs": [
        {"kind": "surface", "id": "<id>", "sha256": "<sha256>"}
      ],
      "test_runs": [
        {"id": "<id>", "command": "<command>", "collected": 1, "passed": 1, "failed": 0, "skipped": 0}
      ],
      "live_run_ids": ["<live-run-id>"],
      "artifacts": [{"uri": "s3://...", "sha256": "<sha256>"}],
      "owner": "<identity-ref>",
      "verifier": "<identity-ref>",
      "verified_at": "<ISO-8601 UTC>",
      "deviations": []
    }
  ]
}
```

顶层 Git/migration/OpenAPI/environment 字段只用于 manifest 索引，不能替代 `checks[]` 的逐项映射。`git_commits` 对每个完成项必填；`migration_revisions`、`openapi_contracts`、Campaign、Connection、Account 或 live run 不适用时可以为空，但必须有对应 DoR/DoD 或 scope applicability 的 `not_applicable` 记录及独立 verifier。

scope applicability ID 固定为 `SCOPE-PROJECT`、`SCOPE-CAMPAIGN`、`SCOPE-CONNECTION`、`SCOPE-ACCOUNT`、`SCOPE-ENVIRONMENT` 和 `EVIDENCE-LIVE`。环境名称/指纹始终 required；Project-scoped 项的 Project required；Customer/Campaign 项的 Campaign required；external/live 项的脱敏 Connection/Account 与 live evidence required。只有全局 governance/release 等确实不绑定这些 scope 的工作包才能记录 N/A，且遵守总路线图第 1.3 节的理由、依据、decided_by、verified_by、时间和 evidence reference 规则。

manifest 不保存 token、账号邮箱、proxy password、Cookie、参与者 PII 或供应商 raw 禁止字段。真实账号只保存不可反推 PII 的脱敏 connection/account reference；verifier 必须能通过受控后台把 reference 与实际验收账号对应，但该映射不进入普通 evidence bundle。

## 11. 最终专项发布 checklist

- [x] `EXT-PLAN-TIME-01` 本专项与总路线图均使用 `T+0`--`T+5` 连续交付窗口；`M0`--`M6`、所有 `EXT-GATE-*`、样本量和证据门槛保持不变。
- [ ] `EXT-FINAL-01` `EXT-GATE-M0` 至 `EXT-GATE-M6` 全部 `ACCEPTED`，无跳过波次或用后续证据倒填未发生的验收。
- [ ] `EXT-FINAL-02` Connector、Provider、Surface、Egress、Sampling、安全/恢复的所有 `*-FINAL-*` 项均已签字。
- [ ] `EXT-FINAL-03` 五类 API、真实 GSC/GA4、真实官方报告和三个消费者 surface 当前轨道均有最终 Gate 时有效的证据。
- [ ] `EXT-FINAL-04` 每个 Adapter/Surface Release 的授权、条款、保留、SDK/browser/parser、fixture/live hash 和 rollback release 可查。
- [ ] `EXT-FINAL-05` 所有来源在 Admin、Customer、API、export、Metric input 中使用同一身份和 eligibility；GSC/GA4/official-report 只经 approved External Data Report 可见，零绕过批准或跨分母污染。
- [ ] `EXT-FINAL-06` 澳洲出口证据能逐 Attempt 证明 sticky pre/target/post 同源；没有把裸 IP、周期健康检查或供应商地区声明当成页面真实性。
- [ ] `EXT-FINAL-07` 备份恢复后全部业务关系、工件和代表性 secret 可用；错误/缺失历史 key fail closed。
- [ ] `EXT-FINAL-08` Product、Connector、Sampling、Browser、QA、Security、Migration 和 release owner 最终签字，无未批准 P1/P2 风险。

## 12. 官方实现参考

以下链接用于 Adapter Release 实施时核对能力和条款。每次发布保存当时文档/条款版本；本文不把当前字段、模型或限额当作永久合同。

- [PyAirbyte](https://docs.airbyte.com/developers/pyairbyte)
- [Airbyte Google Search Console Connector](https://docs.airbyte.com/integrations/sources/google-search-console)
- [Airbyte Google Analytics 4 Connector](https://docs.airbyte.com/integrations/sources/google-analytics-data-api)
- [OpenAI Web Search](https://developers.openai.com/api/docs/guides/tools-web-search)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Gemini Grounding with Google Search](https://ai.google.dev/gemini-api/docs/google-search)
- [Perplexity API](https://docs.perplexity.ai/docs/getting-started/overview)
- [Microsoft Grounding with Bing Search](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools)
- [Kimi Chat API](https://platform.kimi.ai/docs/api/chat)
- [Playwright BrowserContext](https://playwright.dev/docs/api/class-browser#browser-new-context)
- [Google 搜索位置说明](https://support.google.com/websearch/answer/179386)
- [Google machine-generated traffic 政策](https://developers.google.com/search/docs/essentials/spam-policies#machine-generated-traffic)
- [Microsoft Services Agreement](https://www.microsoft.com/en-us/servicesagreement)
