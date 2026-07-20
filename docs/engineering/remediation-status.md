# 架构整改执行状态

更新时间：2026-07-19

状态只使用可复核证据，不使用单一总体完成率。`Verified=local` 不表示已部署到客户生产，也不表示真实外部渠道或付费模型已验证。

| 工作项 | Planned | Implemented | Verified | Deployed | 说明 |
|---|---|---|---|---|---|
| 整改前基线与隔离 worktree | satisfied | satisfied | local | unavailable | 基线 `267d970`，保护标签 `geo-pre-remediation-20260719`；实施未修改主工作树和既有运行栈 |
| 14 项 ACCEPTED 整改 | satisfied | satisfied | local | not_executed | 70 条 AC、68 个稳定测试 ID 已由机器注册表闭合 |
| CI 与 inline acceptance 真实性 | satisfied | satisfied | local | not_applicable | 缺环境、零收集、必需 skip 和跨 run 污染均 fail closed；报告明确 `inline_isolated` |
| egress 与运行真实性 | satisfied | satisfied | local_runtime | not_executed | 真实 readiness、heartbeat、队列卡滞、Compose health 和 preflight 已在一次性 Docker 环境验证 |
| Campaign、Prompt 与人工发布验证 | satisfied | satisfied | local_postgres_browser | not_executed | 精确 Campaign 祖先、Opportunity Release 绑定和人工 URL 验证闭环已通过 |
| Fact、Evidence 与 F-019 RAG | satisfied | satisfied | local_postgres_minio_browser | not_executed | Project Native 已选中；Fact/Chunk 当前性在 RAG、Question、Prompt、Simulation、Generation 与 Publication 最终执行点均 fail closed |
| 来源、统计、Customer 与导出 | satisfied | satisfied | local_postgres_browser | not_executed | v3 来源分层、冻结成员、Customer latest 和可复算 ZIP/JSON/CSV 已通过 |
| 旧版功能与数据兼容 | satisfied | satisfied | local_postgres_browser | not_executed | `0010→0026` populated 升级、7 类旧 Job、历史只读/重建路径和 16 条 Chromium 流程通过；仓库外旧 `/v1` 客户端需预迁移 |
| Alembic 数据基线 | satisfied | satisfied | local | not_executed | 单 head `0026_legacy_simulation`；空库 `0001→0026`、`0026→0025→0026`、旧数据与 parentless/replay Artifact 已验证 |
| 双 Web 与稳定 OpenAPI | satisfied | satisfied | local | not_executed | Admin/Customer 生产构建、16 条 Chromium 必需流程和 2 个 OpenAPI surface 通过 |
| 外部 staging smoke | satisfied | satisfied | contract_only | not_executed | 命令、双重 opt-in、Secret 脱敏及结果合同已测试；真实请求和付费模型调用待授权 |
| 客户生产部署 | satisfied | not_executed | not_executed | not_executed | 尚未配置或验证客户生产 OIDC、域名、TLS、Secret 和第三方发布现场 |

2026-07-15 的 `final-live-deepseek-20260715` 是本轮整改前基线证据，不能证明当前提交的外部 staging 可用性。当前本地完成证据见 [GEO ACCEPTED 整改验证记录](GEO-accepted-remediation-verification-record-2026-07-19.md)与[旧版功能兼容性复查报告](GEO-legacy-feature-parity-2026-07-19.md)。系统仍不能声称已经替客户完成第三方真实发布，或证明投放导致 AI 推荐变化。
