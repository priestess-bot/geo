UPDATE projects
SET status = 'paused'
WHERE status = 'configured';

CREATE TABLE IF NOT EXISTS score_weight_profiles (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  profile_key text NOT NULL UNIQUE,
  name text NOT NULL,
  description text,
  base_formula_version text NOT NULL DEFAULT 'au_visibility_v1',
  weights jsonb NOT NULL,
  scope text NOT NULL DEFAULT 'global',
  is_system boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'active',
  created_by text NOT NULL,
  updated_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (profile_key <> ''),
  CHECK (name <> ''),
  CHECK (scope IN ('global')),
  CHECK (status IN ('active', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_score_weight_profiles_status
  ON score_weight_profiles(status, is_system, updated_at DESC);

ALTER TABLE score_weight_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE score_weight_profiles FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS score_weight_profiles_runtime_read ON score_weight_profiles;
CREATE POLICY score_weight_profiles_runtime_read ON score_weight_profiles
  USING (true)
  WITH CHECK (true);
