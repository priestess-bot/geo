DROP POLICY IF EXISTS project_scope ON project_memberships;
CREATE POLICY project_scope ON project_memberships
USING (
    identity_id = geo_current_identity_id()
    AND tenant_id = geo_current_tenant_id()
)
WITH CHECK (
    identity_id = geo_current_identity_id()
    AND tenant_id = geo_current_tenant_id()
);
DROP FUNCTION IF EXISTS geo_can_manage_project_memberships(uuid, uuid);

DROP TABLE IF EXISTS access_audit_events CASCADE;
DROP TABLE IF EXISTS membership_commands CASCADE;
DROP TABLE IF EXISTS invitation_redemptions CASCADE;
DROP TABLE IF EXISTS project_invitations CASCADE;
ALTER TABLE customer_sessions
    DROP COLUMN IF EXISTS surface,
    DROP COLUMN IF EXISTS csrf_token_hash;
DROP FUNCTION IF EXISTS geo_reject_access_audit_change();
DROP FUNCTION IF EXISTS geo_protect_bootstrap_audit_insert();
DROP FUNCTION IF EXISTS geo_current_invitation_token_hash();
