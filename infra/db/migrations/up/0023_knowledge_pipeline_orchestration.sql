CREATE TABLE IF NOT EXISTS knowledge_pipeline_runs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  run_type text NOT NULL,
  status text NOT NULL DEFAULT 'draft',
  entry_source text NOT NULL DEFAULT 'mixed',
  market_code text NOT NULL DEFAULT 'GLOBAL',
  locale text NOT NULL DEFAULT 'en',
  city text,
  created_by text NOT NULL,
  started_at timestamptz,
  completed_at timestamptz,
  failed_step text,
  blocking_quality_gate text,
  waiting_review_stage_key text,
  waiting_review_count integer NOT NULL DEFAULT 0,
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (run_type IN ('full_ingestion', 'reparse', 'rechunk', 'reindex', 'fact_refresh', 'prompt_generation', 'content_generation', 'full_rebuild')),
  CHECK (status IN ('draft', 'ready', 'queued', 'running', 'waiting_human_review', 'succeeded', 'partial_succeeded', 'failed', 'cancelled')),
  CHECK (entry_source IN ('file', 'url', 'site', 'text', 'csv', 'mixed'))
);

CREATE TABLE IF NOT EXISTS knowledge_pipeline_stages (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  pipeline_run_id uuid NOT NULL REFERENCES knowledge_pipeline_runs(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  stage_key text NOT NULL,
  status text NOT NULL DEFAULT 'not_started',
  required boolean NOT NULL DEFAULT true,
  blocking boolean NOT NULL DEFAULT true,
  retry_count integer NOT NULL DEFAULT 0,
  error_code text,
  error_message text,
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (pipeline_run_id, stage_key),
  CHECK (stage_key IN (
    'source_precheck', 'asset_ingestion', 'crawl', 'parse', 'ocr', 'table_extract',
    'chunk', 'quality_summary', 'embedding', 'fact_extract', 'fact_review',
    'prompt_generate', 'prompt_review', 'content_generate', 'content_review',
    'trace_verify', 'publish_or_export'
  )),
  CHECK (status IN ('not_started', 'queued', 'running', 'succeeded', 'skipped', 'failed', 'retrying', 'blocked', 'waiting_review'))
);

CREATE TABLE IF NOT EXISTS knowledge_import_jobs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  source_mode text NOT NULL,
  status text NOT NULL DEFAULT 'draft',
  requested_by text NOT NULL,
  source_config jsonb NOT NULL DEFAULT '{}'::jsonb,
  result_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  locked_by text,
  locked_at timestamptz,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  next_run_at timestamptz NOT NULL DEFAULT now(),
  priority integer NOT NULL DEFAULT 0,
  last_error_code text,
  last_error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (source_mode IN ('file', 'url', 'url_batch', 'site_crawl', 'pasted_text', 'csv')),
  CHECK (status IN ('draft', 'ready', 'queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS crawl_jobs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  import_job_id uuid REFERENCES knowledge_import_jobs(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'queued',
  source_url text NOT NULL,
  normalized_url text,
  crawl_mode text NOT NULL DEFAULT 'single_url',
  max_pages integer NOT NULL DEFAULT 1,
  depth_limit integer NOT NULL DEFAULT 0,
  adapter_version text NOT NULL DEFAULT 'crawl4ai_adapter_v1',
  output_asset_ids uuid[] NOT NULL DEFAULT '{}',
  result_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  locked_by text,
  locked_at timestamptz,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  next_run_at timestamptz NOT NULL DEFAULT now(),
  priority integer NOT NULL DEFAULT 0,
  last_error_code text,
  last_error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (crawl_mode IN ('single_url', 'url_batch', 'sitemap', 'site_depth')),
  CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS knowledge_source_assets (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  import_job_id uuid REFERENCES knowledge_import_jobs(id) ON DELETE SET NULL,
  crawl_job_id uuid REFERENCES crawl_jobs(id) ON DELETE SET NULL,
  asset_type text NOT NULL,
  status text NOT NULL DEFAULT 'registered',
  source_uri text,
  object_uri text,
  title text NOT NULL DEFAULT '',
  content_type text,
  content_hash text NOT NULL DEFAULT '',
  byte_size bigint NOT NULL DEFAULT 0,
  market_code text NOT NULL DEFAULT 'GLOBAL',
  locale text NOT NULL DEFAULT 'en',
  city text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL DEFAULT 'runtime-console',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (asset_type IN ('uploaded_file', 'pasted_text', 'uploaded_csv', 'normalized_csv', 'crawled_html', 'crawled_markdown', 'screenshot', 'crawl_link_graph', 'parser_json', 'parser_markdown', 'parser_log', 'table_csv', 'table_html', 'quality_report')),
  CHECK (status IN ('registered', 'uploaded', 'prechecked', 'accepted', 'rejected', 'processing', 'processed', 'failed', 'disabled', 'archived'))
);

CREATE TABLE IF NOT EXISTS knowledge_parser_runs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  import_job_id uuid REFERENCES knowledge_import_jobs(id) ON DELETE SET NULL,
  source_asset_id uuid NOT NULL REFERENCES knowledge_source_assets(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'queued',
  adapter_engine text NOT NULL DEFAULT 'docling',
  adapter_version text NOT NULL DEFAULT 'geo-parser-adapter-v1',
  engine_version text NOT NULL DEFAULT 'unknown',
  fallback_from_engine text,
  parser_json_asset_id uuid,
  parser_markdown_asset_id uuid,
  block_count integer NOT NULL DEFAULT 0,
  table_count integer NOT NULL DEFAULT 0,
  ocr_span_count integer NOT NULL DEFAULT 0,
  page_count integer NOT NULL DEFAULT 0,
  quality_signals jsonb NOT NULL DEFAULT '[]'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  locked_by text,
  locked_at timestamptz,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  next_run_at timestamptz NOT NULL DEFAULT now(),
  priority integer NOT NULL DEFAULT 0,
  last_error_code text,
  last_error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('queued', 'running', 'succeeded', 'fallback_succeeded', 'partial_succeeded', 'failed', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS chunk_jobs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  import_job_id uuid REFERENCES knowledge_import_jobs(id) ON DELETE SET NULL,
  parser_run_id uuid REFERENCES knowledge_parser_runs(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'queued',
  chunk_profile_version text NOT NULL DEFAULT 'geo_chunk_profile_v1',
  cleaner_profile_version text NOT NULL DEFAULT 'geo_cleaner_v1',
  chunk_count integer NOT NULL DEFAULT 0,
  result_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  locked_by text,
  locked_at timestamptz,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  next_run_at timestamptz NOT NULL DEFAULT now(),
  priority integer NOT NULL DEFAULT 0,
  last_error_code text,
  last_error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS embedding_jobs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  chunk_job_id uuid REFERENCES chunk_jobs(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'queued',
  embedding_model text NOT NULL DEFAULT 'BAAI/bge-m3',
  embedding_model_version text NOT NULL DEFAULT 'bge-m3-local-v1',
  qdrant_collection text NOT NULL DEFAULT 'geo_knowledge_chunks_bge_m3_v1',
  embedded_count integer NOT NULL DEFAULT 0,
  failed_count integer NOT NULL DEFAULT 0,
  result_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  locked_by text,
  locked_at timestamptz,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  next_run_at timestamptz NOT NULL DEFAULT now(),
  priority integer NOT NULL DEFAULT 0,
  last_error_code text,
  last_error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS knowledge_blocks (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  source_asset_id uuid REFERENCES knowledge_source_assets(id) ON DELETE CASCADE,
  parser_run_id uuid REFERENCES knowledge_parser_runs(id) ON DELETE CASCADE,
  page_number integer,
  block_index integer NOT NULL DEFAULT 0,
  block_type text NOT NULL DEFAULT 'paragraph',
  text text NOT NULL DEFAULT '',
  bbox jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_tables (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  source_asset_id uuid REFERENCES knowledge_source_assets(id) ON DELETE CASCADE,
  parser_run_id uuid REFERENCES knowledge_parser_runs(id) ON DELETE CASCADE,
  page_number integer,
  table_index integer NOT NULL DEFAULT 0,
  caption text,
  table_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  csv_asset_id uuid,
  html_asset_id uuid,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_ocr_spans (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  source_asset_id uuid REFERENCES knowledge_source_assets(id) ON DELETE CASCADE,
  parser_run_id uuid REFERENCES knowledge_parser_runs(id) ON DELETE CASCADE,
  page_number integer,
  text text NOT NULL DEFAULT '',
  confidence numeric(8,4),
  bbox jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_page_snapshots (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  source_asset_id uuid REFERENCES knowledge_source_assets(id) ON DELETE CASCADE,
  parser_run_id uuid REFERENCES knowledge_parser_runs(id) ON DELETE CASCADE,
  page_number integer NOT NULL,
  image_asset_id uuid,
  text_preview text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  import_job_id uuid REFERENCES knowledge_import_jobs(id) ON DELETE SET NULL,
  source_asset_id uuid REFERENCES knowledge_source_assets(id) ON DELETE SET NULL,
  parser_run_id uuid REFERENCES knowledge_parser_runs(id) ON DELETE SET NULL,
  chunk_job_id uuid REFERENCES chunk_jobs(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'active',
  embedding_status text NOT NULL DEFAULT 'pending',
  chunk_type text NOT NULL DEFAULT 'text',
  chunk_index integer NOT NULL DEFAULT 0,
  text text NOT NULL,
  token_count integer NOT NULL DEFAULT 0,
  market_code text NOT NULL DEFAULT 'GLOBAL',
  locale text NOT NULL DEFAULT 'en',
  city text,
  content_hash text NOT NULL,
  chunk_version integer NOT NULL DEFAULT 1,
  qdrant_point_id text,
  source_block_ids uuid[] NOT NULL DEFAULT '{}',
  source_table_ids uuid[] NOT NULL DEFAULT '{}',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  superseded_by_chunk_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('active', 'disabled', 'archived', 'superseded')),
  CHECK (embedding_status IN ('pending', 'embedded', 'failed', 'disabled', 'stale'))
);

CREATE TABLE IF NOT EXISTS fact_extraction_jobs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  import_job_id uuid REFERENCES knowledge_import_jobs(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'queued',
  fact_kinds text[] NOT NULL DEFAULT '{}',
  chunk_filter jsonb NOT NULL DEFAULT '{}'::jsonb,
  model text NOT NULL DEFAULT 'deepseek-v4-flash',
  prompt_version text NOT NULL DEFAULT 'knowledge_fact_extraction_v1',
  max_facts integer NOT NULL DEFAULT 20,
  output_candidate_count integer NOT NULL DEFAULT 0,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  locked_by text,
  locked_at timestamptz,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  next_run_at timestamptz NOT NULL DEFAULT now(),
  priority integer NOT NULL DEFAULT 0,
  last_error_code text,
  last_error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS knowledge_fact_candidates (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  fact_extraction_job_id uuid REFERENCES fact_extraction_jobs(id) ON DELETE SET NULL,
  fact_kind text NOT NULL DEFAULT 'brand',
  fact_type text NOT NULL,
  subject text NOT NULL,
  predicate text NOT NULL,
  object_value text NOT NULL,
  market_code text NOT NULL DEFAULT 'GLOBAL',
  locale text NOT NULL DEFAULT 'en',
  city text,
  confidence numeric(8,4) NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'pending_review',
  source_chunk_ids uuid[] NOT NULL DEFAULT '{}',
  source_block_ids uuid[] NOT NULL DEFAULT '{}',
  source_asset_ids uuid[] NOT NULL DEFAULT '{}',
  reviewed_by text,
  reviewed_at timestamptz,
  merged_into_fact_id uuid,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('pending_review', 'approved', 'rejected', 'archived', 'forbidden', 'superseded', 'merged', 'needs_reextract'))
);

ALTER TABLE localized_knowledge_facts
  ADD COLUMN IF NOT EXISTS source_candidate_id uuid,
  ADD COLUMN IF NOT EXISTS fact_kind text NOT NULL DEFAULT 'brand',
  ADD COLUMN IF NOT EXISTS locale text NOT NULL DEFAULT 'en',
  ADD COLUMN IF NOT EXISTS source_chunk_ids uuid[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS source_block_ids uuid[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS source_asset_ids uuid[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS approved_by text,
  ADD COLUMN IF NOT EXISTS approved_at timestamptz,
  ADD COLUMN IF NOT EXISTS validity_start timestamptz,
  ADD COLUMN IF NOT EXISTS validity_end timestamptz,
  ADD COLUMN IF NOT EXISTS created_from_pipeline_run_id uuid,
  ADD COLUMN IF NOT EXISTS created_from_job_id uuid,
  ADD COLUMN IF NOT EXISTS fact_version integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS prompt_generation_templates (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  template_key text NOT NULL,
  template_version text NOT NULL DEFAULT 'v1',
  name text NOT NULL,
  template_body text NOT NULL,
  status text NOT NULL DEFAULT 'active',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL DEFAULT 'system',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (template_key, template_version),
  CHECK (status IN ('active', 'archived'))
);

CREATE TABLE IF NOT EXISTS prompt_generation_jobs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  template_id uuid REFERENCES prompt_generation_templates(id) ON DELETE SET NULL,
  template_version text NOT NULL DEFAULT 'v1',
  status text NOT NULL DEFAULT 'queued',
  target_platform text NOT NULL DEFAULT 'chatgpt',
  intent_type text,
  city text,
  source_fact_filter jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_chunk_filter jsonb NOT NULL DEFAULT '{}'::jsonb,
  requested_count integer NOT NULL DEFAULT 10,
  generated_count integer NOT NULL DEFAULT 0,
  model text NOT NULL DEFAULT 'deepseek-v4-flash',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  locked_by text,
  locked_at timestamptz,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  next_run_at timestamptz NOT NULL DEFAULT now(),
  priority integer NOT NULL DEFAULT 0,
  last_error_code text,
  last_error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'))
);

ALTER TABLE prompt_candidates
  ADD COLUMN IF NOT EXISTS pipeline_run_id uuid,
  ADD COLUMN IF NOT EXISTS prompt_generation_job_id uuid,
  ADD COLUMN IF NOT EXISTS source_chunk_ids uuid[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS risk_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS candidate_version integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS superseded_by_candidate_id uuid;

ALTER TABLE prompt_candidates
  DROP CONSTRAINT IF EXISTS prompt_candidates_review_status_check;
ALTER TABLE prompt_candidates
  ADD CONSTRAINT prompt_candidates_review_status_check
  CHECK (review_status IN ('pending_review', 'approved', 'rejected', 'edited_approved', 'imported', 'archived', 'superseded'));

CREATE TABLE IF NOT EXISTS content_generation_jobs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  content_type text NOT NULL DEFAULT 'faq',
  target_platform text NOT NULL DEFAULT 'chatgpt',
  target_city text,
  tone text NOT NULL DEFAULT 'clear',
  required_citations integer NOT NULL DEFAULT 1,
  forbidden_claims text[] NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'queued',
  model text NOT NULL DEFAULT 'deepseek-v4-flash',
  template_version text NOT NULL DEFAULT 'geo_content_draft_v1',
  generated_count integer NOT NULL DEFAULT 0,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  locked_by text,
  locked_at timestamptz,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  next_run_at timestamptz NOT NULL DEFAULT now(),
  priority integer NOT NULL DEFAULT 0,
  last_error_code text,
  last_error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'))
);

ALTER TABLE content_drafts
  ADD COLUMN IF NOT EXISTS pipeline_run_id uuid,
  ADD COLUMN IF NOT EXISTS content_generation_job_id uuid,
  ADD COLUMN IF NOT EXISTS source_chunk_ids uuid[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS citation_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'pending_human_review';

ALTER TABLE content_drafts
  DROP CONSTRAINT IF EXISTS content_drafts_status_check;
ALTER TABLE content_drafts
  ADD CONSTRAINT content_drafts_status_check
  CHECK (status IN ('pending_human_review', 'approved', 'rejected', 'needs_revision', 'published', 'exported', 'archived'));

CREATE TABLE IF NOT EXISTS knowledge_trace_refs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  source_type text NOT NULL,
  source_id text NOT NULL,
  target_type text NOT NULL,
  target_id text NOT NULL,
  trace_role text NOT NULL,
  confidence numeric(8,4),
  created_by_job_type text,
  created_by_job_id uuid,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (source_type IN ('crawl_job', 'source_asset', 'parser_run', 'block', 'table', 'ocr_span', 'chunk_job', 'chunk', 'embedding_job', 'fact_candidate', 'approved_fact', 'prompt_candidate', 'content_draft', 'quality_finding')),
  CHECK (target_type IN ('parser_run', 'table', 'ocr_span', 'page_snapshot', 'chunk', 'fact_candidate', 'approved_fact', 'prompt_generation_job', 'prompt_candidate', 'official_prompt', 'content_generation_job', 'content_draft', 'quality_finding', 'report', 'action_plan', 'retest')),
  CHECK (trace_role IN ('derived_from', 'supporting_evidence', 'citation', 'risk_source', 'prompt_input', 'content_input', 'quality_evidence'))
);

CREATE TABLE IF NOT EXISTS knowledge_quality_findings (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  target_type text NOT NULL,
  target_id text NOT NULL,
  finding_type text NOT NULL,
  severity text NOT NULL DEFAULT 'warning',
  status text NOT NULL DEFAULT 'open',
  message text NOT NULL,
  evidence_refs jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (target_type IN ('pipeline_run', 'pipeline_stage', 'import_job', 'crawl_job', 'asset', 'parser_run', 'block', 'table', 'ocr_span', 'page_snapshot', 'chunk_job', 'chunk', 'embedding_job', 'fact_extraction_job', 'fact_candidate', 'approved_fact', 'prompt_generation_job', 'prompt_candidate', 'content_generation_job', 'content_draft', 'quality_gate_run')),
  CHECK (severity IN ('info', 'warning', 'blocked', 'critical')),
  CHECK (status IN ('open', 'resolved', 'accepted_risk'))
);

CREATE TABLE IF NOT EXISTS knowledge_quality_gates (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  gate_key text NOT NULL UNIQUE,
  name text NOT NULL,
  gate_type text NOT NULL,
  blocking boolean NOT NULL DEFAULT true,
  config_version text NOT NULL DEFAULT 'v1',
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (gate_type IN ('pre_import_gate', 'parser_quality_gate', 'chunk_quality_gate', 'embedding_gate', 'fact_quality_gate', 'generation_quality_gate', 'traceability_gate', 'security_gate', 'publish_gate')),
  CHECK (status IN ('active', 'archived'))
);

CREATE TABLE IF NOT EXISTS knowledge_quality_gate_runs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pipeline_run_id uuid REFERENCES knowledge_pipeline_runs(id) ON DELETE SET NULL,
  pipeline_stage_id uuid REFERENCES knowledge_pipeline_stages(id) ON DELETE SET NULL,
  gate_id uuid REFERENCES knowledge_quality_gates(id) ON DELETE SET NULL,
  gate_key text NOT NULL,
  status text NOT NULL DEFAULT 'passed',
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  finding_ids uuid[] NOT NULL DEFAULT '{}',
  accepted_by text,
  accepted_at timestamptz,
  accepted_reason text,
  accepted_expires_at timestamptz,
  affected_gate_run_ids uuid[] NOT NULL DEFAULT '{}',
  affected_finding_ids uuid[] NOT NULL DEFAULT '{}',
  locked_by text,
  locked_at timestamptz,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  next_run_at timestamptz NOT NULL DEFAULT now(),
  priority integer NOT NULL DEFAULT 0,
  last_error_code text,
  last_error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('passed', 'warning', 'blocked', 'accepted_risk', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_knowledge_pipeline_runs_project_status
  ON knowledge_pipeline_runs(project_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_pipeline_stages_run
  ON knowledge_pipeline_stages(pipeline_run_id, stage_key);
CREATE INDEX IF NOT EXISTS idx_knowledge_import_jobs_queue
  ON knowledge_import_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_crawl_jobs_queue
  ON crawl_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_parser_runs_queue
  ON knowledge_parser_runs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_chunk_jobs_queue
  ON chunk_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_embedding_jobs_queue
  ON embedding_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_fact_extraction_jobs_queue
  ON fact_extraction_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_prompt_generation_jobs_queue
  ON prompt_generation_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_content_generation_jobs_queue
  ON content_generation_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_project_status
  ON knowledge_chunks(project_id, status, embedding_status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_trace_refs_target
  ON knowledge_trace_refs(project_id, target_type, target_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_trace_refs_unique_edge
  ON knowledge_trace_refs(project_id, source_type, source_id, target_type, target_id, trace_role);
CREATE INDEX IF NOT EXISTS idx_knowledge_quality_findings_project
  ON knowledge_quality_findings(project_id, status, severity, created_at DESC);

INSERT INTO knowledge_quality_gates (gate_key, name, gate_type, blocking, config)
VALUES
  ('pre_import_gate', '导入预检查', 'pre_import_gate', true, '{"max_file_mb": 50}'::jsonb),
  ('parser_quality_gate', '解析质量门禁', 'parser_quality_gate', true, '{"min_text_chars": 1}'::jsonb),
  ('chunk_quality_gate', 'Chunk 质量门禁', 'chunk_quality_gate', true, '{"min_active_chunks": 1}'::jsonb),
  ('embedding_gate', 'Embedding 门禁', 'embedding_gate', true, '{"min_success_ratio": 0.8}'::jsonb),
  ('fact_quality_gate', '事实质量门禁', 'fact_quality_gate', true, '{"min_candidate_count": 1}'::jsonb),
  ('generation_quality_gate', '生成质量门禁', 'generation_quality_gate', true, '{"trace_required": true}'::jsonb),
  ('traceability_gate', '证据追踪门禁', 'traceability_gate', true, '{"trace_required": true}'::jsonb),
  ('security_gate', '安全门禁', 'security_gate', true, '{"security_block_always_fails": true}'::jsonb),
  ('publish_gate', '发布门禁', 'publish_gate', true, '{"review_required": true}'::jsonb)
ON CONFLICT (gate_key) DO NOTHING;

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'knowledge_pipeline_runs',
    'knowledge_pipeline_stages',
    'knowledge_import_jobs',
    'crawl_jobs',
    'knowledge_source_assets',
    'knowledge_parser_runs',
    'chunk_jobs',
    'embedding_jobs',
    'knowledge_blocks',
    'knowledge_tables',
    'knowledge_ocr_spans',
    'knowledge_page_snapshots',
    'knowledge_chunks',
    'fact_extraction_jobs',
    'knowledge_fact_candidates',
    'prompt_generation_templates',
    'prompt_generation_jobs',
    'content_generation_jobs',
    'knowledge_trace_refs',
    'knowledge_quality_findings',
    'knowledge_quality_gates',
    'knowledge_quality_gate_runs'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
  END LOOP;
END $$;

DROP POLICY IF EXISTS knowledge_quality_gates_runtime_read ON knowledge_quality_gates;
CREATE POLICY knowledge_quality_gates_runtime_read ON knowledge_quality_gates
  USING (true)
  WITH CHECK (true);

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'knowledge_pipeline_runs',
    'knowledge_pipeline_stages',
    'knowledge_import_jobs',
    'crawl_jobs',
    'knowledge_source_assets',
    'knowledge_parser_runs',
    'chunk_jobs',
    'embedding_jobs',
    'knowledge_blocks',
    'knowledge_tables',
    'knowledge_ocr_spans',
    'knowledge_page_snapshots',
    'knowledge_chunks',
    'fact_extraction_jobs',
    'knowledge_fact_candidates',
    'prompt_generation_jobs',
    'content_generation_jobs',
    'knowledge_trace_refs',
    'knowledge_quality_findings',
    'knowledge_quality_gate_runs'
  ]
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I', table_name || '_runtime_project_isolation', table_name);
    EXECUTE format(
      'CREATE POLICY %I ON %I USING (geno_runtime_can_access_project(project_id)) WITH CHECK (geno_runtime_can_access_project(project_id))',
      table_name || '_runtime_project_isolation',
      table_name
    );
  END LOOP;
END $$;
