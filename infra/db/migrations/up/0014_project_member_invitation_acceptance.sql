CREATE OR REPLACE FUNCTION geo_runtime_invitation_token_hash()
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT nullif(current_setting('geo.runtime_invitation_token_hash', true), '');
$$;

CREATE OR REPLACE FUNCTION geo_runtime_can_accept_project_invitation(row_project_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT
    geo_runtime_rls_enabled()
    AND row_project_id IS NOT NULL
    AND geo_runtime_invitation_token_hash() IS NOT NULL
    AND EXISTS (
      SELECT 1
      FROM project_member_invitations pmi
      WHERE pmi.project_id = row_project_id
        AND pmi.status = 'pending'
        AND pmi.invite_token_hash = geo_runtime_invitation_token_hash()
        AND (pmi.expires_at IS NULL OR pmi.expires_at > now())
    );
$$;

DROP POLICY IF EXISTS project_member_invitations_runtime_project_isolation ON project_member_invitations;
CREATE POLICY project_member_invitations_runtime_project_isolation ON project_member_invitations
  USING (
    geo_runtime_can_access_project(project_id)
    OR (
      status = 'pending'
      AND invite_token_hash = geo_runtime_invitation_token_hash()
      AND (expires_at IS NULL OR expires_at > now())
    )
  )
  WITH CHECK (
    geo_runtime_can_access_project(project_id)
    OR (
      invite_token_hash = geo_runtime_invitation_token_hash()
      AND status IN ('pending', 'accepted')
    )
  );

DROP POLICY IF EXISTS project_members_runtime_project_isolation ON project_members;
CREATE POLICY project_members_runtime_project_isolation ON project_members
  USING (
    NOT geo_runtime_rls_enabled()
    OR (
      geo_runtime_project_id() IS NOT NULL
      AND project_id = geo_runtime_project_id()
    )
    OR (
      geo_runtime_project_id() IS NULL
      AND user_id = geo_runtime_actor_id()
    )
  )
  WITH CHECK (
    NOT geo_runtime_rls_enabled()
    OR (
      geo_runtime_project_id() IS NOT NULL
      AND project_id = geo_runtime_project_id()
    )
    OR geo_runtime_can_accept_project_invitation(project_id)
  );
