# 架构整改执行状态

更新时间：2026-07-15

状态只使用证据，不使用单一总体完成率。

| 工作项 | Planned | Implemented | Verified | Deployed | 说明 |
|---|---|---|---|---|---|
| 整改前基线与标签 | satisfied | satisfied | satisfied | unavailable | 已提交 GEO v3 基线并创建回退标签 |
| GEO 命名与工具链 | satisfied | satisfied | satisfied | local | 运行代码统一 GEO 命名，uv/pnpm/typecheck 和架构门禁通过 |
| 双 API Foundation | satisfied | satisfied | satisfied | local | Internal/Customer ASGI、路由与 OpenAPI 负向隔离已验证 |
| Alembic 数据基线 | satisfied | satisfied | satisfied | local | 空库 0001→0007、checksum、down/up 与复合 FK 约束通过 |
| Durable Job 统一 | satisfied | satisfied | satisfied | local | PostgreSQL Job/outbox/lease/replay 和运营任务集成测试通过 |
| Admin/Customer 收敛 | satisfied | satisfied | satisfied | local | 双 Web、邀请恢复、多项目 Session 与客户只读投影已验收 |
| 领域纵向迁移 | satisfied | satisfied | satisfied | local | 旧巨型运行路径已删除，架构文件大小与依赖边界门禁通过 |
| 独立生产 Compose | satisfied | satisfied | satisfied | pending | 开发栈实跑；生产 Compose/Secret 合同通过，尚未部署到客户生产主机 |
| 备份与恢复 | satisfied | satisfied | satisfied | local | PostgreSQL 全量隔离恢复及 MinIO 逐对象 SHA-256 实跑通过 |
| 全流程 DeepSeek 验收 | satisfied | satisfied | satisfied | local | `final-live-deepseek-20260715` 已真实调用并完成审批、投放状态与客户投影 |

代码和本地产品验收已闭合，可进入客户环境部署。仍不能声称已经替客户完成第三方真实发布、生产 OIDC/域名/TLS 配置，或证明投放导致 AI 推荐变化；这些是部署及运营阶段的外部责任，必须按全流程手册留证。
