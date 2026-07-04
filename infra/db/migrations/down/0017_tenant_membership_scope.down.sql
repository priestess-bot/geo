DROP POLICY IF EXISTS tenant_members_runtime_tenant_isolation ON tenant_members;
DROP INDEX IF EXISTS idx_projects_tenant_id;
DROP INDEX IF EXISTS idx_tenant_members_user_status;
DROP INDEX IF EXISTS idx_tenant_members_tenant_user;
DROP TABLE IF EXISTS tenant_members;
