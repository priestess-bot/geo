CREATE TABLE IF NOT EXISTS runtime_sessions (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_token_hash text NOT NULL UNIQUE,
  actor_id text NOT NULL,
  actor_type text NOT NULL DEFAULT 'user',
  tenant_id uuid,
  project_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  roles jsonb NOT NULL DEFAULT '[]'::jsonb,
  permissions jsonb NOT NULL DEFAULT '[]'::jsonb,
  auth_method text NOT NULL DEFAULT 'session',
  status text NOT NULL DEFAULT 'active',
  issued_by text NOT NULL DEFAULT 'runtime-auth',
  issued_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  last_used_at timestamptz,
  revoked_at timestamptz,
  revoked_by text,
  revoke_reason text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (actor_type IN ('user', 'system', 'service')),
  CHECK (auth_method IN ('session')),
  CHECK (status IN ('active', 'expired', 'revoked'))
);

CREATE INDEX IF NOT EXISTS idx_runtime_sessions_actor_status
  ON runtime_sessions(lower(actor_id), status);
CREATE INDEX IF NOT EXISTS idx_runtime_sessions_tenant_status
  ON runtime_sessions(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_runtime_sessions_expires_at
  ON runtime_sessions(expires_at);

ALTER TABLE runtime_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_sessions FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS runtime_sessions_runtime_actor_isolation ON runtime_sessions;
CREATE POLICY runtime_sessions_runtime_actor_isolation ON runtime_sessions
  USING (
    NOT geno_runtime_rls_enabled()
    OR actor_id = nullif(current_setting('geno.runtime_actor_id', true), '')
  )
  WITH CHECK (
    NOT geno_runtime_rls_enabled()
    OR actor_id = nullif(current_setting('geno.runtime_actor_id', true), '')
  );
