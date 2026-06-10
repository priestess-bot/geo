CREATE TABLE IF NOT EXISTS collection_run_summaries (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL,
  run_type text NOT NULL,
  mode text NOT NULL,
  planned_runs integer NOT NULL DEFAULT 0,
  attempted_runs integer NOT NULL DEFAULT 0,
  success_count integer NOT NULL DEFAULT 0,
  failure_count integer NOT NULL DEFAULT 0,
  success_rate numeric(8,4) NOT NULL DEFAULT 0,
  trigger_rate numeric(8,4) NOT NULL DEFAULT 0,
  answer_present_rate numeric(8,4) NOT NULL DEFAULT 0,
  total_cost numeric(12,6) NOT NULL DEFAULT 0,
  average_cost_per_run numeric(12,6) NOT NULL DEFAULT 0,
  total_duration_ms integer NOT NULL DEFAULT 0,
  average_duration_ms integer NOT NULL DEFAULT 0,
  collector_backend_ids text[] NOT NULL DEFAULT '{}',
  platform_distribution jsonb NOT NULL DEFAULT '{}'::jsonb,
  city_distribution jsonb NOT NULL DEFAULT '{}'::jsonb,
  access_method_distribution jsonb NOT NULL DEFAULT '{}'::jsonb,
  failure_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  answer_run_ids uuid[] NOT NULL DEFAULT '{}',
  started_at timestamptz NOT NULL,
  completed_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_collection_run_summaries_project_created
  ON collection_run_summaries(project_id, created_at DESC);
