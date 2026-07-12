-- Fail-closed rollback. The tightened tenant constraints, grants, attempt ledger,
-- and scope-v2 columns are intentionally retained.
UPDATE runtime_sessions
SET status = 'revoked',
    revoked_at = coalesce(revoked_at, now()),
    revoked_by = coalesce(revoked_by, '0030_auth_session_scope_v2_rollback'),
    revoke_reason = coalesce(revoke_reason, 'scope_v2_binary_rollback'),
    updated_at = now()
WHERE status = 'active'
  AND scope_version = 'runtime_session_scope_v2';

UPDATE auth_runtime_write_controls
SET writes_enabled = false,
    reason = 'scope_v2_binary_rollback_requires_forward_fix',
    updated_at = now()
WHERE singleton;

REVOKE INSERT, UPDATE, DELETE ON project_members FROM geno_runtime_rollback_app;
REVOKE INSERT, UPDATE, DELETE ON project_member_invitations FROM geno_runtime_rollback_app;
REVOKE INSERT, UPDATE, DELETE ON tenant_members FROM geno_runtime_rollback_app;
REVOKE INSERT, UPDATE, DELETE ON runtime_sessions FROM geno_runtime_rollback_app;
REVOKE INSERT, UPDATE, DELETE ON runtime_project_access_grants FROM geno_runtime_rollback_app;
REVOKE INSERT, UPDATE, DELETE ON auth_invitation_redemption_attempts FROM geno_runtime_rollback_app;
