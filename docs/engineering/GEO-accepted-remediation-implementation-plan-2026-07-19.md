# GEO ACCEPTED 整改统一实施计划

> 计划日期：2026-07-19
> 计划状态：`IMPLEMENTED_LOCAL_VERIFIED`；外部 staging smoke 为 `PENDING_AUTHORIZATION`，客户生产部署为 `NOT_EXECUTED`
> 决策来源：`docs/audits/GEO-effect-first-remediation-decisions-2026-07-18.md`
> 需求与审计来源：`GEO_REQUIREMENTS.md`、`docs/audits/GEO-project-full-audit-2026-07-18.md`
> 范围：仅包含当前状态精确为 `ACCEPTED` 的 14 项整改
> 核心约束：效果优先、控制开发量、每项整改随附行为测试，不扩张为完整成熟 GEO 平台
> 实施证据：`docs/engineering/GEO-accepted-remediation-verification-record-2026-07-19.md`

## 1. 计划结论

本阶段共有 14 个 `ACCEPTED` 项：

`F-001`、`F-009`、`F-011`、`F-012`、`F-013`、`F-014`、`F-015`、`F-016`、`F-018`、`F-019`、`F-021`、`F-023`、`F-025`、`F-027`。

其中：

- 11 项是功能或运行整改。
- `F-015`、`F-016`、`F-025` 是贯穿全部实施工作的交付约束。
- `F-025` 在批次 0 启动，在所有其他整改完成后才能关闭，不能作为末尾补覆盖率的独立项目。
- `F-019` 是本阶段最大工作项，先做量化选型 Gate，再做生产集成；未通过 Gate 不得直接全面引入 RAG 框架。
- 当前工作树包含大量既有未提交修改。正式实施每一批前必须先核对已有实现与本计划验收标准，复用已经满足合同的部分，不回退、不覆盖、不重复实现用户现有工作。

本计划明确不包含状态为 `ACCEPTED_RISK`、`DEFERRED`、`MANUAL_WORKAROUND`、`OUT_OF_SCOPE` 或 `NEXT_PHASE_REQUIRED` 的完整平台能力。

### 1.1 Git 与运行环境保护

- 当前原型已经以提交 `267d970` 保存于 `main`，并创建本地保护标签 `geo-pre-remediation-20260719`。
- 全部整改只在本地分支 `feat/geo-accepted-remediation-20260719` 和 sibling worktree `/home/ymm/ym/gz/20260608-geo-accepted-remediation` 中实施；不向 `origin` 推送。
- 原工作树 `/home/ymm/ym/gz/20260608-geo` 保持在 `main`，现有 `geo-development` 和 `geo-advinsys-staging` 运行栈不用于整改迁移或测试。
- 整改栈使用 Compose project `geo-accepted-remediation`、独立数据卷以及端口 PostgreSQL `55434`、Valkey `26379`、MinIO `29000/29001`、API `28000/28001`、Web `23000/23001`。
- 每批在整改栈独立验收并创建本地批次标签；批次 5 全部通过前不更新 `main`。最终优先 `--ff-only` 合并；若 `main` 存在必要热修复，先同步热修复并重跑全部门禁。

## 2. 总体依赖顺序

```text
F-015 CI 真实性
   -> F-016 inline_isolated acceptance
   -> F-025 测试追踪开始
          |
          +-> F-001 egress -> F-018 运行真实性
          |
          +-> F-012 Campaign 真源 -> F-014 Opportunity Prompt 绑定
          |                         -> F-011 人工发布验证
          |
          +-> F-013 Fact -> Evidence -> F-019 RAG 核心
          |
          +-> F-009 观测来源契约 -> F-021 统计正确性
                                      |
                       F-012 ----------+-> F-023 Customer latest/Campaign
                                      |
F-013 + F-014 + F-009 + F-021 --------+-> F-019 问题/仿真
                                      |
F-011 + F-009 + F-021 + F-023 --------+-> F-027 JSON/CSV 导出
                                      |
全部 ACCEPTED 项 ----------------------+-> F-025 最终关闭
```

允许并行的工作：

- F-001/F-018 基础设施线可以与领域功能线并行，但二者共用 `compose.prod.yml`，必须由同一负责人串行合入。
- F-019 的代表语料、人工 gold set 和 adapter PoC 可在批次 1 启动；正式领域接入必须等待 F-013、F-014、F-009 和 F-021 的合同稳定。
- F-013 与 F-009 可并行开发；Alembic 迁移仍必须沿单一主干依次合入。
- F-011 verifier 逻辑可与 F-001 并行开发，但生产等价 URL 验收必须等待 egress 可用。
- F-023 的 Customer selector 可以在 F-012 后提前开发，但 latest 指标语义必须等待 F-021 完成。
- F-027 的导出骨架可以提前准备，Customer 字段白名单、统计复算和最终 schema 必须等待 F-009/F-021/F-023 稳定。

## 3. ACCEPTED 项与批次

| ID | 本阶段交付物 | 直接依赖 | 完成批次 |
|---|---|---|---:|
| F-015 | CI 不再零收集、意外跳过或读取其他 run 数据 | 无 | 0 |
| F-016 | 技术上隔离并明确标记的 `inline_isolated` acceptance | F-015 | 0 |
| F-025 | 验收条款到行为测试的追踪与最终门禁 | F-015；贯穿全部项 | 0 启动，5 关闭 |
| F-001 | 仅 Internal API 和 Task Worker 使用的 egress 网络 | F-015 | 1 |
| F-018 | 真实 readiness、heartbeat、队列检查、Compose health、preflight | F-001 的最终 Compose 拓扑 | 1 |
| F-012 | 前后端统一的多 Campaign 根上下文 | F-015/F-016 | 2 |
| F-014 | Opportunity 级 approved Prompt Release 显式绑定 | F-012 | 2 |
| F-013 | approved Fact 到 Evidence 的 UI、lineage 和枚举一致性 | F-015 | 2 |
| F-009 | 五类 capture method、平台/surface 和 eligible 强合同 | F-015；复用 F-012 Campaign 规则 | 2 |
| F-011 | 人工发布后的最小 URL 验证闭环 | F-001/F-012/F-014 | 3 |
| F-019 | RAG adapter、事实/实体候选、问题体系和内部仿真 | F-013/F-014/F-009/F-021；F-001 用于外部模型 | 1 PoC，3-4 实施 |
| F-021 | 最小重复采样、分层分母和版本化统计 | F-009 | 3 |
| F-023 | 后端 latest 语义和 Customer Campaign 上下文 | F-012/F-021 | 4 |
| F-027 | 项目/可选 Campaign 的 JSON/CSV 可复核导出 | F-011/F-009/F-021/F-023 | 4 |

## 4. 编码前冻结的合同

以下合同作为本计划的实施默认值。若实施时需要改变，必须先更新决策记录和本计划，不能由单个代码 PR 隐式改变。

### 4.1 Campaign 与错误语义

- `campaign_id` 是 Protocol、Opportunity、Job、Publication、Submission、Observation、Metric 和 Customer 查询的必需根上下文。
- Admin/Customer URL 以 `campaign_id` 保存当前选择；API 在 path/query/body 中显式接收并做复合归属校验。
- 资源不存在、不可见或不属于 path 中的 Project/Campaign：返回 `404`，避免泄露其他范围资源。
- 同一请求显式提交互相冲突的 Campaign/下游 ID：返回 `422 campaign_context_mismatch`。
- 资源归属正确但状态不允许当前动作：返回 `409`。
- 不允许回退到数据库第一条 Campaign、Protocol 或 Destination。

### 4.2 Prompt Release 绑定

- 正式绑定的规范 owner 是 `placement_opportunity_id`，因为 Opportunity 表示某 Campaign 下的实际渠道任务。
- Project 级 `task_key -> release` 只能作为模板目录或人工选择建议，不构成正式生成绑定。
- 既有 Opportunity 迁移为显式 `unbound`，不得自动继承第一条、最新或项目默认 Release。
- 只有 `approved` Release 可以绑定；撤销后不得创建新 Bundle，但历史 Bundle 和历史绑定保持不变。
- Prompt Bundle 冻结 Opportunity、Campaign、Destination、Release ID、Release version 和 hash。

### 4.3 URL verifier v2

- 合同版本固定为 `publication-url-verifier-v2`。
- `required_disclosures` 永远是显式数组；没有披露要求时为 `[]`。
- 允许受控重定向，但最终响应必须为公开可访问的 `2xx` HTML；每跳继续使用现有 SSRF/redirect 校验。
- 正文匹配使用批准版本生成的稳定必需文本片段集合及其规范化 hash，不做模糊语义猜测。
- 目标链接按 scheme/host/default port/path/query 规范化后比较，忽略 fragment。
- 披露按规则版本保存的规范化可见文本匹配。
- 验证结果保存最终 URL、时间、规则版本、检查项、证据 hash 和非敏感失败分类。

### 4.4 Fact 到 Evidence

- 使用权规范值统一为 `public_reference`；现有脚本、fixture 或配置中的 `public_domain` 一次性迁移，所有新输入拒绝该旧值。
- 一个 Project 中同一个 approved Fact 只能对应一个正式 Evidence lineage。
- 重复转换返回已有 Evidence 并明确显示“已存在”，不得静默插入第二条。
- lineage 至少保存 Knowledge source、document、chunk、fact 和 Evidence ID。

### 4.5 观测来源

- 新写入只允许五类 `capture_method`：`official_report_import`、`manual_ui`、`provider_api`、`proxy_grounded_api`、`synthetic`。
- 数据库存储兼容值 `unknown` 只用于历史迁移；API 不允许创建 `unknown`，且该类记录强制 `eligible=false`。
- 平台规范值至少包含 `openai`、`google`、`perplexity`、`microsoft`、`anthropic`、`other`。
- surface 至少包含 `chatgpt_search`、`google_search`、`google_ai_overviews`、`google_ai_mode`、`gemini`、`perplexity_answer`、`bing_copilot`、`claude_ai`、`other`；`other` 必须附说明。
- `synthetic` 只能由服务端受控任务创建。provider/proxy 结果不能标记为消费者 UI 结果。
- 每种 capture method 的必填字段矩阵由 Domain 单点校验，前端隐藏字段不能替代后端约束。
- `official_report_import` 使用独立的 Report Import/Row typed projection，不能伪装成单次
  回答型 Observation；它在页面和导出中保留同一 capture method 标签，但永不进入其他
  回答型来源的逐问题分母。
- 消费者 UI 未披露模型时保存显式 `not_disclosed`，不适用时保存 `not_applicable`；不得
  用 configured model 或猜测值填充 reported model。
- 回答型样本使用同一不可变 `SourceStratumKey`：capture method、platform、surface、
  engine、configured/reported model 状态和值、locale、region、language、device/client、
  search enabled/mode。样本槽和分母都使用该 key 的 canonical hash。

### 4.6 最小统计方法

- 每题每分层预期重复次数不得低于 3；Protocol 可以提高，不能降低。
- 稳定结论所需有效重复数不得低于 3，且不得低于该 Protocol 预期重复数的 80%，向上取整。
- 任一纳入结论的问题未达到门槛时，该分层只能输出 `insufficient_evidence`。
- 二元占比显示 95% Wilson interval；同时显示每题结果范围、最差问题结果、有效/无效数量及无效原因。
- Protocol 必须冻结计划采集的 SourceStratum inventory；即使某个计划分层零采样，也必须
  进入完成度和 `insufficient_evidence` 计算，不能只从已有 Observation 反推分层。
- F-021 直接复用 F-009 的完整 `SourceStratumKey`，再组合冻结的 query cluster；任一维度
  不同都形成独立分层和分母，不得另造缩水键。
- 初始统计方法版本为 `geo-observation-statistics-v2`；规范化输入排序、算法和版本共同生成 SHA-256 input/result hash。
- 方法、门槛或 Protocol 改变时创建新版本，不覆盖旧快照；所有结果继续标明非因果边界。

### 4.7 Customer latest

- Customer 只消费 approved report 及其关联的 immutable Metric Snapshot。
- latest 分区键为 Campaign/Protocol/Measurement Window/完整 `SourceStratumKey` hash/query cluster；不同来源或问题簇保持独立分母，绝不合并。同一分区全序为：`approved_at DESC`、`computed_at DESC`、`report_id DESC`。
- 后端直接返回显式 latest 投影；前端不得用数组 `[0]` 猜测。
- Customer verified URL 只能来自 latest approved Snapshot 冻结的 `verified_destination_ids`；无 approved report 或 legacy Snapshot 缺少冻结目的地集合时返回空。
- Customer 四个模块固定为 `summary`、`metrics`、`placements`、`reports`，统一使用同一 `campaign_id`。
- 无 Campaign、Campaign 无数据、Campaign 无权限分别返回可区分状态，禁止回退到其他 Campaign。

### 4.8 F-019 选型与质量 Gate

- 最小 benchmark corpus：至少 20 份代表性文档，覆盖 HTML、PDF、DOCX、纯文本及产品、竞品、市场三类内容。
- 人工 gold set 至少包含 50 条事实、30 个实体、30 条关系和 40 个覆盖目标维度的问题意图。
- LlamaIndex 与当前项目内基线使用同一语料、模型策略和 gold set；GraphRAG 只允许隔离对比，不直接接入生产。
- 进入生产实现的最低门槛：实体 precision `>= 0.85`、关系 precision `>= 0.80`、正式候选事实来源可追踪率 `= 100%`、无事实支持问题比例 `<= 5%`、语义重复问题比例 `<= 10%`、有证据支撑的计划维度覆盖率 `>= 90%`。
- 项目间数据泄漏、候选绕过人工批准、`test_only` 产物变为可发布，三类测试必须零失败。
- benchmark manifest 必须记录每个候选的输入/输出 token、模型调用数、估算成本和墙钟时间，但这些指标不设置固定或相对基线硬上限，也不单独淘汰质量更好的方案。
- 继续保留单 Job 调用预算、网络/任务超时和人工中止能力，防止循环或失控；这些是运行保护，不是选型成本门槛。
- 候选先通过本节全部质量硬门槛，再按实体、关系、问题支持度、覆盖度和去重结果的综合质量选择；质量差距小于 2 个百分点时才以成本和耗时作为次级条件，仍相同时优先 LlamaIndex。
- 框架版本固定；框架类型不得进入 Domain、稳定 API 或业务主数据。

### 4.9 Runtime truth 默认阈值

- readiness 单依赖超时 2 秒，整个探针预算 5 秒；只做无写入检查。
- Worker/Relay 默认每 10 秒 heartbeat，30 秒未更新即 stale；阈值可配置，但生产示例和运行手册必须一致。
- queued/retry 默认 10 分钟未推进为异常；running/finalizing 超过 lease expiry 加 60 秒为异常；未投递 Outbox 超过 5 分钟为异常；expired lease、dead-letter 和 terminal failure 立即报告。
- 阈值只能通过显式配置调整，运维检查必须同时输出实际阈值，不能硬编码后静默变化。
- Customer API readiness 只检查 PostgreSQL；Internal API 检查 PostgreSQL、Valkey 和 MinIO。

### 4.10 Acceptance 隔离

- `inline_isolated` 使用独立数据库、独立 Valkey namespace/实例和独立对象存储 bucket；共享 Worker/Relay 没有该环境的凭据。
- 仅有 run ID 或 heartbeat 空窗不能证明隔离。
- 无法证明端点和凭据隔离时，acceptance 在创建数据前拒绝启动。
- 报告必须记录 `execution_mode=inline_isolated`、run ID、受控 adapter 清单和环境指纹。

### 4.11 导出格式

- 导出包为 ZIP，至少包含 `manifest.json`、`data.json`、`protocols.csv`、`queries.csv`、`observations.csv`、`citations.csv`、`metric_snapshots.csv`、`approved_reports.csv`、`verified_urls.csv` 和 `lineage.csv`。
- JSON 保留类型和嵌套；CSV 使用 UTF-8、稳定列顺序、RFC 4180 转义和 ISO 8601 UTC 时间。
- manifest 记录 schema version、Project/Campaign filter、生成时间、每个文件记录数、SHA-256、metric method version 和不可复算字段说明。
- 初始 schema version 为 `geo-project-export-v1`；Customer 导出使用独立字段白名单，不包含原始 Prompt、内部 raw response、未批准报告或内部身份字段。

## 5. 实施批次

### 批次 0：交付真实性底座

范围：`F-015`、`F-016`，启动 `F-025`。

实施内容：

1. 修正 migration ledger、model call log 和 Worker/Outbox 当前已知受污染断言。
2. 为必需 integration 显式提供 App、Worker、Admin 数据库 URL；缺失时在 pytest 之前失败。
3. 修正 DeepSeek `live` marker 和显式 opt-in，保证 `make deepseek-live` 不会零收集。
4. CI 输出 collected、passed、failed、skipped；必需测试意外 skip 或零收集为失败。
5. acceptance 改为独立环境的 `inline_isolated`，报告冻结执行模式和 adapter。
6. 建立本文件第 6 节的验收追踪表，并建立单 Chromium 桌面测试入口。

批次退出条件：

- 必需 integration 实际执行，无意外 skip 或零收集。
- 相同数据库连续和并行运行不跨 run 读取、领取或断言数据。
- 共享 Worker/Relay 无法隔离时 acceptance 在写数据前拒绝启动。
- 普通 PR 明确报告未请求付费调用；显式 live target 至少收集目标测试。
- Chromium 测试入口可以执行，暂不要求所有后续功能 spec 已存在。

### 批次 1：运行拓扑与 RAG 选型准备

范围：`F-001`、`F-018`；启动 `F-019` benchmark/PoC。

实施顺序：

1. 先冻结生产 Compose 网络：仅 Internal API 和 Task Worker 加入 egress。
2. 再接入 API readiness、Worker/Relay heartbeat、队列卡滞检查和 Compose healthcheck。
3. 增加生产配置 preflight，移除或禁用虚假 Prometheus scrape target。
4. 并行建立 F-019 corpus、gold set、benchmark manifest 和项目自有 adapter PoC，不改业务主数据。

批次退出条件：

- backend-only 服务不能外连；Internal API/Task Worker 可访问受控外部 fixture；数据服务无新入站、无 egress。
- PostgreSQL/Valkey/MinIO 故障按 API surface 正确影响 `/ready`，不影响 `/health` 表达进程存活。
- Worker/Relay 停止后在阈值内 stale；队列、lease、Outbox 和 dead-letter fixture 能被准确分类。
- Compose 显示真实 unhealthy；坏 secret/digest/config 被 preflight 阻断且不泄密。
- 仓库不再启用不存在的 `/metrics` target。
- F-019 benchmark 数据集、质量评分规则和成本/耗时记录格式已冻结；PoC 尚不能被描述为正式功能完成。

### 批次 2：共享领域合同

范围：`F-012`、`F-014`、`F-013`、`F-009`。

并行工作线：

1. Campaign/Prompt 线：先让后端对所有下游资源做 Campaign 归属校验，再改 Admin URL、selector、动作 payload 和 Opportunity Prompt 绑定。
2. Knowledge/Evidence 线：统一 `public_reference`，增加 Fact lineage、幂等转换命令和最小 UI。
3. Observation 线：增加 capture method、platform/surface、运行参数、原始工件和 eligibility 强约束。

合入约束：

- Alembic 只有一个 owner，建议顺序为 `runtime_truth`、`campaign_prompt_context`、`knowledge_evidence_lineage`、`observation_source_contract`。
- Monitoring Domain/API 由 F-009 owner 持有，后续 F-021/F-023 接续，避免并行改同一合同。
- 每条线完成迁移、Domain、API、OpenAPI、前端和行为测试后才算完成，不以 UI 出现字段作为完成证据。

批次退出条件：

- 2 Project x 2 Campaign x 每 Campaign 2 Destination fixture 的跨范围读写全部拒绝。
- Opportunity 只能显式绑定 approved Release，历史绑定不漂移，未绑定不能生成正式 Bundle。
- approved Fact 可从 UI 创建或复用带完整 lineage 的 Evidence，并进入现有 Evidence Pack。
- 五类 capture method 各有 fixture；缺原始证据或关键参数一律 ineligible。
- 历史未知观测迁移为 `unknown/ineligible`，不被静默升级为真实数据。

### 批次 3：发布、RAG 核心与统计

范围：`F-011`、`F-019` 核心、`F-021`。

并行工作线：

1. 发布线：实现 verifier v2、验证证据持久化和只重跑 verifier 的显式重试。
2. RAG 核心线：先通过选型 Gate，再实现 adapter、候选事实/实体/关系、来源 lineage、增量/删除/去重和 Worker 集成。
3. 统计线：实现 Protocol 重复门槛、分层分母、`insufficient_evidence`、区间/波动、最差结果和 method version/hash。

批次退出条件：

- 正确人工发布页面验证成功；错误 URL、正文、链接、披露和非公开页面均明确失败。
- verifier 重试不产生新模型调用或新生成工件。
- F-019 达到第 4.8 节量化阈值；PostgreSQL 仍是业务真源，框架类型不泄漏。
- RAG 重复导入、增量更新和删除可复核；两个 Project 零串数据。
- sample size 1 或低于门槛只能得到 `insufficient_evidence`。
- 不同来源、引擎、模型、locale、region、query cluster 不合并分母；相同输入可重复得到相同 hash。

### 批次 4：问题/仿真、Customer 与导出

范围：完成 `F-019`，实施 `F-023`、`F-027`。

实施顺序：

1. F-019 在核心候选之上完成问题簇、fan-out、多轮候选、去重、覆盖、批准、冻结 QuestionSet 和 Protocol 绑定。
2. 内部仿真复用 approved Prompt Release 和 F-009 synthetic 合同，数据库与 API 双重保证不可发布。
3. F-023 后端先定义 latest 投影和 Campaign 权限，再实现 Customer selector、四模块和全部链接。
4. F-027 在上游 schema 稳定后完成 Admin/Customer 导出、manifest、hash 和 KPI 复算。

批次退出条件：

- QuestionSet 只有人工批准后才能冻结并绑定 Protocol；版本不可被静默覆盖。
- 内部仿真始终为 `test_only=true`、`publication_eligible=false`，不能进入真实观测分母或创建发布对象。
- 乱序插入多 Campaign/Protocol/window/version 后，Customer 四模块始终使用选定 Campaign 的明确 latest。
- 切换、刷新、返回和深链保留 Campaign；无权限、无数据和无 Campaign 不静默回退。
- Admin 可导出 Project/可选 Campaign；Customer 只能导出选定 Campaign 的批准数据。
- 文件计数/hash 正确，导出包可以独立复算三项约定 KPI。

### 批次 5：统一生产等价验收

范围：关闭 `F-025`，对全部 14 项做最终验收，不新增功能。

执行顺序：

1. 从受支持旧 schema 执行 upgrade，核对历史数据回填和 Alembic 单 head。
2. 执行快速质量、单元、架构、OpenAPI、Web build 和全部必需 PostgreSQL integration。
3. 执行 Admin 9 条、Customer 4 条 Chromium 桌面必需流程。
4. 执行 `inline_isolated` acceptance，并在报告中明确它不证明真实 Worker/Relay 拓扑。
5. 在生产等价 Compose 执行 egress、readiness、heartbeat、队列卡滞、preflight 和数据服务网络负向测试。
6. 在显式授权的 staging 执行真实 OIDC/JWKS、Knowledge URL、一次真实模型调用和公开发布 URL 验证。该步骤的命令和拒绝/脱敏合同已实现并测试；截至 2026-07-19 未获外部及付费调用授权，未执行真实 staging 请求。

最终退出条件：

- 第 6 节每一条验收标准至少映射一个自动化行为测试，且全部通过。
- staging 外部 smoke 的证据与 inline acceptance 分开保存、分开描述。
- 无必需测试 skip、零收集、跨 run 污染或只靠源码字符串断言的关键场景。
- 未实施的风险接受、延后和下一阶段能力没有被误报为完成。

## 6. 逐项验收标准与测试清单

以下测试 ID 是计划中的稳定追踪 ID；实施时可映射到具体 pytest node、Playwright spec 或基础设施脚本，但不得删除验收语义。

### F-015：CI 真实性

验收标准：

- [x] `F015-AC1` 必需 integration 缺环境、零收集、意外 skip 或失败时 Job 非零退出。
- [x] `F015-AC2` migration ledger、model log、Outbox 三类当前已知污染问题修正。
- [x] `F015-AC3` 同库连续或并行 run 不读取或消费其他 run 数据。
- [x] `F015-AC4` 普通 PR 不付费；显式 live target 至少收集目标测试。

测试清单：

- `F015-CI-01`：CI 环境预检缺任一 App/Worker/Admin URL 时在 pytest 前失败。
- `F015-CI-02`：JUnit/摘要断言必需 suite 的 collected/passed/failed/skipped 数量。
- `F015-INT-01`：migration ledger、model call、Outbox 测试连续运行两次。
- `F015-INT-02`：两个 run 并行创建 Project/Job/Outbox，断言领取和统计隔离。
- `F015-LIVE-01`：`--collect-only -m live` 至少一个 node；未 opt-in 明确报告不执行，opt-in 后执行目标 node。

### F-016：inline-only acceptance

验收标准：

- [x] `F016-AC1` 无法证明与共享 Worker/Relay 隔离时，在创建数据前拒绝运行。
- [x] `F016-AC2` 重复/并行运行无重复工件、错误 claim 或跨 run Outbox。
- [x] `F016-AC3` 报告明确记录 `inline_isolated` 和受控 adapter，不能被解释为生产拓扑验收。

测试清单：

- `F016-UNIT-01`：共享端点/凭据检测和隔离配置校验。
- `F016-INT-01`：独立数据库、队列 namespace、bucket 下连续与并行 acceptance。
- `F016-INT-02`：重复终态查询不创建第二份工件。
- `F016-CONTRACT-01`：报告 schema 固定 execution mode、run ID、adapter 和环境指纹。

### F-025：行为测试门禁

验收标准：

- [x] `F025-AC1` 所有 ACCEPTED 验收条款均映射到自动化行为测试。
- [x] `F025-AC2` 权限、幂等、失败和跨 Campaign 场景不以源码字符串断言作为唯一证据。
- [x] `F025-AC3` CI 明确报告执行/跳过，必需环境缺失不能假绿。
- [x] `F025-AC4` 不建立覆盖率百分比、跨浏览器、移动端或无关补测门槛。

测试清单：

- `F025-MAP-01`：机器检查本节所有 `Fxxx-ACn` 都有至少一个测试 ID/pytest node 映射。
- `F025-WEB-01`：Chromium Admin Campaign/Prompt/Publication 流程。
- `F025-WEB-02`：Chromium Knowledge/Fact/Evidence/RAG 流程。
- `F025-WEB-03`：Chromium Monitoring/Statistics/Export 流程。
- `F025-WEB-04`：Chromium Customer Campaign 四模块流程。
- `F025-CONTRACT-01`：普通 CI 不引入全仓覆盖率百分比、跨浏览器、移动端或读屏硬门槛。

### F-001：受控 egress

验收标准：

- [x] `F001-AC1` Internal API 可完成 OIDC/JWKS 和允许的 Knowledge URL 请求。
- [x] `F001-AC2` Task Worker 可完成模型调用和发布 URL 验证。
- [x] `F001-AC3` Postgres、Valkey、MinIO 不接 egress、无新增宿主入站。
- [x] `F001-AC4` 未接 egress 的后端服务仍不能直接外连。

测试清单：

- `F001-INFRA-01`：解析 Compose 服务网络和 ports 的静态负向合同。
- `F001-INFRA-02`：backend-only 探针访问受控外部 fixture 失败，egress 探针成功。
- `F001-INT-01`：本地 JWKS、Knowledge URL、publication URL、model HTTP fixture 四类请求。
- `F001-STAGE-01`：显式 staging OIDC/JWKS、真实模型和公开 URL smoke；不进入普通 PR。

### F-018：运行真实性

验收标准：

- [x] `F018-AC1` PostgreSQL 故障使相关 `/ready` 失败，而 `/health` 仍表达进程存活。
- [x] `F018-AC2` Internal API 因 Valkey/MinIO 故障失败；Customer API 不因无关依赖下线。
- [x] `F018-AC3` Worker/Relay 停止后按阈值 stale。
- [x] `F018-AC4` queued/retry/running/finalizing/lease/Outbox/dead-letter 异常被分类并非零退出。
- [x] `F018-AC5` Compose health 与探针一致。
- [x] `F018-AC6` 空 secret、占位/非 digest 镜像及缺配置被 preflight 阻断。
- [x] `F018-AC7` 不再启用虚假 Prometheus target。
- [x] `F018-AC8` 探针、日志和错误不泄露敏感正文或凭据。

测试清单：

- `F018-UNIT-01`：surface 依赖矩阵、timeout、heartbeat/stale、卡滞阈值。
- `F018-INT-01`：分别停止 PostgreSQL、Valkey、MinIO 并断言两个 API 的差异。
- `F018-INT-02`：停止 Worker/Relay 并等待 stale；构造六类队列/lease/Outbox 状态。
- `F018-INFRA-01`：运行中 Compose 实际变为 healthy/unhealthy，而非只检查 YAML 字符串。
- `F018-PREFLIGHT-01`：错误配置矩阵及输出脱敏扫描。
- `F018-CONTRACT-01`：Prometheus 配置和文档不再声明不存在的 endpoint。

### F-012：多 Campaign 上下文

验收标准：

- [x] `F012-AC1` 使用至少 2 Campaign x 每 Campaign 2 Destination fixture。
- [x] `F012-AC2` 切换 Campaign 清除全部旧下游参数和状态。
- [x] `F012-AC3` 跨 Campaign read/mutation 被后端拒绝且零写入。
- [x] `F012-AC4` 页面、URL、payload 和数据库写入始终属于当前 Campaign。
- [x] `F012-AC5` 返回、刷新、深链不恢复旧 Campaign 下游上下文。

测试清单：

- `F012-DOMAIN-01`：Protocol/Destination/Opportunity/Job/Publication/Submission 归属矩阵。
- `F012-INT-01`：跨 Campaign ID 逐类 read/mutation 的 404/422/409 合同及零副作用。
- `F012-WEB-01`：Chromium 切换、动作 payload、刷新、返回和深链。
- `F012-REG-01`：禁止 first Campaign/Protocol fallback 的回归 fixture。

### F-014：Opportunity Prompt Release

验收标准：

- [x] `F014-AC1` 九个渠道可分别绑定 Release，生成记录的 ID/version/hash 一致。
- [x] `F014-AC2` unbound、非 approved、撤销或跨 Campaign Release 不能生成正式 Bundle。
- [x] `F014-AC3` 新 Release 不改变历史绑定或 Bundle。
- [x] `F014-AC4` 重复渠道、blocked Destination、缺 Prompt/Evidence 不计入就绪度。
- [x] `F014-AC5` 生成前操作者可见并确认实际 Release。

测试清单：

- `F014-DOMAIN-01`：Release 状态、Opportunity owner、历史不可变规则。
- `F014-INT-01`：九渠道不同绑定生成 Bundle 并核对 frozen identity/hash。
- `F014-INT-02`：unbound/draft/revoked/cross-Campaign/blocked/duplicate 负向矩阵。
- `F014-WEB-01`：Chromium 选择、确认、生成和新 Release 不漂移。

### F-013：Fact 到 Evidence

验收标准：

- [x] `F013-AC1` approved Fact 可完全通过 UI 创建或复用 Evidence。
- [x] `F013-AC2` 未批准、缺元数据或无权限成员不能创建。
- [x] `F013-AC3` Evidence 可进入现有 Evidence Pack。
- [x] `F013-AC4` 可追踪到 source/document/chunk/fact。
- [x] `F013-AC5` 前端、API、Domain、数据库和脚本统一 `public_reference`。

测试清单：

- `F013-DOMAIN-01`：Fact 状态、必填元数据、枚举和幂等规则。
- `F013-INT-01`：PostgreSQL/MinIO lineage、重复转换和 Evidence Pack 接入。
- `F013-INT-02`：未批准、越权、跨项目、缺元数据负向矩阵。
- `F013-WEB-01`：Chromium Fact -> Evidence -> Evidence Pack -> 来源回溯。

### F-009：观测来源真实性

验收标准：

- [x] `F009-AC1` 五类 capture method 各有 fixture，页面和导出显示来源标签。
- [x] `F009-AC2` 缺原始回答/工件、来源或关键参数时后端拒绝 eligible。
- [x] `F009-AC3` synthetic/provider/manual 等来源不进入彼此 KPI 分母。
- [x] `F009-AC4` Bing/Copilot 和 Claude 不再错误落入 `other`。
- [x] `F009-AC5` 历史未知来源迁移为 `unknown/ineligible`。

测试清单：

- `F009-DOMAIN-01`：capture method/platform/surface 枚举及逐方法必填矩阵。
- `F009-INT-01`：五类来源保存原始证据、引用顺序和运行参数。
- `F009-INT-02`：缺字段、伪造 synthetic/official、API 冒充消费者 UI 的负向矩阵。
- `F009-MIG-01`：历史数据回填保持 ineligible。
- `F009-WEB-01`：Admin 来源标签和 surface 选择；导出标签一致。

### F-011：人工发布结果验证

验收标准：

- [x] `F011-AC1` 空披露列表可通过，不再因缺字段进入 `retry_wait`。
- [x] `F011-AC2` 缺必要披露时明确失败。
- [x] `F011-AC3` 错误/非公开 URL、正文不符、缺链接均失败。
- [x] `F011-AC4` 正确人工页面成功并保存版本化验证证据。
- [x] `F011-AC5` 重试不触发模型生成。

测试清单：

- `F011-UNIT-01`：2xx、redirect、正文片段/hash、链接规范化、披露和失败分类。
- `F011-CONTRACT-01`：Publication 到 Worker 的 `required_disclosures` 始终存在。
- `F011-INT-01`：PostgreSQL 保存规则版本、时间、检查项、证据和失败原因。
- `F011-INT-02`：重试前后按 Project/Job/run 断言 model call 数量不变。
- `F011-WEB-01`：Chromium 录入 URL、查看失败、人工修正、显式重试和成功。

### F-021：最小统计正确性

验收标准：

- [x] `F021-AC1` 单样本或低于冻结门槛只能输出 `insufficient_evidence`。
- [x] `F021-AC2` engine/model/capture/locale/region/query cluster 不跨层合并。
- [x] `F021-AC3` 显示完成度、无效原因、区间/波动、最差结果和 confounders。
- [x] `F021-AC4` 同一冻结输入和 method version 得到相同结果/hash。
- [x] `F021-AC5` Protocol、门槛或方法变更创建新版本，历史报告不变。

测试清单：

- `F021-UNIT-01`：1/2/3/更多重复样本的状态边界与 80% 门槛。
- `F021-UNIT-02`：Wilson interval、最差问题、invalid reason 和 canonical hash golden cases。
- `F021-INT-01`：所有分层维度的独立分母及不可变快照。
- `F021-INT-02`：相同输入重算和 method/protocol 变更新版本。
- `F021-WEB-01`：样本不足不显示提升/下降/稳定，完整结果显示统计上下文。

### F-019：RAG 核心与内部仿真

验收标准：

- [x] `F019-AC1` 同一 corpus/gold set 的选型报告满足第 4.8 节阈值和预算。
- [x] `F019-AC2` Knowledge/Catalog/Evidence/PostgreSQL 是唯一业务真源，框架类型不泄漏。
- [x] `F019-AC3` 候选事实、实体、关系、问题必须保留来源并经人工批准。
- [x] `F019-AC4` 重复导入、增量更新和删除行为幂等可复核。
- [x] `F019-AC5` 两个 Project 零数据泄漏。
- [x] `F019-AC6` 问题支持去重、覆盖、批准、冻结版本和 Protocol 绑定。
- [x] `F019-AC7` 仿真始终 `test_only=true`、`publication_eligible=false`，不进入真实 KPI。
- [x] `F019-AC8` 复用现有 Worker、gateway、模型日志、MinIO 和 pgvector，不出现平行基础设施。

测试清单：

- `F019-BENCH-01`：实体/关系 precision、事实追踪、问题覆盖/重复/无依据、成本和耗时 scorecard。
- `F019-ARCH-01`：adapter 边界和依赖扫描，禁止 LlamaIndex/GraphRAG 类型进入 Domain/API。
- `F019-INT-01`：Knowledge Worker + PostgreSQL + MinIO/pgvector 的导入、增量、删除、重导。
- `F019-INT-02`：两个 Project 使用相似内容的隔离与权限负向测试。
- `F019-INT-03`：候选批准、QuestionSet 冻结、Protocol 绑定和不可变版本。
- `F019-WEB-01`：Chromium 问题管理与内部仿真流程。
- `F019-REG-01`：synthetic 不进入真实分母、不生成 Publication/Submission。

### F-023：Customer latest 与 Campaign

验收标准：

- [x] `F023-AC1` 乱序插入至少 2 Campaign、多 Protocol/window/version。
- [x] `F023-AC2` Customer 四模块显示选定 Campaign 的 latest approved 版本。
- [x] `F023-AC3` 切换、刷新、返回和深链不丢失或串用 Campaign。
- [x] `F023-AC4` 无权限/跨项目 Campaign 被 API 拒绝且不回退。

测试清单：

- `F023-UNIT-01`：approved_at/computed_at/report_id 全序的乱序选择。
- `F023-INT-01`：Campaign/Protocol/window/version 组合及 Customer 字段可见性。
- `F023-INT-02`：无 Campaign、无数据、无权限、跨项目四类状态。
- `F023-WEB-01`：Chromium summary/metrics/placements/reports 的切换、刷新、返回、深链。

### F-027：项目 JSON/CSV 导出

验收标准：

- [x] `F027-AC1` Admin 下载 Project/指定 Campaign 的 JSON 和 CSV 包。
- [x] `F027-AC2` Customer 只导出有权查看的已批准只读数据。
- [x] `F027-AC3` manifest 记录数和 hash 与文件一致。
- [x] `F027-AC4` 导出数据可复算 recommendation share、mention share、verified citation rate。
- [x] `F027-AC5` 多 Project、多 Campaign 零越界或串数据。

测试清单：

- `F027-UNIT-01`：JSON 类型、CSV 列序/转义、manifest canonical hash。
- `F027-INT-01`：Admin Project/Campaign 范围和 Customer approved-only/RLS。
- `F027-INT-02`：多 Project/Campaign 导出数据隔离及内部字段负向断言。
- `F027-RECALC-01`：独立脚本从导出包复算三项 KPI 并核对 method version。
- `F027-WEB-01`：Chromium Admin/Customer 下载和过滤范围确认。

### 6.1 验收追踪矩阵

| 整改项 | 验收条款到测试 ID 的映射 |
|---|---|
| F-015 | AC1 -> `F015-CI-01/02`；AC2 -> `F015-INT-01`；AC3 -> `F015-INT-02`；AC4 -> `F015-LIVE-01` |
| F-016 | AC1 -> `F016-UNIT-01`；AC2 -> `F016-INT-01/02`；AC3 -> `F016-CONTRACT-01` |
| F-025 | AC1 -> `F025-MAP-01`；AC2 -> `F025-WEB-01/02/03/04` 及各项负向 integration；AC3 -> `F015-CI-01/02`；AC4 -> `F025-CONTRACT-01` |
| F-001 | AC1/AC2 -> `F001-INT-01`、`F001-STAGE-01`；AC3/AC4 -> `F001-INFRA-01/02` |
| F-018 | AC1/AC2 -> `F018-INT-01`；AC3/AC4 -> `F018-INT-02`；AC5 -> `F018-INFRA-01`；AC6 -> `F018-PREFLIGHT-01`；AC7 -> `F018-CONTRACT-01`；AC8 -> `F018-PREFLIGHT-01` 的脱敏扫描 |
| F-012 | AC1 -> `F012-INT-01` fixture；AC2/AC4/AC5 -> `F012-WEB-01`；AC3 -> `F012-DOMAIN-01`、`F012-INT-01`；first fallback 回归 -> `F012-REG-01` |
| F-014 | AC1 -> `F014-INT-01`；AC2/AC4 -> `F014-INT-02`；AC3 -> `F014-DOMAIN-01`、`F014-WEB-01`；AC5 -> `F014-WEB-01` |
| F-013 | AC1 -> `F013-WEB-01`；AC2 -> `F013-INT-02`；AC3/AC4 -> `F013-INT-01`；AC5 -> `F013-DOMAIN-01` |
| F-009 | AC1 -> `F009-INT-01`、`F009-WEB-01`；AC2/AC3 -> `F009-INT-02`；AC4 -> `F009-DOMAIN-01`、`F009-WEB-01`；AC5 -> `F009-MIG-01` |
| F-011 | AC1/AC2/AC3 -> `F011-UNIT-01`、`F011-CONTRACT-01`；AC4 -> `F011-INT-01`、`F011-WEB-01`；AC5 -> `F011-INT-02` |
| F-021 | AC1 -> `F021-UNIT-01`；AC2 -> `F021-INT-01`；AC3 -> `F021-UNIT-02`、`F021-WEB-01`；AC4 -> `F021-UNIT-02`、`F021-INT-02`；AC5 -> `F021-INT-02` |
| F-019 | AC1 -> `F019-BENCH-01`；AC2/AC8 -> `F019-ARCH-01`、`F019-INT-01`；AC3/AC6 -> `F019-INT-03`、`F019-WEB-01`；AC4 -> `F019-INT-01`；AC5 -> `F019-INT-02`；AC7 -> `F019-REG-01` |
| F-023 | AC1/AC2 -> `F023-UNIT-01`、`F023-INT-01`；AC3 -> `F023-WEB-01`；AC4 -> `F023-INT-02` |
| F-027 | AC1 -> `F027-WEB-01`；AC2/AC5 -> `F027-INT-01/02`；AC3 -> `F027-UNIT-01`；AC4 -> `F027-RECALC-01` |

`F025-CONTRACT-01` 检查普通 CI 没有新增全仓覆盖率百分比、跨浏览器、移动端或读屏硬门槛；它不阻止团队自愿运行这些测试。

## 7. 测试目标与发布门禁

### 7.1 普通 PR 必须执行

现有目标继续保留：

```bash
make quality
make test-migrated
make openapi-contracts
make web-build
```

计划新增或收紧的目标：

```text
make test-integration-required   # 必需 PostgreSQL integration，零收集/意外 skip 失败
make test-browser-chromium       # 单浏览器、桌面、四条核心流程
make geo-acceptance-inline       # 只允许 inline_isolated
make test-infra-contracts        # Compose/preflight 静态合同
```

普通 PR 不执行真实付费模型调用，不以 deterministic adapter 证明真实外部供应商或生产拓扑可用。

### 7.2 批次 5 生产等价门禁

```text
make test-infra-runtime          # 生产等价 Compose 网络、ready、heartbeat、unhealthy
make production-preflight       # 真实生产配置文件，仅输出字段名，不输出值
make deepseek-live               # 显式授权，至少收集并执行目标测试
make geo-staging-smoke           # OIDC/JWKS、Knowledge URL、model、publication URL
```

这些命令均已实现。`test-infra-runtime`、本地受控 fixture 和 `inline_isolated` 已执行；`deepseek-live` 与 `geo-staging-smoke` 仍要求显式外部/付费授权，本轮未执行。staging/live 证据必须继续与普通 CI、inline acceptance 分开保存。

### 7.3 每批统一门禁

每个批次合入前必须满足：

1. Alembic 只有一个 head，upgrade 和旧数据回填通过。
2. Domain、API、OpenAPI、Web types 和前端使用同一合同。
3. 本批所有 `AC` 条款存在自动行为测试映射。
4. 权限、幂等、跨 Campaign、失败路径不能只有源码字符串测试。
5. 快速测试、必需 integration、Chromium 相关 spec 和构建全部通过。
6. 文档说明真实能力边界，不把 inline/synthetic/PoC 描述为生产或真实外部效果。

## 8. 合并与并行约束

- `infra/compose.prod.yml`、production env、Prometheus 和 runtime health 由 F-001/F-018 单一 owner 维护。
- `infra/db/alembic` 始终单主干串行；并行功能可以先写 Domain/测试，不得各自制造 Alembic head。
- Monitoring schema/Domain/API 按 F-009 -> F-021 -> F-023 顺序由同一 owner 链合入。
- Placement schema/repository/Admin shared data 按 F-012 -> F-014 -> F-011 顺序合入。
- Knowledge/Evidence 按 F-013 -> F-019 顺序合入。
- Stable OpenAPI snapshot、Web types/client 在每批末统一生成，不由并行分支手工竞争修改。
- F-027 不复用现有“单篇文案 Package export”语义；可以复用 Durable Job、MinIO 和 artifact finalization，但项目数据导出保持独立 bounded context。
- 所有迁移优先采用 expand/backfill/enforce；不得以删除历史数据解决兼容问题。

## 9. 明确排除的范围

本计划不实施以下项目：

- `ACCEPTED_RISK`：F-002、F-003、F-004、F-026。
- `MANUAL_WORKAROUND`：F-005、F-006 的本阶段处置。
- `OUT_OF_SCOPE`：F-008。
- `DEFERRED`：F-007、F-010、F-017、F-020、F-022、F-024。
- 下一阶段完整平台：连接器平台、自动跨引擎采集、完整实验告警、业务归因、可解释建议。

同时不因本计划顺带建设 CMS 自动发布、Google/Bing 消费者 UI 抓取、完整 OTel/Grafana/Alertmanager、全仓覆盖率、跨浏览器/移动端/读屏矩阵、Neo4j、RAGFlow 或第二套 Knowledge 管理 UI。

## 10. 完成定义

单个整改只能在以下条件全部满足后标记完成：

1. 决策记录中的实施范围已经交付，明确排除项没有被扩入。
2. 本文件对应 `AC` 条款全部通过。
3. 自动化测试真实执行且无意外 skip、零收集或共享数据污染。
4. OpenAPI、Web types、运行手册和能力边界同步。
5. 相关迁移可从受支持旧版本升级，历史未知数据不被伪造为有效数据。
6. 运行证据区分 deterministic、synthetic、manual UI、provider API、真实 staging 和生产等价拓扑。

14 个 `ACCEPTED` 项的代码、70 条本地验收标准和 F-025 追踪矩阵已经闭合。真实外部 staging smoke 和客户生产部署是独立的发布证据；执行前不得把当前状态提升为外部环境或生产验证完成。
