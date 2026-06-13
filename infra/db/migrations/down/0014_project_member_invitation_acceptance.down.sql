DROP POLICY IF EXISTS project_member_invitations_runtime_project_isolation ON project_member_invitations;
CREATE POLICY project_member_invitations_runtime_project_isolation ON project_member_invitations
  USING (geno_runtime_can_access_project(project_id))
  WITH CHECK (geno_runtime_can_access_project(project_id));

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
  );

DROP FUNCTION IF EXISTS geno_runtime_can_accept_project_invitation(uuid);
DROP FUNCTION IF EXISTS geno_runtime_invitation_token_hash();
