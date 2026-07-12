# `codex/auth-web` 执行计划

## 目标

实现设计方案 §20.8 与 §22.7 的 Admin/Customer Web 部分：

- 错入口兑换在 API 消费前就被拒绝；
- BFF 使用跨浏览器 -> BFF -> API 稳定的 Idempotency-Key；
- 响应或 303 丢失后可用同 recovery Cookie 恢复；
- 不使用 `ADMIN_ROLES` 或 flat roles 推导入口/项目权限；
- Admin/Customer 只读取 API 按 surface 投影的项目；
- raw token 不进 URL/localStorage/log/analytics；
- desktop/mobile 登录、多项目选择和错误恢复可用。

必须完整阅读且严格消费 `docs/worktree-plans/contracts/auth-v2-wire-contract.md`，不得在本分支改变后端语义。

## 文件所有权

可修改：

```text
apps/admin-web/app/_auth/contracts.ts
apps/admin-web/app/_auth/recovery.ts
apps/admin-web/app/_auth/InvitationLoginForm.tsx
apps/admin-web/app/_auth/SessionDeliveryConfirm.tsx
apps/admin-web/app/api/auth/redeem-prepare/route.ts
apps/admin-web/app/api/auth/login/route.ts
apps/admin-web/app/api/auth/session-confirm/route.ts
apps/admin-web/app/api/auth/logout/route.ts
apps/admin-web/app/login/page.tsx
apps/admin-web/app/projects/page.tsx
apps/admin-web/app/projects/[project_id]/page.tsx
apps/admin-web/app/runtime.ts
apps/admin-web/middleware.ts

apps/customer-web/app/_auth/contracts.ts
apps/customer-web/app/_auth/recovery.ts
apps/customer-web/app/_auth/InvitationLoginForm.tsx
apps/customer-web/app/_auth/SessionDeliveryConfirm.tsx
apps/customer-web/app/api/auth/redeem-prepare/route.ts
apps/customer-web/app/api/auth/login/route.ts
apps/customer-web/app/api/auth/session-confirm/route.ts
apps/customer-web/app/api/auth/logout/route.ts
apps/customer-web/app/page.tsx
apps/customer-web/app/runtime.ts
apps/customer-web/app/portal/[module]/page.tsx

tests/test_auth_web_contracts.py
scripts/run_auth_surface_session_e2e.py
```

尽量不修改 `package.json/package-lock.json`，使用 Node `crypto`/Web Crypto 实现 recovery Cookie。

禁止修改：

- `apps/api/**`、`packages/geno_core/**`、`infra/db/**`；
- `infra/docker-compose*.yml`、`Makefile`、总 Gate 脚本/测试；
- `tests/test_api_contracts.py`、`tests/test_core_contracts.py`、`tests/test_infra_contracts.py`；
- 冻结 wire contract、设计方案和其他 worktree plan。

## 1. Typed Contract

- 两个 app 的 `contracts.ts` 生成/表达完全相同的冻结 DTO/enums/error envelope。
- 测试比较两份 schema/contract hash，防止 Admin 和 Customer 各自演进。
- 不允许 `Record<string, unknown>` 或裸 `string` 代替关键 auth enum/DTO。
- 错误必须保留 `code/detail/correlation_id/recommended_surface`，不把全部失败压成一个字符串或 `null`。

## 2. Prepare 与 Recovery Cookie

- Admin 固定 `requested_surface=admin`，Customer 固定 `customer`。
- 第一次提交先调 BFF `redeem-prepare`，可先调上游只读 preflight，不得调 redeem。
- BFF 生成随机 Idempotency-Key，用 `GENO_AUTH_RECOVERY_COOKIE_SECRET` 对以下绑定数据做认证加密或 HMAC 完整性保护：

```text
key
requested_surface
token_fingerprint
request_hash
issued_at/expires_at
```

- Cookie 必须 `HttpOnly + Secure(production) + SameSite=Lax + Path=/ + Max-Age=600`。
- 没有合法 recovery Cookie 的 login/redeem 返回 `428 redeem_prepare_required`，且不调上游 mutation。
- 客户端只在 React 组件内存中保留原 invitation form body，prepare 成功后用原 body 重提。
- 刷新、断网重提和上游结果不确定时复用同一 key，不在每次 fetch 时新建。

## 3. Login BFF

- 删除 `ADMIN_ROLES`、`hasAdminRole` 和所有 top-level flat role 推导。
- redeem body/header 完全按冻结 contract，不传 `accepted_by`。
- surface mismatch 不转发任何上游 Cookie，只显示不携带 token 的推荐入口链接。
- 成功时完整转发所有上游 `Set-Cookie`，不重新生成/缩短 Session Cookie。
- 只允许 303 到固定 landing：Admin `/projects`，Customer `/`。忽略恶意 return URL。
- landing 通过 `SessionDeliveryConfirm`/BFF 使用新 Session 请求 `/v1/auth/me`，成功后清理 recovery Cookie。
- `/auth/me` 失败时不清理 recovery Cookie，允许 TTL 内重试。

## 4. Surface Project Projection

- Admin runtime/project list 总是调用 `/v1/projects/runtime?surface=admin`。
- Customer runtime/project list 总是调用 `/v1/projects/runtime?surface=customer`。
- UI 不接收全量 Session scopes 再自行过滤。
- 切换 Project 后 detail/mutation 仍通过 API 逐项目授权，隐藏按钮不代替后端 403。
- owner(A)+viewer(B)：Admin selector 只见 A，Customer selector 只见 B。
- 组件必须处理 0/1/N 项目、当前项目被 revoke、Session 失效和网络错误。

## 5. UX/安全细节

- raw invite token 不写 query、redirect URL、localStorage/sessionStorage、log、analytics 或 error text。
- mismatch 提示只说明正确门户，不泄露其他 membership/project。
- 重复点击期间固定按钮尺寸、disabled/loading 状态，不产生布局跳动。
- 错误和状态使用 `aria-live`，键盘和移动端可完成登录/选项目。
- 不在页面中增加解释系统内部架构、特性或快捷键的说明文案。

## 6. 测试

合同/类型：

- analyst Admin 登录成功，但命令受逐项目 capability 限制；
- viewer 在 Admin mismatch，原 Invitation 后续可 Customer 兑换；
- owner(A)+viewer(B) 的双 surface 投影；
- 无 recovery Cookie 时不调用上游 redeem；
- 上游响应/303 丢失后同 Cookie 重试使用同 key；
- 完整转发 Session/CSRF Cookie；
- 固定 landing，恶意 return URL 无效；
- raw token 不出现在 URL/log/storage/source artifact；
- Admin/Customer contract hash 相同；
- 错误 code/correlation ID 保留。

执行：

```bash
PYTHONPATH=packages/geno_core:apps/api \
  python3 -m unittest tests.test_auth_web_contracts

npm --prefix apps/admin-web run typecheck
npm --prefix apps/customer-web run typecheck
npm --prefix apps/admin-web run build
npm --prefix apps/customer-web run build

python3 scripts/run_auth_surface_session_e2e.py --contract-only
git diff --check
```

具备合并后 API 时，Playwright 覆盖 desktop/mobile、刷新、后退、多标签、重复提交、丢失重定向和项目切换。本分支若无后端实现，使用严格遵守 wire contract 的 mock server，不伪造 live pass。

## 提交与 Handoff

建议提交：

```text
fix(auth-web): validate invitation surface before redeem
feat(auth-web): add stable browser redemption recovery
test(auth-web): cover surface-scoped multi-project sessions
```

新增并提交 `docs/worktree-results/auth-web.md`，列出集成 session 需注入的 `GENO_AUTH_RECOVERY_COOKIE_SECRET`、OpenAPI/generated DTO 对账、后端错误映射、Playwright 启动命令和未执行 live 场景。

