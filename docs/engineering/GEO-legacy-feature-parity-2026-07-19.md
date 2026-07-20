# GEO 旧版功能兼容性复查报告

> 复查日期：2026-07-19
> 旧版基线：`267d9708a8ec859e74027ecde9a38cd6403c2ff1`
> 候选分支：`feat/geo-accepted-remediation-20260719`
> 状态：`READY_FOR_USER_CONFIRMATION_NOT_MERGED`

## 1. 结论

在“维护窗口、停止旧进程、数据库升级、同一版本整体启动”的部署模型下，旧版的仓库内
用户功能、历史数据和持久任务均已保留、完善，或获得了明确且可操作的安全迁移路径。
最终代码审查没有剩余 P0/P1，真实 PostgreSQL/MinIO、双 Web、OpenAPI、Compose 和浏览器
门禁均通过。

这不等于仓库外旧 HTTP 客户端可零修改继续调用。新版强化了 Campaign、Prompt Release、
来源分层和统计口径，部分保留路径新增必填参数或请求字段。随仓 Admin/Customer Web、API
Client、API、Worker 和 Relay 已同步迁移；仓库外调用方必须在维护窗口前完成合同迁移。

| 复查维度 | 结论 | 说明 |
|---|---|---|
| 仓库内用户工作流 | PASS | 旧页面/路由无删除，新版流程可完成相同目标并增加治理门禁 |
| 历史数据读取 | PASS | 历史 Source、Fact、Evidence、Bundle、Simulation、Package、Publication、Metric 等保持可读 |
| `0010 -> 0026` 数据升级 | PASS | populated 旧库、空库、`0026 -> 0025 -> 0026` 均验证 |
| 升级时持久任务 | PASS | 7 类旧业务 Job 的 queued/expired-running/terminal 路径均有真实 PostgreSQL 证据 |
| 新旧进程混跑 | NOT SUPPORTED | 必须维护窗口原子切换，旧二进制不得写新 schema |
| 仓库外旧 `/v1` 请求 | PARTIAL | operation 未删除，但部分参数和 body 合同不再原样兼容 |
| 外部 staging/付费模型 | NOT EXECUTED | 未获双重授权，未发起真实外部或付费调用 |

## 2. 表面清单

| 清单 | 旧版 | 新版 | 删除 |
|---|---:|---:|---:|
| Internal API paths / operations | 93 / 120 | 112 / 144 | 0 / 0 |
| Customer API paths / operations | 12 / 12 | 15 / 15 | 0 / 0 |
| Admin + Customer `page`/`route` | 17 | 20 | 0 |
| `scripts/` 文件（排除依赖目录） | 26 | 36 | 0 |
| 测试源文件 | 60 | 165 | 0 |
| Python test functions | 236 | 558 | 3 个旧名称由更强 v2 测试替代 |

仅删除了两份会制造错误可观测性预期的 Prometheus/Grafana 假配置。当前阶段没有对应真实
采集服务；删除行为符合 F-018 已接受决策，生产运行改由 readiness、heartbeat、队列卡滞
和 Compose healthcheck 提供真实信号。

三个未保留原名称的旧统计测试分别由更严格的 v2 分母、来源分层、非因果报告和引用血缘
测试替代。基线已有的 57 个 Python 测试文件在新代码上单独执行为 321 passed。

## 3. 历史对象处置

| 对象 | 升级后行为 | 新操作 |
|---|---|---|
| Knowledge Source/Run/Chunk/Fact | 历史记录可读；旧内容不会绕过 active/current 门禁 | 重新处理后生成当前 Chunk、RAG、Fact，再审批提升 |
| 旧 Fact/Evidence | 历史 Evidence 保留，无法证明的新血缘不被伪造 | 通过 Fact 身份和当前 Chunk 重新提升 |
| 旧 Prompt Bundle | 可读、可审计，Admin 明示“迁移历史、只读” | 返回证据步骤，以 approved Opportunity Release 绑定重建 |
| 旧 Prompt Simulation | 项目级可读、可下载；合法在途 generation/artifact 可续跑 | generation 新 replay 禁止；失败 artifact 可按冻结血缘 replay 完成 |
| 旧 Monitoring Protocol/Observation/Metric | 历史结果可读，但不会冒充 statistics-v2 官方口径 | 建立 v3 来源分层和 statistics-v2 Protocol 后重新采集/计算 |
| 缺少 query cluster 的旧建议 | 可见、只读；应用层和持锁 Repository 均拒绝审批 | 新建带显式 cluster key 的建议 |
| 旧 Package/Review/Export | 历史工件保持不可变、可读 | 只有当前 Fact/Chunk/Bundle 血缘可进入新审核、导出和发布 |
| 旧 Publication/Submission | 历史人工记录和核验 attempt 保留 | 新核验/提交仅在当前合同下创建；已入队合法核验可终态协调 |

## 4. 持久任务兼容

基线共识别 7 类业务 Job，并使用真实 `0010` 数据覆盖 queued、expired-running、幂等重放、
取消和终态：

| Job kind | 处置 |
|---|---|
| `knowledge.process` | 续租、接管、完成并派生 RAG；二次调度不重复模型调用 |
| `evidence_pack.build` | 续跑或接管，Evidence Pack 结果幂等 |
| `artifact.finalize` | 续跑；parentless 旧根任务和历史多层 replay 使用精确业务血缘识别 |
| `placement.generate` | 缺少 v2 Bundle 的旧 Job 结构化终止并给出 rebuild operator action |
| `placement.measure` | 合法任务续跑；核验暂态用不消耗 attempt 的 defer，失效时不污染指标 |
| `publication.verify` | 仅已冻结完整核验合同的在途任务续跑；latest-job/sibling/manual-terminal 一致 |
| `prompt_simulation.generate` | 精确 `legacy-v1` 冻结输入可续跑；任意 null-Campaign Job 仍 fail closed |

Publication 核验使用 `(created_at, id)` 最新 Job 所有权和
`job -> opportunity -> submission/request` 锁序。重核期间保留上一次已验证投影；只有权威
内容失败或血缘失效才撤销。Measurement 执行、人工记录和任务完成都会再次检查当前
verified 状态。

## 5. 最终测试证据

| 门禁 | 最终结果 |
|---|---|
| `make test-migrated` | 565 passed / 73 deselected |
| 基线已有测试文件集 | 57 files；321 passed / 17 deselected |
| `make quality` | Ruff；mypy 225 files；6 Web workspaces；Architecture 13 passed |
| `make test-integration-required` | fresh PostgreSQL/MinIO；70 passed / 0 skipped |
| Legacy populated upgrade 子矩阵 | 10 passed，包含 `0010 -> 0026` 与 7 类 Job |
| `make openapi-contracts` | 2 surfaces verified；6 passed |
| `make web-contracts` | API Client type contract + Auth BFF 4/4 |
| `make web-build` | Admin/Customer production builds passed |
| `make test-browser-chromium` | Admin 13/13；Customer 4/4；0 skipped / 0 flaky |
| `make test-infra-contracts` | 34/34 |
| `make test-infra-runtime` | isolated Docker 6/6 |
| `make test-production-network` | 1/1 |
| `make f019-benchmark` | dataset and selected Project Native report valid |
| `geo-acceptance-inline` | `legacy-parity-final-20260719`；`inline_isolated` passed |

Inline acceptance 报告 SHA-256：
`b96a3de4532ecec82cb60423a969a6a610feed7cd2c924ea9ef3a5bc125a8a5c`。

## 6. API 兼容边界

旧 API operation 均仍存在，但保留 operation 中：

- Internal 有 47 个 operation 新增必填 `campaign_id`，Prompt Bundle POST 另新增必填
  `Idempotency-Key`；
- Customer 有 5 个读取 operation 新增必填 `campaign_id`；
- Prompt Bundle/Simulation 创建改为 Campaign + Opportunity + approved Prompt Release binding；
- Monitoring Protocol、Observation、Metric、Suggestion、Report 写入新增或重构统计与来源字段；
- 通用 `approved_fact` Evidence 创建收窄为专用 Fact promotion 路径。

因此“旧功能保留”是功能和数据层结论，不是旧 HTTP 请求字节级兼容结论。OpenAPI 快照只
检测当前实现与当前合同一致，不能单独证明与旧版本兼容。生产升级必须遵循
`docs/operations/production-runbook.md` 的原子切换与整库快照回退流程。

## 7. 已知非阻断项

- 核验失效前已经打开的 Measurement Task 仍显示 `open`，但新增测量和完成操作均会被
  current-verified 门禁拒绝，不会污染统计；
- 长期处于可修复 `failed` 的 Submission 会每 6 小时产生一次少量 defer/outbox 事件，
  直到复核成功或运营人员显式 block/cancel；
- 真实外部渠道发布、客户生产 OIDC/TLS/Secret 和付费模型调用未在本轮执行。

## 8. 合并门禁

2026-07-20 的后续独立复核提出 8 项问题，现已全部修复并增加对应回归：Customer API
即时导出不再依赖对象存储；URL 验证拒绝嵌入非公开 IPv4 的 IPv6 地址、支持已验证地址
回退和国际化 URL；导出取消保持 cancelled 语义；问题预算按 turn 批次计算；两个 CSV
出口统一中和公式前缀；Admin 在导出失败、死信或取消时立即停止轮询并显示终态。

候选分支已达到请求用户确认的条件，但尚未合并。用户确认时应同时接受：

1. 功能/历史数据/在途任务结论为 PASS；
2. 仓库外旧 `/v1` 客户端需要预迁移，部署采用单版本原子切换；
3. 外部 staging、真实人工渠道发布和付费模型不属于本次本地兼容性证明。
