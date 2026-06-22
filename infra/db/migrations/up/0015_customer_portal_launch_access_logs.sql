CREATE OR REPLACE FUNCTION geno_runtime_portal_token_hash()
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT nullif(current_setting('geno.runtime_portal_token_hash', true), '');
$$;

CREATE TABLE IF NOT EXISTS customer_portal_tokens (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  invitation_id uuid REFERENCES project_member_invitations(id) ON DELETE SET NULL,
  member_user_id text NOT NULL,
  token_hash text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'active',
  issued_by text NOT NULL DEFAULT 'runtime-console',
  issued_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  revoked_at timestamptz,
  revoked_by text,
  revoke_reason text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('active', 'revoked'))
);

CREATE INDEX IF NOT EXISTS idx_customer_portal_tokens_project_id
  ON customer_portal_tokens(project_id);
CREATE INDEX IF NOT EXISTS idx_customer_portal_tokens_member_user_id
  ON customer_portal_tokens(lower(member_user_id));

CREATE UNIQUE INDEX IF NOT EXISTS idx_project_members_viewer_user_global_unique
  ON project_members(lower(user_id))
  WHERE role = 'viewer';

CREATE UNIQUE INDEX IF NOT EXISTS idx_project_member_invitations_viewer_email_global_unique
  ON project_member_invitations(lower(email))
  WHERE role = 'viewer' AND status IN ('pending', 'accepted');

CREATE TABLE IF NOT EXISTS project_launch_configs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  config_version text NOT NULL DEFAULT 'au_launch_config_v1',
  customer_email text NOT NULL,
  primary_domain text NOT NULL,
  competitor_domains jsonb NOT NULL DEFAULT '[]'::jsonb,
  locale text NOT NULL DEFAULT 'en-AU',
  country_code text NOT NULL DEFAULT 'AU',
  timezone text NOT NULL DEFAULT 'Australia/Sydney',
  collection_mode text NOT NULL DEFAULT 'fixture',
  schedule jsonb NOT NULL DEFAULT '{}'::jsonb,
  external_connectors jsonb NOT NULL DEFAULT '{}'::jsonb,
  scoring_profile text NOT NULL DEFAULT 'au_visibility_v1',
  status text NOT NULL DEFAULT 'draft',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL DEFAULT 'runtime-console',
  updated_by text NOT NULL DEFAULT 'runtime-console',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, config_version),
  CHECK (status IN ('draft', 'ready', 'active', 'paused'))
);

CREATE INDEX IF NOT EXISTS idx_project_launch_configs_project_id
  ON project_launch_configs(project_id);

CREATE TABLE IF NOT EXISTS runtime_http_access_logs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  request_id text NOT NULL,
  project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
  actor_id text,
  method text NOT NULL,
  path text NOT NULL,
  route text NOT NULL,
  query_hash text,
  request_headers_hash text,
  request_body_hash text,
  request_body_size integer NOT NULL DEFAULT 0,
  request_body_uri text,
  request_headers_uri text,
  response_headers_hash text,
  response_body_hash text,
  response_body_size integer NOT NULL DEFAULT 0,
  response_body_uri text,
  response_headers_uri text,
  status_code integer NOT NULL,
  duration_ms numeric(12,3) NOT NULL,
  client_host_hash text,
  user_agent_hash text,
  error_type text,
  capture_status text NOT NULL DEFAULT 'metadata_only',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_runtime_http_access_logs_request_id
  ON runtime_http_access_logs(request_id);
CREATE INDEX IF NOT EXISTS idx_runtime_http_access_logs_project_id_created_at
  ON runtime_http_access_logs(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runtime_http_access_logs_route_created_at
  ON runtime_http_access_logs(route, created_at DESC);

ALTER TABLE customer_portal_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_launch_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_http_access_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS customer_portal_tokens_runtime_project_isolation ON customer_portal_tokens;
CREATE POLICY customer_portal_tokens_runtime_project_isolation ON customer_portal_tokens
  USING (
    NOT geno_runtime_rls_enabled()
    OR geno_runtime_can_access_project(project_id)
    OR (
      status = 'active'
      AND token_hash = geno_runtime_portal_token_hash()
    )
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR geno_runtime_can_access_project(project_id)
    OR (
      status = 'active'
      AND token_hash = geno_runtime_portal_token_hash()
    )
  );

DROP POLICY IF EXISTS project_launch_configs_runtime_project_isolation ON project_launch_configs;
CREATE POLICY project_launch_configs_runtime_project_isolation ON project_launch_configs
  USING (
    NOT geno_runtime_rls_enabled()
    OR geno_runtime_can_access_project(project_id)
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR geno_runtime_can_access_project(project_id)
  );

DROP POLICY IF EXISTS runtime_http_access_logs_runtime_project_isolation ON runtime_http_access_logs;
CREATE POLICY runtime_http_access_logs_runtime_project_isolation ON runtime_http_access_logs
  USING (
    NOT geno_runtime_rls_enabled()
    OR project_id IS NULL
    OR geno_runtime_can_access_project(project_id)
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR project_id IS NULL
    OR geno_runtime_can_access_project(project_id)
  );
