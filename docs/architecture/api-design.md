# API 设计

Internal 和 Customer API 都使用 `/v1`，但位于不同进程和 OpenAPI。路径不得包含 `runtime`、`p0a`、`p0b`、`fixture` 或硬编码市场阶段。

通用约定：

- 错误使用 `application/problem+json`。
- 所有响应携带 `X-Request-ID`。
- 创建长任务返回 `202`、`job_id`、`status` 和 `status_url`。
- 写请求要求 `Idempotency-Key`。
- 大型事件列表使用 cursor；普通管理列表使用 `{items,total,limit,offset}`。
- Customer API 不注册 engineering、dev-tools、成员管理、Secret 或内部审核端点。
- Dev Tools 仅在内部进程、功能开关、管理员和测试租户四项同时满足时注册。

当前稳定 Foundation 路径包括 `/v1/auth`、`/v1/projects`、`/v1/jobs`，Internal 额外提供 `/v1/engineering`。领域路由按纵向迁移进度接入；未接入时必须返回 503 Problem Details，不允许伪造数据。

Internal `/v1/auth/me` 默认验证 OIDC discovery/JWKS、issuer、audience、期限和
tenant claim。只有显式 `GEO_AUTH_MODE=development` 且非生产部署时，才接受
`X-GEO-Actor-ID` 与 `X-GEO-Tenant-ID`。Customer 只接受
`GEO_CUSTOMER_SESSION` HttpOnly Cookie 对应的服务端哈希 Session；Customer
项目列表使用不含内部 role/key 的独立 DTO。两个表面都通过当前 membership
获得完整项目集合，Job 查询只返回该集合内的数据。
