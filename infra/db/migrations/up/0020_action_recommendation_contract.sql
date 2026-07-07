ALTER TABLE action_recommendations
  ADD COLUMN IF NOT EXISTS action_type text NOT NULL DEFAULT 'general',
  ADD COLUMN IF NOT EXISTS customer_visible boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS score_contribution_ids uuid[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS visibility_note text;

CREATE INDEX IF NOT EXISTS idx_action_recommendations_project_type
  ON action_recommendations(project_id, action_type);

CREATE INDEX IF NOT EXISTS idx_action_recommendations_customer_visible
  ON action_recommendations(project_id, customer_visible)
  WHERE customer_visible = true;
