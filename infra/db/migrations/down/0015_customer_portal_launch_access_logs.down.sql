DROP POLICY IF EXISTS runtime_http_access_logs_runtime_project_isolation ON runtime_http_access_logs;
DROP POLICY IF EXISTS project_launch_configs_runtime_project_isolation ON project_launch_configs;
DROP POLICY IF EXISTS customer_portal_tokens_runtime_project_isolation ON customer_portal_tokens;

DROP TABLE IF EXISTS runtime_http_access_logs;
DROP TABLE IF EXISTS project_launch_configs;
DROP TABLE IF EXISTS customer_portal_tokens;

DROP INDEX IF EXISTS idx_project_member_invitations_viewer_email_global_unique;
DROP INDEX IF EXISTS idx_project_members_viewer_user_global_unique;

DROP FUNCTION IF EXISTS geo_runtime_portal_token_hash();
