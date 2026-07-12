# Auth v2 冻结线上合同

本文件是 `codex/auth-core` 和 `codex/auth-web` 的共享真源。两个功能分支都只能消费，不得单方修改；需要变更时写入 handoff，由集成 session 决定。

## Routes

```http
POST /v1/auth/invitations/preflight
POST /v1/auth/invitations/redeem
GET  /v1/auth/me
POST /v1/auth/logout
GET  /v1/projects/runtime?surface=admin|customer
```

`preflight` 和 `redeem` 必须返回 `Cache-Control: no-store`。

## Enums

```text
InvitationSurface = admin | customer

InvitationSurfaceCompatibility =
  compatible | surface_mismatch | policy_stale | invalid

InvitationRedeemRecoveryStatus =
  created | replayed | confirmed | recovery_expired | replay_limit_exceeded

RuntimeSessionScopeVersion = runtime_session_scope_v2
```

## Preflight

Request body：

```json
{
  "invitation_id": "uuid",
  "invite_token": "secret",
  "requested_surface": "admin"
}
```

Response 只能包含安全字段：

```json
{
  "compatibility": "compatible",
  "requested_surface": "admin",
  "recommended_surface": "admin",
  "invitation_role": "analyst",
  "policy_version": "auth_surface_policy_v1",
  "correlation_id": "uuid"
}
```

preflight 是只读 UX 优化，不能创建 Member/Session/attempt，不能改 Invitation，不能设置 API Session Cookie。

## Redeem

Request body 与 preflight 相同，另外必须有：

```http
Idempotency-Key: <opaque-random-value>
```

禁止客户端传入 `accepted_by`。不再依赖客户端 `reason`，actor/reason 由服务端从邀请和 surface 推导。

成功响应返回 Session v2 摘要和 recovery status，并设置服务端签发的 Session/CSRF Cookie。同 invitation + surface + key + request hash 重试必须返回字节等价的同一 Cookie，不得 rotate/revoke。

surface mismatch 返回 `409`：

```json
{
  "code": "invitation_surface_mismatch",
  "detail": "This invitation cannot open the requested surface.",
  "recommended_surface": "customer",
  "invitation_consumed": false,
  "correlation_id": "uuid"
}
```

该响应不得有 `Set-Cookie`，不得有 Member/Session/accepted audit 副作用。

## Session v2

`RuntimeProjectSessionScope`：

```json
{
  "project_id": "uuid",
  "roles": ["project_owner"],
  "permissions": ["project.read", "project.update"],
  "portal_capabilities": ["portal.admin.access"],
  "scope_sources": ["direct_member"]
}
```

`scope_sources` 允许 `direct_member` 和 `tenant_role`。

`RuntimeSessionScopeV2`：

```json
{
  "scope_version": "runtime_session_scope_v2",
  "authz_policy_version": "auth_surface_policy_v1",
  "actor_id": "user@example.com",
  "tenant_id": "uuid",
  "tenant_roles": [],
  "project_scopes": [],
  "project_ids": []
}
```

`project_ids` 只是 `project_scopes[].project_id` 的兼容投影。所有授权必须读取请求项目对应的 scope，不得使用顶层 flat roles/permissions。

## Surface Policy v1

| Canonical role | Capability |
| --- | --- |
| `super_admin/tenant_admin` | `portal.admin.access` |
| `project_owner`（`owner/admin` alias） | `portal.admin.access` |
| `analyst/reviewer/knowledge_architect/content_operator` | `portal.admin.access` |
| `client_viewer`（`viewer` alias） | `portal.customer.access` |

analyst 可以进入 Admin，但命令仍受逐项目 permission 限制。viewer 从 Admin 兑换必须 mismatch 且不消费。

## Stable Errors

```text
invitation_invalid
invitation_surface_mismatch
invitation_policy_stale
idempotency_key_reused
invitation_already_consumed
redeem_recovery_expired
redeem_replay_limit_exceeded
redeem_prepare_required
auth_writes_temporarily_disabled
```

错误 envelope 至少包含 `code/detail/correlation_id`。只有 surface mismatch 可以返回 `recommended_surface`。

## Project Projection

```http
GET /v1/projects/runtime?surface=admin
GET /v1/projects/runtime?surface=customer
```

API 服务端按 `portal_capabilities` 投影：Admin 只返回 admin scope，Customer 只返回 customer scope。UI 不得先接收全量 scope 再自行过滤。detail/mutation 仍需逐项目 API/RLS 授权。

## Browser Recovery

1. 第一次提交先调 BFF prepare/preflight，生成随机 Idempotency-Key。
2. BFF 将 key、surface、token fingerprint 和 request hash 放入有完整性保护的 `Secure + HttpOnly + SameSite=Lax` 短时 recovery Cookie，TTL 为 10 分钟。
3. 没有 recovery Cookie 的 redeem 只返回 `428 redeem_prepare_required`，不调用上游 mutation。
4. 客户端只在组件内存中保留原表单 body，不写 URL/localStorage/analytics。
5. 成功后 BFF 完整转发上游所有 `Set-Cookie`，并只 303 到固定 allowlist landing。
6. landing 用新 Session 调用 `/v1/auth/me`。确认成功后 API 擦除 delivery ciphertext，BFF 清理 recovery Cookie。

