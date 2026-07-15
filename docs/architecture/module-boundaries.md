# 模块与依赖边界

## 当前稳定模块

| 模块 | 职责 | 主要位置 |
| --- | --- | --- |
| identity/access | OIDC、Customer Session、Invitation、成员、角色和项目范围 | `geo_core/access`、`geo_api/access_*`、`member_*` |
| catalog | Project、Entity、Market Profile、Evidence 治理 | `geo_core/catalog`、`geo_api/catalog_*` |
| monitoring | Protocol、Query、Observation、Metric、Report、Customer 投影 | `geo_core/monitoring`、`geo_api/monitoring_*`、`customer_geo_routes.py` |
| placements | Destination、Policy、Opportunity、Brief、Evidence Pack、Package、Review、Publication | `geo_core/placements`、`geo_api/placement_*` |
| prompts/model gateway | Skill/Release 编译、Bundle、DeepSeek gateway 与调用日志 | `geo_core/prompts`、`geo_core/model_gateway`、placements adapter |
| jobs | Durable Job、lease、heartbeat、fencing、retry/replay、outbox | `geo_core/jobs`、`geo_worker` |
| engineering | GitHub/CI/运行健康的独立内部读写切片 | `geo_core/engineering`、`geo_api/engineering_*` |

## 依赖规则

```text
Router -> Application Service -> Domain + Port <- Adapter
Worker -> Application Service/Worker Handler
CLI    -> Application Service
```

- Router 只做认证、DTO 校验、Application 调用和 presenter，不写 SQL、不调用模型、不决定状态机。
- Application Service 负责授权后的 use case、事务边界和跨对象不变量。
- Domain 是无框架规则，不导入 FastAPI、psycopg、HTTP client、对象存储 SDK 或环境变量。
- Repository 只持久化，不 commit、不调用网络、不决定流程。
- Unit of Work 是事务、RLS context、commit 和 rollback 的唯一所有者。
- Adapter 实现 PostgreSQL、MinIO、DeepSeek、URL verifier 等 Port。
- Customer Router 只能依赖 customer-safe read model，不复用内部响应 DTO。

认证先解析可信 OIDC 身份或哈希 Customer Session，再实时读取有效 membership。Session 不保存项目快照，因此新增/撤销权限在下一请求生效。每个 PostgreSQL 事务设置 actor、identity、tenant 和 project scope；Repository 不得覆盖这些上下文。

外部模型、HTTP 和 MinIO 调用不得发生在数据库锁或长事务中：

```text
冻结输入 + claim Job lease
-> commit/release lock
-> 外部调用
-> 新事务校验 lease/fencing/idempotency
-> 写结果 + Job 完成 + outbox
```

## 前端边界

- Admin Web 只调用 Internal API；Customer Web 只调用 Customer API。
- 浏览器不得直接持有数据库、MinIO 或 DeepSeek 凭据。
- Admin BFF 转发受信任 OIDC Bearer；Customer BFF 只转发 HttpOnly Customer Session Cookie。
- 页面按 Campaign、Observations、Destinations/Opportunities、Placement 四个业务工作区拆分；Server Action 不复制领域规则。
- UI 必须展示异步 queued/running/failed/blocked 状态和 request/job ID，不能把失败渲染成空成功态。

## 文件预算

- App factory 不超过 300 行；
- Router 不超过 400 行；
- 普通 Python/TypeScript 文件不超过 600 行；
- 测试文件不超过 800 行；
- 例外必须有 ADR、Owner 和拆分日期，不能以“暂时”长期豁免。

架构测试应阻止：旧 `geno` 包/路由、阶段名 URL、Customer 注册内部 Router、Domain 导入框架、Router 直接 SQL、生产默认 Secret 和超过预算的新文件。
