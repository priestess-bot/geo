# GEO 文档索引

本文档目录是当前工程信息的唯一入口。根目录只保留启动导航；带日期的旧方案、旧阶段名和已经失效的交付说明必须放入 `archive/`，不能作为当前实现合同。

## 当前架构

- [系统总览](architecture/system-overview.md)
- [模块与依赖边界](architecture/module-boundaries.md)
- [数据模型与不变量](architecture/data-model.md)
- [API 设计](architecture/api-design.md)
- [整改执行状态](engineering/remediation-status.md)

## 开发

- [本地开发运行手册](operations/development-runbook.md)
- [代码质量与测试](development/code-quality.md)
- [Worktree 与合并规范](development/worktree-workflow.md)

## 运行与交付

- [GEO 全流程操作手册](operations/geo-full-flow-runbook.md)
- [生产部署](operations/production-runbook.md)
- [备份与恢复](operations/backup-restore.md)

## 决策记录

- [ADR-0001：模块化单体与双 API](adr/0001-modular-monolith-and-api-surfaces.md)
- [ADR-0002：PostgreSQL Durable Job](adr/0002-postgres-durable-jobs.md)
- [ADR-0003：Prompt 与流程解耦](adr/0003-prompt-release-boundary.md)

## 历史资料

`archive/` 只用于追溯，不参与当前命名、API、部署和验收门禁。`runtime_preflight/` 保存特定时间点的运行证据，不应被解释为当前版本已经通过验收。
