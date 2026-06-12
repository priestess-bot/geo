CREATE TABLE IF NOT EXISTS entity_alias_candidate_reviews (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  candidate_id text NOT NULL,
  entity_id uuid NOT NULL,
  entity_kind text NOT NULL,
  alias text NOT NULL,
  alias_type text NOT NULL,
  source text,
  confidence numeric(6,4),
  decision text NOT NULL,
  reviewed_by text,
  reason text,
  notes text,
  evidence_answer_run_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  evidence_urls text[] NOT NULL DEFAULT ARRAY[]::text[],
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, candidate_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_alias_candidate_reviews_project
  ON entity_alias_candidate_reviews(project_id, decision, updated_at);

CREATE INDEX IF NOT EXISTS idx_entity_alias_candidate_reviews_entity
  ON entity_alias_candidate_reviews(entity_kind, entity_id, alias_type, alias);
