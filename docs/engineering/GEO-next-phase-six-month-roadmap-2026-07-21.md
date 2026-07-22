# GEO 后续六个月实施路线图

> 计划日期：2026-07-21
> 修订日期：2026-07-22（第 3 次修订）
> 计划状态：`PLANNED`
> 计划周期：启动后连续六个月，以月度退出门槛而非自然月末作为批次完成标准
> 决策来源：[README 下一阶段发展目标](../../README.md#下一阶段发展目标)、[GEO 效果优先整改决策记录](../audits/GEO-effect-first-remediation-decisions-2026-07-18.md#6-c-组效果测量判断和优化)
> 当前能力来源：[F-019 RAG 核心集成合同](F019-core-integration-contract-2026-07-19.md)、[F-019 QuestionSet/Protocol/Simulation 合同](F019-question-set-protocol-simulation-contract-2026-07-19.md)
> 范围变更：按 2026-07-22 用户决定，将 Google AI Overviews/AI Mode、Bing Copilot 及其他获准消费者 AI 界面自动采样纳入本阶段重点；本路线图中的新边界取代本文件初版的排除项，既有审计决策保留为历史依据
> 第 2 次修订变更：引入授权双轨完成定义和第 2 月授权决策点（第 2.4 节）；一方事件入口升级为归因主来源，GA4 降级为聚合对账（第 6.3 节）；风格采集渠道纳入与消费者 surface 对称的授权门槛并增加人工样本导入路径（第 5.2 节）；出口验证改为 Session 级语义并新增吞吐预算合同（第 7.1/7.2.2 节）；`reference_translation` 移出首批交付；供应商存储/保留条款纳入 adapter release 合同（第 4.2 节）
> 第 3 次修订变更：闭合在线迁移追尾、Secret/备份恢复、真实归因、统计不确定结论、逐 Surface Release 保真度、粘性代理证明、登录工件治理、人力容量、建议失效传播和性能负载门禁

## 1. 执行结论

未来六个月交付五个可以使用真实账号、真实数据和不可变证据验收的业务板块：

| 板块 | 六个月完成定义 |
|---|---|
| 内部合成测评实验室 | 九个标准渠道均具备澳洲英文风格样本、版本化 Style Profile、知识冲突检查、修订闭环和三臂离线 GEO 实验；全部结果保持 `test_only=true`、`publication_eligible=false` |
| 外部数据与跨引擎采样 | Connector Core、GSC、GA4、Google/Bing 官方报告、五类 Provider API adapter，以及通过已验证澳洲出口采集 Google AI Overviews/AI Mode、Bing Copilot 等真实消费者界面的 Browser Capture Connector 在 live staging 运行；未取得授权依据的 surface 按第 2.4 节 B 轨（fixture + 人工采样）完成并记录降级决定，不阻塞阶段验收；来源类型、原始工件和分母不可混淆 |
| 统计实验与告警 | 重复采样、完成度门槛、区间、胜/等效/负/不确定、跨问题负收益、漂移、阈值/基线告警及完整处置记录可重复计算 |
| 本地业务归因 | 一方事件入口（Session/Touch 主来源）、UTM、无 PII trace token、Session、Touch、Lead、Conversion、Deal、Revenue 与 Campaign、QuestionSet、内容/Package Version、verified URL 串联，并生成版本化归因快照；GA4 作为聚合对账口径 |
| 可解释建议闭环 | 建议可以回溯到真实观测、统计、归因、Fact、规则和 Prompt Release；人工批准后只创建实验、问题、内容或采样草稿 |

本阶段不是自动发布平台，也不是完整 CRM。人工审核、人工发布和 Customer 只查看已批准真实结果的现有边界继续有效。`synthetic`、内部评审中间结果、未批准建议、原始凭据和内部调试字段永不进入 Customer 投影。

阶段验收不依赖任何第三方平台授权的实际取得；依赖的是每个自动采集 surface/渠道都有明确的授权结论，以及对应轨道（第 2.4 节）的完成证据。

六个月结束时，系统应能回答以下闭环问题，并提供可复核证据：

```text
哪些真实数据或外部回答发生了变化？
  -> 变化是否超过冻结协议的样本和统计门槛？
  -> 变化涉及哪些问题、来源、页面、内容版本和业务结果？
  -> 系统为什么建议修改、实验、不修改或继续采样？
  -> 人工批准后创建了哪个草稿，后续真实结果如何回填？
```

## 2. 范围和不可变边界

### 2.1 本阶段包含

1. 通用 Prompt Program 和多模型 Model Gateway。
2. 本地加密 Secret Store 及项目级 secret reference。
3. 九渠道风格采集、Style Profile、合成 Candidate、评审、修订、Corpus 和离线实验。
4. Connector Core、PyAirbyte 运行底座、GSC/GA4 同步和 Google/Bing 官方报告导入。
5. OpenAI、Gemini Grounding、Perplexity、Microsoft Bing Grounding 和 Kimi 的 Provider API 采样。
6. Google AI Overviews、Google AI Mode、Bing Copilot 及后续获准消费者 AI surface 的浏览器自动采样，支持用户提供的澳洲 HTTP CONNECT/HTTPS/SOCKS5 代理出口。
7. 重复采样、语义指标、统计比较、漂移和告警中心。
8. 最小本地归因账本及 GA4/Snowplow 一方事件入口。
9. 可解释建议、人工批准和下游草稿创建。
10. Admin 全功能界面、Customer 已批准真实结果投影、兼容迁移和 live staging 验收。

### 2.2 本阶段明确不做

- 不自动发布到 CMS、站点或第三方渠道，不自动执行建议。
- 不把 Provider API、proxy grounded API、官方聚合报告、manual UI、automated UI 或 synthetic 合并成同一“真实 AI 可见性”分母。
- 不使用代理轮换、stealth/fingerprint 伪装、验证码代答、限流规避或封禁绕过；代理只用于复现经验证的地域出口，检测到访问阻断时停止并记录。
- 不把 B 轨（无授权依据）下的 fixture 或人工采样证据标注为 `automated_ui` 自动采集完成；轨道归属永远显式记录（第 2.4 节）。
- 不承诺一个澳洲 IP 等于所有澳洲消费者的统一结果；系统只证明冻结账号/匿名模式、设备、语言、位置、Cookie/个性化和时间条件下实际看到的页面。
- 不建设概率身份图、跨设备身份拼接、广告归因或完整 CRM 自动化。
- 不把相关性、last-click 或 assisted attribution 描述为内容变更导致业务结果的因果证明。
- 不让知识库未覆盖本身成为合成文案失败原因；只有与当前批准 Fact 明确冲突或商品/竞品主体串用才进入知识修订路径。
- 不因引入 PyAirbyte、Snowplow 或模型供应商 SDK 而把第三方对象变成领域主数据或建立第二套任务、密钥、审计、Knowledge UI。
- 不在本阶段实现完整传统 SEO 平台；第 13 节只冻结未来兼容方向。

### 2.3 真实性和可见性矩阵

| 数据类型 | `capture_method` | 可进入真实 GEO 指标 | Customer 可见条件 | 说明 |
|---|---|---:|---|---|
| Google/Bing 官方聚合报告 | `official_report_import` | 是，使用独立 typed projection | 报告获批且满足门槛 | 不伪造成单次回答 |
| 消费者 AI 人工采样 | `manual_ui` | 是，独立分母 | 样本合格且报告获批 | 保存采集人、时间和原始证据 |
| 消费者 AI 浏览器自动采样 | `automated_ui` | 是，独立分母 | 授权、地域、保真度和样本门槛均通过，且报告获批 | 必须保存页面证据、浏览器画像和澳洲出口证明 |
| 官方 Provider API | `provider_api` | 是，独立分母 | 样本合格且报告获批 | 不代表对应消费者 UI |
| Grounded proxy/API | `proxy_grounded_api` | 是，独立分母 | 样本合格且报告获批 | 必须显示实际 provider/surface |
| 内部合成或离线仿真 | `synthetic` | 否 | 永不 | 仅 Admin；可用于内部实验 |

未知历史来源继续保持 `unknown/ineligible`，不得迁移为任何真实来源。

### 2.4 授权双轨和授权决策点

自动访问第三方平台（第 7.2 节消费者 AI surface 和第 5.2 节风格采集渠道）统一使用同一套授权机制，不允许双重标准：

- 每个 surface/渠道维护 `authorization_state`：`not_assessed`、`assessed_no_basis`、`approved`、`expired`、`revoked`。`approved` 必须有依据链接/文件、批准人、允许用途、频率和到期日；代理、登录账号或技术可行性都不构成授权。
- **A 轨（有授权依据）**：允许自动采集，按冻结频率、并发和配额运行，按 live 证据验收。
- **B 轨（无授权依据）**：只允许 parser fixture、经授权 PoC 和人工采集/导入（`manual_ui` 或人工样本导入）；对应 surface/渠道标记 `deferred_pending_authorization`，其本阶段完成证据为 fixture 全量回归 + 人工采样对照。
- **授权决策点**：第 2 月退出评审时，对每个自动采集 surface/渠道逐项记录授权结论（`approved` / `assessed_no_basis` / 申请中且有明确期限）。`assessed_no_basis` 即正式降级到 B 轨并重基线化后续月份的相关门槛；不允许无结论的悬置状态跨月存在。决策记录进入当月 evidence manifest；后续取得授权可随时升轨并补做 A 轨验收。
- 阶段 `ACCEPTED` 不以任何第三方授权的取得为前提；前提是每个 surface/渠道要么完成 A 轨证据，要么有记录在案的降级决定和完整 B 轨证据。以 B 轨证据冒充 A 轨完成属于验收造假。

## 3. 总体架构和依赖

### 3.1 共享执行骨架

```text
Admin 控制面
  ├─ Prompt Program / Release / Binding
  ├─ Secret Reference / Connection / Collection Account / Egress Endpoint
  ├─ Review / Approval / Alert Disposition
  └─ Experiment / Recommendation / Draft
             |
             v
Application Service -> Durable Job + Broker Outbox
             |              |
             |              v
             |       Existing Worker / Relay
             |          ├─ Prompt + Model Gateway
             |          ├─ Style Collection / Synthetic Lab
             |          ├─ PyAirbyte / Report Import
             |          ├─ Provider Sampling
             |          └─ Metrics / Attribution / Recommendation
             |
             +------ Browser Capture Worker
             |          ├─ Surface Adapter + Browser Profile
             |          ├─ AU Proxy / Geo Verification
             |          └─ DOM + Screenshot + HAR + Parsed Answer
             |
             +-> PostgreSQL: state, lineage, projections, ciphertext/reference
             +-> MinIO: immutable raw answers, reports, samples, manifests, results
             +-> Valkey: existing broker/cache role only
             +-> model_call_logs: every reserved/succeeded/failed model attempt

Approved real projections only -> Customer API -> Customer Portal
```

所有外部任务复用现有 Durable Job、lease、heartbeat、fencing、取消、重试、outbox、MinIO 内容寻址工件和模型调用日志。外部网络 I/O 期间不得持有数据库事务或行锁；终态、领域行和 outbox 在 fenced PostgreSQL transaction 中提交。

### 3.2 四条并行工作流

| 工作流 | 主交付 | 共享依赖 |
|---|---|---|
| A. 合成与知识 | Style Collection、Profile、Review、Revision、Corpus、Offline Experiment | Prompt Program、Secret Store、Fact/QuestionSet、Model Gateway |
| B. 连接器与归因 | Connector Core、GSC/GA4、官方报告、澳洲 Egress/Browser Capture Connector、事件入口、归因账本 | Secret Store、Durable Job、Content/URL 维度 |
| C. 观测与统计 | Sampling、消费者 UI surface adapter、五类 Provider adapter、语义指标、统计、漂移、告警 | Prompt Program、Model Gateway、QuestionSet、Connector raw artifacts |
| D. Prompt 与建议 | Prompt 生命周期、judge/arbiter、Recommendation、草稿闭环 | A/B/C 的真实 lineage 与版本化输出 |

四条工作流允许按月并行，但以下内容必须单线合入：

- Alembic 迁移始终只有一个 owner 和一个线性 head。
- 共享枚举、OpenAPI schema、Prompt/Model Gateway port 和 artifact manifest 先冻结合同再实现。
- 同一共享表、共享 API schema 或 Customer 投影不得由两条工作流并行修改。
- 每月先通过共享合同测试，再合并工作流功能；不以跨分支临时兼容代码替代合同。

### 3.3 启动前提

- 达到第 3.4 节最低人力配置并完成具名分配；只指定 owner 但没有足额并行 FTE 不启动六个月时钟。
- 准备可产生验收证据的 GSC、GA4、五类 Provider API、至少一个登录采集账号，以及至少一个可路由浏览器流量的澳洲代理出口。
- “可用澳洲 IP”在实现合同中必须是可连接的 HTTP CONNECT/HTTPS/SOCKS5 `host:port`（可附 username/password）或受控网络网关；只有 IP 字符串但没有代理/隧道服务不能作为浏览器出口。
- Google 明确将未经许可的自动查询/结果抓取列为违规流量；Bing 内容的商业下载、复制或产品化也需要明确授权；Amazon、Instagram、TikTok、Reddit 等风格采集渠道的条款同样限制自动抓取。因此任何自动采集启用前必须按第 2.4 节完成授权评审并记录 `authorization_state`；没有明确允许依据时进入 B 轨（parser fixture、人工交互采样、人工样本导入或经授权 PoC），不以代理绕过该门槛。
- 设定月度模型/API 预算和供应商并发上限；预算不足只能缩小 QuestionSet，不得减少统计门槛后仍声称完成。同一规则适用于吞吐：Suite 冻结前必须完成第 7.1 节吞吐预算测算。
- 第三方连接器凭据进入系统前，完成数据库服务角色最小权限复核、负向权限测试和 Secret 轮换演练。这是既有 F-017 重新评估条件被触发后的进入门槛。
- 任何真实 Connector/Provider/代理凭据或 Lead、Deal、Revenue 数据进入系统前，重新开启 F-003 备份安全门禁：备份目录 `0700`、文件 `0600`、PostgreSQL/MinIO 备份静态认证加密、备份加密密钥与应用 Secret 主密钥隔离、checksum/签名验证和第 4.3 节外部 keyring 恢复演练必须全部通过。未通过时只能使用无敏感信息 fixture。

### 3.4 最低人力和降范围规则

六个月排期以以下有效月均投入为启动硬门槛。FTE 可以由多人拆分，但同一人的并行分配合计不得超过 `1.0`，共享角色必须在月度容量表中显式分摊：

| 能力/工作流 | 最低 FTE | 最低组成 |
|---|---:|---|
| A. 合成与知识 | 1.5 | 1 名资深 backend/ML + 0.5 data/evaluation |
| B. 连接器与归因 | 2.0 | 2 名资深 backend/data；其中至少 0.5 FTE 保护给迁移/数据合同 |
| C. 观测与统计 | 2.0 | 1 名资深 browser/backend + 1 名 statistics/data/backend |
| D. Prompt 与建议 | 1.0 | 1 名资深 backend/ML |
| 跨流 Frontend | 1.5 | Admin 1.0 + Customer/共享组件 0.5 |
| QA/测试自动化 | 1.0 | 集成、浏览器、live evidence 和恢复验收 |
| DevOps/Security | 0.5 | 网络、Secret、备份、staging 和容量 |
| Product/运营明审 | 1.0 | 授权决策、样本明审、真实归因旅程和月度签字 |

工程最低投入为 `9.5 FTE`，另加 `1.0 FTE` Product/运营。迁移/共享合同 owner 从 B/C 的资深人员中具名指定，但其受保护容量不得被功能开发占用。

容量不足时按以下规则处理：

1. 短缺不超过 20% 且不连续超过一个月时，先移除三个首批消费者 surface 之外的扩展、managed-account 可选 cohort、非关键 UI polish 和其他明确 optional 项；Secret、备份、迁移、统计正确性、三个首批 surface 合同和真实归因旅程不得降级。
2. 工程投入低于 `7.6 FTE`、Product/运营低于 `1.0 FTE`，或任一 A/B/C/D 工作流低于表中最低值连续两个 sprint 时，暂停六个月时钟并创建范围/日期变更记录；不得通过把工作串行化但保留原截止日来宣称排期仍成立。
3. 降范围影响五个板块任一完成定义时，阶段状态保持 `IN_PROGRESS`，只能延长日期或由新的批准决策修改完成定义，不能在 evidence manifest 中豁免。

## 4. 共享基础合同

### 4.1 Prompt Program

Prompt Program 是现有 Prompt/Skill Release 能力的通用化，不建立互不兼容的第二套提示词目录。首批支持以下 `program_kind`：

| kind | 输入重点 | 结构化输出重点 |
|---|---|---|
| `generation` | scenario、Fact、Style Profile、channel | Candidate 文案、claim hints、使用的事实引用 |
| `claim_extraction` | Candidate | claim、subject、predicate、object、confidence、span |
| `conflict_check` | claims、approved Facts、Catalog identity | supported/derived_or_unknown/conflict/subject_mix |
| `revision` | Candidate、评审问题、允许的事实和风格 | 修订 Candidate、修改说明、保留 claim lineage |
| `style_judge` | Candidate、Style Profile、匿名短例 | 1-5 分、维度分、失败原因、复刻风险 |
| `arbiter` | 多个 judge 结果及证据 | 最终 disposition 和可解释理由 |
| `metric_judge` | 原始回答、引用、Fact、metric schema | 语义指标和逐项 evidence locator |
| `recommendation` | 真实观测、统计、归因、规则 | 建议类型、影响链、置信度、验证计划 |

`reference_translation`（翻译与术语映射）保留枚举值但移出首批交付：本阶段没有任何工作流消费它，待出现明确消费方（如多语言参考材料）再排期，避免孤儿交付。

每个 Program 至少保存变量 schema、输入/输出 JSON Schema、模板、适用模型策略、测试集、compiler version 和 owner。Admin 支持创建、测试、与当前 approved Release 做固定输入差异比较、批准、冻结、绑定和退役。

运行时必须冻结并记录：

- Program/Release ID、版本、release hash、compiler version 和 binding ID。
- system/user template 的已编译 hash、变量输入 hash 和输出 schema version。
- provider、adapter release、配置模型、供应商报告模型、采样参数和模型策略版本。
- Fact/Profile/QuestionSet/Corpus/metric method 等所有业务输入版本。

冻结 Release 不可原地修改；变更创建新 Release。供应商返回符合 JSON Schema 仍只代表语法层成功，应用侧继续执行 schema、枚举、长度、主体归属、Fact 引用和领域状态校验。OpenAI Structured Outputs 等供应商能力只作为 adapter 优化，不能替代领域校验。

### 4.2 Model Gateway

在现有 DeepSeek adapter 之外增加 OpenAI、Kimi、Gemini、Perplexity 和 Microsoft adapter。Gateway 使用统一 request/result/error 合同，但保留供应商差异字段：

- request：purpose、configured model、messages、JSON Schema、temperature/seed（若支持）、tool/search mode、预算、deadline、idempotency key。
- result：reported model、finish reason、structured payload、usage、citations/tool events、provider request ID、latency、raw artifact reference。
- error：auth、quota、rate limit、timeout、schema invalid、content refusal、provider unavailable、cancelled、non-retryable validation。
- policy：项目允许供应商、数据发送范围、每类调用预算、并发、重试和 fallback。不得在未冻结策略下静默切换模型。

每次调用先写 reserved model call log，再记录 succeeded/failed；重试创建新 attempt。Provider 的幂等、限流、`Retry-After`、取消和并发限制由 adapter 解释为统一错误，不由业务工作流各自实现。

adapter release 合同必须记录该供应商对结果存储、缓存、展示和再分发的条款约束（例如 Grounding with Bing Search 的使用与展示要求）。默认的 MinIO 不可变原文存储只适用于条款允许持久化的供应商；条款限制保留的字段按 adapter 合同以保留窗口、加密引用或不落盘处理，条款冲突未解决前该 adapter 不得发布，fail closed。

### 4.3 本地加密 Secret Store

Secret Store 采用 envelope encryption：PostgreSQL 只保存 ciphertext、nonce、algorithm/key version、secret reference、scope、状态和审计元数据；主密钥通过 Docker Secret 注入，仅在需要解密的 Internal API/Worker 进程内存中短暂存在。

必须满足：

1. Connection、Style Collection Account、Model Provider、Egress Endpoint 和 Browser Account 只持有 secret reference。
2. Job payload、outbox、日志、异常、MinIO 工件、导出和 Customer API 不出现明文凭据。
3. 创建后 UI 不回显 secret；测试连接仅返回非敏感分类。
4. 支持创建新版本、验证、原子切换、撤销旧版本和完整审计；运行中的 Job 冻结 reference version，不冻结明文。
5. 日志 redaction 同时覆盖 header、query、form、JSON、SDK exception 和 provider request dump。
6. 主密钥缺失、权限过宽、版本未知或解密失败时进程/preflight fail closed。
7. 维护独立于 PostgreSQL/MinIO 备份的加密历史 keyring/escrow，覆盖所有仍有 ciphertext 引用的 master key version、算法、状态和恢复说明；keyring 由至少两名授权保管人控制，不与数据备份、备份加密密钥或同一宿主机明文共存。
8. 每个 master key version 保存不含业务凭据的 known-plaintext decrypt canary；轮换只有在旧 ciphertext 全量 rewrap、逐版本 canary 和代表性 Connector/Provider/Egress secret 解密验证通过后才能退役旧 key。
9. 空环境恢复必须先恢复/挂载历史 keyring，再恢复数据；逐版本 canary、代表性有效 secret 解密和一次不泄密的 connection test 全部通过，才能声明 Secret Store 已恢复。只有数据库行、ciphertext hash 或 MinIO hash 一致不构成恢复成功。

### 4.4 Durable Job 和工件

新任务至少包含以下 job kind：

`style.collect`、`style.profile.build`、`review.case.run`、`candidate.generate`、`candidate.revise`、`offline_experiment.run`、`connector.sync`、`official_report.import`、`egress.verify`、`browser.capture`、`sampling.task.run`、`metric.compute`、`drift.compute`、`alert.evaluate`、`attribution.snapshot` 和 `recommendation.generate`。

每类任务遵循相同规则：

- enqueue 时冻结业务输入 ID/version/hash、adapter release、预算和 requested_by。
- 长任务按安全检查点 heartbeat，并在每次外部调用和提交前校验 lease/fencing/cancel。
- 原始输入/输出通过第 4.5 节落盘前治理后再写 MinIO 内容寻址对象，并以 manifest URI/hash 引用；数据库不存大段原始网页、回答或报告正文。
- terminal state 与领域 revision 一次 fenced 提交；丢失 lease 的旧 Worker 不能覆盖新 owner 结果。
- 重跑创建 Attempt/Run/revision，不覆盖历史成功或失败证据。
- artifact manifest 至少保存 schema version、content hash、byte size、record count、source identity、created_at 和 producer release。

### 4.5 原始工件落盘前治理

登录页面、浏览器 HAR/DOM/截图和第三方回答可能包含账号标识、Cookie、受限内容或 PII。首次真实登录采集前必须实现并测试以下分类和处置，不能先把“原始”内容不可变落盘后再补脱敏：

| 分类 | 允许内容 | 落盘与访问 | 默认保留 |
|---|---|---|---|
| `public_raw` | 公开页面且不含 secret/高风险 PII | 加密 MinIO raw bucket；仅内部证据角色 | 90 天 |
| `restricted_authenticated_raw` | 获准登录后页面的必要证据 | artifact 独立 DEK 加密、受限 bucket；仅 `style_raw_reviewer`/security auditor | 30 天 |
| `derived_anonymized` | 去标识文本、结构化答案、引用和必要 locator | 标准项目范围；可进入后续评审 | 随对应 Corpus/Observation 生命周期 |
| `secret_bearing_rejected` | Cookie、Authorization、session token、密码、完整 storage state 或无法可靠脱敏的内容 | 禁止写 PostgreSQL/MinIO/日志；立即销毁临时数据 | 0 |

- 浏览器临时 HAR/DOM/截图只写加密 tmpfs；持久化前执行 header/query/form/Cookie 清除、用户名/头像/账号链接和直接标识符检测。检测失败时整个 raw bundle 进入 `secret_bearing_rejected`，不得“先存后删”。
- 对必须保留视觉/DOM 证据的登录页面，同时生成受限加密 raw bundle 和 `derived_anonymized` bundle；普通运营、模型训练/生成、Customer、通用导出和 recommendation 不得读取受限 raw。
- adapter/平台条款要求更短保留或禁止持久化时，以更严格规则覆盖上表。TTL 到期删除对象和 artifact DEK，manifest 只保留 hash、分类、删除时间和 tombstone，不保留可恢复正文。
- 唯一删除例外为显式 `legal_hold`/incident hold：需要两名授权人员批准、原因、对象范围和不超过 90 天的到期日；延期必须重新批准并审计。不得用“调试需要”建立无限期例外。
- 行为测试至少注入 Cookie、token、用户名、账号 URL、头像、邮箱和受限页面内容，证明 raw/derived 分流、RBAC/RLS、TTL 删除、hold 到期和 Customer/导出负向边界。

## 5. 工作流 A：内部合成测评实验室

### 5.1 领域对象和生命周期

| 对象 | 职责 | 关键版本/状态 |
|---|---|---|
| Style Source | 平台/页面/账号引用和采集边界 | source revision、access mode、locale、channel |
| Collection Run | 一次可复核采集 | adapter release、checkpoint、raw manifest、终态 |
| Style Sample | 去重匿名短样本 | sample hash、AU English 标签、review status |
| Style Profile Version | 平台风格的版本化统计/指令画像 | corpus hash、Prompt Release、approved/frozen |
| Review Suite/Case | 固定回归场景和期望 | mode、competitor flag、Fact/Question version |
| Review Run | 对冻结 Suite 的一次执行 | model/judge matrix、完成度、终态 |
| Candidate | 单个生成候选 | batch、ordinal、generation/revision lineage |
| Evaluation | judge/规则的逐项结果 | evaluator release、evidence locator、score/disposition |
| Revision | 对候选的一轮修订 | parent candidate、issue set、round 1/2 |
| Corpus Version | 已通过和 warning 候选的冻结集合 | passed/warning 分层及 hash |
| Offline Experiment | baseline/current/candidate 三臂配对实验 | QuestionSet、10 repetitions、method version |

### 5.2 风格采集

九个标准渠道固定为 `owned_site`、`amazon`、`youtube`、`tiktok`、`instagram`、`productreview`、`reddit`、`ozbargain` 和 `quora`。

- 支持公开页面和显式配置的登录后页面。自动登录只能使用 Secret Reference 和正常登录流程；不得绕过验证码、封禁、付费墙或其他访问控制。
- 每个渠道启用自动采集前适用第 2.4 节授权机制：保存条款评审、允许行为、频率和到期日；`assessed_no_basis` 的渠道只使用人工采集/导入路径，不因风格采集不是 AI surface 而豁免。
- 人工采集/导入是一等路径：运营人员人工浏览并提交样本，Admin 导入时保存采集人、时间、来源 URL、原文/截图工件和 hash；人工样本与自动样本进入同一去重、匿名和明审流程，200 条门槛可全部由人工导入满足。
- 以视频/图片为主的渠道（如 `tiktok`、`instagram`、`youtube`）明确样本对象为标题、字幕、描述和评论等文本，并预期以人工路径为主。
- 采集 adapter 保存最终 URL、时间、locale/region、登录/公开模式、页面 hash、解析器版本和原始工件；重定向和 egress 继续受现有安全策略约束。公开、登录和人工导入工件全部先执行第 4.5 节分类、脱敏、加密、访问和 TTL 合同，尤其不得把登录页面原件先写入普通 MinIO bucket。
- 每个平台发布 Style Profile 前至少有 200 条去重、匿名、澳洲英文、人工明审通过的样本。样本不保存用户名、头像、账号链接或其他不必要标识。
- 去重同时覆盖规范化精确 hash、近重复和跨 run 重复；同一内容不能因多次采集增加权重。
- 生成时使用统计 Style Profile 和少量匿名短例。短例有最大长度和重叠检测；不得要求模型复刻某一作者或完整原文。

### 5.3 场景、生成和冲突语义

Review Case 支持两种模式：

- `autonomous_scenario`：系统根据 Persona、UseCase、channel、QuestionSet 和 approved Fact 构造场景。
- `guided_scenario`：运营输入仅作为创意参考，不成为事实源，不可覆盖 approved Fact、Catalog 主体或渠道边界。

每个 Case 默认生成 4 个候选。单个候选按以下确定性状态机处理：

```text
generate
  -> claim extraction
  -> conflict + subject check
  -> style/judge evaluation
      ├─ pass ---------------------------> passed
      ├─ only derived/unknown or soft issue -> completed_with_warning
      └─ correctable conflict/style issue -> revision round 1
                                               -> revision round 2
                                               -> regenerate one batch
                                                   ├─ pass/warning
                                                   └─ failed
```

知识判定冻结如下：

- 与当前 approved Fact 一致或可直接蕴含：`supported`。
- 知识库没有覆盖、但属于允许的产品/场景推演：`derived_or_unknown`，允许输出并形成 warning/标注，不因缺少 Fact 自动修订。
- 与当前 approved Fact 明确矛盾：`conflict`，进入修订。
- 品牌、商品或竞品属性错配：`subject_mix`，进入修订并作为零容忍门槛。
- 已批准 Fact 在运行中 retired/失效时，后续步骤必须停止使用；当前 run 以可解释失败或重新绑定新版本结束，不静默改写冻结输入。

最终 Review Run 状态只有 `passed`、`completed_with_warning` 或 `failed`。Warning 文案可以进入离线仿真和总体指标，但所有页面/导出必须同时显示 warning 数量、占比和独立分层结果，禁止只显示合并后的总体均值。

### 5.4 Corpus 和离线 GEO 实验

默认实验使用同一冻结 QuestionSet 的三臂配对设计：

1. `no_corpus_baseline`：无语料基线。
2. `current_approved_corpus`：当前批准语料。
3. `new_candidate_corpus`：新候选语料。

每题每臂默认重复 10 次；相同 repetition index 共享冻结问题、模型策略和运行参数，形成配对单位。实验保存原始回答、引用、模型身份、Corpus hash、QuestionSet hash、Prompt Release、随机/seed 能力、metric method 和失败原因。

合成实验不得写入真实 Observation 分母，不得出现在 Customer Portal。Admin 必须明确显示 `synthetic`、`test_only`、`publication_eligible=false`，并允许按 passed/warning、channel、scenario mode、competitor、model 和 Question cluster 分层。

## 6. 工作流 B：连接器和本地归因

### 6.1 Connector Core

Connector Core 的领域模型固定为：

| 对象 | 关键职责 |
|---|---|
| Connector Definition | connector kind、adapter release、固定 PyAirbyte/SDK 版本、capability/schema |
| Connection | project、definition、secret reference、状态和授权身份摘要 |
| Scope | property/account/stream、locale、时间范围和只读权限 |
| Checkpoint | cursor/watermark/state hash；成功提交后推进 |
| Sync Run | 冻结 definition/connection/scope/checkpoint、进度和终态 |
| Raw Artifact | 原始 payload/file、manifest、hash 和 source lineage |
| Schema Version | 原始 schema fingerprint、兼容性判定和变更记录 |
| Projection | GSC/GA4/官方报告的 typed、幂等业务投影 |
| Freshness | expected/observed watermark、lag、stale reason |
| Connector Error | auth/quota/rate-limit/schema/revoked/transient/permanent 分类 |

PyAirbyte 嵌入现有 Worker，不新增常驻 Airbyte 控制面。connector package/image 版本固定在 Definition release；升级必须以代表 fixture 和真实 canary 连接生成新 release。第三方 state 只能作为 checkpoint payload，项目自己的 Connection、Run、工件和 projection 仍是业务真源。

首批交付：

- GSC：只读 Search Console 数据，项目/站点 scope，增量窗口和回刷。
- GA4：只读 Data API 报告，property scope，维度/指标 schema 版本化。
- Google Generative AI Performance 官方报告文件导入。
- Bing AI Performance 官方报告文件导入。

官方报告导入保存原文件、文件 hash、解析器 release、表头/schema fingerprint、行数、重复检测和 typed projection。报告没有单次回答时不得伪造 Observation。

### 6.2 同步语义

- 同一 Connection/Scope/窗口/adapter release 使用稳定 idempotency key。
- Checkpoint 只在 raw artifact 和 projection 同时成功后推进；失败、取消或 lease 丢失不推进。
- 回刷创建独立 Run，覆盖同一业务键时保留来源 Run lineage，不重复累计。
- schema 兼容变更生成新 Schema Version；未知破坏性变更暂停 projection 并告警，不丢弃 raw artifact。
- 撤权、secret rotation、quota 和 `Retry-After` 有独立可操作错误；重授权后从最后已提交 checkpoint 继续。
- freshness 不能用“Job 成功”代替；必须比较来源 watermark、期望频率和最新有效 projection。

### 6.3 归因账本

归因模块保存最小业务对象，不承担完整 CRM 职责：

`Session -> Touch -> Lead -> Stage -> Conversion -> Deal -> Revenue`

每个对象保存 project scope、source event ID、occurred_at/received_at、source type、schema version、lineage 和去重键。Lead/Deal 仅保存归因所需的本地业务标识及金额/阶段，不要求复制 CRM 全字段。Lead/Stage/Deal/Revenue 通过 Admin 手工录入或幂等文件导入获得：导入模板 schema version、文件 hash、行级去重键和 requested_by 全部冻结；本阶段不建 CRM 集成。

一方事件入口是 Session/Touch 的主来源：复用 Snowplow Browser Tracker（或兼容 SDK）向本地接收端发送事件；collector endpoint、event schema、consent/启用状态和 SDK release 必须版本化，Snowplow 只是采集 adapter，不成为归因规则引擎。GA4 Data API 只提供聚合报表，无法重建用户/会话级链路，因此 GA4 定位为聚合口径对账和 freshness 参考，不作为 Session/Touch 真源；GA4 BigQuery export 不在本阶段范围。一方采集端未上线或未获 consent 的站点，归因页面只显示官方聚合与 exposure 口径，不得用聚合数据伪造 Session。

### 6.4 UTM、trace 和口径

- 规范 UTM 至少关联 Campaign、QuestionSet、Package Version、Content Asset 和 verified URL。
- trace token 使用随机、不含 PII、不可反推出客户身份的 opaque token；只用于同意范围内的一方 Session/Touch 关联。
- 禁止基于 IP、User-Agent、时间邻近或模型推断做概率跨设备拼接。
- 没有 click/touch 的零点击曝光保存在独立 exposure/visibility 维度，绝不计为 Session、Lead 或 Conversion。
- 默认 last-click 窗口为 30 天、assisted 窗口为 90 天；窗口、eligible touch、direct 处理和 revenue 规则按 Project 创建不可变 Attribution Policy Version。
- 同一快照同时输出 direct、first-click、last-click 和 assisted 口径；默认决策口径为 30 天 last-click，90 天 assisted 只作补充。
- 所有归因页面标明 observation/association，不输出因果措辞。

## 7. 工作流 C：跨引擎采样、统计和告警

### 7.1 Sampling Core

Sampling Suite/Run/Task 的执行单位固定为：

```text
platform + surface + configured/reported model + capture_method
+ question_version + repetition + locale + region + language + search_mode
+ browser_profile_version + egress_verification_id (UI capture only)
```

每个 Task 可独立租赁、重试、取消和终止；成功必须有原始回答/工件和完整运行参数。Suite 冻结 QuestionSet、目标平台、重复次数、有效完成度门槛、统计方法和预算。Run 只聚合 Task，不把失败 Task 静默从预期分母中删除。

自动 adapter 包括：

1. OpenAI API/Web Search 模式。
2. Gemini Grounding。
3. Perplexity API。
4. Microsoft Bing Grounding。
5. Kimi API/Search 模式。

Provider adapter 名称描述实际 API，不使用 ChatGPT UI、Google AIO/AI Mode、Perplexity consumer UI、Bing Copilot UI 或 Kimi consumer UI 标签。消费者界面由第 7.2 节的 Browser Capture Connector 以 `automated_ui` 独立采样；尚未获得启用依据或尚无稳定 surface adapter 时继续使用 `manual_ui`。

API 采样默认每题重复 10 次，manual UI 每题最低重复 3 次，automated UI 默认每题 5 次且不得低于 3 次；高波动核心问题可在 Protocol 中冻结为 10 次。实际有效 Task 少于冻结样本门槛，或 Run 有效完成度低于 80%，只能输出 `insufficient_evidence`。完成度分母是计划 Task 总数，不能通过删除失败项提高。

Suite 冻结时必须同时冻结吞吐预算：按计划 Task 总数、每平台并发（automated UI 默认 1）、最小请求间隔和日配额推算预计完成窗口并写入 Protocol。预算装不下的 QuestionSet 只能缩小问题数或降低非核心问题重复次数（不得低于下限），不得放宽完成度门槛、混分母或超出授权频率。实际耗时与预算一并保存，作为后续 Suite 规模的依据。

### 7.2 Consumer Surface Browser Capture

Browser Capture Connector 是本阶段真实观测的重点交付，与 Provider API 并列，不是 `proxy_grounded_api` 的别名。首批 surface 为：

1. Google Search AI Overviews。
2. Google Search AI Mode。
3. Bing Search/Copilot 消费者界面。
4. 后续经范围批准的 ChatGPT Search、Perplexity、Kimi 等消费者界面；每个 surface 单独发布 adapter release，不能复用相似 DOM 选择器冒名。

#### 7.2.1 领域对象

| 对象 | 职责 | 必需冻结内容 |
|---|---|---|
| Surface Definition/Release | 页面入口、surface 检测、答案/引用解析和阻断检测 | platform、surface、URL allowlist、selector/parser release、适用条款版本 |
| Egress Endpoint | 用户提供的代理/网关及预期地域 | protocol、secret reference、expected country/region、operator、状态 |
| Egress Verification | 证明同一 Capture Attempt 使用澳洲出口 | sticky lease/session ID、pre/post observed public IP、country/region/city、ASN、network type、可信代理连接日志（若有）、verification sources、artifact hash |
| Browser Profile Version | 复现消费者环境 | browser/build、device/viewport、`en-AU`、timezone、geolocation、region、SafeSearch、account/personalization mode |
| Browser Session | 一次隔离上下文 | profile、egress lease、storage-state reference、started/closed time、session hash |
| UI Capture Attempt | 单个 query/repetition 的执行与终态 | Task、surface release、session、timings、result class、failure class |
| Page Artifact Bundle | 页面原始证据 | screenshot、DOM snapshot、HAR、final URL、console/network summary 及逐文件 hash |
| Parsed UI Observation | 从同一页面提取的回答与引用 | answer text、citation URL/order、surface state、evidence locators、parser version |

#### 7.2.2 澳洲代理和网络隔离

- V1 支持 Playwright/Chromium 可直接使用的 HTTP CONNECT、HTTPS 和 SOCKS5 代理。Admin 创建 Egress Endpoint 时录入 `host:port`、可选 username/password、预期 `AU` 及城市/州；认证信息只进入 Secret Store。
- `browser-capture-worker` 作为隔离运行角色消费现有 Durable Job，不建立第二套队列。其普通公网直连默认拒绝，只允许连接已批准代理端点和最小控制/地域验证 allowlist；页面内所有 HTTP(S)、WebSocket 和 DNS 路径必须经过所选代理。
- Egress Endpoint 必须提供固定出口或可显式申请的 sticky session/lease；lease ID、申请时间、承诺保持时长和到期时间冻结到 Browser Session。没有 sticky 能力时，只有供应商能够提供可信的逐请求连接日志并证明目标 hostname 请求使用同一澳洲出口，Capture Attempt 才可 eligible。
- 每个 Capture Attempt 都在同一 BrowserContext/sticky lease 内执行前置和后置出口验证，前后 observed IP/ASN 必须一致且至少两个独立地域源确认 country=`AU`。若代理提供连接日志，同时保存目标 hostname、lease ID、出口 IP 和时间范围的签名/hash 引用；周期复验只能补充健康检查，不能替代逐 Attempt 前后证明。
- 两源一致判非 AU 为 `geo_mismatch/ineligible`，两源不一致为 `geo_unverified/ineligible` 并告警（可配置第三源做 tie-breaker，但 eligible 仍需至少两源一致）。前后 IP/ASN 不一致、lease 到期或目标请求不在可信连接日志范围内时，当前 Attempt 为 `egress_changed/ineligible`；之前已完成逐 Attempt 前后验证的结果不受影响。
- residential/mobile 出口的 IP/ASN 跨 Session 漂移属预期行为：新 Session 申请新 lease 并重新验证。不得仅依赖供应商声称的保持时长，也不得用 Session 开始时的一次验证覆盖其后的全部 Page Artifact Bundle。
- Egress Verification 区分 `residential`、`mobile`、`datacenter` 和 `unknown`。澳洲数据中心 IP 只能标记 `au_geo_verified`，不能标记 `au_consumer_representative`；消费者代表性验收默认要求 residential/ISP 或 mobile 出口。
- Endpoint 健康失败可以由运营人员显式切换到另一个已批准 Endpoint；检测到 CAPTCHA、封禁或限流后不得自动轮换代理继续请求。
- Proxy 的目的仅是地域复现。系统不修改自动化特征来规避检测，不注入 stealth patch，不自动解 CAPTCHA，不复用来路不明的 Cookie/账号。

Playwright 的 BrowserContext 原生支持 HTTP/SOCKS proxy、locale、timezone、geolocation、storage state、HAR 和隔离 Cookie；实现固定 Playwright/Chromium release，并在 adapter 升级时重新执行保真度回归。

#### 7.2.3 澳洲消费者浏览器画像

IP 只是地域信号之一。Google 官方说明搜索位置还可能来自设备位置、账号的 Home/Work、历史活动、Cookie 和 IP；Bing 也会使用设备位置、IP、语言、历史和设备特征。因此每次采样必须冻结并展示：

- `locale=en-AU`、`Accept-Language`、`timezone=Australia/Sydney`（或 Protocol 指定的澳洲时区）。
- desktop/mobile device、viewport、浏览器/OS build、User-Agent 和 SafeSearch。
- browser geolocation 及是否授予页面 location permission；指定城市时保存坐标来源和精度，不用虚假高精度定位扩大结论。
- platform region/location setting、页面底部或设置页显示的 detected location，以及最终服务域名/URL。
- `clean_anonymous` 或 `managed_test_account`；两类使用独立分母。后者冻结账号区域、语言、年龄适用状态、搜索历史/个性化开关和 storage-state secret version。
- Cookie/consent 状态、Search Labs/实验资格（若有）、登录状态、采集时间和页面报告的模型/模式（若有）。

默认每个 repetition 使用全新 `clean_anonymous` BrowserContext；需要衡量个性化时创建独立的 managed cohort，不在运行中把匿名上下文升级为登录上下文。一个验证过的澳洲出口加上述冻结画像只能证明“该条件下的澳洲消费者界面实测”，不能外推为全澳所有用户唯一结果。

#### 7.2.4 页面采集和解析状态机

```text
authorization/policy gate
  -> egress verification (AU)
  -> isolated BrowserContext + frozen profile
  -> in-page location/region verification
  -> submit frozen query through normal UI
  -> wait for documented surface-ready condition
  -> capture screenshot + DOM + HAR + final URL
  -> detect surface/answer/citations
       ├─ answer present ----------> captured/eligible
       ├─ complete page, no surface -> surface_not_present/eligible negative
       ├─ consent/login required ---> blocked/ineligible
       ├─ CAPTCHA/rate-limit/ban ---> access_blocked/ineligible and stop endpoint
       ├─ geo mismatch ------------> geo_mismatch/ineligible
       ├─ egress changed/unverified -> egress_changed|geo_unverified/ineligible
       └─ selector/timeout --------> parser_failed|timeout/ineligible
```

- 只有原始页面证据完整、地域验证有效、surface release 匹配且解析字段可回指 DOM/screenshot 的结果才可 `eligible=true`。
- `surface_not_present` 必须证明普通结果页已完整加载且阻断/解析健康检查通过，才能作为 AI surface 未出现的有效负样本。
- Google AI Overviews、AI Mode 和 Bing Copilot 分开识别入口、模式、回答、折叠状态、引用卡片/链接和 follow-up；不得把普通 featured snippet、knowledge panel 或 Bing 传统 SERP 错标为 AI 回答。
- 页面保存全屏及答案区域截图、最终 DOM snapshot、必要 HAR 和结构化提取；不得只保存解析后的纯文本。敏感账号/Cookie/header 在写 MinIO 前剥离或加密引用。
- selector/parser 失败触发 adapter drift 告警和人工复核，不把空解析当成 surface 缺失。

#### 7.2.5 授权、节流和保真度门槛

Google 的公开政策明确将未经许可的自动查询和结果抓取列为违规流量；微软条款也限制未获授权的下载、复制、再分发或产品化使用。因此实现和 fixture 开发可以先完成，但每个真实 surface release 必须有 `authorization_state=approved`、依据链接/文件、批准人、允许频率、用途和到期日，过期自动停用。授权结论和轨道切换按第 2.4 节授权决策点执行：`assessed_no_basis` 的 surface 进入 B 轨，以 fixture 全量回归 + `manual_ui` 对照作为本阶段完成证据。澳洲代理不构成授权，也不能被用于规避平台限制。

每个平台默认并发为 1，使用冻结的最小请求间隔和日配额；收到阻断信号立即停止该 Endpoint/Surface Run。平台明确许可的频率高于或低于默认值时，以授权记录为准。

adapter 发布前，对同一 Page Artifact Bundle 做人工逐字段复核。所有比例门槛按精确的 `platform + surface + Surface Release + Playwright/Chromium release` 分别计算，禁止跨 release 或跨 surface 汇总后通过：

- surface 分类准确率 `>= 95%`，且普通结果误标为 AI 回答为 0。
- answer 可见文本完整率 `>= 99%`。
- citation URL、顺序和可见标题逐项一致率 `100%`。
- CAPTCHA、登录墙、consent、限流、geo mismatch 和 parser drift 不得误判为有效负样本。
- 每个 A 轨 Surface Release 独立包含至少 20 个澳洲 live capture：至少 10 个 `captured/eligible`；对按 query 决定是否出现的 surface，至少 5 个 `surface_not_present/eligible`；其余样本可以补足真实页面构成。另为该 release 提供阻断 fixture，至少分别覆盖 CAPTCHA、登录墙、consent、rate limit、geo mismatch、egress change 和 selector drift 各 2 个。
- 每个 B 轨 Surface Release 独立包含至少 30 个 fixture（至少 10 个成功页面、适用时至少 5 个有效缺失页面，并覆盖上述每类阻断）以及至少 10 个 `manual_ui` 页面逐字段对照；adapter 只发布到 fixture-ready 状态。
- 任一 release 样本不足或该 release 自身未达到分类/文本/引用门槛时只能保持 candidate/fixture-ready，不得借用其他 release 的样本，也不得用 Provider API 或人工转录冒充 `automated_ui` 结果。

### 7.3 指标

每个指标保存 metric key/version、输入集合 hash、分层键、分子/分母、point estimate、interval、judge/规则版本和可复核 evidence locator。

首批完整指标包括：

- 品牌/产品提及、推荐和推荐强度。
- 竞品提及、相对位置和胜/等效/负/不确定。
- 情感及明确负面理由。
- 事实准确性、明确冲突、主体串用和关键事实遗漏。
- 引用是否蕴含 claim、引用位置/顺序、verified URL 命中。
- 来源域和来源类型多样性。
- 答案对 approved corpus 的吸收度；只作为语义相似/蕴含指标，不声称训练或检索因果。
- 最差问题、最差问题簇和跨查询负收益。

`metric_judge` 的模型输出必须关联原始回答 span、citation 或 Fact；无法给出 locator 的判断为 invalid。确定性规则优先于模型 judge，主体串用、URL 匹配、引用顺序和分母等可规则化项不交给自由文本判断。

### 7.4 统计合同

- 二元单臂比例使用 95% Wilson 区间；比例差使用冻结的 Newcombe 方法。
- 版本/实验比较使用确定性配对 bootstrap；seed 由 Protocol/QuestionSet、两侧版本、metric method 和 comparison ID 的 hash 派生。
- 同一 comparison family 默认使用 Holm 多重比较校正；family、alpha 和校正方法在协议中冻结。
- 每个 metric/comparison 在 Protocol 中预先冻结 practical effect threshold `delta`、目标 power（默认至少 80%）、允许的区间最大半宽/precision、最小有效配对数、alpha 和多重校正 family；运行后不得根据结果放宽。
- 比较结论枚举固定为 `win`、`equivalent`、`loss`、`inconclusive` 和 `insufficient_evidence`：校正后区间下界高于 `+delta` 才是 `win`，上界低于 `-delta` 才是 `loss`；整个校正后区间落在 `[-delta,+delta]` 内且达到冻结 power/precision 条件才是 `equivalent`；样本/完成度低于冻结最低门槛时为 `insufficient_evidence`；其余情况一律为 `inconclusive`。
- UI 不再使用无统计定义的“平”。`equivalent` 只能显示为“达到冻结等效门槛”，`inconclusive` 显示为“不确定/需要更多证据”；automated UI 即使有 3-5 个有效样本并达到 80% 完成度，也不能在区间跨越任一决策边界时被判为等效或方向性结论。
- 负收益同时显示受影响问题数量、幅度、区间和最差问题，平均提升不能遮蔽局部退化。
- 漂移按 provider、reported model、capture method、locale/region、source composition 和 Question cluster 分层；模型或来源构成变化必须与业务效果变化分别报告。
- 不同 capture method 永不共享分母；跨层汇总只能作为带清晰构成权重的二级展示，不能替代独立结果。
- 同一冻结输入和 method version 重算必须得到相同结果和 hash；方法变化创建新版本，不覆盖历史快照。

### 7.5 告警中心

告警规则支持 threshold、baseline delta、negative question、completion/freshness、model drift、source drift 和 connector failure。Alert 保存 rule version、触发快照、证据、严重度、去重 key 和状态。

状态流转为：

```text
open -> acknowledged -> resolved
  |          |
  +-------> suppressed(until/reason) -> open/resolved
```

每次确认、抑制、解除抑制和解决均保存 actor、时间、原因及 disposition。通知通过 Admin inbox、本地 SMTP 和内网 Webhook 发送；Outbox 确保事务后投递，通知失败不回滚告警，重试不得重复创建业务告警。Webhook 只发送非敏感摘要和内部详情链接，签名 secret 使用 Secret Reference。

## 8. 工作流 D：可解释建议闭环

### 8.1 建议证据图

Recommendation 不是模型自由生成的一段文字。每条建议必须保存：

- type：`hard_blocker`、`gap`、`experiment`、`optional`、`no_change` 或 `insufficient_evidence`。
- scope：Project、Campaign、Question/cluster、Surface、Content Asset、URL 和适用版本。
- observation lineage：真实 Observation/官方 projection、capture method、原始工件和样本门槛。
- analysis lineage：Metric Snapshot、comparison、interval、drift、attribution snapshot 和 method version。
- knowledge lineage：approved Fact、Catalog subject、规则版本和冲突/遗漏定位。
- generation lineage：recommendation Prompt Release、model identity、input/output hash 和 model call log。
- decision fields：影响链、风险、工作量、业务价值、置信度、反证、验证计划和建议失效条件。

缺少真实观测、低于统计门槛或 lineage 不完整时，只能生成 `insufficient_evidence` 或明确的继续采样计划。系统必须允许 `no_change`，不得为了填充 UI 强制产生修改动作。

### 8.2 人工批准和下游草稿

Recommendation 生命周期为 `draft -> in_review -> approved -> stale|expired`，同时允许 `draft|in_review -> rejected|expired`。`stale` 是显式持久状态，不是 UI 临时标签；批准时和每次下游动作前都重新校验所有输入。Fact retired、数据刷新、告警解决、统计方法替换或内容版本变化使已批准建议进入 `stale`；到达冻结有效期则进入 `expired`。`stale/expired` 不可恢复为 approved，只能基于新输入创建新 Recommendation 并重新审批。

人工批准后，系统根据建议类型只创建以下之一：

- Experiment Plan draft。
- QuestionSet draft。
- Content Brief draft。
- Sampling Plan draft。

创建草稿使用 idempotency key，并保存 `recommendation_id`、Recommendation version、approval ID 和全部 lineage。Recommendation 转为 `stale/expired` 时，在同一事务中将所有尚未执行的关联草稿标记 `blocked_source_stale|blocked_source_expired`，并取消其未投递 outbox/未开始 Job。任何关联草稿从 draft 进入排期、生成、执行或审核流转前，都必须锁定并重新校验源 Recommendation 仍为同一 approved version；否则返回 `409 recommendation_source_stale`。该动作不启动实验、不触发采样、不生成正式内容、不创建 Publication Request，也不发布。后续仍沿用各领域现有审核和执行动作，但不能绕过此执行前检查。

## 9. 六个月批次计划

月份是交付批次，不是可以绕过退出门槛的截止日。某条工作流未过门槛时可以继续修复，其他无直接依赖的工作流仍可推进；依赖该合同的功能不得以临时数据完成名义验收。

### 9.1 总表

| 月份 | 主题 | 退出门槛 |
|---|---|---|
| 第 1 月 | 共享基础、代理和浏览器采集骨架 | Prompt Program、多模型 Gateway、Secret Store、Connector Core、Egress/Browser Capture、风格采集及基准合同可运行 |
| 第 2 月 | 澳洲消费者 UI、首批真实数据和五平台测评 | 按授权轨道完成 Google AI Overviews/AI Mode、Bing Copilot 采集 Beta 与授权决策点、前五平台 Profile、GSC/GA4 真实同步和 Sampling Core 通过验收 |
| 第 3 月 | 消费者 UI 稳定化、九平台闭环和五类 Provider | 浏览器 adapter 保真度/漂移闭环、后四平台、修订循环、Corpus/三臂仿真、五类 Provider adapter 完成 |
| 第 4 月 | 判断、告警和归因入口 | 完整语义指标、统计比较、漂移、告警中心及归因事件入口完成 |
| 第 5 月 | 业务闭环和 Customer 投影 | 归因快照、Customer 已批准真实投影、建议和四类草稿闭环完成 |
| 第 6 月 | 生产等价验收 | 全链 live staging、兼容迁移、性能/故障/浏览器/备份恢复验收完成 |

### 9.2 第 1 月：共享基础

**交付**

- 冻结共享枚举（含 `automated_ui`）、artifact manifest、Prompt Program、Model Gateway、Secret Reference、Connector Core、Egress Endpoint、Browser Profile/Session、Style Collection 和 Sampling 合同。
- 在现有 Prompt Release 上实现八种 `program_kind`（`reference_translation` 仅保留枚举，移出首批）的创建、测试、diff、批准、冻结和绑定骨架。
- Model Gateway 完成 DeepSeek 兼容迁移及 OpenAI/Kimi/Gemini/Perplexity/Microsoft adapter contract tests；至少三个真实供应商完成最小结构化输出 smoke。
- Secret Store 完成加密、审计、轮换、redaction、Docker Secret preflight、历史 keyring/escrow、逐 key-version decrypt canary 和负向权限测试；备份 `0700/0600`、认证加密、密钥隔离和签名/checksum 门禁在首次真实数据接入前启用。
- Connector Definition/Connection/Scope/Checkpoint/Sync Run/Raw Artifact/Schema/Freshness/Error 骨架落地。
- 独立 `browser-capture-worker`、`egress.verify`/`browser.capture` Job、澳洲 HTTP CONNECT/HTTPS/SOCKS5 代理配置和 direct-egress deny 骨架落地。
- Google AI Overviews、Google AI Mode、Bing Copilot 的 Surface Definition/Release、页面工件 bundle、解析状态和授权 gate 合同冻结；用本地 fixture 完成 parser PoC。
- Style Source/Collection Run/Sample/Profile（含人工样本导入路径）和 Review Suite/Case 的 schema、API、Admin 基础界面落地。
- 九平台采集授权/可行性矩阵（按第 2.4 节记录 `authorization_state`、允许行为和人工/自动路径归属）、登录/公开模式、匿名规则和 360 Case 回归合同的 schema 冻结；Case 内容在对应平台 Profile Version 发布时逐平台冻结，第 1 月不要求内容完整。

**退出门槛**

1. 同一 Prompt 固定输入可以比较两个 Release，批准后内容/hash 不可变，Job 可冻结并复现绑定。
2. 真实模型返回错误 JSON、错误 enum、主体错配时应用侧拒绝，不因供应商宣称 structured output 而放行。
3. 数据库、Job、日志、MinIO、API/浏览器均检索不到测试 secret 明文；轮换后旧 reference 被拒绝。
4. Connector Core 能以 fixture 完成增量、限流、schema 变化、取消和 lease 丢失状态机。
5. 至少一个公开 Style Source 和一个正常登录 Style Source 可生成不可变匿名样本工件；验证码/封禁路径明确停止。
6. 用户提供的测试代理可以通过 Secret Reference 建立连接；浏览器内 observed IP、两个地域验证源和预期 AU 一致，任何直连泄漏使测试失败。
7. Google/Bing fixture 能区分 AI surface、普通结果、`surface_not_present`、CAPTCHA/登录墙和 parser drift，且阻断不会触发代理自动轮换。
8. 在空环境中恢复加密测试备份和独立历史 keyring，逐版本 canary、代表性 secret 解密及 connection test 通过；备份文件权限、明文扫描和错误密钥 fail-closed 测试通过后，才允许第 2 月接入真实凭据/数据。

### 9.3 第 2 月：五平台、GSC/GA4 和 Sampling Core

首批平台为 `owned_site`、`productreview`、`reddit`、`ozbargain` 和 `quora`；优先完成公开或低登录复杂度渠道，使 Profile/Review 合同先稳定。

**交付**

- 五个平台各完成不少于 200 条合格样本（自动或人工导入路径，按授权矩阵执行）、Profile Version、人工明审和冻结发布。
- `autonomous_scenario`、`guided_scenario`、每 Case 四候选和基础 claim/style judge 可运行。
- 固定版本 PyAirbyte 嵌入 Worker；GSC 和 GA4 完成真实只读授权、首次同步、增量同步、回刷和 freshness。
- Google/Bing 官方报告导入完成原文件、schema version、typed projection 和重复检测骨架。
- Sampling Suite/Run/Task、manual UI、`automated_ui` 和 raw answer/citation/page artifact 完成；分母按完整维度隔离。
- 对已取得授权依据（A 轨）的 surface，使用经验证的澳洲 residential/ISP 或 mobile 出口完成 Browser Capture Beta；保存冻结浏览器画像、地域证明、截图、DOM、HAR、答案和引用顺序。对尚无依据的 surface 完成 fixture 全链路 Beta 加 `manual_ui` 基线采样，为月末授权决策点准备证据。
- Admin 完成 Egress Endpoint 新建/测试/停用、Browser Profile、Surface Run 进度、阻断原因和原始页面证据查看。

**退出门槛**

1. 五个平台的样本数、去重、匿名、AU English 和人工审批均可由查询及 manifest 复核。
2. 真实 GSC/GA4 各完成首次 + 增量 sync；checkpoint 只在 raw/projection 同时成功后推进。
3. 回刷、限流、撤权和 schema fixture 不破坏既有 projection，也不伪造 freshness。
4. Sampling Task 可独立重试/取消；少于门槛或低于 80% 完成度只输出 `insufficient_evidence`。
5. manual UI、automated UI、provider fixture 和 synthetic 不可进入彼此分母。
6. 按第 2.4 节完成授权决策点：每个 surface 要么为 A 轨并有至少一个澳洲真实成功页面，要么有记录在案的 `assessed_no_basis` 结论、降级决定和 B 轨证据（fixture 全链路 + `manual_ui` 基线）；不允许无结论悬置。
7. 运营人员对同一 Page Artifact Bundle 的答案和引用逐项复核通过，阻断/普通 SERP 不会被记为 AI surface 成功或有效缺失。

### 9.4 第 3 月：九平台、修订、Corpus 和 Provider

后四个平台为 `amazon`、`youtube`、`tiktok` 和 `instagram`；登录与动态页面适配必须遵守第 5.2 节访问边界，无自动化授权依据或自动化不可行的渠道以人工导入路径完成样本门槛。

**交付**

- 后四个平台达到样本/Profile 发布门槛，形成九平台完整 Suite。
- conflict check、最多两轮 revision、一次 regenerate batch、warning 直出和 Fact 失效路径完成。
- Corpus Version 及无语料/当前批准/新候选三臂配对离线实验完成。
- OpenAI、Gemini Grounding、Perplexity、Microsoft Bing Grounding、Kimi 五类真实 Provider adapter 完成。
- 每类 adapter 保存实际 provider/surface/model、原始回答、引用、search mode、用量和错误分类。
- 每个 A 轨 Surface Release 分别完成第 7.2.5 节至少 20 个澳洲 live capture、阻断 fixture、匿名/managed account 独立 cohort 和重复采样调度；每个 B 轨 Surface Release 分别完成至少 30 个 fixture、至少 10 个 `manual_ui` 页面对照和重复采样调度；selector/parser drift 告警对两轨统一生效。其他获准消费者 surface 按价值增加独立 adapter release，但不得稀释首批 release 的独立门槛。

**退出门槛**

1. 九平台固定回归 Case 全量运行；发布门槛满足第 10.1 节。
2. 两轮修订后仍失败会且只会创建一个新生成 batch；任务取消和 lease 丢失不会提交陈旧结果。
3. `derived_or_unknown` 可直接形成 warning；明确 Fact conflict 或 subject mix 必须修订。
4. Warning 进入总体实验仍显示数量、占比和独立分层。
5. 三臂每题 10 次的冻结实验可重复计算；synthetic 结果无法通过 Customer API 获取。
6. 五类 Provider 使用真实凭据完成 live canary，且任何结果都没有消费者 UI 冒名标签。
7. Browser Capture 按所在轨道达到第 7.2.5 节分类、文本和引用门槛；Session 内换 IP、直接出口、CAPTCHA、限流和 DOM 漂移路径均 fail closed，跨 Session 的 residential/mobile IP 漂移不误判为失败。

### 9.5 第 4 月：指标、统计、漂移、告警和归因入口

**交付**

- 第 7.3 节完整语义指标、evidence locator、规则优先和 metric judge/arbiter 完成。
- Wilson/Newcombe、确定性配对 bootstrap、Holm 校正、`win/equivalent/loss/inconclusive/insufficient_evidence`、负收益和最差问题完成。
- provider/model/source/locale/region/query cluster 漂移及阈值/基线告警完成。
- Admin inbox、本地 SMTP、签名内网 Webhook 及确认/抑制/解决/处置记录完成。
- 本地 attribution event schema、Snowplow-compatible receiver（Session/Touch 主来源）、UTM/trace 生成、Session/Touch/Conversion 去重入口及 GA4 聚合对账口径完成。

**退出门槛**

1. 同一冻结输入和 method version 在不同进程重算得到相同 hash、区间和结论。
2. 多重比较 family、alpha、seed 和 practical threshold 可从报告还原。
3. `delta`、power、precision 和最小有效配对数在运行前冻结；区间跨越方向/等效边界时只能输出 `inconclusive`，不得显示为“平”或方向性结论。
4. 平均提升存在但至少一个问题显著退化时，负收益和最差问题仍可见并触发对应规则。
5. 构造 reported model 或来源构成漂移时，与业务指标变化分开展示。
6. 告警重复评估不重复建单；通知失败可重试，状态/处置历史不丢失。
7. 重复事件幂等；无 PII trace、禁概率跨设备和零点击隔离均有负向测试。

### 9.6 第 5 月：归因快照、Customer 投影和建议闭环

**交付**

- Lead/Stage/Deal/Revenue 的 Admin 录入与幂等文件导入（冻结模板 schema、文件 hash、去重键）、Attribution Policy Version 和快照完成。
- 30 天 last-click、90 天 assisted、direct/first/last/assisted 和零点击独立结果完成。
- Customer API/Portal 只读展示已批准、满足门槛的真实观测、统计和归因摘要。
- Recommendation evidence graph、六种建议类型、stale/expired 和人工批准完成。
- Experiment Plan、QuestionSet、Content Brief、Sampling Plan 四类下游草稿创建完成。

**退出门槛**

1. 从 Revenue 可回溯到 Deal/Conversion/Session/Touch、verified URL、UTM/trace、Campaign、QuestionSet 和内容/Package Version。
2. 30/90 天窗口边界、direct、first、last、assisted、跨设备拒绝和零点击均有确定性 fixture。
3. Customer 无法读取 synthetic、未批准/不足证据结果、内部建议、原始回答或 connector/model secret。
4. Recommendation 的每项事实和指标均有有效 lineage；Fact/数据/版本失效后，已批准建议持久化转为 `stale/expired`，关联草稿同步进入 blocked 状态。
5. 批准建议只创建一个幂等草稿，不自动排队、生成、执行或发布；草稿任何后续流转都重新校验源 Recommendation version，stale/expired 时以 `409 recommendation_source_stale` 阻断。

### 9.7 第 6 月：live staging 和发布准备

**交付**

- 以真实 GSC、GA4、一方事件入口、五类 Provider、至少三家生成/评审模型、一个登录采集账号，以及一个经验证的澳洲 residential/ISP 或 mobile 代理出口执行全链 live staging；A 轨 surface 走真实自动采样，B 轨 surface 走 fixture + `manual_ui` 链路。
- 完成至少一条经业务授权且参与者同意的一方真实归因旅程：真实 landing click 携带冻结 UTM/trace，形成真实 Session/Touch/Conversion、Lead、Deal 和 booked Revenue，并回溯到 Campaign、QuestionSet、verified URL 与内容/Package Version。fixture、GA4 聚合行、人工补造事件或彼此无强 lineage 的真实记录均不能替代。
- 完成旧 Prompt/Protocol/Observation/Metric 数据兼容迁移、unknown/ineligible 保持、回滚/forward-fix 演练。
- 完成容量、并发、配额、慢供应商、取消、lease、outbox、MinIO/DB/Valkey 故障和恢复测试。
- Admin/Customer Chromium 全链测试及关键桌面 viewport 视觉/交互验收。
- PostgreSQL + MinIO 认证加密一致备份、checksum/签名、独立历史 keyring 空环境恢复、逐 key-version canary/代表性 secret 解密、业务行/关系/工件 hash 和 Customer 投影复核。
- 固化 runbook、告警处置、secret/provider 轮换、connector 撤权、schema change 和恢复证据模板。

**退出门槛**

1. 第 10 节全部验收项有 live run ID、版本/hash、工件、测试结果和人工签字；mock 结果不能替代 live 证据。
2. 外部 API 或 Browser Capture 的超时、限流、撤权、阻断、地域变化、DOM drift、部分完成和 schema 变化不产生假成功、串分母或数据覆盖。
3. 旧数据迁移后保持原有 Customer 可见性和历史 hash；未知来源不升级为真实。
4. 第 10.7 节冻结负载下满足 API、队列、Job、工件和错误率门槛；不得用更小负载替代后宣称通过。
5. 从备份恢复后的关键业务计数、复合关系、MinIO manifest/hash、批准 Customer 投影、全部在用 key-version canary 和代表性 Connector/Provider/Egress secret 解密均一致可用。
6. 真实归因旅程从 Revenue 到 UTM/trace 与 GEO 内容版本逐跳可复核，且无 PII 导出、概率拼接或 GA4 聚合记录冒充事件。
7. 每个自动采集 surface/渠道的授权结论、轨道归属和对应轨道证据在六个月 evidence manifest 中完整可查。

## 10. 验收与质量门禁

### 10.1 合成实验室固定验收集

- 九个平台各至少 40 个固定回归 Case，共至少 360 个。
- 每个平台 `autonomous_scenario` 和 `guided_scenario` 各占一半。
- 每个平台竞品场景不少于 30%，避免总体比例掩盖单平台空缺。
- Case 冻结 Persona、UseCase、Question、Fact/Profile version、主体、预期风险和人工 rubric。

Prompt/Profile Release 同时满足以下条件才能发布：

| 门槛 | 要求 |
|---|---:|
| `passed` | `>= 95%` |
| 商品/竞品主体串用 | `0` |
| source reproduction/防复刻违规 | `0` |
| 平台风格均值 | `>= 4.2/5` |
| 人工明审 | 至少 1 名运营人员完成并签字 |

自动门槛之外，必须覆盖两轮修订、一次重新生成、Warning 直接输出、任务取消、租约丢失和 Fact 失效。人工明审保存 reviewer、rubric version、时间和结论，不只保存自由文本备注。

### 10.2 真实外部验收

完成证据必须包括：

- 一个真实 GSC property 和一个真实 GA4 property 的首次/增量/回刷结果。
- Google/Bing 官方报告的真实文件导入（若账号在验收期无数据，仍需真实导出文件和可解释空结果，不能用 mock 宣称数据投影完成）。
- OpenAI、Gemini Grounding、Perplexity、Microsoft Bing Grounding、Kimi 五类 Provider live run。
- 消费者 surface 按第 2.4 节轨道及第 7.2.5 节逐 Surface Release 验收。A 轨每个 release 独立满足 20 个 live capture 的构成和阻断 fixture；B 轨每个 release 独立满足 30 个 fixture 与 10 个 `manual_ui` 页面对照。分类/文本/引用比例不得跨 release 汇总。阶段完成不要求任何特定 surface 处于 A 轨，但每个 release 必须有自身轨道证据。
- 至少三家不同供应商模型参与 generation/judge/arbiter 角色，验证跨模型合同而非单模型自评。
- 至少一个正常登录的风格采集账号；不得用绕过验证码或访问控制获得的结果验收。

mock/fixture 用于 PR 和故障覆盖，但不能替代上述 live 完成证据。真实验收记录 secret reference ID，不记录 secret 内容。

### 10.3 连接器、代理和 Secret 验收

- PyAirbyte 增量游标、相同 checkpoint 重试、历史回刷、限流/`Retry-After`、schema 兼容/破坏变化、撤权和恢复。
- Secret 创建、测试、轮换、并发中的 reference version、撤销、主密钥错误、日志/工件/Job 泄漏扫描。
- 历史 keyring/escrow 与数据备份分离；空环境按全部在用 master key version 执行 decrypt canary、代表性 Connector/Provider/Egress secret 解密和不泄密 connection test，缺任一历史 key 或使用错误 key 时 fail closed。
- Raw Artifact 与 projection 的 record count/hash/lineage 一致；未知 schema 只阻断 projection，不丢原始证据。
- 失败/取消/lease 丢失不推进 checkpoint，不提交 freshness 假象。
- Egress Endpoint 覆盖 HTTP CONNECT/HTTPS/SOCKS5、认证失败、超时、sticky lease 创建/到期、Attempt 前后出口变化（fail closed）与跨 Session 漂移（新 lease 验证后继续）、两个地域源不一致（`geo_unverified`）、AU datacenter 与 residential/mobile 分类和显式停用。
- 在同一 BrowserContext/sticky lease 内完成每个 Attempt 的前后 observed IP/region 验证，或保存可信代理侧目标 hostname/出口连接日志；证明页面请求、WebSocket 和 DNS 未绕过代理。无 sticky 能力且无可信连接日志、前后不一致或 browser-capture-worker direct egress 均必须使结果 ineligible。
- 代理或 Browser Account secret 不进入 screenshot、DOM、HAR、console、exception、Job、日志或 Customer 投影。
- CAPTCHA、登录墙、consent 未完成、限流、封禁、geo mismatch 和 parser drift 均停止/隔离对应任务，不自动轮换代理继续采集。

### 10.4 采样和统计验收

- API 每题默认 10 次、automated UI 默认 5 次且至少 3 次、manual UI 每题至少 3 次，完成度和有效性使用冻结预期分母。
- 低于样本门槛或 80% 有效完成度只产生 `insufficient_evidence`。
- Suite 冻结的吞吐预算与实际耗时一致可查；超出授权频率或日配额的执行路径有负向测试。
- capture method、engine/model、locale/region、language/search mode 任一不同均不得静默混分母。
- automated UI 的 Egress Verification、Browser Profile、account/personalization cohort 或 Surface Release 不同，不得静默合并；需要汇总时必须展示构成。
- Browser Capture 满足 surface 分类准确率 `>=95%`、普通结果误标为 AI 回答为 0、可见答案完整率 `>=99%`、引用 URL/顺序一致率 `100%`。
- Warning 合并后仍显示比例和独立 passed/warning 结果。
- Wilson/Newcombe、paired bootstrap、Holm、`win/equivalent/loss/inconclusive/insufficient_evidence`、负收益、最差问题和漂移使用 golden fixture 与重复计算测试；至少覆盖区间跨 `-delta/+delta`、区间完全落入等效区、方向性胜负、完成度不足和 observed variance 导致 precision 未达标。
- 修改 Protocol、阈值、统计方法、Prompt 或 metric judge 后产生新版本，历史结果不变。

### 10.5 归因和建议验收

- 验证 30/90 天窗口边界、direct/first/last/assisted、重复事件、迟到事件和 snapshot cutoff。
- 验证跨设备拼接被拒绝，零点击 exposure 不进入 Conversion/Revenue 分母。
- Revenue 到 GEO 内容版本的 lineage 可复核；缺任一强关联时明确 unassigned，不做概率填补。
- 至少一条经业务授权和参与者同意的真实 live 旅程覆盖 UTM/trace -> landing -> Session/Touch -> Conversion -> Lead -> Deal -> booked Revenue -> Campaign/QuestionSet/verified URL/Package Version；fixture、GA4 聚合或人工补造链不得计为完成证据。
- 六种 Recommendation 均有 fixture；`no_change` 和 `insufficient_evidence` 是正常终态。
- 建议输入 stale、Fact retired、统计版本替换、批准并发和重复草稿创建均有行为测试；`approved -> stale|expired` 必须同步阻断已创建草稿，草稿排期/生成/执行前的 version recheck 不得被 API、Worker 或直接 repository 调用绕过。

### 10.6 全仓门禁

每个批次执行与风险相称的门禁；第 6 月至少覆盖：

- 质量/静态检查和全部单元测试。
- PostgreSQL、MinIO、Valkey、Durable Worker/Relay 集成测试。
- 隔离 Browser Capture Worker、代理出口强制、Chromium/adapter drift 和页面工件一致性集成测试。
- Alembic 从当前 head 前向迁移、在线写入追尾/切换对账、兼容数据迁移和单一 head 检查。
- OpenAPI 生成、稳定快照和 Admin/Customer client contract。
- Admin Web 与 Customer Web 生产构建。
- Chromium 关键工作流、权限负测和 Customer 数据泄漏测试。
- 生产网络、readiness、heartbeat、队列卡滞、secret preflight 和外部 egress 测试。
- PostgreSQL/MinIO 认证加密备份、`0700/0600` 权限、备份密钥隔离、历史 Secret keyring 空环境恢复、逐版本解密 canary 和业务一致性校验。
- 登录/受限 raw artifact 的落盘前 secret/PII 检测、独立加密、RBAC/RLS、30/90 天 TTL、双人 hold 和 Customer/导出负向测试。

### 10.7 性能验收冻结负载

第 1 月结束前将下列 `performance-profile-v1` 写入版本化 manifest。第 6 月必须在生产等价 PostgreSQL/MinIO/Valkey 和固定 Worker 拓扑上执行；外部供应商调用用记录回放/受控 adapter 承载负载，live canary 另按授权配额运行，避免以性能测试突破平台限制。

| 维度 | 冻结负载/门槛 |
|---|---|
| Project | 10 个已建项目，其中 4 个并发活跃、每个具有独立 Campaign/QuestionSet/权限数据 |
| Sampling | 4 个并发 Run；每个 1,000 个 planned Task，共 4,000 个 Task；admission controller 按冻结配额设置 `not_before`，任一时点至少 400 个同时 eligible，capture method 和 Project 均隔离 |
| Connector | 2 个并发 Sync Run；每个 250,000 raw records，包含首次同步、增量 checkpoint 和 projection |
| Page Artifact Bundle | 平均 10 MiB、p95 25 MiB、硬上限 50 MiB；负载集中至少写入 20 GiB MinIO 工件并校验 manifest/hash |
| 进程拓扑 | 4 个通用 Task Worker、2 个 Browser Capture Worker、1 个 Outbox Relay；CPU/内存/DB pool/MinIO 配额记录进 manifest |
| API 负载 | 30 分钟持续 20 read RPS + 5 write RPS；read p95 `<=500 ms`、write p95 `<=800 ms`、总体 p99 `<=2 s`、非预期 5xx `<1%` |
| 队列/Outbox | eligible Job dispatch p95 `<=60 s`、最大队列年龄 `<=5 min`；Outbox publish p95 `<=5 s`；测试结束 10 分钟内无非配额/`not_before` 原因的积压 |
| 计算/同步 | 1,000 Observation 的 metric recompute p95 `<=30 s`；250,000 行 connector projection 单 Run `<=15 min` |
| 正确性 | 0 跨 Project/Campaign 读取、0 重复终态、0 丢失/重复 checkpoint、0 hash 不一致；lease 丢失和 Worker 重启后结果一致 |

任何缩小 Project、Task、record、artifact 或请求率的运行只能作为诊断，不能通过本门禁。evidence manifest 必须保存负载生成器/recording 版本、拓扑、开始/结束时间、所有目标值和实测 p50/p95/p99/max、错误/队列年龄、资源水位及原始报告 URI/hash；门槛变更创建 `performance-profile-v2` 和批准记录，不能在失败后原地放宽 v1。

## 11. 发布、兼容和证据

### 11.1 迁移策略

- 采用 `expand -> compatible writer -> initial backfill -> write catch-up -> dual-read comparison -> cutover reconciliation -> switch -> rollback window -> contract`；不可在同一部署先删旧列再迁移，也不得把 dual-read 当作写入同步机制。
- 每个迁移在编码前枚举全部写入方（新旧 API、Worker、Relay、脚本和数据库触发器），并选择以下一种可验证模式：
  - **在线双写**：先部署能够同时写旧/新结构的兼容 writer；同一 PostgreSQL 内优先同事务双写，异步 projection 使用 transactional outbox、幂等 consumer 和可观测 lag。所有旧版本仍可能产生的写入都被双写/捕获后才能开始 initial backfill；新侧写入失败不得静默提交旧侧成功。
  - **受控停写切换**：无法安全双写时，声明受影响资源和最大停写窗口，取得 cutover lock 并阻断全部旧写入；用单调 change sequence/outbox ID（不得只用 wall-clock `updated_at`）执行最终增量 backfill，然后才允许切换读写。
- initial backfill 记录起始/结束 watermark；切换前按 Project/Campaign 对 rows、business keys、lineage FKs、artifact refs 和 hash 做最终增量追尾与两轮零差异对账。发现新写入或 lag 非零时 cutover fail closed，继续追尾或回滚，不得切换。
- switch 后至少保留一个批准的 rollback window：在线模式继续双写并监控差异；停写模式保留可逆 schema/旧读路径。所有旧 writer 已下线、rollback window 结束且最终差异为 0 后，才能 contract 删除旧列/表/代码。
- 历史 Prompt、Observation、Metric 和 synthetic 记录保留原始版本/来源；无法证明的字段回填 `unknown`、NULL 或 ineligible，不猜测。
- 新功能按 Project feature flag 开启，先内部 dogfood，再单 Project staging canary，最后扩大范围。
- Provider/Connector adapter 升级创建新 release；旧 Run 始终能解析其冻结 manifest。
- Customer 投影在新统计和批准合同稳定前保持旧读路径；切换时用同一 Campaign/Protocol fixture 做逐字段对账。

### 11.2 月度证据包

每月退出评审保存一个不可变 evidence manifest，至少包含：

- Git commit、migration head、OpenAPI manifest 和 Web build IDs。
- Prompt/Profile/adapter/schema/method release IDs 与 hashes。
- 测试命令、收集数、通过/失败/skip 数和关键报告 URI/hash。
- live run IDs、脱敏账号/connection IDs、原始工件 manifest 和人工审核记录。
- 迁移 writer 清单、双写/outbox lag 或停写窗口、initial/final watermark、逐 Project/Campaign 对账和 rollback-window 证据。
- 备份权限/加密报告、数据备份与历史 keyring 的独立恢复记录、逐 key-version canary、代表性 secret connection test 和明文扫描结果。
- `performance-profile` 版本、冻结负载/拓扑、实测延迟/队列年龄/资源水位及原始报告 URI/hash。
- 真实归因旅程的 consent/业务授权引用和脱敏逐跳 lineage；不保存参与者 PII 或支付凭据。
- 未完成项、已知偏差、成本/耗时、告警和下一月依赖。

只有 evidence manifest 完整且退出门槛逐项签字，月度状态才能从 `IN_PROGRESS` 变为 `ACCEPTED`。功能“页面可见”或 mock 测试通过不构成批次完成。

## 12. 主要风险和控制

| 风险 | 早期信号 | 控制/退出条件 |
|---|---|---|
| 四工作流争用共享 schema | 多 Alembic head、枚举反复冲突 | 单迁移 owner；共享合同先行；月度 contract freeze |
| Provider API 被误解为消费者 UI | API 结果使用 ChatGPT/AIO/Copilot UI 名称 | `provider_api`/`automated_ui` 强类型分离；页面证据和 UI/导出负测 |
| 消费者 UI 自动采样缺少平台允许依据 | 无 authorization record、条款过期或用途超范围 | surface fail closed；第 2 月授权决策点强制出结论并降级 B 轨；B 轨证据是一等完成路径；代理不能替代授权 |
| 澳洲代理不具备消费者代表性 | 出口为数据中心、地域源冲突或页面显示非 AU | 每 Attempt 同一 sticky lease 前后双源验证或可信连接日志；network type 分级；只有 residential/mobile 可标记代表性 |
| 浏览器采集违反访问边界 | CAPTCHA、封禁、限流或异常重试上升 | 立即停止 Endpoint/Surface Run；不绕过、不自动换代理；保留阻断证据 |
| DOM/实验分流导致误判 | 答案为空、普通 snippet 被识别为 AIO、引用丢失 | screenshot/DOM/HAR 三证据、parser health、人工保真集和 adapter drift 告警 |
| 模型 judge 偏差或自评 | 不同模型分数分歧大、无 evidence locator | 规则优先、三供应商交叉验收、arbiter 和人工固定集 |
| API 成本/配额不足 | completion < 80%、持续 quota 告警 | 预冻结预算/并发；缩小 Suite 范围并新建 Protocol，不降低门槛 |
| Connector schema/API 漂移 | projection 失败但 Job 表面成功 | raw-first、schema fingerprint、fail-closed projection 和 freshness |
| 在线迁移遗漏增量写入 | backfill 后新旧计数/hash 持续分叉 | 全 writer 清单；事务双写/outbox 或停写锁 + 单调 watermark 最终追尾；零差异才切换 |
| Attribution 被当作因果 | 报告出现“导致收入”措辞 | 页面/导出固定非因果声明；并列 direct/first/last/assisted/zero-click |
| GA4 聚合数据被误用为会话级归因 | Session/Touch 记录源头指向 GA4 报表 | 一方事件入口为唯一 Session/Touch 真源；GA4 只做聚合对账；无 consent/未上线站点只显示 exposure/官方口径 |
| Secret 泄漏 | SDK exception/request dump 含 token | 集中 redaction、泄漏扫描、最小权限、轮换和撤销演练 |
| Warning 掩盖质量问题 | 总分上涨但 warning 占比增加 | 强制占比、独立分层、发布门槛和人工明审 |
| 备份仍是假阳性 | 只校验命令退出码或数据 hash，Secret 无法解密 | `0700/0600`、认证加密/密钥隔离、空环境数据 + 历史 keyring 恢复、逐版本 canary、代表性 secret 和业务关系/hash 全部通过 |

若真实账号、预算或其他用户侧资源未在对应月份就绪，应把相关里程碑标记为 `BLOCKED_EXTERNAL` 或 `IN_PROGRESS`，不得以 mock、人工描述、降低样本量或合并分母改写为完成。平台授权不适用无限期 `BLOCKED_EXTERNAL`：按第 2.4 节授权决策点在第 2 月强制出结论并落入对应轨道。

## 13. 六个月后的技术展望

下一阶段进入“成熟传统 SEO + GEO 统一平台”，按以下顺序扩展：

1. 多域名站点库存、抓取、渲染 DOM 和索引资格。
2. robots、canonical、Sitemap、结构化数据、WAF 和 AI bot 用途策略。
3. 关键词、排名、搜索意图、内容缺口、页面质量和竞品覆盖。
4. 内链、外链、站外权威、Feed、IndexNow 和抓取时效。
5. CMS 草稿/发布连接器、Agent 任务完成率和全面治理。
6. 统一实验与归因控制面，同时保持 Organic Search 与 Generative Engine 的独立指标、来源及分母。

本六个月的数据模型预留中性的 `Query`、`Surface`、`Content Asset`、`URL`、`Experiment` 和 `Recommendation` 分类。GEO 专属字段通过 typed extension/projection 表达，不把 `query=prompt`、`surface=AI provider` 或 `content asset=Package` 写死在共享身份中。这样未来加入完整传统 SEO 能力时可以复用项目、Campaign、版本、实验、归因和建议链路，而无需重写核心主键或历史 lineage。

## 14. 外部实现参考

以下参考只说明 adapter 能力和集成方向；本路线图的领域、权限、来源、分母和验收合同以本仓库文档为准：

- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Kimi Chat API](https://platform.kimi.ai/docs/api/chat)
- [PyAirbyte](https://airbyte.com/product/pyairbyte)
- [Airbyte Google Search Console Connector](https://docs.airbyte.com/integrations/sources/google-search-console)
- [Airbyte Google Analytics 4 Connector](https://docs.airbyte.com/integrations/sources/google-analytics-data-api)
- [Snowplow Trackers/Sources](https://docs.snowplow.io/docs/sources/)
- [Playwright BrowserContext proxy and emulation](https://playwright.dev/docs/api/class-browser#browser-new-context)
- [Google 如何确定搜索位置](https://support.google.com/websearch/answer/179386)
- [Google 不同国家/地区搜索设置](https://support.google.com/websearch/answer/873)
- [Google AI Mode 可用国家/地区（包含 Australia）](https://support.google.com/websearch/answer/16011537)
- [Google machine-generated traffic 政策](https://developers.google.com/search/docs/essentials/spam-policies#machine-generated-traffic)
- [Bing 如何使用位置](https://support.microsoft.com/en-us/bing/how-bing-uses-your-location)
- [Microsoft Services Agreement - Bing and MSN](https://www.microsoft.com/en-us/servicesagreement)
- [Grounding with Bing Search 使用与展示要求](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/bing-grounding)
