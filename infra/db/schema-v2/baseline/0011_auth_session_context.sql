-- Session-backed read-only authorization context for Schema v2.
-- Invitation redemption and all sensitive runtime writes are deferred to 0012.

DO $api_role$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'geno_v2_api_login'
    ) THEN
        CREATE ROLE geno_v2_api_login
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
            NOREPLICATION NOBYPASSRLS;
    ELSE
        ALTER ROLE geno_v2_api_login
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
            NOREPLICATION NOBYPASSRLS;
    END IF;
    ALTER ROLE geno_v2_api_login PASSWORD NULL;
    ALTER ROLE geno_v2_api_login RESET ALL;
    ALTER ROLE geno_v2_api_login IN DATABASE geno_v2 RESET ALL;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        WHERE (
                membership.roleid = (
                    SELECT oid FROM pg_catalog.pg_roles
                    WHERE rolname = 'geno_v2_api_login'
                )
                OR membership.member = (
                    SELECT oid FROM pg_catalog.pg_roles
                    WHERE rolname = 'geno_v2_api_login'
                )
              )
          AND NOT (
                membership.roleid = (
                    SELECT oid FROM pg_catalog.pg_roles
                    WHERE rolname = 'geno_v2_runtime'
                )
                AND membership.member = (
                    SELECT oid FROM pg_catalog.pg_roles
                    WHERE rolname = 'geno_v2_api_login'
                )
                AND membership.inherit_option = false
                AND membership.set_option = true
                AND membership.admin_option = false
              )
    ) THEN
        RAISE EXCEPTION 'Schema v2 API role contains an unauthorized membership';
    END IF;
END
$api_role$;

GRANT geno_v2_runtime TO geno_v2_api_login
    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;

REVOKE CONNECT, TEMPORARY ON DATABASE geno_v2 FROM PUBLIC;
GRANT CONNECT ON DATABASE geno_v2 TO geno_v2_api_login;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

CREATE TABLE project_member_invitations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    email text NOT NULL,
    role text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    invite_token_hash text NOT NULL UNIQUE,
    audience text NOT NULL,
    allowed_surfaces text[] NOT NULL,
    policy_version text NOT NULL DEFAULT 'auth_surface_policy_v1',
    invited_by text NOT NULL,
    accepted_by_attempt_id uuid,
    expires_at timestamptz NOT NULL,
    accepted_at timestamptz,
    revoked_at timestamptz,
    revoke_reason text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT project_invitations_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT project_invitations_id_project_tenant_unique
        UNIQUE (id, project_id, tenant_id),
    CONSTRAINT project_invitations_email_canonical
        CHECK (email = lower(btrim(email)) AND email <> ''),
    CONSTRAINT project_invitations_role_canonical
        CHECK (role IN (
            'project_owner', 'analyst', 'reviewer', 'knowledge_architect',
            'content_operator', 'client_viewer'
        )),
    CONSTRAINT project_invitations_status_canonical
        CHECK (status IN ('pending', 'accepted', 'revoked', 'expired')),
    CONSTRAINT project_invitations_token_hash_sha256
        CHECK (invite_token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT project_invitations_surface_snapshot
        CHECK (
            (role = 'client_viewer'
                AND audience = 'customer'
                AND allowed_surfaces = ARRAY['customer']::text[])
            OR (role <> 'client_viewer'
                AND audience = 'admin'
                AND allowed_surfaces = ARRAY['admin']::text[])
        ),
    CONSTRAINT project_invitations_policy_version_v1
        CHECK (policy_version = 'auth_surface_policy_v1'),
    CONSTRAINT project_invitations_invited_by_nonempty CHECK (btrim(invited_by) <> ''),
    CONSTRAINT project_invitations_metadata_object
        CHECK (jsonb_typeof(metadata) = 'object'),
    CONSTRAINT project_invitations_expiry_order CHECK (expires_at > created_at),
    CONSTRAINT project_invitations_acceptance_order
        CHECK (accepted_at IS NULL OR (
            accepted_at >= created_at AND accepted_at <= expires_at
        )),
    CONSTRAINT project_invitations_revocation_order
        CHECK (revoked_at IS NULL OR revoked_at >= created_at),
    CONSTRAINT project_invitations_lifecycle_coherent
        CHECK (
            (status = 'pending'
                AND accepted_by_attempt_id IS NULL
                AND accepted_at IS NULL
                AND revoked_at IS NULL
                AND revoke_reason IS NULL)
            OR (status = 'accepted'
                AND accepted_by_attempt_id IS NOT NULL
                AND accepted_at IS NOT NULL
                AND revoked_at IS NULL
                AND revoke_reason IS NULL)
            OR (status IN ('revoked', 'expired')
                AND accepted_by_attempt_id IS NULL
                AND accepted_at IS NULL
                AND revoked_at IS NOT NULL
                AND btrim(revoke_reason) <> '')
        )
);

CREATE TABLE runtime_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_token_hash text NOT NULL UNIQUE,
    actor_id text NOT NULL,
    actor_type text NOT NULL DEFAULT 'user',
    tenant_id uuid NOT NULL,
    project_ids jsonb NOT NULL,
    roles jsonb NOT NULL,
    permissions jsonb NOT NULL,
    tenant_roles jsonb NOT NULL,
    project_scopes jsonb NOT NULL,
    scope_version text NOT NULL DEFAULT 'runtime_session_scope_v2',
    authz_policy_version text NOT NULL DEFAULT 'auth_surface_policy_v1',
    redemption_attempt_id uuid NOT NULL UNIQUE,
    auth_method text NOT NULL DEFAULT 'session',
    status text NOT NULL DEFAULT 'active',
    issued_by text NOT NULL,
    issued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    revoked_by text,
    revoke_reason text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT runtime_sessions_tenant_fkey
        FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT runtime_sessions_id_tenant_actor_unique UNIQUE (id, tenant_id, actor_id),
    CONSTRAINT runtime_sessions_id_tenant_unique UNIQUE (id, tenant_id),
    CONSTRAINT runtime_sessions_redemption_id_pair_unique
        UNIQUE (redemption_attempt_id, id),
    CONSTRAINT runtime_sessions_token_hash_sha256
        CHECK (session_token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT runtime_sessions_actor_id_canonical
        CHECK (actor_id = lower(btrim(actor_id)) AND actor_id <> ''),
    CONSTRAINT runtime_sessions_actor_type_user CHECK (actor_type = 'user'),
    CONSTRAINT runtime_sessions_scope_version_v2
        CHECK (scope_version = 'runtime_session_scope_v2'),
    CONSTRAINT runtime_sessions_authz_policy_v1
        CHECK (authz_policy_version = 'auth_surface_policy_v1'),
    CONSTRAINT runtime_sessions_auth_method_session CHECK (auth_method = 'session'),
    CONSTRAINT runtime_sessions_status_canonical
        CHECK (status IN ('active', 'expired', 'revoked')),
    CONSTRAINT runtime_sessions_issued_by_nonempty CHECK (btrim(issued_by) <> ''),
    CONSTRAINT runtime_sessions_expiry_order CHECK (expires_at > issued_at),
    CONSTRAINT runtime_sessions_metadata_object CHECK (jsonb_typeof(metadata) = 'object'),
    CONSTRAINT runtime_sessions_terminal_state_coherent
        CHECK (
            (status IN ('active', 'expired')
                AND revoked_at IS NULL
                AND revoked_by IS NULL
                AND revoke_reason IS NULL)
            OR (status = 'revoked'
                AND revoked_at IS NOT NULL
                AND btrim(revoked_by) <> ''
                AND btrim(revoke_reason) <> '')
        )
);

CREATE TABLE auth_invitation_redemption_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    invitation_id uuid NOT NULL,
    requested_surface text NOT NULL,
    idempotency_key_hash text NOT NULL,
    request_hash text NOT NULL,
    token_fingerprint text NOT NULL,
    session_id uuid,
    status text NOT NULL DEFAULT 'preparing',
    replay_count integer NOT NULL DEFAULT 0,
    delivery_ciphertext bytea,
    delivery_key_id text,
    delivery_nonce bytea,
    delivery_expires_at timestamptz,
    delivery_confirmed_at timestamptz,
    secret_erased_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT auth_attempts_invitation_scope_fkey
        FOREIGN KEY (invitation_id, project_id, tenant_id)
        REFERENCES project_member_invitations(id, project_id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT auth_attempts_invitation_id_pair_unique UNIQUE (invitation_id, id),
    CONSTRAINT auth_attempts_id_tenant_unique UNIQUE (id, tenant_id),
    CONSTRAINT auth_attempts_session_id_pair_unique UNIQUE (session_id, id),
    CONSTRAINT auth_attempts_idempotency_unique
        UNIQUE (invitation_id, requested_surface, idempotency_key_hash),
    CONSTRAINT auth_attempts_requested_surface_canonical
        CHECK (requested_surface IN ('admin', 'customer')),
    CONSTRAINT auth_attempts_idempotency_hash_sha256
        CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT auth_attempts_request_hash_sha256
        CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT auth_attempts_token_fingerprint_sha256
        CHECK (token_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT auth_attempts_status_canonical
        CHECK (status IN ('preparing', 'succeeded', 'failed')),
    CONSTRAINT auth_attempts_replay_count_nonnegative CHECK (replay_count >= 0),
    CONSTRAINT auth_attempts_session_state_coherent
        CHECK ((status = 'succeeded' AND session_id IS NOT NULL)
            OR (status <> 'succeeded' AND session_id IS NULL)),
    CONSTRAINT auth_attempts_delivery_secret_coherent
        CHECK (
            (delivery_ciphertext IS NULL
                AND delivery_key_id IS NULL
                AND delivery_nonce IS NULL
                AND delivery_expires_at IS NULL)
            OR (delivery_ciphertext IS NOT NULL
                AND btrim(delivery_key_id) <> ''
                AND delivery_nonce IS NOT NULL
                AND delivery_expires_at IS NOT NULL
                AND secret_erased_at IS NULL)
        ),
    CONSTRAINT auth_attempts_delivery_confirmation_order
        CHECK (delivery_confirmed_at IS NULL OR delivery_confirmed_at >= created_at),
    CONSTRAINT auth_attempts_secret_erasure_order
        CHECK (secret_erased_at IS NULL OR secret_erased_at >= created_at)
);

ALTER TABLE project_member_invitations
    ADD CONSTRAINT project_invitations_accepted_attempt_fkey
    FOREIGN KEY (accepted_by_attempt_id, tenant_id)
    REFERENCES auth_invitation_redemption_attempts(id, tenant_id)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE project_member_invitations
    ADD CONSTRAINT project_invitations_attempt_lineage_fkey
    FOREIGN KEY (id, accepted_by_attempt_id)
    REFERENCES auth_invitation_redemption_attempts(invitation_id, id)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE runtime_sessions
    ADD CONSTRAINT runtime_sessions_redemption_attempt_fkey
    FOREIGN KEY (redemption_attempt_id, tenant_id)
    REFERENCES auth_invitation_redemption_attempts(id, tenant_id)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE runtime_sessions
    ADD CONSTRAINT runtime_sessions_attempt_lineage_fkey
    FOREIGN KEY (id, redemption_attempt_id)
    REFERENCES auth_invitation_redemption_attempts(session_id, id)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE auth_invitation_redemption_attempts
    ADD CONSTRAINT auth_attempts_session_fkey
    FOREIGN KEY (session_id, tenant_id) REFERENCES runtime_sessions(id, tenant_id)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE auth_invitation_redemption_attempts
    ADD CONSTRAINT auth_attempts_session_lineage_fkey
    FOREIGN KEY (id, session_id)
    REFERENCES runtime_sessions(redemption_attempt_id, id)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE auth_preflight_rate_limits (
    bucket_key text PRIMARY KEY,
    window_started_at timestamptz NOT NULL,
    request_count integer NOT NULL,
    expires_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT auth_preflight_bucket_key_nonempty
        CHECK (btrim(bucket_key) <> '' AND length(bucket_key) <= 256),
    CONSTRAINT auth_preflight_request_count_positive CHECK (request_count > 0),
    CONSTRAINT auth_preflight_window_order CHECK (expires_at > window_started_at)
);

CREATE TABLE runtime_session_reauth_queue (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL UNIQUE,
    tenant_id uuid NOT NULL,
    actor_id text NOT NULL,
    reason_code text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    resolved_at timestamptz,
    CONSTRAINT runtime_reauth_session_identity_fkey
        FOREIGN KEY (session_id, tenant_id, actor_id)
        REFERENCES runtime_sessions(id, tenant_id, actor_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT runtime_reauth_actor_id_canonical
        CHECK (actor_id = lower(btrim(actor_id)) AND actor_id <> ''),
    CONSTRAINT runtime_reauth_reason_code_nonempty CHECK (btrim(reason_code) <> ''),
    CONSTRAINT runtime_reauth_status_canonical CHECK (status IN ('pending', 'resolved')),
    CONSTRAINT runtime_reauth_resolution_coherent
        CHECK ((status = 'pending' AND resolved_at IS NULL)
            OR (status = 'resolved' AND resolved_at IS NOT NULL))
);

CREATE TABLE auth_runtime_write_controls (
    singleton boolean PRIMARY KEY DEFAULT true,
    writes_enabled boolean NOT NULL DEFAULT false,
    reason text NOT NULL DEFAULT 'sealed_until_0012_sensitive_auth_commands',
    updated_by text NOT NULL DEFAULT 'schema-v2-baseline',
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT auth_write_controls_singleton CHECK (singleton),
    CONSTRAINT auth_write_controls_reason_nonempty CHECK (btrim(reason) <> ''),
    CONSTRAINT auth_write_controls_updated_by_nonempty CHECK (btrim(updated_by) <> '')
);

INSERT INTO auth_runtime_write_controls (singleton, writes_enabled)
VALUES (true, false);

CREATE UNIQUE INDEX project_invitations_pending_email_unique
    ON project_member_invitations (project_id, email)
    WHERE status = 'pending';
CREATE INDEX project_invitations_project_status_idx
    ON project_member_invitations (project_id, tenant_id, status, created_at DESC);
CREATE INDEX project_invitations_expiry_idx
    ON project_member_invitations (expires_at) WHERE status = 'pending';
CREATE INDEX runtime_sessions_actor_status_idx
    ON runtime_sessions (actor_id, tenant_id, status, expires_at);
CREATE INDEX runtime_sessions_tenant_status_idx
    ON runtime_sessions (tenant_id, status, expires_at);
CREATE INDEX runtime_sessions_expiry_idx
    ON runtime_sessions (expires_at) WHERE status = 'active';
CREATE INDEX auth_attempts_invitation_status_idx
    ON auth_invitation_redemption_attempts (invitation_id, status, created_at DESC);
CREATE INDEX auth_attempts_session_idx
    ON auth_invitation_redemption_attempts (session_id) WHERE session_id IS NOT NULL;
CREATE INDEX auth_attempts_delivery_expiry_idx
    ON auth_invitation_redemption_attempts (delivery_expires_at)
    WHERE delivery_ciphertext IS NOT NULL;
CREATE INDEX auth_preflight_expiry_idx ON auth_preflight_rate_limits (expires_at);
CREATE INDEX runtime_reauth_pending_idx
    ON runtime_session_reauth_queue (created_at) WHERE status = 'pending';

CREATE FUNCTION geno_v2_jsonb_text_set(value jsonb)
RETURNS text[]
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog
AS $jsonb_text_set$
    SELECT coalesce(array_agg(DISTINCT item ORDER BY item), ARRAY[]::text[])
    FROM jsonb_array_elements_text(value) AS array_item(item);
$jsonb_text_set$;

CREATE FUNCTION geno_v2_validate_auth_redemption_lineage()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $validate_auth_lineage$
DECLARE
    lineage_attempt_id uuid;
    invitation_row public.project_member_invitations%ROWTYPE;
    attempt_row public.auth_invitation_redemption_attempts%ROWTYPE;
    session_row public.runtime_sessions%ROWTYPE;
    chain_required boolean := false;
BEGIN
    -- Deferred triggers must validate the final row state, not their queued NEW snapshot.
    IF TG_TABLE_NAME = 'project_member_invitations' THEN
        SELECT * INTO invitation_row
        FROM public.project_member_invitations
        WHERE id = NEW.id;
        IF NOT FOUND THEN
            RETURN NULL;
        END IF;
        lineage_attempt_id := invitation_row.accepted_by_attempt_id;
        IF lineage_attempt_id IS NULL THEN
            SELECT id INTO lineage_attempt_id
            FROM public.auth_invitation_redemption_attempts
            WHERE invitation_id = invitation_row.id AND status = 'succeeded'
            ORDER BY created_at, id
            LIMIT 1;
        END IF;
        IF lineage_attempt_id IS NULL THEN
            RETURN NULL;
        END IF;
    ELSIF TG_TABLE_NAME = 'auth_invitation_redemption_attempts' THEN
        lineage_attempt_id := NEW.id;
    ELSIF TG_TABLE_NAME = 'runtime_sessions' THEN
        SELECT redemption_attempt_id INTO lineage_attempt_id
        FROM public.runtime_sessions
        WHERE id = NEW.id;
        IF lineage_attempt_id IS NULL THEN
            RETURN NULL;
        END IF;
        chain_required := true;
    ELSE
        RAISE EXCEPTION 'unsupported auth lineage trigger table'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO attempt_row
    FROM public.auth_invitation_redemption_attempts
    WHERE id = lineage_attempt_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'auth lineage redemption attempt is missing'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO invitation_row
    FROM public.project_member_invitations
    WHERE id = attempt_row.invitation_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'auth lineage invitation is missing'
            USING ERRCODE = '23514';
    END IF;

    IF attempt_row.tenant_id <> invitation_row.tenant_id
       OR attempt_row.project_id <> invitation_row.project_id THEN
        RAISE EXCEPTION 'auth lineage invitation and attempt scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF attempt_row.token_fingerprint <> invitation_row.invite_token_hash THEN
        RAISE EXCEPTION 'auth lineage invitation token fingerprint mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF attempt_row.requested_surface <> invitation_row.audience
       OR NOT (attempt_row.requested_surface = ANY(invitation_row.allowed_surfaces)) THEN
        RAISE EXCEPTION 'auth lineage requested surface is not allowed'
            USING ERRCODE = '23514';
    END IF;

    chain_required := chain_required
        OR attempt_row.status = 'succeeded'
        OR invitation_row.accepted_by_attempt_id = attempt_row.id;
    IF NOT chain_required THEN
        RETURN NULL;
    END IF;
    IF invitation_row.status <> 'accepted'
       OR invitation_row.accepted_by_attempt_id <> attempt_row.id
       OR attempt_row.status <> 'succeeded'
       OR attempt_row.session_id IS NULL THEN
        RAISE EXCEPTION 'auth lineage accepted and succeeded state is not exact'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO session_row
    FROM public.runtime_sessions
    WHERE id = attempt_row.session_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'auth lineage runtime session is missing'
            USING ERRCODE = '23514';
    END IF;
    IF session_row.redemption_attempt_id <> attempt_row.id
       OR session_row.tenant_id <> attempt_row.tenant_id
       OR session_row.tenant_id <> invitation_row.tenant_id
       OR session_row.actor_id <> invitation_row.email
       OR session_row.authz_policy_version <> invitation_row.policy_version THEN
        RAISE EXCEPTION 'auth lineage session identity or policy mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF invitation_row.created_at > attempt_row.created_at
       OR attempt_row.created_at > invitation_row.accepted_at
       OR invitation_row.accepted_at > session_row.issued_at
       OR session_row.issued_at > invitation_row.expires_at
       OR session_row.issued_at >= session_row.expires_at THEN
        RAISE EXCEPTION 'auth lineage issuance timeline is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NOT (session_row.project_ids ? attempt_row.project_id::text)
       OR NOT EXISTS (
            SELECT 1
            FROM jsonb_array_elements(session_row.project_scopes) AS scope(value)
            WHERE scope.value->>'project_id' = attempt_row.project_id::text
              AND scope.value->'roles' ? invitation_row.role
              AND scope.value->'portal_capabilities'
                    ? ('portal.' || attempt_row.requested_surface || '.access')
       ) THEN
        RAISE EXCEPTION 'auth lineage project or portal scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$validate_auth_lineage$;

CREATE FUNCTION geno_v2_validate_runtime_session_snapshot()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $validate_session$
DECLARE
    scope_item jsonb;
    scope_project_id uuid;
    declared_project_ids text[];
    actual_project_ids text[];
    projected_project_ids text[];
    declared_tenant_roles text[];
    actual_tenant_roles text[];
    declared_roles text[];
    actual_roles text[];
    declared_permissions text[];
    actual_permissions text[];
    declared_capabilities text[];
    actual_capabilities text[];
    declared_sources text[];
    actual_sources text[];
    aggregate_roles text[] := ARRAY[]::text[];
    aggregate_permissions text[] := ARRAY[]::text[];
BEGIN
    IF NEW.status <> 'active' THEN
        RAISE EXCEPTION 'runtime session must be inserted active' USING ERRCODE = '23514';
    END IF;
    IF jsonb_typeof(NEW.project_ids) <> 'array'
       OR jsonb_typeof(NEW.roles) <> 'array'
       OR jsonb_typeof(NEW.permissions) <> 'array'
       OR jsonb_typeof(NEW.tenant_roles) <> 'array'
       OR jsonb_typeof(NEW.project_scopes) <> 'array' THEN
        RAISE EXCEPTION 'runtime session snapshots must be JSON arrays'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(NEW.project_ids) AS item(value)
        WHERE jsonb_typeof(item.value) <> 'string'
    ) OR EXISTS (
        SELECT 1
        FROM jsonb_array_elements(NEW.roles) AS item(value)
        WHERE jsonb_typeof(item.value) <> 'string'
    ) OR EXISTS (
        SELECT 1
        FROM jsonb_array_elements(NEW.permissions) AS item(value)
        WHERE jsonb_typeof(item.value) <> 'string'
    ) OR EXISTS (
        SELECT 1
        FROM jsonb_array_elements(NEW.tenant_roles) AS item(value)
        WHERE jsonb_typeof(item.value) <> 'string'
    ) THEN
        RAISE EXCEPTION 'runtime session flat snapshots must contain only strings'
            USING ERRCODE = '23514';
    END IF;

    declared_project_ids := public.geno_v2_jsonb_text_set(NEW.project_ids);
    IF cardinality(declared_project_ids) = 0
       OR cardinality(declared_project_ids) <> jsonb_array_length(NEW.project_ids) THEN
        RAISE EXCEPTION 'runtime session project_ids must be nonempty and unique'
            USING ERRCODE = '23514';
    END IF;
    declared_tenant_roles := public.geno_v2_jsonb_text_set(NEW.tenant_roles);
    IF cardinality(declared_tenant_roles) <> jsonb_array_length(NEW.tenant_roles)
       OR cardinality(public.geno_v2_jsonb_text_set(NEW.roles))
            <> jsonb_array_length(NEW.roles)
       OR cardinality(public.geno_v2_jsonb_text_set(NEW.permissions))
            <> jsonb_array_length(NEW.permissions) THEN
        RAISE EXCEPTION 'runtime session flat snapshots must be unique'
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.tenants AS tenant_row
        WHERE tenant_row.id = NEW.tenant_id AND tenant_row.status = 'active'
    ) THEN
        RAISE EXCEPTION 'runtime session tenant must be active' USING ERRCODE = '23514';
    END IF;
    SELECT coalesce(array_agg(member.role ORDER BY member.role), ARRAY[]::text[])
    INTO actual_tenant_roles
    FROM public.tenant_members AS member
    WHERE member.tenant_id = NEW.tenant_id
      AND member.user_id = NEW.actor_id
      AND member.status = 'active';
    IF declared_tenant_roles <> actual_tenant_roles THEN
        RAISE EXCEPTION 'runtime session tenant_roles do not match active membership'
            USING ERRCODE = '23514';
    END IF;

    SELECT coalesce(array_agg(project_id ORDER BY project_id), ARRAY[]::text[])
    INTO actual_project_ids
    FROM (
        SELECT member.project_id::text AS project_id
        FROM public.project_members AS member
        JOIN public.projects AS project_row
          ON project_row.id = member.project_id
         AND project_row.tenant_id = member.tenant_id
         AND project_row.status <> 'archived'
        WHERE member.tenant_id = NEW.tenant_id
          AND member.user_id = NEW.actor_id
          AND member.status = 'active'
        UNION
        SELECT grant_row.project_id::text
        FROM public.runtime_project_access_grants AS grant_row
        JOIN public.projects AS project_row
          ON project_row.id = grant_row.project_id
         AND project_row.tenant_id = grant_row.tenant_id
         AND project_row.status <> 'archived'
        WHERE grant_row.tenant_id = NEW.tenant_id
          AND grant_row.actor_id = NEW.actor_id
          AND grant_row.status = 'active'
    ) AS accessible_projects(project_id);
    IF declared_project_ids <> actual_project_ids THEN
        RAISE EXCEPTION 'runtime session must snapshot every accessible project'
            USING ERRCODE = '23514';
    END IF;

    SELECT coalesce(array_agg(scope.value->>'project_id' ORDER BY scope.ordinality), ARRAY[]::text[])
    INTO projected_project_ids
    FROM jsonb_array_elements(NEW.project_scopes)
        WITH ORDINALITY AS scope(value, ordinality);
    IF NEW.project_ids <> to_jsonb(projected_project_ids) THEN
        RAISE EXCEPTION 'runtime session project_ids must equal project_scopes projection'
            USING ERRCODE = '23514';
    END IF;

    FOR scope_item IN
        SELECT scope.value
        FROM jsonb_array_elements(NEW.project_scopes)
            WITH ORDINALITY AS scope(value, ordinality)
        ORDER BY scope.ordinality
    LOOP
        IF jsonb_typeof(scope_item) <> 'object'
           OR NOT scope_item ?& ARRAY[
                'project_id', 'roles', 'permissions',
                'portal_capabilities', 'scope_sources'
           ]
           OR scope_item - ARRAY[
                'project_id', 'roles', 'permissions',
                'portal_capabilities', 'scope_sources'
           ] <> '{}'::jsonb
           OR jsonb_typeof(scope_item->'roles') <> 'array'
           OR jsonb_typeof(scope_item->'permissions') <> 'array'
           OR jsonb_typeof(scope_item->'portal_capabilities') <> 'array'
           OR jsonb_typeof(scope_item->'scope_sources') <> 'array' THEN
            RAISE EXCEPTION 'runtime session project scope shape is invalid'
                USING ERRCODE = '23514';
        END IF;
        scope_project_id := (scope_item->>'project_id')::uuid;
        IF NOT EXISTS (
            SELECT 1 FROM public.projects AS project_row
            WHERE project_row.id = scope_project_id
              AND project_row.tenant_id = NEW.tenant_id
              AND project_row.status <> 'archived'
        ) THEN
            RAISE EXCEPTION 'runtime session project scope is outside the active tenant'
                USING ERRCODE = '23514';
        END IF;

        declared_roles := public.geno_v2_jsonb_text_set(scope_item->'roles');
        declared_permissions := public.geno_v2_jsonb_text_set(scope_item->'permissions');
        declared_capabilities := public.geno_v2_jsonb_text_set(
            scope_item->'portal_capabilities'
        );
        declared_sources := public.geno_v2_jsonb_text_set(scope_item->'scope_sources');
        IF cardinality(declared_roles) = 0
           OR cardinality(declared_roles) <> jsonb_array_length(scope_item->'roles')
           OR cardinality(declared_permissions)
                <> jsonb_array_length(scope_item->'permissions')
           OR cardinality(declared_capabilities)
                <> jsonb_array_length(scope_item->'portal_capabilities')
           OR cardinality(declared_sources)
                <> jsonb_array_length(scope_item->'scope_sources') THEN
            RAISE EXCEPTION 'runtime session project scope arrays must be unique'
                USING ERRCODE = '23514';
        END IF;

        SELECT coalesce(array_agg(DISTINCT role_name ORDER BY role_name), ARRAY[]::text[])
        INTO actual_roles
        FROM (
            SELECT member.role AS role_name
            FROM public.project_members AS member
            WHERE member.project_id = scope_project_id
              AND member.tenant_id = NEW.tenant_id
              AND member.user_id = NEW.actor_id
              AND member.status = 'active'
            UNION
            SELECT grant_row.canonical_role
            FROM public.runtime_project_access_grants AS grant_row
            WHERE grant_row.project_id = scope_project_id
              AND grant_row.tenant_id = NEW.tenant_id
              AND grant_row.actor_id = NEW.actor_id
              AND grant_row.status = 'active'
        ) AS backed_roles(role_name);
        IF declared_roles <> actual_roles THEN
            RAISE EXCEPTION 'runtime session project roles are not fully backed'
                USING ERRCODE = '23514';
        END IF;

        SELECT coalesce(array_agg(DISTINCT permission ORDER BY permission), ARRAY[]::text[])
        INTO actual_permissions
        FROM unnest(actual_roles) AS role_item(role_name)
        CROSS JOIN LATERAL unnest(
            public.geno_v2_permissions_for_role(role_item.role_name)
        ) AS permission_item(permission);
        IF declared_permissions <> actual_permissions THEN
            RAISE EXCEPTION 'runtime session project permissions are not canonical'
                USING ERRCODE = '23514';
        END IF;

        SELECT coalesce(array_agg(DISTINCT capability ORDER BY capability), ARRAY[]::text[])
        INTO actual_capabilities
        FROM (
            SELECT CASE
                WHEN role_name = 'client_viewer' THEN 'portal.customer.access'
                ELSE 'portal.admin.access'
            END AS capability
            FROM unnest(actual_roles) AS role_item(role_name)
        ) AS capabilities;
        IF declared_capabilities <> actual_capabilities THEN
            RAISE EXCEPTION 'runtime session portal capabilities are not canonical'
                USING ERRCODE = '23514';
        END IF;

        SELECT coalesce(array_agg(source_name ORDER BY source_name), ARRAY[]::text[])
        INTO actual_sources
        FROM (
            SELECT 'direct_member'::text AS source_name
            WHERE EXISTS (
                SELECT 1 FROM public.project_members AS member
                WHERE member.project_id = scope_project_id
                  AND member.tenant_id = NEW.tenant_id
                  AND member.user_id = NEW.actor_id
                  AND member.status = 'active'
            )
            UNION
            SELECT 'tenant_role'::text
            WHERE EXISTS (
                SELECT 1 FROM public.runtime_project_access_grants AS grant_row
                WHERE grant_row.project_id = scope_project_id
                  AND grant_row.tenant_id = NEW.tenant_id
                  AND grant_row.actor_id = NEW.actor_id
                  AND grant_row.status = 'active'
            )
        ) AS sources;
        IF declared_sources <> actual_sources THEN
            RAISE EXCEPTION 'runtime session scope sources are not canonical'
                USING ERRCODE = '23514';
        END IF;
        aggregate_roles := aggregate_roles || actual_roles;
        aggregate_permissions := aggregate_permissions || actual_permissions;
    END LOOP;

    SELECT coalesce(array_agg(DISTINCT value ORDER BY value), ARRAY[]::text[])
    INTO aggregate_roles FROM unnest(declared_tenant_roles || aggregate_roles) AS item(value);
    SELECT coalesce(array_agg(DISTINCT value ORDER BY value), ARRAY[]::text[])
    INTO aggregate_permissions FROM unnest(aggregate_permissions) AS item(value);
    IF public.geno_v2_jsonb_text_set(NEW.roles) <> aggregate_roles
       OR public.geno_v2_jsonb_text_set(NEW.permissions) <> aggregate_permissions THEN
        RAISE EXCEPTION 'runtime session flat role or permission projection is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
EXCEPTION WHEN invalid_text_representation THEN
    RAISE EXCEPTION 'runtime session project identifiers must be UUIDs'
        USING ERRCODE = '23514';
END;
$validate_session$;

CREATE FUNCTION geno_v2_guard_runtime_session_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard_session_update$
BEGIN
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
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'runtime session identity and scope snapshot are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status <> 'active' OR NEW.status NOT IN ('expired', 'revoked') THEN
        RAISE EXCEPTION 'runtime session allows only active to terminal transitions'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_session_update$;

CREATE FUNCTION geno_v2_resolve_session_context()
RETURNS TABLE (
    session_id uuid,
    actor_id text,
    tenant_id uuid,
    project_ids jsonb,
    tenant_roles jsonb,
    project_scopes jsonb
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $resolve_session$
DECLARE
    supplied_hash text;
BEGIN
    supplied_hash := nullif(btrim(current_setting('app.session_token_hash', true)), '');
    IF supplied_hash IS NULL OR supplied_hash !~ '^[0-9a-f]{64}$' THEN
        RETURN;
    END IF;
    RETURN QUERY
    SELECT
        session_row.id,
        session_row.actor_id,
        session_row.tenant_id,
        session_row.project_ids,
        session_row.tenant_roles,
        session_row.project_scopes
    FROM public.runtime_sessions AS session_row
    JOIN public.tenants AS tenant_row ON tenant_row.id = session_row.tenant_id
    WHERE session_row.session_token_hash = supplied_hash
      AND session_row.status = 'active'
      AND session_row.issued_at <= statement_timestamp()
      AND session_row.expires_at > statement_timestamp()
      AND session_row.scope_version = 'runtime_session_scope_v2'
      AND session_row.authz_policy_version = 'auth_surface_policy_v1'
      AND tenant_row.status = 'active'
      AND NOT EXISTS (
          SELECT 1
          FROM jsonb_array_elements_text(session_row.project_ids) AS scoped(project_id)
          LEFT JOIN public.projects AS project_row
            ON project_row.id = scoped.project_id::uuid
           AND project_row.tenant_id = session_row.tenant_id
           AND project_row.status <> 'archived'
          WHERE project_row.id IS NULL
      );
END;
$resolve_session$;

CREATE FUNCTION geno_v2_session_can_access_tenant(row_tenant_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $tenant_access$
    SELECT EXISTS (
        SELECT 1 FROM public.geno_v2_resolve_session_context() AS context
        WHERE context.tenant_id = row_tenant_id
    );
$tenant_access$;

CREATE FUNCTION geno_v2_session_has_tenant_permission(
    row_tenant_id uuid,
    required_permission text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $tenant_permission$
    SELECT EXISTS (
        SELECT 1
        FROM public.geno_v2_resolve_session_context() AS context
        CROSS JOIN LATERAL jsonb_array_elements_text(context.tenant_roles) AS role_item(role_name)
        WHERE context.tenant_id = row_tenant_id
          AND public.geno_v2_role_has_permission(role_item.role_name, required_permission)
    );
$tenant_permission$;

CREATE FUNCTION geno_v2_session_has_project_permission(
    row_project_id uuid,
    row_tenant_id uuid,
    required_permission text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $project_permission$
    SELECT EXISTS (
        SELECT 1
        FROM public.geno_v2_resolve_session_context() AS context
        CROSS JOIN LATERAL jsonb_array_elements(context.project_scopes) AS scope(value)
        CROSS JOIN LATERAL jsonb_array_elements_text(scope.value->'permissions')
            AS permission_item(permission_name)
        WHERE context.tenant_id = row_tenant_id
          AND scope.value->>'project_id' = row_project_id::text
          AND permission_item.permission_name = required_permission
    );
$project_permission$;

CREATE FUNCTION geno_v2_session_can_read_profile(
    row_market_code text,
    row_industry_code text DEFAULT NULL
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $profile_access$
    SELECT EXISTS (
        SELECT 1
        FROM public.geno_v2_resolve_session_context() AS context
        CROSS JOIN LATERAL jsonb_array_elements_text(context.project_ids) AS scoped(project_id)
        JOIN public.projects AS project_row
          ON project_row.id = scoped.project_id::uuid
         AND project_row.tenant_id = context.tenant_id
         AND project_row.status <> 'archived'
        WHERE project_row.market_code = row_market_code
          AND (row_industry_code IS NULL OR project_row.industry_code = row_industry_code)
    );
$profile_access$;

CREATE FUNCTION geno_v2_session_can_read_tenant_member(
    row_tenant_id uuid,
    row_user_id text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $tenant_member_access$
    SELECT EXISTS (
        SELECT 1 FROM public.geno_v2_resolve_session_context() AS context
        WHERE context.tenant_id = row_tenant_id
          AND (
              context.actor_id = row_user_id
              OR public.geno_v2_session_has_tenant_permission(
                  row_tenant_id,
                  'member.manage'
              )
          )
    );
$tenant_member_access$;

CREATE FUNCTION geno_v2_session_can_read_project_member(
    row_project_id uuid,
    row_tenant_id uuid,
    row_user_id text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $project_member_access$
    SELECT EXISTS (
        SELECT 1
        FROM public.geno_v2_resolve_session_context() AS context
        CROSS JOIN LATERAL jsonb_array_elements(context.project_scopes) AS scope(value)
        WHERE context.tenant_id = row_tenant_id
          AND scope.value->>'project_id' = row_project_id::text
          AND (
              context.actor_id = row_user_id
              OR scope.value->'permissions' ? 'member.manage'
          )
    );
$project_member_access$;

CREATE FUNCTION geno_v2_session_can_read_audit(
    row_tenant_id uuid,
    row_project_id uuid,
    row_actor_id text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $audit_access$
    SELECT EXISTS (
        SELECT 1 FROM public.geno_v2_resolve_session_context() AS context
        WHERE (row_project_id IS NULL AND row_tenant_id IS NULL
                AND context.actor_id = row_actor_id)
           OR (row_project_id IS NULL AND row_tenant_id = context.tenant_id
                AND public.geno_v2_session_has_tenant_permission(
                    row_tenant_id,
                    'audit.read'
                ))
           OR (row_project_id IS NOT NULL
                AND public.geno_v2_session_has_project_permission(
                    row_project_id,
                    row_tenant_id,
                    'audit.read'
                ))
    );
$audit_access$;

ALTER FUNCTION geno_v2_jsonb_text_set(jsonb) OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_validate_auth_redemption_lineage() OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_validate_runtime_session_snapshot() OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_guard_runtime_session_update() OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_resolve_session_context() OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_session_can_access_tenant(uuid) OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_session_has_tenant_permission(uuid, text)
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_session_has_project_permission(uuid, uuid, text)
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_session_can_read_profile(text, text) OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_session_can_read_tenant_member(uuid, text)
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_session_can_read_project_member(uuid, uuid, text)
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_session_can_read_audit(uuid, uuid, text)
    OWNER TO geno_v2_authz_owner;

GRANT SELECT ON project_member_invitations, auth_invitation_redemption_attempts,
    runtime_sessions, project_members TO geno_v2_authz_owner;

CREATE CONSTRAINT TRIGGER project_invitations_validate_auth_lineage
AFTER INSERT OR UPDATE ON project_member_invitations
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_auth_redemption_lineage();

CREATE CONSTRAINT TRIGGER auth_attempts_validate_auth_lineage
AFTER INSERT OR UPDATE ON auth_invitation_redemption_attempts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_auth_redemption_lineage();

CREATE CONSTRAINT TRIGGER runtime_sessions_validate_auth_lineage
AFTER INSERT OR UPDATE ON runtime_sessions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_auth_redemption_lineage();

CREATE TRIGGER runtime_sessions_validate_snapshot
BEFORE INSERT ON runtime_sessions
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_runtime_session_snapshot();

CREATE TRIGGER runtime_sessions_guard_update
BEFORE UPDATE ON runtime_sessions
FOR EACH ROW EXECUTE FUNCTION geno_v2_guard_runtime_session_update();

ALTER TABLE project_member_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_member_invitations FORCE ROW LEVEL SECURITY;
ALTER TABLE runtime_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE auth_invitation_redemption_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_invitation_redemption_attempts FORCE ROW LEVEL SECURITY;
ALTER TABLE auth_preflight_rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_preflight_rate_limits FORCE ROW LEVEL SECURITY;
ALTER TABLE runtime_session_reauth_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_session_reauth_queue FORCE ROW LEVEL SECURITY;
ALTER TABLE auth_runtime_write_controls ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_runtime_write_controls FORCE ROW LEVEL SECURITY;

CREATE POLICY market_profiles_session_select ON market_profiles
FOR SELECT TO geno_v2_runtime
USING (geno_v2_session_can_read_profile(market_code, NULL));

CREATE POLICY industry_profiles_session_select ON industry_profiles
FOR SELECT TO geno_v2_runtime
USING (geno_v2_session_can_read_profile(market_code, industry_code));

CREATE POLICY tenants_session_select ON tenants
FOR SELECT TO geno_v2_runtime
USING (geno_v2_session_can_access_tenant(id));

CREATE POLICY projects_session_select ON projects
FOR SELECT TO geno_v2_runtime
USING (geno_v2_session_has_project_permission(id, tenant_id, 'project.read'));

CREATE POLICY tenant_members_session_select ON tenant_members
FOR SELECT TO geno_v2_runtime
USING (geno_v2_session_can_read_tenant_member(tenant_id, user_id));

CREATE POLICY project_members_session_select ON project_members
FOR SELECT TO geno_v2_runtime
USING (geno_v2_session_can_read_project_member(project_id, tenant_id, user_id));

CREATE POLICY audit_events_session_select ON audit_events
FOR SELECT TO geno_v2_runtime
USING (geno_v2_session_can_read_audit(tenant_id, project_id, actor_id));

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

GRANT USAGE ON SCHEMA public TO geno_v2_runtime;
GRANT SELECT ON market_profiles, industry_profiles, tenants, projects,
    tenant_members, project_members, audit_events TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_resolve_session_context() TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_session_can_access_tenant(uuid) TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_session_has_tenant_permission(uuid, text)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_session_has_project_permission(uuid, uuid, text)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_session_can_read_profile(text, text)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_session_can_read_tenant_member(uuid, text)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_session_can_read_project_member(uuid, uuid, text)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_session_can_read_audit(uuid, uuid, text)
    TO geno_v2_runtime;

COMMENT ON FUNCTION geno_v2_resolve_session_context() IS
    'Returns a safe read-only session projection; session_token_hash is never returned.';
COMMENT ON TABLE auth_runtime_write_controls IS
    'Auth writes remain disabled until the 0012 sensitive command boundary is installed.';
