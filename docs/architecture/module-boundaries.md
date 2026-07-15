# 模块与依赖边界

## 模块

| 模块 | 职责 |
|---|---|
| identity_access | OIDC、客户 Session、成员、角色和项目范围 |
| projects | 项目、品牌、商品、市场配置和集成 |
| monitoring | 消费者查询、采集计划、AI 回答和引用 |
| evidence | Source、Fact、Evidence Pack、权利与公开引用 |
| knowledge | 文档解析、Chunk、向量检索和事实治理 |
| insights | 可见度、图谱、差距、Action 和复测 |
| placements | Campaign、Opportunity、Brief、文案、审核和投放 |
| reporting | 报告、导出工件和交互溯源 |
| engineering | GitHub、CI、运行健康和四轴进度 |
| jobs | Durable Job、租约、Outbox、重试和取消 |

## 允许的依赖

```text
Router -> Application Service -> Domain + Port <- Adapter
Worker -> Application Service
CLI    -> Application Service
```

Domain 禁止导入 FastAPI、psycopg、httpx、对象存储 SDK或环境变量。Repository 只负责持久化，不能提交事务、调用网络、调用模型或决定工作流。Unit of Work 是事务、RLS 上下文、commit 和 rollback 的唯一所有者。

`identity_access` 的实现拆为 `models.py`、`ports.py`、`service.py` 和
`postgres.py`。认证先解析可信身份或哈希 Session，再读取当前有效 membership；
Session 不保存项目快照，因此用户新增或撤销项目权限会在下一次请求立即生效。
每个事务都设置 `geo.actor_id`、`geo.identity_id`、`geo.tenant_id`、
`geo.project_id` 和 `geo.project_ids`，Repository 不得自行覆盖或提交这些上下文。

外部模型、HTTP 和 MinIO 调用不得发生在数据库锁或长事务中。正确顺序是冻结输入并提交、执行外部调用、在新事务中校验 lease/fencing/idempotency、写入结果并完成任务。

## 文件预算

- App factory 不超过 300 行。
- Router 不超过 400 行。
- 普通 Python/TypeScript 文件不超过 600 行。
- 测试文件不超过 800 行。
- 例外必须有 ADR，不能以“暂时”作为长期理由。
