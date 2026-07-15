DROP TABLE IF EXISTS access_audit_events CASCADE;
DROP TABLE IF EXISTS invitation_redemptions CASCADE;
DROP TABLE IF EXISTS project_invitations CASCADE;
ALTER TABLE customer_sessions
    DROP COLUMN IF EXISTS surface,
    DROP COLUMN IF EXISTS csrf_token_hash;
DROP FUNCTION IF EXISTS geo_reject_access_audit_change();
DROP FUNCTION IF EXISTS geo_current_invitation_token_hash();
