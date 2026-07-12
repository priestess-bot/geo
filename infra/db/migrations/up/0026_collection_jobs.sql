CREATE TABLE IF NOT EXISTS collection_jobs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'queued',
  mode text NOT NULL DEFAULT 'api',
  prompt_limit integer NOT NULL DEFAULT 10,
  sample_size integer NOT NULL DEFAULT 1,
  cities text[] NOT NULL DEFAULT '{}',
  requested_by text NOT NULL,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  locked_by text,
  locked_at timestamptz,
  lease_expires_at timestamptz,
  result_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  last_error_code text,
  last_error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  cancelled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'dead_letter', 'cancelled')),
  CHECK (mode IN ('api')),
  CHECK (prompt_limit BETWEEN 1 AND 200),
  CHECK (sample_size BETWEEN 1 AND 20),
  CHECK (max_attempts BETWEEN 1 AND 10)
);

CREATE INDEX IF NOT EXISTS idx_collection_jobs_project_created
  ON collection_jobs(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_collection_jobs_claim
  ON collection_jobs(status, next_attempt_at, created_at)
  WHERE status = 'queued';

ALTER TABLE collection_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE collection_jobs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS collection_jobs_runtime_project_isolation ON collection_jobs;
CREATE POLICY collection_jobs_runtime_project_isolation ON collection_jobs
  USING (geno_runtime_can_access_project(project_id))
  WITH CHECK (geno_runtime_can_access_project(project_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON collection_jobs TO geno_runtime_app;
