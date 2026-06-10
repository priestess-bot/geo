CREATE TABLE IF NOT EXISTS human_review_records (
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

CREATE INDEX IF NOT EXISTS idx_human_review_records_project
  ON human_review_records(project_id, target_type, review_status, created_at);

CREATE INDEX IF NOT EXISTS idx_human_review_records_target
  ON human_review_records(target_type, target_id, created_at);
