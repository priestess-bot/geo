# GEO 加速实施路线图（原六个月基线）

> 计划日期：2026-07-21
> 修订日期：2026-07-24（第 65 次修订）
> 计划状态：`PLANNED`
> 计划周期：`T+0` 至 `T+5` 连续交付日；`M0`--`M6` 保留为稳定 Gate 标签，不再表示自然月或人类团队月度排期
> 决策来源：[README 下一阶段发展目标](../../README.md#下一阶段发展目标)、[GEO 效果优先整改决策记录](../audits/GEO-effect-first-remediation-decisions-2026-07-18.md#6-c-组效果测量判断和优化)
> 当前能力来源：[F-019 RAG 核心集成合同](F019-core-integration-contract-2026-07-19.md)、[F-019 QuestionSet/Protocol/Simulation 合同](F019-question-set-protocol-simulation-contract-2026-07-19.md)
> 专项实施计划：[外部数据与跨引擎采样实施计划](GEO-external-data-cross-engine-sampling-implementation-plan-2026-07-22.md)
> 范围变更：按 2026-07-22 用户决定，将 Google AI Overviews/AI Mode、Bing Copilot 及其他获准消费者 AI 界面自动采样纳入本阶段重点；本路线图中的新边界取代本文件初版的排除项，既有审计决策保留为历史依据
> 第 2 次修订变更：引入授权双轨完成定义和第 2 月授权决策点（第 2.4 节）；一方事件入口升级为归因主来源，GA4 降级为聚合对账（第 6.3 节）；风格采集渠道纳入与消费者 surface 对称的授权门槛并增加人工样本导入路径（第 5.2 节）；出口验证改为 Session 级语义并新增吞吐预算合同（第 7.1/7.2.2 节）；`reference_translation` 移出首批交付；供应商存储/保留条款纳入 adapter release 合同（第 4.2 节）
> 第 3 次修订变更：闭合在线迁移追尾、Secret/备份恢复、真实归因、统计不确定结论、逐 Surface Release 保真度、粘性代理证明、登录工件治理、人力容量、建议失效传播和性能负载门禁
> 第 4 次修订变更：增加执行基线、阶段状态、DoR/DoD、RACI、稳定验收 ID 和逐月 checklist；将“外部数据与跨引擎采样”的工作分解、适配器发布与逐源验收移入独立专项文件，主路线图只保留全局合同、阶段依赖和统一发布 Gate
> 第 5 次修订变更：按工作包类型限定 DoR/DoD 并增加可审计 `not_applicable`；将实际出口验证从 Task/分母身份移到 Attempt/Observation lineage；冻结授权先于 live enqueue；增加外部投影独立数据批准生命周期；补齐单项 evidence manifest 溯源字段
> 第 6 次修订变更：增加当前实现状态账本（第 16 节）。本账本不改变原始验收门槛，不以代码或 mock 代替 evidence manifest、独立 verifier、真实账号、授权或 live staging 证据；本轮实施暂不执行工作流 B，相关条目保持显式 `EXCLUDED_B_FOR_CURRENT_ITERATION`
> 第 7 次修订变更：补全第 2--8 节叙述性合同的稳定 checklist、最早批次、专项计划映射和最终 Gate 关系；避免共享/合成/统计/建议合同只在正文出现而没有可审计完成项
> 第 8 次修订变更：将 Workflow C 告警人工处置收敛到 `0039` 的项目范围数据库命令，原子写入 disposition、三通道通知、Durable Job 与 outbox；实施账本保留其余统计、采样和 live 验收缺口
> 第 9 次修订变更：将 Workflow C Sampling 的 frozen Suite input 与 Suite 创建收敛到 `0040` 的项目范围命令；新增 Python/SQL 一致的 C-collation canonical JSON helper，避免数据库 locale 改变 frozen hash。Run reservation、Task/Attempt producer、完整 API 组合和 live 验收仍保持未完成
> 第 10 次修订变更：将 Workflow C Sampling 的 Run reservation 与完整 Task 分母物化收敛到 `0041` 的项目范围命令；同一 admission policy 行串行化 active reservation 配额检查，Run 单独持久化 `reserved/consumed/released` 计数，避免将预留和实际 Attempt 消费混为一谈。Attempt/Job producer、取消、lease/fence 和 live 验收仍保持未完成
> 第 11 次修订变更：将首个 Provider Sampling Attempt 的 frozen spec、Run reservation consumption、UTC daily usage、Durable Job、immutable Job Spec、broker outbox、enqueue event 和 command replay 收敛到 `0042` 的单一项目范围事务；`0043` 再将 Durable Job 的首次 claim/retry claim 原子投影为 Attempt/Task 的 `running` 状态和版本。隔离 PostgreSQL 已验证 `queued -> running -> retry_wait -> running`、RLS 和 fencing generation；手工 Attempt producer、取消/预留释放、MinIO 证据及真实 Provider canary 仍未完成。
> 第 12 次修订变更：`0044` 将 Provider Attempt/Run 取消收敛到项目范围 RPC 与 Durable Job 终态触发器；排队 Job 立即终结并同步 Attempt/Task，运行中 Job 仅进入 `cancel_requested`，由持有 lease 的 Worker 终结后收敛。Run 只释放从未消费的预留。Task 的物化 ID 改为 `run_id + stable task_key`，允许同一 frozen Suite 在释放额度后安全重跑；旧 identity ID 仅为既有行读取兼容。隔离 PostgreSQL 已覆盖 queue/running cancellation、replay、lease fencing、`head -> 0039 -> head` 和重跑主键隔离；手工 producer、MinIO 证据及真实 Provider canary 仍未完成。
> 第 13 次修订变更：`0045` 将 shared dispatcher 处理未预期 Provider Worker 异常或耗尽重试时的 Durable `retry_wait|failed|dead_lettered` 状态投影回 Sampling Attempt/Task/Run，避免领域状态永远停在 `running`。正常 fenced failure 已先完成领域写入时触发器不重复加版本。同步修复 Durable Store 将 `timedelta(0)` 误判为无重试的语义，零延迟和正延迟重试均在耗尽后进入 `dead_lettered`。隔离 PostgreSQL 覆盖三次立即重试、最终 dead letter 与领域失败收敛。
> 第 14 次修订变更：共享 Durable Store 的 completion/failure/retry/defer/cancel 现均在 SQL CAS 中要求 `lease_expires_at > clock_timestamp()`，消除旧 Worker 在 lease 到期但尚未被新 Worker 认领时仍能写终态的窗口。Sampling 隔离 PostgreSQL 已验证旧 lease 的 finalization/failure 被拒绝、relay recoverable 查询可发现过期 Job、新 fence 接管后才可收敛 Attempt/Task。Outbox Store 同步兼容 tuple 与 `dict_row`，避免恢复循环因行工厂不同崩溃。
> 第 15 次修订变更：`0046` 使 Workflow C 手工工件 DDL 接受受治理 writer 实际写入的独立 DEK envelope 与 redaction assurance；staged 审计事件仅经 SECURITY DEFINER trigger 追加，激活仅经 Project-scoped SECURITY DEFINER RPC 完成，应用角色保持无工件表 `UPDATE` 权限。隔离 PostgreSQL + 真实 MinIO 已完成 `head -> 0045 -> head`、受限内容清理/读取、过期后 crypto-erasure 与 payload/manifest 删除，以及 tombstone 后在访问对象存储前 fail-closed；仍不替代真实 Provider canary 或 evidence manifest。
> 第 16 次修订变更：Workflow C Sampling API 的 Run response 与领域状态机对齐，显式支持 `cancel_requested`、`cancelled` 和 `failed`，避免取消后的详情读取触发 500；稳定 OpenAPI 快照已重生并验证。PostgreSQL alert notification reader 同步将受限 rule/severity/status 文本显式还原为领域枚举，防止类型漂移绕过通知 payload 校验。
> 第 17 次修订变更：`0047` 将手工 `manual_ui` 证据的 staged 工件提交、maker/checker 审核、批准后 Attempt/Job/Spec/outbox 原子创建以及拒绝零 Attempt 的边界收敛到项目范围 RPC；实际出口验证仍属于 Attempt/Observation lineage，手工证据本身不构成消费者 UI 自动采样或 Provider live canary 证据。
> 第 18 次修订变更：`0048` 修复 Synthetic retention 过期 lease 的重领 guard：项目范围 claim RPC 已按显式 scheduler time 选择候选，outbox trigger 改为要求新 token、fence/attempt 单调递增及延长 expiry，避免 wall clock 尚未追上 scheduler time 时拒绝合法接管；旧 lease 的 terminal write 仍由 token/fence 拒绝。
> 第 19 次修订变更：`0049` 为 Synthetic retention scheduler 的“无现存 Job”分支增加按 Project 的事务 advisory lock，防止并发 wake 同时选择相同 replay nonce 或重复创建 Job/outbox；隔离 PostgreSQL 在插入处主动暂停以稳定覆盖该竞争窗口。
> 第 20 次修订变更：`0050` 对 Workflow C restricted artifact maintenance scheduler 应用相同的 Project transaction advisory lock；隔离 PostgreSQL 在首次 Job insert 暂停期间验证并发 seed 只创建一条 Job/outbox。
> 第 21 次修订变更：收敛非 B Internal API 的稳定 URL，移除面向调用方的 `runtime` 术语；Prompt Bootstrap payload 不再携带由服务端派生的 schema hash；Workflow C 可选 PostgreSQL builder 在其父模块尚未安装时正确 fail closed 为 unavailable。稳定 OpenAPI 已重新导出并通过校验。
> 第 22 次修订变更：`0051` 使 Synthetic parent-job terminal trigger 在检查 Project scope 前先确认该 Job 实际关联 Synthetic Model Call child，避免无关 Durable Job 的终态更新被错误的 Synthetic scope guard 阻断；对真实关联的 Synthetic parent 仍保持原有 fail-closed scope guard。真实 PostgreSQL 已完成升级、回退和重放，完整集成套件无失败。
> 第 23 次修订变更：认证恢复 Gate 已在随机隔离 Docker Compose 项目实际执行到 `0051_synthetic_parent_scope`，验证五桶加密归档、ACL/RLS、冻结 Secret resolve receipt、所有在用 key version 及错误 key/HMAC 负测；收据与 manifest hash 记录在第 16 节。该次本地演练不替代生产恢复、独立 verifier 或最终签字。
> 第 24 次修订变更：五桶 MinIO production bootstrap 已在全新隔离实例以真实 `minio/mc` 完整执行、撤销短期 restore/retention principal 并在同一实例重入 provision。演练发现并修复 `mc` 镜像不含 `cmp`、纯 delete-only principal 的单对象删除会隐式读取及 receipt 默认 umask 过宽三个运行问题；回执现为 `0600`。该次本地演练不替代生产身份、基础设施加密、独立 verifier 或最终签字。
> 第 25 次修订变更：`0052/0053` 为 Provider Sampling 增加独立、不可变的服务端 execution input registry，并在 Provider Suite 创建与 Attempt 写入两道数据库边界强制 exact binding。旧未绑定 Suite 仍可读取但不可 enqueue；新 Provider Suite 必须绑定逐题原文/hash、Prompt lineage、runtime 与 deadline 输入，且由同一 immutable Suite source 固定 search mode。隔离 PostgreSQL 已完成前进、回退、重放、RLS/ACL、unbound Suite 与篡改 Prompt 负测；持久化 Internal API composition 和真实 Provider canary 仍未完成。
> 第 26 次修订变更：`0054_provider_attempt_schedule` 关闭 Provider Attempt 的排程旁路。应用角色失去旧无调度 RPC 的执行权限，只能调用新 wrapper；该 wrapper 在同一事务内保留 future `requested_not_before` 到 Durable Job `next_run_at`，同键 replay 对 deferred 时间进行一致性检查。`PostgresWorkflowCProviderSamplingControl` 只从 Suite binding 读取 immutable execution input，并从任务版本、Run admission 与 Suite source 派生 Worker spec，HTTP body 不携带问题正文、Prompt、runtime、search mode 或 deadline。隔离 PostgreSQL 已验证前进/回退/重放、权限撤销、延迟 Job、registry rebuild spec 与 idempotent replay；完整 durable Internal API composition 和真实 Provider canary 仍未完成。
> 第 27 次修订变更：Sampling 的 Attempt aggregate 与 Durable Job 现在显式保存一对一但可不同的 `durable_job_id`，不再错误假定二者 UUID 相同。`PostgresSamplingReadRepository` 在 Project RLS 下从持久化 Attempt/Observation/Job 恢复 Admin 读模型，并逐项复核 Job 终态、Observation hash、地点谱系、工件与 evidence schema；其不读取 worker-only immutable spec。隔离 `geo_app` PostgreSQL 已验证排队 Attempt 可读，完整 durable Internal API composition、bulk command 与真实 Provider canary 仍未完成。
> 第 28 次修订变更：`0055_provider_bulk_enqueue` 将 Provider `/enqueue-ready` 的持久化子项收敛为单一、Project-scoped、RLS fenced 的数据库命令。首次命令在稳定 `task_key` 顺序锁定 exact ready slice，按 Suite 最小间隔派生 schedule，并在同一事务逐项调用 `0054`；任一版本、配额、授权或 lineage 错误均回滚此前 Attempt/Job/Spec/outbox。外层 ledger 只冻结调用方可控的 `run/requested_not_before/max_tasks`，而将服务器解析的 slice/Worker spec 固化进结果，避免 Task 状态变为 `queued` 后把同键 replay 错判为新请求。隔离 PostgreSQL 已验证 future schedule、replay、改变 payload 拒绝和后项失败的整批回滚；完整 durable Internal API composition 与真实 Provider canary 仍未完成。
> 第 29 次修订变更：`0056_sampling_cancel_lineage` 保持既有 Run cancel RPC 兼容，并通过同事务、同 advisory lock 的 v2 wrapper 在命令账本冻结实际被处置的 Provider Attempt ID；重放只返回该不可变 lineage，绝不由当前 Attempt 状态反推。`PostgresWorkflowCSamplingRuntime` 及其局部 composition factory 已组合 policy、Suite、Run、Provider 单/批 enqueue、manual evidence、取消和只读模型，并以隔离 PostgreSQL 验证 v2 首次/重放 lineage、`head -> 0039 -> head` 和 Provider/bulk 回归。该局部适配器尚未使全局 Workflow C API become durable：Analysis 的持久化 command/read controls、真实受治理 manual artifact writer 的生产接线、全路由 integration 和 live Provider canary 仍未完成。
> 第 30 次修订变更：`0057_provider_exec_retirement` 将 Provider execution input 的预留 `retired` 状态收敛为 one-way、optimistic-version-fenced、命令账本可重放的受控 lifecycle；审计只接受枚举 reason code，避免把自由文本或凭据写入不可变记录。退役后 0052 binder 仍只可为新 Suite 选择 `approved` input；已冻结 Suite 保留其 exact FK 和不可变 payload，并由替换后的 Attempt trigger 对每次 enqueue 重新核对完整 lineage。隔离最小 `geo_app` PostgreSQL 验证退役/重放、旧 Suite durable enqueue、新 Suite 拒绝、direct update 拒绝以及有 retirement evidence 时 downgrade fail-closed。真实 catalog/backfill、secret 递归负测与 Provider live canary 仍未完成。
> 第 31 次修订变更：`0058_wfc_spec_sensitive` 令 Workflow C immutable Job spec 的 Python 与 PostgreSQL 递归 guard 同步拒绝 `api_key`、access/refresh/id token、cookie、session、storage state 及 proxy 实值字段，同时保留 `secret_reference_id` 与 `max_output_tokens` 等非敏感冻结 lineage。修复迁移初版遗漏 JSON scalar `ELSE` 后，隔离 App-role PostgreSQL 完整跑通十种 kind、嵌套 `api-key` 直接 RPC 拒绝和 `head -> 0057 -> head`。这只完成通用 producer 边界，不替代十类业务 admission 的完整集成与 live evidence。
> 第 32 次修订变更：仓库级 `make quality` 暴露 Customer Workflow C PostgreSQL approved-report reader 未将 durable marker 标注为协议要求的 `Literal["durable"]`，以及 Sampling Suite PostgreSQL integration fixture 超出架构测试 800 行上限。前者现为精确结构类型，后者仅将共享构造/权限断言抽至 346 行 support module，原 606 行端到端测试的 RLS、排程、取消、租约丢失与 retry 断言不变；`make quality` 与真实隔离 PostgreSQL 回归均已通过。
> 第 33 次修订变更：Chromium required gate 不再硬占本机固定端口。Admin、Customer 与 Workflow C Playwright config 现在各自接受并校验本地 `*_SERVER_PORT`，同时将自动启动的 Next server URL 与 `-p` 绑定到同一值；默认端口及显式 external Base URL 行为不变。`3100` 已被本机服务占用时，正式 runner 在 `3110/3190`、`3111/3191`、`3201/3291` 隔离端口完整通过 Admin 25、Customer 4、Workflow C 3 项，且 runner 后 `next-env.d.ts` 回到正式 `.next` 基线。
> 第 34 次修订变更：`make test-infra-runtime` 在隔离 Compose 项目从空 PostgreSQL 完整升级至 `0058_wfc_spec_sensitive`，随后执行 F018 production-network、compose health、runtime readiness dependency 与 PostgreSQL heartbeat 矩阵；pytest failure cache 为空且临时容器已清理。该本地 runtime 证据补充但不替代 M6 production network、备份恢复与独立 verifier 签字。
> 第 35 次修订变更：仓库内 release-contract 回归已重新执行：稳定 Internal/Customer OpenAPI export/verify 及其合同测试、Web API client/Auth BFF 合同测试和 Admin/Customer 的 production `next build` 均无失败；构建后 `apps/admin-web/next-env.d.ts` 仍指向正式 `.next` 路由类型，稳定 OpenAPI 文件没有因 verify 产生额外变更。该次只记录可重复的本地发布合同，不替代真实环境、外部账号、live canary 或最终 evidence manifest。
> 第 36 次修订变更：`0059_analysis_project_scope` 修复 Workflow C 分析投影把内容 hash 错当全局租户身份的问题。Semantic Snapshot/Result、Comparison Family/Result 和 Drift Report 现以 `project_id + hash` 复合键持久化；Worker 的 conflict/read 查询同样带 Project，RLS 子表直接按 Project 过滤且仍由复合 FK 验证父投影归属。Recommendation 的 SECURITY DEFINER 证据解析器对 comparison 分支使用 Project-qualified join，避免在关闭 row security 的函数内把两个 Project 的相同 family hash 混合。隔离 PostgreSQL 已以两个 Project 的相同快照、比较和漂移 hash 验证各自可写、只可读自身、建议解析返回正确 Project，并验证存在重复 Project-scoped identity 时回退到旧全局键被 fail-closed 拒绝；同时将 Customer report projection 的历史来源夹具改为最小合法 draft policy，避免夹具伪造已批准采样授权。`make quality`、迁移合同及两项相关 PostgreSQL 回归通过；这仍不替代统计 live evidence、独立 verifier 或最终 evidence manifest。
> 第 37 次修订变更：第 36 次修订后的 required non-live test suite 已完整执行，`1994 passed, 0 failed, 0 skipped`（`make test-migrated`，7 分 09 秒）。该结果覆盖非 integration/live/browser 的仓库合同，作为后续 durable Workflow C API 与 Metric Worker 收敛前的回归基线；不会替代隔离 PostgreSQL/MinIO、真实 Provider、live staging 或 evidence manifest 验收。
> 第 38 次修订变更：Metric Worker 的真实 terminal RPC 回归发现并修复 `geo_complete_workflow_c_metric_child` 与 `geo_fail_workflow_c_metric_child` 的 PL/pgSQL 名称歧义：`RETURNS TABLE aggregate_version` 会令未限定的 `SET aggregate_version = aggregate_version + 1` 失败。`0060_metric_rpc_aggregate_fix` 保留既有 function 的 fence/RLS/privilege 定义，只显式限定目标表列；`head -> 0059 -> head`、最小 `geo_worker` Judge completion、Project scope、direct write 拒绝和 terminal replay fence 已在隔离 PostgreSQL 通过。完整 Metric producer、加密任务/MinIO、Model Gateway、arbiter 与 live evidence 仍未完成。
> 第 39 次修订变更：`0061_metric_child_reconcile` 将 Metric child 的 Durable 状态异常路径收敛回数据库 aggregate：`retry_wait` 只把遗留的 `running` child 重置为 `queued`；`failed`、`dead_lettered` 和 `cancelled` 终结 child/batch，取消尚未执行 sibling 并向运行 sibling 写入 cooperative cancel。该 SECURITY DEFINER trigger 使用 Project/batch advisory lock、行级 lineage 校验和 Worker-only 表权限，既不接受旁路写入也不因正常 fenced terminal RPC 而回滚既有结果。隔离 PostgreSQL 已验证 `head -> 0060 -> head`、真实 Job Store retry/failure/cancel、queued/running sibling 收敛；完整 Metric producer、加密任务/MinIO、Model Gateway、arbiter 与 live evidence 仍未完成。
> 第 40 次修订变更：`make test-infra-runtime` 已在独立 Compose 项目从空 PostgreSQL 完整迁移至 `0061_metric_child_reconcile`，并重新执行 F018 production-network、Compose health、runtime readiness dependency 与 PostgreSQL heartbeat；命令成功返回，临时容器与网络清理完成。这是当前 head 的本地运行时兼容性证据，不替代真实 secret、生产网络、恢复演练、外部 Provider 或独立 verifier 的最终验收。
> 第 41 次修订变更：`0062_metric_judge_agreement` 为一致 Judge 结果增加无 Arbiter 的确定性终态：只有至少两名已准入 Judge 全部成功、全部拥有 output hash 且 hash 完全一致时，才按 `evaluator_id, candidate_id` 稳定选取候选并完成 batch；不完整或分歧仍保持 running，原 Arbiter 分支不变。迁移以版本控制的完整 `CREATE OR REPLACE FUNCTION` 重建 fenced completion RPC，不再依赖 `pg_get_functiondef` 的格式化文本；隔离 PostgreSQL 已验证 `head -> 0061 -> head`、完整 Sampling Run/Observation 外键 lineage、最小 `geo_worker` 身份、直接写入拒绝、跨 Project fence 和 replay。SQL checksum ledger 同步按 `0062` 创建并校验。完整 typed producer、加密任务/MinIO、governed Model Gateway、Arbiter 调度和 live evidence 仍未完成。
> 第 42 次修订变更：F018 runtime gate 已再次从空库完整迁移至 `0062_metric_judge_agreement` 并执行 Compose health、production-network、readiness dependency 与 PostgreSQL heartbeat。复查发现 runner 曾吞掉 `compose down` 退出码，现改为 cleanup 失败即输出 stdout/stderr 并返回失败；本次重跑后检查无任何 `geo-f018-runtime-*` 容器或卷残留。该本地隔离证据不替代生产网络、真实 secret、恢复演练、外部 Provider 或独立 verifier 的最终验收。
> 第 43 次修订变更：`0063_wfc_artifact_write_grant` 修复 Workflow C restricted artifact 的真实写入故障路径。原 `geo_enqueue_workflow_c_artifact_write_failure` 既未授权受限 `geo_app` writer，又因 `RETURNS TABLE(artifact_id ...)` 与未限定列冲突而无法执行；现仅向 writer 授予该 SECURITY DEFINER RPC，并以显式表别名重编译函数，不扩大 scheduler、claim、crypto-erasure 或表直写权限。隔离 PostgreSQL + 临时真实 MinIO 已验证 manifest 写入失败后原子入队 `write_failed`、创建 durable Job/outbox、worker lease 执行 DEK 先销毁再删对象；另验证 activate 前的 staged artifact 在 60 秒 grace 后创建同类 durable wake 并 tombstone。该项不替代 legal hold、生产 identity、独立 verifier 或 live evidence。
> 第 44 次修订变更：F018 runtime gate 已在独立 Compose 项目从空 PostgreSQL 完整迁移至 `0063_wfc_artifact_write_grant`，并通过 production-network、Compose health、runtime readiness dependency 和 PostgreSQL heartbeat 的 7/7 项测试（62.59 秒）；`compose down --volumes --remove-orphans` 后复核无 `geo-f018-runtime-*` 容器或卷残留。0063 的 SQL checksum ledger 已建立并自校验，Metric 隔离 PostgreSQL 已完成 `head -> 0061_metric_child_reconcile -> head` 重放。以上仍是本地隔离证据，不替代生产网络、真实 secret、恢复演练、外部 Provider 或独立 verifier。
> 第 45 次修订变更：`0064_wfc_artifact_hold_expiry` 将 Workflow C restricted artifact 的 legal hold 从无限期布尔开关收敛为有截止日期的双人控制：`apply`/`extend` 必须冻结不超过 90 天的 `hold_until`，`release` 不得携带截止日期；延期是新的 maker/checker 请求，不得缩短或旁路当前 hold。maintenance seed 在同一事务先处理到期 hold，再发现正常 retention；到期请求/hold 追加审计事件，当前有效 hold 解除后已过期工件立即进入既有 durable deletion queue。隔离 PostgreSQL + 真实临时 MinIO 已验证真实 Sampling Run/Task lineage、申请、独立审批、延期、到期、Job/outbox、DEK 先销毁、对象删除和 tombstone。升级遇到旧版 active boolean hold 会 fail closed，要求先人工释放并按新流程重新批准，绝不杜撰历史截止时间；兼容降级会将新字段和 `extend` 行为写入 `legacy_0064` 审计文本后映射到旧模型。该项仍不替代生产最小权限身份、独立 verifier、真实账号或 live evidence。
> 第 46 次修订变更：F018 runtime gate 已从空 PostgreSQL 完整迁移至当前 `0064_wfc_artifact_hold_expiry`，并成功执行 production-network、Compose health、runtime readiness dependency 和 PostgreSQL heartbeat；命令正常返回且随后复核无 `geo-f018-runtime-*` 容器或卷残留。此为当前 head 的本地隔离运行时同等性证据，不替代真实 secret、生产网络、外部账号、恢复演练或独立 verifier。
> 第 47 次修订变更：`0065_metric_output_projection` 令 Metric Judge/Arbiter 的当前 Worker 在同一 fenced completion transaction 中写入 hash-bound、最小化 JSON 结果投影。投影不修改不可变 child lineage，而是以 `(project_id, child_job_id)` 独立 append-only RLS 表保存，避免为历史 child 补结果时重检已退役 Prompt Binding 的无关外键；老十参数 RPC 仍可完成滚动部署中的 Job，但不会创建投影，因此父任务必须 fail closed。隔离 PostgreSQL 已验证 `head -> 0059 -> head`、Worker scope/fence、hash mismatch 原子拒绝、legacy 无投影、Judge agreement 和 terminal reconciliation；F018 亦已从空库升级至 0065 并清理临时资源。完整 Metric parent producer、仲裁调度、父任务唤醒/合并、模型 live evidence 仍未完成。
> 第 48 次修订变更：Metric child 的 future producer 现在可由唯一 task factory 从已冻结的 Judge batch、候选分歧和已解析 Model request 创建任务；factory 会丢弃 Observation 中预存的 judge outputs、强制 `en-AU`、精确绑定 plan/evidence/citation 集，并将 canonical JSON 以 child Job/Project AAD 加密为 Secret Store envelope。Arbiter 只可在真实 Judge 分歧时构造，十参数 legacy completion 仍无投影。该项是 typed producer 的基础合同，不替代 admission、数据库 reservation、Job/outbox 原子生产、父任务唤醒或模型 live evidence。
> 第 49 次修订变更：Metric parent 的读取端现在只查询 completed batch 中 `selected_candidate_id/selected_output_hash` 对应的 Judge child，并以独立 projection 的 canonical hash 重建 candidate；未完成 batch、legacy 十参数 completion 的缺失 projection、非 selected child 或结构/hash 不匹配一律 fail closed。隔离 PostgreSQL 已在一致 Judge completion 与 terminal reconciliation 后验证该读取路径。该项仍不创建/唤醒 parent，也不替代 typed producer、Arbiter 调度或最终 snapshot merge。
> 第 50 次修订变更：Metric parent 的纯合并层现在会从当前冻结 `MetricInputSet + Suite` 重算全部 batch，拒绝不完整、重复、陈旧或 input 已含 model 输出的集合；对每个 selected projection 再验证 exact batch canonical input、metric ID/kind、judge schema/observation lineage，以及 locator 不越过该 plan 的 allowed evidence。该项只闭合 snapshot merge 的无副作用领域合约，不创建/唤醒 parent、Job/Spec/outbox、Arbiter 或任何模型调用。
> 第 51 次修订变更：跨工作流质量复查发现 Metric Worker/contracts 超出仓库单模块 600 行边界；contracts 的值解析职责现拆入独立 parser/value 模块，原 public import 路径保持兼容，执行层亦压至 600 行。修复 projection 重建向 `StructuredJudgeOutput` 传入裸字符串的类型边界，并为未知 kind fail-closed 增加回归；完整 `make quality` 已重跑通过。
> 第 52 次修订变更：进一步复查拆分后的 module import order，发现 value parser 若作为首个 import 会与 contracts re-export 形成部分初始化风险；现将纯 dataclass/error 移入 dependency-light types module，形成无循环的 `types -> values -> contracts` 层次并保持原 contracts import 路径。直接 values-first import、Ruff、mypy 与 Metric Worker/semantic 单元回归已通过；此项仍不创建 durable parent producer。
> 第 53 次修订变更：types/value/contracts 边界修正后完整 `make quality` 再次通过（669 Python source、双 Web typecheck、secret/backup scans、42 architecture tests）；该结果只确认仓库内组合质量，不替代 parent producer 的持久化流程或最终 live/evidence 验收。
> 第 54 次修订变更：Metric task factory 复查发现 `evaluation` 仅存在于应用侧 task 字段，过去并未自动进入实际 `ModelGatewayRequest.messages`，导致 Judge/Arbiter 可能在严格 lineage 下调用模型却没有 Observation、允许证据或候选内容。factory 现将 Judge 的 `MetricJudgePlanBatch.program_input` 及 Arbiter 的完整候选 canonical result/hash、允许 evidence/citation 集以一个 canonical JSON user message 固化进同一加密 task；应用侧 `evaluation` 仍保留作独立输出校验。定向 Ruff、mypy 和 13 项 Metric contract/semantic/Worker 单元回归通过。此项只修复真实模型请求的输入完整性，不创建 durable parent producer、Arbiter admission/wake、snapshot merge 或 live evidence。
> 第 55 次修订变更：`0066_metric_parent_admission` 将首批 Metric Judge 子任务的 typed producer 收敛为一个由持有父 `semantic_metrics` lease 的 Worker 调用的 SECURITY DEFINER RPC。每个 batch 在同一事务内校验父 Job/spec/hash/lease、冻结 Prompt/runtime、可解密的主密钥版本及至少两名独立 Judge，并原子创建加密 task、secret-free immutable child spec、Durable Job、batch/child lineage、outbox 和 enqueue event。普通 Job Spec 继续要求 `input_hash=spec_hash`；Metric child 仅在 canonical public ref 的 `task_hash` 精确绑定 Durable input hash 时获准，从而不将 Observation 或模型输入泄露到 spec。隔离 PostgreSQL 已完成 `head -> 0065 -> head`、受限 Worker、重复 admission、direct write 拒绝和 child terminal/reconciliation 回归。该项仅创建 Judge；父任务的实际调用/deferral/wake、分歧 Arbiter admission、selected projection merge 和 live 模型证据仍未完成。
> 第 56 次修订变更：分歧 Arbiter 的 encrypted-task preparation contract 已补齐。它只接受 `arbiter_required=true` 的精确 Judge candidate resolution，使用同一 batch/input evidence 构造 Arbiter program input，并将 candidate IDs、evaluator IDs、canonical output/hash 和允许 evidence/citation 集只写入加密 task；公开 immutable spec 仍只有 parent/batch/role/task hash 引用。Ruff、mypy 及 12 项定向 Metric 单元回归通过。此项是后续 `0067` 原子 Arbiter admission 的必要输入，但尚不创建 Job/child/outbox，也不唤醒或完成 parent。
> 第 57 次修订变更：Arbiter preparation 在入口显式要求所有 Judge candidate ID 为 UUID，与 Durable child/terminal RPC 的数据库身份合同保持一致；自由字符串在加密或入队前 fail closed。定向 Ruff、mypy 与 8 项 Metric preparation/task-factory 回归通过。
> 第 58 次修订变更：`0067_metric_arbiter_admission` 将 Judge 分歧后的 Arbiter 准入收敛为一个由父 `semantic_metrics` lease 持有者调用的 Worker-only SECURITY DEFINER RPC。它锁定 running batch，要求所有 Judge 已成功、每个 hash-bound output projection 存在且至少两个 output hash 分歧，之后才在同一事务创建一个 encrypted Arbiter task、Durable Job、secret-free immutable spec、child lineage、outbox 与 event，并写入 batch 的唯一 `arbiter_child_job_id`。隔离 PostgreSQL 已完成 `head -> 0066 -> head`、受限 Worker、缺 projection 拒绝、重复 admission/direct child update 拒绝；这仍未把 Judge/Arbiter admission 接入父 operation 的 defer/wake/merge/snapshot 生命周期，也不构成 live 模型证据。
> 第 59 次修订变更：废止以传统团队 FTE 和自然月为单位的执行时钟。范围、稳定 ID、Gate、样本量、统计/安全/授权门槛及最终证据要求完全不变；全部可由 Agent 完成的实现、自动化验证和复查压缩为 `T+0`--`T+5` 的连续交付窗口。真实账号、授权、独立 verifier、人工明审和 live staging 自 `T+0` 并行启动，未就绪时仅阻断相应 evidence/Gate，绝不以 mock 降低标准或把其等待时间伪装为工程实现周期。
> 第 60 次修订变更：`0068_metric_parent_progress` 为持有 `semantic_metrics` 父 lease 的 Worker 增加两条最小、fenced、Worker-only progress reader。父 operation 只能取得自身 batch 状态和可消费 Judge projection，读取同时重检 Project、父 Job、lease token/fence、frozen spec hash、运行态和未取消条件；不会接触 child 加密任务、原始模型输出或凭据。隔离 PostgreSQL 完成 `head -> 0067 -> head`、受限 Worker reader 与 Judge resolution 路径；静态、类型、50 项单元/迁移和 PostgreSQL 集成回归通过。该项仍不替代父 operation 的最终 snapshot persistence、真实模型调用、live evidence 或最终 manifest。
> 第 61 次修订变更：`0069_metric_snapshot_rpc` 将语义 Metric Snapshot/Result 的最终写入收敛为 Worker-only、fenced SECURITY DEFINER RPC。写入前重检父 `semantic_metrics` Job/spec 的 frozen hash、Project、lease token/fence、运行/未取消状态，并核对 snapshot canonical hash、结果行、payload 和不可变冲突；Worker 保留最小只读验证权限但不再拥有 snapshot/result 表直写权限。隔离 PostgreSQL 空库 migration、`head -> 0066 -> head`、直写拒绝、两个 Judge 完成、父 Job 恢复、snapshot/result 持久化和 Durable terminal 完整通过；尚不替代真实模型、live canary 或最终 evidence manifest。
> 第 62 次修订变更：`0070_analysis_projection_rpc` 将 Comparison Family/Result 与 Drift Report 的最终写入同样收敛为 Worker-only、fenced SECURITY DEFINER RPC。每次写入重检 Project、Job/spec frozen hash、lease token/fence、running/未取消状态，验证 canonical payload/result 对应、不可变冲突并撤销 Worker 表直写；Python 只保留 Project-scoped equality read 和同事务 Job terminal。统计域 Python 的 `sort_keys` hash 与 PostgreSQL locale 排序存在键序差异，迁移新增 C-collated Python-compatible canonicalizer，仅用于新 RPC 验证，未重写历史 hash 语义。隔离 PostgreSQL 完成空库 migration、`head -> 0069 -> head`、受限 Worker 直写拒绝和真实 comparison/drift operation 落库/Job 成功；尚不替代真实模型、live canary 或最终 evidence manifest。
> 第 63 次修订变更：`0071_analysis_job_admission` 闭合 Comparison/Drift 的此前测试夹具旁路：App 侧先以共享统计 contracts 严格重建完整 frozen payload，数据库再校验精确结构、stratum、hash、decimal 与非空数组边界，随后才原子创建 Durable Job/spec/outbox/event。分析 Job 的 hash 校验使用既有 C-collated Python canonicalizer，避免 `a_` 等键在 PostgreSQL locale 下与 Python `sort_keys` 分叉；其他历史通用 Job 保持原 hash 语义。隔离 PostgreSQL 完成 `head -> 0070 -> head`、受限 App 的无效输入零写入、App admission、Worker lease、comparison/drift 持久化和 Job 成功。该项仍不替代从真实 approved Observation/Snapshot 服务器解析统计输入、完整 durable Internal API 路由或 live Provider evidence。
> 第 64 次修订变更：新增 Project-RLS scoped 的 Workflow C analytical projection read model。它只读取 fenced Worker RPC 已写入的 immutable Semantic Snapshot、Comparison Family 和 Drift Report，在 API presenter 重算 projection/result hash，并核对可比较的 semantic input/suite header 与 payload 后才渲染；Sampling `source_stratum_hash` 与 Metric payload 的 `stratum_hash` 属于不同 lineage，明确不强行相等。读取不接触 worker-only Job spec 或 HTTP body。durable adapter 的三个 compute command 明确 `503 unavailable`，直到 Comparison Plan/Drift Protocol/Metric Protocol 的持久化版本和真实 approved Observation/Snapshot server-side resolver 完成，防止冻结 payload admission 被误表述为真实业务输入。隔离 PostgreSQL 已验证 `geo_app` 自身 Project 的 comparison/drift read、response hash 与随机 Project 零结果；此项不使全局 `WorkflowCApi` durable，也不替代完整 route composition、真实 Provider 或最终 evidence manifest。
> 第 65 次修订变更：全局 `WorkflowCApi` 现组合已完成的 Sampling、分析 immutable projection read 和 Alert disposition 三条 durable vertical。Internal API 的受治理工件 writer 启动时只读调用 `0072` 的 SECURITY DEFINER canary RPC，校验 Docker Secret keyring 后才可用；`geo_app` 仍无 `workflow_c_artifact_master_key_versions` 的直接 `SELECT`、同步或轮换权。缺少 keyring、对象存储凭据、canary、数据库权限或任一构造依赖时不回退内存 runtime，整体继续 `unavailable`。Analysis 三个 compute command 仍为 `503`，直至真实 approved Observation/Snapshot 的服务器端 resolver 及 Protocol/Plan lifecycle 完成。单元和隔离 PostgreSQL 已验证只读 RPC、rollback、受限 App RPC 成功与直接表读取拒绝；尚不构成 Provider/live staging/final evidence 验收。

## 1. 执行结论

在 `T+0`--`T+5` 完成可由 Agent 交付的实现、自动化验证与复查，并为五个可使用真实账号、真实数据和不可变证据验收的业务板块完成所有可控准备：

| 板块 | 加速实施完成定义 |
|---|---|
| 内部合成测评实验室 | 九个标准渠道均具备澳洲英文风格样本、版本化 Style Profile、知识冲突检查、修订闭环和三臂离线 GEO 实验；全部结果保持 `test_only=true`、`publication_eligible=false` |
| 外部数据与跨引擎采样 | Connector Core、GSC、GA4、Google/Bing 官方报告、五类外部 API adapter（Microsoft Grounding 使用 `proxy_grounded_api`，其余按实际能力使用 `provider_api`），以及通过已验证澳洲出口采集 Google AI Overviews/AI Mode、Bing Copilot 等真实消费者界面的 Browser Capture Connector 在 live staging 运行；未取得授权依据的 surface 按第 2.4 节 B 轨（fixture + 人工采样）完成并记录降级决定，不阻塞阶段验收；来源类型、原始工件和分母不可混淆 |
| 统计实验与告警 | 重复采样、完成度门槛、区间、胜/等效/负/不确定、跨问题负收益、漂移、阈值/基线告警及完整处置记录可重复计算 |
| 本地业务归因 | 一方事件入口（Session/Touch 主来源）、UTM、无 PII trace token、Session、Touch、Lead、Conversion、Deal、Revenue 与 Campaign、QuestionSet、内容/Package Version、verified URL 串联，并生成版本化归因快照；GA4 作为聚合对账口径 |
| 可解释建议闭环 | 建议可以回溯到真实观测、统计、归因、Fact、规则和 Prompt Release；人工批准后只创建实验、问题、内容或采样草稿 |

本阶段不是自动发布平台，也不是完整 CRM。人工审核、人工发布和 Customer 只查看已批准真实结果的现有边界继续有效。`synthetic`、内部评审中间结果、未批准建议、原始凭据和内部调试字段永不进入 Customer 投影。

阶段验收不依赖任何第三方平台授权的实际取得；依赖的是每个自动采集 surface/渠道都有明确的授权结论，以及对应轨道（第 2.4 节）的完成证据。

在最终 Gate 的真实外部证据到齐后，系统应能回答以下闭环问题，并提供可复核证据：

```text
哪些真实数据或外部回答发生了变化？
  -> 变化是否超过冻结协议的样本和统计门槛？
  -> 变化涉及哪些问题、来源、页面、内容版本和业务结果？
  -> 系统为什么建议修改、实验、不修改或继续采样？
  -> 人工批准后创建了哪个草稿，后续真实结果如何回填？
```

### 1.1 文档职责和执行方式

本文件是加速实施计划的总控基线，负责范围、跨工作流依赖、共享合同、连续 Gate 退出门槛和最终发布决定。“外部数据与跨引擎采样”专项文件负责 Connector Core、GSC/GA4、官方报告、五类外部 API、消费者 AI 界面、澳洲代理和 Sampling Core 的详细工作包与逐源验收。两份文件发生歧义时按以下顺序处理：

1. 安全、权限、真实性、分母和 Customer 可见性采用两份文件中更严格的条款。
2. 外部板块的任务状态和证据以专项文件的 `EXT-*` ID 为准；本文件不复制其完成状态。
3. 对应交付波次只有在本文件对应 `GATE-M*` 与专项文件对应 `EXT-GATE-M*` 同时通过时，才可整体 `ACCEPTED`。
4. 任何范围、门槛或样本量变更必须先形成批准的基线变更记录，并同时更新受影响的主计划和专项计划；实现 PR 不能隐式改变计划。

Checklist 统一使用以下语义：

- `[ ]`：尚未由证据证明完成，包括“代码已写但未验收”的状态。
- `[x]`：owner 和 verifier 已在 evidence manifest 中签字，且所有必需证据 URI/hash 可读取并通过校验。
- 阻塞、豁免和部分完成不使用非标准 Markdown 符号冒充完成，而是在交付状态表记录 `BLOCKED_EXTERNAL`、`IN_PROGRESS` 或批准的 change record。
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

DoR/DoD 是每个工作包重复使用的模板，不在计划阶段预先勾选。实施时在对应波次的 evidence manifest 中为每个 ID 建立类型、flags、适用性和证据实例。

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
| 消费者 AI 人工采样 | `manual_ui` | 是，独立分母 | 不进入 Workflow C Customer approved report；仅 Admin | 保存采集人、时间和原始证据；不得以人工样本替代已批准自动/API 结果 |
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
- **授权决策点与执行顺序**：任何真实自动采集 enqueue 前，目标 surface/渠道必须已经有有效 `approved` 记录；`not_assessed`、申请中、`assessed_no_basis`、过期或撤销均不能创建 live 自动任务。`T+0` 即并行发起每个首批 surface/渠道的逐项决定，并在 `M2` Gate（最晚 `T+2`）前形成 `approved` 或 `assessed_no_basis`，再按对应轨道执行；申请中在技术上按 B 轨限制，达到该 Gate 仍未获批准则正式记录 `assessed_no_basis`，不允许第三种悬置轨道延后。决策记录进入对应交付波次的 evidence manifest；后续取得授权可创建新授权版本、升轨并补做 A 轨验收。
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

四条工作流允许按连续交付波次并行，但以下内容必须单线合入：

- Alembic 迁移始终只有一个 owner 和一个线性 head。
- 共享枚举、OpenAPI schema、Prompt/Model Gateway port 和 artifact manifest 先冻结合同再实现。
- 同一共享表、共享 API schema 或 Customer 投影不得由两条工作流并行修改。
- 每个交付波次先通过共享合同测试，再合并工作流功能；不以跨分支临时兼容代码替代合同。

### 3.3 `T+0` 启动前提

- `T+0` 立即启动 Agent 可独立完成的代码、迁移、测试和复查；传统工程 FTE 不再是该实现时钟的启动条件。第 3.4 节保留的人工角色只约束不可委托的授权、账号、明审、独立复核和发布签字。
- 准备可产生验收证据的 GSC、GA4、五类外部 API、至少一个登录采集账号，以及至少一个可路由浏览器流量的澳洲代理出口。
- “可用澳洲 IP”在实现合同中必须是可连接的 HTTP CONNECT/HTTPS/SOCKS5 `host:port`（可附 username/password）或受控网络网关；只有 IP 字符串但没有代理/隧道服务不能作为浏览器出口。
- Google 明确将未经许可的自动查询/结果抓取列为违规流量；Bing 内容的商业下载、复制或产品化也需要明确授权；Amazon、Instagram、TikTok、Reddit 等风格采集渠道的条款同样限制自动抓取。因此任何自动采集启用前必须按第 2.4 节完成授权评审并记录 `authorization_state`；没有明确允许依据时进入 B 轨（parser fixture、人工交互采样、人工样本导入或经授权 PoC），不以代理绕过该门槛。
- 设定整个 `T+0`--`T+5` 窗口的模型/API 预算和供应商并发上限；预算不足只能缩小 QuestionSet，不得减少统计门槛后仍声称完成。同一规则适用于吞吐：Suite 冻结前必须完成第 7.1 节吞吐预算测算。
- 第三方连接器凭据进入系统前，完成数据库服务角色最小权限复核、负向权限测试和 Secret 轮换演练。这是既有 F-017 重新评估条件被触发后的进入门槛。
- 任何真实 Connector/Provider/代理凭据或 Lead、Deal、Revenue 数据进入系统前，重新开启 F-003 备份安全门禁：备份目录 `0700`、文件 `0600`、PostgreSQL/MinIO 备份静态认证加密、备份加密密钥与应用 Secret 主密钥隔离、checksum/签名验证和第 4.3 节外部 keyring 恢复演练必须全部通过。未通过时只能使用无敏感信息 fixture。

### 3.4 人工不可委托投入和降范围规则

下表是原六个月团队方案的人工职责基线，现仅用于保证不可由 Agent 替代的责任有人承担，并不延长 `T+0`--`T+5` 的实现窗口。FTE 可以由多人拆分，但同一人的并行分配合计不得超过 `1.0`，共享角色必须在交付容量表中显式分摊：

| 能力/工作流 | 最低 FTE | 最低组成 |
|---|---:|---|
| A. 合成与知识 | 1.5 | 1 名资深 backend/ML + 0.5 data/evaluation |
| B. 连接器与归因 | 2.0 | 2 名资深 backend/data；其中至少 0.5 FTE 保护给迁移/数据合同 |
| C. 观测与统计 | 2.0 | 1 名资深 browser/backend + 1 名 statistics/data/backend |
| D. Prompt 与建议 | 1.0 | 1 名资深 backend/ML |
| 跨流 Frontend | 1.5 | Admin 1.0 + Customer/共享组件 0.5 |
| QA/测试自动化 | 1.0 | 集成、浏览器、live evidence 和恢复验收 |
| DevOps/Security | 0.5 | 网络、Secret、备份、staging 和容量 |
| Product/运营明审 | 1.0 | 授权决策、样本明审、真实归因旅程和波次签字 |

原团队模型的工程基线为 `9.5 FTE`，另加 `1.0 FTE` Product/运营；在本计划中，Agent 承担工程实现及自动化验证，表中工程角色用于代码审阅、运行环境和职责覆盖，不得作为延迟实现的理由。迁移/共享合同 owner 从 B/C 的资深人员中具名指定，但其受保护容量不得被功能开发占用。

容量不足时按以下规则处理：

1. 人工可用性短缺时，先移除三个首批消费者 surface 之外的扩展、managed-account 可选 cohort、非关键 UI polish 和其他明确 optional 项；Secret、备份、迁移、统计正确性、三个首批 surface 合同和真实归因旅程不得降级。
2. 人工授权、明审或独立签字不可用时，相关 Gate 标记 `BLOCKED_EXTERNAL` 并保留缺口；Agent 继续推进不依赖该签字的实现与自动化验证，不暂停或串行化 `T+0`--`T+5` 时钟。
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

- 每个交付日：Agent 更新稳定 ID 的状态、剩余依赖、预算消耗、live 配额和新增风险；只链接证据，不在工作记录中替代 evidence manifest。
- 每个波次：先合并线性 migration/共享合同，再合并 Domain、Application/Repository、API/Worker、Admin/Customer 和验收证据；跨层未闭合的功能保持 feature flag 关闭。
- `T+4`：执行 release candidate、数据对账、性能趋势和故障演练；`T+5` 专用于复查、修复、最终 evidence 汇总和退出评审。
- 波次退出评审：owner 提交 `READY_FOR_REVIEW`，verifier 按 `GATE-M*` 与 `EXT-GATE-M*` 逐项复核。任一必需项失败则该波次不进入 `ACCEPTED`。
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

### 8.3 前半段合同可追溯 checklist

第 2--8 节定义的是产品和工程合同，不能只靠后文某个宽泛的波次任务间接覆盖。以下 checklist 为这些合同提供稳定验收锚点；每项 evidence manifest 都必须记录实现工作包 ID、`work_package_type`、capability flags、DoR/DoD applicability、commit、migration/OpenAPI/adapter release、测试或 live run、artifact hash、Project/Campaign/environment scope 与 owner/verifier 签字。

“最早批次”表示不得晚于该批次完成合同实现或形成受控降级，不表示可以绕过依赖 Gate。依赖 Connector、Provider、消费者 UI 或澳洲出口的项，主计划只核对本项与专项 `EXT-*` 证据的映射，不复制专项逐源完成状态。当前迭代不实施工作流 B；`B-CONTRACT-*` 保持 `[ ]` 和 `EXCLUDED_B_FOR_CURRENT_ITERATION`，不得因此阻塞非 B 代码验收，也不得从路线图删除。

| 合同范围 | Checklist ID | 最早批次 | 最终验证入口 |
|---|---|---|---|
| 边界、授权、版本和证据 | `FND-*` | M0--M1 | `GATE-M0/M1`、`REPO-GATE-*` |
| Prompt、Gateway、Secret、Job、工件 | `SHARED-*` | M1 | `M1-AC-*`、`CORE-*-AC-*` |
| 合成实验室 | `SYN-CONTRACT-*` | M1--M3 | `LAB-*-AC-*`、`M2/M3-AC-*` |
| 连接器与归因 | `B-CONTRACT-*` | M1--M5 | `EXT-GATE-M*`、`ATTR-*-AC-*` |
| 采样、统计和告警 | `C-CONTRACT-*` | M1--M4 | `EXT-*`、`STAT-*-AC-*`、`M4-AC-*` |
| 建议与 Customer 投影 | `D-CONTRACT-*` | M5 | `REC-*-AC-*`、`M5-AC-*` |

**跨工作流与不可变边界**

- [ ] `FND-BOUND-01` 将第 2.1/2.2 的包含范围、明确不做项、人工审核/发布边界和 B 轨降级限制固化为 capability policy；任何 route、Worker、导出或 feature flag 违反时 fail closed。最早 M0；验收：M0 policy hash、负向 API/Worker 测试和 `M6-AC-07` 复核。
- [ ] `FND-VIS-01` 将第 2.3 真实性/可见性矩阵实现为不可变 `capture_method`、source kind、分母和 Customer eligibility 规则；未知来源只能为 `unknown/ineligible`，不得通过迁移或 UI 标记提升。最早 M1；验收：跨 method/source 的 RLS、统计输入、导出和 Customer 负测，以及 `M2-AC-05`、`M5-AC-03`。
- [ ] `FND-AUTH-01` 为所有自动访问的风格渠道与消费者 surface 实现版本化 authorization record、A/B 轨、到期/撤销和同事务 admission；无有效 `approved` 时产生零 Job/零 outbox。最早 M1，首批真实 admission 不晚于 M2；验收：`M2-AUTH-01`、`M2-AC-07` 和专项授权证据。
- [ ] `FND-VERSION-01` 将 Project/Campaign、Prompt/Profile/Fact/QuestionSet/Corpus、adapter release、schema/method、输入/输出与 artifact 的 ID/version/hash 作为每个 durable command 的冻结 lineage；重试和回放不覆盖历史。最早 M1；验收：replay、stale、cross-Project 和 hash recompute 负测。
- [ ] `FND-CUSTOMER-01` 将“Customer 只见 approved、真实、current、字段白名单内的数据”实现为持久化投影规则，不允许前端自行推断 latest/eligible，也不回退到 raw 或 memory fixture。最早 M1，M5 完成产品投影；验收：`M1-BASE-01`、`M5-CUST-01`、`M5-AC-03/07/08`。
- [ ] `FND-EVIDENCE-01` 每个稳定 ID 建立可读取 evidence manifest 映射；N/A 记录由独立 verifier 批准，外部 live、fixture、人工明审和恢复证据不能互相替代。最早 M0；验收：`M0-EVD-01`、`M0-AC-05` 和 `M6-EVD-01`。
- [ ] `FND-CHANGE-01` 对 scope、样本量、统计门槛、provider/surface、权限或 capability flag 的变化实行批准的 change record、影响 ID 映射与回滚计划；实现 PR 不能隐式改写基线。最早 M0；验收：波次审计和 `M6-EVD-01`。

**共享基础合同**

- [ ] `SHARED-PROMPT-01` 建立八类首批 Prompt Program 的 create/test/diff/approve/freeze/bind/retire 生命周期；每次运行冻结 compiled hash、变量 hash、schema、模型策略和业务输入版本。最早 M1；验收：`M1-PROMPT-01`、`M1-AC-01` 与 Prompt 迁移/API/Worker 回归。
- [ ] `SHARED-GATEWAY-01` 以统一受治理 request/result/error/policy 合同接入 DeepSeek、OpenAI、Kimi、Gemini、Perplexity 和 Microsoft；结构化输出后仍执行应用层领域校验，禁止静默 fallback。最早 M1；验收：`M1-MODEL-01/AC-02`、`REAL-MODEL-AC-01`。
- [ ] `SHARED-GATEWAY-02` 每个 adapter release 冻结供应商存储、缓存、展示和再分发约束；原始结果只在条款允许时按保留窗口/加密引用保存，条款冲突时 release 不可用。最早 M1；验收：adapter policy review、provider artifact negative tests 和 live release evidence。
- [ ] `SHARED-SECRET-01` Secret Store 实现项目范围 envelope encryption、reference version、审计、redaction、轮换/撤销和缺主密钥 fail-closed；任何 Job/outbox/log/API/artifact/浏览器响应均不得含明文。最早 M1；验收：`M1-SECRET-01`、`M1-AC-03`、`CORE-SECRET-AC-01`。
- [ ] `SHARED-SECRET-02` 备份外历史 keyring/escrow、双保管人、逐 key canary、旧 ciphertext rewrap 和空环境代表性 secret 解密/connection test 均可复核。最早 M1，真实凭据进入前必须通过；验收：`M1-SECRET-02/AC-04`、`CORE-SECRET-AC-02`、`M6-RESTORE-01`。
- [ ] `SHARED-JOB-01` 所有本阶段外部或长任务复用 Durable Job、lease、heartbeat、fencing、cancel、outbox 和 immutable artifact manifest；外部 I/O 前后均检查当前 lease/授权/secret 状态。最早 M1；验收：`CORE-JOB-AC-01`、每类 operation 的 replay/cancel/lease-loss 负测和 `REPO-GATE-02`。
- [ ] `SHARED-RAW-01` 在首次真实登录或浏览器采集前实施第 4.5 节分类、落盘前脱敏、受限 bucket/DEK/RBAC、TTL、legal hold、tombstone 和 Customer/export 拒绝；`secret_bearing_rejected` 永不落盘。最早 M1；验收：`M1-SYN-02/AC-05`、`CORE-RAW-AC-01`、五桶恢复和 MinIO 负测。
- [ ] `SHARED-COMPAT-01` 任何共享 schema/API/worker composition 变更遵守单一 Alembic head、expand/compatible writer、追尾/对账、forward-fix 与 rollback 合同；不以本地人工 SQL 或 fixture 代替。最早 M0，持续至 M6；验收：`M0-AC-04`、`M6-MIG-01/02`、`REPO-GATE-03`。

**工作流 A：内部合成测评实验室**

- [ ] `SYN-CONTRACT-01` 按第 5.1 节实现 Style Source、Collection Run/Sample/Profile、Review Suite/Case/Run、Candidate/Evaluation/Revision、Corpus 与 Offline Experiment 的项目范围状态机、版本和 immutable lineage。最早 M1；验收：`M1-SYN-01`、迁移/RLS/API/Admin tests。
- [ ] `SYN-CONTRACT-02` 每个渠道的公开、正常登录和人工导入路径共享授权、分类、去重、匿名、AU English 与人工明审门槛；登录凭据仅可用 Secret Reference。最早 M1，样本完成不晚于 M3；验收：`M1-SYN-02`、`M2-SYN-01`、`M3-SYN-01`、`REAL-STYLE-AC-01`。
- [ ] `SYN-CONTRACT-03` Style Profile 只能从审核通过的匿名样本构建；Profile Release 绑定 corpus/Prompt/reviewer/hash，不可原地修改，未批准 Profile 不能启动正式 Review Run。最早 M2；验收：`M2-SYN-02`、`M2-AC-02`。
- [ ] `SYN-CONTRACT-04` `autonomous_scenario` 与 `guided_scenario` 都把 Fact/Catalog 身份作为权威输入；运营输入仅作创意参考，每 Case 默认四候选并完整保存 generation lineage。最早 M2；验收：`M2-SYN-03/04`、`M2-AC-03`。
- [ ] `SYN-CONTRACT-05` Claim extraction、conflict/subject check、style judge/arbiter、至多两轮 revision、一次 regenerate、warning 与 Fact 失效/cancel/lease-loss 终态遵循第 5.3 节。最早 M3；验收：`M3-SYN-02`、`LAB-FLOW-AC-01`、`M3-AC-02/03`。
- [ ] `SYN-CONTRACT-06` Corpus Version 与 baseline/current/candidate 三臂 Offline Experiment 以相同冻结输入、每题每臂 10 次、warning 独立分层和可重算 hash 运行；synthetic 永不进入真实 Observation/Customer。最早 M3；验收：`M3-SYN-03/04`、`M3-AC-04`、`LAB-CUST-AC-01`。
- [ ] `SYN-CONTRACT-07` 九平台 360 Case 和逐平台 `passed>=95%`、主体串用/防复刻为零、风格均值和人工 rubric 签字均按平台独立计算，禁止总体平均掩盖单平台失败。最早 M3；验收：`LAB-SET-*`、`LAB-REL-*`、`M3-AC-01`。

**工作流 B：连接器和本地归因（专项映射，当前实施排除）**

- [ ] `B-CONTRACT-01` Connector Definition/Connection/Scope/Checkpoint/Sync Run/Raw Artifact/Schema Version/Projection/Freshness/Error 的真源、checkpoint、回刷、schema drift、撤权和 raw-to-projection 一致性只按专项 `EXT-CONN-*` 实现与验收。最早 M1；验收：`EXT-GATE-M1..M6`、`CORE-RAW-AC-01`。
- [ ] `B-CONTRACT-02` GSC、GA4 与 Google/Bing official report 是独立 typed projection；Adapter Release 或 sync/import 成功不能直接 Customer 可见，必须经过 immutable External Data Snapshot/Report 的独立数据批准生命周期。最早 M2；验收：`EXT-*`、`M5-AC-07`、`REAL-EXT-AC-02/04`。
- [ ] `B-CONTRACT-03` 一方事件入口是 Session/Touch/Conversion 真源；GA4 仅用于聚合对账，技术上不得创建 Session/Touch。UTM 与无 PII trace token 必须关联 Campaign、QuestionSet、Package Version 和 verified URL。最早 M4；验收：`M4-ATTR-01/02`、`M4-AC-06`。
- [ ] `B-CONTRACT-04` Attribution Policy Version 冻结 30 天 last-click、90 天 assisted、direct/first/last/assisted、cutoff/迟到规则；Revenue 缺少强关联时只可为 `unassigned`，禁止概率跨设备和零点击转化。最早 M5；验收：`M5-ATTR-*`、`ATTR-*-AC-*`、`M6-ATTR-01`。

**工作流 C：跨引擎采样、统计和告警**

- [ ] `C-CONTRACT-01` Sampling Suite/Run/Task/Attempt/Observation 的 stable identity 只包含冻结 source stratum、release、问题、重复槽位和区域/语言；每次实际 egress verification 仅属于 Attempt/Observation lineage，不能拆分 planned denominator。最早 M1；验收：专项 `EXT-SAMP-*`、`STAT-STRATUM-AC-01`、`STAT-EGRESS-AC-01`。
- [ ] `C-CONTRACT-02` AIO、AI Mode、Bing Copilot 与后续消费者 surface 的自动采样只在有效授权和粘性澳洲 egress session 下执行；每个 Capture bundle 必须有前/后地域证明或可信代理连接日志，阻断即停止。最早 M2；验收：专项 `EXT-UI/EXT-EGR-*`、`REAL-EXT-AC-03`。
- [ ] `C-CONTRACT-03` Provider API、proxy grounded API、automated UI、manual UI、official report 与 synthetic 始终使用独立 source/capture denominator；每个 Surface Release 自身满足保真度阈值，不借用其他 release 样本。最早 M2；验收：专项逐 release evidence、`STAT-SAMPLE-*`、`STAT-UI-AC-01`。
- [ ] `C-CONTRACT-04` 指标按规则优先、必要时 metric judge/arbiter，持久化 span/citation/Fact locator、invalid/missing 和 source diversity；输出可回溯到 frozen Observation 而不暴露 raw。最早 M4；验收：`M4-METRIC-01`、recompute/negative tests。
- [ ] `C-CONTRACT-05` Wilson/Newcombe、deterministic paired bootstrap、Holm、family、`delta/power/precision/min_pairs`、胜/等效/负/不确定/不足证据和跨问题负收益按第 7.4 节冻结并可重算。最早 M4；验收：`M4-STAT-*`、`M4-AC-01..04`、`STAT-METHOD-*`。
- [ ] `C-CONTRACT-06` 告警从冻结观测、统计、freshness 或 connector/provider/source drift 生成；确认、抑制、解决、处置、Admin inbox、SMTP、签名内网 Webhook 与重试均不重复建单、不回滚业务事实。最早 M4；验收：`M4-ALERT-*`、`M4-AC-05/07`。

**工作流 D：建议与批准后草稿**

- [ ] `D-CONTRACT-01` 六种 Recommendation 均绑定真实 Observation、Statistic、Attribution、Fact、规则和 Prompt Release；`no_change`/`insufficient_evidence` 是可解释正常终态，不能为生成建议而强行给方向。最早 M5；验收：`M5-REC-01`、`REC-TYPE-AC-01`。
- [ ] `D-CONTRACT-02` Recommendation 从 approved 进入 stale/expired 时原子阻断关联未执行草稿、取消未投递 outbox/未开始 Job；任何后续执行前都重新锁定并校验 approved version。最早 M5；验收：`M5-REC-02`、`M5-AC-04/05`、`REC-STALE/REC-BYPASS-AC-*`。
- [ ] `D-CONTRACT-03` 人工批准只创建 Experiment Plan、QuestionSet、Content Brief 或 Sampling Plan 幂等草稿；不得自动 enqueue、生成、执行、创建 Publication Request 或发布。最早 M5；验收：`M5-DRAFT-01`、`REC-BYPASS-AC-01`。
- [ ] `D-CONTRACT-04` Customer 只读取批准且未 stale/revoked 的白名单投影；Workflow C、External Data Report、legacy Monitoring Report 的批准状态机彼此独立，未批准/raw/internal recommendation/debug 永不泄漏。最早 M5；验收：`M5-CUST-01`、`M5-AC-03/07/08`。

## 9. 分阶段实施计划和 checklist

`M0`--`M6` 是有依赖关系的稳定交付标签，不是月份，也不可以绕过退出门槛。每个阶段先满足进入条件，再执行工作包，最后通过阶段 Gate；未通过的阶段继续修复，依赖它的工作包不得用临时 fixture 或手工数据库写入冒充完成。

`M0` 在 `T+0` 完成基线冻结，随后波次按下表连续推进。外部资源准备长期未完成不会延长 Agent 实现窗口，也不能降低 M6 门槛；它只使相关 Gate 保持 `BLOCKED_EXTERNAL`，直至真实证据补齐。

### 9.1 阶段总表和关键路径

| 阶段 | 连续窗口 | 主题 | 必须先通过 | 关键输出 | 阶段 Gate |
|---|---|---|---|---|---|
| M0 | `T+0` | 启动与基线冻结 | 无 | 人力、资源、授权、预算、迁移和证据基线 | `GATE-M0` |
| M1 | `T+0--T+1` | 共享基础与采集骨架 | `GATE-M0` | Prompt、Gateway、Secret、合成/外部领域骨架、性能基线 | `GATE-M1` + `EXT-GATE-M1` |
| M2 | `T+1--T+2` | 首批真实数据与五平台测评 | M1 shared contracts | 五平台 Profile、生成 Beta、GSC/GA4、消费者 UI Beta | `GATE-M2` + `EXT-GATE-M2` |
| M3 | `T+2--T+3` | 九平台闭环与多引擎发布 | M2 Profile/Sampling | 修订、Corpus、三臂实验、五类外部 API、三首批 surface release | `GATE-M3` + `EXT-GATE-M3` |
| M4 | `T+3--T+4` | 统计、告警与归因入口 | M3 frozen observations | 完整指标、统计比较、漂移/告警、一方事件入口 | `GATE-M4` + `EXT-GATE-M4` |
| M5 | `T+4` | 业务闭环与 Customer 投影 | M4 metrics/events | 归因快照、批准投影、建议与草稿阻断闭环 | `GATE-M5` + `EXT-GATE-M5` |
| M6 | `T+5` | 生产等价验收 | M1-M5 accepted | live staging、迁移、性能、故障、备份恢复和发布证据 | `GATE-M6` + `EXT-GATE-M6` |

关键路径为 `Secret/备份 -> Connector/Browser live -> frozen Observation -> Metric Snapshot -> Attribution/Recommendation -> Customer approved projection -> full-chain staging`。非关键 UI polish 可以按第 3.4 节降范围，关键路径中的真实性、安全、统计和恢复门禁不可降级。

### 9.2 M0：启动与基线冻结

**实施 checklist**

- [ ] `M0-GOV-01` 冻结第 3.4 节人工不可委托职责的具名分配、替补和 on-call；Agent 为工程实现与自动化验证 owner；证据：签字容量表。
- [ ] `M0-GOV-02` 指定唯一 Alembic owner、OpenAPI owner、release owner 和各工作流 verifier；证据：RACI 与 CODEOWNERS/评审规则映射。
- [ ] `M0-GOV-03` 在每项工作开始前为 M0 checklist ID 冻结 work package type、capability flags 及全部 DoR/DoD applicability；M1-M6 逐阶段沿用同一规则。
- [ ] `M0-RES-01` 建立真实资源清单：GSC、GA4、五类外部 API、三个消费者 surface、登录采集账号、澳洲代理、一方事件测试站点；只记录 reference/owner/状态，不记录 secret。
- [ ] `M0-AUTH-01` 为九个风格渠道和三个首批消费者 surface 建立 authorization record，记录待评审依据、用途、频率、到期日和 A/B 轨决策日期。
- [ ] `M0-BUD-01` 冻结 `T+0`--`T+5` 模型/API/代理/存储预算、供应商配额、成本告警和预算耗尽的缩范围顺序。
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
- [ ] `M1-SYN-02` 实现人工样本导入、公开/正常登录采集、落盘前分类/脱敏/加密/TTL 和去重骨架；raw 与 derived 必须落到隔离 bucket，认证备份/空环境恢复必须把业务、Recommendation、Workflow C、Synthetic raw、Synthetic derived 五桶逐一镜像、计数并用固定 bucket-to-reader allowlist 复核。冻结九平台 360 Case 的 schema。真实自动采集只有在渠道已有有效 `approved` 时执行，否则只跑 fixture/人工导入。
- [ ] `M1-EXT-01` 完成专项文件全部 `EXT-M1-*`，包括 Connector/Sampling/Browser/Egress 骨架和三个 surface parser fixture PoC。
- [ ] `M1-QA-01` 为共享合同建立 architecture/unit/PostgreSQL/MinIO/Valkey/OpenAPI/Chromium 测试入口，并证明必需测试零收集/意外 skip 会失败。
- [ ] `M1-PERF-01` 冻结第 10.7 节 `performance-profile-v1`、负载生成器合同、生产等价拓扑和资源上限。

**退出 Gate `GATE-M1`**

- [ ] `M1-AC-01` 同一固定输入可比较两个 Prompt Release；approved Release、compiled prompt、binding 和 hash 不可原地变更，历史 Job 可复现。
- [ ] `M1-AC-02` 至少三个真实模型 smoke 成功；错误 JSON/enum、schema、主体和 Fact 引用被应用侧拒绝，provider fallback 不会静默发生。
- [ ] `M1-AC-03` 测试 secret 在数据库可见字段、Job/outbox、日志、exception、MinIO、API 和浏览器中零明文命中；撤销旧 reference 后调用 fail closed。
- [ ] `M1-AC-04` 空环境恢复全部在用 key-version canary、代表性 secret 和不泄密 connection test；错误/缺失 key 必然失败。
- [ ] `M1-AC-05` 一个公开 Style Source 和一个正常登录 Style Source 通过已批准自动路径或合规人工导入产生匿名派生样本；Cookie/token/PII 不落普通 bucket，raw/derived 不能跨 bucket 读取，且五桶恢复在未知 bucket、跨 bucket URI、缺失挂载时 fail closed；未批准自动访问、验证码/封禁路径停止。
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
- [ ] `M5-CUST-01` 实现三条相互独立的 Customer latest 投影：回答型 **Workflow C Approved Report Snapshot**、既有 approved Monitoring Report 与非回答型 approved External Data Report。Workflow C 以不可变 semantic snapshot 和 approved-safe payload 创建 `draft -> in_review -> approved -> stale|superseded|revoked` 的独立 Report 状态机，禁止复用 legacy Monitoring Report 的批准作为其数据批准；来源/分母/区间/warning/非因果标签和字段白名单冻结。无数据批准、不足证据、`manual_ui`、`synthetic`、未批准或非 current 状态时返回明确空状态。
- [ ] `M5-REC-01` 实现 Recommendation evidence graph、六种类型、Prompt/Fact/Metric/Attribution lineage、人工 review/approve/reject。
- [ ] `M5-REC-02` 实现 `approved -> stale|expired`、输入版本再校验，以及所有关联草稿的事务内 blocked propagation。
- [ ] `M5-DRAFT-01` 实现 Experiment Plan、QuestionSet、Content Brief、Sampling Plan 幂等草稿；批准不 enqueue、不生成、不执行、不发布。
- [ ] `M5-EXT-01` 完成专项文件全部 `EXT-M5-*`：外部来源批准投影、运营控制面和 runbook 达到稳定状态。

**退出 Gate `GATE-M5`**

- [ ] `M5-AC-01` fixture Revenue 可逐跳回溯到 GEO 内容版本；任一强关联缺失时明确 `unassigned`，不使用 IP/UA/时间邻近填补。
- [ ] `M5-AC-02` 30/90 天窗口边界、direct/first/last/assisted、重复/迟到、跨设备拒绝和零点击隔离都有确定性 golden fixture。
- [ ] `M5-AC-03` Customer 无法读取 synthetic、未批准/不足证据、内部建议、raw answer/page、secret、内部 actor 或 debug 字段。
- [ ] `M5-AC-07` GSC/GA4/official-report 的 sync/import/Adapter Release approval 都不能直接提升 Customer 可见性；只有绑定 exact immutable snapshot 的 approved External Data Report 可见，stale/superseded/revoked 立即退出 latest。
- [ ] `M5-AC-08` Workflow C Customer reader 只读取自身 immutable approved Report Snapshot，且每条均证明 semantic snapshot=`complete`、完成度达到冻结门槛、所有 Observation 非 `synthetic`/非 `manual_ui`、approved-safe payload hash 和 Project/Campaign lineage 完整；`draft`、`in_review`、`insufficient_evidence`、`stale`、`superseded`、`revoked`、raw artifact 和 legacy Monitoring Report 绑定均不得通过该 reader 返回。
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

### 11.2 波次证据包

每个交付波次退出评审保存一个不可变 evidence manifest，至少包含：

- Git commit、migration head、OpenAPI manifest 和 Web build IDs。
- 每个 check ID 自身的 work package type/flags、逐条 DoR/DoD applicability、开始/结束时间、Git commits、migration revisions、OpenAPI contracts 和 `not_applicable` 独立批准；顶层汇总字段不能替代单项映射。
- Prompt/Profile/adapter/schema/method release IDs 与 hashes。
- 测试命令、收集数、通过/失败/skip 数和关键报告 URI/hash。
- 每个 check ID 自身的 Project/Campaign/environment fingerprint、live run IDs、脱敏 account/connection refs、原始工件 manifest 和人工审核记录；不适用的 scope 必须按第 1.3 节留痕。
- 迁移 writer 清单、双写/outbox lag 或停写窗口、initial/final watermark、逐 Project/Campaign 对账和 rollback-window 证据。
- 备份权限/加密报告、数据备份与历史 keyring 的独立恢复记录、逐 key-version canary、代表性 secret connection test 和明文扫描结果。
- `performance-profile` 版本、冻结负载/拓扑、实测延迟/队列年龄/资源水位及原始报告 URI/hash。
- 真实归因旅程的 consent/业务授权引用和脱敏逐跳 lineage；不保存参与者 PII 或支付凭据。
- 未完成项、已知偏差、成本/耗时、告警和下一波次依赖。

只有 evidence manifest 完整且退出门槛逐项签字，波次状态才能从 `IN_PROGRESS` 变为 `ACCEPTED`。功能“页面可见”或 mock 测试通过不构成批次完成。

## 12. 主要风险和控制

| 风险 | 早期信号 | 控制/退出条件 |
|---|---|---|
| 四工作流争用共享 schema | 多 Alembic head、枚举反复冲突 | 单迁移 owner；共享合同先行；每波次 contract freeze |
| Provider API 被误解为消费者 UI | API 结果使用 ChatGPT/AIO/Copilot UI 名称 | `provider_api`/`automated_ui` 强类型分离；页面证据和 UI/导出负测 |
| 消费者 UI 自动采样缺少平台允许依据 | 无 authorization record、条款过期或用途超范围 | 先决策后采集；enqueue 同事务 admission，失败零 Job/outbox；claim/导航前复验；最晚 `T+2` 强制 A/B 结论；代理不能替代授权 |
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

若真实账号、预算或其他用户侧资源未在对应波次就绪，应把相关里程碑标记为 `BLOCKED_EXTERNAL` 或 `IN_PROGRESS`，不得以 mock、人工描述、降低样本量或合并分母改写为完成。平台授权不适用无限期 `BLOCKED_EXTERNAL`：按第 2.4 节授权决策点最晚 `T+2` 强制出结论并落入对应轨道。

## 13. 加速实施完成后的技术展望

下一阶段进入“成熟传统 SEO + GEO 统一平台”，按以下顺序扩展：

1. 多域名站点库存、抓取、渲染 DOM 和索引资格。
2. robots、canonical、Sitemap、结构化数据、WAF 和 AI bot 用途策略。
3. 关键词、排名、搜索意图、内容缺口、页面质量和竞品覆盖。
4. 内链、外链、站外权威、Feed、IndexNow 和抓取时效。
5. CMS 草稿/发布连接器、Agent 任务完成率和全面治理。
6. 统一实验与归因控制面，同时保持 Organic Search 与 Generative Engine 的独立指标、来源及分母。

本加速实施计划的数据模型预留中性的 `Query`、`Surface`、`Content Asset`、`URL`、`Experiment` 和 `Recommendation` 分类。GEO 专属字段通过 typed extension/projection 表达，不把 `query=prompt`、`surface=AI provider` 或 `content asset=Package` 写死在共享身份中。这样未来加入完整传统 SEO 能力时可以复用项目、Campaign、版本、实验、归因和建议链路，而无需重写核心主键或历史 lineage。

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

## 15. 最终发布 checklist

本节是最终 Go/No-Go 索引，不替代前述细项。release owner 只能在被引用的原始 check ID 已有证据和签字后勾选，不能只凭本节的汇总勾选反向宣称完成。

### 15.1 阶段和范围

- [x] `PLAN-TIME-01` 本文件和专项计划均已将传统月度排期替换为 `T+0`--`T+5` 连续交付；`M0`--`M6` 及所有 `GATE-*`/check ID 保持不变，外部证据仍按原门槛并行验收。
- [ ] `PLAN-FINAL-01` `GATE-M0` 至 `GATE-M6` 全部 `ACCEPTED`，每个波次 evidence manifest 的 URI/hash 可读取。
- [ ] `PLAN-FINAL-02` `EXT-GATE-M0` 至 `EXT-GATE-M6` 与专项 `EXT-FINAL-01..08` 全部 `ACCEPTED`。
- [ ] `PLAN-FINAL-03` 五个业务板块均达到第 1 节完成定义；所有降范围均有批准 change record，未修改真实性/安全/统计门槛。
- [ ] `PLAN-FINAL-04` 人力、预算、授权、账号和 live 资源的最终状态记录完整，无用 mock 掩盖的 `BLOCKED_EXTERNAL`。

### 15.2 产品和数据正确性

- [ ] `PLAN-FINAL-05` `LAB-*` 全部通过：九平台、360 Case、发布门槛、修订/Warning/Fact/lease 路径和 synthetic 隔离完成。
- [ ] `PLAN-FINAL-06` `REAL-*`、`CORE-*` 与专项逐源 AC 全部通过：GSC/GA4、官方报告、五类 API、三个消费者 surface 和澳洲出口证据完成。
- [ ] `PLAN-FINAL-07` `STAT-*` 全部通过：冻结分母、区间/校正、`inconclusive`、负收益、漂移、版本/hash 和 Warning 分层正确。
- [ ] `PLAN-FINAL-08` `ATTR-*` 全部通过：30/90 天、direct/first/last/assisted、零点击/跨设备边界和真实 Revenue 旅程完成。
- [ ] `PLAN-FINAL-09` `REC-*` 全部通过：证据图、六种类型、人工批准、stale/expired 传播和下游草稿执行前阻断完成。
- [ ] `PLAN-FINAL-10` Customer 只见 latest approved Workflow C Report Snapshot、approved Monitoring Report 或 approved External Data Report；synthetic、`manual_ui` Workflow C 输入、raw、未批准/stale/revoked/不足证据、secret、内部建议和 actor/debug 字段全不可见。

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

## 16. 当前实施状态账本

> 快照日期：2026-07-23。此表是实现推进账本，不是 evidence manifest，也不替代第 9、10、15
> 节的原始 checklist。根据第 1.1 节语义，下面任何 `IN_PROGRESS`、`BLOCKED_EXTERNAL` 或
> `EXCLUDED_B_FOR_CURRENT_ITERATION` 都不能勾选原有 `[ ]`，更不能作为 `GATE-M*`、`EXT-GATE-M*`
> 或最终 `GO` 的依据。

| 实施范围 | 当前状态 | 已有仓库内证据（尚未构成最终验收） | 完成前仍需事项 |
|---|---|---|---|
| `IMPL-NONB-SHARED` Prompt Program、Model Gateway、Secret Store、Durable Job/工件 | `IN_PROGRESS` | 双 portable/application schema、六 Provider adapter、Secret 加密/轮换、七 keyring 和受限工件 contracts；通用 Worker 启动时已合并 Prompt、Synthetic、Recommendation 和 Workflow C 四个 builder，缺任一 handler/依赖即 fail closed，并有 composition 回归。0032 的 `workflow_c_job_specs` 与 `durable_jobs.input_hash` 一对一绑定；0034 的受控 producer RPC 在同一事务写入 Job、Spec、Outbox 和 enqueue event，应用角色只能执行 RPC、Worker 只读 Spec。resolver 验证当前 Project/lease/fence、kind、canonical hash、schema version 和递归敏感字段。Workflow C 现由单一 production composer 精确注册两类 Sampling、三类 analysis、两类 metric child 和三类 alert/notification PostgreSQL operation；composer 会在任一 builder、keyring 或通知 transport 不可用时失败，绝不注册 no-op。2026-07-23 正常模式认证恢复 Gate 在独立 Docker 项目中完成 PostgreSQL ACL/RLS canary、冻结 Secret handle/HMAC receipt、五个工件 bucket、各 keyring 与错误/缺失 key 拒绝，receipt SHA-256 为 `8860d11486a9990a6103a089dc373f34a52d3a9bfde7759921fa4aa8cff61bc1`，manifest SHA-256 为 `428f1038fc49f66f44fa2e95265ea8484a3b19a250d4614bf6c8cb26e6683f01`；`tests/unit/prompts`、`tests/unit/model_gateway`、`tests/unit/secrets` 与 backup/infra 回归 | 为十类实际 Workflow C admission/producer 完成隔离 PostgreSQL/MinIO integration；完成真实数据迁移、独立审阅、真实模型/secret canary 与 evidence manifest |
| `IMPL-A-SYNTHETIC` Style Collection、Profile、Review、Revision、Corpus、Offline Experiment | `IN_PROGRESS` | 九渠道固定 workload、手工样本导入 maker/checker、原始工件治理、候选/修订/三臂实验 domain 与测试；Style raw/derived 已拆为隔离 bucket，认证备份 manifest/verify allowlist 已纳入业务、Recommendation、Workflow C、Synthetic raw、Synthetic derived 五桶，恢复 probe 使用固定 bucket-to-reader map；2026-07-23 正常模式认证恢复 Gate 已逐桶镜像、count/hash、恢复挂载并以固定 reader 复核；Synthetic retention 已有项目范围 stage/claim adapter、独立 deletion-only Worker、Relay 原子 Durable Job/outbox 调度与专用 queue，且 Worker 不挂 keyring；隔离 PostgreSQL 已从 scheduler 到 fenced Worker 完成一个项目的 crypto-erasure、DEK 销毁、对象删除记录和 tombstone，同时另一项目保持 pending；同一隔离库已验证 active legal hold 不可 claim、partial remote delete 后不重复 crypto-erasure 的 retry，以及失效删除 lease 被 fenced；`M1-SYNTH-WEB-01..03` 验证 Style Collection admission 的服务端 Job 身份、排队/取消状态、fail-closed 和 409 路径 | Production model-child admission/Worker 完整接线、隔离 MinIO retention、并发 wake/最小化凭据、人工审核、正常登录账号与 360 Case/live 证据 |
| `IMPL-C-SAMPLING-STATS` Provider API Sampling、语义指标、统计、漂移、告警 | `IN_PROGRESS` | 固定分母、`inconclusive`、Wilson/Newcombe/bootstrap/Holm、typed metric locator、Workflow C 双 bucket/crypto erase、SMTP/Webhook contracts；`workflow_c_job_specs` 的 comparison/drift/semantic decoder 会重建完整冻结分层输入。0034 producer RPC 已以十种允许 kind 的有效 schema v1 载荷在隔离 PostgreSQL 验证原子 Job/Spec/Outbox/event、重放、UTF-8 canonical hash、敏感字段拒绝和 App 直读/直写拒绝。`sampling.provider_execute`/`.manual_import`、`workflow_c.analysis.semantic_metrics`/`.comparison`/`.drift`、`workflow_c.metric_judge`/`.metric_arbiter` 与 `workflow_c.alert.schedule`/`.evaluate`/`.notify` 均已有实际 PostgreSQL Worker operation，并由 production composer 精确注册为十种 kind。Sampling 和 metric child 复核 Project、lease/fence、冻结 Prompt/runtime/schema；metric child 只经 Worker-only fenced RPC 终结。0037 修复 Workflow C 受限工件 tombstone RPC 的 output-column 歧义；0038 将 Sampling admission 的五态 maker-checker 生命周期、冻结 runtime option、项目范围 create/transition RPC 和 command ledger 落入 PostgreSQL，撤销 App 对策略/ledger 的旁路写入；隔离 `geo_app` 登录已验证 draft/submit/独立 approve/revoke、幂等回放、跨 Project scope 拒绝和直写拒绝。0039 将人工 `acknowledge/suppress/unsuppress/resolve` 收敛到受 RLS、version fence 和 command hash 约束的 RPC；每个新处置与三通道 notification、notify Job、immutable spec 和 outbox 同事务提交，且 App 角色无法直接写 alert/disposition/notification 表。0040 将 immutable Suite input 与 Suite create 收敛为两个 Project-scoped RPC。0041--0045 已完成 Run reservation、Provider Attempt/Job/Spec/outbox producer、claim/retry、取消、dead-letter 与 expired-lease fence 的持久化收敛；0046--0047 则完成受治理手工工件与 maker/checker 手工证据 admission。0052--0053 将 Provider question text/hash、Prompt binding/state/release/bundle/schema、runtime selection、deadline 和 Suite binding 置于独立 immutable registry，并在新 Provider Suite/Attempt 两个写入边界复核，旧未绑定 Suite 只能读取。0054 再以受限 schedule wrapper 保留 deferred `requested_not_before`，撤销 App 对旧无调度 RPC 的执行权限；typed producer control 仅按 registry、Run admission、Task version 与 Suite source 重建 spec。隔离 PostgreSQL/真实 MinIO 已验证 project-scoped scheduler/job/outbox、worker claim、DEK crypto-erasure、对象删除、partial-delete retry/tombstone、active hold 保留与跨 Project 不触碰；0047 另以公共控制层验证手工提交/批准/拒绝/重放与有数据降级拒绝。告警通知使用独立 lease、外部 I/O 无数据库锁，取消/lease loss 原样上抛；Admin Inbox 只持久化 whitelisted summary、hash 和幂等身份。该实现不包括本轮排除的消费者 UI capture；focused unit、migration contract、Ruff 与 mypy 已通过，尚未完成其余隔离 integration/live 证据 | 完成持久化 Internal API 组合与每类实际 admission/producer 的隔离 PostgreSQL/MinIO 集成，完成**项目范围持久化 maintenance schedule/seed、写入侧原子 Durable Job/outbox wake、按项目 claim（不得由 maintenance Job 自行全局发现 idle expiry）**、五 Provider live canary、外部专项与逐 release evidence |
| `IMPL-C-CUSTOMER-APPROVED-PROJECTION` Workflow C immutable approved report snapshot 与 Customer reader | `IN_PROGRESS` | 0032 的 append-only `workflow_c_report_snapshot_versions` 已冻结 `draft -> in_review -> approved -> stale|superseded|revoked`；0035 以同一 Report 的 transaction-scoped advisory lock 串行 application lifecycle，移除与 App 最小权限冲突的 `FOR SHARE`，并在 append trigger 内重检 Monitoring Report hash、semantic `complete`、独立 semantic approval、非 test/synthetic 及自动/API source kind。Customer reader 用每个 `report_id` 的 latest version 选择，只返回 `approved`，并拒绝 legacy Monitoring Report approval、`manual_ui`、raw、不足证据及 stale/revoked；Customer API 始终保留只读 projection 合同，缺 durable reader 时明确 `503`，绝不回退 memory；隔离 PostgreSQL 已验证 approved 可读、source 失效/stale 隐藏、审批重检、跨 Project RLS 和 direct-SQL incomplete source 拒绝 | 完成度门槛的持久化重检、独立 verifier 与 live evidence |
| `IMPL-D-RECOMMENDATION` 证据图、人工批准、stale/expired、下游草稿 | `IN_PROGRESS` | 六种建议、证据 graph、stale/blocked guards、portable/application Prompt 合同、独立工件生命周期与 unit 回归；0036 已将 Recommendation workflow 版本写入固定为 append-only，应用层以 transaction-scoped advisory lock 串行 lifecycle，数据库 trigger 仍拒绝 direct `UPDATE`；`insufficient_evidence` 仅可生成 `sampling_plan` 草稿，符合领域合同。durable Internal API builder 组合 PostgreSQL UoW、generation admission、受治理 runtime catalog 和 draft blocker，不存在 memory/provider fallback。隔离 PostgreSQL 以最小 `geo_app` 角色验证 create -> submit -> independent review -> approve -> draft、Fact 失效 -> expire/阻断 draft、Customer/API reader 读取及 direct UPDATE 拒绝；同库的 Recommendation generation submission 使用 frozen Prompt binding、当前 producer evidence 与确定性 approved-runtime selector，验证 Job/immutable Spec/Outbox/event/receipt 同事务创建和同键重放不增行 | Recommendation generation 的真实受治理 runtime/Worker、完整 Customer 负测、独立 verifier 与真实 Observation/Statistic/Attribution/Fact lineage |
| `IMPL-NONB-MIGRATION` 0027--0058、RLS、兼容/回滚 | `IN_PROGRESS` | 线性 migration ownership、SQL checksum/ledger、当前 SQL/RLS 实现；2026-07-23 空库隔离 PostgreSQL 已在含 0034 的完整链完成 `upgrade head -> downgrade 0029_model_gateway -> upgrade head`，并以 `head -> 0033_terminal_shape_guard -> head` 单独核对 0034 的 RPC/授权回退；0035 已由 Workflow C Customer projection RLS 集成验证，0036 已由 Recommendation lifecycle 的最小 `geo_app` integration 验证，0037 已以 Workflow C artifact real-MinIO 集成及 `0036 -> head` round trip 验证。0038--0047 已完成对应的隔离 PostgreSQL/真实 MinIO round trip；0048--0051 分别关闭 retention reclaim、scheduler concurrency 和 Synthetic parent scope 的持久化边界。0052--0056 已在 head 下验证 Provider input/enqueue/bulk/cancel runtime；0057 已在空库执行 `upgrade -> 0056 -> head`，并在最小 App role 的隔离库验证 retirement 的 replay、ACL、旧 Suite enqueue/新 Suite 拒绝和有审计证据时回退拒绝。0058 已在最小 App role 的隔离库验证十种 Job kind 正向入队、嵌套 credential-like key 的直接 RPC 拒绝和 `head -> 0057 -> head`。当前唯一 Alembic head 为 `0058_wfc_spec_sensitive`。重放后 `workflow_c_job_specs` 为 FORCE RLS，App 无直读/直写权限、只能执行受控 producer RPC，Worker 仅 SELECT；0038 还撤销 App 对 Sampling policy/command ledger 的写入，仅授予两个 scoped RPC；0039 撤销 App 对 alert/disposition/notification 表的写入，仅授予项目范围处置 RPC；0040 撤销 App 对 Suite input/Suite 的直接写入，仅授予两个 scoped RPC；0047 撤销 App 对 manual import 的直接写入，仅授予 scoped submit/review RPC。Alert enqueue/complete 与 Metric child complete/fail 均只授予 Worker，Admin Inbox 为 FORCE RLS（App 只读、Worker 仅读写）；不支持的 `connector_failure` 已从可持久化规则枚举移除。旧 global synthetic stage/claim 无 Worker EXECUTE 而 scoped overload 有 EXECUTE；Workflow C channel 为 `admin_inbox`/`local_smtp`/`internal_webhook`，三个 retry/terminal notification constraints 与 `last_attempt_at` 都已存在。认证恢复 Gate 以临时 `NOINHERIT` canary 显式切换至恢复后的 `geo_app`/`geo_worker`/`geo_readonly`，验证 scoped 可见、空 scope 隐藏和仅 Worker dispatch 权限。 | 完成全链 direct-SQL/RLS、真实数据兼容迁移、backfill/catch-up/rollback 演练 |
| `IMPL-NONB-PERF-FAILURE` 冻结性能和故障演练工具 | `IN_PROGRESS` | `performance-profile-v1-non-b`、deterministic workload、raw API RPS runner/validator、non-B fault scenario matrix、[非 B 性能运行手册](../operations/non-b-performance-runbook.md) | 隔离 staging 执行完整 30 分钟负载、汇总队列/工件/正确性测量、执行 Docker 故障演练并写入 evidence manifest |
| `IMPL-B-CONNECTOR-ATTRIBUTION` Connector Core、GSC/GA4、官方报告、消费者 UI capture、事件入口、归因账本 | `EXCLUDED_B_FOR_CURRENT_ITERATION` | 不在本轮写入或验证该范围；专项计划及主计划原始条目保持不变 | 获得单独恢复范围的用户指令后，按专项计划重新建立执行/证据状态 |
| 真实账号、授权、live staging、人工签字和最终发布 | `BLOCKED_EXTERNAL` | 无；fixture、mock、静态/单元测试均不计入 live evidence | 用户提供正确环境的账号、授权、预算、澳洲出口和独立 reviewer 后执行第 9--15 节既有 Gate/AC |

> 历史实施追记（2026-07-23，记录 `0048` 时状态；Alembic 当前 head 以本节最后一条校正为准）：表中 `IMPL-C-SAMPLING-STATS` 和 `IMPL-NONB-MIGRATION` 对 0040 的描述是此前快照。0041 已持久化 Run reservation 与完整 Task 分母，0042 已原子创建首个 Provider Attempt/Job/Spec/outbox/event 并只消费一次预留，0043 已将 Worker claim/retry claim 原子投影到 Attempt/Task 状态，0044 已以 fenced RPC 与 Durable terminal trigger 收敛 Provider Attempt/Run 取消及未消费预留释放，0045 再收敛 shared dispatcher 未预期失败和耗尽重试的 `retry_wait|failed|dead_lettered` 领域终态，0046 则对齐手工工件的 independent-DEK metadata 并将激活收敛到 scoped RPC；0047 进一步以 scoped submit/review RPC 将手工证据的 stage-to-active、独立复核、批准后的 Attempt/Job/Spec/outbox 原子创建和拒绝零 Attempt 统一到同一命令边界；0048 允许由 scoped claim RPC 以新 token、递增 fence/attempt 和延长 lease 接管超时 Synthetic deletion，而旧 lease 的 crypto/object terminal write 仍由 token/fence 拒绝。共享 Durable Store 的所有 terminal/defer 写入现要求数据库当前时间内的 lease，过期旧 Worker 无法 failure、cancel 或 complete；relay recovery 能重新派发并由新 fence 接管。相应隔离 `geo_app`/`geo_worker` 测试已验证 queued/running cancellation、replay、过期 lease 的 finalization/failure 拒绝与新 fence 接管、三次立即重试到 dead letter、Suite 重跑 Task ID 隔离与 `head -> 0039 -> head` 回退/重放；0046 已在空库完成 `head -> 0045 -> head`，并以真实 MinIO 验证 staged -> active 只能经 RPC、过期 crypto-erasure、payload/manifest 删除和 tombstone reader fail-closed；0047 则以真实临时 PostgreSQL/MinIO 验证提交与批准重放不增行、App 无 direct insert/spec read、批准恰建一条 Attempt/outbox、拒绝不建 Attempt。这些事实替代表内关于“Run/Attempt producer、取消仍待完成”和“head 为 0040”的表述，但不替代下列尚未完成的真实 Provider canary 与 evidence manifest。

> 历史实施状态校正（2026-07-23，记录 `0050` 时状态；Alembic 当前 head 以本节最后一条校正为准）：0049 在每个 Project 的 Synthetic retention lookup/create/wake 周围持有 transaction advisory lock，并将 wake outbox 的 conflict target 绑定为明确唯一约束；0050 以等价 Project lock 保护 Workflow C restricted artifact scheduler 的首次 Job 创建。空库分别完成 `head -> 0048_synthetic_retention_reclaim -> head` 与 `head -> 0049_synthetic_retention_lock -> head`；隔离 PostgreSQL 在两类 scheduler 的 Job insert 暂停竞争窗口中均验证两次并发调用只得到同一 Job、一次 `false` 与一次 `true` replay、以及一条 outbox。该补齐不改变 B 的排除范围，也不替代五桶最小化凭据、真实账号、授权、live canary 或 evidence manifest。

> 实施状态校正（2026-07-23，覆盖表内 `0048` head 和旧 API URL 的快照表述）：当前唯一 Alembic head 以本节最后一条校正为准。0049、0050 分别以 Project transaction advisory lock 关闭 Synthetic retention 与 Workflow C restricted-artifact scheduler 的并发 create/wake 窗口；0051 再让共享 parent-job terminal trigger 对无关联 Synthetic child 的 Durable Job 直接返回，且只在存在关联 child 时执行既有 Project scope guard，避免跨领域终态更新被误阻断。Internal API 将 `/model-gateway/runtime-options`、`/sampling/admission-runtime-options` 和 `/prompt-program-test-runtimes` 分别收敛为 `/model-gateway/options`、`/sampling/admission-options` 和 `/prompt-program-test-options`，以避免把部署实现暴露为稳定产品 URL；Admin、browser fixture、OpenAPI allowlist 与稳定快照已同步。Bootstrap create payload 仅携带可提交的 schema 版本/内容，不携带 `output_schema_hash` 或 `application_output_schema_hash`；而可选 Workflow C PostgreSQL composition 的缺失父 package 返回 unavailable，绝不回退 memory 或在 API 组装阶段异常退出。非集成全量回归、`make quality`、OpenAPI export/verify、真实 PostgreSQL 完整 integration，以及 `0050 -> 0051 -> 0050 -> 0051` 已执行。本项仍不替代 durable Workflow C API composition、真实账号或 evidence manifest。

> 实施状态校正（2026-07-23，`0052/0053`）：当前唯一 Alembic head 为 `0053_provider_exec_enforce`。`0052_provider_execution_input` 新建 Project-scoped、FORCE RLS 的 immutable execution-input registry；它保存逐题原文/hash、冻结 Prompt binding/state/release/bundle/schema、runtime selection 和 deadline，应用角色只能通过受控注册 RPC 写入。`0053_provider_exec_enforce` 不修改历史 Suite：旧的 unbound Provider Suite 仍可读取；但所有新 Provider Suite 必须由数据库 binder 写入该输入 ID/hash，所有 Provider Attempt 在写入时重新核对 runtime、Prompt、search mode、deadline 与题目原文/hash。空库及隔离最小 `geo_app` PostgreSQL 已完成 `0052 -> 0053 -> 0052 -> 0053`、正向绑定、direct table write 拒绝、unbound Suite 和变更 Prompt Attempt 拒绝。此项不替代 durable Internal API composition、execution input 退役/真实 catalog 注册、Provider canary 或最终 evidence manifest。

> 实施状态校正（2026-07-23，`0054_provider_attempt_schedule`）：当前唯一 Alembic head 为 `0054_provider_attempt_schedule`。该 migration 新增带 `p_requested_not_before` 的 Provider Attempt wrapper，并撤销 `geo_app` 对旧 0042 无调度函数的 EXECUTE；future schedule 在同一 transaction 更新新 Job 的 `next_run_at`，deferred retry 则必须和首次时间完全一致。`PostgresWorkflowCProviderSamplingControl` 只读取该 Suite 已绑定的 execution input，使用 immutable Run admission timestamp 和 deterministic command identity 生成可重放 spec；`authorization_checked_at` 只用于本次数据库检查，不能污染 idempotency hash。隔离 PostgreSQL 已完成 `upgrade -> downgrade -> upgrade`、最小 App ACL、延迟 Job 不可提前 claim、registry rebuild spec、篡改 Prompt 拒绝和同键 replay；这不替代完整 durable Internal API composition、execution input 退役/真实 catalog、Provider canary 或最终 evidence manifest。

> 实施状态校正（2026-07-23，`0055/0056`）：当前唯一 Alembic head 以本节最后一条校正为准。0055 的 bulk Provider producer 已在隔离 PostgreSQL 验证 exact ready slice、同键 replay、payload reuse 冲突和嵌套 producer 原子回滚；0056 则让 Run cancellation 的实际 Provider Attempt ID 与取消计数同一事务冻结在 command ledger，v2 RPC 在 replay 时直接返回该 lineage。空库已完成 `head -> 0039_workflow_c_alert_control -> head`，并在包含 0056 的 head 运行 Provider execution/bulk 与 queued/running cancellation 集成。`build_postgres_workflow_c_sampling_runtime` 只组装 Sampling 垂直切片，保持全局 Workflow C builder unavailable，直到 Analysis、Alerts 与真实手工工件 writer 的持久化路由组合也完成。

> 实施状态校正（2026-07-23，`0057_provider_exec_retirement`）：当前唯一 Alembic head 为 `0057_provider_exec_retirement`。execution input registry 增加版本、退役时间、操作者和原因，并只允许 Project-scoped、one-way retirement RPC 在 optimistic version 与 canonical command hash 一致时修改 lifecycle；结果写入 command ledger，因此同键 replay 只返回同一 immutable row。0052 binder 继续只选择 `approved`，而 0057 的 Attempt guard 接受已绑定 row 的 `approved|retired`，每次仍精确复核 Prompt/runtime/search mode/deadline/题目，确保旧 Suite 可复现但新 Suite 无法使用退役 input。隔离最小 App PostgreSQL 已验证 lifecycle replay、旧 Suite 实际 enqueue、新 Suite reject、direct update reject、有 retirement evidence 时 downgrade fail-closed；空库完成 `head -> 0056_sampling_cancel_lineage -> head`。这不替代 catalog/backfill、递归 secret 注入负测、全局 Workflow C composition 或 live Provider canary。

> 实施状态校正（2026-07-23，`0058_wfc_spec_sensitive`）：当前唯一 Alembic head 为 `0058_wfc_spec_sensitive`。Workflow C Job spec 的应用 guard 与 SQL definer producer 同时按规范化 key 递归拒绝 `api_key`、access/refresh/id token、cookie、session、storage state 和 proxy 实值；`secret_reference_id`、version/purpose 等 Secret Store 句柄仍是合法 lineage，`max_output_tokens` 不会被误判为 token。隔离最小 App PostgreSQL 已验证全部十种允许 kind 保持可入队、嵌套 `api-key` 直接 RPC 在任何 Durable Job/spec/outbox 前失败，以及空库 `head -> 0057_provider_exec_retirement -> head`。这只完成 generic producer 安全边界，不替代每个实际 business admission、跨 Project、lease/fence 或 live evidence。

> 最新实施状态校正（2026-07-23，`0059--0064`）：本节先前各条关于“当前唯一 Alembic head”的文字均为对应修订时的历史快照，不能作为当前部署或恢复目标。当前唯一 head 是 `0064_wfc_artifact_hold_expiry`：0059 使分析投影按 Project 隔离，0060 修复 Metric terminal RPC 的 aggregate 名称歧义，0061 由 SECURITY DEFINER trigger 在 Durable `retry_wait|failed|dead_lettered|cancelled` 后收敛 Metric child/batch，0062 则只在所有已准入 Judge 完整一致时无 Arbiter 完成 batch，0063 修复受限 artifact writer 的 failed-stage cleanup 权限和 RPC 名称歧义，0064 则将 Workflow C legal hold 固定为最长 90 天的双人 `apply|extend|release` 生命周期，并由 maintenance seed 处理到期后再进入 retention。0063 的隔离 PostgreSQL/MinIO 已实际验证 write-failure、staged timeout、durable Job/outbox、worker lease、DEK crypto-erasure 与 tombstone；0064 另以真实 Sampling lineage 与临时 MinIO 验证 apply、独立 approve、extend、expiry、持久化 wake、crypto-erasure 和 tombstone。0064 对旧 active boolean hold 在前向升级 fail closed，避免伪造期限；兼容降级以 `legacy_0064` 审计文本保留扩展/期限后再映射旧模型。本项仍不替代完整 Metric producer、生产数据迁移前置处置、backfill/catch-up/rollback 或 live evidence。

> 最新实施状态校正（2026-07-23，`0065_metric_output_projection`）：当前唯一 Alembic head 是 `0065_metric_output_projection`。0065 将 current Metric Judge/Arbiter Worker 的已验证最小输出，作为 `(project_id, child_job_id)` 独立 append-only、FORCE RLS projection 写入；completion RPC 在 hash 校验后先执行既有 fenced terminal transition，再在同一事务插入 projection。该设计避免更新 child lineage 时重检已退役 Prompt Binding 的历史外键。旧十参数 completion 保持 rolling-deployment 兼容，但不创建 projection，任何 future parent merge/read 必须将其 fail closed。隔离 PostgreSQL 已验证 `head -> 0059_analysis_project_scope -> head`、最小 Worker 的 Project scope/lease fence、hash mismatch 回滚、legacy no-projection、一致 Judge completion 和 Durable terminal reconciliation；F018 从空库升至 0065 后成功完成并清理所有临时资源。本项不替代 Metric parent typed producer、分歧 Arbiter 调度、父任务 wake/recompute、真实模型/MinIO 或 live evidence。

> 最新实施状态校正（2026-07-23，`0067_metric_arbiter_admission`）：当前唯一 Alembic head 是 `0067_metric_arbiter_admission`。0066 负责从冻结 `semantic_metrics` parent lease 原子准入至少两个 encrypted Judge child；0067 只在同一 batch 全部 Judge 已成功、投影 hash 完整且存在真实分歧时准入唯一 encrypted Arbiter child。两个迁移的 public `workflow_c_job_specs` 都只保存 schema/kind/child reference，encrypted task plaintext hash 仅以 Durable Job 与 child reference 绑定；其他十类 Job 仍保持 `input_hash=spec_hash`。隔离 PostgreSQL 已完成 `head -> 0065 -> head`（Judge）及 `head -> 0066 -> head`（Arbiter），受限 Worker 下验证 Job/spec/outbox 创建、缺失 Judge projection 拒绝、重复 admission/direct child update 拒绝以及既有 terminal/reconciliation 回归；尚未把 admission 接入 semantic parent operation 的 defer/wake、selected projection merge、snapshot persistence 或 live evidence。

本轮结束前的实现 checklist：

- [x] `IMPL-QA-2026-07-23` Admin fixture browser 回归完成：`M1-SYNTH-WEB-01..03` 通过，确认 Style Collection 请求只发送 Source/adapter/Secret Reference，由服务端返回 Job 身份与状态；默认共享 fixture Admin 集已固定单 worker，`pnpm test:browser` 25/25、Admin typecheck 和 9 个相关静态契约测试通过。此项只证明确定性 UI/合同回归，不替代 `M1-AC-*` 的真实账号、授权或 live evidence。
- [x] `IMPL-MIGRATION-2026-07-23` 最新空库 DDL 前向/回退/重放已在隔离 PostgreSQL 完成：含 0034 的完整 `upgrade head -> downgrade 0029_model_gateway -> upgrade head`，以及 0034 专项 `head -> 0033_terminal_shape_guard -> head`；0035 已由 Customer projection 集成覆盖 App 最小权限下的 trigger 兼容，0036 已由 Recommendation lifecycle 的最小 `geo_app` integration 覆盖，0037 已由 Workflow C artifact real-MinIO 集成的 `head -> 0036_recommendation_locks -> head` 覆盖，0038 已由 Sampling admission 隔离 PostgreSQL 的 `head -> 0037_wfc_artifact_tombstone -> head` 覆盖，0039 已由 Alert control 隔离 PostgreSQL 的 `head -> 0038_sampling_admission_control -> head` 覆盖，0040--0047 已完成对应隔离 round trip，0048--0050 完成两类 maintenance scheduler 的 reclaim/concurrency 修复，0051 完成 Synthetic parent scope 修复；当前唯一 Alembic head 为 `0051_synthetic_parent_scope`，并已实跑 `0050 -> 0051 -> 0050 -> 0051`。同一库核对 `workflow_c_job_specs` FORCE RLS（App 无 SELECT/INSERT、仅 EXECUTE 受控 producer RPC；Worker SELECT）、0038 policy/command ledger App 无写入且只执行 create/transition RPC、0039 alert/disposition/notification App 无写入且只执行处置 RPC、Alert/Metric fenced RPC 仅 Worker EXECUTE、Admin Inbox FORCE RLS（App 只读、Worker 仅 SELECT/INSERT）、Synthetic 仅项目范围 stage/claim overload 有 Worker EXECUTE，以及 Workflow C notification channel 与 `last_attempt_at` 三项约束。0032 `down` 现对称清理 alert/report/admin-inbox、sampling/metric helper、trigger 和新增列，避免对象泄漏至 0031 回退；0034 `down` 对称移除 producer RPC 并恢复 predecessor 的直写授权，0035--0039 `down` 对称恢复各自 predecessor trigger/constraint。支持的 Alert rule kind 与实际 evaluator/API 一致。此勾选仅证明空库 DDL/最小权限合同；不替代 direct-SQL/RLS、真实数据兼容迁移、backfill/catch-up、rollback 或恢复验收。
- [x] `IMPL-SYNTHETIC-POSTGRES-CONTRACT-2026-07-23` 隔离 PostgreSQL 的 `test_synthetic_lab_postgres_authorization_execution_and_guards` 已通过：授权的批准/撤销/重新评估、maker-checker/CAS 拒绝、服务端 Job 入队幂等重放、Worker lease/fence 终结、跨 Project RLS 和包含 Synthetic 数据时的 downgrade fail-closed 均已验证。该项不替代 raw/derived 对象、crypto-erasure 或真实登录采集的 MinIO/live 演练。
- [x] `IMPL-SYNTHETIC-RETENTION-POSTGRES-2026-07-23` 隔离 PostgreSQL 的四个 retention integration 已通过：原子 scheduler 为两个 Project 各创建一个 maintenance Durable Job/outbox；第一个 Project 的 fenced Worker 只 claim 自身 artifact，完成 crypto-erasure、独立 DEK 销毁、对象删除、tombstone 与 Job/outbox terminal 状态，第二个 Project 仍为 `deletion_pending`/`pending`。同库验证 active legal hold 不可 claim；partial remote delete 首次只完成 crypto-erasure 并进入 retry，第二次不重复擦除而完成 tombstone；失效删除 lease 的 crypto-erasure RPC 被拒绝且不改变当前 leased artifact。测试用 recording object store 验证删除调用顺序，**不**替代隔离 MinIO、并发 wake 或五桶最小化凭据验收。
- [ ] 0027--0047 的 direct-SQL/RLS、真实数据兼容迁移、backfill/catch-up/rollback 与 PostgreSQL 集成全部通过。
- [x] `IMPL-WORKER-COMPOSITION-2026-07-23` 通用 Worker 已在启动路径调用 Prompt、Synthetic、Recommendation 和 Workflow C 的单一闭集 builder；Workflow C production composer 现在精确组装两类 Sampling、三类 analysis、两类 metric child 和三类 alert/notification PostgreSQL operation，并由 `tests/unit/jobs/test_shared_worker_composition.py` 证明十种 kind 完整、缺 operation fail closed；0034 通用 producer 已独立验证十种 kind 的原子入队。此项仍只证明 registry/通用 producer，不替代每种业务 admission 的 typed input、隔离 PostgreSQL/MinIO integration 或 live evidence。
- [x] `IMPL-WORKFLOW-C-PRODUCER-ATOMIC-2026-07-23` 0034 的 `geo_enqueue_workflow_c_job_spec` 已在隔离 PostgreSQL 以临时 `NOINHERIT` App login 验证十种允许 kind：每次首次提交原子创建 Durable Job、immutable Spec、broker wakeup 和 `job_enqueued` event；同 payload/key 重放复用原 Job，不新增任何记录；Python/PostgreSQL 对含 UTF-8 标量的 canonical hash 一致，递归敏感字段在入库前拒绝。App 对 `workflow_c_job_specs` 的 SELECT 和 INSERT 均被拒绝，只能 EXECUTE RPC，Worker 保留 SELECT。此项只验证通用 producer 边界，不替代各实际 admission 的 typed input、跨 Project 业务授权、取消/lease loss/fence、对象工件或 live evidence。
- [ ] `IMPL-WORKFLOW-C-JOB-SPECS-2026-07-23` 0032/0034 的 `workflow_c_job_specs` 与 Durable Job 同事务创建、由 `input_hash/spec_hash` 绑定、immutable/RLS/最小权限均通过；每一类实际 admission/producer 必须以 canonical schema v1 写入实际 operation 输入，递归拒绝 secret/credential/token/password/proxy/authorization 值，Worker 只在当前 Project 的有效 lease/fence 下重建并验证输入。该项不因通用 RPC 或 unit test 存在而完成，仍必须覆盖十类实际 admission、跨 Project、过期 lease 与敏感字段负测。
- [x] `IMPL-WORKFLOW-C-JOB-SPECS-SENSITIVE-BOUNDARY-2026-07-23` `0058_wfc_spec_sensitive` 将通用 immutable Job spec 的 Python 与 PostgreSQL security boundary 同步为规范化递归 key guard：拒绝 API key、token、cookie/session/storage state 与 proxy 实值，且先于 canonical JSON hash 拒绝 Secret Store plaintext object；`secret_reference_id`/版本/用途等安全句柄与 `max_output_tokens` 仍可冻结。隔离最小 `geo_app` PostgreSQL 已验证十种 allowlisted kind 正向持久化、App 直读/直写拒绝、嵌套 `api-key` 直接 RPC 零写入、空库 `head -> 0057 -> head`；该项不代表十类实际 business admission 的端到端 secret/lease/cross-Project 集成已全部完成。
- [x] `IMPL-WORKFLOW-C-SAMPLING-ADMISSION-POSTGRES-2026-07-23` 0038 将 Sampling admission 的策略定义字段、五态 maker-checker lifecycle、frozen runtime option、项目范围 RLS、命令 ledger 和 create/transition security-definer RPC 一并落入 PostgreSQL；应用角色对 policy/ledger 无 `INSERT`/`UPDATE`，只能执行两个 RPC。隔离最小 `geo_app` 登录已验证 option 匹配、hash 重算、创建/提交/独立批准/撤销、同键回放、错误 maker approval、同键不同输入、跨 Project scope 和 direct SQL 旁路拒绝，并完成空库 `head -> 0037 -> head`。此项只完成 policy control plane；不替代 Suite/Run/Task/Attempt 的 typed durable admission、quota/interval/concurrency usage、Durable Job/outbox producer、取消/lease/fence、Admin workflow 或真实 Provider evidence，故全局 Workflow C 仍不得勾选。
- [x] `IMPL-WORKFLOW-C-SAMPLING-SUITE-POSTGRES-2026-07-23` 0040 新增 immutable `workflow_c_sampling_suite_input_options`，并用两个 Project-scoped security-definer RPC 注册 frozen input 和创建 Suite；Suite 必须逐项匹配 input selector、questions、SourceStratum 与当前 approved admission policy，数据库以 C-collation canonical JSON 重算 input/Suite/source hash，避免 locale 造成 Python/SQL hash 分叉。`geo_app` 对 input/Suite 无直接写入，仅可执行 scoped RPC。隔离最小 `geo_app` 登录已完成 `head -> 0039 -> head`、input/Suite 首次创建和精确回放、错误同身份不同内容、直写拒绝和跨 Project 拒绝。此项仅完成 Suite 控制面；不替代 Run reservation、daily/quota/interval/concurrency usage、Task/Attempt/Job/outbox 原子 producer、取消/lease/fence、完整 API composition 或真实 Provider evidence。
- [x] `IMPL-WORKFLOW-C-SAMPLING-RUN-POSTGRES-2026-07-23` 0041 通过单个 Project-scoped security-definer RPC 在同一事务锁定 admission policy、校验当前 approved definition/purpose/有效期、预留完整 Run 分母、物化全部确定性 Task、更新 daily reservation audit 和 command ledger。Run 分别持久化 `reserved_task_count`、`consumed_task_count` 与 `released_task_count`，active quota 使用三者差值，避免预留被错误视为实际请求。`task_key` 保持稳定分母身份，物化 Task ID 从 `run_id + task_key` 派生，避免同一 Suite 的合法重跑撞全局主键；旧 ID 只兼容读取历史行。`geo_app` 对 Run/Task 无直接写入；durable Run control 在创建前复核 Suite 的 definition hash 并重新计算 Grant。隔离最小 `geo_app` 登录已验证 0041 空库重放、首次创建/精确回放、完整 Task inventory、活跃预留导致的 quota 拒绝、取消后同 Suite 重跑和 direct write 拒绝。此项不替代 daily/interval/concurrency execution gate、完整 durable runtime 或真实 Provider evidence。
- [x] `IMPL-WORKFLOW-C-SAMPLING-ATTEMPT-PRODUCER-2026-07-23` 0042 将首次 Provider Attempt 的 typed frozen spec、Run reservation consumption、UTC daily usage、Durable Job、immutable Job Spec、broker outbox、enqueue event 和 command ledger 收敛为同一 Project-scoped transaction；同键重放返回同一 Attempt/Job，不重复消费预留或新建 Job。隔离最小 `geo_app` 登录已验证 0042 的 `head -> 0039 -> head` 回退/重放、Task/Run 计数、direct write 拒绝、scope 拒绝和 exact replay。此项只涵盖首个 `provider_api`/`proxy_grounded_api` Attempt，不替代手工 Attempt、取消/释放、并发/interval、MinIO 证据或真实 Provider evidence。
- [x] `IMPL-WORKFLOW-C-SAMPLING-ATTEMPT-CLAIM-2026-07-23` 0043 将 `sampling.provider_execute` Durable Job 的首次与 retry claim 在同一事务投影为 Attempt/Task 的 `running` 状态及新版本；重新领取过期且仍为 `running` 的 aggregate 仅改变 Durable fencing generation，不覆盖状态。Worker 以 claim 后的版本调用既有 fenced completion/failure RPC；可重试失败原子写入 `retry_ready`/`queued` 与 Durable `retry_wait`，60 秒后才允许重试。隔离最小 `geo_worker` 登录已验证 `queued -> running -> retry_wait -> running`、版本递增和 fencing generation；0044 继续覆盖该 claimed Attempt 的 `cancel_requested -> cancelled` 收敛。此项不替代 lease-loss completion、manual import 或真实 Provider evidence。
- [x] `IMPL-WORKFLOW-C-SAMPLING-CANCEL-POSTGRES-2026-07-23` 0044 将 Provider Attempt/Run cancel 收敛为两个 Project-scoped RPC，并以 Durable Job `cancelled` trigger 完成最终 Attempt/Task/Run 投影。排队或 retry Job 立即写入 Durable terminal 与 event，trigger 原子终结领域行；运行中/终结中 Job 只写 `cancel_requested`，保持已消费的 reservation，最终由持有当前 lease 的 Worker cancel 收敛。Run cancel 仅将无 Attempt 的 planned Task 计入 `released_task_count`，同步 admission usage 的 released count，绝不释放已消费 Task。typed cancellation repository 验证 UTC 时间、版本 fence、RLS、输入 hash 与 command replay。隔离最小 App/Worker 登录已验证 queued cancel、running cancel、replay、状态/版本计数、Worker final cancel、跨 Project/RLS、`head -> 0039 -> head` 及取消后同 Suite 重跑。此项不替代 manual Attempt、MinIO evidence、真实 Provider canary 或 evidence manifest。
- [x] `IMPL-WORKFLOW-C-SAMPLING-TERMINAL-RECONCILIATION-2026-07-23` 0045 监听 `sampling.provider_execute` Durable Job 的 `retry_wait|failed|dead_lettered` 转换。已通过 fenced failure RPC 的 Attempt/Task 不会被重复修改；共享 dispatcher 在未预期异常时若跳过该 RPC，trigger 会将 `running -> queued/retry_ready` 或最终 `failed` 收敛，并在所有 Task 终态时关闭 Run。`PostgresDurableJobStore.fail` 以 `retry_delay is not None` 区分“立即重试”和“不重试”，确保 `timedelta(0)` 的第三次耗尽仍为 `dead_lettered`。隔离 PostgreSQL 已验证三次立即重试、Attempt/Task 版本与最终失败状态；此项不替代 Worker 失租后的业务重试、manual Attempt、MinIO evidence 或真实 Provider canary。
- [ ] `IMPL-WORKFLOW-C-PROVIDER-EXECUTION-INPUT-2026-07-23` 在启用 durable Provider enqueue 前，必须将每个 approved Suite input 的问题原文（逐题 hash 复核）、Prompt binding/state/release/bundle/schema、runtime selection 和可选 deadline 作为独立、服务端注册且 immutable 的 execution input 持久化；同一 immutable Suite source 固定 search mode。Suite 创建必须固定该 input ID/hash，Attempt producer 只能按该绑定、Run admission、Task version 和 Suite source 重建 `ProviderSamplingWorkerSpec`，不得从 HTTP enqueue body、前端状态或 memory fixture 取得问题/Prompt/runtime。旧 Suite 没有该 binding 时必须 fail closed；注册、读取、enqueue、RLS/ACL、退役、重放、跨 Project、Prompt/Question hash 不一致、secret 递归拒绝和 migration expand/backfill/cutover 均需以 PostgreSQL 集成验证。`0052--0057` 已完成 registry、RLS/ACL、Suite/Attempt write boundary、typed registry-only producer、同键重放、跨 Project/direct write、unbound Suite、篡改 Prompt、deferred schedule、旧 RPC ACL 负测及 version-fenced retirement；仍需 secret 递归负测、真实 catalog/backfill/cutover、完整 durable Internal API composition 和 live Provider canary。该项是 `IMPL-WORKFLOW-C-JOB-SPECS`、durable Internal API composition 和真实 Provider canary 的前置，当前未完成。
- [x] `IMPL-WORKFLOW-C-PROVIDER-EXECUTION-INPUT-FOUNDATION-2026-07-23` `0052_provider_execution_input` 与 `0053_provider_exec_enforce` 已完成 execution input 的数据库基础：输入 canonical hash 由 PostgreSQL 和应用层双重复核，题目必须精确对应 frozen Suite input；registry 为 FORCE RLS，`geo_app` 无 direct insert、仅能执行 scoped registration RPC。新 Provider Suite 先由 binder 选择唯一 approved registry row，再由后置 require trigger 拒绝未绑定 Suite；Provider Attempt insert 则重检 registry payload 与 frozen spec 的 runtime、Prompt、search mode、deadline、题目原文/hash 一致。真实隔离 PostgreSQL 完成前进/回退/重放、正向 binding、RLS/ACL、unbound Suite 和篡改 Prompt Attempt 负测。此子项不声明 durable API producer 或 live Provider 已完成。
- [x] `IMPL-WORKFLOW-C-PROVIDER-EXECUTION-INPUT-RETIREMENT-2026-07-23` `0057_provider_exec_retirement` 把 registry 的 `approved -> retired` 固化为仅一次的 Project-scoped RPC：输入包含 exact execution hash、expected version、actor、非敏感枚举 reason code、retired time 和 canonical idempotency hash；成功结果、版本和 retired identity 写入 command ledger，重放必须返回同一 durable row。新的 Suite binder 仍只选 `approved`；已冻结 Suite 的 exact FK 不变，Attempt trigger 对 `approved|retired` input 继续复核完整 frozen spec，因此可审计重现而不重新向新 Suite 分发已退役 runtime。隔离最小 `geo_app` PostgreSQL 已验证首次/重放、拒绝 credential-like reason、旧 Suite durable enqueue、新 Suite reject、direct update reject、空库 `head -> 0056 -> head` 和 retirement evidence downgrade fail-closed。此子项不替代真实 catalog/backfill、secret 递归拒绝、全局 durable API 或 live Provider canary。
- [x] `IMPL-WORKFLOW-C-PROVIDER-ENQUEUE-CONTROL-2026-07-23` `0054_provider_attempt_schedule` 与 `PostgresWorkflowCProviderSamplingControl` 已闭合 Provider enqueue 的持久化 producer 子项：API 只可提交 `expected_task_version` 和 `requested_not_before`；控制器只从 bound execution registry、immutable Suite source 和 Run admission 重建 spec。函数 wrapper 原子创建 Attempt/Job/Spec/outbox 后保留 future schedule，replay 不允许改 deferred time；`geo_app` 不能执行旧无调度 RPC。隔离最小 App/Worker PostgreSQL 已验证 registry rebuild 的 Prompt/question/search lineage、Job 时间、同键重放、ACL 和 `upgrade -> downgrade -> upgrade`。此子项不代表全量 durable API composition、retirement/catalog/backfill 或 live Provider 完成。
- [x] `IMPL-WORKFLOW-C-SAMPLING-POSTGRES-READS-2026-07-23` `SamplingAttempt` 现在明确区分 Attempt aggregate ID 与一对一 `durable_job_id`；内存路径仍默认同 ID，PostgreSQL 路径保留 producer 分配的真实 Job ID。`PostgresSamplingReadRepository` 只从 Project-scoped Attempt、Durable Job 与 Observation 行恢复只读视图，拒绝 Job/Attempt 终态不一致、Observation hash、location、artifact 或 evidence schema 损坏的行，且不向 Admin API 读取 worker-only immutable Job spec。focused 单元回归覆盖成功恢复和 hash 篡改拒绝；隔离最小 `geo_app` PostgreSQL 已验证按 Run 读取新排队 Provider Attempt 与空 Observation 集。该子项不声明 durable Internal API composition、真实 Provider canary 或 evidence manifest 已完成。
- [x] `IMPL-WORKFLOW-C-PROVIDER-BULK-ENQUEUE-2026-07-23` `0055_provider_bulk_enqueue` 与 `PostgresWorkflowCProviderBulkSamplingControl` 已闭合 Provider `enqueue-ready` 的持久化 producer 子项。控制器只从 Run/Suite、Task inventory 与 immutable execution registry 构造 exact ready slice；RPC 在固定 `task_key` 顺序下锁定该 slice，按 Suite interval 计算 future schedule，并在一个 SQL transaction 内调用既有 fenced single-attempt producer。outer command ledger 仅绑定调用方可控 request，首次结果冻结服务器 slice，因此同键 retry 即使 Task 已转为 `queued` 也只回放同一 Attempt/Job/schedule；变更 `requested_not_before|max_tasks` 拒绝。隔离真实 `geo_app` PostgreSQL 已验证两项 future schedule、同键 replay、后项 stale version 导致前项 admission 及 Job/outbox 同时回滚。该子项不声明 durable Internal API composition、真实 Provider canary、外部 connector 或 evidence manifest 已完成。
- [x] `IMPL-WORKFLOW-C-SAMPLING-CANCEL-LINEAGE-2026-07-23` `0056_sampling_cancel_lineage` 在不改变 0044 RPC 返回签名的前提下增加受限 v2 wrapper。wrapper 与原命令使用相同 Project scope、advisory lock 和 Run-first/Attempt-second 锁序，首次取消前锁定实际会被处置的 queued/retry/running/finalizing Attempt，并将有序 ID 列表原子追加到同一 command ledger result；replay 仅返回该冻结列表，缺少 lineage 的历史 ledger 明确 fail closed，绝不以可变状态猜测。`PostgresSamplingCancellationRepository` 和 API view 返回 exact `attempt_ids`，隔离 App/Worker PostgreSQL 覆盖 running cancel、首次/重放一致性与 `head -> 0039 -> head`。此子项不替代 Worker 最终取消确认、真实 Provider canary 或 evidence manifest。
- [x] `IMPL-WORKFLOW-C-SAMPLING-DURABLE-COMPOSITION-2026-07-23` `build_postgres_workflow_c_sampling_runtime` 已从单一 RLS-scoped connection port 组合 Admission policy、immutable Suite/execution input、Run/Task、单/批 Provider producer、governed manual evidence、取消及 integrity-checked read model；路由写后响应始终从持久化 aggregate 重建，不缓存 HTTP body。隔离 PostgreSQL 验证 composition construction、Provider execution/bulk contracts、取消 lineage 和 migration round trip。该项刻意只完成 Sampling vertical；全局 `WorkflowCApi` 仍必须保持 unavailable，直到 Analysis durable command/read controls、Alert 完整组合、真实受治理 manual artifact writer 和跨路由 integration 一并完成。
- [x] `IMPL-WORKFLOW-C-ALERT-CONTROL-POSTGRES-2026-07-23` 0039 将人工 `acknowledge`、`suppress`、`unsuppress`、`resolve` 置于项目范围 RLS、raw idempotency key、canonical command hash、expected version 和状态迁移的单一 SECURITY DEFINER RPC；一次新处置原子写入 append-only disposition、三通道 safe notification、notify Durable Job、immutable spec、broker outbox 与 enqueue event。应用角色对 `workflow_c_alerts`、`workflow_c_alert_dispositions`、`workflow_c_alert_notifications` 无直接写入权限。隔离最小 `geo_app` 登录已验证确认、抑制、重放不增行、同键不同输入冲突、跨 Project 拒绝、六份通知/Job/Outbox 和直写拒绝；`PostgresWorkflowCAlertControl` 保持现有 Internal API 路由方法形状。此项不替代规则创建/排程/评估的真实输入、通知 Worker 的 live 传输、自动解除抑制、完整 Admin 接线、独立 verifier 或 live evidence。
- [ ] `IMPL-WORKFLOW-C-SAMPLING-WORKER-2026-07-23` 已完成两个非浏览器 Sampling operation 的代码级闭环：`sampling.provider_execute` 以冻结 spec、Prompt Release、Model Gateway Secret handle 和 structured-output/lineage 校验执行；`sampling.manual_import` 只读取已批准、加密且受限的持久化手工工件，绝不发起消费者 UI/browser capture。两类操作均把 Project、lease/fence、attempt `durable_job_id`、版本、幂等 Observation 和 RPC 写入置于同一持久化边界；0043 已使 Provider claim/retry claim 与 aggregate 状态一致，0044 已使 queued/running cancellation 回到 fenced terminal aggregate，0045 已使 shared dispatcher 的未预期失败和重试耗尽不再留下 `running` aggregate，retryable failure 使用 Durable `retry_wait` 而非错误终结为 `failed`，且已接入十种 operation 的 production composer。0046 已以最小 `geo_app` 与真实 MinIO 验证 `sampling.manual_import` 的 encrypted staged -> active 工件只能通过 scoped activation RPC，读取后的过期路径先 crypto-erase 再删除 payload/manifest，并在 tombstone 后于访问对象存储前 fail-closed；应用角色保持无直接 `UPDATE`。共享 Durable Store 已验证过期旧 lease 无法 finalization/failure，relay 可发现过期 Job，接管 lease 才能收敛领域终态。`tests/unit/sampling/test_postgres_worker_contracts.py`、`tests/architecture/test_codebase_boundaries.py`、`tests/test_workflow_c_migration.py`、mypy 及 Provider claim/retry/cancel/dead-letter/lease-loss 的隔离 PostgreSQL 测试已通过。**不得勾选**，直至真实 Provider canary/evidence manifest 完成；不以 fixture 替代 live 证据。

- [x] `IMPL-WORKFLOW-C-MANUAL-ARTIFACT-PERSISTENCE-2026-07-23` 0046 对齐实际 independent-DEK encryption label 与两类 governed redaction assurance；应用角色仍仅能 INSERT staged row，insert trigger 在受限 definer 权限下追加 immutable staged event，active 仅由 Project-scoped RPC 在 staged、未过期和 active DEK 均成立时推进。隔离 PostgreSQL + 真实临时 MinIO 已覆盖 `head -> 0045_sampling_terminal_reconcile -> head`、实际 Sampling Run/Task lineage、email/token 落盘前清理、redacted payload 恢复、expiry scheduler、crypto-erasure、payload/manifest 物理删除与 tombstone 后不触碰 MinIO 的 fail-closed。0046 `down` 遇到新标签 lineage 会拒绝回退，避免静默丢失语义；此项不替代 live Provider evidence 或最终 evidence manifest。
- [x] `IMPL-WORKFLOW-C-MANUAL-EVIDENCE-ADMISSION-2026-07-23` 0047 将 `manual_ui` 证据的 submitted/rejected/approved lifecycle 固化为 project-scoped submit/review RPC。提交仅接受经 pre-redaction attestation 的 metadata/hash 与 staged encrypted artifact；审核强制 maker/checker 分离和 optimistic version。批准在同一数据库事务激活工件、创建首个 Manual Attempt、immutable Job Spec、Durable Job、broker outbox 和 command ledger，批准重放不增加 Attempt/outbox；拒绝只产生审计与状态，不创建 Attempt。`tests/integration/test_workflow_c_manual_evidence_postgres.py` 已用临时 PostgreSQL 与真实 MinIO 验证上述边界、direct SQL 拒绝与 Job Spec 读取最小权限；此项不替代登录 surface、真实 Provider 或最终 evidence manifest。

- [x] `IMPL-DURABLE-LEASE-FENCE-2026-07-23` 共享 `PostgresDurableJobStore` 的 complete、failure、retry、defer 与 cancel 全部将 token、fencing generation、`running|finalizing` 状态及数据库当前 lease 有效期作为同一 SQL CAS 条件。隔离 Sampling PostgreSQL 已验证：到期旧 Worker 的 finalization 与 failure 都抛出 `LostJobLease` 且不改变 Attempt/Task；`geo_worker_recoverable_jobs` 返回该 Job；新 fencing generation 重新认领后才可写入失败终态。`PostgresOutboxStore` 同时读取 tuple 和 `dict_row`，恢复循环不依赖连接行工厂。此项是代码与隔离数据库证据，不替代 live/evidence manifest 验收。

- [x] `IMPL-WORKFLOW-C-API-TERMINAL-STATUS-2026-07-23` Sampling Run API response 已覆盖领域 `planned/running/cancel_requested/completed/cancelled/failed` 全状态，bulk enqueue 后取消的 Run 详情不再因 Pydantic literal 漏项产生 500；focused API 回归断言 Run 和全部 Task 均可返回 `cancelled`。`SamplingRunResponse` 的稳定 Internal OpenAPI 快照和 manifest 已重生并验证。PostgreSQL alert notification reader 也将数据库 rule kind、severity、status 显式解析为领域枚举；隔离 alert control integration 已覆盖实际 notification 读取。此项只闭合 API 兼容性，不替代 Workflow C 全部 durable API composition、真实 Provider 或最终 evidence manifest。
- [ ] `IMPL-WORKFLOW-C-METRIC-WORKER-2026-07-23` `workflow_c.metric_judge` 与 `workflow_c.metric_arbiter` 已完成代码级 frozen-command 闭环：重建精确 Job spec、解密 child `task_*`、核验 Prompt/runtime/schema lineage、调用 governed Model Gateway/semantic parser，并且只经 fenced Worker-only 0032 RPC terminalize；repository/direct SQL 不得直接改 Metric child/batch。RPC 在数据库端复核 Project/lease/fence、parent hash/role、Judge 全部 succeeded 且有 output、Judge output 分歧、以及 Arbiter selected candidate/output 精确匹配；`0062_metric_judge_agreement` 另闭合“至少两名已准入 Judge 全部成功且同一 output hash”时的确定性无 Arbiter 完成分支。两类 operation 已接入 production composer。已完成 focused contract/semantic/architecture 测试、Ruff 和 mypy。**不得勾选**，直至 typed producer、隔离 PostgreSQL/MinIO 的 RLS/lease/replay/取消/失败恢复和 live evidence manifest 完成。
- [x] `IMPL-WORKFLOW-C-CUSTOMER-LIFECYCLE-2026-07-23` `workflow_c_report_snapshot_versions` 的 draft/review/approved/stale/superseded/revoked append-only 生命周期已接入 project-scoped PostgreSQL writer/reader。0035 用事务 advisory lock 取代 App 无权执行的 row lock，trigger 在任何 approved 插入时独立重检 report hash、semantic `complete`/approved、非 test/synthetic 和 source kind；Customer 查询按每个 Report Snapshot 的 latest version 过滤为 approved，并重新验证语义证据、批准、source kind 和 safe payload；Customer API 始终挂载只读 projection，缺 durable reader 时 fail closed `503`。隔离 PostgreSQL 测试已覆盖同项目 approved 返回、source 失效和 stale 隐藏、审批重检、跨 Project RLS、direct UPDATE 拒绝及不完整来源的 direct approved INSERT 拒绝。此项不替代完成度门槛、独立 verifier 和 live evidence。
- [x] `IMPL-RECOMMENDATION-POSTGRES-LIFECYCLE-2026-07-23` 0036 的 Recommendation lifecycle 已由隔离 PostgreSQL 验证：最小 `geo_app` 角色可经 durable builder 创建、提交、独立复核和批准 Recommendation，批准只创建幂等下游草稿；Fact 失效后追加 expired 版本并原子阻断未开始草稿。版本表保持 append-only，应用层 lifecycle advisory lock 与数据库 predecessor/trigger 双重约束下 direct `UPDATE` 被拒绝；`insufficient_evidence` 仅可产生 `sampling_plan`。builder 可读取 approved version，且没有未配置时回退 memory/provider 的路径。该项不替代 `D-CONTRACT-01..04`：真实 Observation/Statistic/Attribution lineage、完整 Customer 白名单投影、Recommendation generation Worker、独立 verifier 与 live evidence 仍未完成。
- [x] `IMPL-RECOMMENDATION-GENERATION-POSTGRES-ENQUEUE-2026-07-23` Recommendation generation submission 已在隔离 PostgreSQL 验证真实冻结 Prompt binding、当前 Fact/Question producer evidence、项目角色和受控 `geo_enqueue_recommendation_generation` RPC：首次调用原子创建一份 Durable Job、immutable generation Spec、broker outbox、`job_enqueued` event 与 receipt；相同 selection/idempotency key 重放只返回原 Job，不新增任一记录。runtime selector 在该数据库合同中为确定性 approved-catalog 替身，未发起 Provider 请求；这不替代真实 catalog 注册、Worker parent/child、取消/lease-loss、对象工件或 live provider evidence。
- [ ] 通用 Worker/Relay 的 Prompt、Synthetic、Workflow C、Recommendation production handler 均以真实 PostgreSQL/Model Gateway composition 注册，且 readiness 在缺任一 handler 时 fail closed。
- [ ] Workflow C restricted artifact retention 的 write-failure、staged timeout、expiry、retry 和 hold 路径均使用项目范围的持久化 schedule/seed；每次唤醒与 `durable_jobs`/`broker_outbox` 同一事务幂等提交，maintenance Worker 只按 lease Project claim，且 crypto-erasure receipt 必须早于 remote delete。已完成 idle queue、并发 seed、write-failure、staged timeout、跨 Project、expiry、对象删除失败/重试，以及 bounded legal hold 的申请、独立审批、延期、到期和随后真实对象清理的 PostgreSQL/MinIO 证据；仍须完成生产最小权限身份、独立 verifier 与 live evidence，故不得勾选。
- [x] `IMPL-WORKFLOW-C-ARTIFACT-CONCURRENT-SEED-2026-07-23` 0050 已关闭上项中 Workflow C 的并发 seed 子门槛：`geo_schedule_workflow_c_artifact_maintenance` 以 `workflow-c-artifact-maintenance:<project_id>` transaction advisory lock 串行 active lookup/create/wake。`test_workflow_c_artifact_scheduler_concurrent_seeds_create_one_job_and_outbox` 在独立 PostgreSQL/MinIO 环境暂停首次 durable Job insert 后并发运行两个 project-scoped seed，验证相同 Job/outbox 与精确一次 replay；空库已完成 `head -> 0049_synthetic_retention_lock -> head`。母项仍须保留，直至 hold lifecycle、生产最小化凭据、独立 verifier 和 live evidence 完成。
- [x] `IMPL-WORKFLOW-C-ARTIFACT-EXPIRY-MINIO-2026-07-23` 0037 已修复 Workflow C artifact tombstone RPC 的 output-column/column 歧义。隔离 PostgreSQL 加真实临时 MinIO 验证两 Project 的 idle scheduler 各原子建立 maintenance Durable Job/outbox；第一个 Project 的 worker 以正确 RLS scope claim 过期 artifact，先销毁 DEK，再删除 payload/manifest，最后写入 tombstone；同 Project 的 active legal hold 和第二 Project 的对象均保持可用。另一路真实 MinIO 演练令首次对象删除失败，验证 queue 进入 `retry_wait`、第二次 claim 不重复 crypto-erasure 且完成 tombstone。测试还完成 `head -> 0036_recommendation_locks -> head`。此项不替代 dedicated write-failure/staged-timeout fault recovery、完整 hold lifecycle 或生产最小化凭据证据。
- [x] `IMPL-WORKFLOW-C-ARTIFACT-FAULT-RECOVERY-2026-07-23` `0063_wfc_artifact_write_grant` 以最小权限闭合受限 writer 的即时故障清理：`geo_app` 只取得 `geo_enqueue_workflow_c_artifact_write_failure` 的执行权，仍无 artifact table `UPDATE`、maintenance schedule/claim、crypto-erasure 或对象删除权限；函数改以 `artifact_row`/`queued_row` 显式限定列，避免 output-column 歧义。`test_workflow_c_artifact_fault_recovery_postgres.py` 在隔离 PostgreSQL + 临时真实 MinIO 中让 manifest 的第二次 put 失败，验证 writer 仅入队、`write_failed` queue 与同事务 durable Job/outbox 存在，受限 worker 成功 claim/complete 后先销毁 DEK、再删除遗留 payload 并 tombstone；同一测试还以 `activate=False` 的真实 staged artifact 和 60 秒 grace 验证 scheduler wake、worker lease 和 `staged_timeout` tombstone。0063 migration contract、SQL checksum ledger create/verify 及隔离 PostgreSQL `head -> 0061_metric_child_reconcile -> head` 均已复核；本项不替代 hold、生产身份、独立 verifier 或 live evidence。
- [x] `IMPL-WORKFLOW-C-ARTIFACT-LEGAL-HOLD-LIFECYCLE-2026-07-23` `0064_wfc_artifact_hold_expiry` 为 restricted artifact 增加 `legal_hold_until` 和 policy v2：`apply`/`extend` 均必须携带严格晚于请求且不超过 90 天的截止时间，`extend` 只能延后当前截止时间，`release` 必须为空；申请、决定和延期均保留 maker/checker/version fence，`geo_app` 不再拥有 hold request table 的直写权限。`geo_seed_workflow_c_artifact_maintenance` 在按项目入队前调用受限 expiry helper，后者仅释放当前生效、同截止时间的 hold，并把超时 pending request 或生效 hold 记为 `expired` 与 `hold_expired`，避免旧 extension 抢占新的期限。`test_workflow_c_artifact_hold_expiry_postgres.py` 使用真实 App/Worker role、真实 Sampling Run/Task 和临时 MinIO 验证 apply -> independent approve -> extend -> automatic expiry -> durable Job/outbox -> DEK crypto-erasure -> payload/manifest delete -> tombstone；领域和迁移合同测试同时覆盖缺失/超 90 天期限及前向/回退兼容。旧 active boolean hold 的升级明确阻断，要求人工释放和重新审批；回退用 `legacy_0064` 审计文本保存被旧 schema 不能表达的 action/期限。本项不替代生产 identity、独立 verifier 或 live evidence。
- [x] `IMPL-SYNTHETIC-FIVE-BUCKET-RESTORE-2026-07-23` 正常模式 `scripts/run_authenticated_restore_gate.sh` 已在独立随机 Compose 项目完成开发认证备份/恢复：业务、Recommendation、Workflow C、Synthetic raw、Synthetic derived 五桶逐一镜像，manifest/verify allowlist、逐桶 count/hash、恢复挂载和固定 bucket-to-reader 均通过；raw/derived 路由、未知 bucket/跨 bucket URI/缺失挂载均 fail closed，结果写入 `geo-development-backup-restore-smoke-v6` 收据。该项不替代生产备份演练或最终 `M1-AC-04/M6` 签字。
- [ ] `IMPL-SYNTHETIC-RETENTION-PROJECT-SCOPE-2026-07-23` Synthetic retention 已接入项目范围 stage/claim adapter、Relay 的原子 Durable Job/outbox wake、独立 `synthetic-artifact-maintenance` queue 和不挂 keyring 的 deletion-only Worker；隔离 PostgreSQL 已验证两个 Project 不互相 claim、crypto-erasure 先于录制对象删除、失效 lease 拒绝、partial delete retry 与 active legal hold。`test_synthetic_artifact_maintenance_deletes_real_minio_objects_after_crypto_erasure` 现以临时隔离 PostgreSQL + MinIO 写入真实 manifest/payload，验证 crypto-erasure 后对象不可读且 tombstone 完成；`test_synthetic_artifact_maintenance_retries_partial_real_minio_deletion_after_crypto_erasure` 进一步让真实 manifest 先删除、payload 删除首次失败，确认重试不会重复 crypto-erasure、将缺失 manifest 视为幂等成功，并删除遗留 payload 后 tombstone。0049 已补齐并发 wake/seed，首个 fenced operation 已证明另一 Project 不被该 Job claim；五桶 production policy 的真实 bootstrap 又已完成最小权限演练。母项仍保持未勾选，直至 production identity 下的 live evidence 与独立验收完成。
- [x] `IMPL-SYNTHETIC-RETENTION-CONCURRENT-WAKE-2026-07-23` 0049 已关闭上项中的并发 wake/seed 子门槛：`geo_enqueue_synthetic_artifact_maintenance` 为每个 candidate Project 持有 transaction advisory lock，且 active wake 以 `broker_outbox_project_id_idempotency_key_key` 去重。`test_synthetic_artifact_maintenance_concurrent_wakes_create_one_job_and_outbox` 在真实隔离 PostgreSQL 的 Job insert trigger 暂停窗口中并发调用两次 scheduler，验证一条 Job、一条 outbox、相同 Job ID 与精确一次 replay；另已完成 `head -> 0048_synthetic_retention_reclaim -> head`。母项仍未勾选，仅剩五桶最小化凭据与最终外部/独立验收；既有首个 fenced operation 已证明另一个 Project 不被该 Job claim。
- [x] `IMPL-SYNTHETIC-PARENT-TRIGGER-SCOPE-2026-07-23` 0051 已修复共享 Durable Job terminal trigger 的跨领域 scope 误拦截：不存在 `synthetic_lab_model_call_children` 关联的 Job 在无 Synthetic Project scope 时直接返回，存在关联 child 时才要求该 Project scope 并继续取消未启动 child。静态迁移/回退测试 40 项、真实 PostgreSQL 迁移 `0050 -> 0051 -> 0050 -> 0051`、以及配置真实 PostgreSQL 的完整 `tests/integration` 均已通过。此项不放宽任何 Synthetic parent 的项目隔离，也不替代最终 live/evidence 验收。
- [x] `IMPL-NONB-API-CONTRACT-2026-07-23` Internal API 的 Model Gateway、Sampling admission 和 Prompt test option URL 已从 implementation-facing `runtime` 术语收敛为稳定产品术语；Admin data loaders、browser fixtures、OpenAPI export allowlist、稳定 OpenAPI 和 API 合同回归已同步。Workflow C missing-parent import 现在稳定返回 unavailable，Bootstrap 默认草稿与严格 create schema 的字段集合一致。`pytest --cache-clear --ignore=tests/integration -q`、OpenAPI export/verify 和 `make quality` 已运行。本项只证明仓库内合同回归，不替代 durable Workflow C API composition、真实模型/Provider 或最终 evidence manifest。
- [x] `IMPL-NONB-QUALITY-GATE-2026-07-23` 当前工作树已通过 `make quality`：Ruff、667 个 Python source 的 mypy、双 Web TypeScript、受披露 legacy backup plaintext scan、repository secret scan 与 42 项 architecture tests 均无失败。Customer Workflow C durable reader 的结构协议现由 `Literal["durable"]` 明确；Sampling Suite PostgreSQL integration fixture 拆为 606 行 test 和 346 行 shared support，未放宽 800 行架构限制。临时隔离 PostgreSQL 另完整通过该 Suite 的一项 RLS/Job/lease/cancel/retry 集成回归。本项仅记录本次代码质量基线，不替代 `REPO-GATE-01..08` 的最终 evidence manifest、独立 verifier 或 live evidence。
- [x] `IMPL-NONB-BROWSER-PORT-ISOLATION-2026-07-23` 三份 required Chromium config 的自动 Next server 均可由独立、严格校验的 `PLAYWRIGHT_*_SERVER_PORT` 覆盖，Base URL 与监听端口保持同值；已配置 external Base URL 时仍不启动本地 server。隔离端口 `3110/3190`、`3111/3191`、`3201/3291` 实跑 `make test-browser-chromium`，Admin 25、Customer 4、Workflow C 3 项均通过；正常 `3100` 服务未被停止或复用，runner 的 `finally` 后 `apps/admin-web/next-env.d.ts` hash 与正式 `.next` 基线一致。该项仅闭合本地测试端口兼容性和 Chromium 回归，不替代 `REPO-GATE-05` 的最终 production evidence manifest。
- [x] `IMPL-NONB-INFRA-RUNTIME-2026-07-23` `make test-infra-contracts` 通过 71 项 Compose、production preflight 与认证 backup contract；`make test-infra-runtime` 在独立 Compose 项目执行 F018 production-network、compose health、runtime readiness dependency 与 PostgreSQL runtime heartbeat。2026-07-23 已从空库完整迁移到当前 `0064_wfc_artifact_hold_expiry` 并成功完成该 Gate，随后复核无 `geo-f018-runtime-*` 容器或卷残留；此前 `0063` 的 7/7（62.59 秒）保留为历史基线。runner 现将 Compose cleanup 的非零返回码提升为失败并输出诊断。`0062/0063/0064` 的单独 PostgreSQL upgrade/downgrade/RLS/fence 回归分别记录在 Metric Judge、Artifact Fault Recovery 和 Legal Hold Lifecycle 子项。此项是本地隔离运行时证据，不替代 `REPO-GATE-06/07` 的生产网络、真实 secret、恢复及独立签字验收。
- [x] `IMPL-NONB-RELEASE-CONTRACTS-2026-07-23` 本次本地回归重新执行 `make openapi-contracts`、`make web-contracts` 与 `make web-build`：两份稳定 OpenAPI 已 verify，API client TypeScript 与 Auth BFF 四项合同测试通过，Admin/Customer 两个 production Next build 成功完成。构建后 `apps/admin-web/next-env.d.ts` 保持正式 `.next/types/routes.d.ts` 引用，OpenAPI verify 未产生新增稳定合同差异。本项只覆盖仓库内 API/前端发布合同，不能替代 `REPO-GATE-02/05` 的真实环境、独立 verifier 或最终 evidence manifest。
- [x] `IMPL-WORKFLOW-C-ANALYSIS-PROJECTION-PROJECT-SCOPE-2026-07-23` `0059_analysis_project_scope` 已将 Workflow C 分析内容 hash 与租户身份分离：Semantic Snapshot/Result、Comparison Family/Result、Drift Report 分别以 Project-qualified primary key 写入，child projection 的 Project 列由父 projection 回填并经 `(hash, project_id)` FK 固定归属；Worker persistence 的 `ON CONFLICT` 与 equality read 亦始终携带 `lease.project_id`。Comparison child RLS 由 Project 列过滤，Recommendation SECURITY DEFINER evidence resolver 的 comparison join 同时匹配 `family_hash` 和 `project_id`，不再能在 row security 关闭时混合相同 hash 的不同 Project。隔离 PostgreSQL 以两个 Project 的同一 Snapshot/Family/Report hash 验证双写成功、每个 App scope 只读自身、Recommendation 解析的 `project_id` 正确，以及这类重复 identity 会阻断向旧全局主键 schema 回退；迁移 ID 保持在 `alembic_version.version_num` 的 32 字符限制内，并已通过 SQL ledger 构建。Customer report projection historical fixture 同步只构造最小合法 draft policy，不伪造已批准采样授权。本项只闭合分析投影隔离和迁移契约，不替代 `IMPL-WORKFLOW-C-METRIC-WORKER`、完整统计 live evidence 或最终 manifest。
- [x] `IMPL-NONB-REQUIRED-NON-LIVE-REGRESSION-2026-07-23` 第 37 次修订后已执行 `make test-migrated`：严格 marker、`--fail-on-skipped` 的 required non-live suite 收集 1994 项，`1994 passed, 0 failed, 0 skipped`，耗时 429.78 秒。该项仅提供无 integration/live/browser 条件下的仓库回归基线；隔离 PostgreSQL/MinIO、真实 Provider/账号、Chromium、性能和最终 evidence manifest 仍须按各自 Gate 另行验收。
- [x] `IMPL-WORKFLOW-C-METRIC-TERMINAL-RPC-2026-07-23` `0060_metric_rpc_aggregate_fix` 修复 Metric Judge/Arbiter completion 与 failure SECURITY DEFINER RPC 的真实 PostgreSQL 编译错误：其 `RETURNS TABLE(aggregate_version ...)` 输出变量曾与未限定 `SET aggregate_version = aggregate_version + 1` 冲突，导致 Judge terminal write 抛出 `AmbiguousColumn`。迁移从已审计的 predecessor function definition 重编译，逐项保留原 fence、RLS、权限与 validation，只将两个 aggregate 写入限定为 `workflow_c_metric_judge_batches.aggregate_version`；down 也先验证当前 definition 再还原。隔离 PostgreSQL 已完成 `head -> 0059_analysis_project_scope -> head`，并以最小 `geo_worker` 登录验证有效 lease Judge completion、child/batch 状态推进、direct child update 拒绝、重复 terminal completion fencing 和跨 Project fail-closed。该项仅闭合 terminal RPC；`IMPL-WORKFLOW-C-METRIC-WORKER` 仍需 typed producer、加密任务/MinIO、Model Gateway、arbiter、取消/失败恢复和 live evidence。
- [x] `IMPL-WORKFLOW-C-METRIC-CHILD-RECONCILIATION-2026-07-23` `0061_metric_child_reconcile` 闭合 Metric child 在 shared dispatcher 重试、死信或取消后的 aggregate recovery：Database trigger 只匹配 `workflow_c.metric_judge|metric_arbiter`，逐项锁定 Child/Batch、验证 Job kind/role、parent lineage 和 Project，并以 batch advisory lock 串行同批异常。`retry_wait` 仅修复遗留 `running -> queued` child；`failed|dead_lettered|cancelled` 则终结当前 child 与尚未终结的 batch，立即取消 queued/retry sibling、向运行 sibling 写入 cancel request，保留已先发生的 batch failure。隔离 PostgreSQL 已完成 `head -> 0060_metric_rpc_aggregate_fix -> head`，以最小 `geo_worker` Job Store 验证 retry、最终 failure、queued sibling 取消、running sibling cooperative cancel 与显式 cancel；Ruff、mypy、Web typecheck、密钥扫描和架构测试通过。此项只闭合异常终态，不替代 `IMPL-WORKFLOW-C-METRIC-WORKER` 的 typed producer、加密任务/MinIO、governed Model Gateway、arbiter、完整 API/read model 或 live evidence。
- [x] `IMPL-WORKFLOW-C-METRIC-JUDGE-AGREEMENT-2026-07-23` `0062_metric_judge_agreement` 将 Judge 一致性收敛放入既有 fenced completion RPC：只有 `>=2` 个同一 batch 的 `metric_judge` child 全部 `succeeded`、各自存在 output hash 且唯一 hash 数为一时，才按 `evaluator_id, candidate_id` 选择结果、写入 selected candidate/hash 并完成 batch；未完成或不同 hash 继续 `running`，Arbiter 的 validation/完成路径不变。迁移和 down 均使用版本控制的完整 function source，避免 `pg_get_functiondef` 格式差异；静态 migration/worker/semantic 定向回归 30 项、Ruff、diff check、SQL checksum ledger，以及隔离 PostgreSQL `head -> 0061 -> head`、真实 Project-scoped worker、完整 Sampling Run/Observation FK lineage、直接写入拒绝和 replay fence 均通过。该项只闭合一致 Judge 分支，不替代 `IMPL-WORKFLOW-C-METRIC-WORKER` 的 typed producer、分歧后的 Arbiter 调度、加密任务/MinIO、模型调用、完整取消/失败恢复或 live evidence。
- [x] `IMPL-WORKFLOW-C-METRIC-OUTPUT-PROJECTION-2026-07-23` `0065_metric_output_projection` 让 Metric Judge/Arbiter current Worker 在 fenced completion RPC 内，以结果 canonical hash 绑定并写入最小化 `results|overall_status|output_locale` 或 `disposition|selected_candidate_id|considered_evaluators|issue_codes` projection。投影保存到独立 `(project_id, child_job_id)` append-only/FORCE-RLS 表，避免触碰本身不可变且可能含退役 Prompt Binding 引用的 child lineage；App 无表权限，Worker 只读，写入只能经十一参数 RPC。兼容十参数 RPC 仍可让 rolling deployment 的 child 终结，但不创建投影，future parent reader 必须将其视为不可消费。隔离 PostgreSQL 通过 `head -> 0059 -> head`、最小 Worker scope/fence、projection hash mismatch 不改变 child、legacy no-projection、matching Judge agreement 和 terminal reconciliation；F018 空库运行时门禁也已到 0065。该项只提供 parent merge 的安全输入，不替代 typed producer、父任务 wake/recompute、分歧 Arbiter 调度、模型/MinIO live evidence。
- [x] `IMPL-WORKFLOW-C-METRIC-TASK-FACTORY-2026-07-23` Metric child producer 的纯 contracts 现以唯一 factory 构造 Judge/Arbiter task：Judge 只从 `MetricJudgePlanBatch`、主体、citation 与已解析 Model request 取得输入，绝不继承 Observation 里已有的 judge outputs；Arbiter 只接受 exact disagreeing candidate/evaluator set，并冻结可见 evidence/citation refs。factory 把 canonical task JSON hash 后，以 `(project_id, child_job_id, workflow_c.metric_model_task, v1)` Secret envelope 加密；解密仍通过现有 strict parser。定向 Ruff、mypy 和 35 个 Worker/semantic/migration 单元回归证明 hash、AAD、batch plan、裁判分歧门槛与 task schema。该项不创建任何 Job、child row、outbox 或模型调用，`IMPL-WORKFLOW-C-METRIC-WORKER` 继续等待 typed producer、reservation、parent wake/merge 和 live evidence。
- [x] `IMPL-WORKFLOW-C-METRIC-SELECTED-READER-2026-07-23` parent-facing reader 只从 `completed` batch 连接 `selected_candidate_id/selected_output_hash` 的 succeeded Judge child 与其独立 projection；它重新解析每个 result/locator、重算 canonical output hash，并拒绝任何缺失 projection、legacy 十参数 completion、非 selected candidate、未完成 batch 或结构漂移。隔离 PostgreSQL 在真实 Worker scope、matching Judge agreement 和 terminal reconciliation 后执行该读取路径；无 raw model response、rationale 或秘密进入 projection/read model。该项仅提供 future parent merge 所需的 fail-closed 输入，不替代 batch/child typed producer、分歧 Arbiter schedule、parent wake/recompute 或 live evidence。
- [x] `IMPL-WORKFLOW-C-METRIC-PARENT-MERGE-CONTRACT-2026-07-23` `merge_selected_metric_judge_batches` 只接受按当前冻结 input/suite 重算出的完整 batch 集，拒绝重复、缺失、过期 hash、canonical batch 漂移及预存的 model judge output；每个 selected candidate 再逐项复核 exact `metric_id/kind`、suite judge schema、observation/fact/citation/answer-span lineage，并拒绝 locator 越过其 frozen plan 的 allowed evidence。定向 Ruff、mypy 与 13 项 semantic/Worker 单元回归覆盖 complete merge、缺 batch 和将仍合法的 corpus result 重新绑定到 recommendation plan 的负例。此项是纯领域 merge，不创建 parent Job、child/Arbiter admission、Job Spec/outbox、wake/recompute 或模型调用，`IMPL-WORKFLOW-C-METRIC-WORKER` 仍不得勾选。
- [x] `IMPL-WORKFLOW-C-METRIC-PROGRAM-INPUT-2026-07-23` Metric Judge/Arbiter task factory 现将实际评估上下文写入加密 task 的 `ModelGatewayRequest.messages`：Judge 使用 `MetricJudgePlanBatch.program_input` 的精确 Observation、Fact/evidence、subject 和 plan 集；Arbiter 使用同一受限输入以及每个分歧候选的 ID、evaluator、canonical output/hash 与允许 evidence/citation 集。输入使用确定性 JSON，仍由 task hash、Project/child AAD 和既有 application-side output validation 约束；不会把任意 task 内部字段隐式暴露给模型。定向 unit 回归确认解密后请求含完整 Judge input 与 exact Arbiter candidates。此项不替代 typed durable producer、Batch/Arbiter admission、parent wake/merge、模型 live evidence 或最终 manifest。
- [x] `IMPL-WORKFLOW-C-METRIC-PARENT-ADMISSION-2026-07-23` `0066_metric_parent_admission` 与 typed `PostgresWorkflowCMetricJudgeParentAdmissionRepository` 已完成首批 Judge producer：从冻结 `MetricInputSet + Suite + Prompt/runtime evaluator` 重算 batch，使用 parent lease 构造 per-Judge encrypted task，并在一个 Worker-only、fenced PostgreSQL RPC 中原子写入 batch、child、Durable Job、secret-free immutable spec、outbox 和 event。数据库同时验证 approved runtime、frozen Prompt、可用/可解密 key version、至少两名不同 evaluator、public spec canonical hash 及 public `task_hash == durable.input_hash`；普通 Job Spec hash 合同保持不变。Ruff、mypy、65 项定向 unit/migration 回归及隔离 PostgreSQL `head -> 0065 -> head`、restricted Worker、duplicate/direct-write/terminal-reconcile 路径通过。该项只准入 Judge；父 operation 尚未调用并 defer/wake，分歧 Arbiter admission、parent selected-projection merge、snapshot persistence 与 live evidence 均不得视为完成。
- [x] `IMPL-WORKFLOW-C-METRIC-ARBITER-PREPARATION-2026-07-23` Arbiter child 的 typed preparation 现要求 exact disagreeing Judge resolution 和全部 candidate UUID identity；它以确定性 parent/batch/evaluator identity 创建 encrypted task，并冻结候选 ID/evaluator/canonical output hash、允许 evidence/citation 与 Arbiter Prompt/runtime request。公开 spec 仍只有 schema/kind/child reference，不能包含 Answer、candidate、model output 或 secret；一致 Judge 集合或自由字符串 candidate ID 都会在任何 admission 前 fail closed。Ruff、mypy 与 8 项当前 Metric preparation/task-factory 回归通过。该项不创建数据库 child/Job/outbox，不触发 Arbiter 模型调用，也不替代 `0067` atomic admission、parent wake/merge 或 live evidence。
- [x] `IMPL-WORKFLOW-C-METRIC-ARBITER-ADMISSION-2026-07-23` `0067_metric_arbiter_admission` 与 typed `PostgresWorkflowCMetricArbiterAdmissionRepository` 已将分歧 batch 的唯一 Arbiter producer 收敛为 Worker-only、fenced PostgreSQL RPC：它重检 parent Job/spec/hash/lease、approved runtime、frozen Prompt、可解密 key 与 canonical secret-free public spec，锁定 batch 后要求全部 Judge child `succeeded`、output hash 存在、每个 hash-bound output projection 存在且至少两个输出不同，才同事务创建 encrypted Arbiter task、Durable Job、immutable spec、child lineage、batch reference、outbox 和 enqueue event。隔离 PostgreSQL `head -> 0066 -> head` 已以最小 Worker 验证缺 projection 零写入、补齐分歧投影后成功、重复 admission/direct child update 拒绝；Ruff、mypy、migration contract 与定向 unit 回归通过。该项只闭合 Arbiter admission，不替代父 operation 对 Judge/Arbiter 的 defer/wake、selected-projection merge、snapshot persistence、模型 live canary 或最终 evidence manifest。
- [x] `IMPL-WORKFLOW-C-METRIC-PARENT-PROGRESS-2026-07-24` `0068_metric_parent_progress` 将 Metric parent operation 的 progress/recompute 读取收敛为两条 Worker-only SECURITY DEFINER reader：batch reader 仅返回父 `semantic_metrics` Job 的最小 batch status；Judge reader 仅返回指定 batch 的可消费、hash-bound Judge projection。每次读取都校验 Project scope、父 Job/lease token/fencing、frozen spec hash、Job `running`、有效 lease 与未取消状态，普通 App/readonly 无执行权，原始模型输出、加密 task 与 secret 均不在返回面。`head -> 0067 -> head`、受限 `geo_worker` reader/Judge resolution、Ruff、mypy、50 项定向单元/迁移基线及 PostgreSQL 集成均通过。该项不替代 parent 的完整 snapshot persistence、真实模型调用、live canary 或最终 evidence manifest。
- [x] `IMPL-WORKFLOW-C-METRIC-SNAPSHOT-PERSISTENCE-2026-07-24` `0069_metric_snapshot_rpc` 以单一 Worker-only SECURITY DEFINER RPC 持久化 Semantic Snapshot 与其 Result 投影；RPC 在同一 parent finalization transaction 中复核 Project scope、父 Job/spec frozen hash、lease token/fencing、有效 running lease 和取消状态，随后验证 snapshot canonical hash、payload/result 行对应、数量守恒、结果哈希和不可变冲突。`geo_worker` 的 snapshot/result `INSERT/UPDATE/DELETE` 明确撤销，应用代码改为调用 RPC 后仅做 Project-scoped equality read，再以同一 fenced transaction 终结 Durable Job。空库 migration、`head -> 0066 -> head`、restricted Worker direct insert 拒绝、Judge agreement 后 parent resume、snapshot/result 落库和 Job `succeeded` 均通过；Ruff、mypy、31 项 migration/ledger 和 50 项相关 unit/API 也通过。该子项只闭合 Metric parent 的最终持久化，不能替代剩余指标族、真实模型调用、Provider/live canary 或最终 evidence manifest。
- [x] `IMPL-WORKFLOW-C-COMPARISON-DRIFT-PERSISTENCE-2026-07-24` `0070_analysis_projection_rpc` 以两个 Worker-only SECURITY DEFINER RPC 持久化 Comparison Family/Result 与 Drift Report；写入前验证 canonical family/report hash、结果行与 family payload、Project、Job/spec frozen hash、lease token/fencing、有效 running lease 和取消状态，随后在同一 fenced transaction 内写入不可变投影。`geo_worker` 对 comparison/drift 三表的 `INSERT/UPDATE/DELETE` 已撤销，Python operation 仅调用 RPC、做 Project-scoped equality read 后终结 Job。统计 Python hash 采用 code-point key order，故迁移新增仅用于新 RPC 的 C-collated canonical JSON helper，避免 PostgreSQL locale 造成 `a_`/`ad` 键序漂移且不改变历史 hash。隔离 PostgreSQL 完成 `head -> 0069_metric_snapshot_rpc -> head`、受限 Worker direct insert 拒绝、comparison/drift operation 实际落库与 Job `succeeded`；该项不替代实际 business admission、真实模型/Provider、live canary 或最终 evidence manifest。
- [x] `IMPL-WORKFLOW-C-COMPARISON-DRIFT-ADMISSION-2026-07-24` `0071_analysis_job_admission` 让 Comparison/Drift 不再依赖 admin test fixture 或 `session_replication_role`：`geo_app` 只能以 secret-free、schema v1 的完整 frozen analysis payload 经过通用原子 producer 入队；Python 先调用同一严格统计 decoder，PostgreSQL 再验证 exact envelope、stratum、hash、decimal、数组与相异 snapshot，并在分析 kind 上以 C-collated Python canonical JSON 重算 spec hash。无效 direct RPC 在任何 Durable Job/spec/outbox 前拒绝；有效 App command 由受限 Worker claim 后执行 comparison/drift operation，最终完成 fenced projection 与 Durable Job。迁移 round trip `head -> 0070_analysis_projection_rpc -> head`、App/Worker 最小登录、direct malformed input 和两种成功执行均已通过。此项只完成冻结输入的受控命令准入，不替代由真实 approved Observation/Snapshot 服务器解析输入、完整 durable Internal API/read model、live Provider 或最终 evidence manifest。
- [x] `IMPL-WORKFLOW-C-ANALYSIS-DURABLE-READ-MODEL-2026-07-24` `PostgresWorkflowCAnalysisReadRepository` 以 App RLS project scope 读取 immutable Semantic Snapshot、Comparison Family、Drift Report，并以稳定 computed-at/hash 排序；它不读取 encrypted task、worker-only Job spec 或 HTTP compute payload。`PostgresWorkflowCAnalysisRuntime` 在 production-shaped adapter 中只开放上述 read，三个 compute command 统一 fail closed 为 `503 unavailable`。Presenter 对数据库 projection 重新计算 root/result hash，并核对 semantic 的可比较 input/suite header 与 canonical payload；Sampling `source_stratum_hash` 与 Metric payload `stratum_hash` 分属不同 lineage，不会错误要求相等，结构/哈希漂移不会渲染为 API 成功。隔离 PostgreSQL 已在真实受限 App role、worker fenced semantic/comparison/drift write 后验证三类投影读回与 hash response、异 Project 空列表；此项尚不完成 Comparison/Drift 的真实 approved Observation/Snapshot server resolver、Protocol/Plan version lifecycle、全局 Workflow C composition、live Provider 或 final manifest。
- [x] `IMPL-WORKFLOW-C-DURABLE-GLOBAL-COMPOSITION-2026-07-24` `build_workflow_c_api` 现从实际 `geo_api.workflow_c_postgres` composition root 组装 Sampling 的 project-RLS PostgreSQL controls、Analysis 的 immutable projection reads 及 Alert lifecycle control，成功时唯一标记为 `durable`，任何构造失败均不返回 memory fallback。`0072_wfc_artifact_keyring_reader` 只向 `geo_app`/`geo_worker` 暴露非 retired key version、状态、算法和加密 canary；Internal API writer 先以 read-only transaction 调用 RPC 验证挂载 keyring，再使用既有最小写权限创建 DEK/工件。隔离 PostgreSQL 证实 App 可读 canary 而 direct master-key table SELECT 被拒绝；单元验证 RPC-only/rollback 及三 vertical durable 组合。Analysis compute 仍明确 `503`，此项不替代真实 approved Observation/Snapshot resolver、Provider/Browser capture、对象存储 live canary 或 final evidence manifest。
- [ ] `IMPL-B-SEARCH-AGGREGATION-PROTOTYPE-2026-07-24` 已合并 SerpAPI Google AI Overview/Bing Copilot 与 OpenRouter OpenAI Web/Perplexity 的即时 Internal API 原型，并完成其 adapter 单元测试、Ruff、MyPy 与稳定 OpenAPI 合同更新。它不是 B 连接器或消费者 UI Sampling 实现：没有 Connector Core/GSC/GA4/官方报告、Google AI Mode、澳洲 sticky egress、Browser Capture、Surface Release/授权、Secret Store、Durable Job、工件/Attempt/Observation/SourceStratum、项目预算/RBAC 或 Customer approved projection；缺密钥时 mock success 与 raw 调试响应也必须在正式化前治理。完整阻断 checklist 见 `docs/engineering/search-aggregation-capabilities.md` 第 0 节；本项保持未完成，不得计入任何 B Gate 或真实证据。
- [x] `IMPL-NONB-CROSS-WORKFLOW-QUALITY-2026-07-23` 在并行 Non-B 改动汇合后重新执行 `make quality`：Ruff、668 个 Python source 的 mypy、Admin/Customer Web typecheck、repository secret scan 与 42 项架构测试均通过；backup plaintext scan 只披露两份既存 legacy 演练目录。复查同时将 Metric Worker/contracts 从超出单文件预算的 601/812 行拆为 600/599/389 行的 execution/contract/value 模块，保持 contracts public import 兼容；projection reader 显式重建 `JudgeKind` 并拒绝未知值。该质量门禁不替代迁移、真实 PostgreSQL/MinIO、OpenAPI/build、Chromium、性能、live staging 或最终 evidence manifest。
- [x] `IMPL-WORKFLOW-C-METRIC-IMPORT-ORDER-2026-07-23` Metric worker contracts 的 split 后复查将纯 `MetricChild`/task dataclass 与 contract error 移入 dependency-light types module，避免 `values` 首次 import 反向加载 contracts 时取得未初始化 re-export。现依赖方向为 `types -> values -> contracts`，既有 `workflow_c_metric_judge_worker_contracts` public import 保持可用。direct values-first import、Ruff、mypy 与 13 项 Metric semantic/Worker 单元回归通过；随后完整 `make quality`（669 Python source、双 Web typecheck、scans、42 architecture tests）亦通过。此项仅修复模块可用性，不创建 Metric parent Job、child admission、outbox/wake 或模型调用。
- [x] `IMPL-NONB-INFRA-RUNTIME-0065-2026-07-23` F018 已在独立 Compose 项目从空 PostgreSQL 完整迁移至 `0065_metric_output_projection`，并成功执行 production-network、Compose health、runtime readiness dependency 与 PostgreSQL heartbeat；随后复核无 `geo-f018-runtime-*` 容器、网络或卷残留。此项更新此前 0064 runtime 快照，但不替代生产网络、真实 secret、恢复演练或独立 verifier。
- [x] `IMPL-NONB-AUTHENTICATED-RESTORE-2026-07-23` 认证备份/恢复已在隔离空环境保存并恢复 PostgreSQL ACL；临时 `NOINHERIT` canary 显式切换为恢复后的 `geo_app`、`geo_worker`、`geo_readonly`，验证正确 Project scope 可见、空 scope 不可见和 Worker-only dispatch 权限隔离。2026-07-23 的随机 Compose 实跑恢复至 `0051_synthetic_parent_scope`，receipt SHA-256=`8860d11486a9990a6103a089dc373f34a52d3a9bfde7759921fa4aa8cff61bc1`、manifest SHA-256=`428f1038fc49f66f44fa2e95265ea8484a3b19a250d4614bf6c8cb26e6683f01`；五桶逐一 count/hash、历史 keyring、冻结 `restore_probe` Secret handle/receipt/audit，以及错误/缺失 HMAC、历史 key、服务身份、receipt 或 ACL/RLS 的 fail-closed 路径均通过，临时容器和卷已清理。此项不替代生产备份演练、独立 verifier 或最终签字。
- [x] `IMPL-FIVE-BUCKET-MINIO-LEAST-PRIVILEGE-2026-07-23` 使用全新隔离 MinIO 和临时、互异的 test principal 执行 `infra/minio/bootstrap.sh`：应用身份无法 delete/CreateBucket/admin 或访问三类 restricted bucket；Workflow C writer/reader/deleter 分别验证写入、只读、删除与跨桶拒绝；Recommendation writer/delete-only 与 Synthetic writer/delete-only 验证写入、删除、读取拒绝、写入拒绝及跨桶拒绝。restore/retention ephemeral identity 随后被实际撤销且旧凭据无法列举；同一实例重复 provision 成功。完整 bootstrap receipt SHA-256=`883b52261b004b0db0034811f0d5fbbce4b0806dfef6eb824f5e8ce88ba2f01d`，撤销 receipt SHA-256=`e0089d22bdbe14d5408534a730bf7d9146a634dccb5ea041b0801f1b649cc213`，均为 `0600`。演练修复 `minio/mc` 缺 `cmp`、单对象 `mc rm` 对 delete-only identity 的隐式读取和过宽默认 umask；测试容器已清理。本项只证明 production policy 的本地功能，不替代生产身份、基础设施加密、live staging evidence 或独立签字。
- [ ] 静态、单元、隔离 PostgreSQL/MinIO/Valkey、OpenAPI、双 Web build、Chromium 与故障/恢复演练完成；对应实际计数、skip 和 artifact hash 写入 manifest。
- [ ] 非 B 功能完成独立复查和易用性修正；之后才评估是否可删除仓库根目录的临时持续执行指令。
