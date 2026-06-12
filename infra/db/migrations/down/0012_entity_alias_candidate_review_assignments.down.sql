DROP INDEX IF EXISTS idx_entity_alias_candidate_reviews_assignment;

ALTER TABLE entity_alias_candidate_reviews
  DROP COLUMN IF EXISTS priority,
  DROP COLUMN IF EXISTS due_at,
  DROP COLUMN IF EXISTS assigned_at,
  DROP COLUMN IF EXISTS assignment_note,
  DROP COLUMN IF EXISTS assignment_status,
  DROP COLUMN IF EXISTS assigned_by,
  DROP COLUMN IF EXISTS assigned_to;
