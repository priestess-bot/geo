# GEO 后续六个月实施路线图

> 计划日期：2026-07-21
> 修订日期：2026-07-22（第 5 次修订）
> 计划状态：`PLANNED`
> 计划周期：启动后连续六个月，以月度退出门槛而非自然月末作为批次完成标准
> 决策来源：[README 下一阶段发展目标](../../README.md#下一阶段发展目标)、[GEO 效果优先整改决策记录](../audits/GEO-effect-first-remediation-decisions-2026-07-18.md#6-c-组效果测量判断和优化)
> 当前能力来源：[F-019 RAG 核心集成合同](F019-core-integration-contract-2026-07-19.md)、[F-019 QuestionSet/Protocol/Simulation 合同](F019-question-set-protocol-simulation-contract-2026-07-19.md)
> 专项实施计划：[外部数据与跨引擎采样实施计划](GEO-external-data-cross-engine-sampling-implementation-plan-2026-07-22.md)
> 范围变更：按 2026-07-22 用户决定，将 Google AI Overviews/AI Mode、Bing Copilot 及其他获准消费者 AI 界面自动采样纳入本阶段重点；本路线图中的新边界取代本文件初版的排除项，既有审计决策保留为历史依据
> 第 2 次修订变更：引入授权双轨完成定义和第 2 月授权决策点（第 2.4 节）；一方事件入口升级为归因主来源，GA4 降级为聚合对账（第 6.3 节）；风格采集渠道纳入与消费者 surface 对称的授权门槛并增加人工样本导入路径（第 5.2 节）；出口验证改为 Session 级语义并新增吞吐预算合同（第 7.1/7.2.2 节）；`reference_translation` 移出首批交付；供应商存储/保留条款纳入 adapter release 合同（第 4.2 节）
> 第 3 次修订变更：闭合在线迁移追尾、Secret/备份恢复、真实归因、统计不确定结论、逐 Surface Release 保真度、粘性代理证明、登录工件治理、人力容量、建议失效传播和性能负载门禁
> 第 4 次修订变更：增加执行基线、阶段状态、DoR/DoD、RACI、稳定验收 ID 和逐月 checklist；将“外部数据与跨引擎采样”的工作分解、适配器发布与逐源验收移入独立专项文件，主路线图只保留全局合同、阶段依赖和统一发布 Gate
> 第 5 次修订变更：按工作包类型限定 DoR/DoD 并增加可审计 `not_applicable`；将实际出口验证从 Task/分母身份移到 Attempt/Observation lineage；冻结授权先于 live enqueue；增加外部投影独立数据批准生命周期；补齐单项 evidence manifest 溯源字段

## 1. 执行结论

未来六个月交付五个可以使用真实账号、真实数据和不可变证据验收的业务板块：

| 板块 | 六个月完成定义 |
|---|---|
| 内部合成测评实验室 | 九个标准渠道均具备澳洲英文风格样本、版本化 Style Profile、知识冲突检查、修订闭环和三臂离线 GEO 实验；全部结果保持 `test_only=true`、`publication_eligible=false` |
| 外部数据与跨引擎采样 | Connector Core、GSC、GA4、Google/Bing 官方报告、五类外部 API adapter（Microsoft Grounding 使用 `proxy_grounded_api`，其余按实际能力使用 `provider_api`），以及通过已验证澳洲出口采集 Google AI Overviews/AI Mode、Bing Copilot 等真实消费者界面的 Browser Capture Connector 在 live staging 运行；未取得授权依据的 surface 按第 2.4 节 B 轨（fixture + 人工采样）完成并记录降级决定，不阻塞阶段验收；来源类型、原始工件和分母不可混淆 |
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

### 1.1 文档职责和执行方式

本文件是六个月计划的总控基线，负责范围、跨工作流依赖、共享合同、月度退出门槛和最终发布决定。“外部数据与跨引擎采样”专项文件负责 Connector Core、GSC/GA4、官方报告、五类外部 API、消费者 AI 界面、澳洲代理和 Sampling Core 的详细工作包与逐源验收。两份文件发生歧义时按以下顺序处理：

1. 安全、权限、真实性、分母和 Customer 可见性采用两份文件中更严格的条款。
2. 外部板块的任务状态和证据以专项文件的 `EXT-*` ID 为准；本文件不复制其完成状态。
3. 月度批次只有在本文件对应 `GATE-M*` 与专项文件对应 `EXT-GATE-M*` 同时通过时，才可整体 `ACCEPTED`。
4. 任何范围、门槛或样本量变更必须先形成批准的基线变更记录，并同时更新受影响的主计划和专项计划；实现 PR 不能隐式改变计划。

Checklist 统一使用以下语义：

- `[ ]`：尚未由证据证明完成，包括“代码已写但未验收”的状态。
- `[x]`：owner 和 verifier 已在 evidence manifest 中签字，且所有必需证据 URI/hash 可读取并通过校验。
- 阻塞、豁免和部分完成不使用非标准 Markdown 符号冒充完成，而是在月度状态表记录 `BLOCKED_EXTERNAL`、`IN_PROGRESS` 或批准的 change record。
- 每个清单项的稳定 ID 不因代码文件或测试名称变化而改变；测试节点、迁移号、PR 和 run ID 作为该 ID 的证据映射。

### 1.2 阶段状态和验收判定

| 状态 | 含义 | 是否允许依赖方据此验收 |
|---|---|---:|
| `NOT_STARTED` | 未满足进入条件或尚未排期 | 否 |
| `IN_PROGRESS` | 已启动，但至少一个必需清单项未完成 | 否 |
| `BLOCKED_EXTERNAL` | 真实账号、授权、预算或外部服务阻塞；已保存阻塞证据 | 否；授权双轨按第 2.4 节形成 B 轨结论后可解除 |
| `READY_FOR_REVIEW` | owner 声明完成，证据包待独立 verifier 复核 | 否 |
| `ACCEPTED` | 全部必需项、退出门槛、证据和签字通过 | 是 |
| `REJECTED` | verifier 发现门槛失败或证据不可复核 | 否，修复后重新提交 |

单项完成至少记录：`check_id`、`work_package_type`、capability flags、逐条 DoR/DoD applicability、owner、verifier、Git commit、migration/OpenAPI/adapter release（适用时）、test/live run ID、artifact URI + SHA-256、Project/Campaign/environment/脱敏 account/connection scope、开始/结束时间、结果和偏差。没有可读取的证据，或者证据来自错误 Project/Campaign、错误环境、错误版本或 mock 替代 live，均保持未勾选。

### 1.3 Definition of Ready 和 Definition of Done

每个 checklist ID 先且只能选择一个主要 `work_package_type`：

| 类型 | 适用对象 | 典型 ID |
|---|---|---|
| `governance_control` | 人力、预算、资源、授权决定、计划与政策冻结 | `M0-GOV-*`、`M0-BUD-*`、`M0-RES-*`、`M0-AUTH-*` |
| `contract_migration` | 领域/API/schema、迁移、兼容 writer 和数据合同 | `M1-BASE-*`、`EXT-M1-01..05` |
| `runtime_feature` | 内部运行功能、UI、Worker、统计、归因、告警和安全控制 | `M*-SYN/STAT/ATTR/REC/SECRET/WEB/OPS-*` |
| `external_integration` | Connector、Provider、Browser、代理、真实账号和 live 数据路径 | `M*-EXT-*`、`EXT-M2/M3/M4-*` |
| `verification_release` | Gate、AC、证据汇总、性能/恢复验收和最终发布决定 | `*-AC-*`、`*-FINAL-*`、`M*-EVD-*` |

现有稳定 ID 按以下优先级确定主要类型，首次匹配即停止；若任务实际内容需要覆盖默认类型，必须在开工前记录 change record 和独立批准：

1. `DOR-*`/`DOD-*` 是模板条款，不是工作包，不递归实例化自身。
2. `*-AC-*`、`*-FINAL-*`、`REPO-GATE-*`、`PERF-AC-*`、`*-EVD-*`、`*-QA-*` 为 `verification_release`。
3. `*-GOV-*`、`*-RES-*`、`*-AUTH-*`、`*-BUD-*`、`*-PLAN-*`、`EXT-M0-*`、`M0-SEC-*`、`M0-ARCH-*`、`M1-PERF-*` 为 `governance_control`。
4. `*-MIG-*`、`*-BASE-*`、`EXT-M1-01..05` 为 `contract_migration`。
5. 其余 `*-EXT-*` 与 `EXT-*` 实施 ID 为 `external_integration`。
6. 其余实施 ID 为 `runtime_feature`。

同时冻结布尔 capability flags：`changes_database`、`changes_api`、`has_customer_surface`、`handles_sensitive_data`、`has_runtime_operation`、`calls_external_service`、`requires_live_evidence`。类型决定默认适用性，flags 决定条件项是否转为必需；不能通过选择类型规避实际工作内容。

工作包进入实现前，对 applicability=`required` 的条款满足 Definition of Ready（DoR）：

- [ ] `DOR-01` 业务 owner、engineering owner、independent verifier 和升级路径已具名。
- [ ] `DOR-02` 该工作包实际拥有的输入/输出 schema、状态机、权限、幂等键、失败分类和 Customer 边界已冻结。
- [ ] `DOR-03` 该工作包的上游依赖已有版本/hash；调用外部服务时已有授权轨道、secret reference、预算和配额。
- [ ] `DOR-04` `changes_database=true` 时 Alembic owner 已给出线性迁移和 expand/contract 方案；`changes_api=true` 时已有 OpenAPI 兼容方案。
- [ ] `DOR-05` 该工作包适用的自动化、live、人工明审、故障、签字决策和回滚证据已写入验收映射；不要求无关证据类型。
- [ ] `DOR-06` `handles_sensitive_data=true` 或改变数据落盘/保留时，分类、保留、删除、备份和恢复要求已完成 threat/data review。

工作包只有 applicability=`required` 的 DoD 全部通过，且所有 `not_applicable` 决定有效，才可勾选：

- [ ] `DOD-01` 该工作包实际涉及的 Domain/Application/Repository/API/Worker/Admin 层使用同一冻结合同，没有平行状态机或旁路写入。
- [ ] `DOD-02` 该工作包适用的正向、权限、幂等、重试、取消、lease/fencing、跨 Project、错误分类和泄漏负测通过。
- [ ] `DOD-03` `changes_database=true` 时，前向迁移、兼容 writer、回填/追尾/对账和 rollback/forward-fix 证据通过。
- [ ] `DOD-04` `changes_api=true`、`has_customer_surface=true` 或改变导出时，OpenAPI、Web client、Admin/Customer 投影和导出边界通过；Customer 只见批准的真实结果。
- [ ] `DOD-05` `has_runtime_operation=true` 时，适用的指标、日志、readiness、heartbeat、告警、runbook 和人工操作路径可用。
- [ ] `DOD-06` `requires_live_evidence=true` 时，真实账号/live canary 与适用人工复核完成；fixture 只承担确定性回归和故障覆盖。
- [ ] `DOD-07` evidence manifest 完整、hash 可重算、owner/verifier 已签字，且没有未批准的 P1/P2 偏差。

适用性矩阵中的 `R` 为默认 required，`C` 由 capability flags 和实际范围在开工前解析，`N` 为默认 not applicable：

| 条款 | governance | contract/migration | runtime feature | external integration | verification/release |
|---|---:|---:|---:|---:|---:|
| `DOR-01` | R | R | R | R | R |
| `DOR-02` | C | R | R | R | C |
| `DOR-03` | C | C | R | R | R |
| `DOR-04` | N | C | C | C | N |
| `DOR-05` | R | R | R | R | R |
| `DOR-06` | C | C | C | R | C |
| `DOD-01` | N | R | R | R | N |
| `DOD-02` | C | R | R | R | R |
| `DOD-03` | N | C | C | C | N |
| `DOD-04` | N | C | C | C | C |
| `DOD-05` | C | C | R | R | C |
| `DOD-06` | N | N | C | C | C |
| `DOD-07` | R | R | R | R | R |

每个 `C` 必须在实现开始前解析为 `required` 或 `not_applicable`。每条 `not_applicable` 都保存 `clause_id`、具体理由、类型/flag 依据、decided_by、independent verifier、decided_at 和 evidence reference；owner 不能自批，不能使用“无关”作为唯一理由。范围或 capability flag 变化会使原 applicability 失效并重新评审。Gate/AC 类型只验证其引用工作包的证据，不递归要求 Gate 自身实现迁移、OpenAPI、lease 或 live 调用。只有全部 required 条款通过且所有 N/A 记录有效，check ID 才能完成。

DoR/DoD 是每个工作包重复使用的模板，不在计划阶段预先勾选。实施时在月度 evidence manifest 中为每个 ID 建立类型、flags、适用性和证据实例。

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
| GSC Connector projection | connector typed projection | 是，使用独立搜索效果口径 | 绑定 immutable snapshot 的 External Data Report 已批准且未 stale/revoked | 不进入回答型 Observation 分母 |
| GA4 Connector projection | connector typed projection | 是，使用独立聚合对账口径 | 绑定 immutable snapshot 的 External Data Report 已批准且未 stale/revoked | 不作为 Session/Touch 真源 |
| Google/Bing 官方聚合报告 | `official_report_import` | 是，使用独立 typed projection | 绑定 immutable snapshot 的 External Data Report 已批准且未 stale/revoked | 不伪造成单次回答 |
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
- **授权决策点与执行顺序**：任何真实自动采集 enqueue 前，目标 surface/渠道必须已经有有效 `approved` 记录；`not_assessed`、申请中、`assessed_no_basis`、过期或撤销均不能创建 live 自动任务。第 2 月先对每个首批 surface/渠道逐项形成 `approved` 或 `assessed_no_basis`，再按对应轨道执行；申请中在技术上按 B 轨限制，月末仍未获批准则正式记录 `assessed_no_basis`，不允许第三种悬置轨道跨月。决策记录进入当月 evidence manifest；后续取得授权可创建新授权版本、升轨并补做 A 轨验收。
- live admission 在创建 Job/outbox 的同一事务中校验 authorization ID/version/hash、surface/release、用途、允许频率和到期时间并冻结引用；校验失败时零 Job、零 outbox。Worker claim 后和目标页面导航前再次检查未 revoked/expired；失效时停止且不得发起页面请求。
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
| C. 观测与统计 | Sampling、消费者 UI surface adapter、五类外部 API adapter、语义指标、统计、漂移、告警 | Prompt Program、Model Gateway、QuestionSet、Connector raw artifacts |
| D. Prompt 与建议 | Prompt 生命周期、judge/arbiter、Recommendation、草稿闭环 | A/B/C 的真实 lineage 与版本化输出 |

四条工作流允许按月并行，但以下内容必须单线合入：

- Alembic 迁移始终只有一个 owner 和一个线性 head。
- 共享枚举、OpenAPI schema、Prompt/Model Gateway port 和 artifact manifest 先冻结合同再实现。
- 同一共享表、共享 API schema 或 Customer 投影不得由两条工作流并行修改。
- 每月先通过共享合同测试，再合并工作流功能；不以跨分支临时兼容代码替代合同。

### 3.3 启动前提

- 达到第 3.4 节最低人力配置并完成具名分配；只指定 owner 但没有足额并行 FTE 不启动六个月时钟。
- 准备可产生验收证据的 GSC、GA4、五类外部 API、至少一个登录采集账号，以及至少一个可路由浏览器流量的澳洲代理出口。
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

### 3.5 RACI 和签字责任

| 事项 | Accountable（最终负责） | Responsible（实施） | Consulted（必需会签） | Independent verifier |
|---|---|---|---|---|
| 共享 schema、Alembic 和兼容迁移 | Migration owner | 指定 backend/data engineer | 各受影响工作流 owner | QA + 未编写该迁移的 backend |
| Prompt/Model Gateway/Secret | D 工作流 owner | backend/ML + DevOps/Security | A/C owner、运营 | QA/Security |
| 合成实验室和 Profile 发布 | A 工作流 owner | backend/ML + data/evaluation | Product/运营、Knowledge owner | QA + 运营明审人 |
| 外部数据与跨引擎采样 | B/C 联合 owner，以专项文件为准 | backend/data/browser | Security、Product/运营、统计 owner | QA + Security/运营（按证据类型） |
| 指标、统计和告警 | C 工作流 owner | statistics/data/backend | B、D owner | 独立 statistics reviewer + QA |
| 归因账本和真实旅程 | B 工作流 owner | backend/data | Product/运营、Privacy/Security | QA + 业务数据 owner |
| 建议与下游草稿 | D 工作流 owner | backend/ML + frontend | A/B/C owner | QA + Product/运营 |
| Customer 投影和最终发布 | Product owner | frontend/backend/DevOps | A/B/C/D owner、Security | QA release owner |

同一人可以兼任多个 Responsible 角色，但不能验证自己编写的迁移、统计实现、安全控制或 live 采集证据。Product/运营签字确认业务语义、授权轨道和人工明审，不替代工程测试；QA/Security 签字也不替代业务 owner 对真实账号和真实归因旅程的确认。

### 3.6 实现落点和仓库边界

下表冻结模块所有权，不冻结每个文件的最终名称。新目录在首个合同 PR 中创建；若实施时改变目录，必须保持依赖方向并在 architecture test 中更新边界。

| 能力 | 计划代码落点 | 复用现有能力 | 禁止事项 |
|---|---|---|---|
| Prompt Program / Model Gateway | `packages/geo_core/geo_core/prompts/`、`model_gateway/` | Prompt Release、`model_call_logs` | Provider SDK 类型进入 Domain |
| Secret Store | `packages/geo_core/geo_core/secrets/` + Internal API/Admin | Docker Secret、审计、项目权限 | Job/日志/工件保存明文 secret |
| 合成实验室 | `packages/geo_core/geo_core/synthetic_lab/` | Knowledge/Fact、QuestionSet、Placements simulation | synthetic 写入真实 Observation |
| 外部 Connector | `packages/geo_core/geo_core/connectors/` | Durable Job、MinIO、`monitoring.official_reports` | PyAirbyte state 成为业务真源 |
| Sampling/Provider | `packages/geo_core/geo_core/sampling/` | `monitoring.source_contract`、Model Gateway | API 结果冒名消费者 UI |
| Browser Capture | `packages/geo_core/geo_core/browser_capture/` + 独立 Worker composition | Durable Job、Secret、MinIO | 第二套队列、直连旁路、stealth/CAPTCHA 绕过 |
| 指标/统计/告警 | 扩展 `packages/geo_core/geo_core/monitoring/` | SourceStratum、statistics、Customer projection | 不同 capture method 混分母 |
| Attribution | `packages/geo_core/geo_core/attribution/` | Project/Campaign、verified URL、Outbox | GA4 聚合伪造成 Session/Touch |
| Recommendation | `packages/geo_core/geo_core/recommendations/` | Prompt Program、Monitoring、Knowledge | 批准后自动执行或发布 |
| API/Worker | `apps/api/geo_api/`、`apps/api/geo_worker/` | Internal/Customer app、Relay、readiness | 在 route/task 内复制领域规则 |
| Admin/Customer Web | `apps/admin-web/`、`apps/customer-web/`、`packages/web/` | 稳定 OpenAPI client、现有 Portal shell | 前端自行推断 latest/eligible |
| Infra/Test | `infra/`、`scripts/`、`tests/`、`contracts/openapi/` | Compose、备份恢复、Chromium、acceptance | 另建不可追踪的部署/测试入口 |

### 3.7 执行节奏和变更控制

- 每周：工作流 owner 更新稳定 ID 的状态、剩余依赖、预算消耗、live 配额和新增风险；只链接证据，不在会议记录中替代 evidence manifest。
- 每个 sprint：先合并线性 migration/共享合同，再合并 Domain、Application/Repository、API/Worker、Admin/Customer 和验收证据；跨层未闭合的功能保持 feature flag 关闭。
- 每月第 3 周：执行 release candidate、数据对账、性能趋势和故障演练，给退出评审保留至少一周修复时间。
- 月度退出评审：owner 提交 `READY_FOR_REVIEW`，verifier 按 `GATE-M*` 与 `EXT-GATE-M*` 逐项复核。任一必需项失败则整月不进入 `ACCEPTED`。
- 变更控制：记录提出人、原因、影响的 check/gate ID、成本/日期变化、风险、回滚方案和批准人；被替换条款保留历史，不原地抹除失败证据。

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

> 本节保留跨模块不可变合同。Connector Core、GSC/GA4、官方报告的任务分解、当前代码差距、逐源测试和完成状态统一维护在[外部数据与跨引擎采样专项实施计划](GEO-external-data-cross-engine-sampling-implementation-plan-2026-07-22.md)；本节 6.3/6.4 的本地归因仍由主计划负责。

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

#### 6.2.1 外部投影批准边界

GSC、GA4 和 official-report 的 raw/projection 默认只对 Admin 可见。Adapter Release 的批准只授权代码运行，不批准任何数据。Customer 展示必须先创建不可变 External Data Snapshot，再由独立 External Data Report 执行 `draft -> in_review -> approved -> stale|superseded|revoked`；只有 `approved` report 进入 Customer latest。snapshot 冻结 Project、显式 Campaign、Connection/Scope、源 Run/Import、period/freshness、schema/parser/adapter、row count、dataset/payload hash、字段白名单和 lineage。同步/导入/刷新只创建新 internal projection 和 draft，不自动批准或修改历史 approved report。完整对象、命令、幂等、latest 和验收合同以外部专项计划第 5.4 节为准。

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

> 本节保留 SourceStratum、消费者 surface、代理真实性和统计的全局合同。Sampling Core、Provider/Grounded API、Browser Capture、Egress 与 Surface Release 的实施 checklist 和状态以[专项实施计划](GEO-external-data-cross-engine-sampling-implementation-plan-2026-07-22.md)为准；指标、统计与告警仍由本文件 7.3-7.5 节负责。

### 7.1 Sampling Core

Sampling Suite/Run/Task 的执行单位固定为：

```text
platform + surface + configured/reported model + capture_method
+ question_version + repetition + locale + region + language + search_mode
+ browser_profile_version + egress_policy_version + egress_cohort_key
+ account_cohort (UI capture only)
```

每个 Task 可独立租赁、重试、取消和终止；成功必须有原始回答/工件和完整运行参数。Suite 冻结 QuestionSet、目标平台、重复次数、有效完成度门槛、统计方法和预算。Run 只聚合 Task，不把失败 Task 静默从预期分母中删除。

UI Task 创建前冻结稳定的 `egress_policy_version` 和 `egress_cohort_key`。cohort 至少包含预期国家/地区、允许的 network type，以及单一 Egress Endpoint 或版本化 approved endpoint pool；这些稳定字段参与 planned Task、幂等键和 SourceStratum 分母。`egress_verification_id`、实际 endpoint、sticky lease、pre/post IP/ASN 和连接日志只有 Attempt 执行后才产生，只保存到 Attempt 和其胜出 Observation lineage，永不参与 Task identity、幂等键或基础分母 hash。重试创建新 Attempt 和新 Egress Verification，但仍占同一 repetition/planned slot。实际出口偏离冻结 cohort 时该 Attempt ineligible；若 Protocol 要做 endpoint-specific 分层，必须在 Suite 冻结时把 endpoint ID 显式纳入 cohort，不能事后按 verification ID 拆分。

自动 adapter 包括：

1. OpenAI API/Web Search 模式。
2. Gemini Grounding。
3. Perplexity API。
4. Microsoft Bing Grounding。
5. Kimi API；是否具备供应商原生 Search 必须由 Adapter Release 按当时官方能力和真实响应证明。没有原生 Search 时冻结为 `search_mode=disabled`，不得用自建检索冒充 Kimi Search。

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
| UI Capture Attempt | 单个 query/repetition 的执行与终态 | Task、surface release、session、egress verification、timings、result class、failure class |
| Page Artifact Bundle | 页面原始证据 | screenshot、DOM snapshot、HAR、final URL、console/network summary 及逐文件 hash |
| Parsed UI Observation | 从同一页面提取的回答与引用 | winning Attempt/egress verification lineage、answer text、citation URL/order、surface state、evidence locators、parser version |

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

## 9. 分阶段实施计划和 checklist

月份是有依赖关系的交付批次，不是可以绕过退出门槛的日历截止日。每个阶段先满足进入条件，再执行工作包，最后通过阶段 Gate；未通过的阶段继续修复，依赖它的工作包不得用临时 fixture 或手工数据库写入冒充完成。

M0 是六个月时钟启动前的准备 Gate，不计入六个月交付周期。只有 `GATE-M0` 和 `EXT-GATE-M0` 通过后才进入 M1 并开始计时；资源准备长期未完成不能消耗月份后再降低 M6 门槛。

### 9.1 阶段总表和关键路径

| 阶段 | 主题 | 必须先通过 | 关键输出 | 阶段 Gate |
|---|---|---|---|---|
| M0 | 启动与基线冻结 | 无 | 人力、资源、授权、预算、迁移和证据基线 | `GATE-M0` |
| M1 | 共享基础与采集骨架 | `GATE-M0` | Prompt、Gateway、Secret、合成/外部领域骨架、性能基线 | `GATE-M1` + `EXT-GATE-M1` |
| M2 | 首批真实数据与五平台测评 | M1 shared contracts | 五平台 Profile、生成 Beta、GSC/GA4、消费者 UI Beta | `GATE-M2` + `EXT-GATE-M2` |
| M3 | 九平台闭环与多引擎发布 | M2 Profile/Sampling | 修订、Corpus、三臂实验、五类外部 API、三首批 surface release | `GATE-M3` + `EXT-GATE-M3` |
| M4 | 统计、告警与归因入口 | M3 frozen observations | 完整指标、统计比较、漂移/告警、一方事件入口 | `GATE-M4` + `EXT-GATE-M4` |
| M5 | 业务闭环与 Customer 投影 | M4 metrics/events | 归因快照、批准投影、建议与草稿阻断闭环 | `GATE-M5` + `EXT-GATE-M5` |
| M6 | 生产等价验收 | M1-M5 accepted | live staging、迁移、性能、故障、备份恢复和发布证据 | `GATE-M6` + `EXT-GATE-M6` |

关键路径为 `Secret/备份 -> Connector/Browser live -> frozen Observation -> Metric Snapshot -> Attribution/Recommendation -> Customer approved projection -> full-chain staging`。非关键 UI polish 可以按第 3.4 节降范围，关键路径中的真实性、安全、统计和恢复门禁不可降级。

### 9.2 M0：启动与基线冻结

**实施 checklist**

- [ ] `M0-GOV-01` 冻结 9.5 engineering FTE + 1.0 Product/运营的具名分配、替补和 on-call；owner：Product/Engineering lead；证据：签字容量表。
- [ ] `M0-GOV-02` 指定唯一 Alembic owner、OpenAPI owner、release owner 和各工作流 verifier；证据：RACI 与 CODEOWNERS/评审规则映射。
- [ ] `M0-GOV-03` 在每项工作开始前为 M0 checklist ID 冻结 work package type、capability flags 及全部 DoR/DoD applicability；M1-M6 逐阶段沿用同一规则。
- [ ] `M0-RES-01` 建立真实资源清单：GSC、GA4、五类外部 API、三个消费者 surface、登录采集账号、澳洲代理、一方事件测试站点；只记录 reference/owner/状态，不记录 secret。
- [ ] `M0-AUTH-01` 为九个风格渠道和三个首批消费者 surface 建立 authorization record，记录待评审依据、用途、频率、到期日和 A/B 轨决策日期。
- [ ] `M0-BUD-01` 冻结六个月模型/API/代理/存储预算、供应商配额、成本告警和预算耗尽的缩范围顺序。
- [ ] `M0-SEC-01` 完成 F-003/F-017 重新评估计划、数据分类、keyring/escrow 保管人、备份加密密钥隔离和真实数据准入清单。
- [ ] `M0-ARCH-01` 对现有 migration head、SourceStratum v3、official report、Durable Job、Model Gateway、MinIO、Compose 和 Admin/Customer 基线做 inventory，并为新增模块形成 ADR/合同差异表。
- [ ] `M0-EVD-01` 冻结 evidence manifest schema、逐 check 的 type/flags/applicability/时间/commit/migration/OpenAPI/scope/run/artifact 映射、N/A 独立签字规则、保存 bucket 和 hash 校验命令。
- [ ] `M0-PLAN-01` 专项文件的 `EXT-M0-*` 和 `EXT-GATE-M0` 全部完成。

**退出 Gate `GATE-M0`**

- [ ] `M0-AC-01` 所有关键角色达到最低 FTE，任一人的总分配不超过 1.0，且未来两个 sprint 可实际投入。
- [ ] `M0-AC-02` 每项真实外部资源都有 owner、预计可用日期、secret reference 计划和不可用时的明确轨道/阻塞处理。
- [ ] `M0-AC-03` 未通过 Secret/备份门禁前，环境技术上只能接收无敏感 fixture，不能靠流程提醒绕过。
- [ ] `M0-AC-04` Alembic 仍为单一 head；首批 expand/compatible-writer 顺序和 writer inventory 已获各工作流 owner 会签。
- [ ] `M0-AC-05` evidence manifest 能以一个治理项和一个技术项的基线 smoke run 证明 type/flags、required/N/A、scope、记录数、hash、commit、环境指纹和双人签字可复核。
- [ ] `M0-AC-06` `EXT-GATE-M0` 已通过，主计划与专项计划不存在未解释的范围或门槛冲突。
- [ ] `M0-AC-07` M0 所有 `C` 均已解析，所有 N/A 有独立 verifier；治理/预算/Gate 项不会被要求提供不适用的 migration/OpenAPI/lease/live 证据。

### 9.3 M1：共享基础与采集骨架

**进入条件**：`GATE-M0=ACCEPTED`；migration、security、Prompt、external 三类首批合同均已完成 DoR。

**实施 checklist**

- [ ] `M1-BASE-01` 冻结共享枚举、artifact/evidence manifest、版本/hash、错误语义、Customer 过滤和 RLS/RBAC 合同；owner：Migration + API owner。
- [ ] `M1-PROMPT-01` 在现有 Prompt Release 上实现八种首批 `program_kind` 的 create/test/diff/approve/freeze/bind；`reference_translation` 仅保留枚举。
- [ ] `M1-MODEL-01` 将 DeepSeek 迁入统一 Gateway，并完成 OpenAI/Kimi/Gemini/Perplexity/Microsoft adapter contract；至少三个真实供应商做结构化输出 smoke。
- [ ] `M1-SECRET-01` 实现 envelope encryption、project scope、审计、轮换/撤销、redaction、Docker Secret fail-closed、历史 keyring 和逐版本 canary。
- [ ] `M1-SECRET-02` 完成认证加密备份、`0700/0600`、签名/checksum、错误 key 负测及空环境 keyring + 数据恢复演练，作为真实凭据准入 Gate。
- [ ] `M1-SYN-01` 落地 Style Source/Collection Run/Sample/Profile、Review Suite/Case 的 Domain、迁移、repository、Internal API 和 Admin 最小界面。
- [ ] `M1-SYN-02` 实现人工样本导入、公开/正常登录采集、落盘前分类/脱敏/加密/TTL 和去重骨架；冻结九平台 360 Case 的 schema。真实自动采集只有在渠道已有有效 `approved` 时执行，否则只跑 fixture/人工导入。
- [ ] `M1-EXT-01` 完成专项文件全部 `EXT-M1-*`，包括 Connector/Sampling/Browser/Egress 骨架和三个 surface parser fixture PoC。
- [ ] `M1-QA-01` 为共享合同建立 architecture/unit/PostgreSQL/MinIO/Valkey/OpenAPI/Chromium 测试入口，并证明必需测试零收集/意外 skip 会失败。
- [ ] `M1-PERF-01` 冻结第 10.7 节 `performance-profile-v1`、负载生成器合同、生产等价拓扑和资源上限。

**退出 Gate `GATE-M1`**

- [ ] `M1-AC-01` 同一固定输入可比较两个 Prompt Release；approved Release、compiled prompt、binding 和 hash 不可原地变更，历史 Job 可复现。
- [ ] `M1-AC-02` 至少三个真实模型 smoke 成功；错误 JSON/enum、schema、主体和 Fact 引用被应用侧拒绝，provider fallback 不会静默发生。
- [ ] `M1-AC-03` 测试 secret 在数据库可见字段、Job/outbox、日志、exception、MinIO、API 和浏览器中零明文命中；撤销旧 reference 后调用 fail closed。
- [ ] `M1-AC-04` 空环境恢复全部在用 key-version canary、代表性 secret 和不泄密 connection test；错误/缺失 key 必然失败。
- [ ] `M1-AC-05` 一个公开 Style Source 和一个正常登录 Style Source 通过已批准自动路径或合规人工导入产生匿名派生样本；Cookie/token/PII 不落普通 bucket，未批准自动访问、验证码/封禁路径停止。
- [ ] `M1-AC-06` `EXT-GATE-M1` 通过；Connector 状态机、代理强制出口、surface fixture 分类和阻断检测均有专项证据。
- [ ] `M1-AC-07` `performance-profile-v1` 已写入版本化 manifest，包含 Project/Task/record/artifact/RPS/Worker/队列/API 目标，不能在 M6 失败后原地放宽。
- [ ] `M1-AC-08` 当月 evidence manifest 覆盖全部已勾选 ID，owner/verifier 可从干净环境重算 hash。

### 9.4 M2：首批真实数据与五平台测评

首批平台为 `owned_site`、`productreview`、`reddit`、`ozbargain` 和 `quora`。自动采集或人工导入必须服从同一授权、匿名、去重和明审合同。

**进入条件**：M1 shared schema、Secret Store、备份恢复和 `EXT-GATE-M1` 已接受；真实凭据准入清单已签字。

**实施 checklist**

- [ ] `M2-AUTH-01` 在任何真实自动采集 enqueue 前完成第 2.4 节授权决策点；九风格渠道和三个消费者 surface 均进入明确 A/B 轨，申请中按 B 轨限制且没有悬置状态跨月。
- [ ] `M2-SYN-01` 五个平台各导入/采集至少 200 条去重、匿名、AU English、人工明审通过样本，并冻结 corpus manifest。
- [ ] `M2-SYN-02` 为五个平台构建、评审、批准和冻结 Style Profile Version；Profile 可回溯到样本、Prompt Release 和 reviewer。
- [ ] `M2-SYN-03` 实现 `autonomous_scenario`、`guided_scenario`、每 Case 四候选、claim extraction、基础 conflict/style judge 和候选 lineage。
- [ ] `M2-SYN-04` 冻结五平台各 40 Case 的固定回归内容，模式各半、竞品场景每平台不少于 30%。
- [ ] `M2-EXT-01` 完成专项文件全部 `EXT-M2-*`：真实 GSC/GA4 首次+增量、官方报告导入骨架、Sampling Core、消费者 UI Beta 和 Admin 控制面；非 UI Connector 可与授权评审并行，但消费者 UI live 子项必须在 `M2-AUTH-01` 后执行。
- [ ] `M2-QA-01` 执行五平台回归、跨 Project/RLS、重复导入、取消/lease、原始工件治理和 Customer 不可见负测。

**退出 Gate `GATE-M2`**

- [ ] `M2-AC-01` 五平台各自的样本数、去重率、匿名扫描、AU English 判定和人工审批可由 manifest 与查询逐条对账。
- [ ] `M2-AC-02` 五个 Profile Release 均不可变且通过人工明审；未批准 Profile 无法绑定正式 Review Run。
- [ ] `M2-AC-03` 两种 scenario mode 各自生成四候选；运营输入不能覆盖 Fact/Catalog 主体或成为事实来源。
- [ ] `M2-AC-04` `EXT-GATE-M2` 通过：真实 GSC/GA4、Sampling 分母、消费者 UI 所在轨道和授权决策均有专项证据。
- [ ] `M2-AC-07` 缺失/申请中/B 轨/过期/撤销授权的 automated UI enqueue 产生零 Job/零 outbox；已排队或运行任务在 claim/导航前发现失效即停止。
- [ ] `M2-AC-05` `manual_ui`、`automated_ui`、Provider fixture、official report 和 synthetic 在 API、统计输入、UI 与导出中无法互相冒名或混分母。
- [ ] `M2-AC-06` Customer API 对所有 M2 合成、中间评审、raw external 和未批准结果返回空或授权错误，不泄漏内部存在性。

### 9.5 M3：九平台闭环与多引擎发布

后四个平台为 `amazon`、`youtube`、`tiktok` 和 `instagram`；授权或技术条件不支持自动采集时，以合规人工导入完成样本门槛，不降低样本质量。

**进入条件**：五平台 Profile/Suite 已冻结；Sampling/Observation source contract 可稳定消费；M2 授权双轨已决策。

**实施 checklist**

- [ ] `M3-SYN-01` 后四平台各完成 200 合格样本、Profile 发布和 40 固定 Case，形成九平台 360 Case Suite。
- [ ] `M3-SYN-02` 完成 conflict/subject check、最多两轮 revision、一次 regenerate batch、warning 直出、任务取消、lease 丢失和 Fact 失效状态机。
- [ ] `M3-SYN-03` 完成 Corpus Version 与三臂配对 Offline Experiment；每题每臂 10 次，冻结 QuestionSet/模型/Prompt/Corpus/method/hash。
- [ ] `M3-SYN-04` 实现 passed/warning 合并与独立分层、Admin 明确 synthetic/test-only 标签及 Customer 全路径拒绝。
- [ ] `M3-EXT-01` 完成专项文件全部 `EXT-M3-*`：五类外部 API release、三个首批 Surface Release 的 A/B 轨保真度和重复采样调度。
- [ ] `M3-QA-01` 执行九平台固定集、跨模型 judge/arbiter、修订/regenerate 精确次数、工件/hash、并发取消和 stale writer 负测。

**退出 Gate `GATE-M3`**

- [ ] `M3-AC-01` 九平台均满足第 10.1 节发布门槛；任何单平台不能由全局平均掩盖失败。
- [ ] `M3-AC-02` 两轮修订后只允许一个 regenerate batch；取消、lease/fencing 丢失或 Fact retired 不提交陈旧 Candidate/Corpus。
- [ ] `M3-AC-03` `derived_or_unknown` 可形成 warning；明确 conflict/subject mix 必须修订，subject mix 总数为 0 才可发布。
- [ ] `M3-AC-04` 三臂实验对相同冻结输入可重算同一 hash；warning 占比/分层始终可见；synthetic 无 Customer 读取路径。
- [ ] `M3-AC-05` `EXT-GATE-M3` 通过；五类外部 API live canary 与三个 Surface Release 逐 release 保真证据齐全，不借用其他 surface/release 样本。
- [ ] `M3-AC-06` 至少三家不同模型供应商参与 generation/judge/arbiter 验收，单一供应商不能同时充当唯一生成者和唯一裁判。

### 9.6 M4：统计、告警与归因入口

**进入条件**：M3 产生冻结 Observation/Corpus；metric schema、统计 Protocol 和 attribution event schema 完成 DoR。

**实施 checklist**

- [ ] `M4-METRIC-01` 实现第 7.3 节完整指标、规则优先、metric judge/arbiter、逐回答 span/citation/Fact evidence locator 和 invalid 判定。
- [ ] `M4-STAT-01` 实现 Wilson/Newcombe、确定性 paired bootstrap、Holm、多重 family、冻结 `delta/power/precision/min pairs` 和五类结论。
- [ ] `M4-STAT-02` 实现跨问题负收益、最差问题/簇，以及 provider/model/source/locale/region/query cluster 漂移的独立报告。
- [ ] `M4-ALERT-01` 实现 threshold/baseline/negative/completion/freshness/model/source/connector 告警、去重、确认/抑制/解决和处置历史。
- [ ] `M4-ALERT-02` 实现 Admin inbox、本地 SMTP 和签名内网 Webhook outbox；通知失败不回滚业务告警且重试不重复建单。
- [ ] `M4-ATTR-01` 实现版本化一方事件 schema/receiver、consent 状态、UTM/opaque trace、Session/Touch/Conversion 幂等入口和零点击 exposure 隔离。
- [ ] `M4-ATTR-02` 实现 GA4 聚合对账视图，技术上禁止 GA4 report row 创建 Session/Touch。
- [ ] `M4-EXT-01` 完成专项文件全部 `EXT-M4-*`：adapter drift/freshness/错误进入告警，冻结 Observation 能稳定交付统计层。

**退出 Gate `GATE-M4`**

- [ ] `M4-AC-01` 相同输入/method 在不同进程和重试中得到相同 input/result hash、区间、校正和结论。
- [ ] `M4-AC-02` `delta`、power、precision、min pairs、alpha、family 和 seed 均在运行前冻结并可从报告还原。
- [ ] `M4-AC-03` 区间跨任一方向/等效边界时只能为 `inconclusive`；样本/完成度不足只能为 `insufficient_evidence`，UI 不显示含混“平”。
- [ ] `M4-AC-04` 平均提升不能隐藏局部退化；负收益和最差问题可触发独立规则，model/source drift 与效果变化分开显示。
- [ ] `M4-AC-05` 告警重复计算、并发确认、抑制到期和通知重试保持一个业务告警及完整处置历史。
- [ ] `M4-AC-06` 重复/迟到一方事件幂等；PII trace、概率跨设备、GA4 聚合造 Session 和零点击造转化均被拒绝。
- [ ] `M4-AC-07` `EXT-GATE-M4` 通过，connector/surface/provider failure、freshness 和 drift 均能以非敏感证据进入告警。

### 9.7 M5：业务闭环与 Customer 投影

**进入条件**：M4 Metric Snapshot、Alert 和一方事件入口已接受；Customer 字段白名单和 attribution policy 完成 DoR。

**实施 checklist**

- [ ] `M5-ATTR-01` 实现 Lead/Stage/Deal/Revenue Admin 录入和幂等文件导入，冻结模板 schema、文件 hash、source event ID 与行级错误报告。
- [ ] `M5-ATTR-02` 实现不可变 Attribution Policy Version、30 天 last-click、90 天 assisted、direct/first/last/assisted 和 snapshot cutoff/迟到事件处理。
- [ ] `M5-ATTR-03` 实现 Revenue -> Deal/Conversion/Lead/Session/Touch -> UTM/trace -> Campaign/QuestionSet/verified URL/Package Version 强 lineage 与 unassigned 路径。
- [ ] `M5-CUST-01` 实现回答型 approved Monitoring Report 与非回答型 approved External Data Report 的独立 Customer latest 投影、来源/分母/区间/warning/非因果标签和字段白名单；无数据批准或不足证据时返回明确空状态。
- [ ] `M5-REC-01` 实现 Recommendation evidence graph、六种类型、Prompt/Fact/Metric/Attribution lineage、人工 review/approve/reject。
- [ ] `M5-REC-02` 实现 `approved -> stale|expired`、输入版本再校验，以及所有关联草稿的事务内 blocked propagation。
- [ ] `M5-DRAFT-01` 实现 Experiment Plan、QuestionSet、Content Brief、Sampling Plan 幂等草稿；批准不 enqueue、不生成、不执行、不发布。
- [ ] `M5-EXT-01` 完成专项文件全部 `EXT-M5-*`：外部来源批准投影、运营控制面和 runbook 达到稳定状态。

**退出 Gate `GATE-M5`**

- [ ] `M5-AC-01` fixture Revenue 可逐跳回溯到 GEO 内容版本；任一强关联缺失时明确 `unassigned`，不使用 IP/UA/时间邻近填补。
- [ ] `M5-AC-02` 30/90 天窗口边界、direct/first/last/assisted、重复/迟到、跨设备拒绝和零点击隔离都有确定性 golden fixture。
- [ ] `M5-AC-03` Customer 无法读取 synthetic、未批准/不足证据、内部建议、raw answer/page、secret、内部 actor 或 debug 字段。
- [ ] `M5-AC-07` GSC/GA4/official-report 的 sync/import/Adapter Release approval 都不能直接提升 Customer 可见性；只有绑定 exact immutable snapshot 的 approved External Data Report 可见，stale/superseded/revoked 立即退出 latest。
- [ ] `M5-AC-04` Recommendation 任一 Fact/Observation/Metric/Attribution/Prompt 版本失效后持久化为 `stale|expired`，关联草稿同步 blocked。
- [ ] `M5-AC-05` 批准重试只创建一个草稿；API、Worker 和 repository 直接调用都无法绕过源 Recommendation version recheck。
- [ ] `M5-AC-06` `EXT-GATE-M5` 通过，外部运行状态、授权到期、freshness 和 adapter release 可由 Admin 处置且 Customer 只见批准结果。

### 9.8 M6：生产等价验收与发布准备

M6 只允许修复、迁移、验证和运维固化，不新增未基线化的 Provider、surface、指标或建议类型。新需求进入后续版本，避免最终验收期间改变分母或风险面。

**进入条件**：M1-M5 所有主 Gate 和专项 Gate 已接受；release candidate、migration plan、rollback window 和 live evidence calendar 已冻结。

**实施 checklist**

- [ ] `M6-LIVE-01` 使用真实 GSC、GA4、一方事件、五类外部 API、至少三家生成/评审模型、一个正常登录采集账号和一个验证过的澳洲 residential/ISP/mobile 出口执行全链 staging。
- [ ] `M6-LIVE-02` 对 A 轨 surface 执行真实 automated UI，对 B 轨执行 fixture + `manual_ui`；逐 release 保留自身证据，不汇总借样本。
- [ ] `M6-ATTR-01` 完成一条经授权/同意的真实 UTM/trace -> Session/Touch -> Conversion/Lead/Deal/booked Revenue 旅程并回溯 GEO 版本。
- [ ] `M6-MIG-01` 完成旧 Prompt/Protocol/Observation/Metric 的 expand、compatible writer、initial backfill、增量追尾、dual-read 对账、cutover、rollback window 和 contract 演练。
- [ ] `M6-MIG-02` 证明 unknown/ineligible 与历史 hash/Customer 可见性不被提升或改写；forward-fix 和回滚均不删除真实数据。
- [ ] `M6-PERF-01` 在第 10.7 节完整 `performance-profile-v1` 下执行容量测试并达到 API/队列/Job/工件/正确性门槛。
- [ ] `M6-FAIL-01` 演练慢/限流/撤权供应商、取消、lease/fencing、Worker/Relay、PostgreSQL、MinIO、Valkey、网络和 outbox 故障恢复。
- [ ] `M6-WEB-01` 完成 Admin/Customer Chromium 全链、权限负测、关键桌面 viewport、长文本/错误/空/加载状态验收。
- [ ] `M6-RESTORE-01` 在空环境恢复认证加密 PostgreSQL/MinIO、独立历史 keyring、逐 key canary、代表性 secret、业务关系/hash 和批准 Customer 投影。
- [ ] `M6-OPS-01` 固化部署/回滚、告警、secret/provider/代理轮换、connector 撤权、schema drift、raw TTL、备份恢复和 incident runbook。
- [ ] `M6-EXT-01` 完成专项文件全部 `EXT-M6-*` 和 `EXT-FINAL-*`。
- [ ] `M6-EVD-01` 汇总 M0-M6 evidence manifest，验证所有 URI/hash、签字、change record、未完成项和已知风险。

**退出 Gate `GATE-M6`**

- [ ] `M6-AC-01` 第 10 节和专项计划全部必需 AC 均映射到可读取的自动化/live/人工/恢复证据；mock 不替代 live。
- [ ] `M6-AC-02` 外部超时、限流、撤权、阻断、地域变化、DOM/schema drift 和部分完成不会产生假成功、串分母、覆盖 checkpoint 或 freshness 假象。
- [ ] `M6-AC-03` 在线迁移切换前连续两轮逐 Project/Campaign 零差异且 lag=0；rollback window 内新旧 writer/read path 可逆。
- [ ] `M6-AC-04` 完整 `performance-profile-v1` 达标；任何缩小 Project/Task/record/artifact/RPS 的运行仅标记诊断。
- [ ] `M6-AC-05` 空环境恢复后关键计数/关系、MinIO manifest/hash、approved projection、全部在用 key-version canary 和代表性 secret 均一致可用。
- [ ] `M6-AC-06` 真实归因旅程逐跳可复核，无 PII 导出、概率拼接、人工补造或 GA4 聚合冒充事件。
- [ ] `M6-AC-07` 每个自动采集 surface/渠道均有有效授权结论、轨道、到期日和对应轨道证据；过期/revoked 会自动停用。
- [ ] `M6-AC-08` `EXT-GATE-M6` 和专项 `EXT-FINAL-*` 全部通过。
- [ ] `M6-AC-09` release owner、Product、QA、Security、Migration owner 与四工作流 owner 完成最终签字；无未批准 P1/P2 风险。

## 10. 验收与质量门禁

### 10.1 合成实验室固定验收集

- [ ] `LAB-SET-AC-01` 九个平台各至少 40 个固定回归 Case，共至少 360 个。
- [ ] `LAB-SET-AC-02` 每个平台 `autonomous_scenario` 和 `guided_scenario` 各占一半。
- [ ] `LAB-SET-AC-03` 每个平台竞品场景不少于 30%，避免总体比例掩盖单平台空缺。
- [ ] `LAB-SET-AC-04` Case 冻结 Persona、UseCase、Question、Fact/Profile version、主体、预期风险和人工 rubric。

Prompt/Profile Release 同时满足以下条件才能发布：

| 门槛 | 要求 |
|---|---:|
| `passed` | `>= 95%` |
| 商品/竞品主体串用 | `0` |
| source reproduction/防复刻违规 | `0` |
| 平台风格均值 | `>= 4.2/5` |
| 人工明审 | 至少 1 名运营人员完成并签字 |

自动门槛之外，必须覆盖两轮修订、一次重新生成、Warning 直接输出、任务取消、租约丢失和 Fact 失效。人工明审保存 reviewer、rubric version、时间和结论，不只保存自由文本备注。

- [ ] `LAB-REL-AC-01` 九个平台分别达到 `passed>=95%`，不能用跨平台总平均替代。
- [ ] `LAB-REL-AC-02` 商品/竞品主体串用为 0，source reproduction/防复刻违规为 0。
- [ ] `LAB-REL-AC-03` 每个平台风格均值 `>=4.2/5`，至少一名运营 reviewer 按冻结 rubric 签字。
- [ ] `LAB-FLOW-AC-01` 两轮修订、一个 regenerate batch、Warning 直出、取消、lease/fencing 和 Fact 失效均有行为证据。
- [ ] `LAB-CUST-AC-01` 所有 synthetic/Review/Candidate/Corpus/Offline Experiment 均保持 test-only，Customer/API/export 全路径不可见。

### 10.2 真实外部验收

外部板块的逐项状态以[专项实施计划](GEO-external-data-cross-engine-sampling-implementation-plan-2026-07-22.md)为准；总计划只检查以下跨板块完成事实：

- [ ] `REAL-EXT-AC-01` 专项 `EXT-FINAL-01` 至 `EXT-FINAL-08` 全部通过。
- [ ] `REAL-EXT-AC-02` 一个真实 GSC property、一个真实 GA4 property、两类真实官方报告和五类 API 的证据均来自正确环境/release。
- [ ] `REAL-EXT-AC-03` AIO、AI Mode、Bing Copilot 各自按 A/B 轨逐 Surface Release 验收，分类/文本/引用比例不跨 release 汇总。
- [ ] `REAL-EXT-AC-04` GSC、GA4 和 official-report projection 均通过独立 External Data Report 数据批准生命周期；Adapter Release approval、sync/import success 或 raw projection 不能替代。
- [ ] `REAL-MODEL-AC-01` 至少三家不同供应商模型参与 generation/judge/arbiter，验证跨模型合同而非单模型自评。
- [ ] `REAL-STYLE-AC-01` 至少一个正常登录的风格采集账号通过落盘前治理；没有绕过验证码或访问控制。

mock/fixture 用于 PR 和故障覆盖，但不能替代上述 live 完成证据。真实验收记录 secret reference ID，不记录 secret 内容。

### 10.3 连接器、代理和 Secret 验收

- [ ] `CORE-SECRET-AC-01` Secret 创建、test、轮换、并发 reference version、撤销、错误主密钥和全介质泄漏扫描通过。
- [ ] `CORE-SECRET-AC-02` 历史 keyring 与数据备份分离；全部在用 key version 的 canary、代表性 Connector/Provider/Egress secret 和 connection test 在空环境通过。
- [ ] `CORE-RAW-AC-01` Raw Artifact 与 projection 的 record count/hash/lineage 一致；未知 schema 只阻断 projection，不删除 raw。
- [ ] `CORE-JOB-AC-01` 外部 Job 失败、取消、lease/fencing 丢失不提交领域终态、checkpoint 或 freshness 假象。
- [ ] `CORE-EXT-AC-01` Connector、Egress、Surface、Sampling 的详细 `EXT-CONN/EXT-EGR/EXT-UI/EXT-SAMP/EXT-SEC-FINAL-*` 全部通过。

### 10.4 采样和统计验收

- [ ] `STAT-SAMPLE-AC-01` API=10、automated UI 默认 5/最低 3、manual UI 最低 3，完成度使用冻结 planned denominator。
- [ ] `STAT-SAMPLE-AC-02` 低于样本门槛或 80% 有效完成度只产生 `insufficient_evidence`；超授权频率/配额被 admission 阻断。
- [ ] `STAT-STRATUM-AC-01` capture/model/locale/region/language/search/profile/egress policy/cohort/release/account cohort 任一预冻结维度不同不得静默混分母。
- [ ] `STAT-EGRESS-AC-01` UI 分母只使用预先冻结的 egress policy/cohort；每次 Attempt 的 verification ID 只作 Observation lineage，重试不会拆出新分母或新增 planned slot。
- [ ] `STAT-UI-AC-01` 每个 Surface Release 自身达到分类 `>=95%`、普通结果误标 0、答案 `>=99%`、引用 `100%`。
- [ ] `STAT-WARN-AC-01` Warning 合并后仍显示数量、比例和 passed/warning 独立结果。
- [ ] `STAT-METHOD-AC-01` Wilson/Newcombe、paired bootstrap、Holm、五类结论、负收益、最差问题和漂移通过 golden/recompute 测试。
- [ ] `STAT-METHOD-AC-02` 覆盖区间跨 `-delta/+delta`、完整等效区、胜/负、完成度不足和 variance 导致 precision 不足；不存在含混“平”。
- [ ] `STAT-VERSION-AC-01` Protocol/阈值/method/Prompt/judge 变化创建新版本，历史结果/hash 不变。

### 10.5 归因和建议验收

- [ ] `ATTR-METHOD-AC-01` 30/90 天窗口、direct/first/last/assisted、重复/迟到和 snapshot cutoff 通过 golden fixture。
- [ ] `ATTR-IDENTITY-AC-01` 跨设备概率拼接被拒绝，zero-click exposure 不进入 Session/Conversion/Revenue。
- [ ] `ATTR-LINEAGE-AC-01` Revenue 到 GEO 内容版本逐跳可复核；缺强关联时为 `unassigned`，不概率填补。
- [ ] `ATTR-LIVE-AC-01` 至少一条经授权/同意的真实旅程覆盖 UTM/trace -> Session/Touch -> Conversion/Lead/Deal/booked Revenue -> GEO 版本；fixture、GA4 聚合或人工补造不计入。
- [ ] `REC-TYPE-AC-01` 六种 Recommendation 均有 fixture；`no_change` 和 `insufficient_evidence` 是正常终态。
- [ ] `REC-STALE-AC-01` stale/Fact retired/method replacement/并发批准/重复草稿均有行为测试，关联草稿同步 blocked。
- [ ] `REC-BYPASS-AC-01` API、Worker 和 repository 直接调用都不能绕过 Recommendation version recheck；批准不自动执行/发布。

### 10.6 全仓门禁

每个批次执行与风险相称的门禁；第 6 月至少覆盖：

- [ ] `REPO-GATE-01` `make quality` 和全部单元/architecture 测试通过，无意外 skip/零收集。
- [ ] `REPO-GATE-02` PostgreSQL、MinIO、Valkey、Durable Worker/Relay 与隔离 Browser Worker 集成通过。
- [ ] `REPO-GATE-03` Alembic 前向、兼容 writer、追尾/对账、rollback/forward-fix 和单一 head 通过。
- [ ] `REPO-GATE-04` OpenAPI 生成/稳定快照、Web client contract、Admin/Customer 生产构建通过。
- [ ] `REPO-GATE-05` Chromium 关键工作流、权限负测、Customer 数据泄漏、长文本/错误/空状态通过。
- [ ] `REPO-GATE-06` 生产网络、代理强制、readiness、heartbeat、队列卡滞、secret preflight 和外部 egress 通过。
- [ ] `REPO-GATE-07` 认证加密备份、`0700/0600`、密钥隔离、历史 keyring 空环境恢复、逐 key canary 和业务一致性通过。
- [ ] `REPO-GATE-08` 受限 raw 的落盘前 secret/PII、独立加密、RBAC/RLS、TTL、双人 hold 和 Customer/export 负测通过。

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

- [ ] `PERF-AC-01` M1 前冻结的 `performance-profile-v1` 与本表逐项一致，负载生成器/recording、拓扑和资源配额均有版本/hash。
- [ ] `PERF-AC-02` M6 使用完整负载执行，所有延迟、队列、同步、容量和正确性门槛通过；缩量诊断 run 未被计为验收。
- [ ] `PERF-AC-03` evidence manifest 保存目标与实测 p50/p95/p99/max、错误/队列年龄、资源水位和原始报告 URI/hash。
- [ ] `PERF-AC-04` 若创建 v2，存在事前批准的业务/容量依据和影响分析；没有在 v1 失败后原地放宽。

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
- 每个 check ID 自身的 work package type/flags、逐条 DoR/DoD applicability、开始/结束时间、Git commits、migration revisions、OpenAPI contracts 和 `not_applicable` 独立批准；顶层汇总字段不能替代单项映射。
- Prompt/Profile/adapter/schema/method release IDs 与 hashes。
- 测试命令、收集数、通过/失败/skip 数和关键报告 URI/hash。
- 每个 check ID 自身的 Project/Campaign/environment fingerprint、live run IDs、脱敏 account/connection refs、原始工件 manifest 和人工审核记录；不适用的 scope 必须按第 1.3 节留痕。
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
| 消费者 UI 自动采样缺少平台允许依据 | 无 authorization record、条款过期或用途超范围 | 先决策后采集；enqueue 同事务 admission，失败零 Job/outbox；claim/导航前复验；第 2 月强制 A/B 结论；代理不能替代授权 |
| 澳洲代理不具备消费者代表性 | 出口为数据中心、地域源冲突或页面显示非 AU | 每 Attempt 同一 sticky lease 前后双源验证或可信连接日志；network type 分级；只有 residential/mobile 可标记代表性 |
| Attempt 出口证据拆碎统计分母 | 每个 verification ID 形成 n=1 分层 | Task/SourceStratum 只冻结 egress policy/cohort；verification 仅作 Attempt/Observation lineage；endpoint composition 单独展示 |
| 浏览器采集违反访问边界 | CAPTCHA、封禁、限流或异常重试上升 | 立即停止 Endpoint/Surface Run；不绕过、不自动换代理；保留阻断证据 |
| DOM/实验分流导致误判 | 答案为空、普通 snippet 被识别为 AIO、引用丢失 | screenshot/DOM/HAR 三证据、parser health、人工保真集和 adapter drift 告警 |
| 模型 judge 偏差或自评 | 不同模型分数分歧大、无 evidence locator | 规则优先、三供应商交叉验收、arbiter 和人工固定集 |
| API 成本/配额不足 | completion < 80%、持续 quota 告警 | 预冻结预算/并发；缩小 Suite 范围并新建 Protocol，不降低门槛 |
| Connector schema/API 漂移 | projection 失败但 Job 表面成功 | raw-first、schema fingerprint、fail-closed projection 和 freshness |
| Adapter 批准被误作数据批准 | sync/import 后 Customer 直接出现 GSC/GA4/official 数据 | External Data Snapshot/Report/Approval 独立状态机；只有 approved report 投影可见，raw/draft/stale/revoked 均拒绝 |
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
- [Microsoft Foundry Grounding with Bing Search](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools)

## 15. 六个月最终发布 checklist

本节是最终 Go/No-Go 索引，不替代前述细项。release owner 只能在被引用的原始 check ID 已有证据和签字后勾选，不能只凭本节的汇总勾选反向宣称完成。

### 15.1 阶段和范围

- [ ] `PLAN-FINAL-01` `GATE-M0` 至 `GATE-M6` 全部 `ACCEPTED`，每月 evidence manifest 的 URI/hash 可读取。
- [ ] `PLAN-FINAL-02` `EXT-GATE-M0` 至 `EXT-GATE-M6` 与专项 `EXT-FINAL-01..08` 全部 `ACCEPTED`。
- [ ] `PLAN-FINAL-03` 五个业务板块均达到第 1 节完成定义；所有降范围均有批准 change record，未修改真实性/安全/统计门槛。
- [ ] `PLAN-FINAL-04` 人力、预算、授权、账号和 live 资源的最终状态记录完整，无用 mock 掩盖的 `BLOCKED_EXTERNAL`。

### 15.2 产品和数据正确性

- [ ] `PLAN-FINAL-05` `LAB-*` 全部通过：九平台、360 Case、发布门槛、修订/Warning/Fact/lease 路径和 synthetic 隔离完成。
- [ ] `PLAN-FINAL-06` `REAL-*`、`CORE-*` 与专项逐源 AC 全部通过：GSC/GA4、官方报告、五类 API、三个消费者 surface 和澳洲出口证据完成。
- [ ] `PLAN-FINAL-07` `STAT-*` 全部通过：冻结分母、区间/校正、`inconclusive`、负收益、漂移、版本/hash 和 Warning 分层正确。
- [ ] `PLAN-FINAL-08` `ATTR-*` 全部通过：30/90 天、direct/first/last/assisted、零点击/跨设备边界和真实 Revenue 旅程完成。
- [ ] `PLAN-FINAL-09` `REC-*` 全部通过：证据图、六种类型、人工批准、stale/expired 传播和下游草稿执行前阻断完成。
- [ ] `PLAN-FINAL-10` Customer 只见 latest approved Monitoring Report 或 External Data Report；synthetic、raw、未批准/stale/revoked/不足证据、secret、内部建议和 actor/debug 字段全不可见。

### 15.3 工程、迁移和恢复

- [ ] `PLAN-FINAL-11` `REPO-GATE-01..08` 全部通过，实际执行数/skip/失败数进入 evidence manifest。
- [ ] `PLAN-FINAL-12` 所有 Alembic 迁移保持单一 head；writer inventory、双写/outbox 或停写锁、initial/final watermark、两轮零差异和 rollback window 证据完整。
- [ ] `PLAN-FINAL-13` `PERF-AC-01..04` 全部通过，完整 `performance-profile-v1` 达标。
- [ ] `PLAN-FINAL-14` PostgreSQL/MinIO 认证加密备份、权限、签名/checksum、密钥隔离和空环境恢复通过。
- [ ] `PLAN-FINAL-15` 全部在用 Secret master key version 的 canary、代表性 Connector/Provider/Egress secret 和 connection test 恢复可用；错误/缺失 key fail closed。
- [ ] `PLAN-FINAL-16` Raw Artifact 的分类、落盘前清理、独立加密、RBAC/RLS、TTL/tombstone、双人 hold 和 Customer/export 负测完成。

### 15.4 运营和签字

- [ ] `PLAN-FINAL-17` 部署/回滚、告警、secret/provider/代理轮换、connector 撤权、schema/DOM drift、归因补录和备份恢复 runbook 已由非作者演练。
- [ ] `PLAN-FINAL-18` 所有 authorization record 有当前状态、依据、用途、频率、到期和轨道；expired/revoked 技术上停止新任务。
- [ ] `PLAN-FINAL-19` 最终 evidence manifest 记录 Git/migration/OpenAPI/Web build、全部 release/hash、live/test/perf/restore run、人工审核、偏差和成本。
- [ ] `PLAN-FINAL-20` Product、A/B/C/D owner、Migration、QA、Security、DevOps 和 release owner 全部签字，无未批准 P1/P2 风险。

最终决定只允许：

| 决定 | 条件 | 后续动作 |
|---|---|---|
| `GO` | `PLAN-FINAL-01..20` 全部勾选 | 按 feature flag/canary 计划发布，保留 rollback window |
| `NO_GO` | 任一必需项未勾选或证据失效 | 保持现有生产路径，记录失败 ID、owner、修复日期并重新验收 |
| `SCOPE_CHANGE_REQUIRED` | 外部条件或容量使完成定义不可达 | 先批准新的范围/日期/风险决策，再更新两份计划；不得以豁免直接 GO |
