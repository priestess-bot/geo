DROP POLICY IF EXISTS project_member_invitations_runtime_project_isolation ON project_member_invitations;
CREATE POLICY project_member_invitations_runtime_project_isolation ON project_member_invitations
  USING (geo_runtime_can_access_project(project_id))
  WITH CHECK (geo_runtime_can_access_project(project_id));

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
  );

DROP FUNCTION IF EXISTS geo_runtime_can_accept_project_invitation(uuid);
DROP FUNCTION IF EXISTS geo_runtime_invitation_token_hash();
