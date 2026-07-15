-- Auth Session Scope v2 is additive. The parent index is built outside a
-- transaction so upgrades do not take a long ACCESS EXCLUSIVE lock.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS projects_id_tenant_id_key
  ON projects(id, tenant_id);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'projects'::regclass
      AND conname = 'projects_id_tenant_id_key'
  ) THEN
    ALTER TABLE projects
      ADD CONSTRAINT projects_id_tenant_id_key
      UNIQUE USING INDEX projects_id_tenant_id_key;
  END IF;
END $$;

-- A rerun after a fail-closed down migration is the forward-fix path. Re-open
-- the DB guard before any reconciliation writes, if the control table exists.
DO $$
BEGIN
  IF to_regclass('public.auth_runtime_write_controls') IS NOT NULL THEN
    UPDATE auth_runtime_write_controls
    SET writes_enabled = true,
        reason = '0030_forward_fix_reapply',
        updated_at = now()
    WHERE singleton;
  END IF;
END $$;

ALTER TABLE project_members
  ADD COLUMN IF NOT EXISTS tenant_id uuid,
  ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active',
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE project_member_invitations
  ADD COLUMN IF NOT EXISTS tenant_id uuid,
  ADD COLUMN IF NOT EXISTS audience text,
  ADD COLUMN IF NOT EXISTS allowed_surfaces text[],
  ADD COLUMN IF NOT EXISTS policy_version text,
  ADD COLUMN IF NOT EXISTS accepted_by_attempt_id uuid;

CREATE TABLE IF NOT EXISTS auth_migration_quarantine (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  source_table text NOT NULL,
  source_id uuid NOT NULL,
  conflict_type text NOT NULL,
  source_payload jsonb NOT NULL,
  quarantined_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(source_table, source_id, conflict_type)
);

INSERT INTO auth_migration_quarantine(source_table, source_id, conflict_type, source_payload)
SELECT
  'project_members',
  pm.id,
  CASE WHEN p.id IS NULL THEN 'orphan_project' ELSE 'tenant_mismatch' END,
  to_jsonb(pm)
FROM project_members pm
LEFT JOIN projects p ON p.id = pm.project_id
WHERE p.id IS NULL
   OR (pm.tenant_id IS NOT NULL AND pm.tenant_id <> p.tenant_id)
ON CONFLICT (source_table, source_id, conflict_type) DO NOTHING;

INSERT INTO auth_migration_quarantine(source_table, source_id, conflict_type, source_payload)
SELECT
  'project_member_invitations',
  pmi.id,
  CASE WHEN p.id IS NULL THEN 'orphan_project' ELSE 'tenant_mismatch' END,
  to_jsonb(pmi)
FROM project_member_invitations pmi
LEFT JOIN projects p ON p.id = pmi.project_id
WHERE p.id IS NULL
   OR (pmi.tenant_id IS NOT NULL AND pmi.tenant_id <> p.tenant_id)
ON CONFLICT (source_table, source_id, conflict_type) DO NOTHING;

DELETE FROM project_members pm
WHERE NOT EXISTS (SELECT 1 FROM projects p WHERE p.id = pm.project_id);

DELETE FROM project_member_invitations pmi
WHERE NOT EXISTS (SELECT 1 FROM projects p WHERE p.id = pmi.project_id);

UPDATE project_members pm
SET tenant_id = p.tenant_id,
    status = 'conflict',
    updated_at = now()
FROM projects p
WHERE p.id = pm.project_id
  AND pm.tenant_id IS NOT NULL
  AND pm.tenant_id <> p.tenant_id;

UPDATE project_member_invitations pmi
SET tenant_id = p.tenant_id,
    status = 'revoked',
    revoked_at = coalesce(pmi.revoked_at, now()),
    updated_at = now()
FROM projects p
WHERE p.id = pmi.project_id
  AND pmi.tenant_id IS NOT NULL
  AND pmi.tenant_id <> p.tenant_id;

UPDATE project_members pm
SET tenant_id = p.tenant_id,
    updated_at = now()
FROM projects p
WHERE p.id = pm.project_id
  AND pm.tenant_id IS NULL;

UPDATE project_member_invitations pmi
SET tenant_id = p.tenant_id,
    audience = CASE
      WHEN lower(pmi.role) IN ('viewer', 'client_viewer') THEN 'customer'
      ELSE 'admin'
    END,
    allowed_surfaces = CASE
      WHEN lower(pmi.role) IN ('viewer', 'client_viewer') THEN ARRAY['customer']::text[]
      ELSE ARRAY['admin']::text[]
    END,
    policy_version = 'auth_surface_policy_v1',
    updated_at = now()
FROM projects p
WHERE p.id = pmi.project_id
  AND (
    pmi.tenant_id IS NULL
    OR pmi.audience IS NULL
    OR pmi.allowed_surfaces IS NULL
    OR pmi.policy_version IS NULL
  );

CREATE TABLE IF NOT EXISTS auth_migration_conflicts (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  project_id uuid NOT NULL,
  conflict_type text NOT NULL,
  normalized_actor_id text NOT NULL,
  source_ids uuid[] NOT NULL DEFAULT '{}',
  source_values jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'open',
  resolution_notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  UNIQUE(project_id, conflict_type, normalized_actor_id),
  FOREIGN KEY (project_id, tenant_id)
    REFERENCES projects(id, tenant_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_auth_migration_conflicts_project_status
  ON auth_migration_conflicts(project_id, status, created_at);

CREATE TABLE IF NOT EXISTS auth_migration_reconciliation (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  migration_key text NOT NULL,
  stage text NOT NULL,
  before_count bigint NOT NULL,
  after_count bigint NOT NULL,
  before_hash text NOT NULL,
  after_hash text NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(migration_key, stage)
);

INSERT INTO auth_migration_reconciliation (
  migration_key, stage, before_count, after_count, before_hash, after_hash
)
SELECT
  '0030_auth_session_scope_v2',
  'member_tenant_backfill',
  count(*),
  count(*) FILTER (WHERE tenant_id IS NOT NULL),
  md5(coalesce(string_agg(id::text || ':' || project_id::text, ',' ORDER BY id), '')),
  md5(coalesce(string_agg(id::text || ':' || coalesce(tenant_id::text, ''), ',' ORDER BY id), ''))
FROM project_members
ON CONFLICT (migration_key, stage) DO UPDATE SET
  before_count = EXCLUDED.before_count,
  after_count = EXCLUDED.after_count,
  before_hash = EXCLUDED.before_hash,
  after_hash = EXCLUDED.after_hash,
  recorded_at = now();

INSERT INTO auth_migration_reconciliation (
  migration_key, stage, before_count, after_count, before_hash, after_hash
)
SELECT
  '0030_auth_session_scope_v2',
  'invitation_tenant_backfill',
  count(*),
  count(*) FILTER (
    WHERE tenant_id IS NOT NULL
      AND audience IS NOT NULL
      AND allowed_surfaces IS NOT NULL
      AND policy_version IS NOT NULL
  ),
  md5(coalesce(string_agg(id::text || ':' || project_id::text, ',' ORDER BY id), '')),
  md5(coalesce(string_agg(
    id::text || ':' || coalesce(tenant_id::text, '') || ':' || coalesce(audience, ''),
    ',' ORDER BY id
  ), ''))
FROM project_member_invitations
ON CONFLICT (migration_key, stage) DO UPDATE SET
  before_count = EXCLUDED.before_count,
  after_count = EXCLUDED.after_count,
  before_hash = EXCLUDED.before_hash,
  after_hash = EXCLUDED.after_hash,
  recorded_at = now();

-- The old four-column invitation constraint prevents deterministic revocation
-- when a historical revoked row already exists. The partial pending index below
-- is the authoritative uniqueness contract after cleanup.
ALTER TABLE project_member_invitations
  DROP CONSTRAINT IF EXISTS project_member_invitations_project_id_email_role_status_key;

DROP INDEX IF EXISTS idx_project_members_viewer_user_global_unique;
DROP INDEX IF EXISTS idx_project_member_invitations_viewer_email_global_unique;

-- Same normalized member with conflicting roles is reduced to one disabled
-- canonical row and queued for owner review. No role is promoted automatically.
WITH conflict_groups AS (
  SELECT
    project_id,
    (array_agg(tenant_id ORDER BY tenant_id))[1] AS tenant_id,
    lower(btrim(user_id)) AS normalized_actor_id,
    array_agg(id ORDER BY created_at, id) AS source_ids,
    jsonb_agg(jsonb_build_object('id', id, 'role', role) ORDER BY created_at, id) AS source_values
  FROM project_members
  GROUP BY project_id, lower(btrim(user_id))
  HAVING count(DISTINCT lower(role)) > 1
)
INSERT INTO auth_migration_conflicts (
  tenant_id, project_id, conflict_type, normalized_actor_id, source_ids, source_values
)
SELECT tenant_id, project_id, 'project_member_role_conflict', normalized_actor_id, source_ids, source_values
FROM conflict_groups
ON CONFLICT (project_id, conflict_type, normalized_actor_id) DO NOTHING;

WITH conflict_groups AS (
  SELECT project_id, lower(btrim(user_id)) AS normalized_actor_id
  FROM project_members
  GROUP BY project_id, lower(btrim(user_id))
  HAVING count(DISTINCT lower(role)) > 1
), ranked AS (
  SELECT
    id,
    project_id,
    lower(btrim(user_id)) AS normalized_actor_id,
    row_number() OVER (
      PARTITION BY project_id, lower(btrim(user_id))
      ORDER BY created_at, id
    ) AS row_number
  FROM project_members
)
UPDATE project_members pm
SET status = 'conflict',
    updated_at = now()
FROM ranked r
JOIN conflict_groups conflicts
  ON conflicts.project_id = r.project_id
 AND conflicts.normalized_actor_id = r.normalized_actor_id
WHERE pm.id = r.id
  AND r.row_number = 1;

WITH ranked AS (
  SELECT
    id,
    row_number() OVER (
      PARTITION BY project_id, lower(btrim(user_id))
      ORDER BY created_at, id
    ) AS row_number
  FROM project_members
)
DELETE FROM project_members pm
USING ranked r
WHERE pm.id = r.id
  AND r.row_number > 1;

-- Conflicting pending invitations are all revoked. Equivalent invitations keep
-- only the newest item that has not expired.
WITH conflict_groups AS (
  SELECT
    project_id,
    (array_agg(tenant_id ORDER BY tenant_id))[1] AS tenant_id,
    lower(btrim(email)) AS normalized_actor_id,
    array_agg(id ORDER BY created_at, id) AS source_ids,
    jsonb_agg(
      jsonb_build_object('id', id, 'role', role, 'audience', audience)
      ORDER BY created_at, id
    ) AS source_values
  FROM project_member_invitations
  WHERE status = 'pending'
  GROUP BY project_id, lower(btrim(email))
  HAVING count(DISTINCT lower(role) || ':' || audience) > 1
)
INSERT INTO auth_migration_conflicts (
  tenant_id, project_id, conflict_type, normalized_actor_id, source_ids, source_values
)
SELECT tenant_id, project_id, 'pending_invitation_policy_conflict', normalized_actor_id, source_ids, source_values
FROM conflict_groups
ON CONFLICT (project_id, conflict_type, normalized_actor_id) DO NOTHING;

WITH conflict_groups AS (
  SELECT project_id, lower(btrim(email)) AS normalized_actor_id
  FROM project_member_invitations
  WHERE status = 'pending'
  GROUP BY project_id, lower(btrim(email))
  HAVING count(DISTINCT lower(role) || ':' || audience) > 1
)
UPDATE project_member_invitations pmi
SET status = 'revoked',
    revoked_at = coalesce(revoked_at, now()),
    updated_at = now()
FROM conflict_groups conflicts
WHERE pmi.project_id = conflicts.project_id
  AND lower(btrim(pmi.email)) = conflicts.normalized_actor_id
  AND pmi.status = 'pending';

WITH ranked AS (
  SELECT
    id,
    row_number() OVER (
      PARTITION BY project_id, lower(btrim(email))
      ORDER BY created_at DESC, id DESC
    ) AS row_number
  FROM project_member_invitations
  WHERE status = 'pending'
    AND (expires_at IS NULL OR expires_at > now())
), keepers AS (
  SELECT id FROM ranked WHERE row_number = 1
)
UPDATE project_member_invitations pmi
SET status = 'revoked',
    revoked_at = coalesce(revoked_at, now()),
    updated_at = now()
WHERE pmi.status = 'pending'
  AND NOT EXISTS (SELECT 1 FROM keepers WHERE keepers.id = pmi.id);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'project_members'::regclass
      AND conname = 'project_members_project_tenant_fkey'
  ) THEN
    ALTER TABLE project_members
      ADD CONSTRAINT project_members_project_tenant_fkey
      FOREIGN KEY (project_id, tenant_id)
      REFERENCES projects(id, tenant_id) ON DELETE CASCADE NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'project_members'::regclass
      AND conname = 'project_members_tenant_id_not_null'
  ) THEN
    ALTER TABLE project_members
      ADD CONSTRAINT project_members_tenant_id_not_null
      CHECK (tenant_id IS NOT NULL) NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'project_member_invitations'::regclass
      AND conname = 'project_member_invitations_project_tenant_fkey'
  ) THEN
    ALTER TABLE project_member_invitations
      ADD CONSTRAINT project_member_invitations_project_tenant_fkey
      FOREIGN KEY (project_id, tenant_id)
      REFERENCES projects(id, tenant_id) ON DELETE CASCADE NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'project_member_invitations'::regclass
      AND conname = 'project_member_invitations_tenant_id_not_null'
  ) THEN
    ALTER TABLE project_member_invitations
      ADD CONSTRAINT project_member_invitations_tenant_id_not_null
      CHECK (tenant_id IS NOT NULL) NOT VALID;
  END IF;
END $$;

ALTER TABLE project_members VALIDATE CONSTRAINT project_members_project_tenant_fkey;
ALTER TABLE project_members VALIDATE CONSTRAINT project_members_tenant_id_not_null;
ALTER TABLE project_member_invitations VALIDATE CONSTRAINT project_member_invitations_project_tenant_fkey;
ALTER TABLE project_member_invitations VALIDATE CONSTRAINT project_member_invitations_tenant_id_not_null;

ALTER TABLE project_members ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE project_member_invitations ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE project_member_invitations ALTER COLUMN audience SET NOT NULL;
ALTER TABLE project_member_invitations ALTER COLUMN allowed_surfaces SET NOT NULL;
ALTER TABLE project_member_invitations ALTER COLUMN policy_version SET NOT NULL;

ALTER TABLE project_members DROP CONSTRAINT IF EXISTS project_members_tenant_id_not_null;
ALTER TABLE project_member_invitations DROP CONSTRAINT IF EXISTS project_member_invitations_tenant_id_not_null;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'project_members'::regclass
      AND conname = 'project_members_status_check'
  ) THEN
    ALTER TABLE project_members
      ADD CONSTRAINT project_members_status_check
      CHECK (status IN ('active', 'disabled', 'conflict'));
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'project_member_invitations'::regclass
      AND conname = 'project_member_invitations_surface_check'
  ) THEN
    ALTER TABLE project_member_invitations
      ADD CONSTRAINT project_member_invitations_surface_check
      CHECK (
        audience IN ('admin', 'customer')
        AND allowed_surfaces <@ ARRAY['admin', 'customer']::text[]
        AND cardinality(allowed_surfaces) > 0
      );
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'project_member_invitations'::regclass
      AND conname = 'project_member_invitations_audience_snapshot_check'
  ) THEN
    ALTER TABLE project_member_invitations
      ADD CONSTRAINT project_member_invitations_audience_snapshot_check
      CHECK (audience = ANY(allowed_surfaces)) NOT VALID;
  END IF;
END $$;

ALTER TABLE project_member_invitations
  VALIDATE CONSTRAINT project_member_invitations_audience_snapshot_check;

CREATE UNIQUE INDEX IF NOT EXISTS idx_project_members_project_user_ci_unique
  ON project_members(project_id, lower(btrim(user_id)));
CREATE INDEX IF NOT EXISTS idx_project_members_tenant_actor_status
  ON project_members(tenant_id, lower(btrim(user_id)), status, project_id);
CREATE INDEX IF NOT EXISTS idx_project_members_project_tenant
  ON project_members(project_id, tenant_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_project_member_invitations_pending_email_ci_unique
  ON project_member_invitations(project_id, lower(btrim(email)))
  WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_project_member_invitations_tenant_email_status
  ON project_member_invitations(tenant_id, lower(btrim(email)), status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_project_member_invitations_project_tenant
  ON project_member_invitations(project_id, tenant_id);

CREATE TABLE IF NOT EXISTS runtime_project_access_grants (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  project_id uuid NOT NULL,
  actor_id text NOT NULL,
  source_type text NOT NULL,
  source_id uuid NOT NULL,
  canonical_role text NOT NULL,
  permission_set_version text NOT NULL,
  permissions text[] NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'active',
  granted_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(tenant_id, project_id, actor_id, source_type, source_id),
  FOREIGN KEY (project_id, tenant_id)
    REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
  CHECK (source_type IN ('tenant_role')),
  CHECK (status IN ('active', 'revoked'))
);

CREATE INDEX IF NOT EXISTS idx_runtime_project_access_grants_project_tenant
  ON runtime_project_access_grants(project_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_runtime_project_access_grants_actor_tenant_status
  ON runtime_project_access_grants(lower(btrim(actor_id)), tenant_id, status, project_id);
CREATE INDEX IF NOT EXISTS idx_runtime_project_access_grants_project_actor_status
  ON runtime_project_access_grants(project_id, lower(btrim(actor_id)), status);

CREATE TABLE IF NOT EXISTS auth_invitation_redemption_attempts (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  invitation_id uuid NOT NULL REFERENCES project_member_invitations(id) ON DELETE CASCADE,
  requested_surface text NOT NULL,
  idempotency_key_hash text NOT NULL,
  request_hash text NOT NULL,
  token_fingerprint text NOT NULL,
  session_id uuid REFERENCES runtime_sessions(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'preparing',
  replay_count integer NOT NULL DEFAULT 0,
  delivery_ciphertext bytea,
  delivery_key_id text,
  delivery_nonce bytea,
  delivery_expires_at timestamptz,
  delivery_confirmed_at timestamptz,
  secret_erased_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(invitation_id, requested_surface, idempotency_key_hash),
  CHECK (requested_surface IN ('admin', 'customer')),
  CHECK (status IN ('preparing', 'succeeded', 'failed')),
  CHECK (replay_count >= 0),
  CHECK (
    (status <> 'succeeded')
    OR session_id IS NOT NULL
  )
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'auth_invitation_redemption_attempts'::regclass
      AND conname = 'auth_redemption_attempts_invitation_id_id_key'
  ) THEN
    ALTER TABLE auth_invitation_redemption_attempts
      ADD CONSTRAINT auth_redemption_attempts_invitation_id_id_key
      UNIQUE (invitation_id, id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'auth_invitation_redemption_attempts'::regclass
      AND conname = 'auth_redemption_attempts_session_id_id_key'
  ) THEN
    ALTER TABLE auth_invitation_redemption_attempts
      ADD CONSTRAINT auth_redemption_attempts_session_id_id_key
      UNIQUE (session_id, id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_auth_redemption_attempts_invitation_status
  ON auth_invitation_redemption_attempts(invitation_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_redemption_attempts_session_id
  ON auth_invitation_redemption_attempts(session_id)
  WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_auth_redemption_attempts_delivery_expiry
  ON auth_invitation_redemption_attempts(delivery_expires_at)
  WHERE delivery_ciphertext IS NOT NULL;

CREATE TABLE IF NOT EXISTS auth_preflight_rate_limits (
  bucket_key text PRIMARY KEY,
  window_started_at timestamptz NOT NULL,
  request_count integer NOT NULL,
  expires_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (request_count > 0)
);
CREATE INDEX IF NOT EXISTS idx_auth_preflight_rate_limits_expiry
  ON auth_preflight_rate_limits(expires_at);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'project_member_invitations'::regclass
      AND conname = 'project_member_invitations_accepted_attempt_fkey'
  ) THEN
    ALTER TABLE project_member_invitations
      ADD CONSTRAINT project_member_invitations_accepted_attempt_fkey
      FOREIGN KEY (accepted_by_attempt_id)
      REFERENCES auth_invitation_redemption_attempts(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'project_member_invitations'::regclass
      AND conname = 'project_member_invitations_accepted_attempt_lineage_fkey'
  ) THEN
    ALTER TABLE project_member_invitations
      ADD CONSTRAINT project_member_invitations_accepted_attempt_lineage_fkey
      FOREIGN KEY (id, accepted_by_attempt_id)
      REFERENCES auth_invitation_redemption_attempts(invitation_id, id)
      DEFERRABLE INITIALLY DEFERRED NOT VALID;
  END IF;
END $$;

ALTER TABLE project_member_invitations
  VALIDATE CONSTRAINT project_member_invitations_accepted_attempt_lineage_fkey;

ALTER TABLE runtime_sessions
  ADD COLUMN IF NOT EXISTS scope_version text NOT NULL DEFAULT 'runtime_session_scope_v1',
  ADD COLUMN IF NOT EXISTS authz_policy_version text,
  ADD COLUMN IF NOT EXISTS tenant_roles jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS project_scopes jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS redemption_attempt_id uuid;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'runtime_sessions'::regclass
      AND conname = 'runtime_sessions_redemption_attempt_fkey'
  ) THEN
    ALTER TABLE runtime_sessions
      ADD CONSTRAINT runtime_sessions_redemption_attempt_fkey
      FOREIGN KEY (redemption_attempt_id)
      REFERENCES auth_invitation_redemption_attempts(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'runtime_sessions'::regclass
      AND conname = 'runtime_sessions_scope_version_check'
  ) THEN
    ALTER TABLE runtime_sessions
      ADD CONSTRAINT runtime_sessions_scope_version_check
      CHECK (scope_version IN ('runtime_session_scope_v1', 'runtime_session_scope_v2'));
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'runtime_sessions'::regclass
      AND conname = 'runtime_sessions_redemption_attempt_id_id_key'
  ) THEN
    ALTER TABLE runtime_sessions
      ADD CONSTRAINT runtime_sessions_redemption_attempt_id_id_key
      UNIQUE (redemption_attempt_id, id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'runtime_sessions'::regclass
      AND conname = 'runtime_sessions_attempt_lineage_fkey'
  ) THEN
    ALTER TABLE runtime_sessions
      ADD CONSTRAINT runtime_sessions_attempt_lineage_fkey
      FOREIGN KEY (id, redemption_attempt_id)
      REFERENCES auth_invitation_redemption_attempts(session_id, id)
      DEFERRABLE INITIALLY DEFERRED NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'auth_invitation_redemption_attempts'::regclass
      AND conname = 'auth_redemption_attempts_session_lineage_fkey'
  ) THEN
    ALTER TABLE auth_invitation_redemption_attempts
      ADD CONSTRAINT auth_redemption_attempts_session_lineage_fkey
      FOREIGN KEY (id, session_id)
      REFERENCES runtime_sessions(redemption_attempt_id, id)
      DEFERRABLE INITIALLY DEFERRED NOT VALID;
  END IF;
END $$;

ALTER TABLE runtime_sessions VALIDATE CONSTRAINT runtime_sessions_attempt_lineage_fkey;
ALTER TABLE auth_invitation_redemption_attempts
  VALIDATE CONSTRAINT auth_redemption_attempts_session_lineage_fkey;

CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_sessions_redemption_attempt_unique
  ON runtime_sessions(redemption_attempt_id)
  WHERE redemption_attempt_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_runtime_sessions_scope_policy_status
  ON runtime_sessions(scope_version, authz_policy_version, status);

CREATE TABLE IF NOT EXISTS runtime_session_reauth_queue (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id uuid NOT NULL UNIQUE REFERENCES runtime_sessions(id) ON DELETE CASCADE,
  actor_id text NOT NULL,
  tenant_id uuid,
  reason_code text NOT NULL,
  status text NOT NULL DEFAULT 'pending',
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  CHECK (status IN ('pending', 'resolved'))
);

INSERT INTO runtime_session_reauth_queue (session_id, actor_id, tenant_id, reason_code)
SELECT id, actor_id, tenant_id, 'runtime_session_scope_v1_not_reliably_backfillable'
FROM runtime_sessions
WHERE status = 'active'
  AND scope_version = 'runtime_session_scope_v1'
ON CONFLICT (session_id) DO NOTHING;

UPDATE runtime_sessions
SET status = 'revoked',
    revoked_at = coalesce(revoked_at, now()),
    revoked_by = coalesce(revoked_by, '0030_auth_session_scope_v2'),
    revoke_reason = coalesce(revoke_reason, 'scope_v2_reauthentication_required'),
    updated_at = now()
WHERE status = 'active'
  AND scope_version = 'runtime_session_scope_v1';

CREATE TABLE IF NOT EXISTS auth_runtime_write_controls (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  writes_enabled boolean NOT NULL,
  reason text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO auth_runtime_write_controls(singleton, writes_enabled, reason)
VALUES (true, true, '0030_forward_schema_active')
ON CONFLICT (singleton) DO UPDATE SET
  writes_enabled = true,
  reason = EXCLUDED.reason,
  updated_at = now();

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'geo_rls_authz_owner') THEN
    CREATE ROLE geo_rls_authz_owner NOLOGIN BYPASSRLS;
  ELSE
    ALTER ROLE geo_rls_authz_owner NOLOGIN BYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'geo_runtime_rollback_app') THEN
    CREATE ROLE geo_runtime_rollback_app NOLOGIN;
  END IF;
END $$;

GRANT SELECT ON projects, project_members, project_member_invitations,
  tenant_members, runtime_sessions, runtime_project_access_grants,
  auth_invitation_redemption_attempts, auth_runtime_write_controls,
  runtime_session_reauth_queue
  TO geo_rls_authz_owner;
GRANT INSERT, UPDATE ON runtime_project_access_grants TO geo_rls_authz_owner;
GRANT UPDATE ON project_members TO geo_rls_authz_owner;
GRANT UPDATE ON runtime_sessions TO geo_rls_authz_owner;
GRANT INSERT, UPDATE ON runtime_session_reauth_queue TO geo_rls_authz_owner;

CREATE OR REPLACE FUNCTION geo_runtime_tenant_id()
RETURNS uuid
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog
AS $$
DECLARE
  value text;
BEGIN
  value := coalesce(
    nullif(current_setting('app.tenant_id', true), ''),
    nullif(current_setting('geo.runtime_tenant_id', true), '')
  );
  IF value IS NULL THEN
    RETURN NULL;
  END IF;
  RETURN value::uuid;
EXCEPTION WHEN invalid_text_representation THEN
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION geo_runtime_idempotency_key_hash()
RETURNS text
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $$
  SELECT nullif(current_setting('geo.runtime_idempotency_key_hash', true), '');
$$;

CREATE OR REPLACE FUNCTION geo_runtime_requested_surface()
RETURNS text
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $$
  SELECT nullif(current_setting('geo.runtime_requested_surface', true), '');
$$;

CREATE OR REPLACE FUNCTION geo_runtime_session_token_hash()
RETURNS text
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $$
  SELECT nullif(current_setting('geo.runtime_session_token_hash', true), '');
$$;

REVOKE ALL ON FUNCTION geo_runtime_session_token_hash() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION geo_runtime_session_token_hash() TO geo_runtime_app;

CREATE OR REPLACE FUNCTION geo_authz_role_has_permission(role_name text, required_permission text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
  SELECT CASE lower(role_name)
    WHEN 'super_admin' THEN true
    WHEN 'tenant_admin' THEN required_permission = ANY(ARRAY[
      'tenant.read', 'tenant.update', 'member.invite', 'member.manage',
      'project.create', 'project.read', 'project.update', 'report.read',
      'audit.read', 'cost.read'
    ]::text[])
    WHEN 'owner' THEN required_permission = ANY(ARRAY[
      'project.read', 'project.update', 'project.archive', 'member.invite',
      'member.manage',
      'prompt.import', 'connector.read', 'connector.manage',
      'connector.secret.manage', 'collection.run', 'collection.read',
      'evidence.read_summary', 'analysis.read', 'analysis.review', 'score.read',
      'score.configure', 'report.read', 'report.generate', 'report.publish',
      'report.revoke', 'report.download', 'action.manage', 'action.read',
      'retest.run', 'retest.read'
    ]::text[])
    WHEN 'admin' THEN public.geo_authz_role_has_permission('owner', required_permission)
    WHEN 'project_owner' THEN public.geo_authz_role_has_permission('owner', required_permission)
    WHEN 'analyst' THEN required_permission = ANY(ARRAY[
      'project.read', 'prompt.import', 'collection.run', 'collection.read',
      'evidence.read_summary', 'evidence.read_raw', 'analysis.read',
      'analysis.review', 'score.read', 'report.read', 'report.generate',
      'action.manage', 'action.read'
    ]::text[])
    WHEN 'reviewer' THEN required_permission = ANY(ARRAY[
      'project.read', 'evidence.read_summary', 'analysis.read',
      'analysis.review', 'score.read', 'report.read', 'report.approve',
      'report.revoke', 'content.review'
    ]::text[])
    WHEN 'knowledge_architect' THEN required_permission = ANY(ARRAY[
      'project.read', 'knowledge.read', 'knowledge.import', 'knowledge.review',
      'knowledge.read_approved', 'content.read'
    ]::text[])
    WHEN 'content_operator' THEN required_permission = ANY(ARRAY[
      'project.read', 'knowledge.read_approved', 'content.read',
      'content.generate', 'content.update', 'distribution.read',
      'distribution.create', 'distribution.update'
    ]::text[])
    WHEN 'viewer' THEN required_permission = ANY(ARRAY[
      'project.read', 'score.read', 'report.read', 'report.download',
      'action.read', 'retest.read', 'knowledge.read_approved'
    ]::text[])
    WHEN 'client_viewer' THEN public.geo_authz_role_has_permission('viewer', required_permission)
    ELSE false
  END;
$$;

CREATE OR REPLACE FUNCTION geo_authz_has_project_permission(
  row_project_id uuid,
  required_permission text DEFAULT 'project.read'
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
  SELECT
    row_project_id IS NOT NULL
    AND public.geo_runtime_actor_id() IS NOT NULL
    AND public.geo_runtime_tenant_id() IS NOT NULL
    AND (
      EXISTS (
        SELECT 1
        FROM public.project_members pm
        WHERE pm.project_id = row_project_id
          AND pm.tenant_id = public.geo_runtime_tenant_id()
          AND lower(btrim(pm.user_id)) = lower(btrim(public.geo_runtime_actor_id()))
          AND pm.status = 'active'
          AND public.geo_authz_role_has_permission(pm.role, required_permission)
      )
      OR EXISTS (
        SELECT 1
        FROM public.runtime_project_access_grants grant_row
        WHERE grant_row.project_id = row_project_id
          AND grant_row.tenant_id = public.geo_runtime_tenant_id()
          AND lower(btrim(grant_row.actor_id)) = lower(btrim(public.geo_runtime_actor_id()))
          AND grant_row.status = 'active'
          AND required_permission = ANY(grant_row.permissions)
      )
    );
$$;

ALTER FUNCTION geo_authz_role_has_permission(text, text) OWNER TO geo_rls_authz_owner;
ALTER FUNCTION geo_authz_has_project_permission(uuid, text) OWNER TO geo_rls_authz_owner;
REVOKE ALL ON FUNCTION geo_authz_role_has_permission(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_authz_has_project_permission(uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION geo_authz_role_has_permission(text, text) TO geo_runtime_app;
GRANT EXECUTE ON FUNCTION geo_authz_has_project_permission(uuid, text) TO geo_runtime_app;

CREATE OR REPLACE FUNCTION geo_authz_can_manage_tenant(row_tenant_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.tenant_members tm
    WHERE tm.tenant_id = row_tenant_id
      AND lower(btrim(tm.user_id)) = lower(btrim(public.geo_runtime_actor_id()))
      AND tm.status = 'active'
      AND lower(tm.role) IN ('super_admin', 'tenant_admin')
  );
$$;

ALTER FUNCTION geo_authz_can_manage_tenant(uuid) OWNER TO geo_rls_authz_owner;
REVOKE ALL ON FUNCTION geo_authz_can_manage_tenant(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION geo_authz_can_manage_tenant(uuid) TO geo_runtime_app;

DROP POLICY IF EXISTS tenant_members_runtime_tenant_isolation ON tenant_members;
CREATE POLICY tenant_members_runtime_tenant_isolation ON tenant_members
  USING (
    NOT geo_runtime_rls_enabled()
    OR lower(btrim(user_id)) = lower(btrim(geo_runtime_actor_id()))
    OR geo_authz_can_manage_tenant(tenant_id)
  )
  WITH CHECK (
    NOT geo_runtime_rls_enabled()
    OR geo_authz_can_manage_tenant(tenant_id)
  );

CREATE OR REPLACE FUNCTION geo_runtime_can_access_project(row_project_id uuid)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog
AS $$
DECLARE
  context_project_id uuid;
BEGIN
  IF NOT public.geo_runtime_rls_enabled() THEN
    RETURN true;
  END IF;
  IF row_project_id IS NULL THEN
    RETURN false;
  END IF;
  context_project_id := public.geo_runtime_project_id();
  IF context_project_id IS NOT NULL AND context_project_id <> row_project_id THEN
    RETURN false;
  END IF;
  IF context_project_id IS NULL
    AND cardinality(public.geo_runtime_project_ids()) > 0
    AND NOT (row_project_id = ANY(public.geo_runtime_project_ids()))
  THEN
    RETURN false;
  END IF;
  RETURN public.geo_authz_has_project_permission(row_project_id, 'project.read');
END;
$$;

DROP POLICY IF EXISTS project_member_invitations_runtime_project_isolation ON project_member_invitations;
DROP POLICY IF EXISTS project_member_invitations_select ON project_member_invitations;
DROP POLICY IF EXISTS project_member_invitations_insert_manage ON project_member_invitations;
DROP POLICY IF EXISTS project_member_invitations_update_manage ON project_member_invitations;
DROP POLICY IF EXISTS project_member_invitations_update_accept ON project_member_invitations;
DROP POLICY IF EXISTS project_member_invitations_update_recover ON project_member_invitations;
DROP POLICY IF EXISTS project_member_invitations_delete_manage ON project_member_invitations;
DROP POLICY IF EXISTS project_members_runtime_project_isolation ON project_members;
DROP POLICY IF EXISTS project_members_select ON project_members;
DROP POLICY IF EXISTS project_members_insert_manage ON project_members;
DROP POLICY IF EXISTS project_members_insert_invitation ON project_members;
DROP POLICY IF EXISTS project_members_update_manage ON project_members;
DROP POLICY IF EXISTS project_members_delete_manage ON project_members;
DROP FUNCTION IF EXISTS geo_runtime_can_accept_project_invitation(uuid);
DROP FUNCTION IF EXISTS geo_runtime_can_accept_project_invitation(uuid, uuid);

CREATE OR REPLACE FUNCTION geo_runtime_can_recover_project_invitation(row_invitation_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
  SELECT
    public.geo_runtime_invitation_token_hash() IS NOT NULL
    AND public.geo_runtime_idempotency_key_hash() IS NOT NULL
    AND public.geo_runtime_requested_surface() IN ('admin', 'customer')
    AND EXISTS (
      SELECT 1
      FROM public.project_member_invitations pmi
      JOIN public.auth_invitation_redemption_attempts attempt
        ON attempt.invitation_id = pmi.id
      WHERE pmi.id = row_invitation_id
        AND pmi.invite_token_hash = public.geo_runtime_invitation_token_hash()
        AND pmi.status = 'accepted'
        AND pmi.accepted_by_attempt_id = attempt.id
        AND attempt.idempotency_key_hash = public.geo_runtime_idempotency_key_hash()
        AND attempt.requested_surface = public.geo_runtime_requested_surface()
        AND attempt.token_fingerprint = public.geo_runtime_invitation_token_hash()
        AND attempt.status IN ('preparing', 'succeeded')
    );
$$;

CREATE OR REPLACE FUNCTION geo_runtime_can_recover_redemption_attempt(row_attempt_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
  SELECT (
    public.geo_runtime_invitation_token_hash() IS NOT NULL
    AND public.geo_runtime_idempotency_key_hash() IS NOT NULL
    AND public.geo_runtime_requested_surface() IN ('admin', 'customer')
    AND EXISTS (
      SELECT 1
      FROM public.auth_invitation_redemption_attempts attempt
      JOIN public.project_member_invitations pmi ON pmi.id = attempt.invitation_id
      WHERE attempt.id = row_attempt_id
        AND pmi.invite_token_hash = public.geo_runtime_invitation_token_hash()
        AND attempt.idempotency_key_hash = public.geo_runtime_idempotency_key_hash()
        AND attempt.requested_surface = public.geo_runtime_requested_surface()
        AND attempt.token_fingerprint = public.geo_runtime_invitation_token_hash()
        AND attempt.status = 'succeeded'
        AND pmi.status = 'accepted'
        AND pmi.accepted_by_attempt_id = attempt.id
    )
  ) OR EXISTS (
    SELECT 1
    FROM public.auth_invitation_redemption_attempts attempt
    JOIN public.runtime_sessions session_row ON session_row.id = attempt.session_id
    WHERE attempt.id = row_attempt_id
      AND session_row.status = 'active'
      AND lower(btrim(session_row.actor_id)) = lower(btrim(public.geo_runtime_actor_id()))
  );
$$;

ALTER FUNCTION geo_runtime_can_recover_project_invitation(uuid) OWNER TO geo_rls_authz_owner;
ALTER FUNCTION geo_runtime_can_recover_redemption_attempt(uuid) OWNER TO geo_rls_authz_owner;
REVOKE ALL ON FUNCTION geo_runtime_can_recover_project_invitation(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_runtime_can_recover_redemption_attempt(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION geo_runtime_can_recover_project_invitation(uuid) TO geo_runtime_app;
GRANT EXECUTE ON FUNCTION geo_runtime_can_recover_redemption_attempt(uuid) TO geo_runtime_app;

CREATE OR REPLACE FUNCTION geo_runtime_can_accept_project_invitation(
  row_project_id uuid,
  row_tenant_id uuid,
  row_user_id text,
  row_role text,
  row_status text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
  SELECT
    public.geo_runtime_rls_enabled()
    AND row_project_id IS NOT NULL
    AND row_tenant_id IS NOT NULL
    AND nullif(btrim(row_user_id), '') IS NOT NULL
    AND lower(row_status) = 'active'
    AND public.geo_runtime_invitation_token_hash() IS NOT NULL
    AND public.geo_runtime_idempotency_key_hash() IS NOT NULL
    AND public.geo_runtime_requested_surface() IN ('admin', 'customer')
    AND EXISTS (
      SELECT 1
      FROM public.project_member_invitations pmi
      JOIN public.auth_invitation_redemption_attempts attempt
        ON attempt.invitation_id = pmi.id
      WHERE pmi.project_id = row_project_id
        AND pmi.tenant_id = row_tenant_id
        AND lower(btrim(pmi.email)) = lower(btrim(row_user_id))
        AND lower(btrim(pmi.role)) = lower(btrim(row_role))
        AND pmi.status = 'pending'
        AND pmi.invite_token_hash = public.geo_runtime_invitation_token_hash()
        AND (pmi.expires_at IS NULL OR pmi.expires_at > now())
        AND attempt.status = 'preparing'
        AND attempt.idempotency_key_hash = public.geo_runtime_idempotency_key_hash()
        AND attempt.requested_surface = public.geo_runtime_requested_surface()
        AND attempt.token_fingerprint = public.geo_runtime_invitation_token_hash()
    );
$$;

CREATE OR REPLACE FUNCTION geo_runtime_can_finalize_project_invitation(
  row_invitation_id uuid,
  row_attempt_id uuid,
  row_status text,
  row_accepted_at timestamptz
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
  SELECT
    lower(row_status) = 'accepted'
    AND row_accepted_at IS NOT NULL
    AND public.geo_runtime_invitation_token_hash() IS NOT NULL
    AND public.geo_runtime_idempotency_key_hash() IS NOT NULL
    AND public.geo_runtime_requested_surface() IN ('admin', 'customer')
    AND EXISTS (
      SELECT 1
      FROM public.project_member_invitations pmi
      JOIN public.auth_invitation_redemption_attempts attempt
        ON attempt.invitation_id = pmi.id
      WHERE pmi.id = row_invitation_id
        AND pmi.invite_token_hash = public.geo_runtime_invitation_token_hash()
        AND (pmi.expires_at IS NULL OR pmi.expires_at > now())
        AND attempt.id = row_attempt_id
        AND attempt.status = 'preparing'
        AND attempt.idempotency_key_hash = public.geo_runtime_idempotency_key_hash()
        AND attempt.requested_surface = public.geo_runtime_requested_surface()
        AND attempt.token_fingerprint = public.geo_runtime_invitation_token_hash()
        AND row_accepted_at >= attempt.created_at
        AND row_accepted_at <= now() + interval '1 minute'
    );
$$;

CREATE OR REPLACE FUNCTION geo_runtime_can_insert_redeemed_session(
  row_attempt_id uuid,
  row_actor_id text,
  row_tenant_id uuid,
  row_status text,
  row_scope_version text,
  row_policy_version text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
  SELECT
    lower(row_status) = 'active'
    AND row_scope_version = 'runtime_session_scope_v2'
    AND row_policy_version = 'auth_surface_policy_v1'
    AND public.geo_runtime_invitation_token_hash() IS NOT NULL
    AND public.geo_runtime_idempotency_key_hash() IS NOT NULL
    AND public.geo_runtime_requested_surface() IN ('admin', 'customer')
    AND EXISTS (
      SELECT 1
      FROM public.auth_invitation_redemption_attempts attempt
      JOIN public.project_member_invitations pmi ON pmi.id = attempt.invitation_id
      WHERE attempt.id = row_attempt_id
        AND attempt.status = 'preparing'
        AND attempt.idempotency_key_hash = public.geo_runtime_idempotency_key_hash()
        AND attempt.requested_surface = public.geo_runtime_requested_surface()
        AND attempt.token_fingerprint = public.geo_runtime_invitation_token_hash()
        AND pmi.status = 'pending'
        AND pmi.invite_token_hash = public.geo_runtime_invitation_token_hash()
        AND lower(btrim(pmi.email)) = lower(btrim(row_actor_id))
        AND pmi.tenant_id = row_tenant_id
    );
$$;

CREATE OR REPLACE FUNCTION geo_runtime_lock_scope_members(
  requested_actor_id text,
  requested_tenant_id uuid
)
RETURNS TABLE(project_id uuid, role text)
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
  SELECT member_row.project_id, member_row.role
  FROM public.project_members member_row
  WHERE requested_tenant_id = public.geo_runtime_tenant_id()
    AND lower(btrim(requested_actor_id)) = lower(btrim(public.geo_runtime_actor_id()))
    AND member_row.tenant_id = requested_tenant_id
    AND lower(btrim(member_row.user_id)) = lower(btrim(requested_actor_id))
    AND member_row.status = 'active'
  ORDER BY member_row.project_id, member_row.created_at, member_row.id
  FOR SHARE OF member_row;
$$;

CREATE OR REPLACE FUNCTION geo_runtime_lock_invited_member(
  requested_project_id uuid,
  requested_tenant_id uuid,
  requested_actor_id text
)
RETURNS TABLE(id uuid, role text, status text)
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
  SELECT member_row.id, member_row.role, member_row.status
  FROM public.project_members member_row
  WHERE member_row.project_id = requested_project_id
    AND member_row.tenant_id = requested_tenant_id
    AND lower(btrim(member_row.user_id)) = lower(btrim(requested_actor_id))
    AND member_row.status = 'active'
    AND public.geo_runtime_can_accept_project_invitation(
      member_row.project_id,
      member_row.tenant_id,
      member_row.user_id,
      member_row.role,
      member_row.status
    )
  FOR SHARE OF member_row;
$$;

CREATE OR REPLACE FUNCTION geo_runtime_lock_scope_grants(
  requested_actor_id text,
  requested_tenant_id uuid
)
RETURNS TABLE(project_id uuid, canonical_role text, permissions text[])
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
  SELECT grant_row.project_id, grant_row.canonical_role, grant_row.permissions
  FROM public.runtime_project_access_grants grant_row
  WHERE requested_tenant_id = public.geo_runtime_tenant_id()
    AND lower(btrim(requested_actor_id)) = lower(btrim(public.geo_runtime_actor_id()))
    AND grant_row.tenant_id = requested_tenant_id
    AND lower(btrim(grant_row.actor_id)) = lower(btrim(requested_actor_id))
    AND grant_row.status = 'active'
  ORDER BY grant_row.project_id, grant_row.granted_at, grant_row.id
  FOR SHARE OF grant_row;
$$;

ALTER FUNCTION geo_runtime_can_accept_project_invitation(uuid, uuid, text, text, text)
  OWNER TO geo_rls_authz_owner;
ALTER FUNCTION geo_runtime_can_finalize_project_invitation(uuid, uuid, text, timestamptz)
  OWNER TO geo_rls_authz_owner;
ALTER FUNCTION geo_runtime_can_insert_redeemed_session(uuid, text, uuid, text, text, text)
  OWNER TO geo_rls_authz_owner;
ALTER FUNCTION geo_runtime_lock_scope_members(text, uuid) OWNER TO geo_rls_authz_owner;
ALTER FUNCTION geo_runtime_lock_invited_member(uuid, uuid, text) OWNER TO geo_rls_authz_owner;
ALTER FUNCTION geo_runtime_lock_scope_grants(text, uuid) OWNER TO geo_rls_authz_owner;
REVOKE ALL ON FUNCTION geo_runtime_can_accept_project_invitation(uuid, uuid, text, text, text)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_runtime_can_finalize_project_invitation(uuid, uuid, text, timestamptz)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_runtime_can_insert_redeemed_session(uuid, text, uuid, text, text, text)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_runtime_lock_scope_members(text, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_runtime_lock_invited_member(uuid, uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_runtime_lock_scope_grants(text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION geo_runtime_can_accept_project_invitation(uuid, uuid, text, text, text)
  TO geo_runtime_app;
GRANT EXECUTE ON FUNCTION geo_runtime_can_finalize_project_invitation(uuid, uuid, text, timestamptz)
  TO geo_runtime_app;
GRANT EXECUTE ON FUNCTION geo_runtime_can_insert_redeemed_session(uuid, text, uuid, text, text, text)
  TO geo_runtime_app;
GRANT EXECUTE ON FUNCTION geo_runtime_lock_scope_members(text, uuid) TO geo_runtime_app;
GRANT EXECUTE ON FUNCTION geo_runtime_lock_invited_member(uuid, uuid, text) TO geo_runtime_app;
GRANT EXECUTE ON FUNCTION geo_runtime_lock_scope_grants(text, uuid) TO geo_runtime_app;

CREATE OR REPLACE FUNCTION geo_guard_project_invitation_update()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
  IF session_user <> 'geo_runtime_app' THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'pending' AND NEW.status = 'accepted' THEN
    IF NEW.id IS DISTINCT FROM OLD.id
      OR NEW.project_id IS DISTINCT FROM OLD.project_id
      OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
      OR NEW.email IS DISTINCT FROM OLD.email
      OR NEW.role IS DISTINCT FROM OLD.role
      OR NEW.invite_token_hash IS DISTINCT FROM OLD.invite_token_hash
      OR NEW.invited_by IS DISTINCT FROM OLD.invited_by
      OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
      OR NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
      OR NEW.metadata IS DISTINCT FROM OLD.metadata
      OR NEW.created_at IS DISTINCT FROM OLD.created_at
      OR NEW.audience IS DISTINCT FROM OLD.audience
      OR NEW.allowed_surfaces IS DISTINCT FROM OLD.allowed_surfaces
      OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
      OR NOT public.geo_runtime_can_finalize_project_invitation(
        NEW.id, NEW.accepted_by_attempt_id, NEW.status, NEW.accepted_at
      )
    THEN
      RAISE EXCEPTION 'invitation acceptance snapshot or attempt binding is invalid' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
  END IF;
  IF public.geo_authz_has_project_permission(OLD.project_id, 'member.manage')
    AND public.geo_authz_has_project_permission(NEW.project_id, 'member.manage')
  THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'project invitation update requires member.manage' USING ERRCODE = '42501';
END;
$$;

ALTER FUNCTION geo_guard_project_invitation_update() OWNER TO geo_rls_authz_owner;
REVOKE ALL ON FUNCTION geo_guard_project_invitation_update() FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_guard_project_invitation_update() FROM geo_runtime_app;
DROP TRIGGER IF EXISTS project_member_invitations_strict_update ON project_member_invitations;
CREATE TRIGGER project_member_invitations_strict_update
BEFORE UPDATE ON project_member_invitations
FOR EACH ROW EXECUTE FUNCTION geo_guard_project_invitation_update();

CREATE POLICY project_member_invitations_select ON project_member_invitations
  FOR SELECT USING (
    geo_authz_has_project_permission(project_id, 'member.manage')
    OR (
      status = 'pending'
      AND invite_token_hash = geo_runtime_invitation_token_hash()
      AND (expires_at IS NULL OR expires_at > now())
    )
    OR (
      status = 'accepted'
      AND accepted_by_attempt_id IS NOT NULL
      AND geo_runtime_can_finalize_project_invitation(id, accepted_by_attempt_id, status, accepted_at)
    )
    OR geo_runtime_can_recover_project_invitation(id)
  );
CREATE POLICY project_member_invitations_insert_manage ON project_member_invitations
  FOR INSERT WITH CHECK (geo_authz_has_project_permission(project_id, 'member.manage'));
CREATE POLICY project_member_invitations_update_manage ON project_member_invitations
  FOR UPDATE
  USING (geo_authz_has_project_permission(project_id, 'member.manage'))
  WITH CHECK (geo_authz_has_project_permission(project_id, 'member.manage'));
CREATE POLICY project_member_invitations_update_accept ON project_member_invitations
  FOR UPDATE
  USING (
    status = 'pending'
    AND invite_token_hash = geo_runtime_invitation_token_hash()
    AND (expires_at IS NULL OR expires_at > now())
  )
  WITH CHECK (
    status = 'accepted'
    AND accepted_by_attempt_id IS NOT NULL
    AND accepted_at IS NOT NULL
    AND invite_token_hash = geo_runtime_invitation_token_hash()
  );
CREATE POLICY project_member_invitations_update_recover ON project_member_invitations
  FOR UPDATE
  USING (geo_runtime_can_recover_project_invitation(id))
  WITH CHECK (false);
CREATE POLICY project_member_invitations_delete_manage ON project_member_invitations
  FOR DELETE USING (geo_authz_has_project_permission(project_id, 'member.manage'));

CREATE POLICY project_members_select ON project_members
  FOR SELECT USING (geo_authz_has_project_permission(project_id, 'project.read'));
CREATE POLICY project_members_insert_manage ON project_members
  FOR INSERT WITH CHECK (geo_authz_has_project_permission(project_id, 'member.manage'));
CREATE POLICY project_members_insert_invitation ON project_members
  FOR INSERT WITH CHECK (
    geo_runtime_can_accept_project_invitation(project_id, tenant_id, user_id, role, status)
  );
CREATE POLICY project_members_update_manage ON project_members
  FOR UPDATE
  USING (geo_authz_has_project_permission(project_id, 'member.manage'))
  WITH CHECK (geo_authz_has_project_permission(project_id, 'member.manage'));
CREATE POLICY project_members_delete_manage ON project_members
  FOR DELETE USING (geo_authz_has_project_permission(project_id, 'member.manage'));

DROP POLICY IF EXISTS runtime_sessions_runtime_actor_isolation ON runtime_sessions;
DROP POLICY IF EXISTS runtime_sessions_select ON runtime_sessions;
DROP POLICY IF EXISTS runtime_sessions_insert_redeem ON runtime_sessions;
DROP POLICY IF EXISTS runtime_sessions_update_self ON runtime_sessions;
CREATE POLICY runtime_sessions_select ON runtime_sessions
  FOR SELECT USING (
    lower(btrim(actor_id)) = lower(btrim(geo_runtime_actor_id()))
    OR session_token_hash = geo_runtime_session_token_hash()
  );
CREATE POLICY runtime_sessions_insert_redeem ON runtime_sessions
  FOR INSERT WITH CHECK (
    geo_runtime_can_insert_redeemed_session(
      redemption_attempt_id, actor_id, tenant_id, status, scope_version, authz_policy_version
    )
  );
CREATE POLICY runtime_sessions_update_self ON runtime_sessions
  FOR UPDATE
  USING (
    lower(btrim(actor_id)) = lower(btrim(geo_runtime_actor_id()))
    OR session_token_hash = geo_runtime_session_token_hash()
  )
  WITH CHECK (
    lower(btrim(actor_id)) = lower(btrim(geo_runtime_actor_id()))
    OR session_token_hash = geo_runtime_session_token_hash()
  );

ALTER TABLE runtime_project_access_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_project_access_grants FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS runtime_project_access_grants_runtime_project_isolation ON runtime_project_access_grants;
DROP POLICY IF EXISTS runtime_project_access_grants_select ON runtime_project_access_grants;
CREATE POLICY runtime_project_access_grants_select ON runtime_project_access_grants
  FOR SELECT USING (geo_authz_has_project_permission(project_id, 'project.read'));

ALTER TABLE auth_invitation_redemption_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_invitation_redemption_attempts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS auth_redemption_attempts_runtime_isolation ON auth_invitation_redemption_attempts;
CREATE POLICY auth_redemption_attempts_runtime_isolation ON auth_invitation_redemption_attempts
  USING (
    (
      idempotency_key_hash = geo_runtime_idempotency_key_hash()
      AND requested_surface = geo_runtime_requested_surface()
      AND EXISTS (
        SELECT 1 FROM project_member_invitations pmi
        WHERE pmi.id = invitation_id
          AND pmi.invite_token_hash = geo_runtime_invitation_token_hash()
      )
    )
    OR geo_runtime_can_recover_redemption_attempt(id)
  )
  WITH CHECK (
    (
      idempotency_key_hash = geo_runtime_idempotency_key_hash()
      AND requested_surface = geo_runtime_requested_surface()
      AND EXISTS (
        SELECT 1 FROM project_member_invitations pmi
        WHERE pmi.id = invitation_id
          AND pmi.invite_token_hash = geo_runtime_invitation_token_hash()
      )
    )
    OR geo_runtime_can_recover_redemption_attempt(id)
  );

ALTER TABLE auth_preflight_rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_preflight_rate_limits FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS auth_preflight_rate_limits_shared_counter ON auth_preflight_rate_limits;
CREATE POLICY auth_preflight_rate_limits_shared_counter ON auth_preflight_rate_limits
  USING (true)
  WITH CHECK (true);

ALTER TABLE auth_migration_conflicts ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_migration_conflicts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS auth_migration_conflicts_runtime_isolation ON auth_migration_conflicts;
CREATE POLICY auth_migration_conflicts_runtime_isolation ON auth_migration_conflicts
  USING (geo_runtime_can_access_project(project_id))
  WITH CHECK (geo_runtime_can_access_project(project_id));

ALTER TABLE auth_migration_reconciliation ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_migration_reconciliation FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS auth_migration_reconciliation_maintenance_only ON auth_migration_reconciliation;
CREATE POLICY auth_migration_reconciliation_maintenance_only ON auth_migration_reconciliation
  USING (NOT geo_runtime_rls_enabled())
  WITH CHECK (NOT geo_runtime_rls_enabled());

ALTER TABLE auth_migration_quarantine ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_migration_quarantine FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS auth_migration_quarantine_maintenance_only ON auth_migration_quarantine;
CREATE POLICY auth_migration_quarantine_maintenance_only ON auth_migration_quarantine
  USING (NOT geo_runtime_rls_enabled())
  WITH CHECK (NOT geo_runtime_rls_enabled());

ALTER TABLE runtime_session_reauth_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_session_reauth_queue FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS runtime_session_reauth_queue_actor_isolation ON runtime_session_reauth_queue;
CREATE POLICY runtime_session_reauth_queue_actor_isolation ON runtime_session_reauth_queue
  USING (
    NOT geo_runtime_rls_enabled()
    OR lower(btrim(actor_id)) = lower(btrim(geo_runtime_actor_id()))
  )
  WITH CHECK (NOT geo_runtime_rls_enabled());

ALTER TABLE auth_runtime_write_controls ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_runtime_write_controls FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS auth_runtime_write_controls_read_policy ON auth_runtime_write_controls;
CREATE POLICY auth_runtime_write_controls_read_policy ON auth_runtime_write_controls
  FOR SELECT USING (true);

CREATE OR REPLACE FUNCTION geo_sync_tenant_member_project_grants()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
  canonical_role text;
  grant_permissions text[];
BEGIN
  IF TG_OP = 'DELETE' THEN
    UPDATE public.runtime_project_access_grants
    SET status = 'revoked', revoked_at = coalesce(revoked_at, now()), updated_at = now()
    WHERE source_type = 'tenant_role'
      AND source_id = OLD.id
      AND status = 'active';
    RETURN OLD;
  END IF;

  canonical_role := CASE lower(NEW.role)
    WHEN 'superadmin' THEN 'super_admin'
    WHEN 'tenantadmin' THEN 'tenant_admin'
    ELSE lower(NEW.role)
  END;
  grant_permissions := CASE canonical_role
    WHEN 'super_admin' THEN ARRAY[
      'tenant.create', 'tenant.read', 'tenant.update', 'tenant.disable',
      'member.invite', 'member.manage', 'project.create', 'project.read',
      'project.update', 'project.archive', 'report.read', 'audit.read',
      'cost.read', 'system.admin'
    ]::text[]
    WHEN 'tenant_admin' THEN ARRAY[
      'tenant.read', 'tenant.update', 'member.invite', 'member.manage',
      'project.create', 'project.read', 'project.update', 'report.read',
      'audit.read', 'cost.read'
    ]::text[]
    ELSE ARRAY[]::text[]
  END;

  UPDATE public.runtime_project_access_grants
  SET status = 'revoked', revoked_at = coalesce(revoked_at, now()), updated_at = now()
  WHERE source_type = 'tenant_role'
    AND source_id = NEW.id
    AND status = 'active';

  IF NEW.status = 'active' AND canonical_role IN ('super_admin', 'tenant_admin') THEN
    INSERT INTO public.runtime_project_access_grants (
      tenant_id, project_id, actor_id, source_type, source_id, canonical_role,
      permission_set_version, permissions, status, granted_at, revoked_at
    )
    SELECT
      NEW.tenant_id, p.id, lower(btrim(NEW.user_id)), 'tenant_role', NEW.id,
      canonical_role, 'auth_surface_policy_v1', grant_permissions,
      'active', now(), NULL
    FROM public.projects p
    WHERE p.tenant_id = NEW.tenant_id
      AND p.status <> 'archived'
    ON CONFLICT (tenant_id, project_id, actor_id, source_type, source_id)
    DO UPDATE SET
      canonical_role = EXCLUDED.canonical_role,
      permission_set_version = EXCLUDED.permission_set_version,
      permissions = EXCLUDED.permissions,
      status = 'active',
      granted_at = now(),
      revoked_at = NULL,
      updated_at = now();
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION geo_sync_project_tenant_role_grants()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
  UPDATE public.runtime_project_access_grants
  SET status = 'revoked', revoked_at = coalesce(revoked_at, now()), updated_at = now()
  WHERE project_id = NEW.id
    AND source_type = 'tenant_role'
    AND status = 'active';

  IF NEW.status <> 'archived' THEN
    INSERT INTO public.runtime_project_access_grants (
      tenant_id, project_id, actor_id, source_type, source_id, canonical_role,
      permission_set_version, permissions, status, granted_at, revoked_at
    )
    SELECT
      NEW.tenant_id, NEW.id, lower(btrim(tm.user_id)), 'tenant_role', tm.id,
      lower(tm.role), 'auth_surface_policy_v1',
      CASE lower(tm.role)
        WHEN 'super_admin' THEN ARRAY[
          'tenant.create', 'tenant.read', 'tenant.update', 'tenant.disable',
          'member.invite', 'member.manage', 'project.create', 'project.read',
          'project.update', 'project.archive', 'report.read', 'audit.read',
          'cost.read', 'system.admin'
        ]::text[]
        ELSE ARRAY[
          'tenant.read', 'tenant.update', 'member.invite', 'member.manage',
          'project.create', 'project.read', 'project.update', 'report.read',
          'audit.read', 'cost.read'
        ]::text[]
      END,
      'active', now(), NULL
    FROM public.tenant_members tm
    WHERE tm.tenant_id = NEW.tenant_id
      AND tm.status = 'active'
      AND lower(tm.role) IN ('super_admin', 'tenant_admin')
    ON CONFLICT (tenant_id, project_id, actor_id, source_type, source_id)
    DO UPDATE SET
      canonical_role = EXCLUDED.canonical_role,
      permission_set_version = EXCLUDED.permission_set_version,
      permissions = EXCLUDED.permissions,
      status = 'active',
      granted_at = now(),
      revoked_at = NULL,
      updated_at = now();
  END IF;
  RETURN NEW;
END;
$$;

ALTER FUNCTION geo_sync_tenant_member_project_grants() OWNER TO geo_rls_authz_owner;
ALTER FUNCTION geo_sync_project_tenant_role_grants() OWNER TO geo_rls_authz_owner;
REVOKE ALL ON FUNCTION geo_sync_tenant_member_project_grants() FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_sync_project_tenant_role_grants() FROM PUBLIC;

DROP TRIGGER IF EXISTS tenant_members_sync_project_grants ON tenant_members;
CREATE TRIGGER tenant_members_sync_project_grants
AFTER INSERT OR UPDATE OF role, status, tenant_id, user_id OR DELETE ON tenant_members
FOR EACH ROW EXECUTE FUNCTION geo_sync_tenant_member_project_grants();

DROP TRIGGER IF EXISTS projects_sync_tenant_role_grants ON projects;
CREATE TRIGGER projects_sync_tenant_role_grants
AFTER INSERT OR UPDATE OF status, tenant_id ON projects
FOR EACH ROW EXECUTE FUNCTION geo_sync_project_tenant_role_grants();

-- Backfill grants using the same trigger contract used by subsequent writes.
UPDATE tenant_members
SET role = role,
    updated_at = updated_at
WHERE status = 'active'
  AND lower(role) IN ('super_admin', 'tenant_admin')
  AND EXISTS (
    SELECT 1
    FROM projects project_row
    WHERE project_row.tenant_id = tenant_members.tenant_id
      AND project_row.status <> 'archived'
      AND NOT EXISTS (
        SELECT 1
        FROM runtime_project_access_grants grant_row
        WHERE grant_row.project_id = project_row.id
          AND grant_row.source_type = 'tenant_role'
          AND grant_row.source_id = tenant_members.id
          AND grant_row.status = 'active'
      )
  );

CREATE OR REPLACE FUNCTION geo_revoke_scope_v2_sessions(
  scope_actor_id text,
  scope_tenant_id uuid,
  scope_project_id uuid,
  scope_reason_code text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
  INSERT INTO public.runtime_session_reauth_queue (
    session_id, actor_id, tenant_id, reason_code, status, resolved_at
  )
  SELECT
    session_row.id,
    session_row.actor_id,
    session_row.tenant_id,
    scope_reason_code,
    'pending',
    NULL
  FROM public.runtime_sessions session_row
  WHERE session_row.status = 'active'
    AND session_row.scope_version = 'runtime_session_scope_v2'
    AND (
      scope_actor_id IS NULL
      OR lower(btrim(session_row.actor_id)) = lower(btrim(scope_actor_id))
    )
    AND (scope_tenant_id IS NULL OR session_row.tenant_id = scope_tenant_id)
    AND (
      scope_project_id IS NULL
      OR EXISTS (
        SELECT 1
        FROM pg_catalog.jsonb_array_elements(session_row.project_scopes) project_scope
        WHERE project_scope->>'project_id' = scope_project_id::text
      )
    )
  ON CONFLICT (session_id) DO UPDATE SET
    reason_code = EXCLUDED.reason_code,
    status = 'pending',
    resolved_at = NULL;

  UPDATE public.runtime_sessions session_row
  SET status = 'revoked',
      revoked_at = coalesce(session_row.revoked_at, now()),
      revoked_by = coalesce(session_row.revoked_by, 'auth_scope_change'),
      revoke_reason = coalesce(session_row.revoke_reason, scope_reason_code),
      updated_at = now()
  WHERE session_row.status = 'active'
    AND session_row.scope_version = 'runtime_session_scope_v2'
    AND (
      scope_actor_id IS NULL
      OR lower(btrim(session_row.actor_id)) = lower(btrim(scope_actor_id))
    )
    AND (scope_tenant_id IS NULL OR session_row.tenant_id = scope_tenant_id)
    AND (
      scope_project_id IS NULL
      OR EXISTS (
        SELECT 1
        FROM pg_catalog.jsonb_array_elements(session_row.project_scopes) project_scope
        WHERE project_scope->>'project_id' = scope_project_id::text
      )
    );
END;
$$;

CREATE OR REPLACE FUNCTION geo_revoke_sessions_on_project_member_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    PERFORM public.geo_revoke_scope_v2_sessions(
      OLD.user_id, OLD.tenant_id, OLD.project_id, 'project_membership_changed'
    );
  END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') AND (
    TG_OP = 'INSERT'
    OR (NEW.user_id, NEW.tenant_id, NEW.project_id, NEW.role, NEW.status)
       IS DISTINCT FROM
       (OLD.user_id, OLD.tenant_id, OLD.project_id, OLD.role, OLD.status)
  ) THEN
    PERFORM public.geo_revoke_scope_v2_sessions(
      NEW.user_id, NEW.tenant_id, NEW.project_id, 'project_membership_changed'
    );
  END IF;
  RETURN coalesce(NEW, OLD);
END;
$$;

CREATE OR REPLACE FUNCTION geo_revoke_sessions_on_tenant_member_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    PERFORM public.geo_revoke_scope_v2_sessions(
      OLD.user_id, OLD.tenant_id, NULL, 'tenant_membership_changed'
    );
  END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') AND (
    TG_OP = 'INSERT'
    OR (NEW.user_id, NEW.tenant_id, NEW.role, NEW.status)
       IS DISTINCT FROM
       (OLD.user_id, OLD.tenant_id, OLD.role, OLD.status)
  ) THEN
    PERFORM public.geo_revoke_scope_v2_sessions(
      NEW.user_id, NEW.tenant_id, NULL, 'tenant_membership_changed'
    );
  END IF;
  RETURN coalesce(NEW, OLD);
END;
$$;

CREATE OR REPLACE FUNCTION geo_revoke_sessions_on_project_grant_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    PERFORM public.geo_revoke_scope_v2_sessions(
      OLD.actor_id, OLD.tenant_id, OLD.project_id, 'project_access_grant_changed'
    );
  END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') AND (
    TG_OP = 'INSERT'
    OR (NEW.actor_id, NEW.tenant_id, NEW.project_id, NEW.canonical_role, NEW.permissions, NEW.status)
       IS DISTINCT FROM
       (OLD.actor_id, OLD.tenant_id, OLD.project_id, OLD.canonical_role, OLD.permissions, OLD.status)
  ) THEN
    PERFORM public.geo_revoke_scope_v2_sessions(
      NEW.actor_id, NEW.tenant_id, NEW.project_id, 'project_access_grant_changed'
    );
  END IF;
  RETURN coalesce(NEW, OLD);
END;
$$;

CREATE OR REPLACE FUNCTION geo_revoke_sessions_on_project_lifecycle_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
  IF TG_OP = 'DELETE' OR (
    TG_OP = 'UPDATE'
    AND (NEW.tenant_id, NEW.status) IS DISTINCT FROM (OLD.tenant_id, OLD.status)
  ) THEN
    PERFORM public.geo_revoke_scope_v2_sessions(
      NULL, OLD.tenant_id, OLD.id, 'project_lifecycle_changed'
    );
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
    PERFORM public.geo_revoke_scope_v2_sessions(
      NULL, NEW.tenant_id, NEW.id, 'project_lifecycle_changed'
    );
  END IF;
  RETURN coalesce(NEW, OLD);
END;
$$;

ALTER FUNCTION geo_revoke_scope_v2_sessions(text, uuid, uuid, text) OWNER TO geo_rls_authz_owner;
ALTER FUNCTION geo_revoke_sessions_on_project_member_change() OWNER TO geo_rls_authz_owner;
ALTER FUNCTION geo_revoke_sessions_on_tenant_member_change() OWNER TO geo_rls_authz_owner;
ALTER FUNCTION geo_revoke_sessions_on_project_grant_change() OWNER TO geo_rls_authz_owner;
ALTER FUNCTION geo_revoke_sessions_on_project_lifecycle_change() OWNER TO geo_rls_authz_owner;
REVOKE ALL ON FUNCTION geo_revoke_scope_v2_sessions(text, uuid, uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_revoke_sessions_on_project_member_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_revoke_sessions_on_tenant_member_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_revoke_sessions_on_project_grant_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_revoke_sessions_on_project_lifecycle_change() FROM PUBLIC;

DROP TRIGGER IF EXISTS project_members_revoke_scope_v2_sessions ON project_members;
CREATE TRIGGER project_members_revoke_scope_v2_sessions
AFTER INSERT OR UPDATE OF user_id, tenant_id, project_id, role, status OR DELETE ON project_members
FOR EACH ROW EXECUTE FUNCTION geo_revoke_sessions_on_project_member_change();

DROP TRIGGER IF EXISTS tenant_members_revoke_scope_v2_sessions ON tenant_members;
CREATE TRIGGER tenant_members_revoke_scope_v2_sessions
AFTER INSERT OR UPDATE OF user_id, tenant_id, role, status OR DELETE ON tenant_members
FOR EACH ROW EXECUTE FUNCTION geo_revoke_sessions_on_tenant_member_change();

DROP TRIGGER IF EXISTS runtime_grants_revoke_scope_v2_sessions ON runtime_project_access_grants;
CREATE TRIGGER runtime_grants_revoke_scope_v2_sessions
AFTER INSERT OR UPDATE OF actor_id, tenant_id, project_id, canonical_role, permissions, status OR DELETE
ON runtime_project_access_grants
FOR EACH ROW EXECUTE FUNCTION geo_revoke_sessions_on_project_grant_change();

DROP TRIGGER IF EXISTS projects_revoke_scope_v2_sessions ON projects;
CREATE TRIGGER projects_revoke_scope_v2_sessions
AFTER UPDATE OF tenant_id, status OR DELETE ON projects
FOR EACH ROW EXECUTE FUNCTION geo_revoke_sessions_on_project_lifecycle_change();

CREATE OR REPLACE FUNCTION geo_authz_canonical_role(role_name text)
RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
  SELECT CASE lower(btrim(role_name))
    WHEN 'superadmin' THEN 'super_admin'
    WHEN 'tenantadmin' THEN 'tenant_admin'
    WHEN 'owner' THEN 'project_owner'
    WHEN 'admin' THEN 'project_owner'
    WHEN 'projectowner' THEN 'project_owner'
    WHEN 'viewer' THEN 'client_viewer'
    WHEN 'clientviewer' THEN 'client_viewer'
    WHEN 'knowledgearchitect' THEN 'knowledge_architect'
    WHEN 'contentoperator' THEN 'content_operator'
    ELSE lower(btrim(role_name))
  END;
$$;

ALTER FUNCTION geo_authz_canonical_role(text) OWNER TO geo_rls_authz_owner;
REVOKE ALL ON FUNCTION geo_authz_canonical_role(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_authz_canonical_role(text) FROM geo_runtime_app;

CREATE OR REPLACE FUNCTION geo_validate_runtime_session_scope_v2()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
  projected_ids text[];
  stored_ids text[];
  projected_roles text[];
  stored_roles text[];
  projected_permissions text[];
  stored_permissions text[];
BEGIN
  IF TG_OP = 'UPDATE' AND session_user = 'geo_runtime_app' THEN
    IF NEW.id IS DISTINCT FROM OLD.id
      OR NEW.session_token_hash IS DISTINCT FROM OLD.session_token_hash
      OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
      OR NEW.actor_type IS DISTINCT FROM OLD.actor_type
      OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
      OR NEW.project_ids IS DISTINCT FROM OLD.project_ids
      OR NEW.roles IS DISTINCT FROM OLD.roles
      OR NEW.permissions IS DISTINCT FROM OLD.permissions
      OR NEW.tenant_roles IS DISTINCT FROM OLD.tenant_roles
      OR NEW.project_scopes IS DISTINCT FROM OLD.project_scopes
      OR NEW.scope_version IS DISTINCT FROM OLD.scope_version
      OR NEW.authz_policy_version IS DISTINCT FROM OLD.authz_policy_version
      OR NEW.redemption_attempt_id IS DISTINCT FROM OLD.redemption_attempt_id
      OR NEW.auth_method IS DISTINCT FROM OLD.auth_method
      OR NEW.issued_by IS DISTINCT FROM OLD.issued_by
      OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
      OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
      OR NEW.metadata IS DISTINCT FROM OLD.metadata
      OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
      RAISE EXCEPTION 'runtime session authorization snapshot is immutable' USING ERRCODE = '42501';
    END IF;
    IF NEW.status <> OLD.status
      AND NOT (OLD.status = 'active' AND NEW.status IN ('expired', 'revoked'))
    THEN
      RAISE EXCEPTION 'runtime session status transition is invalid' USING ERRCODE = '42501';
    END IF;
    IF NEW.status = 'active' AND (
      NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
      OR NEW.revoked_by IS DISTINCT FROM OLD.revoked_by
      OR NEW.revoke_reason IS DISTINCT FROM OLD.revoke_reason
    ) THEN
      RAISE EXCEPTION 'active runtime session revoke fields are immutable' USING ERRCODE = '42501';
    END IF;
    IF NEW.status = 'expired' AND (
      NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
      OR NEW.revoked_by IS DISTINCT FROM OLD.revoked_by
      OR NEW.revoke_reason IS DISTINCT FROM OLD.revoke_reason
    ) THEN
      RAISE EXCEPTION 'expired runtime session cannot set revoke fields' USING ERRCODE = '42501';
    END IF;
    IF NEW.status = 'revoked' AND (NEW.revoked_at IS NULL OR nullif(btrim(NEW.revoked_by), '') IS NULL) THEN
      RAISE EXCEPTION 'revoked runtime session requires revocation metadata' USING ERRCODE = '42501';
    END IF;
  END IF;
  IF NEW.status = 'active' AND NEW.scope_version <> 'runtime_session_scope_v2' THEN
    RAISE EXCEPTION 'active runtime sessions require runtime_session_scope_v2';
  END IF;
  IF NEW.scope_version <> 'runtime_session_scope_v2' THEN
    RETURN NEW;
  END IF;
  IF NEW.tenant_id IS NULL
    OR NEW.authz_policy_version <> 'auth_surface_policy_v1'
    OR jsonb_typeof(NEW.project_scopes) <> 'array'
    OR jsonb_typeof(NEW.project_ids) <> 'array'
  THEN
    RAISE EXCEPTION 'runtime_session_scope_v2 requires tenant, current policy, and array scopes';
  END IF;
  SELECT coalesce(array_agg(DISTINCT scope_item.scope_json->>'project_id'
                            ORDER BY scope_item.scope_json->>'project_id'), ARRAY[]::text[])
  INTO projected_ids
  FROM jsonb_array_elements(NEW.project_scopes) AS scope_item(scope_json)
  WHERE nullif(scope_item.scope_json->>'project_id', '') IS NOT NULL;
  SELECT coalesce(array_agg(DISTINCT project_item.project_id ORDER BY project_item.project_id), ARRAY[]::text[])
  INTO stored_ids
  FROM jsonb_array_elements_text(NEW.project_ids) AS project_item(project_id);
  IF projected_ids <> stored_ids THEN
    RAISE EXCEPTION 'runtime session project_ids must equal project_scopes projection';
  END IF;
  IF (SELECT count(*) FROM jsonb_array_elements(NEW.project_scopes)) <> cardinality(projected_ids) THEN
    RAISE EXCEPTION 'runtime session project_scopes must contain unique project ids';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM jsonb_array_elements(NEW.project_scopes) AS scope_item(scope_json)
    WHERE jsonb_typeof(scope_item.scope_json->'roles') IS DISTINCT FROM 'array'
       OR jsonb_typeof(scope_item.scope_json->'permissions') IS DISTINCT FROM 'array'
       OR jsonb_typeof(scope_item.scope_json->'portal_capabilities') IS DISTINCT FROM 'array'
       OR jsonb_typeof(scope_item.scope_json->'scope_sources') IS DISTINCT FROM 'array'
       OR jsonb_array_length(scope_item.scope_json->'roles') = 0
       OR jsonb_array_length(scope_item.scope_json->'scope_sources') = 0
  ) THEN
    RAISE EXCEPTION 'runtime session project scope arrays are invalid';
  END IF;
  SELECT coalesce(array_agg(DISTINCT role_value ORDER BY role_value), ARRAY[]::text[])
  INTO projected_roles
  FROM (
    SELECT public.geo_authz_canonical_role(tenant_role.role_name) AS role_value
    FROM jsonb_array_elements_text(NEW.tenant_roles) AS tenant_role(role_name)
    UNION ALL
    SELECT public.geo_authz_canonical_role(scope_role.role_name) AS role_value
    FROM jsonb_array_elements(NEW.project_scopes) AS scope_item(scope_json),
         jsonb_array_elements_text(scope_item.scope_json->'roles') AS scope_role(role_name)
  ) roles_projection;
  SELECT coalesce(array_agg(DISTINCT public.geo_authz_canonical_role(flat_role.role_name)
                            ORDER BY public.geo_authz_canonical_role(flat_role.role_name)), ARRAY[]::text[])
  INTO stored_roles
  FROM jsonb_array_elements_text(NEW.roles) AS flat_role(role_name);
  IF projected_roles <> stored_roles THEN
    RAISE EXCEPTION 'runtime session flat roles must equal the scoped role projection';
  END IF;
  SELECT coalesce(array_agg(DISTINCT scope_permission.permission_name
                            ORDER BY scope_permission.permission_name), ARRAY[]::text[])
  INTO projected_permissions
  FROM jsonb_array_elements(NEW.project_scopes) AS scope_item(scope_json),
       jsonb_array_elements_text(scope_item.scope_json->'permissions') AS scope_permission(permission_name);
  SELECT coalesce(array_agg(DISTINCT flat_permission.permission_name
                            ORDER BY flat_permission.permission_name), ARRAY[]::text[])
  INTO stored_permissions
  FROM jsonb_array_elements_text(NEW.permissions) AS flat_permission(permission_name);
  IF projected_permissions <> stored_permissions THEN
    RAISE EXCEPTION 'runtime session flat permissions must equal the scoped permission projection';
  END IF;
  IF NEW.status = 'active' AND EXISTS (
    SELECT 1
    FROM jsonb_array_elements(NEW.project_scopes) AS project_scope(scope_json)
    LEFT JOIN public.projects project_row
      ON project_row.id::text = project_scope.scope_json->>'project_id'
    WHERE project_row.id IS NULL
       OR project_row.tenant_id <> NEW.tenant_id
       OR project_row.status = 'archived'
  ) THEN
    RAISE EXCEPTION 'runtime session project scope must belong to the active session tenant';
  END IF;
  IF TG_OP = 'INSERT' AND session_user = 'geo_runtime_app' THEN
    IF NOT public.geo_runtime_can_insert_redeemed_session(
      NEW.redemption_attempt_id,
      NEW.actor_id,
      NEW.tenant_id,
      NEW.status,
      NEW.scope_version,
      NEW.authz_policy_version
    ) THEN
      RAISE EXCEPTION 'runtime session must bind the current preparing redemption attempt' USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (
      SELECT 1
      FROM public.auth_invitation_redemption_attempts attempt
      JOIN public.project_member_invitations invitation ON invitation.id = attempt.invitation_id
      WHERE attempt.id = NEW.redemption_attempt_id
        AND NEW.project_ids ? invitation.project_id::text
    ) THEN
      RAISE EXCEPTION 'runtime session scope must include the redeemed invitation project' USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
      SELECT 1
      FROM jsonb_array_elements_text(NEW.tenant_roles) AS tenant_role(role_name)
      WHERE NOT EXISTS (
        SELECT 1
        FROM public.tenant_members member_row
        WHERE member_row.tenant_id = NEW.tenant_id
          AND lower(btrim(member_row.user_id)) = lower(btrim(NEW.actor_id))
          AND member_row.status = 'active'
          AND public.geo_authz_canonical_role(member_row.role)
            = public.geo_authz_canonical_role(tenant_role.role_name)
      )
    ) THEN
      RAISE EXCEPTION 'runtime session tenant role is not backed by active membership' USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
      SELECT 1
      FROM jsonb_array_elements(NEW.project_scopes) AS scope_item(scope_json),
           jsonb_array_elements_text(scope_item.scope_json->'roles') AS scope_role(role_name)
      WHERE NOT EXISTS (
        SELECT 1
        FROM public.project_members member_row
        WHERE member_row.project_id::text = scope_item.scope_json->>'project_id'
          AND member_row.tenant_id = NEW.tenant_id
          AND lower(btrim(member_row.user_id)) = lower(btrim(NEW.actor_id))
          AND member_row.status = 'active'
          AND public.geo_authz_canonical_role(member_row.role)
            = public.geo_authz_canonical_role(scope_role.role_name)
      )
      AND NOT EXISTS (
        SELECT 1
        FROM public.runtime_project_access_grants grant_row
        WHERE grant_row.project_id::text = scope_item.scope_json->>'project_id'
          AND grant_row.tenant_id = NEW.tenant_id
          AND lower(btrim(grant_row.actor_id)) = lower(btrim(NEW.actor_id))
          AND grant_row.status = 'active'
          AND public.geo_authz_canonical_role(grant_row.canonical_role)
            = public.geo_authz_canonical_role(scope_role.role_name)
      )
    ) THEN
      RAISE EXCEPTION 'runtime session project role is not backed by active membership or grant' USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
      SELECT 1
      FROM jsonb_array_elements(NEW.project_scopes) AS scope_item(scope_json),
           jsonb_array_elements_text(scope_item.scope_json->'permissions') AS scope_permission(permission_name)
      WHERE NOT EXISTS (
        SELECT 1
        FROM public.project_members member_row
        WHERE member_row.project_id::text = scope_item.scope_json->>'project_id'
          AND member_row.tenant_id = NEW.tenant_id
          AND lower(btrim(member_row.user_id)) = lower(btrim(NEW.actor_id))
          AND member_row.status = 'active'
          AND public.geo_authz_role_has_permission(member_row.role, scope_permission.permission_name)
      )
      AND NOT EXISTS (
        SELECT 1
        FROM public.runtime_project_access_grants grant_row
        WHERE grant_row.project_id::text = scope_item.scope_json->>'project_id'
          AND grant_row.tenant_id = NEW.tenant_id
          AND lower(btrim(grant_row.actor_id)) = lower(btrim(NEW.actor_id))
          AND grant_row.status = 'active'
          AND scope_permission.permission_name = ANY(grant_row.permissions)
      )
    ) THEN
      RAISE EXCEPTION 'runtime session permission is not backed by active membership or grant' USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
      SELECT 1
      FROM jsonb_array_elements(NEW.project_scopes) AS scope_item(scope_json),
           jsonb_array_elements_text(scope_item.scope_json->'portal_capabilities') AS scope_capability(capability_name)
      WHERE NOT EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(scope_item.scope_json->'roles') AS scope_role(role_name)
        WHERE (scope_capability.capability_name = 'portal.customer.access'
               AND public.geo_authz_canonical_role(scope_role.role_name) = 'client_viewer')
           OR (scope_capability.capability_name = 'portal.admin.access'
               AND public.geo_authz_canonical_role(scope_role.role_name) <> 'client_viewer')
      )
    ) THEN
      RAISE EXCEPTION 'runtime session portal capability is not backed by a scoped role' USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
      SELECT 1
      FROM jsonb_array_elements(NEW.project_scopes) AS scope_item(scope_json),
           jsonb_array_elements_text(scope_item.scope_json->'scope_sources') AS scope_source(source_name)
      WHERE scope_source.source_name NOT IN ('direct_member', 'tenant_role')
         OR (
           scope_source.source_name = 'direct_member'
           AND NOT EXISTS (
             SELECT 1 FROM public.project_members member_row
             WHERE member_row.project_id::text = scope_item.scope_json->>'project_id'
               AND member_row.tenant_id = NEW.tenant_id
               AND lower(btrim(member_row.user_id)) = lower(btrim(NEW.actor_id))
               AND member_row.status = 'active'
           )
         )
         OR (
           scope_source.source_name = 'tenant_role'
           AND NOT EXISTS (
             SELECT 1 FROM public.runtime_project_access_grants grant_row
             WHERE grant_row.project_id::text = scope_item.scope_json->>'project_id'
               AND grant_row.tenant_id = NEW.tenant_id
               AND lower(btrim(grant_row.actor_id)) = lower(btrim(NEW.actor_id))
               AND grant_row.status = 'active'
           )
         )
    ) THEN
      RAISE EXCEPTION 'runtime session scope source is not backed by active membership or grant' USING ERRCODE = '42501';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

ALTER FUNCTION geo_validate_runtime_session_scope_v2() OWNER TO geo_rls_authz_owner;
REVOKE ALL ON FUNCTION geo_validate_runtime_session_scope_v2() FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_validate_runtime_session_scope_v2() FROM geo_runtime_app;

DROP TRIGGER IF EXISTS runtime_sessions_validate_scope_v2 ON runtime_sessions;
CREATE TRIGGER runtime_sessions_validate_scope_v2
BEFORE INSERT OR UPDATE
ON runtime_sessions
FOR EACH ROW EXECUTE FUNCTION geo_validate_runtime_session_scope_v2();

CREATE OR REPLACE FUNCTION geo_enforce_auth_writes_enabled()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.auth_runtime_write_controls
    WHERE singleton AND writes_enabled
  ) THEN
    RAISE EXCEPTION 'auth_writes_temporarily_disabled' USING ERRCODE = '42501';
  END IF;
  RETURN coalesce(NEW, OLD);
END;
$$;

ALTER FUNCTION geo_enforce_auth_writes_enabled() OWNER TO geo_rls_authz_owner;
REVOKE ALL ON FUNCTION geo_enforce_auth_writes_enabled() FROM PUBLIC;

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'project_members',
    'project_member_invitations',
    'tenant_members',
    'runtime_sessions',
    'runtime_project_access_grants',
    'auth_invitation_redemption_attempts'
  ]
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS auth_writes_enabled_guard ON public.%I', table_name);
    EXECUTE format(
      'CREATE TRIGGER auth_writes_enabled_guard BEFORE INSERT OR UPDATE OR DELETE ON public.%I '
      'FOR EACH ROW EXECUTE FUNCTION public.geo_enforce_auth_writes_enabled()',
      table_name
    );
  END LOOP;
END $$;

REVOKE INSERT, UPDATE, DELETE ON runtime_project_access_grants FROM geo_runtime_app;
GRANT SELECT ON runtime_project_access_grants TO geo_runtime_app;
REVOKE UPDATE, DELETE ON runtime_sessions FROM geo_runtime_app;
GRANT UPDATE (last_used_at, status, revoked_at, revoked_by, revoke_reason, updated_at)
  ON runtime_sessions TO geo_runtime_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON auth_invitation_redemption_attempts TO geo_runtime_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON auth_preflight_rate_limits TO geo_runtime_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON runtime_session_reauth_queue TO geo_runtime_app;
GRANT SELECT ON auth_runtime_write_controls TO geo_runtime_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON auth_migration_conflicts TO geo_runtime_app;
GRANT SELECT ON auth_migration_reconciliation TO geo_runtime_app;
GRANT SELECT ON auth_migration_quarantine TO geo_runtime_app;

GRANT USAGE ON SCHEMA public TO geo_runtime_rollback_app;
GRANT SELECT ON projects, tenants, auth_runtime_write_controls TO geo_runtime_rollback_app;
REVOKE INSERT, UPDATE, DELETE ON project_members FROM geo_runtime_rollback_app;
REVOKE INSERT, UPDATE, DELETE ON project_member_invitations FROM geo_runtime_rollback_app;
REVOKE INSERT, UPDATE, DELETE ON tenant_members FROM geo_runtime_rollback_app;
REVOKE INSERT, UPDATE, DELETE ON runtime_sessions FROM geo_runtime_rollback_app;
REVOKE INSERT, UPDATE, DELETE ON runtime_project_access_grants FROM geo_runtime_rollback_app;
REVOKE INSERT, UPDATE, DELETE ON auth_invitation_redemption_attempts FROM geo_runtime_rollback_app;
