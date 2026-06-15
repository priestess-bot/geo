DO $$
DECLARE
  policy_record record;
  table_name text;
BEGIN
  FOR policy_record IN
    SELECT schemaname, tablename, policyname
    FROM pg_policies
    WHERE schemaname = 'public'
      AND policyname LIKE '%_runtime_project_isolation'
  LOOP
    EXECUTE format(
      'DROP POLICY IF EXISTS %I ON %I.%I',
      policy_record.policyname,
      policy_record.schemaname,
      policy_record.tablename
    );
  END LOOP;

  FOREACH table_name IN ARRAY ARRAY[
    'projects',
    'project_members',
    'prompt_questions',
    'answer_runs',
    'raw_answers',
    'answer_citations',
    'evidence_assets',
    'collector_logs',
    'answer_analyses',
    'llm_call_logs',
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
    'project_brand_assets',
    'score_weight_configs',
    'human_review_records',
    'runtime_alert_events',
    'traceability_bundles',
    'visibility_score_snapshots',
    'collection_costs',
    'collection_run_summaries',
    'audit_events',
    'report_exports',
    'report_export_jobs',
    'runtime_notifications',
    'runtime_notification_subscriptions',
    'runtime_notification_deliveries',
    'runtime_notification_email_feedback_events',
    'runtime_notification_email_suppressions',
    'entity_alias_candidate_reviews',
    'score_contributions',
    'score_snapshot_runs',
    'source_graph_evidence',
    'report_evidence',
    'brand_entities',
    'competitor_entities',
    'entity_aliases'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', table_name);
  END LOOP;
END $$;

DROP FUNCTION IF EXISTS geno_runtime_can_access_project(uuid);
DROP FUNCTION IF EXISTS geno_runtime_project_id();
DROP FUNCTION IF EXISTS geno_runtime_actor_id();
DROP FUNCTION IF EXISTS geno_runtime_rls_enabled();

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM geno_runtime_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  REVOKE USAGE, SELECT ON SEQUENCES FROM geno_runtime_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  REVOKE EXECUTE ON FUNCTIONS FROM geno_runtime_app;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM geno_runtime_app;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM geno_runtime_app;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM geno_runtime_app;
REVOKE USAGE ON SCHEMA public FROM geno_runtime_app;

DROP ROLE IF EXISTS geno_runtime_app;
