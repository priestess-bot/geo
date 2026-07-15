CREATE TABLE IF NOT EXISTS connector_secret_refs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  provider text NOT NULL,
  purpose text NOT NULL DEFAULT 'api_key',
  secret_ref text NOT NULL UNIQUE,
  encrypted_secret text NOT NULL,
  encryption_version text NOT NULL,
  key_hint text NOT NULL,
  secret_hash text NOT NULL,
  masked_value text NOT NULL,
  status text NOT NULL DEFAULT 'active',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL,
  rotated_by text,
  deleted_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  rotated_at timestamptz,
  deleted_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (provider <> ''),
  CHECK (purpose <> ''),
  CHECK (status IN ('active', 'rotated', 'deleted'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_connector_secret_refs_active_unique
  ON connector_secret_refs(project_id, provider, purpose)
  WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_connector_secret_refs_project_provider
  ON connector_secret_refs(project_id, provider, status);

ALTER TABLE connector_secret_refs ENABLE ROW LEVEL SECURITY;
ALTER TABLE connector_secret_refs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS connector_secret_refs_runtime_project_isolation ON connector_secret_refs;
CREATE POLICY connector_secret_refs_runtime_project_isolation ON connector_secret_refs
  USING (geo_runtime_can_access_project(project_id))
  WITH CHECK (geo_runtime_can_access_project(project_id));
