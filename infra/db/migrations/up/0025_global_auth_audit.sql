ALTER TABLE audit_events
  ALTER COLUMN project_id DROP NOT NULL;

DROP POLICY IF EXISTS audit_events_runtime_project_isolation ON audit_events;
CREATE POLICY audit_events_runtime_project_isolation ON audit_events
  USING (
    (project_id IS NOT NULL AND geo_runtime_can_access_project(project_id))
    OR (project_id IS NULL AND actor_id = geo_runtime_actor_id())
  )
  WITH CHECK (
    (project_id IS NOT NULL AND geo_runtime_can_access_project(project_id))
    OR (project_id IS NULL AND actor_id = geo_runtime_actor_id())
  );
