CREATE TABLE IF NOT EXISTS project_member_invitations (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  email text NOT NULL,
  role text NOT NULL,
  status text NOT NULL DEFAULT 'pending',
  invite_token_hash text NOT NULL,
  invited_by text NOT NULL DEFAULT 'runtime-console',
  expires_at timestamptz,
  accepted_at timestamptz,
  revoked_at timestamptz,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, email, role, status)
);

CREATE INDEX IF NOT EXISTS idx_project_member_invitations_project_status
  ON project_member_invitations(project_id, status, email, created_at DESC);

ALTER TABLE project_member_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_member_invitations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS project_member_invitations_runtime_project_isolation ON project_member_invitations;
CREATE POLICY project_member_invitations_runtime_project_isolation ON project_member_invitations
  USING (geo_runtime_can_access_project(project_id))
  WITH CHECK (geo_runtime_can_access_project(project_id));
