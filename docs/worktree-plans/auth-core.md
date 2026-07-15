# `codex/auth-core` 执行计划

## 目标

实现设计方案 §19.6、§22.7 和 `CG-PROD-010` 的后端/数据库部分：

- 邀请 surface 在消费前由 API 原子校验；
- 同 key 重试返回同一 Session delivery，不 rotate/revoke；
- Session v2 保留同 tenant 完整直接 Member 与 tenant-role Grant scope；
- RLS 使用 Member/Grant 统一锚点，tenant admin 无显式 Project Member 也只能访问同 tenant 授权项目；
- Member/Invitation 的 tenant 关系由复合 FK 与 `NOT NULL` 保证；
- 实现可验证的 dirty upgrade、ciphertext erasure 和 fail-closed rollback。

必须完整阅读且严格遵守 `docs/worktree-plans/contracts/auth-v2-wire-contract.md`。

## 文件所有权

可修改：

```text
infra/db/migrations/up/0030_auth_session_scope_v2.sql
infra/db/migrations/down/0030_auth_session_scope_v2.down.sql
packages/geo_core/geo_core/auth.py                         # 新增
packages/geo_core/geo_core/auth_delivery.py                # 新增
packages/geo_core/geo_core/rbac.py
packages/geo_core/geo_core/models.py                       # 仅 auth/session DTO
packages/geo_core/geo_core/repository.py                   # 仅 Member/Invitation 持久化
packages/geo_core/geo_core/runtime_project_access_repository.py
packages/geo_core/geo_core/bootstrap.py                    # 仅 auth capability/scope
apps/api/geo_api/auth_contracts.py                          # 新增
apps/api/geo_api/auth_routes.py                             # 新增
apps/api/geo_api/auth_context.py
apps/api/geo_api/runtime_access_routes.py                   # 仅 surface project projection
apps/api/geo_api/main.py                                    # 仅 router 注册/删除旧重复 auth route
scripts/run_auth_session_v2_e2e.py                           # 新增
scripts/cleanup_auth_redemption_attempts.py                  # 按需新增
tests/test_auth_session_v2_contracts.py                      # 新增
tests/test_auth_redemption_repository.py                     # 新增
tests/test_auth_postgres_integration.py                      # 新增
tests/test_api_contracts.py                                 # 仅现有 auth 测试区
tests/test_core_contracts.py                                # 仅现有 auth/repository 测试区
```

禁止修改：

- `apps/admin-web/**`、`apps/customer-web/**`；
- `infra/docker-compose*.yml`、`Makefile`、总 Gate 脚本/测试；
- `0029` 及早于 `0030` 的 migration；
- Knowledge/Collection/object-store 实现；
- 冻结 wire contract、设计方案和其他 worktree plan。

## 1. `0030` Migration

按以下顺序实现，不得跳步：

1. 为 `projects(id, tenant_id)` 建 concurrent unique index 并 attach 为父 UNIQUE constraint。
2. `project_members` 增加 `tenant_id/status/updated_at`。
3. `project_member_invitations` 增加 `tenant_id/audience/allowed_surfaces/policy_version/accepted_by_attempt_id`。
4. 使用 maintenance scope 按 Project 回填 Member/Invitation tenant，隔离无父项/mismatch，做 count/hash 对账。
5. 添加 `(project_id, tenant_id) REFERENCES projects(id, tenant_id) NOT VALID` 和 `tenant_id IS NOT NULL NOT VALID` check，依次 `VALIDATE`，再 `SET NOT NULL`。
6. 大小写重复且同 role 的 Member 确定性合并；role 冲突写入人工队列并 fail closed，禁止自动提权。
7. pending Invitation 同 role/audience 只保留最新未过期项；冲突全 revoke 并要求重发。
8. 删除 viewer 全局 unique，建立 project-scoped case-insensitive Member 和 pending Invitation unique index。
9. 新建 `runtime_project_access_grants`，包含 tenant/project/actor/source/role/permission-version/status、复合 FK 和引用侧索引。
10. 新建 `auth_invitation_redemption_attempts`：

```text
invitation_id/requested_surface/idempotency_key_hash
request_hash/token_fingerprint/session_id/status/replay_count
delivery_ciphertext/delivery_key_id/delivery_nonce/delivery_expires_at
delivery_confirmed_at/secret_erased_at/created_at/updated_at
UNIQUE(invitation_id, requested_surface, idempotency_key_hash)
```

11. `runtime_sessions` 增加 `scope_version/authz_policy_version/tenant_roles/project_scopes/redemption_attempt_id`。
12. 无法可靠回填的 active v1 Session 直接 revoke，写入 `runtime_session_reauth_queue`。
13. 建立 `geo_rls_authz_owner NOLOGIN BYPASSRLS` 和窄 SECURITY DEFINER helper：fixed empty/safe `search_path`、schema-qualified table、无 dynamic SQL、撤销 PUBLIC execute，只授 app role。helper 只读 Member/Grant 与 transaction-local actor/tenant GUC，不读 `projects`。
14. project-owned RLS 收口为 active direct Member 或 active Grant + required permission。新表启用并 `FORCE RLS`。
15. tenant role/policy/Project lifecycle 变更与 Grant 物化/撤销必须同事务。

不使用 PostgreSQL 不支持的 `ADD CONSTRAINT IF NOT EXISTS`。历史 FK 使用 `NOT VALID -> VALIDATE`，所有 FK 建引用侧索引。

Down/rollback 采用 fail closed：不删除已收紧的 additive FK/NOT NULL/Grant/ledger。旧 binary 回滚时由 edge 禁用全 Auth/Member/Invitation mutation，rollback DB role 同时被撤销相关写权。

## 2. Auth 策略与持久化

- `auth.py` 冻结 `auth_surface_policy_v1`。analyst 可进 Admin，viewer 只能 Customer。
- Invitation 的有效 surface 是签发快照与当前 policy 的交集；policy 不得扩大旧邀请。
- `auth_delivery.py` 使用独立 `GEO_AUTH_DELIVERY_MASTER_KEY/GEO_AUTH_DELIVERY_KEY_ID` 做认证加密，密文冻结完整 serialized Set-Cookie、attributes 和绝对 expiry。
- 默认 recovery TTL 10 分钟、max replay 5；确认/到期后擦除 ciphertext，仅保留 hash-only audit metadata。
- key 轮换覆盖 TTL 内旧密文的解密窗口。

## 3. 原子 Redeem UoW

实现单一 repository/application transaction：

```text
BEGIN
  SET LOCAL invitation token context; clear actor/project/tenant
  SELECT invitation FOR UPDATE
  INSERT ON CONFLICT / SELECT attempt FOR UPDATE
  same successful attempt -> validate binding/TTL/confirmation -> replay
  new attempt -> validate token/pending/expiry/audience/surface/policy
  mismatch -> rollback, 409, zero side effects
  upsert project_member with invitation-accept RLS
  SET LOCAL actor/tenant, project=NULL
  read all direct memberships + active grants in tenant
  create scope-v2 session
  encrypt stable Session/CSRF delivery
  mark invitation accepted_by_attempt + audit
COMMIT ONCE
emit cookies after commit
```

所有 context 使用 `SET LOCAL`/`set_config(..., true)`。不允许 repository 子方法自行 commit。

同 token fingerprint + surface + key + request hash 的并发/重试锁定同一 attempt，返回同一 Session/Cookie，不 revoke/rotate。同 key 不同 payload 返回 `idempotency_key_reused`；新 key 不能再次消费已接受 Invitation。

`/v1/auth/me` 首次成功验证该 Session 后，原子确认 delivery 并擦除 ciphertext；不得撤销已 confirmed Session。

## 4. API 与授权

以独立 `auth_contracts.py/auth_routes.py` 实现冻结 routes/DTO，`main.py` 只保留 router 注册和必要 middleware bridge，删除旧重复 auth handler。

- preflight 只读、no-store、限速，不回显 raw token/member existence。
- redeem 必须 `requested_surface + Idempotency-Key`，禁止 `accepted_by`。
- Session v2 授权按请求 Project scope，flat roles/permissions 只兼容展示。
- `/projects/runtime?surface=` 按 portal capability 在 API 服务端投影。
- 当前 Session 只包含一个 tenant，跨 tenant 不静默合并。
- Membership/policy 收紧后撤销或原子刷新 active Session。
- `AUTH_WRITES_ENABLED=0` 时所有 Auth/Member/Invitation mutation 返回 `503 auth_writes_temporarily_disabled`。

## 5. 必测场景

- fresh migration、dirty duplicate/role conflict migration、rollback；
- 伪造 project/tenant mismatch 被复合 FK 拒绝；
- 真实 app role + FORCE RLS 正向、跨 project/tenant negative；
- tenant admin 无显式 Project Member 时通过 Grant 访问同 tenant；
- helper owner/body/ACL/search_path drift 检查；
- commit/rollback 后 pooled connection GUC 不泄漏；
- mismatch 零副作用，stale policy fail closed；
- concurrent redeem 只消费一次；Session 失败全事务 rollback；
- commit 后响应丢失、同 key 并发/乱序返回同 Session 和字节等价 Cookie；
- TTL/replay limit/confirmation/ciphertext erasure；
- owner(A)+viewer(B) 无 role bleed；
- 请求含 `accepted_by` 返回 422；
- 旧 binary + 新 schema 回滚时 edge/DB 双层禁写，不出现 NOT NULL 500 或 v1 Session。

## 6. 执行命令

```bash
export PYTHONPATH="$PWD/packages/geo_core:$PWD/apps/api:$PWD"

python3 -m pytest -q \
  tests/test_auth_session_v2_contracts.py \
  tests/test_auth_redemption_repository.py

python3 -m pytest -q tests/test_auth_postgres_integration.py

python3 -m unittest \
  tests.test_api_contracts \
  tests.test_core_contracts

python3 -m ruff check \
  packages/geo_core/geo_core/auth.py \
  packages/geo_core/geo_core/auth_delivery.py \
  packages/geo_core/geo_core/runtime_project_access_repository.py \
  apps/api/geo_api/auth_contracts.py \
  apps/api/geo_api/auth_routes.py

python3 -m compileall packages/geo_core/geo_core apps/api/geo_api scripts tests
python3 scripts/run_auth_session_v2_e2e.py
git diff --check
```

真实 PostgreSQL integration 必须用新数据库/专用 Compose project，不清理其他 worktree 的 volume。

## 提交与 Handoff

建议提交：

```text
feat(auth): add tenant-scoped session v2 schema
feat(auth): make invitation redemption atomic and replayable
test(auth): cover RLS migration and response-loss recovery
```

新增并提交 `docs/worktree-results/auth-core.md`，列出集成 session 需加入 Compose 的 Auth key/TTL/replay/rollback env、migration/Gate/cleanup job 接线和 OpenAPI 生成命令。
