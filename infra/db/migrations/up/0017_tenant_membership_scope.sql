CREATE TABLE IF NOT EXISTS tenant_members (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id text NOT NULL,
  role text NOT NULL,
  status text NOT NULL DEFAULT 'active',
  invited_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (role IN ('super_admin', 'tenant_admin', 'project_owner', 'analyst', 'reviewer', 'knowledge_architect', 'content_operator', 'client_viewer', 'owner', 'admin', 'viewer')),
  CHECK (status IN ('active', 'disabled'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_members_tenant_user
  ON tenant_members(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_tenant_members_user_status
  ON tenant_members(lower(user_id), status);
CREATE INDEX IF NOT EXISTS idx_projects_tenant_id
  ON projects(tenant_id);

ALTER TABLE tenant_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_members FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_members_runtime_tenant_isolation ON tenant_members;
CREATE POLICY tenant_members_runtime_tenant_isolation ON tenant_members
  USING (
    NOT geo_runtime_rls_enabled()
    OR user_id = nullif(current_setting('geo.runtime_actor_id', true), '')
    OR EXISTS (
      SELECT 1
      FROM tenant_members self_membership
      WHERE self_membership.tenant_id = tenant_members.tenant_id
        AND self_membership.user_id = nullif(current_setting('geo.runtime_actor_id', true), '')
        AND self_membership.status = 'active'
        AND self_membership.role IN ('super_admin', 'tenant_admin')
    )
  )
  WITH CHECK (
    NOT geo_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1
      FROM tenant_members self_membership
      WHERE self_membership.tenant_id = tenant_members.tenant_id
        AND self_membership.user_id = nullif(current_setting('geo.runtime_actor_id', true), '')
        AND self_membership.status = 'active'
        AND self_membership.role IN ('super_admin', 'tenant_admin')
    )
  );
