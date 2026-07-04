ALTER TABLE evidence_assets
  ADD COLUMN IF NOT EXISTS tenant_id uuid,
  ADD COLUMN IF NOT EXISTS project_id uuid,
  ADD COLUMN IF NOT EXISTS storage_backend text NOT NULL DEFAULT 'external_url',
  ADD COLUMN IF NOT EXISTS storage_key text,
  ADD COLUMN IF NOT EXISTS bucket text,
  ADD COLUMN IF NOT EXISTS content_type text,
  ADD COLUMN IF NOT EXISTS byte_size bigint,
  ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS visibility text NOT NULL DEFAULT 'internal',
  ADD COLUMN IF NOT EXISTS created_by text NOT NULL DEFAULT 'system',
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

UPDATE evidence_assets ea
SET project_id = ar.project_id
FROM answer_runs ar
WHERE ea.answer_run_id = ar.id AND ea.project_id IS NULL;

UPDATE evidence_assets ea
SET tenant_id = p.tenant_id
FROM projects p
WHERE ea.project_id = p.id AND ea.tenant_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_evidence_assets_project_scope
  ON evidence_assets(project_id, asset_type, visibility, created_at);

CREATE INDEX IF NOT EXISTS idx_evidence_assets_tenant_scope
  ON evidence_assets(tenant_id, project_id, created_at);

CREATE INDEX IF NOT EXISTS idx_evidence_assets_content_hash
  ON evidence_assets(content_hash);

CREATE INDEX IF NOT EXISTS idx_evidence_links_target
  ON evidence_links(project_id, target_type, target_id);
