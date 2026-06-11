CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE market_profiles (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  market_code text NOT NULL UNIQUE,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE industry_profiles (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  market_code text NOT NULL,
  industry_code text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tenants (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  name text NOT NULL,
  slug text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE projects (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name text NOT NULL,
  market_code text NOT NULL,
  industry_code text NOT NULL,
  target_brand text NOT NULL,
  category text NOT NULL,
  prompt_version text NOT NULL,
  status text NOT NULL DEFAULT 'configured',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE project_members (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id text NOT NULL,
  role text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, user_id)
);

CREATE TABLE prompt_questions (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  market_code text NOT NULL,
  industry_code text NOT NULL,
  text text NOT NULL,
  intent_type text NOT NULL,
  city text NOT NULL,
  language text NOT NULL,
  target_brand text NOT NULL,
  competitors jsonb NOT NULL DEFAULT '[]'::jsonb,
  priority integer NOT NULL DEFAULT 0,
  intent_weight numeric(6,4) NOT NULL DEFAULT 1.0,
  prompt_version text NOT NULL,
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geo_samples (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  market_code text NOT NULL,
  city text NOT NULL,
  language text NOT NULL,
  device text NOT NULL,
  geo_provider text NOT NULL,
  geo_params jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE answer_runs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  prompt_question_id uuid NOT NULL,
  platform text NOT NULL,
  surface text NOT NULL,
  access_method text NOT NULL,
  market_code text NOT NULL,
  city text NOT NULL,
  language text NOT NULL,
  device text NOT NULL,
  answer_present boolean NOT NULL,
  surface_triggered boolean NOT NULL,
  sample_index integer NOT NULL,
  sample_size integer NOT NULL,
  model_or_surface text,
  account_state text,
  collector_backend_id text NOT NULL,
  collector_version text NOT NULL,
  collected_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'completed'
);

CREATE TABLE raw_answers (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  answer_run_id uuid NOT NULL REFERENCES answer_runs(id) ON DELETE CASCADE,
  answer_text text NOT NULL,
  raw_payload jsonb NOT NULL,
  raw_payload_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE answer_citations (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  answer_run_id uuid NOT NULL REFERENCES answer_runs(id) ON DELETE CASCADE,
  url text NOT NULL,
  domain text NOT NULL,
  position integer NOT NULL,
  source_type text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence_assets (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  answer_run_id uuid NOT NULL REFERENCES answer_runs(id) ON DELETE CASCADE,
  asset_type text NOT NULL,
  url text NOT NULL,
  content_hash text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE collector_logs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  answer_run_id uuid REFERENCES answer_runs(id) ON DELETE SET NULL,
  collector_backend_id text NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE answer_analyses (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  answer_run_id uuid NOT NULL REFERENCES answer_runs(id) ON DELETE CASCADE,
  parser_engine_id text NOT NULL,
  analysis_version text NOT NULL,
  payload jsonb NOT NULL,
  confidence numeric(6,4) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE llm_call_logs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid,
  answer_run_id uuid REFERENCES answer_runs(id) ON DELETE SET NULL,
  purpose text NOT NULL,
  provider text NOT NULL,
  model text NOT NULL,
  prompt_version text NOT NULL,
  request_hash text NOT NULL,
  response_hash text,
  prompt_tokens integer NOT NULL DEFAULT 0,
  completion_tokens integer NOT NULL DEFAULT 0,
  total_tokens integer NOT NULL DEFAULT 0,
  estimated_cost numeric(12,6) NOT NULL DEFAULT 0,
  latency_ms integer NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'succeeded',
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE source_graphs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  source_url text NOT NULL,
  source_domain text NOT NULL,
  source_type text NOT NULL,
  topic text,
  source_gap_type text,
  answer_run_ids uuid[] NOT NULL DEFAULT '{}',
  citation_count integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE source_gaps (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  source_type text NOT NULL,
  gap_type text NOT NULL,
  observed_count integer NOT NULL DEFAULT 0,
  expected_weight numeric(8,4) NOT NULL,
  recommendation text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, source_type, gap_type)
);

CREATE TABLE competitor_benchmarks (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  competitor_name text NOT NULL,
  metric_scope text NOT NULL,
  payload jsonb NOT NULL,
  answer_run_ids uuid[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE action_recommendations (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  title text NOT NULL,
  description text NOT NULL,
  priority text NOT NULL,
  status text NOT NULL DEFAULT 'open',
  owner_id text NOT NULL,
  source_gap_type text,
  evidence_answer_run_ids uuid[] NOT NULL DEFAULT '{}',
  related_source_types text[] NOT NULL DEFAULT '{}',
  next_check_date timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE retest_schedules (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  prompt_version text NOT NULL,
  sample_size integer NOT NULL,
  offsets_days integer[] NOT NULL,
  scheduled_dates timestamptz[] NOT NULL,
  answer_run_ids uuid[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE retest_comparisons (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  baseline_score numeric(8,4) NOT NULL,
  retest_score numeric(8,4) NOT NULL,
  score_delta numeric(8,4) NOT NULL,
  baseline_answer_run_ids uuid[] NOT NULL DEFAULT '{}',
  retest_answer_run_ids uuid[] NOT NULL DEFAULT '{}',
  trend text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE api_browser_fidelity_checks (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  report_export_id uuid,
  status text NOT NULL,
  official_api_records integer NOT NULL DEFAULT 0,
  browser_records integer NOT NULL DEFAULT 0,
  comparable_prompt_city_pairs integer NOT NULL DEFAULT 0,
  mismatch_count integer NOT NULL DEFAULT 0,
  difference_rate numeric(8,4),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  payload_hash text NOT NULL,
  answer_run_ids uuid[] NOT NULL DEFAULT '{}',
  checked_by text NOT NULL,
  checked_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE localized_knowledge_facts (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  market_code text NOT NULL,
  fact_type text NOT NULL,
  subject text NOT NULL,
  predicate text NOT NULL,
  object_value text NOT NULL,
  city text,
  evidence_source_id uuid,
  confidence numeric(6,4) NOT NULL,
  status text NOT NULL DEFAULT 'active',
  valid_from timestamptz NOT NULL,
  valid_until timestamptz
);

CREATE TABLE knowledge_fact_embeddings (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  knowledge_fact_id uuid NOT NULL REFERENCES localized_knowledge_facts(id) ON DELETE CASCADE,
  embedding_model text NOT NULL,
  embedding vector(8) NOT NULL,
  content_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(knowledge_fact_id, embedding_model)
);

CREATE TABLE content_drafts (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  title text NOT NULL,
  content_type text NOT NULL,
  content_template_id text NOT NULL,
  target_question_ids uuid[] NOT NULL DEFAULT '{}',
  target_city text NOT NULL,
  target_platform text NOT NULL,
  target_source_type text NOT NULL,
  used_knowledge_fact_ids uuid[] NOT NULL DEFAULT '{}',
  source_gap_types text[] NOT NULL DEFAULT '{}',
  source_action_id uuid,
  evidence_answer_run_ids uuid[] NOT NULL DEFAULT '{}',
  draft_markdown text NOT NULL,
  review_status text NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE integration_connectors (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  provider text NOT NULL,
  connection_status text NOT NULL,
  capabilities text[] NOT NULL DEFAULT '{}',
  auth_mode text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE manual_distribution_records (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  content_draft_id uuid NOT NULL,
  platform text NOT NULL,
  target_url text NOT NULL,
  status text NOT NULL,
  submitted_at timestamptz,
  checked_at timestamptz,
  notes text NOT NULL DEFAULT ''
);

CREATE TABLE evidence_links (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  source_type text NOT NULL,
  source_id uuid NOT NULL,
  target_type text NOT NULL,
  target_id uuid NOT NULL,
  relation_type text NOT NULL,
  answer_run_ids uuid[] NOT NULL DEFAULT '{}'
);

CREATE TABLE runtime_saved_views (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  name text NOT NULL,
  view_type text NOT NULL,
  filters jsonb NOT NULL DEFAULT '{}'::jsonb,
  sort text NOT NULL DEFAULT 'collected_at_desc',
  query_path text NOT NULL,
  export_path text NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, name)
);

CREATE TABLE project_brand_kits (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  client_name text NOT NULL,
  prepared_by text NOT NULL,
  logo_url text,
  primary_color text,
  secondary_color text,
  footer_text text,
  updated_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id)
);

CREATE TABLE project_brand_assets (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  asset_type text NOT NULL,
  asset_url text NOT NULL,
  category text NOT NULL DEFAULT 'uncategorized',
  preview_url text,
  source_filename text,
  source_content_type text,
  content_hash text,
  storage_version text,
  status text NOT NULL DEFAULT 'active',
  scan_status text NOT NULL DEFAULT 'pending',
  scan_checked_at timestamptz,
  scan_method_version text,
  scan_notes text,
  uploaded_by text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, asset_url)
);

CREATE TABLE score_weight_configs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  formula_version text NOT NULL,
  weights jsonb NOT NULL,
  updated_by text NOT NULL,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, formula_version)
);

CREATE TABLE human_review_records (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  target_type text NOT NULL,
  target_id text NOT NULL,
  review_status text NOT NULL,
  decision text NOT NULL,
  reviewer_id text NOT NULL,
  notes text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runtime_alert_events (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  alert_id text NOT NULL,
  alert_type text NOT NULL,
  source text NOT NULL,
  source_id text NOT NULL,
  status text NOT NULL,
  updated_by text NOT NULL,
  note text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE traceability_bundles (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  subject_type text NOT NULL,
  subject_id uuid NOT NULL,
  report_export_ids uuid[] NOT NULL DEFAULT '{}',
  score_snapshot_ids uuid[] NOT NULL DEFAULT '{}',
  score_contribution_ids uuid[] NOT NULL DEFAULT '{}',
  answer_run_ids uuid[] NOT NULL DEFAULT '{}',
  raw_answer_ids uuid[] NOT NULL DEFAULT '{}',
  answer_citation_ids uuid[] NOT NULL DEFAULT '{}',
  evidence_asset_ids uuid[] NOT NULL DEFAULT '{}',
  source_graph_ids uuid[] NOT NULL DEFAULT '{}',
  source_gap_types text[] NOT NULL DEFAULT '{}',
  action_recommendation_ids uuid[] NOT NULL DEFAULT '{}',
  content_draft_ids uuid[] NOT NULL DEFAULT '{}',
  audit_event_ids uuid[] NOT NULL DEFAULT '{}',
  explanation_summary text NOT NULL
);

CREATE TABLE visibility_score_snapshots (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  scope_type text NOT NULL,
  scope_value text NOT NULL,
  formula_version text NOT NULL,
  platform_weights_snapshot jsonb NOT NULL,
  final_score numeric(8,4) NOT NULL,
  trigger_rate numeric(8,4) NOT NULL,
  mention_rate numeric(8,4) NOT NULL,
  recommendation_rate numeric(8,4) NOT NULL,
  answer_run_ids uuid[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  dispersion numeric(8,4) NOT NULL DEFAULT 0,
  component_weights_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE collection_costs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  answer_run_id uuid REFERENCES answer_runs(id) ON DELETE SET NULL,
  project_id uuid NOT NULL,
  collector_backend_id text NOT NULL,
  llm_provider text,
  llm_tokens integer NOT NULL DEFAULT 0,
  llm_cost numeric(12,6) NOT NULL DEFAULT 0,
  proxy_or_vendor_cost numeric(12,6) NOT NULL DEFAULT 0,
  compute_cost numeric(12,6) NOT NULL DEFAULT 0,
  total_cost numeric(12,6) NOT NULL DEFAULT 0,
  duration_ms integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_events (
  id uuid PRIMARY KEY,
  event_type text NOT NULL,
  project_id uuid NOT NULL,
  actor_type text NOT NULL,
  actor_id text NOT NULL,
  target_type text NOT NULL,
  target_id text NOT NULL,
  before_hash text,
  after_hash text,
  input_refs jsonb NOT NULL DEFAULT '{}'::jsonb,
  output_refs jsonb NOT NULL DEFAULT '{}'::jsonb,
  method_version text,
  reason text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE report_exports (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL,
  market_code text NOT NULL,
  report_version text NOT NULL,
  report_type text NOT NULL,
  score_snapshot_ids uuid[] NOT NULL,
  answer_run_ids uuid[] NOT NULL,
  prompt_version text NOT NULL,
  scoring_formula_version text NOT NULL,
  platform_weights_snapshot jsonb NOT NULL,
  sample_size integer NOT NULL,
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  methodology_hash text NOT NULL,
  markdown_url text,
  pdf_url text,
  csv_url text,
  exported_by text NOT NULL,
  exported_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, report_version)
);

CREATE TABLE report_export_jobs (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  report_export_id uuid REFERENCES report_exports(id) ON DELETE SET NULL,
  status text NOT NULL,
  artifact_type text NOT NULL,
  template text NOT NULL DEFAULT 'standard',
  filters jsonb NOT NULL DEFAULT '{}'::jsonb,
  sort text NOT NULL DEFAULT 'collected_at_desc',
  requested_by text NOT NULL,
  requested_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  completed_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  lease_expires_at timestamptz,
  next_attempt_at timestamptz,
  artifact_url text,
  error_message text,
  updated_by text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runtime_notifications (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  notification_type text NOT NULL,
  severity text NOT NULL DEFAULT 'info',
  title text NOT NULL,
  message text NOT NULL,
  target_type text NOT NULL,
  target_id text NOT NULL,
  recipient_role text NOT NULL DEFAULT 'project_member',
  status text NOT NULL DEFAULT 'unread',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  read_at timestamptz,
  updated_by text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runtime_notification_subscriptions (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  channel text NOT NULL DEFAULT 'webhook',
  endpoint_url text NOT NULL,
  event_types text[] NOT NULL DEFAULT ARRAY['report_export_job'],
  severity_threshold text NOT NULL DEFAULT 'info',
  status text NOT NULL DEFAULT 'active',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_by text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, channel, endpoint_url)
);

CREATE TABLE runtime_notification_deliveries (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  notification_id uuid NOT NULL REFERENCES runtime_notifications(id) ON DELETE CASCADE,
  subscription_id uuid NOT NULL REFERENCES runtime_notification_subscriptions(id) ON DELETE CASCADE,
  channel text NOT NULL DEFAULT 'webhook',
  endpoint_url text NOT NULL,
  status text NOT NULL DEFAULT 'queued',
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  lease_expires_at timestamptz,
  next_attempt_at timestamptz,
  response_status integer,
  response_body_hash text,
  error_message text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_by text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(notification_id, subscription_id)
);

CREATE TABLE score_contributions (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  score_snapshot_id uuid NOT NULL REFERENCES visibility_score_snapshots(id) ON DELETE CASCADE,
  component_name text NOT NULL,
  component_score numeric(8,4) NOT NULL,
  weight numeric(8,4) NOT NULL,
  weighted_contribution numeric(8,4) NOT NULL,
  denominator text NOT NULL,
  evidence_answer_run_ids uuid[] NOT NULL DEFAULT '{}',
  positive_evidence_summary text NOT NULL DEFAULT '',
  negative_evidence_summary text NOT NULL DEFAULT '',
  confidence_note text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE source_graph_evidence (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  source_graph_id uuid NOT NULL REFERENCES source_graphs(id) ON DELETE CASCADE,
  answer_run_id uuid NOT NULL REFERENCES answer_runs(id) ON DELETE CASCADE,
  answer_citation_id uuid REFERENCES answer_citations(id) ON DELETE SET NULL,
  relation_type text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE score_snapshot_runs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  score_snapshot_id uuid NOT NULL REFERENCES visibility_score_snapshots(id) ON DELETE CASCADE,
  answer_run_id uuid NOT NULL REFERENCES answer_runs(id) ON DELETE CASCADE,
  contribution_role text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE report_evidence (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  report_export_id uuid NOT NULL REFERENCES report_exports(id) ON DELETE CASCADE,
  answer_run_id uuid NOT NULL REFERENCES answer_runs(id) ON DELETE CASCADE,
  evidence_role text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE brand_entities (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  canonical_name text NOT NULL,
  official_domains jsonb NOT NULL DEFAULT '[]'::jsonb,
  parent_company text,
  product_lines jsonb NOT NULL DEFAULT '[]'::jsonb,
  status text NOT NULL DEFAULT 'active'
);

CREATE TABLE competitor_entities (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  canonical_name text NOT NULL,
  official_domains jsonb NOT NULL DEFAULT '[]'::jsonb,
  parent_company text,
  product_lines jsonb NOT NULL DEFAULT '[]'::jsonb,
  status text NOT NULL DEFAULT 'active'
);

CREATE TABLE entity_aliases (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  entity_id uuid NOT NULL,
  entity_kind text NOT NULL,
  alias text NOT NULL,
  alias_type text NOT NULL,
  confidence numeric(6,4) NOT NULL,
  confirmed_by text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_answer_runs_project ON answer_runs(project_id);
CREATE INDEX idx_answer_runs_prompt ON answer_runs(prompt_question_id);
CREATE INDEX idx_audit_events_project ON audit_events(project_id, created_at);
CREATE INDEX idx_report_exports_project ON report_exports(project_id, exported_at);
CREATE INDEX idx_projects_tenant ON projects(tenant_id);
CREATE INDEX idx_action_recommendations_project ON action_recommendations(project_id, status);
CREATE INDEX idx_localized_knowledge_facts_project ON localized_knowledge_facts(project_id, market_code, status);
CREATE INDEX idx_knowledge_fact_embeddings_project ON knowledge_fact_embeddings(project_id, embedding_model, updated_at);
CREATE INDEX idx_content_drafts_project ON content_drafts(project_id, review_status);
CREATE INDEX idx_evidence_links_project ON evidence_links(project_id, source_type, target_type);
CREATE INDEX idx_runtime_saved_views_project ON runtime_saved_views(project_id, view_type, updated_at);
CREATE INDEX idx_project_brand_kits_project ON project_brand_kits(project_id, updated_at);
CREATE INDEX idx_project_brand_assets_project ON project_brand_assets(project_id, asset_type, category, status, updated_at);
CREATE INDEX idx_score_weight_configs_project ON score_weight_configs(project_id, formula_version);
CREATE INDEX idx_human_review_records_project ON human_review_records(project_id, target_type, review_status, created_at);
CREATE INDEX idx_human_review_records_target ON human_review_records(target_type, target_id, created_at);
CREATE INDEX idx_runtime_alert_events_project ON runtime_alert_events(project_id, created_at DESC);
CREATE INDEX idx_runtime_alert_events_alert ON runtime_alert_events(alert_id, created_at DESC);
CREATE INDEX idx_api_browser_fidelity_checks_project ON api_browser_fidelity_checks(project_id, checked_at);
CREATE INDEX idx_api_browser_fidelity_checks_report ON api_browser_fidelity_checks(report_export_id, checked_at);
CREATE INDEX idx_traceability_bundles_project ON traceability_bundles(project_id, subject_type);
CREATE INDEX idx_report_export_jobs_project ON report_export_jobs(project_id, status, requested_at);
CREATE INDEX idx_report_export_jobs_claim ON report_export_jobs(status, next_attempt_at, lease_expires_at, requested_at);
CREATE INDEX idx_report_export_jobs_report ON report_export_jobs(report_export_id, requested_at);
CREATE INDEX idx_runtime_notifications_project ON runtime_notifications(project_id, status, severity, created_at);
CREATE INDEX idx_runtime_notifications_target ON runtime_notifications(target_type, target_id, created_at);
CREATE INDEX idx_runtime_notification_subscriptions_project ON runtime_notification_subscriptions(project_id, status, updated_at);
CREATE INDEX idx_runtime_notification_deliveries_project ON runtime_notification_deliveries(project_id, status, updated_at);
CREATE INDEX idx_runtime_notification_deliveries_claim ON runtime_notification_deliveries(status, next_attempt_at, lease_expires_at, created_at);
CREATE INDEX idx_runtime_notification_deliveries_notification ON runtime_notification_deliveries(notification_id, status, created_at);
