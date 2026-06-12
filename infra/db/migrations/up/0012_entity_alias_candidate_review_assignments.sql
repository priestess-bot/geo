ALTER TABLE entity_alias_candidate_reviews
  ADD COLUMN IF NOT EXISTS assigned_to text,
  ADD COLUMN IF NOT EXISTS assigned_by text,
  ADD COLUMN IF NOT EXISTS assignment_status text NOT NULL DEFAULT 'unassigned',
  ADD COLUMN IF NOT EXISTS assignment_note text,
  ADD COLUMN IF NOT EXISTS assigned_at timestamptz,
  ADD COLUMN IF NOT EXISTS due_at timestamptz,
  ADD COLUMN IF NOT EXISTS priority text NOT NULL DEFAULT 'normal';

CREATE INDEX IF NOT EXISTS idx_entity_alias_candidate_reviews_assignment
  ON entity_alias_candidate_reviews(project_id, assignment_status, assigned_to, due_at, priority);
