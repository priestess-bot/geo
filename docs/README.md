# GEO 文档索引

本页是项目文档的唯一导航。遇到冲突时，按下列优先级判断当前合同：

1. Alembic schema、稳定 OpenAPI 和自动化测试；
2. `architecture/`、`adr/` 与 `operations/`；
3. [GEO v3 运行与验收合同](GEO-v3-%E5%85%A8%E6%B5%81%E7%A8%8B%E8%BF%90%E8%A1%8C%E6%89%8B%E5%86%8C.md)；
4. v1/v2 历史设计输入。

旧文档可以解释决策过程，但不能定义当前 API、端口、模型、部署方式或验收结论。

## 从这里开始

| 读者 | 首先阅读 | 用途 |
| --- | --- | --- |
| 运营、审核、交付及一线操作人员 | [ADVINSYS GEO 独立全流程操作手册](operations/geo-ui-operator-guide.md)（[PDF](operations/ADVINSYS-GEO-%E5%85%A8%E6%B5%81%E7%A8%8B%E9%83%A8%E7%BD%B2%E8%BF%90%E7%BB%B4%E6%89%8B%E5%86%8C.pdf)） | 部署、知识治理、生成、投放、监测、客户交付和异常恢复的唯一操作真源 |
| 产品负责人、验收人员 | [GEO v3 运行与验收合同](GEO-v3-%E5%85%A8%E6%B5%81%E7%A8%8B%E8%BF%90%E8%A1%8C%E6%89%8B%E5%86%8C.md) | 产品边界、状态机和最终通过条件 |
| 开发人员 | [系统总览](architecture/system-overview.md) | 部署单元、业务主链和依赖边界 |
| 运维人员 | [生产部署](operations/production-runbook.md) | Secret、首次 Owner、上线和回退 |
| 客户成功团队 | [独立手册的客户端全流程](operations/geo-ui-operator-guide.md#21-客户端全流程) | 邀请、只读范围、四视图和异常说明 |

## 当前架构

- [系统总览](architecture/system-overview.md)：产品目标、部署单元和业务主链。
- [模块与依赖边界](architecture/module-boundaries.md)：模块职责、允许依赖和文件预算。
- [数据模型与不变量](architecture/data-model.md)：项目隔离、不可变版本、审核和发布边界。
- [API 设计](architecture/api-design.md)：Internal/Customer surface、认证、错误和幂等约定。

## 当前决策记录

- [ADR-0001：模块化单体与双 API](adr/0001-modular-monolith-and-api-surfaces.md)
- [ADR-0002：PostgreSQL Durable Job](adr/0002-postgres-durable-jobs.md)
- [ADR-0003：Prompt 与流程解耦](adr/0003-prompt-release-boundary.md)

## 运行与交付

- [本地开发运行](operations/development-runbook.md)
- [ADVINSYS GEO 独立全流程操作手册](operations/geo-ui-operator-guide.md)（[PDF 版](operations/ADVINSYS-GEO-%E5%85%A8%E6%B5%81%E7%A8%8B%E9%83%A8%E7%BD%B2%E8%BF%90%E7%BB%B4%E6%89%8B%E5%86%8C.pdf)）
- [生产部署](operations/production-runbook.md)
- [备份与恢复](operations/backup-restore.md)

## 开发与治理

- [代码质量与测试](development/code-quality.md)
- [Worktree 与合并规范](development/worktree-workflow.md)
- [GEO ACCEPTED 整改统一实施计划](engineering/GEO-accepted-remediation-implementation-plan-2026-07-19.md)
- [F-019 RAG 选型 Gate 记录](engineering/F019-rag-selection-gate-2026-07-19.md)
- [真实渠道用户文案研究](engineering/channel-user-copy-research-2026-07-16.md)
- [Admin GEO 工作区可用性整改与功能保留基线](engineering/admin-geo-workspace-usability-remediation.md)
- [架构整改方案](engineering/%E9%A1%B9%E7%9B%AE%E6%9E%B6%E6%9E%84%E4%B8%8E%E4%BB%A3%E7%A0%81%E6%B2%BB%E7%90%86%E6%95%B4%E6%94%B9%E6%96%B9%E6%A1%88-2026-07-15.md)
- [整改执行状态](engineering/remediation-status.md)

## 历史设计与运行证据

以下内容不属于当前真源：

- [旧版 GEO 全流程操作手册](operations/geo-full-flow-runbook.md)

- `GEO-文案生成系统设计方案v1_0.md`、`GEO-文案生成系统最终设计方案v2_0.md`：仅保留为历史设计输入，已由 v3 合同和 ADR 取代。
- `operations/images/`：当前版本的脱敏浏览器截图；必须在全流程手册中登记 commit、运行 ID 和视口。
- `operations/evidence/`：当前版本的小型验收索引。大体积运行产物必须进入受控 artifact store。

新的文档不得把旧产品名、阶段代号、fixture 路由、旧 `/runtime` API、同步模型调用或过时模型别名写成当前架构。历史过程材料不再保存在产品仓库中。
