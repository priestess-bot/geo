CREATE OR REPLACE FUNCTION geno_runtime_invitation_token_hash()
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT nullif(current_setting('geno.runtime_invitation_token_hash', true), '');
$$;

CREATE OR REPLACE FUNCTION geno_runtime_can_accept_project_invitation(row_project_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT
    geno_runtime_rls_enabled()
    AND row_project_id IS NOT NULL
    AND geno_runtime_invitation_token_hash() IS NOT NULL
    AND EXISTS (
      SELECT 1
      FROM project_member_invitations pmi
      WHERE pmi.project_id = row_project_id
        AND pmi.status = 'pending'
        AND pmi.invite_token_hash = geno_runtime_invitation_token_hash()
        AND (pmi.expires_at IS NULL OR pmi.expires_at > now())
    );
$$;

DROP POLICY IF EXISTS project_member_invitations_runtime_project_isolation ON project_member_invitations;
CREATE POLICY project_member_invitations_runtime_project_isolation ON project_member_invitations
  USING (
    geno_runtime_can_access_project(project_id)
    OR (
      status = 'pending'
      AND invite_token_hash = geno_runtime_invitation_token_hash()
      AND (expires_at IS NULL OR expires_at > now())
    )
  )
  WITH CHECK (
    geno_runtime_can_access_project(project_id)
    OR (
      invite_token_hash = geno_runtime_invitation_token_hash()
      AND status IN ('pending', 'accepted')
    )
  );

DROP POLICY IF EXISTS project_members_runtime_project_isolation ON project_members;
CREATE POLICY project_members_runtime_project_isolation ON project_members
  USING (
    NOT geno_runtime_rls_enabled()
    OR (
      geno_runtime_project_id() IS NOT NULL
      AND project_id = geno_runtime_project_id()
    )
    OR (
      geno_runtime_project_id() IS NULL
      AND user_id = geno_runtime_actor_id()
    )
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR (
      geno_runtime_project_id() IS NOT NULL
      AND project_id = geno_runtime_project_id()
    )
    OR geno_runtime_can_accept_project_invitation(project_id)
  );
