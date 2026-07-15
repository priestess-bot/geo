ALTER TABLE localized_knowledge_facts
  ADD COLUMN IF NOT EXISTS knowledge_document_id uuid,
  ADD COLUMN IF NOT EXISTS knowledge_document_version_id uuid,
  ADD COLUMN IF NOT EXISTS source_url text,
  ADD COLUMN IF NOT EXISTS source_quote text,
  ADD COLUMN IF NOT EXISTS source_kind text NOT NULL DEFAULT 'manual_csv',
  ADD COLUMN IF NOT EXISTS review_status text NOT NULL DEFAULT 'approved',
  ADD COLUMN IF NOT EXISTS reviewed_by text,
  ADD COLUMN IF NOT EXISTS reviewed_at timestamptz,
  ADD COLUMN IF NOT EXISTS superseded_by_fact_id uuid;

ALTER TABLE content_drafts
  ADD COLUMN IF NOT EXISTS generation_job_id uuid,
  ADD COLUMN IF NOT EXISTS source_document_ids uuid[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS source_fact_ids uuid[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS generation_model text,
  ADD COLUMN IF NOT EXISTS generation_prompt_version text,
  ADD COLUMN IF NOT EXISTS raw_output_hash text,
  ADD COLUMN IF NOT EXISTS draft_version integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS superseded_by_draft_id uuid;

CREATE TABLE IF NOT EXISTS knowledge_documents (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_type text NOT NULL,
  normalized_url text,
  source_url text,
  title text NOT NULL DEFAULT '',
  raw_text text NOT NULL DEFAULT '',
  content_hash text NOT NULL,
  status text NOT NULL DEFAULT 'queued',
  error_reason text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  imported_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (source_type IN ('csv', 'url', 'web_text')),
  CHECK (status IN ('queued', 'crawling', 'crawled', 'extracting', 'extracted', 'failed', 'archived'))
);

CREATE TABLE IF NOT EXISTS knowledge_document_versions (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  knowledge_document_id uuid NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
  version_number integer NOT NULL,
  normalized_url text,
  source_url text,
  title text NOT NULL DEFAULT '',
  raw_text text NOT NULL DEFAULT '',
  content_hash text NOT NULL,
  status text NOT NULL DEFAULT 'crawled',
  crawl_adapter_version text NOT NULL DEFAULT 'crawl4ai_adapter_v1',
  byte_size integer NOT NULL DEFAULT 0,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (knowledge_document_id, version_number)
);

CREATE TABLE IF NOT EXISTS knowledge_generation_jobs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  job_type text NOT NULL,
  status text NOT NULL DEFAULT 'queued',
  request_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  step_events jsonb NOT NULL DEFAULT '[]'::jsonb,
  generation_model text NOT NULL DEFAULT 'deepseek-v4-flash',
  generation_prompt_version text NOT NULL DEFAULT 'knowledge_application_haystack_adapter_v1',
  secret_ref text,
  raw_output_hash text,
  error_reason text,
  requested_by text NOT NULL,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (job_type IN ('crawl', 'extract_facts', 'content_draft', 'faq_candidates', 'prompt_candidates', 'all')),
  CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS prompt_candidates (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  generation_job_id uuid REFERENCES knowledge_generation_jobs(id) ON DELETE SET NULL,
  text text NOT NULL,
  intent_type text NOT NULL,
  market_code text NOT NULL,
  city text NOT NULL,
  language text NOT NULL,
  target_brand text NOT NULL,
  competitors jsonb NOT NULL DEFAULT '[]'::jsonb,
  priority integer NOT NULL DEFAULT 1,
  intent_weight numeric(8,4) NOT NULL DEFAULT 1.0,
  source_knowledge_fact_ids uuid[] NOT NULL DEFAULT '{}',
  rationale text NOT NULL DEFAULT '',
  duplicate_state text NOT NULL DEFAULT 'unique',
  review_status text NOT NULL DEFAULT 'pending_review',
  reviewed_by text,
  reviewed_at timestamptz,
  imported_prompt_id uuid,
  generation_model text NOT NULL DEFAULT 'deepseek-v4-flash',
  generation_prompt_version text NOT NULL DEFAULT 'geo_prompt_candidate_v1',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (review_status IN ('pending_review', 'approved', 'rejected', 'imported', 'archived')),
  CHECK (duplicate_state IN ('unique', 'duplicate', 'possible_duplicate'))
);

CREATE TABLE IF NOT EXISTS faq_answer_candidates (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  generation_job_id uuid REFERENCES knowledge_generation_jobs(id) ON DELETE SET NULL,
  question text NOT NULL,
  answer_markdown text NOT NULL,
  target_prompt_ids uuid[] NOT NULL DEFAULT '{}',
  used_knowledge_fact_ids uuid[] NOT NULL DEFAULT '{}',
  market_code text NOT NULL,
  city text NOT NULL,
  language text NOT NULL,
  review_status text NOT NULL DEFAULT 'pending_review',
  reviewed_by text,
  reviewed_at timestamptz,
  generation_model text NOT NULL DEFAULT 'deepseek-v4-flash',
  generation_prompt_version text NOT NULL DEFAULT 'geo_faq_candidate_v1',
  rationale text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (review_status IN ('pending_review', 'approved', 'rejected', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_knowledge_documents_project_status
  ON knowledge_documents(project_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_document_versions_document
  ON knowledge_document_versions(knowledge_document_id, version_number DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_generation_jobs_project_status
  ON knowledge_generation_jobs(project_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prompt_candidates_project_status
  ON prompt_candidates(project_id, review_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_faq_answer_candidates_project_status
  ON faq_answer_candidates(project_id, review_status, created_at DESC);

ALTER TABLE knowledge_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_documents FORCE ROW LEVEL SECURITY;
ALTER TABLE knowledge_document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_document_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE knowledge_generation_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_generation_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE prompt_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt_candidates FORCE ROW LEVEL SECURITY;
ALTER TABLE faq_answer_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE faq_answer_candidates FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS knowledge_documents_runtime_project_isolation ON knowledge_documents;
CREATE POLICY knowledge_documents_runtime_project_isolation ON knowledge_documents
  USING (geo_runtime_can_access_project(project_id))
  WITH CHECK (geo_runtime_can_access_project(project_id));

DROP POLICY IF EXISTS knowledge_document_versions_runtime_project_isolation ON knowledge_document_versions;
CREATE POLICY knowledge_document_versions_runtime_project_isolation ON knowledge_document_versions
  USING (geo_runtime_can_access_project(project_id))
  WITH CHECK (geo_runtime_can_access_project(project_id));

DROP POLICY IF EXISTS knowledge_generation_jobs_runtime_project_isolation ON knowledge_generation_jobs;
CREATE POLICY knowledge_generation_jobs_runtime_project_isolation ON knowledge_generation_jobs
  USING (geo_runtime_can_access_project(project_id))
  WITH CHECK (geo_runtime_can_access_project(project_id));

DROP POLICY IF EXISTS prompt_candidates_runtime_project_isolation ON prompt_candidates;
CREATE POLICY prompt_candidates_runtime_project_isolation ON prompt_candidates
  USING (geo_runtime_can_access_project(project_id))
  WITH CHECK (geo_runtime_can_access_project(project_id));

DROP POLICY IF EXISTS faq_answer_candidates_runtime_project_isolation ON faq_answer_candidates;
CREATE POLICY faq_answer_candidates_runtime_project_isolation ON faq_answer_candidates
  USING (geo_runtime_can_access_project(project_id))
  WITH CHECK (geo_runtime_can_access_project(project_id));
