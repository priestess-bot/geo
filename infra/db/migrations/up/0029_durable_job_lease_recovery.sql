-- Durable fencing leases for the Knowledge and Collection PostgreSQL queues.
-- Rollout requires all pre-0029 consumers to be drained before this migration.

ALTER TABLE knowledge_import_jobs
  ADD COLUMN IF NOT EXISTS lease_token uuid,
  ADD COLUMN IF NOT EXISTS lease_reclaimed_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_reclaimed_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_reclaimed_from text,
  ADD COLUMN IF NOT EXISTS dead_lettered_at timestamptz,
  ADD COLUMN IF NOT EXISTS cancel_requested_at timestamptz,
  ADD COLUMN IF NOT EXISTS finalize_descriptor jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE crawl_jobs
  ADD COLUMN IF NOT EXISTS lease_token uuid,
  ADD COLUMN IF NOT EXISTS lease_reclaimed_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_reclaimed_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_reclaimed_from text,
  ADD COLUMN IF NOT EXISTS dead_lettered_at timestamptz,
  ADD COLUMN IF NOT EXISTS cancel_requested_at timestamptz,
  ADD COLUMN IF NOT EXISTS finalize_descriptor jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE knowledge_parser_runs
  ADD COLUMN IF NOT EXISTS lease_token uuid,
  ADD COLUMN IF NOT EXISTS lease_reclaimed_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_reclaimed_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_reclaimed_from text,
  ADD COLUMN IF NOT EXISTS dead_lettered_at timestamptz,
  ADD COLUMN IF NOT EXISTS cancel_requested_at timestamptz,
  ADD COLUMN IF NOT EXISTS finalize_descriptor jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE chunk_jobs
  ADD COLUMN IF NOT EXISTS lease_token uuid,
  ADD COLUMN IF NOT EXISTS lease_reclaimed_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_reclaimed_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_reclaimed_from text,
  ADD COLUMN IF NOT EXISTS dead_lettered_at timestamptz,
  ADD COLUMN IF NOT EXISTS cancel_requested_at timestamptz,
  ADD COLUMN IF NOT EXISTS finalize_descriptor jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE embedding_jobs
  ADD COLUMN IF NOT EXISTS lease_token uuid,
  ADD COLUMN IF NOT EXISTS lease_reclaimed_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_reclaimed_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_reclaimed_from text,
  ADD COLUMN IF NOT EXISTS dead_lettered_at timestamptz,
  ADD COLUMN IF NOT EXISTS cancel_requested_at timestamptz,
  ADD COLUMN IF NOT EXISTS finalize_descriptor jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE fact_extraction_jobs
  ADD COLUMN IF NOT EXISTS lease_token uuid,
  ADD COLUMN IF NOT EXISTS lease_reclaimed_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_reclaimed_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_reclaimed_from text,
  ADD COLUMN IF NOT EXISTS dead_lettered_at timestamptz,
  ADD COLUMN IF NOT EXISTS cancel_requested_at timestamptz;
ALTER TABLE prompt_generation_jobs
  ADD COLUMN IF NOT EXISTS lease_token uuid,
  ADD COLUMN IF NOT EXISTS lease_reclaimed_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_reclaimed_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_reclaimed_from text,
  ADD COLUMN IF NOT EXISTS dead_lettered_at timestamptz,
  ADD COLUMN IF NOT EXISTS cancel_requested_at timestamptz;
ALTER TABLE content_generation_jobs
  ADD COLUMN IF NOT EXISTS lease_token uuid,
  ADD COLUMN IF NOT EXISTS lease_reclaimed_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_reclaimed_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_reclaimed_from text,
  ADD COLUMN IF NOT EXISTS dead_lettered_at timestamptz,
  ADD COLUMN IF NOT EXISTS cancel_requested_at timestamptz;
ALTER TABLE collection_jobs
  ADD COLUMN IF NOT EXISTS heartbeat_at timestamptz,
  ADD COLUMN IF NOT EXISTS lease_token uuid,
  ADD COLUMN IF NOT EXISTS lease_reclaimed_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_reclaimed_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_reclaimed_from text,
  ADD COLUMN IF NOT EXISTS dead_lettered_at timestamptz,
  ADD COLUMN IF NOT EXISTS cancel_requested_at timestamptz,
  ADD COLUMN IF NOT EXISTS finalize_descriptor jsonb NOT NULL DEFAULT '{}'::jsonb;

-- Every status contract is rebuilt independently so existing table-specific
-- states survive the common durable-lease additions.
ALTER TABLE knowledge_import_jobs DROP CONSTRAINT IF EXISTS knowledge_import_jobs_status_check;
ALTER TABLE crawl_jobs DROP CONSTRAINT IF EXISTS crawl_jobs_status_check;
ALTER TABLE knowledge_parser_runs DROP CONSTRAINT IF EXISTS knowledge_parser_runs_status_check;
ALTER TABLE chunk_jobs DROP CONSTRAINT IF EXISTS chunk_jobs_status_check;
ALTER TABLE embedding_jobs DROP CONSTRAINT IF EXISTS embedding_jobs_status_check;
ALTER TABLE fact_extraction_jobs DROP CONSTRAINT IF EXISTS fact_extraction_jobs_status_check;
ALTER TABLE prompt_generation_jobs DROP CONSTRAINT IF EXISTS prompt_generation_jobs_status_check;
ALTER TABLE content_generation_jobs DROP CONSTRAINT IF EXISTS content_generation_jobs_status_check;
ALTER TABLE collection_jobs DROP CONSTRAINT IF EXISTS collection_jobs_status_check;

-- A pre-0029 owner has no fencing token. Drained active rows are made safely
-- retryable or terminal before the active-lease invariant is enabled.
UPDATE knowledge_import_jobs SET
  status = CASE WHEN cancel_requested_at IS NOT NULL THEN 'cancelled' WHEN attempt_count < max_attempts THEN 'retry_wait' ELSE 'dead_letter' END,
  dead_lettered_at = CASE WHEN attempt_count >= max_attempts AND cancel_requested_at IS NULL THEN now() ELSE dead_lettered_at END,
  completed_at = CASE WHEN cancel_requested_at IS NOT NULL OR attempt_count >= max_attempts THEN now() ELSE NULL END,
  locked_by = NULL, locked_at = NULL, lease_expires_at = NULL, heartbeat_at = NULL, lease_token = NULL,
  updated_at = now()
WHERE status IN ('running', 'finalizing') AND lease_token IS NULL;
UPDATE crawl_jobs SET
  status = CASE WHEN cancel_requested_at IS NOT NULL THEN 'cancelled' WHEN attempt_count < max_attempts THEN 'retry_wait' ELSE 'dead_letter' END,
  dead_lettered_at = CASE WHEN attempt_count >= max_attempts AND cancel_requested_at IS NULL THEN now() ELSE dead_lettered_at END,
  completed_at = CASE WHEN cancel_requested_at IS NOT NULL OR attempt_count >= max_attempts THEN now() ELSE NULL END,
  locked_by = NULL, locked_at = NULL, lease_expires_at = NULL, heartbeat_at = NULL, lease_token = NULL,
  updated_at = now()
WHERE status IN ('running', 'finalizing') AND lease_token IS NULL;
UPDATE knowledge_parser_runs SET
  status = CASE WHEN cancel_requested_at IS NOT NULL THEN 'cancelled' WHEN attempt_count < max_attempts THEN 'retry_wait' ELSE 'dead_letter' END,
  dead_lettered_at = CASE WHEN attempt_count >= max_attempts AND cancel_requested_at IS NULL THEN now() ELSE dead_lettered_at END,
  completed_at = CASE WHEN cancel_requested_at IS NOT NULL OR attempt_count >= max_attempts THEN now() ELSE NULL END,
  locked_by = NULL, locked_at = NULL, lease_expires_at = NULL, heartbeat_at = NULL, lease_token = NULL,
  updated_at = now()
WHERE status IN ('running', 'finalizing') AND lease_token IS NULL;
UPDATE chunk_jobs SET
  status = CASE WHEN cancel_requested_at IS NOT NULL THEN 'cancelled' WHEN attempt_count < max_attempts THEN 'retry_wait' ELSE 'dead_letter' END,
  dead_lettered_at = CASE WHEN attempt_count >= max_attempts AND cancel_requested_at IS NULL THEN now() ELSE dead_lettered_at END,
  completed_at = CASE WHEN cancel_requested_at IS NOT NULL OR attempt_count >= max_attempts THEN now() ELSE NULL END,
  locked_by = NULL, locked_at = NULL, lease_expires_at = NULL, heartbeat_at = NULL, lease_token = NULL,
  updated_at = now()
WHERE status IN ('running', 'finalizing') AND lease_token IS NULL;
UPDATE embedding_jobs SET
  status = CASE WHEN cancel_requested_at IS NOT NULL THEN 'cancelled' WHEN attempt_count < max_attempts THEN 'retry_wait' ELSE 'dead_letter' END,
  dead_lettered_at = CASE WHEN attempt_count >= max_attempts AND cancel_requested_at IS NULL THEN now() ELSE dead_lettered_at END,
  completed_at = CASE WHEN cancel_requested_at IS NOT NULL OR attempt_count >= max_attempts THEN now() ELSE NULL END,
  locked_by = NULL, locked_at = NULL, lease_expires_at = NULL, heartbeat_at = NULL, lease_token = NULL,
  updated_at = now()
WHERE status IN ('running', 'finalizing') AND lease_token IS NULL;
UPDATE fact_extraction_jobs SET
  status = CASE WHEN cancel_requested_at IS NOT NULL THEN 'cancelled' WHEN attempt_count < max_attempts THEN 'retry_wait' ELSE 'dead_letter' END,
  dead_lettered_at = CASE WHEN attempt_count >= max_attempts AND cancel_requested_at IS NULL THEN now() ELSE dead_lettered_at END,
  completed_at = CASE WHEN cancel_requested_at IS NOT NULL OR attempt_count >= max_attempts THEN now() ELSE NULL END,
  locked_by = NULL, locked_at = NULL, lease_expires_at = NULL, heartbeat_at = NULL, lease_token = NULL,
  updated_at = now()
WHERE status IN ('running', 'finalizing') AND lease_token IS NULL;
UPDATE prompt_generation_jobs SET
  status = CASE WHEN cancel_requested_at IS NOT NULL THEN 'cancelled' WHEN attempt_count < max_attempts THEN 'retry_wait' ELSE 'dead_letter' END,
  dead_lettered_at = CASE WHEN attempt_count >= max_attempts AND cancel_requested_at IS NULL THEN now() ELSE dead_lettered_at END,
  completed_at = CASE WHEN cancel_requested_at IS NOT NULL OR attempt_count >= max_attempts THEN now() ELSE NULL END,
  locked_by = NULL, locked_at = NULL, lease_expires_at = NULL, heartbeat_at = NULL, lease_token = NULL,
  updated_at = now()
WHERE status IN ('running', 'finalizing') AND lease_token IS NULL;
UPDATE content_generation_jobs SET
  status = CASE WHEN cancel_requested_at IS NOT NULL THEN 'cancelled' WHEN attempt_count < max_attempts THEN 'retry_wait' ELSE 'dead_letter' END,
  dead_lettered_at = CASE WHEN attempt_count >= max_attempts AND cancel_requested_at IS NULL THEN now() ELSE dead_lettered_at END,
  completed_at = CASE WHEN cancel_requested_at IS NOT NULL OR attempt_count >= max_attempts THEN now() ELSE NULL END,
  locked_by = NULL, locked_at = NULL, lease_expires_at = NULL, heartbeat_at = NULL, lease_token = NULL,
  updated_at = now()
WHERE status IN ('running', 'finalizing') AND lease_token IS NULL;
UPDATE collection_jobs SET
  status = CASE WHEN cancel_requested_at IS NOT NULL THEN 'cancelled' WHEN attempt_count < max_attempts THEN 'retry_wait' ELSE 'dead_letter' END,
  dead_lettered_at = CASE WHEN attempt_count >= max_attempts AND cancel_requested_at IS NULL THEN now() ELSE dead_lettered_at END,
  completed_at = CASE WHEN cancel_requested_at IS NOT NULL OR attempt_count >= max_attempts THEN now() ELSE NULL END,
  cancelled_at = CASE WHEN cancel_requested_at IS NOT NULL THEN now() ELSE cancelled_at END,
  locked_by = NULL, locked_at = NULL, lease_expires_at = NULL, heartbeat_at = NULL, lease_token = NULL,
  updated_at = now()
WHERE status IN ('running', 'finalizing') AND lease_token IS NULL;

-- A single-asset Content Job never uses partial success. Only a persisted Draft
-- proves that the model result crossed the durable boundary; all other legacy
-- partial rows fail closed for operator review.
UPDATE content_generation_jobs AS job
SET status = CASE
      WHEN EXISTS (
        SELECT 1 FROM content_drafts AS draft
        WHERE draft.content_generation_job_id = job.id
      ) THEN 'succeeded'
      ELSE 'failed'
    END,
    last_error_code = CASE
      WHEN EXISTS (
        SELECT 1 FROM content_drafts AS draft
        WHERE draft.content_generation_job_id = job.id
      ) THEN last_error_code
      ELSE 'legacy_partial_without_persisted_draft'
    END,
    last_error_message = CASE
      WHEN EXISTS (
        SELECT 1 FROM content_drafts AS draft
        WHERE draft.content_generation_job_id = job.id
      ) THEN last_error_message
      ELSE '0029 normalized a legacy partial Content Job without a persisted Draft'
    END,
    completed_at = COALESCE(completed_at, now()),
    updated_at = now()
WHERE status = 'partial_succeeded';

ALTER TABLE knowledge_import_jobs ADD CONSTRAINT knowledge_import_jobs_status_check CHECK (status IN ('draft', 'ready', 'queued', 'running', 'finalizing', 'succeeded', 'partial_succeeded', 'failed', 'retry_wait', 'dead_letter', 'cancelled'));
ALTER TABLE crawl_jobs ADD CONSTRAINT crawl_jobs_status_check CHECK (status IN ('queued', 'running', 'finalizing', 'succeeded', 'partial_succeeded', 'failed', 'retry_wait', 'dead_letter', 'cancelled'));
ALTER TABLE knowledge_parser_runs ADD CONSTRAINT knowledge_parser_runs_status_check CHECK (status IN ('queued', 'running', 'finalizing', 'succeeded', 'fallback_succeeded', 'partial_succeeded', 'failed', 'retry_wait', 'dead_letter', 'cancelled'));
ALTER TABLE chunk_jobs ADD CONSTRAINT chunk_jobs_status_check CHECK (status IN ('queued', 'running', 'finalizing', 'succeeded', 'partial_succeeded', 'failed', 'retry_wait', 'dead_letter', 'cancelled'));
ALTER TABLE embedding_jobs ADD CONSTRAINT embedding_jobs_status_check CHECK (status IN ('queued', 'running', 'finalizing', 'succeeded', 'partial_succeeded', 'failed', 'retry_wait', 'dead_letter', 'cancelled'));
ALTER TABLE fact_extraction_jobs ADD CONSTRAINT fact_extraction_jobs_status_check CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'retry_wait', 'dead_letter', 'cancelled'));
ALTER TABLE prompt_generation_jobs ADD CONSTRAINT prompt_generation_jobs_status_check CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'retry_wait', 'dead_letter', 'cancelled'));
ALTER TABLE content_generation_jobs ADD CONSTRAINT content_generation_jobs_status_check CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'retry_wait', 'dead_letter', 'cancelled'));
ALTER TABLE collection_jobs ADD CONSTRAINT collection_jobs_status_check CHECK (status IN ('queued', 'running', 'finalizing', 'succeeded', 'partial_succeeded', 'failed', 'retry_wait', 'dead_letter', 'cancelled'));

ALTER TABLE knowledge_import_jobs DROP CONSTRAINT IF EXISTS knowledge_import_jobs_active_lease_check;
ALTER TABLE crawl_jobs DROP CONSTRAINT IF EXISTS crawl_jobs_active_lease_check;
ALTER TABLE knowledge_parser_runs DROP CONSTRAINT IF EXISTS knowledge_parser_runs_active_lease_check;
ALTER TABLE chunk_jobs DROP CONSTRAINT IF EXISTS chunk_jobs_active_lease_check;
ALTER TABLE embedding_jobs DROP CONSTRAINT IF EXISTS embedding_jobs_active_lease_check;
ALTER TABLE fact_extraction_jobs DROP CONSTRAINT IF EXISTS fact_extraction_jobs_active_lease_check;
ALTER TABLE prompt_generation_jobs DROP CONSTRAINT IF EXISTS prompt_generation_jobs_active_lease_check;
ALTER TABLE content_generation_jobs DROP CONSTRAINT IF EXISTS content_generation_jobs_active_lease_check;
ALTER TABLE collection_jobs DROP CONSTRAINT IF EXISTS collection_jobs_active_lease_check;

ALTER TABLE knowledge_import_jobs ADD CONSTRAINT knowledge_import_jobs_active_lease_check CHECK (status NOT IN ('running', 'finalizing') OR (locked_by IS NOT NULL AND locked_at IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL));
ALTER TABLE crawl_jobs ADD CONSTRAINT crawl_jobs_active_lease_check CHECK (status NOT IN ('running', 'finalizing') OR (locked_by IS NOT NULL AND locked_at IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL));
ALTER TABLE knowledge_parser_runs ADD CONSTRAINT knowledge_parser_runs_active_lease_check CHECK (status NOT IN ('running', 'finalizing') OR (locked_by IS NOT NULL AND locked_at IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL));
ALTER TABLE chunk_jobs ADD CONSTRAINT chunk_jobs_active_lease_check CHECK (status NOT IN ('running', 'finalizing') OR (locked_by IS NOT NULL AND locked_at IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL));
ALTER TABLE embedding_jobs ADD CONSTRAINT embedding_jobs_active_lease_check CHECK (status NOT IN ('running', 'finalizing') OR (locked_by IS NOT NULL AND locked_at IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL));
ALTER TABLE fact_extraction_jobs ADD CONSTRAINT fact_extraction_jobs_active_lease_check CHECK (status NOT IN ('running', 'finalizing') OR (locked_by IS NOT NULL AND locked_at IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL));
ALTER TABLE prompt_generation_jobs ADD CONSTRAINT prompt_generation_jobs_active_lease_check CHECK (status NOT IN ('running', 'finalizing') OR (locked_by IS NOT NULL AND locked_at IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL));
ALTER TABLE content_generation_jobs ADD CONSTRAINT content_generation_jobs_active_lease_check CHECK (status NOT IN ('running', 'finalizing') OR (locked_by IS NOT NULL AND locked_at IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL));
ALTER TABLE collection_jobs ADD CONSTRAINT collection_jobs_active_lease_check CHECK (status NOT IN ('running', 'finalizing') OR (locked_by IS NOT NULL AND locked_at IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL));

DROP INDEX IF EXISTS idx_knowledge_import_jobs_queue;
DROP INDEX IF EXISTS idx_crawl_jobs_queue;
DROP INDEX IF EXISTS idx_knowledge_parser_runs_queue;
DROP INDEX IF EXISTS idx_chunk_jobs_queue;
DROP INDEX IF EXISTS idx_embedding_jobs_queue;
DROP INDEX IF EXISTS idx_fact_extraction_jobs_queue;
DROP INDEX IF EXISTS idx_prompt_generation_jobs_queue;
DROP INDEX IF EXISTS idx_content_generation_jobs_queue;
DROP INDEX IF EXISTS idx_collection_jobs_claim;
DROP INDEX IF EXISTS idx_knowledge_import_jobs_durable_fresh; DROP INDEX IF EXISTS idx_knowledge_import_jobs_durable_expired;
DROP INDEX IF EXISTS idx_crawl_jobs_durable_fresh; DROP INDEX IF EXISTS idx_crawl_jobs_durable_expired;
DROP INDEX IF EXISTS idx_knowledge_parser_runs_durable_fresh; DROP INDEX IF EXISTS idx_knowledge_parser_runs_durable_expired;
DROP INDEX IF EXISTS idx_chunk_jobs_durable_fresh; DROP INDEX IF EXISTS idx_chunk_jobs_durable_expired;
DROP INDEX IF EXISTS idx_embedding_jobs_durable_fresh; DROP INDEX IF EXISTS idx_embedding_jobs_durable_expired;
DROP INDEX IF EXISTS idx_fact_extraction_jobs_durable_fresh; DROP INDEX IF EXISTS idx_fact_extraction_jobs_durable_expired;
DROP INDEX IF EXISTS idx_prompt_generation_jobs_durable_fresh; DROP INDEX IF EXISTS idx_prompt_generation_jobs_durable_expired;
DROP INDEX IF EXISTS idx_content_generation_jobs_durable_fresh; DROP INDEX IF EXISTS idx_content_generation_jobs_durable_expired;
DROP INDEX IF EXISTS idx_collection_jobs_durable_fresh; DROP INDEX IF EXISTS idx_collection_jobs_durable_expired;

CREATE INDEX idx_knowledge_import_jobs_durable_fresh ON knowledge_import_jobs(next_run_at, priority DESC, created_at) WHERE status IN ('queued', 'retry_wait') AND cancel_requested_at IS NULL;
CREATE INDEX idx_knowledge_import_jobs_durable_expired ON knowledge_import_jobs(lease_expires_at, priority DESC, created_at) WHERE status IN ('running', 'finalizing') AND lease_expires_at IS NOT NULL AND cancel_requested_at IS NULL;
CREATE INDEX idx_crawl_jobs_durable_fresh ON crawl_jobs(next_run_at, priority DESC, created_at) WHERE status IN ('queued', 'retry_wait') AND cancel_requested_at IS NULL;
CREATE INDEX idx_crawl_jobs_durable_expired ON crawl_jobs(lease_expires_at, priority DESC, created_at) WHERE status IN ('running', 'finalizing') AND lease_expires_at IS NOT NULL AND cancel_requested_at IS NULL;
CREATE INDEX idx_knowledge_parser_runs_durable_fresh ON knowledge_parser_runs(next_run_at, priority DESC, created_at) WHERE status IN ('queued', 'retry_wait') AND cancel_requested_at IS NULL;
CREATE INDEX idx_knowledge_parser_runs_durable_expired ON knowledge_parser_runs(lease_expires_at, priority DESC, created_at) WHERE status IN ('running', 'finalizing') AND lease_expires_at IS NOT NULL AND cancel_requested_at IS NULL;
CREATE INDEX idx_chunk_jobs_durable_fresh ON chunk_jobs(next_run_at, priority DESC, created_at) WHERE status IN ('queued', 'retry_wait') AND cancel_requested_at IS NULL;
CREATE INDEX idx_chunk_jobs_durable_expired ON chunk_jobs(lease_expires_at, priority DESC, created_at) WHERE status IN ('running', 'finalizing') AND lease_expires_at IS NOT NULL AND cancel_requested_at IS NULL;
CREATE INDEX idx_embedding_jobs_durable_fresh ON embedding_jobs(next_run_at, priority DESC, created_at) WHERE status IN ('queued', 'retry_wait') AND cancel_requested_at IS NULL;
CREATE INDEX idx_embedding_jobs_durable_expired ON embedding_jobs(lease_expires_at, priority DESC, created_at) WHERE status IN ('running', 'finalizing') AND lease_expires_at IS NOT NULL AND cancel_requested_at IS NULL;
CREATE INDEX idx_fact_extraction_jobs_durable_fresh ON fact_extraction_jobs(next_run_at, priority DESC, created_at) WHERE status IN ('queued', 'retry_wait') AND cancel_requested_at IS NULL;
CREATE INDEX idx_fact_extraction_jobs_durable_expired ON fact_extraction_jobs(lease_expires_at, priority DESC, created_at) WHERE status IN ('running', 'finalizing') AND lease_expires_at IS NOT NULL AND cancel_requested_at IS NULL;
CREATE INDEX idx_prompt_generation_jobs_durable_fresh ON prompt_generation_jobs(next_run_at, priority DESC, created_at) WHERE status IN ('queued', 'retry_wait') AND cancel_requested_at IS NULL;
CREATE INDEX idx_prompt_generation_jobs_durable_expired ON prompt_generation_jobs(lease_expires_at, priority DESC, created_at) WHERE status IN ('running', 'finalizing') AND lease_expires_at IS NOT NULL AND cancel_requested_at IS NULL;
CREATE INDEX idx_content_generation_jobs_durable_fresh ON content_generation_jobs(next_run_at, priority DESC, created_at) WHERE status IN ('queued', 'retry_wait') AND cancel_requested_at IS NULL;
CREATE INDEX idx_content_generation_jobs_durable_expired ON content_generation_jobs(lease_expires_at, priority DESC, created_at) WHERE status IN ('running', 'finalizing') AND lease_expires_at IS NOT NULL AND cancel_requested_at IS NULL;
CREATE INDEX idx_collection_jobs_durable_fresh ON collection_jobs(next_attempt_at, created_at) WHERE status IN ('queued', 'retry_wait') AND cancel_requested_at IS NULL;
CREATE INDEX idx_collection_jobs_durable_expired ON collection_jobs(lease_expires_at, created_at) WHERE status IN ('running', 'finalizing') AND lease_expires_at IS NOT NULL AND cancel_requested_at IS NULL;

CREATE TABLE IF NOT EXISTS durable_job_recovery_cursors (
  queue_name text PRIMARY KEY,
  cursor_index integer NOT NULL DEFAULT 0 CHECK (cursor_index >= 0),
  recovery_slots_used integer NOT NULL DEFAULT 0 CHECK (recovery_slots_used >= 0),
  last_worker_id text,
  worker_heartbeat_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (queue_name IN ('knowledge_fresh', 'knowledge_recovery', 'collection_recovery'))
);
GRANT SELECT, INSERT, UPDATE ON durable_job_recovery_cursors TO geno_runtime_app;

CREATE TABLE IF NOT EXISTS durable_job_metric_counters (
  queue_name text NOT NULL,
  job_type text NOT NULL,
  metric_name text NOT NULL,
  metric_value bigint NOT NULL DEFAULT 0 CHECK (metric_value >= 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (queue_name, job_type, metric_name),
  CHECK (queue_name IN ('knowledge', 'collection')),
  CHECK (job_type IN (
    'knowledge_import_jobs', 'crawl_jobs', 'knowledge_parser_runs', 'chunk_jobs',
    'embedding_jobs', 'fact_extraction_jobs', 'prompt_generation_jobs',
    'content_generation_jobs', 'collection_jobs'
  )),
  CHECK (metric_name IN (
    'heartbeat_success', 'heartbeat_failure', 'lease_lost',
    'stale_completion', 'cancelled', 'dead_lettered'
  ))
);
ALTER TABLE durable_job_metric_counters
  DROP CONSTRAINT IF EXISTS durable_job_metric_counters_metric_name_check;
ALTER TABLE durable_job_metric_counters
  ADD CONSTRAINT durable_job_metric_counters_metric_name_check CHECK (metric_name IN (
    'heartbeat_success', 'heartbeat_failure', 'lease_lost',
    'stale_completion', 'cancelled', 'dead_lettered'
  ));
GRANT SELECT, INSERT, UPDATE ON durable_job_metric_counters TO geno_runtime_app;
