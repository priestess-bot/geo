# GEO 文档索引

本页是项目文档的唯一导航。遇到冲突时，按下列优先级判断当前合同：

1. Alembic schema、稳定 OpenAPI 和自动化测试；
2. `architecture/`、`adr/` 与 `operations/`；
3. [GEO v3 运行与验收合同](GEO-v3-%E5%85%A8%E6%B5%81%E7%A8%8B%E8%BF%90%E8%A1%8C%E6%89%8B%E5%86%8C.md)；
4. 带日期的进度报告、历史设计和 `runtime_preflight/` 证据。

旧文档可以解释决策过程，但不能定义当前 API、端口、模型、部署方式或验收结论。

## 从这里开始

| 读者 | 首先阅读 | 用途 |
| --- | --- | --- |
| 运营、审核、交付人员 | [GEO 全流程操作手册](operations/geo-full-flow-runbook.md) | 从启动到客户交付的逐步操作 |
| 产品负责人、验收人员 | [GEO v3 运行与验收合同](GEO-v3-%E5%85%A8%E6%B5%81%E7%A8%8B%E8%BF%90%E8%A1%8C%E6%89%8B%E5%86%8C.md) | 产品边界、状态机和最终通过条件 |
| 开发人员 | [系统总览](architecture/system-overview.md) | 部署单元、业务主链和依赖边界 |
| 运维人员 | [生产部署](operations/production-runbook.md) | Secret、首次 Owner、上线和回退 |
| 客户成功团队 | [全流程手册的客户交付章节](operations/geo-full-flow-runbook.md#十五复测报告与客户交付) | 邀请、只读范围和报告说明 |

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
- [GEO 全流程操作手册](operations/geo-full-flow-runbook.md)
- [生产部署](operations/production-runbook.md)
- [备份与恢复](operations/backup-restore.md)

## 开发与治理

- [代码质量与测试](development/code-quality.md)
- [Worktree 与合并规范](development/worktree-workflow.md)
- [架构整改方案](engineering/%E9%A1%B9%E7%9B%AE%E6%9E%B6%E6%9E%84%E4%B8%8E%E4%BB%A3%E7%A0%81%E6%B2%BB%E7%90%86%E6%95%B4%E6%94%B9%E6%96%B9%E6%A1%88-2026-07-15.md)
- [整改执行状态](engineering/remediation-status.md)

## 历史与运行证据

以下内容不属于当前真源：

- `GEO-文案生成系统设计方案v1_0.md`、`GEO-文案生成系统最终设计方案v2_0.md`：历史设计输入，已由 v3 合同和 ADR 取代。
- `GEO-Production-v1*`、`GEO-当前项目进度汇报-*`：特定日期的进度快照。
- `archive/`：旧命名、旧阶段、调研和历史交付资料。
- `approvals/`、`worktree-plans/`、`worktree-results/`：实施过程记录。
- `runtime_preflight/`：特定 commit、环境和时间的运行证据。除非重新按当前手册执行，否则不能证明当前版本已验收。

新的文档不得把 `geno`、`P0`、`AU fixture`、旧 `/runtime` API、同步模型调用或 `deepseek-chat` 写成当前架构。发现冲突时先修正当前手册，再把旧资料移入 `archive/`。
