CREATE TABLE IF NOT EXISTS api_browser_fidelity_checks (
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

CREATE INDEX IF NOT EXISTS idx_api_browser_fidelity_checks_project
  ON api_browser_fidelity_checks(project_id, checked_at);
CREATE INDEX IF NOT EXISTS idx_api_browser_fidelity_checks_report
  ON api_browser_fidelity_checks(report_export_id, checked_at);
