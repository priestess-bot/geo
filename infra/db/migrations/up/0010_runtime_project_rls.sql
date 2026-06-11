DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'geno_runtime_app') THEN
    CREATE ROLE geno_runtime_app LOGIN PASSWORD 'geno_runtime_app';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION geno_runtime_rls_enabled()
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT lower(coalesce(current_setting('geno.runtime_project_access_control', true), '')) IN ('1', 'true', 'yes', 'on');
$$;

CREATE OR REPLACE FUNCTION geno_runtime_actor_id()
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT nullif(current_setting('geno.runtime_actor_id', true), '');
$$;

CREATE OR REPLACE FUNCTION geno_runtime_project_id()
RETURNS uuid
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  value text;
BEGIN
  value := nullif(current_setting('geno.runtime_project_id', true), '');
  IF value IS NULL THEN
    RETURN NULL;
  END IF;
  RETURN value::uuid;
EXCEPTION WHEN invalid_text_representation THEN
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION geno_runtime_can_access_project(row_project_id uuid)
RETURNS boolean
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  context_project_id uuid;
  actor_id text;
BEGIN
  IF NOT geno_runtime_rls_enabled() THEN
    RETURN true;
  END IF;
  IF row_project_id IS NULL THEN
    RETURN false;
  END IF;

  context_project_id := geno_runtime_project_id();
  IF context_project_id IS NOT NULL AND row_project_id <> context_project_id THEN
    RETURN false;
  END IF;

  actor_id := geno_runtime_actor_id();
  IF actor_id IS NULL THEN
    RETURN false;
  END IF;

  RETURN EXISTS (
    SELECT 1
    FROM project_members pm
    WHERE pm.project_id = row_project_id AND pm.user_id = actor_id
  );
END;
$$;

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE ROW LEVEL SECURITY;
CREATE POLICY projects_runtime_project_isolation ON projects
  USING (geno_runtime_can_access_project(id))
  WITH CHECK (NOT geno_runtime_rls_enabled() OR id = geno_runtime_project_id());

ALTER TABLE project_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_members FORCE ROW LEVEL SECURITY;
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

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'prompt_questions',
    'answer_runs',
    'source_graphs',
    'source_gaps',
    'competitor_benchmarks',
    'action_recommendations',
    'retest_schedules',
    'retest_comparisons',
    'api_browser_fidelity_checks',
    'localized_knowledge_facts',
    'knowledge_fact_embeddings',
    'content_drafts',
    'integration_connectors',
    'manual_distribution_records',
    'evidence_links',
    'runtime_saved_views',
    'project_brand_kits',
    'score_weight_configs',
    'human_review_records',
    'traceability_bundles',
    'visibility_score_snapshots',
    'collection_costs',
    'collection_run_summaries',
    'audit_events',
    'report_exports',
    'report_export_jobs',
    'brand_entities',
    'competitor_entities'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format(
      'CREATE POLICY %I ON %I USING (geno_runtime_can_access_project(project_id)) WITH CHECK (geno_runtime_can_access_project(project_id))',
      table_name || '_runtime_project_isolation',
      table_name
    );
  END LOOP;
END $$;

ALTER TABLE llm_call_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_call_logs FORCE ROW LEVEL SECURITY;
CREATE POLICY llm_call_logs_runtime_project_isolation ON llm_call_logs
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

ALTER TABLE raw_answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_answers FORCE ROW LEVEL SECURITY;
CREATE POLICY raw_answers_runtime_project_isolation ON raw_answers
  USING (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM answer_runs ar
      WHERE ar.id = answer_run_id AND geno_runtime_can_access_project(ar.project_id)
    )
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM answer_runs ar
      WHERE ar.id = answer_run_id AND geno_runtime_can_access_project(ar.project_id)
    )
  );

ALTER TABLE answer_citations ENABLE ROW LEVEL SECURITY;
ALTER TABLE answer_citations FORCE ROW LEVEL SECURITY;
CREATE POLICY answer_citations_runtime_project_isolation ON answer_citations
  USING (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM answer_runs ar
      WHERE ar.id = answer_run_id AND geno_runtime_can_access_project(ar.project_id)
    )
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM answer_runs ar
      WHERE ar.id = answer_run_id AND geno_runtime_can_access_project(ar.project_id)
    )
  );

ALTER TABLE evidence_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_assets FORCE ROW LEVEL SECURITY;
CREATE POLICY evidence_assets_runtime_project_isolation ON evidence_assets
  USING (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM answer_runs ar
      WHERE ar.id = answer_run_id AND geno_runtime_can_access_project(ar.project_id)
    )
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM answer_runs ar
      WHERE ar.id = answer_run_id AND geno_runtime_can_access_project(ar.project_id)
    )
  );

ALTER TABLE collector_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE collector_logs FORCE ROW LEVEL SECURITY;
CREATE POLICY collector_logs_runtime_project_isolation ON collector_logs
  USING (
    NOT geno_runtime_rls_enabled()
    OR answer_run_id IS NULL
    OR EXISTS (
      SELECT 1 FROM answer_runs ar
      WHERE ar.id = answer_run_id AND geno_runtime_can_access_project(ar.project_id)
    )
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR answer_run_id IS NULL
    OR EXISTS (
      SELECT 1 FROM answer_runs ar
      WHERE ar.id = answer_run_id AND geno_runtime_can_access_project(ar.project_id)
    )
  );

ALTER TABLE answer_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE answer_analyses FORCE ROW LEVEL SECURITY;
CREATE POLICY answer_analyses_runtime_project_isolation ON answer_analyses
  USING (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM answer_runs ar
      WHERE ar.id = answer_run_id AND geno_runtime_can_access_project(ar.project_id)
    )
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM answer_runs ar
      WHERE ar.id = answer_run_id AND geno_runtime_can_access_project(ar.project_id)
    )
  );

ALTER TABLE score_contributions ENABLE ROW LEVEL SECURITY;
ALTER TABLE score_contributions FORCE ROW LEVEL SECURITY;
CREATE POLICY score_contributions_runtime_project_isolation ON score_contributions
  USING (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM visibility_score_snapshots vs
      WHERE vs.id = score_snapshot_id AND geno_runtime_can_access_project(vs.project_id)
    )
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM visibility_score_snapshots vs
      WHERE vs.id = score_snapshot_id AND geno_runtime_can_access_project(vs.project_id)
    )
  );

ALTER TABLE score_snapshot_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE score_snapshot_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY score_snapshot_runs_runtime_project_isolation ON score_snapshot_runs
  USING (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM visibility_score_snapshots vs
      WHERE vs.id = score_snapshot_id AND geno_runtime_can_access_project(vs.project_id)
    )
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM visibility_score_snapshots vs
      WHERE vs.id = score_snapshot_id AND geno_runtime_can_access_project(vs.project_id)
    )
  );

ALTER TABLE source_graph_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_graph_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY source_graph_evidence_runtime_project_isolation ON source_graph_evidence
  USING (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM source_graphs sg
      WHERE sg.id = source_graph_id AND geno_runtime_can_access_project(sg.project_id)
    )
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM source_graphs sg
      WHERE sg.id = source_graph_id AND geno_runtime_can_access_project(sg.project_id)
    )
  );

ALTER TABLE report_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY report_evidence_runtime_project_isolation ON report_evidence
  USING (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM report_exports re
      WHERE re.id = report_export_id AND geno_runtime_can_access_project(re.project_id)
    )
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR EXISTS (
      SELECT 1 FROM report_exports re
      WHERE re.id = report_export_id AND geno_runtime_can_access_project(re.project_id)
    )
  );

ALTER TABLE entity_aliases ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_aliases FORCE ROW LEVEL SECURITY;
CREATE POLICY entity_aliases_runtime_project_isolation ON entity_aliases
  USING (
    NOT geno_runtime_rls_enabled()
    OR (
      entity_kind = 'brand'
      AND EXISTS (
        SELECT 1 FROM brand_entities be
        WHERE be.id = entity_id AND geno_runtime_can_access_project(be.project_id)
      )
    )
    OR (
      entity_kind = 'competitor'
      AND EXISTS (
        SELECT 1 FROM competitor_entities ce
        WHERE ce.id = entity_id AND geno_runtime_can_access_project(ce.project_id)
      )
    )
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR (
      entity_kind = 'brand'
      AND EXISTS (
        SELECT 1 FROM brand_entities be
        WHERE be.id = entity_id AND geno_runtime_can_access_project(be.project_id)
      )
    )
    OR (
      entity_kind = 'competitor'
      AND EXISTS (
        SELECT 1 FROM competitor_entities ce
        WHERE ce.id = entity_id AND geno_runtime_can_access_project(ce.project_id)
      )
    )
  );

GRANT USAGE ON SCHEMA public TO geno_runtime_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO geno_runtime_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO geno_runtime_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO geno_runtime_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO geno_runtime_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO geno_runtime_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO geno_runtime_app;
