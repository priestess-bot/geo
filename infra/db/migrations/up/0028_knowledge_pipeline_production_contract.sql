-- Bring the persisted knowledge pipeline in line with the production contract.
-- This migration is additive except for enum checks, which are normalized first.

ALTER TABLE knowledge_import_jobs
  ADD COLUMN IF NOT EXISTS parser_strategy text NOT NULL DEFAULT 'auto',
  ADD COLUMN IF NOT EXISTS crawler_strategy text NOT NULL DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS market_code text NOT NULL DEFAULT 'GLOBAL',
  ADD COLUMN IF NOT EXISTS locale text NOT NULL DEFAULT 'en',
  ADD COLUMN IF NOT EXISTS city text,
  ADD COLUMN IF NOT EXISTS created_by text;

UPDATE knowledge_import_jobs
SET created_by = COALESCE(NULLIF(created_by, ''), requested_by, 'runtime-console');

ALTER TABLE knowledge_import_jobs
  ALTER COLUMN created_by SET DEFAULT 'runtime-console',
  ALTER COLUMN created_by SET NOT NULL,
  DROP CONSTRAINT IF EXISTS knowledge_import_jobs_parser_strategy_check,
  DROP CONSTRAINT IF EXISTS knowledge_import_jobs_crawler_strategy_check;
ALTER TABLE knowledge_import_jobs
  ADD CONSTRAINT knowledge_import_jobs_parser_strategy_check
    CHECK (parser_strategy IN ('auto', 'docling', 'mineru', 'unstructured', 'tika', 'markitdown')),
  ADD CONSTRAINT knowledge_import_jobs_crawler_strategy_check
    CHECK (crawler_strategy IN ('none', 'crawl4ai'));

ALTER TABLE knowledge_source_assets
  ADD COLUMN IF NOT EXISTS filename text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS parser_engine text,
  ADD COLUMN IF NOT EXISTS parser_version text,
  ADD COLUMN IF NOT EXISTS precheck_result jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS duplicate_of_asset_id uuid;

ALTER TABLE knowledge_source_assets
  DROP CONSTRAINT IF EXISTS knowledge_source_assets_asset_type_check;
ALTER TABLE knowledge_source_assets
  ADD CONSTRAINT knowledge_source_assets_asset_type_check
    CHECK (asset_type IN (
      'uploaded_file', 'pasted_text', 'uploaded_csv', 'normalized_csv',
      'crawled_html', 'crawled_markdown', 'screenshot', 'crawl_link_graph',
      'parser_json', 'parser_markdown', 'parser_log', 'ocr_debug_json',
      'table_csv', 'table_html', 'quality_report'
    ));

UPDATE knowledge_source_assets
SET filename = COALESCE(NULLIF(filename, ''), title, source_uri, 'knowledge-source');

ALTER TABLE knowledge_parser_runs
  ADD COLUMN IF NOT EXISTS quality_score numeric(8,4),
  ADD COLUMN IF NOT EXISTS config jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS output_asset_ids uuid[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS fallback_reason text;

ALTER TABLE chunk_jobs
  ADD COLUMN IF NOT EXISTS input_block_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS output_chunk_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS quality_finding_count integer NOT NULL DEFAULT 0;

UPDATE chunk_jobs SET output_chunk_count = chunk_count WHERE output_chunk_count = 0;

ALTER TABLE embedding_jobs
  ADD COLUMN IF NOT EXISTS requested_chunk_count integer NOT NULL DEFAULT 0;

ALTER TABLE knowledge_blocks
  ADD COLUMN IF NOT EXISTS section_path text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS html text,
  ADD COLUMN IF NOT EXISTS markdown text,
  ADD COLUMN IF NOT EXISTS reading_order integer,
  ADD COLUMN IF NOT EXISTS confidence numeric(8,4),
  ADD COLUMN IF NOT EXISTS content_hash text NOT NULL DEFAULT '';

UPDATE knowledge_blocks
SET content_hash = encode(sha256(convert_to(text, 'UTF8')), 'hex')
WHERE content_hash = '';

ALTER TABLE knowledge_ocr_spans
  ADD COLUMN IF NOT EXISTS language text,
  ADD COLUMN IF NOT EXISTS source_image_ref text,
  ADD COLUMN IF NOT EXISTS content_hash text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS quality_flags text[] NOT NULL DEFAULT '{}';

UPDATE knowledge_ocr_spans
SET content_hash = encode(sha256(convert_to(text, 'UTF8')), 'hex')
WHERE content_hash = '';

ALTER TABLE knowledge_page_snapshots
  ADD COLUMN IF NOT EXISTS snapshot_asset_id uuid,
  ADD COLUMN IF NOT EXISTS html_asset_id uuid,
  ADD COLUMN IF NOT EXISTS markdown_asset_id uuid,
  ADD COLUMN IF NOT EXISTS title text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS source_url text,
  ADD COLUMN IF NOT EXISTS status_code integer,
  ADD COLUMN IF NOT EXISTS content_hash text NOT NULL DEFAULT '';

ALTER TABLE knowledge_tables
  ADD COLUMN IF NOT EXISTS block_id uuid,
  ADD COLUMN IF NOT EXISTS row_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS column_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS markdown text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS confidence numeric(8,4),
  ADD COLUMN IF NOT EXISTS quality_flags text[] NOT NULL DEFAULT '{}';

ALTER TABLE knowledge_chunks
  ADD COLUMN IF NOT EXISTS section_path text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS quality_flags text[] NOT NULL DEFAULT '{}';

ALTER TABLE knowledge_fact_candidates
  ADD COLUMN IF NOT EXISTS extraction_model text NOT NULL DEFAULT 'deepseek-v4-flash',
  ADD COLUMN IF NOT EXISTS extraction_prompt_version text NOT NULL DEFAULT 'knowledge_fact_extraction_v1',
  ADD COLUMN IF NOT EXISTS review_notes text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS approved_fact_id uuid;

ALTER TABLE localized_knowledge_facts
  ADD COLUMN IF NOT EXISTS superseded_by_fact_id uuid;

ALTER TABLE prompt_candidates
  ADD COLUMN IF NOT EXISTS target_platform text NOT NULL DEFAULT 'chatgpt',
  ADD COLUMN IF NOT EXISTS prompt_template_id uuid,
  ADD COLUMN IF NOT EXISTS prompt_template_version text NOT NULL DEFAULT 'v1';

ALTER TABLE content_drafts
  ADD COLUMN IF NOT EXISTS summary text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS risk_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE content_generation_jobs
  ADD COLUMN IF NOT EXISTS target_audience text NOT NULL DEFAULT 'general customer',
  ADD COLUMN IF NOT EXISTS target_action jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE knowledge_trace_refs
  DROP CONSTRAINT IF EXISTS knowledge_trace_refs_source_type_check,
  DROP CONSTRAINT IF EXISTS knowledge_trace_refs_target_type_check;
ALTER TABLE knowledge_trace_refs
  ADD CONSTRAINT knowledge_trace_refs_source_type_check
    CHECK (source_type IN (
      'crawl_job', 'source_asset', 'parser_run', 'block', 'table', 'ocr_span',
      'chunk_job', 'chunk', 'embedding_job', 'fact_candidate', 'approved_fact',
      'prompt_candidate', 'content_draft', 'quality_finding', 'report', 'action_plan', 'retest'
    )),
  ADD CONSTRAINT knowledge_trace_refs_target_type_check
    CHECK (target_type IN (
      'parser_run', 'table', 'ocr_span', 'page_snapshot', 'chunk', 'fact_candidate',
      'approved_fact', 'prompt_generation_job', 'prompt_candidate', 'official_prompt',
      'content_generation_job', 'content_draft', 'quality_finding', 'report', 'action_plan', 'retest'
    ));

ALTER TABLE prompt_generation_templates
  ADD COLUMN IF NOT EXISTS description text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS system_prompt text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS user_prompt_template text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS input_variables jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS output_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS model_config jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS evaluation_set jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS approved_by text,
  ADD COLUMN IF NOT EXISTS published_at timestamptz;

-- Drop the legacy status constraint before converting active templates to the
-- published lifecycle. This keeps the migration safe to rerun after a partial
-- execution or against a database that already applied the old constraint.
ALTER TABLE prompt_generation_templates
  DROP CONSTRAINT IF EXISTS prompt_generation_templates_status_check;

UPDATE prompt_generation_templates
SET status = CASE WHEN status = 'active' THEN 'published' ELSE status END,
    system_prompt = CASE WHEN system_prompt = '' THEN template_body ELSE system_prompt END,
    user_prompt_template = CASE WHEN user_prompt_template = '' THEN template_body ELSE user_prompt_template END,
    published_at = CASE
      WHEN status = 'active' AND published_at IS NULL THEN COALESCE(updated_at, created_at, now())
      ELSE published_at
    END,
    approved_by = CASE WHEN status = 'active' THEN COALESCE(approved_by, created_by, 'system') ELSE approved_by END,
    input_variables = CASE WHEN input_variables = '[]'::jsonb
      THEN '["project","brand","competitors","market","approved_facts","active_chunks","existing_prompts"]'::jsonb
      ELSE input_variables END,
    output_schema = CASE WHEN output_schema = '{}'::jsonb
      THEN '{"prompt_candidates":[{"text":"string","intent_type":"string","city":"string|null","source_fact_ids":["uuid"],"source_chunk_ids":["uuid"],"rationale":"string","risk_flags":["string"]}]}'::jsonb
      ELSE output_schema END,
    model_config = CASE WHEN model_config = '{}'::jsonb
      THEN '{"model":"deepseek-v4-flash","response_format":"json_object","temperature":0.2}'::jsonb
      ELSE model_config END;

ALTER TABLE prompt_generation_templates
  ADD CONSTRAINT prompt_generation_templates_status_check
    CHECK (status IN ('draft', 'published', 'archived'));

ALTER TABLE knowledge_quality_gates
  ADD COLUMN IF NOT EXISTS description text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS target_stage_key text,
  ADD COLUMN IF NOT EXISTS blocking_default boolean NOT NULL DEFAULT true;

UPDATE knowledge_quality_gates SET blocking_default = blocking;

UPDATE knowledge_quality_gates
SET description = CASE gate_key
      WHEN 'pre_import_gate' THEN 'Validates file type, size, encryption, duplicates, secrets, PII and public URL safety.'
      WHEN 'parser_quality_gate' THEN 'Validates parser output, OCR confidence, table structure and fallback quality.'
      WHEN 'chunk_quality_gate' THEN 'Validates active chunks, source trace, duplicates, length and structural quality.'
      WHEN 'embedding_gate' THEN 'Requires the configured share of active chunks to be embedded in Qdrant.'
      WHEN 'fact_quality_gate' THEN 'Requires traceable fact candidates and blocks unsupported facts.'
      WHEN 'generation_quality_gate' THEN 'Requires approved facts, active chunks and generation constraints.'
      WHEN 'traceability_gate' THEN 'Requires generated outputs to trace back to source assets.'
      WHEN 'security_gate' THEN 'Blocks secrets and unsafe source or generated content.'
      WHEN 'publish_gate' THEN 'Requires explicit human approval before export or publication.'
      ELSE description END,
    target_stage_key = CASE gate_key
      WHEN 'pre_import_gate' THEN 'source_precheck'
      WHEN 'parser_quality_gate' THEN 'parse'
      WHEN 'chunk_quality_gate' THEN 'chunk'
      WHEN 'embedding_gate' THEN 'embedding'
      WHEN 'fact_quality_gate' THEN 'fact_extract'
      WHEN 'generation_quality_gate' THEN 'content_generate'
      WHEN 'traceability_gate' THEN 'trace_verify'
      WHEN 'security_gate' THEN 'quality_summary'
      WHEN 'publish_gate' THEN 'publish_or_export'
      ELSE target_stage_key END;

ALTER TABLE knowledge_quality_gates
  DROP CONSTRAINT IF EXISTS knowledge_quality_gates_status_check;
ALTER TABLE knowledge_quality_gates
  ADD CONSTRAINT knowledge_quality_gates_status_check
    CHECK (status IN ('active', 'disabled', 'archived'));

ALTER TABLE knowledge_quality_gate_runs
  ADD COLUMN IF NOT EXISTS blocking boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

UPDATE knowledge_quality_findings SET severity = 'high' WHERE severity = 'blocked';
ALTER TABLE knowledge_quality_findings
  DROP CONSTRAINT IF EXISTS knowledge_quality_findings_severity_check;
ALTER TABLE knowledge_quality_findings
  ADD CONSTRAINT knowledge_quality_findings_severity_check
    CHECK (severity IN ('info', 'warning', 'high', 'critical'));

CREATE INDEX IF NOT EXISTS idx_knowledge_assets_content_hash
  ON knowledge_source_assets(project_id, content_hash)
  WHERE status NOT IN ('archived', 'rejected', 'failed');
CREATE INDEX IF NOT EXISTS idx_knowledge_blocks_parser_order
  ON knowledge_blocks(project_id, parser_run_id, reading_order, block_index);
CREATE INDEX IF NOT EXISTS idx_knowledge_fact_candidates_review
  ON knowledge_fact_candidates(project_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prompt_templates_published
  ON prompt_generation_templates(template_key, template_version)
  WHERE status = 'published';

DROP POLICY IF EXISTS knowledge_quality_gates_runtime_read ON knowledge_quality_gates;
DROP POLICY IF EXISTS knowledge_quality_gates_runtime_manage ON knowledge_quality_gates;
CREATE POLICY knowledge_quality_gates_runtime_read ON knowledge_quality_gates
  FOR SELECT USING (true);
CREATE POLICY knowledge_quality_gates_runtime_manage ON knowledge_quality_gates
  FOR ALL
  USING (
    string_to_array(current_setting('app.roles', true), ',')
      && ARRAY['owner', 'admin', 'project_admin', 'internal_operator', 'system']::text[]
  )
  WITH CHECK (
    string_to_array(current_setting('app.roles', true), ',')
      && ARRAY['owner', 'admin', 'project_admin', 'internal_operator', 'system']::text[]
  );
