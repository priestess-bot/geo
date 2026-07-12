-- Auth state-transition and authorization-change invalidation boundary.
-- This slice exposes no invitation, redemption, preflight, or provisioning command.

ALTER TABLE auth_invitation_redemption_attempts
    DROP CONSTRAINT auth_attempts_delivery_secret_coherent;
ALTER TABLE auth_invitation_redemption_attempts
    ADD CONSTRAINT auth_attempts_delivery_secret_coherent
    CHECK (
        (status <> 'succeeded'
            AND delivery_ciphertext IS NULL
            AND delivery_key_id IS NULL
            AND delivery_nonce IS NULL
            AND delivery_expires_at IS NULL
            AND secret_erased_at IS NULL)
        OR (status = 'succeeded' AND (
            (delivery_ciphertext IS NOT NULL
                AND octet_length(delivery_ciphertext) BETWEEN 1 AND 16384
                AND delivery_key_id IS NOT NULL
                AND delivery_key_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'
                AND delivery_nonce IS NOT NULL
                AND octet_length(delivery_nonce) = 12
                AND delivery_expires_at IS NOT NULL
                AND delivery_expires_at > created_at
                AND secret_erased_at IS NULL)
            OR (delivery_ciphertext IS NULL
                AND delivery_key_id IS NULL
                AND delivery_nonce IS NULL
                AND delivery_expires_at IS NOT NULL
                AND secret_erased_at IS NOT NULL)
        ))
    );
ALTER TABLE auth_invitation_redemption_attempts
    ADD CONSTRAINT auth_attempts_confirmation_requires_erasure
    CHECK (delivery_confirmed_at IS NULL OR secret_erased_at IS NOT NULL);

CREATE FUNCTION geno_v2_guard_project_member_invitation_state()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard_invitation$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'pending'
           OR NEW.accepted_by_attempt_id IS NOT NULL
           OR NEW.accepted_at IS NOT NULL
           OR NEW.revoked_at IS NOT NULL
           OR NEW.revoke_reason IS NOT NULL THEN
            RAISE EXCEPTION 'project member invitation must be inserted pending'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'project member invitation history is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.email IS DISTINCT FROM OLD.email
       OR NEW.role IS DISTINCT FROM OLD.role
       OR NEW.invite_token_hash IS DISTINCT FROM OLD.invite_token_hash
       OR NEW.audience IS DISTINCT FROM OLD.audience
       OR NEW.allowed_surfaces IS DISTINCT FROM OLD.allowed_surfaces
       OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
       OR NEW.invited_by IS DISTINCT FROM OLD.invited_by
       OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
       OR NEW.metadata IS DISTINCT FROM OLD.metadata
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'project member invitation identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.updated_at <= OLD.updated_at THEN
        RAISE EXCEPTION 'project member invitation updated_at must advance'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status <> 'pending'
       OR NEW.status NOT IN ('accepted', 'revoked', 'expired') THEN
        RAISE EXCEPTION 'project member invitation allows only pending to terminal transitions'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_invitation$;

CREATE FUNCTION geno_v2_guard_auth_redemption_attempt_state()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard_attempt$
DECLARE
    secret_erasure_transition boolean;
    replay_transition boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'preparing'
           OR NEW.session_id IS NOT NULL
           OR NEW.replay_count <> 0
           OR NEW.delivery_ciphertext IS NOT NULL
           OR NEW.delivery_key_id IS NOT NULL
           OR NEW.delivery_nonce IS NOT NULL
           OR NEW.delivery_expires_at IS NOT NULL
           OR NEW.delivery_confirmed_at IS NOT NULL
           OR NEW.secret_erased_at IS NOT NULL THEN
            RAISE EXCEPTION 'auth redemption attempt must be inserted preparing'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'auth redemption attempt history is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.invitation_id IS DISTINCT FROM OLD.invitation_id
       OR NEW.requested_surface IS DISTINCT FROM OLD.requested_surface
       OR NEW.idempotency_key_hash IS DISTINCT FROM OLD.idempotency_key_hash
       OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
       OR NEW.token_fingerprint IS DISTINCT FROM OLD.token_fingerprint
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'auth redemption attempt identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.updated_at <= OLD.updated_at THEN
        RAISE EXCEPTION 'auth redemption attempt updated_at must advance'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.status = 'preparing' AND NEW.status = 'succeeded' THEN
        IF NEW.session_id IS NULL
           OR NEW.replay_count <> OLD.replay_count
           OR NEW.delivery_ciphertext IS NULL
           OR octet_length(NEW.delivery_ciphertext) NOT BETWEEN 1 AND 16384
           OR NEW.delivery_key_id IS NULL
           OR NEW.delivery_key_id !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'
           OR NEW.delivery_nonce IS NULL
           OR octet_length(NEW.delivery_nonce) <> 12
           OR NEW.delivery_expires_at IS NULL
           OR NEW.delivery_expires_at <= NEW.created_at
           OR NEW.delivery_expires_at <= NEW.updated_at
           OR NEW.delivery_expires_at <= statement_timestamp()
           OR NEW.delivery_confirmed_at IS NOT NULL
           OR NEW.secret_erased_at IS NOT NULL THEN
            RAISE EXCEPTION 'auth redemption success transition is invalid'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status = 'preparing' AND NEW.status = 'failed' THEN
        IF NEW.session_id IS DISTINCT FROM OLD.session_id
           OR NEW.replay_count <> OLD.replay_count
           OR NEW.delivery_ciphertext IS DISTINCT FROM OLD.delivery_ciphertext
           OR NEW.delivery_key_id IS DISTINCT FROM OLD.delivery_key_id
           OR NEW.delivery_nonce IS DISTINCT FROM OLD.delivery_nonce
           OR NEW.delivery_expires_at IS DISTINCT FROM OLD.delivery_expires_at
           OR NEW.delivery_confirmed_at IS DISTINCT FROM OLD.delivery_confirmed_at
           OR NEW.secret_erased_at IS DISTINCT FROM OLD.secret_erased_at THEN
            RAISE EXCEPTION 'auth redemption failure transition is invalid'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'succeeded' AND NEW.status = 'succeeded'
       AND NEW.session_id IS NOT DISTINCT FROM OLD.session_id THEN
        secret_erasure_transition :=
            OLD.delivery_ciphertext IS NOT NULL
            AND NEW.delivery_ciphertext IS NULL
            AND NEW.delivery_key_id IS NULL
            AND NEW.delivery_nonce IS NULL
            AND NEW.delivery_expires_at IS NOT DISTINCT FROM OLD.delivery_expires_at
            AND OLD.secret_erased_at IS NULL
            AND NEW.secret_erased_at IS NOT NULL
            AND (NEW.delivery_confirmed_at IS NOT DISTINCT FROM OLD.delivery_confirmed_at
                OR (OLD.delivery_confirmed_at IS NULL
                    AND NEW.delivery_confirmed_at IS NOT NULL))
            AND NEW.replay_count = OLD.replay_count;
        replay_transition :=
            OLD.delivery_ciphertext IS NOT NULL
            AND NEW.replay_count = OLD.replay_count + 1
            AND NEW.delivery_ciphertext IS NOT DISTINCT FROM OLD.delivery_ciphertext
            AND NEW.delivery_key_id IS NOT DISTINCT FROM OLD.delivery_key_id
            AND NEW.delivery_nonce IS NOT DISTINCT FROM OLD.delivery_nonce
            AND NEW.delivery_expires_at IS NOT DISTINCT FROM OLD.delivery_expires_at
            AND NEW.delivery_confirmed_at IS NOT DISTINCT FROM OLD.delivery_confirmed_at
            AND NEW.secret_erased_at IS NOT DISTINCT FROM OLD.secret_erased_at;
        IF secret_erasure_transition OR replay_transition THEN
            RETURN NEW;
        END IF;
    END IF;
    RAISE EXCEPTION 'auth redemption attempt transition is not allowed'
        USING ERRCODE = '55000';
END;
$guard_attempt$;

CREATE OR REPLACE FUNCTION geno_v2_guard_runtime_session_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard_session_update$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'runtime session history is immutable'
            USING ERRCODE = '55000';
    END IF;
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
    IF NEW.updated_at <= OLD.updated_at THEN
        RAISE EXCEPTION 'runtime session updated_at must advance'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status <> 'active' OR NEW.status NOT IN ('expired', 'revoked') THEN
        RAISE EXCEPTION 'runtime session allows only active to terminal transitions'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_session_update$;

CREATE FUNCTION geno_v2_guard_runtime_reauth_state()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard_reauth$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'pending' OR NEW.resolved_at IS NOT NULL THEN
            RAISE EXCEPTION 'runtime reauthentication must be inserted pending'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'runtime reauthentication history is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.session_id IS DISTINCT FROM OLD.session_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
       OR NEW.reason_code IS DISTINCT FROM OLD.reason_code
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'runtime reauthentication identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status <> 'pending' OR NEW.status <> 'resolved' THEN
        RAISE EXCEPTION 'runtime reauthentication allows only pending to resolved'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_reauth$;

CREATE FUNCTION geno_v2_guard_auth_write_control_state()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard_write_control$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'auth runtime write control cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.singleton IS DISTINCT FROM OLD.singleton THEN
        RAISE EXCEPTION 'auth runtime write control identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.writes_enabled = OLD.writes_enabled
       OR NEW.updated_at <= OLD.updated_at THEN
        RAISE EXCEPTION 'auth runtime write control requires an advancing explicit toggle'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_write_control$;

CREATE FUNCTION geno_v2_guard_auth_preflight_rate_limit_state()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard_preflight$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.request_count <> 1 THEN
            RAISE EXCEPTION 'auth preflight bucket must start at one'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF OLD.expires_at > statement_timestamp() THEN
            RAISE EXCEPTION 'active auth preflight bucket cannot be deleted'
                USING ERRCODE = '55000';
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.bucket_key IS DISTINCT FROM OLD.bucket_key
       OR NEW.updated_at <= OLD.updated_at THEN
        RAISE EXCEPTION 'auth preflight bucket identity or update time is invalid'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.window_started_at IS NOT DISTINCT FROM OLD.window_started_at
       AND NEW.expires_at IS NOT DISTINCT FROM OLD.expires_at
       AND NEW.request_count = OLD.request_count + 1 THEN
        RETURN NEW;
    END IF;
    IF OLD.expires_at <= statement_timestamp()
       AND NEW.window_started_at >= OLD.expires_at
       AND NEW.request_count = 1 THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'auth preflight bucket transition is not allowed'
        USING ERRCODE = '55000';
END;
$guard_preflight$;

CREATE FUNCTION geno_v2_require_auth_writes_enabled()
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $require_auth_writes$
BEGIN
    IF NOT coalesce((
        SELECT control.writes_enabled
        FROM public.auth_runtime_write_controls AS control
        WHERE control.singleton
    ), false) THEN
        RAISE EXCEPTION 'auth_writes_temporarily_disabled'
            USING ERRCODE = '42501',
                  DETAIL = 'Privilege-expanding auth writes are disabled.';
    END IF;
END;
$require_auth_writes$;

CREATE FUNCTION geno_v2_revoke_affected_sessions(
    affected_tenant_id uuid,
    affected_actor_id text,
    affected_project_id uuid,
    reason_code text
)
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $revoke_sessions$
DECLARE
    event_time timestamptz := clock_timestamp();
    revoked_count integer := 0;
    revoked_session record;
BEGIN
    IF affected_tenant_id IS NULL OR btrim(reason_code) = '' THEN
        RAISE EXCEPTION 'session revocation scope is incomplete'
            USING ERRCODE = '22023';
    END IF;
    IF affected_actor_id IS NOT NULL
       AND (affected_actor_id <> lower(btrim(affected_actor_id))
            OR affected_actor_id = '') THEN
        RAISE EXCEPTION 'session revocation actor is not canonical'
            USING ERRCODE = '22023';
    END IF;
    IF NOT (
        (reason_code IN (
            'tenant_member_scope_changed',
            'project_member_scope_changed',
            'derived_grant_scope_changed'
        ) AND affected_actor_id IS NOT NULL
          AND (
              (reason_code = 'tenant_member_scope_changed'
                  AND affected_project_id IS NULL)
              OR (reason_code IN (
                    'project_member_scope_changed',
                    'derived_grant_scope_changed'
                  ) AND affected_project_id IS NOT NULL)
          ))
        OR (reason_code = 'project_archived'
            AND affected_actor_id IS NULL AND affected_project_id IS NOT NULL)
        OR (reason_code = 'tenant_disabled'
            AND affected_actor_id IS NULL AND affected_project_id IS NULL)
    ) THEN
        RAISE EXCEPTION 'session revocation reason does not match its scope'
            USING ERRCODE = '22023';
    END IF;
    FOR revoked_session IN
        UPDATE public.runtime_sessions AS session_row
        SET status = 'revoked',
            revoked_at = event_time,
            revoked_by = 'schema-v2-auth-state',
            revoke_reason = reason_code,
            updated_at = greatest(
                event_time,
                session_row.updated_at + interval '1 microsecond'
            )
        WHERE session_row.status = 'active'
          AND session_row.tenant_id = affected_tenant_id
          AND (affected_actor_id IS NULL
               OR session_row.actor_id = affected_actor_id)
          AND (affected_project_id IS NULL
               OR session_row.project_ids ? affected_project_id::text)
        RETURNING session_row.id, session_row.tenant_id, session_row.actor_id
    LOOP
        revoked_count := revoked_count + 1;
        INSERT INTO public.runtime_session_reauth_queue (
            session_id, tenant_id, actor_id, reason_code, created_at
        ) VALUES (
            revoked_session.id,
            revoked_session.tenant_id,
            revoked_session.actor_id,
            reason_code,
            event_time
        ) ON CONFLICT (session_id) DO NOTHING;
    END LOOP;
    RETURN revoked_count;
END;
$revoke_sessions$;

CREATE FUNCTION geno_v2_lock_runtime_session_authz_sources()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $lock_session_sources$
BEGIN
    PERFORM 1
    FROM public.tenants AS tenant_row
    WHERE tenant_row.id = NEW.tenant_id
    FOR SHARE;
    PERFORM 1
    FROM public.projects AS project_row
    WHERE project_row.tenant_id = NEW.tenant_id
      AND (
          project_row.id::text IN (
              SELECT scoped.project_id
              FROM jsonb_array_elements_text(NEW.project_ids) AS scoped(project_id)
          )
          OR EXISTS (
              SELECT 1 FROM public.project_members AS member
              WHERE member.tenant_id = NEW.tenant_id
                AND member.project_id = project_row.id
                AND member.user_id = NEW.actor_id
                AND member.status = 'active'
          )
          OR EXISTS (
              SELECT 1 FROM public.runtime_project_access_grants AS grant_row
              WHERE grant_row.tenant_id = NEW.tenant_id
                AND grant_row.project_id = project_row.id
                AND grant_row.actor_id = NEW.actor_id
                AND grant_row.status = 'active'
          )
      )
    ORDER BY project_row.id
    FOR SHARE;
    PERFORM 1
    FROM public.tenant_members AS member
    WHERE member.tenant_id = NEW.tenant_id
      AND member.user_id = NEW.actor_id
      AND member.status = 'active'
    ORDER BY member.id
    FOR SHARE;
    PERFORM 1
    FROM public.project_members AS member
    WHERE member.tenant_id = NEW.tenant_id
      AND member.user_id = NEW.actor_id
      AND member.status = 'active'
    ORDER BY member.project_id, member.id
    FOR SHARE;
    PERFORM 1
    FROM public.runtime_project_access_grants AS grant_row
    WHERE grant_row.tenant_id = NEW.tenant_id
      AND grant_row.actor_id = NEW.actor_id
      AND grant_row.status = 'active'
    ORDER BY grant_row.project_id, grant_row.id
    FOR SHARE;
    RETURN NEW;
END;
$lock_session_sources$;

CREATE FUNCTION geno_v2_revoke_sessions_for_authz_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $revoke_for_authz_change$
DECLARE
    member_row record;
BEGIN
    IF TG_TABLE_NAME = 'tenant_members' THEN
        IF TG_OP = 'UPDATE'
           AND NEW.tenant_id IS NOT DISTINCT FROM OLD.tenant_id
           AND NEW.user_id IS NOT DISTINCT FROM OLD.user_id
           AND NEW.role IS NOT DISTINCT FROM OLD.role
           AND NEW.status IS NOT DISTINCT FROM OLD.status THEN
            RETURN NEW;
        END IF;
        IF TG_OP <> 'INSERT' AND OLD.status = 'active' THEN
            PERFORM public.geno_v2_revoke_affected_sessions(
                OLD.tenant_id, OLD.user_id, NULL, 'tenant_member_scope_changed'
            );
        END IF;
        IF TG_OP <> 'DELETE' AND NEW.status = 'active'
           AND (TG_OP = 'INSERT'
                OR OLD.status <> 'active'
                OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                OR NEW.user_id IS DISTINCT FROM OLD.user_id) THEN
            PERFORM public.geno_v2_revoke_affected_sessions(
                NEW.tenant_id, NEW.user_id, NULL, 'tenant_member_scope_changed'
            );
        END IF;
    ELSIF TG_TABLE_NAME = 'project_members' THEN
        IF TG_OP = 'UPDATE'
           AND NEW.tenant_id IS NOT DISTINCT FROM OLD.tenant_id
           AND NEW.project_id IS NOT DISTINCT FROM OLD.project_id
           AND NEW.user_id IS NOT DISTINCT FROM OLD.user_id
           AND NEW.role IS NOT DISTINCT FROM OLD.role
           AND NEW.status IS NOT DISTINCT FROM OLD.status THEN
            RETURN NEW;
        END IF;
        IF TG_OP <> 'INSERT' AND OLD.status = 'active' THEN
            PERFORM public.geno_v2_revoke_affected_sessions(
                OLD.tenant_id,
                OLD.user_id,
                OLD.project_id,
                'project_member_scope_changed'
            );
        END IF;
        IF TG_OP <> 'DELETE' AND NEW.status = 'active'
           AND (TG_OP = 'INSERT'
                OR OLD.status <> 'active'
                OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                OR NEW.user_id IS DISTINCT FROM OLD.user_id) THEN
            PERFORM public.geno_v2_revoke_affected_sessions(
                NEW.tenant_id,
                NEW.user_id,
                NEW.project_id,
                'project_member_scope_changed'
            );
        END IF;
    ELSIF TG_TABLE_NAME = 'runtime_project_access_grants' THEN
        IF TG_OP = 'UPDATE'
           AND NEW.tenant_id IS NOT DISTINCT FROM OLD.tenant_id
           AND NEW.project_id IS NOT DISTINCT FROM OLD.project_id
           AND NEW.actor_id IS NOT DISTINCT FROM OLD.actor_id
           AND NEW.source_type IS NOT DISTINCT FROM OLD.source_type
           AND NEW.source_id IS NOT DISTINCT FROM OLD.source_id
           AND NEW.canonical_role IS NOT DISTINCT FROM OLD.canonical_role
           AND NEW.permission_set_version IS NOT DISTINCT FROM OLD.permission_set_version
           AND NEW.permissions IS NOT DISTINCT FROM OLD.permissions
           AND NEW.status IS NOT DISTINCT FROM OLD.status THEN
            RETURN NEW;
        END IF;
        IF TG_OP <> 'INSERT' THEN
            PERFORM public.geno_v2_revoke_affected_sessions(
                OLD.tenant_id,
                OLD.actor_id,
                OLD.project_id,
                'derived_grant_scope_changed'
            );
        END IF;
        IF TG_OP <> 'DELETE'
           AND (TG_OP = 'INSERT'
                OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                OR NEW.actor_id IS DISTINCT FROM OLD.actor_id) THEN
            PERFORM public.geno_v2_revoke_affected_sessions(
                NEW.tenant_id,
                NEW.actor_id,
                NEW.project_id,
                'derived_grant_scope_changed'
            );
        END IF;
    ELSIF TG_TABLE_NAME = 'projects' THEN
        IF TG_OP = 'UPDATE'
           AND (OLD.status = 'archived') IS DISTINCT FROM (NEW.status = 'archived') THEN
            IF NEW.status = 'archived' THEN
                PERFORM public.geno_v2_revoke_affected_sessions(
                    NEW.tenant_id, NULL, NEW.id, 'project_archived'
                );
            ELSE
                FOR member_row IN
                    SELECT member.user_id
                    FROM public.project_members AS member
                    WHERE member.tenant_id = NEW.tenant_id
                      AND member.project_id = NEW.id
                      AND member.status = 'active'
                LOOP
                    PERFORM public.geno_v2_revoke_affected_sessions(
                        NEW.tenant_id,
                        member_row.user_id,
                        NEW.id,
                        'project_member_scope_changed'
                    );
                END LOOP;
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'tenants' THEN
        IF TG_OP = 'UPDATE' AND OLD.status = 'active' AND NEW.status = 'disabled' THEN
            PERFORM public.geno_v2_revoke_affected_sessions(
                NEW.id, NULL, NULL, 'tenant_disabled'
            );
        END IF;
    ELSE
        RAISE EXCEPTION 'unsupported authorization lifecycle trigger table'
            USING ERRCODE = '55000';
    END IF;
    RETURN coalesce(NEW, OLD);
END;
$revoke_for_authz_change$;

ALTER FUNCTION geno_v2_guard_project_member_invitation_state()
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_guard_auth_redemption_attempt_state()
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_guard_runtime_session_update() OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_guard_runtime_reauth_state() OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_guard_auth_write_control_state() OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_guard_auth_preflight_rate_limit_state()
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_require_auth_writes_enabled() OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_revoke_affected_sessions(uuid, text, uuid, text)
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_revoke_sessions_for_authz_change()
    OWNER TO geno_v2_authz_owner;

GRANT UPDATE (status, revoked_at, revoked_by, revoke_reason, updated_at)
    ON runtime_sessions TO geno_v2_authz_owner;
GRANT INSERT ON runtime_session_reauth_queue TO geno_v2_authz_owner;
GRANT SELECT (session_id) ON runtime_session_reauth_queue TO geno_v2_authz_owner;
GRANT SELECT ON auth_runtime_write_controls TO geno_v2_authz_owner;

REVOKE ALL ON FUNCTION geno_v2_guard_project_member_invitation_state() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_guard_auth_redemption_attempt_state() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_guard_runtime_session_update() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_guard_runtime_reauth_state() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_guard_auth_write_control_state() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_guard_auth_preflight_rate_limit_state() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_require_auth_writes_enabled() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_revoke_affected_sessions(uuid, text, uuid, text)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_lock_runtime_session_authz_sources() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_revoke_sessions_for_authz_change() FROM PUBLIC;

CREATE TRIGGER project_invitations_guard_state
BEFORE INSERT OR UPDATE OR DELETE ON project_member_invitations
FOR EACH ROW EXECUTE FUNCTION geno_v2_guard_project_member_invitation_state();

CREATE TRIGGER auth_attempts_guard_state
BEFORE INSERT OR UPDATE OR DELETE ON auth_invitation_redemption_attempts
FOR EACH ROW EXECUTE FUNCTION geno_v2_guard_auth_redemption_attempt_state();

DROP TRIGGER runtime_sessions_guard_update ON runtime_sessions;
CREATE TRIGGER runtime_sessions_guard_update
BEFORE UPDATE OR DELETE ON runtime_sessions
FOR EACH ROW EXECUTE FUNCTION geno_v2_guard_runtime_session_update();

CREATE TRIGGER runtime_sessions_authz_source_lock
BEFORE INSERT ON runtime_sessions
FOR EACH ROW EXECUTE FUNCTION geno_v2_lock_runtime_session_authz_sources();

CREATE TRIGGER runtime_reauth_guard_state
BEFORE INSERT OR UPDATE OR DELETE ON runtime_session_reauth_queue
FOR EACH ROW EXECUTE FUNCTION geno_v2_guard_runtime_reauth_state();

CREATE TRIGGER auth_write_controls_guard_state
BEFORE UPDATE OR DELETE ON auth_runtime_write_controls
FOR EACH ROW EXECUTE FUNCTION geno_v2_guard_auth_write_control_state();

CREATE TRIGGER auth_preflight_guard_state
BEFORE INSERT OR UPDATE OR DELETE ON auth_preflight_rate_limits
FOR EACH ROW EXECUTE FUNCTION geno_v2_guard_auth_preflight_rate_limit_state();

DROP TRIGGER tenant_members_sync_project_grants ON tenant_members;
CREATE TRIGGER tenant_members_sync_project_grants
AFTER INSERT OR DELETE ON tenant_members
FOR EACH ROW EXECUTE FUNCTION geno_v2_sync_tenant_member_project_grants();
CREATE TRIGGER tenant_members_sync_project_grants_update
AFTER UPDATE OF tenant_id, user_id, role, status ON tenant_members
FOR EACH ROW
WHEN (
    OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
    OR OLD.user_id IS DISTINCT FROM NEW.user_id
    OR OLD.role IS DISTINCT FROM NEW.role
    OR OLD.status IS DISTINCT FROM NEW.status
)
EXECUTE FUNCTION geno_v2_sync_tenant_member_project_grants();

DROP TRIGGER projects_sync_tenant_grants ON projects;
CREATE TRIGGER projects_sync_tenant_grants
AFTER INSERT OR DELETE ON projects
FOR EACH ROW EXECUTE FUNCTION geno_v2_sync_project_tenant_grants();
CREATE TRIGGER projects_sync_tenant_grants_update
AFTER UPDATE OF tenant_id, status ON projects
FOR EACH ROW
WHEN (
    OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
    OR (OLD.status = 'archived') IS DISTINCT FROM (NEW.status = 'archived')
)
EXECUTE FUNCTION geno_v2_sync_project_tenant_grants();

DROP TRIGGER tenants_sync_status_grants ON tenants;
CREATE TRIGGER tenants_sync_status_grants
AFTER UPDATE OF status ON tenants
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION geno_v2_sync_tenant_status_grants();

CREATE TRIGGER tenant_members_revoke_sessions
BEFORE INSERT OR UPDATE OF tenant_id, user_id, role, status OR DELETE ON tenant_members
FOR EACH ROW EXECUTE FUNCTION geno_v2_revoke_sessions_for_authz_change();

CREATE TRIGGER project_members_revoke_sessions
BEFORE INSERT OR UPDATE OF tenant_id, project_id, user_id, role, status OR DELETE
ON project_members
FOR EACH ROW EXECUTE FUNCTION geno_v2_revoke_sessions_for_authz_change();

CREATE TRIGGER runtime_grants_revoke_sessions
BEFORE INSERT OR UPDATE OR DELETE ON runtime_project_access_grants
FOR EACH ROW EXECUTE FUNCTION geno_v2_revoke_sessions_for_authz_change();

CREATE TRIGGER projects_revoke_sessions
BEFORE UPDATE OF status ON projects
FOR EACH ROW EXECUTE FUNCTION geno_v2_revoke_sessions_for_authz_change();

CREATE TRIGGER tenants_revoke_sessions
BEFORE UPDATE OF status ON tenants
FOR EACH ROW EXECUTE FUNCTION geno_v2_revoke_sessions_for_authz_change();

COMMENT ON FUNCTION geno_v2_require_auth_writes_enabled() IS
    'Future privilege-expanding auth commands must call this fail-closed helper.';
COMMENT ON FUNCTION geno_v2_revoke_affected_sessions(uuid, text, uuid, text) IS
    'Revocation, logout, and secret erasure remain available while auth writes are disabled.';
COMMENT ON FUNCTION geno_v2_lock_runtime_session_authz_sources() IS
    'Installer-owned trigger helper; schema owner is retained for FOR SHARE lock privileges.';
COMMENT ON TABLE auth_runtime_write_controls IS
    'Privilege-expanding auth commands remain disabled after the 0012 state-guard slice.';
