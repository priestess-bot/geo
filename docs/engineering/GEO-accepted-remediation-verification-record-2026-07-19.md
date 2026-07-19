# GEO ACCEPTED 整改验证记录

> 验证日期：2026-07-19
> 状态：`IMPLEMENTED_LOCAL_VERIFIED`
> 外部 staging smoke：`PENDING_AUTHORIZATION`
> 客户生产部署：`NOT_EXECUTED`
> 分支：`feat/geo-accepted-remediation-20260719`

## 1. 结论与边界

计划内 14 个 `ACCEPTED` 项均已实现；70 条验收标准映射到 68 个稳定测试 ID，并通过机器校验。最终验证覆盖 Domain、API、PostgreSQL、MinIO、双 Web、Chromium、OpenAPI、Compose 和一次性生产等价 Docker 环境。

代码审查后的加固也已闭合：URL 抓取固定到已校验公网 IP；Knowledge Worker 持续续租并统一取消、fencing、dead-letter 终态；Fact→Evidence 使用精确 Fact 身份和原文哈希；禁用/退役 Chunk 不再进入新 RAG、Question、Evidence Pack、Prompt、Simulation、Generation、Review、Export、Publication 或 Monitoring 执行。历史 Evidence、Pack、Package、Export 和核验记录继续保留用于审计，但不会被误当作当前可消费输入。

本记录只证明本地受控环境与生产等价拓扑验证完成。它不证明客户生产已部署、不证明第三方真实发布已发生，也不把 deterministic/synthetic/inline 结果解释为真实外部 GEO 效果或因果提升。

旧版功能、历史数据和在途任务的专项结论见 [GEO 旧版功能兼容性复查报告](GEO-legacy-feature-parity-2026-07-19.md)。仓库内同步升级结论为 PASS；仓库外旧 `/v1` 客户端仍需迁移新增的 Campaign 和治理合同，不能滚动混跑。

代码保护点：

- 整改前提交：`267d970`，标签 `geo-pre-remediation-20260719`。
- Batch 0：`f39beba`，标签 `geo-remediation-b0-20260719`。
- Batch 1：`670efa5`，标签 `geo-remediation-b1-20260719`。
- Batch 2-5 的集成结果由最终标签 `geo-remediation-complete-20260719` 标识；没有补造无独立提交的批次标签。
- 主工作树、开发栈和既有 staging 栈未用于迁移或验收。

## 2. 整改结果

| ID | AC | 实施结果 | 主要证据 |
|---|---:|---|---|
| F-001 | 4 | Internal API/Worker 独立 egress；数据服务和无 egress 后端保持隔离 | 本地真实 HTTP OIDC/JWKS、Knowledge、model、publication fixture；Docker 网络负向测试 |
| F-009 | 5 | 五类 capture method、v3 platform/surface/detail 强合同和来源隔离 | Domain/API/PostgreSQL/Customer/导出测试 |
| F-011 | 5 | 保留人工发布；追加式 URL 验证 attempt、8 项检查、显式重试和最小结果验证 | PostgreSQL Worker、API、Admin Chromium、真实 verifier 逻辑 |
| F-012 | 5 | Campaign 成为全链路真根；跨 Campaign read/mutation fail closed | PostgreSQL、API、Admin Chromium |
| F-013 | 5 | approved Fact 可通过 UI 提升 Evidence，保留 Source→Run→Document→Chunk→Fact 血缘 | PostgreSQL、API、Admin Chromium、0013/0022-0024 迁移 |
| F-014 | 5 | Opportunity 显式绑定 approved Prompt Release；历史 ID/version/hash 不变 | PostgreSQL、API、九渠道就绪度、Admin Chromium |
| F-015 | 4 | 必需测试缺环境、零收集、skip 或失败时非零退出；隔离跨 run 数据 | CI 合同、70 项必需 integration 摘要 |
| F-016 | 3 | acceptance 仅允许隔离数据库身份和 marker；报告标记 `inline_isolated` | 串行/并行 acceptance、报告验证器 |
| F-018 | 8 | 真实 readiness、heartbeat、队列卡滞、Compose health 和 bounded Secret preflight | 34 项静态合同、6 项一次性 Docker runtime |
| F-019 | 8 | Project Native RAG、治理图谱、QuestionSet、Protocol 绑定及不可发布内部仿真 | 选型 Gate、PostgreSQL/MinIO、100 项定向单测、Admin Chromium |
| F-021 | 5 | 最小 3 次、80% 有效门槛、精确分层、Wilson 区间、冻结成员和确定性 hash | Domain/PostgreSQL/API/Admin/Customer |
| F-023 | 4 | Customer 按 Project+Campaign+Protocol+window+stratum+cluster 读取明确 latest approved | PostgreSQL Customer projection、Customer Chromium |
| F-025 | 4 | 70 AC / 68 稳定 ID 的可执行注册表；关键行为不得只靠字符串断言 | traceability validator 与 4 项注册表测试 |
| F-027 | 5 | Durable Project/Campaign export；Admin 与 Customer 权限隔离；ZIP/JSON/CSV 可独立复算 | PostgreSQL/MinIO、API、双门户 Chromium |

## 3. 最终门禁

| 门禁 | 结果 |
|---|---|
| `make test-migrated` | 542 passed，73 deselected |
| `make quality` | Ruff 通过；Mypy 224 个源文件通过；6 个 Web workspace 类型检查通过；架构 13 passed |
| `make test-integration-required` | fresh PostgreSQL/MinIO，70 collected / 70 passed / 0 skipped |
| `make test-browser-chromium` | Admin 12/12、Customer 4/4；0 skipped、0 flaky |
| `make web-build` | Admin 与 Customer 两个 Next.js production build 通过 |
| `make openapi-contracts` | 2 个稳定 surface 验证通过；6 个快照测试通过 |
| `make test-infra-contracts` | 34 collected / 34 passed / 0 skipped |
| `make test-infra-runtime` | fresh Docker/PostgreSQL；6 collected / 6 passed / 0 skipped；故障状态可恢复 |
| `make f019-benchmark` | Dataset 有效；Project Native 选择清单及报告 hash 有效 |
| traceability validator | 70 条 acceptance clause、68 个稳定测试 ID 全部有效 |
| `geo-acceptance-inline` | run `legacy-parity-final-20260719`；`execution_mode=inline_isolated`；报告验证通过 |

验收报告保存在本地忽略目录 `artifacts/geo-acceptance/legacy-parity-final-20260719.json`，其 SHA-256 为 `b96a3de4532ecec82cb60423a969a6a610feed7cd2c924ea9ef3a5bc125a8a5c`。仓库只保存该脱敏索引，不提交数据库凭据或大体积运行产物。

## 4. 数据迁移

- Alembic 单 head：`0026_legacy_simulation`。
- 全新 PostgreSQL 已从 `0001` 顺序升级到 `0026`；另验证 populated `0010→0026` 和 `0026→0025→0026`。
- 单独验证 populated `UP→DOWN→UP`、目标唯一键冲突、Unicode 非精确哈希 fail closed、下游 lineage/JSON 引用保护。
- 0022 只修复可严格证明为旧 Python lowercase 行为生成的 ASCII 历史哈希；无法证明的历史值不被伪造为有效数据。
- 0023 允许已提升 Fact 仅做单向生命周期退役；0024 将 active Chunk 纳入 QuestionSet 当前性；0025 阻止新 Monitoring Protocol 绑定失效 QuestionSet。三者均保留历史记录，不把退役内容继续投影为当前输入。
- 0026 只允许精确 `legacy-v1` Prompt Simulation generation/artifact 血缘完成在途工作；parentless 根 Artifact、历史 replay 链和任意 null-Campaign 负例均已验证。
- App、Worker、Admin 使用独立数据库身份；最终 integration 和 acceptance 无残留测试项目。

## 5. F-019 选型

`project-native-rag-v1` 与 `llamaindex-property-graph-v1` 在同一冻结 corpus/gold set 上均取得 0.99，并通过 12/12 硬门槛。Project Native 被选中，LlamaIndex 保留为需重新生成选择清单才能启用的合格回退。

| 候选 | Token | 估算成本 | 墙钟时间 | 处置 |
|---|---:|---:|---:|---|
| Project Native | 45,606 | USD 0.01015448 | 270,218 ms | selected |
| LlamaIndex Property Graph | 84,235 | USD 0.01846698 | 384,035 ms | qualified fallback |

成本和耗时只记录、不设固定或相对上限；先满足事实质量、Project 隔离、人工审批和不可发布硬门槛，再比较复杂度与资源记录。

## 6. 未执行事项

以下事项没有被本轮证据覆盖：

- `make geo-staging-smoke` 的真实外部执行。命令要求 `GEO_RUN_STAGING_SMOKE=1` 和 `GEO_CONFIRM_STAGING_PAID_MODEL_CALL=1` 双重授权，本轮未获得授权，因此未发起网络请求或付费调用。
- 客户生产 OIDC/JWKS、域名、TLS、Secret、数据库和对象存储部署。
- 运营人员在第三方渠道完成真实人工发布。F-011 只实现 URL 契约和最小发布结果验证。
- 投放对 AI 推荐、业务转化或收入的因果证明。
- 下一阶段完整连接器、自动跨引擎采集、实验告警、业务归因和可解释建议平台。

因此当前分支可作为本地实现完成和进入受控 staging 的候选；只有取得授权并保存独立的 `staging_external` 证据后，才能声称外部 staging 已验证。
