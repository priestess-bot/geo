# ADVINSYS 真实生产路径验收记录（2026-07-29）

## 1. 验收结论

项目 `ADVINSYS Australia` 已在当前 staging 从目标公司资料重新导入，并跑通仓库和当前环境能够控制的真实路径。系统当前可用于继续人工审核和接入真实外部账号，但尚不能宣称完成澳洲消费者界面、GSC/GA4、Provider API、九渠道合成测评或真实营收归因验收。

当前结论：

- 本地生产路径：`GO`。
- Customer 已批准真实结果：`NO_GO`，当前为 0 份。
- 完整 live staging：`BLOCKED_EXTERNAL`。
- 数据库版本：`0118_rec_draft_materialize`。
- Admin：`http://localhost:13001`。
- Customer：`http://localhost:13000`。

`BLOCKED_EXTERNAL` 只表示缺少必须由业务方或外部平台提供的真实输入，不允许用 fixture、mock、技术 canary 或代理生成的数据替代。

## 2. 项目身份和导入结果

| 项目 | 值 |
|---|---|
| Project ID | `6f93ee7b-bd7f-4fca-92b2-0de17254953a` |
| 市场 | Australia / `en-AU` |
| 实体 | 4：ADVINSYS、TerraMow V600、TerraMow V1000、Seauto SAT30 |
| 目标渠道 | 10：9 个必选渠道和 1 个可选渠道 |
| Campaign | 3 |
| Opportunity | 27 |
| Monitoring Query | 6 |
| 导入清单 | `docs/target_company/advinsys-geo-project.json` |
| 导入收据 | `artifacts/runs/advinsys-production-20260729/project-import.json` |

导入收据固定了 manifest hash、运行 commit、实际行数和逐项一致性检查。旧项目在删除前已完成可恢复备份，收据位于 `artifacts/runs/advinsys-pre-delete-20260729T054115Z/manifest.json`；清理收据位于 `artifacts/runs/advinsys-production-20260729/project-purge.json`。

当前导入后的项目也已完成独立加密备份与即时恢复校验：`artifacts/runs/advinsys-current-20260729/advinsys-pre-delete-20260729T103629Z/manifest.json`，manifest SHA-256=`ec983d0b1c0f3a5f898d3492b06e91e20148088e180cb8c862a0d490fd9696e3`。恢复核对 100 个非空 Project 关系、327 个 Project MinIO 对象、Secret key version 1/2 和 1 个实际解密 canary；加密 archive 与 manifest 权限均为 `0600`。

## 3. 路径验收矩阵

| 路径 | 当前结果 | 证据或阻塞 |
|---|---|---|
| 项目导入 | 通过 | 实体、市场、渠道、Campaign、Opportunity、Query、Source、Evidence seed 均与 manifest 一致 |
| 知识采集与处理 | 部分通过 | 13 个 Source：7 个 `ready`、6 个历史修订 `archived`；941 个 Fact Candidate 均为 `pending_review` |
| 真实 RAG | 部分通过 | 官方站点、渠道登记、V600、V1000、SAT30 已取得可追溯结果；Amazon 页面没有产生可追溯 Fact，按失败保留 |
| Prompt Program | 通过 | 14 个目的完成测试与发布；收据为 `prompt-suite-publication.json` |
| Dify 工作流 | 通过 | 10 个工作流完成真实 DeepSeek canary 并激活；收据为 `dify-canaries.jsonl` 和 `dify-activations.jsonl` |
| V600 内容生成 | 通过但未发布 | Package Version `0bf28e75-a1e9-4bdb-a20b-21fd25520e2d`，状态 `generated`；没有替代人工审核或发布 |
| 建议生成 | 通过 | Job `d3245309-f0d6-4002-af45-9757decb8e33` 自动落成 Recommendation `223aee23-0f85-5f4b-a1f1-9b2e73291895` |
| 建议业务判断 | 正确阻断 | 类型 `insufficient_evidence`、状态 `draft`、0 个下游草稿；输入中没有可批准的真实 Observation/Statistic/Fact/Rule |
| 合成测评实验室 | 未开始真实实验 | 0 Sample、0 Style Collection Task、0 Profile Build、0 Execution Task、0 Terminal Result |
| Connector Core | 底座可用 | GSC 和 GA4 两个 Definition 为 `draft`；0 Connection、0 Sync，不批准定义、不伪造 Secret |
| 澳洲消费者界面 | 底座可用 | 3 个 Surface Release、0 LokiProxy pool、0 live Capture；缺真实授权、澳洲 residential/mobile sticky pool、代理侧 session/出口证明和逐 Surface 实测选择器 |
| 归因账本 | 技术路径通过 | Session→Touch→Lead→Stage→Conversion→Deal→Revenue→Snapshot lineage 完整 |
| 真实业务归因 | 未通过 | 当前唯一旅程明确分类为 `validation_canary_not_business_truth`，金额 AUD 0 |
| 外部数据报告 | 审核边界通过 | Report `d6a109bb-f878-4c65-b2d9-d018122ffdaa` 为 `in_review`，没有自动批准 |
| Customer 投影 | 通过 | 未批准报告不可见；当前 Customer 可见的已批准外部报告为 0 |
| 认证空环境恢复 | 通过 | `0118`、288 张表、118 个 migration checksum、111 个非 B 关系和五桶 12 个对象均在隔离空环境恢复 |

## 4. 真实运行说明

### 4.1 知识与 RAG

目标资料首先创建原始 Source，再由实际 Worker 抓取、解析并执行 Dify RAG。页面内容变化后没有修改旧结果，而是创建 Source Revision 并保留 replay lineage；对应收据包括：

- `artifacts/runs/advinsys-production-20260729/knowledge-reprocess.jsonl`
- `artifacts/runs/advinsys-production-20260729/knowledge-revision-recovery.jsonl`
- `artifacts/runs/advinsys-production-20260729/knowledge-rag-filter-retry.jsonl`
- `artifacts/runs/advinsys-production-20260729/knowledge-second-revisions.jsonl`
- `artifacts/runs/advinsys-production-20260729/knowledge-rag-replays-v2.jsonl`

Fact Candidate 尚未经过业务人员逐条明审，因此不能成为 approved Fact，也不能用于宣称产品事实已经正式发布。

### 4.2 Prompt、Dify 与内容

14 个 Prompt Suite 均通过当前测试合同并发布。10 个托管给 Dify 的工作流均通过实际 API canary，包括 question generation、RAG grounding、placement generation/simulation、synthetic generation/claim extraction/conflict check/revision/style profile 和 recommendation。

V600 文案由真实 Dify/DeepSeek 路径生成，结果仅停留在 `generated`。系统没有执行人工审核、批准或发布动作。

### 4.3 建议闭环

Migration `0118` 修复了“模型结果成功但 Admin 没有建议草稿”的断点。Worker 现在在同一事务内通过 fenced RPC 将 v3 生成结果物化为可见的不可变 draft，且继续禁止 Worker 直接写审批和下游草稿表。

ADVINSYS 实跑结果为 `insufficient_evidence`，这是当前输入下的正确业务结果。该 draft 已在 Admin 可见，但不会自动创建 Experiment Plan、QuestionSet、Brief 或 Sampling Plan。

### 4.4 归因与 Customer 边界

归因 canary 使用完整实体链验证 30/90 天策略、trace lineage 和快照生成，但金额固定为 AUD 0，且收据显式标记为非业务真相：

`artifacts/runs/advinsys-production-20260729/attribution-validation-canary.json`

由该 canary 创建的报告只到 `in_review`。Customer API/Web 均未显示它，证明“只展示已批准真实结果”的边界有效。

## 5. 当前不能执行的路径

以下路径没有继续执行，不是代码成功后的人工省略，而是缺少真实输入：

1. 九渠道合成测评：缺每个平台合法取得、匿名化并经人工明审的真实澳洲英文样本，以及 Profile/Corpus 人工批准。
2. 正式 Fact 与内容发布：941 个 Fact Candidate、V600 生成内容均需要业务审核人决定。
3. GSC/GA4：缺对应 Property 权限和 Secret Store 中的真实 OAuth/service-account 凭据。
4. Provider API：缺 OpenAI、Gemini Grounding、Perplexity、Microsoft Bing Grounding 和 Kimi 的可用凭据及预算。
5. 澳洲消费者界面：缺经授权的 Surface 决策、LokiProxy residential/mobile sticky pool、每次 Attempt 的 session/代理侧出口证明、登录账号和逐 Surface 实测选择器。
6. 真实业务归因：缺一条经同意的真实 UTM/trace→Session→Conversion→Deal→Revenue 旅程。
7. 最终签字：缺独立 verifier 对 live staging evidence manifest 的复核。

## 6. 一次性待提供输入

后续统一请求以下输入，未提供时其他本地工作可以继续：

- Fact、V600 内容和外部报告的人工审核决定，以及至少一名独立审核人身份。
- 九个平台各自合法样本来源、最低 200 条匿名化样本和人工明审结果。
- GSC/GA4 授权账号、Property/Scope，以及五类 Provider API 凭据和预算上限。
- LokiProxy residential/mobile provider-managed sticky pool；需要可绑定每次 capture 的唯一 session lease、pre/target/post 出口证明或可信供应商连接日志。单独提供澳洲 IP 不满足条件。
- Google AI Overviews、Google AI Mode、Bing Copilot 各自的授权评估、账号条件、入口和实测 selector/parser release。
- 一条可用于 staging 的真实业务归因旅程及其收入确认口径。
- 独立 verifier 身份与最终验收窗口。

所有凭据只进入 Secret Store/Docker Secret，不写入本文件、Job、日志、Git 或 artifact。

## 7. 发布判定

当前 head 的本地认证恢复已完成，收据为 `artifacts/backup-restore-smoke-authenticated/20260729T102744Z-790047/receipt.json`，SHA-256 为 `75c022e28152dc2e883ea01ed75b4d7cf6d60417d7e696df30ee58b904b99675`；加密 bundle manifest SHA-256 为 `f54b2a9c7f1c3800d4c5a9dbeda22a9fe372d83155426fdf8ea2904e69d822c1`。恢复实际验证 Secret key version 1/2、ACL/RLS、Worker-only dispatch、五桶逐对象 hash，以及 10 条错误或缺失密钥 fail-closed 路径；临时明文、恢复副本、容器、网络和卷均已清理。本证据仍不替代生产环境 key custodian 或独立 verifier。

只有下列条件同时满足，完整 ADVINSYS live staging 才能从 `BLOCKED_EXTERNAL` 改为 `ACCEPTED`：

- 人工批准的 Fact、内容、Style Profile/Corpus 和报告均具备可追溯版本。
- GSC、GA4、五类 Provider 和三个消费者 Surface 分别取得真实成功与失败样本。
- 每个消费者 Surface Release 独立满足 capture fidelity 门槛，并绑定同一 LokiProxy sticky session lease 的地域证明；AIO、AI Mode、Copilot 不得互相借用分母。
- 真实业务旅程能够从 UTM/trace 回溯到 Revenue 和 GEO 内容版本。
- Customer 只读取已批准且未失效的不可变投影。
- 当前数据库 head 的认证空环境恢复、质量、构建、Chromium 和独立复核全部通过。

## 8. 最终本地门禁

2026-07-29 在当前 `0118_rec_draft_materialize` head 完成以下最终验证：

| 门禁 | 结果 |
|---|---|
| Required non-live | `2614 passed, 0 failed, 0 skipped`；另有 143 项按 `integration/live/browser` 标记明确排除 |
| 关键 PostgreSQL 垂直路径 | Connector Core、Browser Capture、Attribution 各 1 条，合计 `3/3`；均在临时数据库升级至 head 后清理 |
| Stable OpenAPI | Internal/Customer 快照重新导出并校验，合同测试 `7/7` |
| 静态质量 | Ruff；MyPy 818 个 Python source；7 个 Web workspace typecheck；2,308 文件 Secret scan；architecture `42/42` |
| Chromium fixture | 外部运行异常与 Surface fail-closed 两项，`2/2` |
| 当前 staging 浏览器 | Admin 外部数据桌面/移动、Recommendation 草稿、已登录 Customer Portal 四项均通过；无控制台错误或横向溢出 |
| Customer 边界 | 使用已有 active Customer session 真实登录；ADVINSYS/V600 可见，已批准报告为 0，`in_review` canary 不可见 |
| Production build/runtime | 重建并原位替换 Internal API/Admin；`18000/13001` 端口不变，13 个核心服务运行，四个公开入口 readiness/HTTP 为 200 |
| 认证恢复 | 收据 `artifacts/backup-restore-smoke-authenticated/20260729T102744Z-790047/receipt.json`，验证 288 张表、118 个 migration checksum、五桶对象、历史 keyring、ACL/RLS 和错误密钥拒绝 |

浏览器截图保存在 `test-results/advinsys-live-20260729-final/`。这些截图和本地测试证明当前实现与数据边界可运行，但不替代第 5、6 节列出的真实外部数据或独立验收。
