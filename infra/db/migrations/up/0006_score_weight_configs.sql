CREATE TABLE IF NOT EXISTS score_weight_configs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  formula_version text NOT NULL,
  weights jsonb NOT NULL,
  updated_by text NOT NULL,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, formula_version)
);

CREATE INDEX IF NOT EXISTS idx_score_weight_configs_project ON score_weight_configs(project_id, formula_version);

ALTER TABLE visibility_score_snapshots
  ADD COLUMN IF NOT EXISTS component_weights_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb;
