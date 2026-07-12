-- New consumers must be drained before old binaries can safely own these rows.
DO $$
DECLARE active_count bigint;
BEGIN
  SELECT sum(count_value) INTO active_count FROM (
    SELECT count(*) AS count_value FROM knowledge_import_jobs WHERE status IN ('running', 'finalizing') AND lease_token IS NOT NULL
    UNION ALL SELECT count(*) FROM crawl_jobs WHERE status IN ('running', 'finalizing') AND lease_token IS NOT NULL
    UNION ALL SELECT count(*) FROM knowledge_parser_runs WHERE status IN ('running', 'finalizing') AND lease_token IS NOT NULL
    UNION ALL SELECT count(*) FROM chunk_jobs WHERE status IN ('running', 'finalizing') AND lease_token IS NOT NULL
    UNION ALL SELECT count(*) FROM embedding_jobs WHERE status IN ('running', 'finalizing') AND lease_token IS NOT NULL
    UNION ALL SELECT count(*) FROM fact_extraction_jobs WHERE status IN ('running', 'finalizing') AND lease_token IS NOT NULL
    UNION ALL SELECT count(*) FROM prompt_generation_jobs WHERE status IN ('running', 'finalizing') AND lease_token IS NOT NULL
    UNION ALL SELECT count(*) FROM content_generation_jobs WHERE status IN ('running', 'finalizing') AND lease_token IS NOT NULL
    UNION ALL SELECT count(*) FROM collection_jobs WHERE status IN ('running', 'finalizing') AND lease_token IS NOT NULL
  ) active_rows;
  IF active_count > 0 THEN
    RAISE EXCEPTION 'cannot roll back durable leases while % active token owner(s) remain', active_count;
  END IF;
END $$;

ALTER TABLE knowledge_import_jobs DROP CONSTRAINT IF EXISTS knowledge_import_jobs_active_lease_check, DROP CONSTRAINT IF EXISTS knowledge_import_jobs_status_check;
ALTER TABLE crawl_jobs DROP CONSTRAINT IF EXISTS crawl_jobs_active_lease_check, DROP CONSTRAINT IF EXISTS crawl_jobs_status_check;
ALTER TABLE knowledge_parser_runs DROP CONSTRAINT IF EXISTS knowledge_parser_runs_active_lease_check, DROP CONSTRAINT IF EXISTS knowledge_parser_runs_status_check;
ALTER TABLE chunk_jobs DROP CONSTRAINT IF EXISTS chunk_jobs_active_lease_check, DROP CONSTRAINT IF EXISTS chunk_jobs_status_check;
ALTER TABLE embedding_jobs DROP CONSTRAINT IF EXISTS embedding_jobs_active_lease_check, DROP CONSTRAINT IF EXISTS embedding_jobs_status_check;
ALTER TABLE fact_extraction_jobs DROP CONSTRAINT IF EXISTS fact_extraction_jobs_active_lease_check, DROP CONSTRAINT IF EXISTS fact_extraction_jobs_status_check;
ALTER TABLE prompt_generation_jobs DROP CONSTRAINT IF EXISTS prompt_generation_jobs_active_lease_check, DROP CONSTRAINT IF EXISTS prompt_generation_jobs_status_check;
ALTER TABLE content_generation_jobs DROP CONSTRAINT IF EXISTS content_generation_jobs_active_lease_check, DROP CONSTRAINT IF EXISTS content_generation_jobs_status_check;
ALTER TABLE collection_jobs DROP CONSTRAINT IF EXISTS collection_jobs_active_lease_check, DROP CONSTRAINT IF EXISTS collection_jobs_status_check;

UPDATE knowledge_import_jobs SET status = CASE WHEN status = 'dead_letter' THEN 'failed' ELSE 'queued' END WHERE status IN ('retry_wait', 'dead_letter', 'finalizing');
UPDATE crawl_jobs SET status = CASE WHEN status = 'dead_letter' THEN 'failed' ELSE 'queued' END WHERE status IN ('retry_wait', 'dead_letter', 'finalizing');
UPDATE knowledge_parser_runs SET status = CASE WHEN status = 'dead_letter' THEN 'failed' ELSE 'queued' END WHERE status IN ('retry_wait', 'dead_letter', 'finalizing');
UPDATE chunk_jobs SET status = CASE WHEN status = 'dead_letter' THEN 'failed' ELSE 'queued' END WHERE status IN ('retry_wait', 'dead_letter', 'finalizing');
UPDATE embedding_jobs SET status = CASE WHEN status = 'dead_letter' THEN 'failed' ELSE 'queued' END WHERE status IN ('retry_wait', 'dead_letter', 'finalizing');
UPDATE fact_extraction_jobs SET status = CASE WHEN status = 'dead_letter' THEN 'failed' ELSE 'queued' END WHERE status IN ('retry_wait', 'dead_letter');
UPDATE prompt_generation_jobs SET status = CASE WHEN status = 'dead_letter' THEN 'failed' ELSE 'queued' END WHERE status IN ('retry_wait', 'dead_letter');
UPDATE content_generation_jobs SET status = CASE WHEN status = 'dead_letter' THEN 'failed' ELSE 'queued' END WHERE status IN ('retry_wait', 'dead_letter');
UPDATE collection_jobs SET status = CASE WHEN status = 'retry_wait' THEN 'queued' WHEN status = 'finalizing' THEN 'queued' ELSE status END WHERE status IN ('retry_wait', 'finalizing');

ALTER TABLE knowledge_import_jobs ADD CONSTRAINT knowledge_import_jobs_status_check CHECK (status IN ('draft', 'ready', 'queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'));
ALTER TABLE crawl_jobs ADD CONSTRAINT crawl_jobs_status_check CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'));
ALTER TABLE knowledge_parser_runs ADD CONSTRAINT knowledge_parser_runs_status_check CHECK (status IN ('queued', 'running', 'succeeded', 'fallback_succeeded', 'partial_succeeded', 'failed', 'cancelled'));
ALTER TABLE chunk_jobs ADD CONSTRAINT chunk_jobs_status_check CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'));
ALTER TABLE embedding_jobs ADD CONSTRAINT embedding_jobs_status_check CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'));
ALTER TABLE fact_extraction_jobs ADD CONSTRAINT fact_extraction_jobs_status_check CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'));
ALTER TABLE prompt_generation_jobs ADD CONSTRAINT prompt_generation_jobs_status_check CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'));
ALTER TABLE content_generation_jobs ADD CONSTRAINT content_generation_jobs_status_check CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'));
ALTER TABLE collection_jobs ADD CONSTRAINT collection_jobs_status_check CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'dead_letter', 'cancelled'));

DROP INDEX IF EXISTS idx_knowledge_import_jobs_durable_fresh; DROP INDEX IF EXISTS idx_knowledge_import_jobs_durable_expired;
DROP INDEX IF EXISTS idx_crawl_jobs_durable_fresh; DROP INDEX IF EXISTS idx_crawl_jobs_durable_expired;
DROP INDEX IF EXISTS idx_knowledge_parser_runs_durable_fresh; DROP INDEX IF EXISTS idx_knowledge_parser_runs_durable_expired;
DROP INDEX IF EXISTS idx_chunk_jobs_durable_fresh; DROP INDEX IF EXISTS idx_chunk_jobs_durable_expired;
DROP INDEX IF EXISTS idx_embedding_jobs_durable_fresh; DROP INDEX IF EXISTS idx_embedding_jobs_durable_expired;
DROP INDEX IF EXISTS idx_fact_extraction_jobs_durable_fresh; DROP INDEX IF EXISTS idx_fact_extraction_jobs_durable_expired;
DROP INDEX IF EXISTS idx_prompt_generation_jobs_durable_fresh; DROP INDEX IF EXISTS idx_prompt_generation_jobs_durable_expired;
DROP INDEX IF EXISTS idx_content_generation_jobs_durable_fresh; DROP INDEX IF EXISTS idx_content_generation_jobs_durable_expired;
DROP INDEX IF EXISTS idx_collection_jobs_durable_fresh; DROP INDEX IF EXISTS idx_collection_jobs_durable_expired;

CREATE INDEX IF NOT EXISTS idx_knowledge_import_jobs_queue ON knowledge_import_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_crawl_jobs_queue ON crawl_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_parser_runs_queue ON knowledge_parser_runs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_chunk_jobs_queue ON chunk_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_embedding_jobs_queue ON embedding_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_fact_extraction_jobs_queue ON fact_extraction_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_prompt_generation_jobs_queue ON prompt_generation_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_content_generation_jobs_queue ON content_generation_jobs(status, next_run_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_collection_jobs_claim ON collection_jobs(status, next_attempt_at, created_at) WHERE status = 'queued';

ALTER TABLE knowledge_import_jobs DROP COLUMN IF EXISTS lease_token, DROP COLUMN IF EXISTS lease_reclaimed_count, DROP COLUMN IF EXISTS last_reclaimed_at, DROP COLUMN IF EXISTS last_reclaimed_from, DROP COLUMN IF EXISTS dead_lettered_at, DROP COLUMN IF EXISTS cancel_requested_at, DROP COLUMN IF EXISTS finalize_descriptor;
ALTER TABLE crawl_jobs DROP COLUMN IF EXISTS lease_token, DROP COLUMN IF EXISTS lease_reclaimed_count, DROP COLUMN IF EXISTS last_reclaimed_at, DROP COLUMN IF EXISTS last_reclaimed_from, DROP COLUMN IF EXISTS dead_lettered_at, DROP COLUMN IF EXISTS cancel_requested_at, DROP COLUMN IF EXISTS finalize_descriptor;
ALTER TABLE knowledge_parser_runs DROP COLUMN IF EXISTS lease_token, DROP COLUMN IF EXISTS lease_reclaimed_count, DROP COLUMN IF EXISTS last_reclaimed_at, DROP COLUMN IF EXISTS last_reclaimed_from, DROP COLUMN IF EXISTS dead_lettered_at, DROP COLUMN IF EXISTS cancel_requested_at, DROP COLUMN IF EXISTS finalize_descriptor;
ALTER TABLE chunk_jobs DROP COLUMN IF EXISTS lease_token, DROP COLUMN IF EXISTS lease_reclaimed_count, DROP COLUMN IF EXISTS last_reclaimed_at, DROP COLUMN IF EXISTS last_reclaimed_from, DROP COLUMN IF EXISTS dead_lettered_at, DROP COLUMN IF EXISTS cancel_requested_at, DROP COLUMN IF EXISTS finalize_descriptor;
ALTER TABLE embedding_jobs DROP COLUMN IF EXISTS lease_token, DROP COLUMN IF EXISTS lease_reclaimed_count, DROP COLUMN IF EXISTS last_reclaimed_at, DROP COLUMN IF EXISTS last_reclaimed_from, DROP COLUMN IF EXISTS dead_lettered_at, DROP COLUMN IF EXISTS cancel_requested_at, DROP COLUMN IF EXISTS finalize_descriptor;
ALTER TABLE fact_extraction_jobs DROP COLUMN IF EXISTS lease_token, DROP COLUMN IF EXISTS lease_reclaimed_count, DROP COLUMN IF EXISTS last_reclaimed_at, DROP COLUMN IF EXISTS last_reclaimed_from, DROP COLUMN IF EXISTS dead_lettered_at, DROP COLUMN IF EXISTS cancel_requested_at;
ALTER TABLE prompt_generation_jobs DROP COLUMN IF EXISTS lease_token, DROP COLUMN IF EXISTS lease_reclaimed_count, DROP COLUMN IF EXISTS last_reclaimed_at, DROP COLUMN IF EXISTS last_reclaimed_from, DROP COLUMN IF EXISTS dead_lettered_at, DROP COLUMN IF EXISTS cancel_requested_at;
ALTER TABLE content_generation_jobs DROP COLUMN IF EXISTS lease_token, DROP COLUMN IF EXISTS lease_reclaimed_count, DROP COLUMN IF EXISTS last_reclaimed_at, DROP COLUMN IF EXISTS last_reclaimed_from, DROP COLUMN IF EXISTS dead_lettered_at, DROP COLUMN IF EXISTS cancel_requested_at;
ALTER TABLE collection_jobs DROP COLUMN IF EXISTS heartbeat_at, DROP COLUMN IF EXISTS lease_token, DROP COLUMN IF EXISTS lease_reclaimed_count, DROP COLUMN IF EXISTS last_reclaimed_at, DROP COLUMN IF EXISTS last_reclaimed_from, DROP COLUMN IF EXISTS dead_lettered_at, DROP COLUMN IF EXISTS cancel_requested_at, DROP COLUMN IF EXISTS finalize_descriptor;
DROP TABLE IF EXISTS durable_job_recovery_cursors;
DROP TABLE IF EXISTS durable_job_metric_counters;
