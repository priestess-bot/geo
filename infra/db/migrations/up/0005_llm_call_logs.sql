CREATE TABLE IF NOT EXISTS llm_call_logs (
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

CREATE INDEX IF NOT EXISTS idx_llm_call_logs_answer_run_id ON llm_call_logs(answer_run_id);
CREATE INDEX IF NOT EXISTS idx_llm_call_logs_project_purpose ON llm_call_logs(project_id, purpose);
