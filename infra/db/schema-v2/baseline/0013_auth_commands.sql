-- Auth command boundary. Public functions are added only after the storage and
-- lifecycle constraints below are complete; no transport or provisioning
-- behavior belongs in this baseline.

CREATE FUNCTION geno_v2_lock_auth_write_control()
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $lock_auth_write_control$
DECLARE
    writes_are_enabled boolean;
BEGIN
    SELECT control.writes_enabled INTO writes_are_enabled
    FROM public.auth_runtime_write_controls AS control
    WHERE control.singleton
    FOR SHARE;
    RETURN coalesce(writes_are_enabled, false);
END;
$lock_auth_write_control$;

CREATE OR REPLACE FUNCTION geno_v2_require_auth_writes_enabled()
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $require_auth_writes$
BEGIN
    IF NOT public.geno_v2_lock_auth_write_control() THEN
        RAISE EXCEPTION 'auth_writes_temporarily_disabled'
            USING ERRCODE = '42501',
                  DETAIL = 'Privilege-expanding auth writes are disabled.';
    END IF;
END;
$require_auth_writes$;

ALTER FUNCTION geno_v2_lock_auth_write_control()
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_require_auth_writes_enabled()
    OWNER TO geno_v2_authz_owner;
REVOKE ALL ON FUNCTION geno_v2_lock_auth_write_control() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_require_auth_writes_enabled() FROM PUBLIC;
GRANT UPDATE (writes_enabled) ON auth_runtime_write_controls
    TO geno_v2_authz_owner;

ALTER TABLE auth_invitation_redemption_attempts
    DROP CONSTRAINT auth_attempts_idempotency_unique;
ALTER TABLE auth_invitation_redemption_attempts
    ADD CONSTRAINT auth_attempts_idempotency_unique
    UNIQUE (invitation_id, idempotency_key_hash);

ALTER TABLE auth_invitation_redemption_attempts
    ADD CONSTRAINT auth_attempts_delivery_recovery_window
    CHECK (
        delivery_expires_at IS NULL
        OR delivery_expires_at <= updated_at + interval '1 hour'
    );

ALTER TABLE runtime_sessions
    ADD CONSTRAINT runtime_sessions_bounded_lifetime
    CHECK (
        expires_at >= issued_at + interval '60 seconds'
        AND expires_at <= issued_at + interval '30 days'
    );

ALTER TABLE runtime_session_reauth_queue
    ADD COLUMN resolved_by_session_id uuid;
ALTER TABLE runtime_session_reauth_queue
    DROP CONSTRAINT runtime_reauth_resolution_coherent;
ALTER TABLE runtime_session_reauth_queue
    ADD CONSTRAINT runtime_reauth_resolution_coherent
    CHECK (
        (status = 'pending'
            AND resolved_at IS NULL
            AND resolved_by_session_id IS NULL)
        OR (status = 'resolved'
            AND resolved_at IS NOT NULL
            AND resolved_by_session_id IS NOT NULL)
    );
ALTER TABLE runtime_session_reauth_queue
    ADD CONSTRAINT runtime_reauth_resolver_identity_fkey
    FOREIGN KEY (resolved_by_session_id, tenant_id, actor_id)
    REFERENCES runtime_sessions(id, tenant_id, actor_id)
    ON UPDATE RESTRICT ON DELETE RESTRICT;

CREATE OR REPLACE FUNCTION geno_v2_guard_runtime_reauth_state()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard_reauth$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'pending'
           OR NEW.resolved_at IS NOT NULL
           OR NEW.resolved_by_session_id IS NOT NULL THEN
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
    IF OLD.status <> 'pending'
       OR NEW.status <> 'resolved'
       OR NEW.resolved_at IS NULL
       OR NEW.resolved_at < NEW.created_at
       OR NEW.resolved_by_session_id IS NULL THEN
        RAISE EXCEPTION 'runtime reauthentication allows only pending to resolved'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_reauth$;

ALTER FUNCTION geno_v2_guard_runtime_reauth_state() OWNER TO geno_v2_authz_owner;
REVOKE ALL ON FUNCTION geno_v2_guard_runtime_reauth_state() FROM PUBLIC;

COMMENT ON CONSTRAINT auth_attempts_idempotency_unique
    ON auth_invitation_redemption_attempts IS
    'One idempotency key is bound to one invitation regardless of requested surface.';
COMMENT ON TABLE auth_invitation_redemption_attempts IS
    'Delivery AAD is exactly auth-delivery-v1 + NUL + canonical attempt UUID + NUL + UTF-8 key ID; replay returns the original attempt and encrypted fields.';
COMMENT ON COLUMN runtime_session_reauth_queue.resolved_by_session_id IS
    'Active same-tenant, same-actor session that resolved this immutable reauthentication item.';

CREATE FUNCTION geno_v2_auth_redeem_request_hash(
    p_invitation_id uuid,
    p_invite_token_hash text,
    p_requested_surface text
)
RETURNS text
LANGUAGE sql
IMMUTABLE
STRICT
SECURITY DEFINER
SET search_path = pg_catalog
AS $request_hash$
    SELECT encode(public.digest(
        convert_to('auth-redeem-v1', 'UTF8')
        || decode('00', 'hex')
        || convert_to(p_invitation_id::text, 'UTF8')
        || decode('00', 'hex')
        || convert_to(p_invite_token_hash, 'UTF8')
        || decode('00', 'hex')
        || convert_to(p_requested_surface, 'UTF8'),
        'sha256'
    ), 'hex');
$request_hash$;

CREATE FUNCTION geno_v2_consume_auth_preflight_bucket(
    p_bucket_key text,
    p_limit integer,
    p_window_seconds integer,
    p_event_time timestamptz
)
RETURNS TABLE (
    bucket_count integer,
    rate_limited boolean,
    retry_after_seconds integer
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $consume_bucket$
BEGIN
    IF p_bucket_key IS NULL OR btrim(p_bucket_key) = ''
       OR p_limit <= 0 OR p_window_seconds <= 0 OR p_event_time IS NULL THEN
        RAISE EXCEPTION 'auth_command_invariant_violation'
            USING ERRCODE = 'GA006';
    END IF;

    RETURN QUERY
    INSERT INTO public.auth_preflight_rate_limits AS bucket (
        bucket_key,
        window_started_at,
        request_count,
        expires_at,
        updated_at
    ) VALUES (
        p_bucket_key,
        p_event_time,
        1,
        p_event_time + make_interval(secs => p_window_seconds),
        p_event_time
    )
    ON CONFLICT (bucket_key) DO UPDATE
    SET window_started_at = CASE
            WHEN bucket.expires_at <= p_event_time THEN p_event_time
            ELSE bucket.window_started_at
        END,
        request_count = CASE
            WHEN bucket.expires_at <= p_event_time THEN 1
            ELSE bucket.request_count + 1
        END,
        expires_at = CASE
            WHEN bucket.expires_at <= p_event_time
                THEN p_event_time + make_interval(secs => p_window_seconds)
            ELSE bucket.expires_at
        END,
        updated_at = greatest(
            p_event_time,
            bucket.updated_at + interval '1 microsecond'
        )
    RETURNING
        bucket.request_count,
        bucket.request_count > p_limit,
        greatest(
            0,
            ceil(extract(epoch FROM bucket.expires_at - p_event_time))::integer
        );
END;
$consume_bucket$;

CREATE FUNCTION geno_v2_lock_auth_command_context(
    p_required boolean,
    p_lock_projects_for_update boolean
)
RETURNS TABLE (
    session_id uuid,
    actor_id text,
    tenant_id uuid,
    project_ids jsonb,
    tenant_roles jsonb,
    project_scopes jsonb
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $command_context$
DECLARE
    supplied_hash text;
    candidate public.runtime_sessions%ROWTYPE;
BEGIN
    supplied_hash := nullif(
        btrim(current_setting('app.session_token_hash', true)),
        ''
    );
    IF supplied_hash IS NULL OR supplied_hash !~ '^[0-9a-f]{64}$' THEN
        IF p_required THEN
            RAISE EXCEPTION 'auth_command_not_authorized'
                USING ERRCODE = 'GA003';
        END IF;
        RETURN;
    END IF;

    SELECT session_row.* INTO candidate
    FROM public.runtime_sessions AS session_row
    WHERE session_row.session_token_hash = supplied_hash;
    IF NOT FOUND THEN
        IF p_required THEN
            RAISE EXCEPTION 'auth_command_not_authorized'
                USING ERRCODE = 'GA003';
        END IF;
        RETURN;
    END IF;

    PERFORM 1
    FROM public.tenants AS tenant_row
    WHERE tenant_row.id = candidate.tenant_id
    FOR SHARE;
    IF p_lock_projects_for_update THEN
        PERFORM 1
        FROM public.projects AS project_row
        WHERE project_row.tenant_id = candidate.tenant_id
        ORDER BY project_row.id
        FOR NO KEY UPDATE;
    ELSE
        PERFORM 1
        FROM public.projects AS project_row
        WHERE project_row.tenant_id = candidate.tenant_id
          AND (
              candidate.project_ids ? project_row.id::text
              OR EXISTS (
                  SELECT 1 FROM public.project_members AS member
                  WHERE member.tenant_id = candidate.tenant_id
                    AND member.project_id = project_row.id
                    AND member.user_id = candidate.actor_id
              )
              OR EXISTS (
                  SELECT 1 FROM public.runtime_project_access_grants AS grant_row
                  WHERE grant_row.tenant_id = candidate.tenant_id
                    AND grant_row.project_id = project_row.id
                    AND grant_row.actor_id = candidate.actor_id
              )
          )
        ORDER BY project_row.id
        FOR SHARE;
    END IF;
    PERFORM 1
    FROM public.tenant_members AS member
    WHERE member.tenant_id = candidate.tenant_id
      AND member.user_id = candidate.actor_id
    ORDER BY member.id
    FOR SHARE;
    PERFORM 1
    FROM public.project_members AS member
    WHERE member.tenant_id = candidate.tenant_id
      AND member.user_id = candidate.actor_id
    ORDER BY member.project_id, member.id
    FOR SHARE;
    PERFORM 1
    FROM public.runtime_project_access_grants AS grant_row
    WHERE grant_row.tenant_id = candidate.tenant_id
      AND grant_row.actor_id = candidate.actor_id
    ORDER BY grant_row.project_id, grant_row.id
    FOR SHARE;

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
    WHERE session_row.id = candidate.id
      AND session_row.session_token_hash = supplied_hash
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
      )
    FOR UPDATE OF session_row;

    IF NOT FOUND AND p_required THEN
        RAISE EXCEPTION 'auth_command_not_authorized'
            USING ERRCODE = 'GA003';
    END IF;
END;
$command_context$;

CREATE FUNCTION geno_v2_lock_auth_command_project(
    p_tenant_id uuid,
    p_project_id uuid
)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $lock_command_project$
BEGIN
    PERFORM 1
    FROM public.tenants AS tenant_row
    WHERE tenant_row.id = p_tenant_id
    FOR SHARE;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    PERFORM 1
    FROM public.projects AS project_row
    WHERE project_row.tenant_id = p_tenant_id
    ORDER BY project_row.id
    FOR NO KEY UPDATE;
    RETURN EXISTS (
        SELECT 1
        FROM public.projects AS project_row
        WHERE project_row.id = p_project_id
          AND project_row.tenant_id = p_tenant_id
    );
END;
$lock_command_project$;

CREATE FUNCTION geno_v2_auth_context_has_project_permission(
    p_project_scopes jsonb,
    p_project_id uuid,
    p_required_permission text
)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
SECURITY DEFINER
SET search_path = pg_catalog
AS $context_permission$
    SELECT EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_project_scopes) AS scope(value)
        WHERE scope.value->>'project_id' = p_project_id::text
          AND scope.value->'permissions' ? p_required_permission
    );
$context_permission$;

CREATE FUNCTION geno_v2_write_auth_command_audit(
    p_event_type text,
    p_tenant_id uuid,
    p_project_id uuid,
    p_actor_id text,
    p_actor_type text,
    p_target_type text,
    p_target_id text,
    p_input_refs jsonb,
    p_output_refs jsonb,
    p_reason text DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $command_audit$
BEGIN
    IF p_event_type IS NULL OR btrim(p_event_type) = ''
       OR p_actor_id IS NULL OR btrim(p_actor_id) = ''
       OR p_actor_type IS NULL
       OR p_actor_type NOT IN ('user', 'system', 'service')
       OR p_target_type IS NULL OR btrim(p_target_type) = ''
       OR p_target_id IS NULL OR btrim(p_target_id) = ''
       OR p_input_refs IS NULL OR p_output_refs IS NULL
       OR jsonb_typeof(p_input_refs) <> 'object'
       OR jsonb_typeof(p_output_refs) <> 'object' THEN
        RAISE EXCEPTION 'auth_command_invariant_violation'
            USING ERRCODE = 'GA006';
    END IF;
    INSERT INTO public.audit_events (
        tenant_id,
        project_id,
        event_type,
        actor_type,
        actor_id,
        target_type,
        target_id,
        input_refs,
        output_refs,
        method_version,
        reason
    ) VALUES (
        p_tenant_id,
        p_project_id,
        p_event_type,
        p_actor_type,
        p_actor_id,
        p_target_type,
        p_target_id,
        p_input_refs,
        p_output_refs,
        'auth_commands_v1',
        p_reason
    );
END;
$command_audit$;

CREATE FUNCTION geno_v2_preflight_auth_invitation(
    p_invitation_id uuid,
    p_invite_token_hash text,
    p_requested_surface text,
    p_source_fingerprint_hmac text
)
RETURNS TABLE (
    result_code text,
    compatibility text,
    requested_surface text,
    recommended_surface text,
    invitation_role text,
    policy_version text,
    invitation_request_count integer,
    source_request_count integer,
    retry_after_seconds integer,
    correlation_id uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $preflight$
DECLARE
    command_version constant text := 'auth-preflight-v1';
    invitation_limit constant integer := 20;
    source_limit constant integer := 100;
    window_seconds constant integer := 600;
    event_time timestamptz := clock_timestamp();
    invitation_bucket_key text;
    source_bucket_key text;
    invitation_limited boolean;
    source_limited boolean;
    invitation_retry integer;
    source_retry integer;
    invitation_row public.project_member_invitations%ROWTYPE;
BEGIN
    correlation_id := gen_random_uuid();
    IF p_invitation_id IS NULL
       OR p_invite_token_hash IS NULL
       OR p_invite_token_hash !~ '^[0-9a-f]{64}$'
       OR p_source_fingerprint_hmac IS NULL
       OR p_source_fingerprint_hmac !~ '^[0-9a-f]{64}$'
       OR p_requested_surface IS NULL
       OR p_requested_surface NOT IN ('admin', 'customer') THEN
        RAISE EXCEPTION 'auth_command_invalid_argument'
            USING ERRCODE = 'GA001';
    END IF;

    invitation_bucket_key := 'invitation:' || encode(public.digest(
        convert_to(command_version, 'UTF8')
        || decode('00', 'hex')
        || convert_to(p_invitation_id::text, 'UTF8')
        || decode('00', 'hex')
        || convert_to(p_invite_token_hash, 'UTF8'),
        'sha256'
    ), 'hex');
    source_bucket_key := 'source:' || encode(public.digest(
        convert_to(command_version, 'UTF8')
        || decode('00', 'hex')
        || convert_to(p_source_fingerprint_hmac, 'UTF8'),
        'sha256'
    ), 'hex');

    SELECT consumed.bucket_count, consumed.rate_limited, consumed.retry_after_seconds
    INTO invitation_request_count, invitation_limited, invitation_retry
    FROM public.geno_v2_consume_auth_preflight_bucket(
        invitation_bucket_key,
        invitation_limit,
        window_seconds,
        event_time
    ) AS consumed;
    SELECT consumed.bucket_count, consumed.rate_limited, consumed.retry_after_seconds
    INTO source_request_count, source_limited, source_retry
    FROM public.geno_v2_consume_auth_preflight_bucket(
        source_bucket_key,
        source_limit,
        window_seconds,
        event_time
    ) AS consumed;

    requested_surface := p_requested_surface;
    recommended_surface := NULL;
    invitation_role := NULL;
    policy_version := NULL;
    retry_after_seconds := NULL;
    IF invitation_limited OR source_limited THEN
        result_code := 'rate_limited';
        compatibility := 'invalid';
        retry_after_seconds := greatest(
            CASE WHEN invitation_limited THEN invitation_retry ELSE 0 END,
            CASE WHEN source_limited THEN source_retry ELSE 0 END
        );
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT invitation.* INTO invitation_row
    FROM public.project_member_invitations AS invitation
    WHERE invitation.id = p_invitation_id
      AND invitation.invite_token_hash = p_invite_token_hash;
    IF NOT FOUND THEN
        result_code := 'invalid';
        compatibility := 'invalid';
        RETURN NEXT;
        RETURN;
    END IF;

    IF NOT public.geno_v2_lock_auth_command_project(
        invitation_row.tenant_id,
        invitation_row.project_id
    ) THEN
        result_code := 'invalid';
        compatibility := 'invalid';
        RETURN NEXT;
        RETURN;
    END IF;
    SELECT invitation.* INTO invitation_row
    FROM public.project_member_invitations AS invitation
    WHERE invitation.id = p_invitation_id
      AND invitation.invite_token_hash = p_invite_token_hash
    FOR UPDATE;
    IF NOT FOUND THEN
        result_code := 'invalid';
        compatibility := 'invalid';
        RETURN NEXT;
        RETURN;
    END IF;

    IF invitation_row.status = 'pending'
       AND invitation_row.expires_at <= event_time THEN
        UPDATE public.project_member_invitations AS invitation
        SET status = 'expired',
            revoked_at = event_time,
            revoke_reason = 'member_invitation_expired',
            updated_at = greatest(
                event_time,
                invitation.updated_at + interval '1 microsecond'
            )
        WHERE invitation.id = invitation_row.id
        RETURNING invitation.* INTO invitation_row;
        PERFORM public.geno_v2_write_auth_command_audit(
            'auth.invitation.expired',
            invitation_row.tenant_id,
            invitation_row.project_id,
            'schema-v2-auth-preflight',
            'service',
            'project_member_invitation',
            invitation_row.id::text,
            '{}'::jsonb,
            jsonb_build_object(
                'status', 'expired',
                'correlation_id', correlation_id
            ),
            'member_invitation_expired'
        );
        result_code := 'invalid';
        compatibility := 'invalid';
        RETURN NEXT;
        RETURN;
    END IF;
    IF invitation_row.status <> 'pending'
       OR NOT EXISTS (
           SELECT 1
           FROM public.tenants AS tenant_row
           JOIN public.projects AS project_row
             ON project_row.tenant_id = tenant_row.id
           WHERE tenant_row.id = invitation_row.tenant_id
             AND project_row.id = invitation_row.project_id
             AND tenant_row.status = 'active'
             AND project_row.status <> 'archived'
       ) THEN
        result_code := 'invalid';
        compatibility := 'invalid';
        RETURN NEXT;
        RETURN;
    END IF;

    IF invitation_row.policy_version <> 'auth_surface_policy_v1' THEN
        result_code := 'policy_stale';
        compatibility := 'policy_stale';
        RETURN NEXT;
        RETURN;
    END IF;

    invitation_role := invitation_row.role;
    policy_version := invitation_row.policy_version;
    recommended_surface := invitation_row.audience;
    IF p_requested_surface = ANY(invitation_row.allowed_surfaces)
       AND p_requested_surface = invitation_row.audience THEN
        result_code := 'compatible';
        compatibility := 'compatible';
    ELSE
        result_code := 'surface_mismatch';
        compatibility := 'surface_mismatch';
    END IF;
    RETURN NEXT;
END;
$preflight$;

CREATE FUNCTION geno_v2_create_project_member_invitation(
    p_invitation_id uuid,
    p_project_id uuid,
    p_email text,
    p_role text,
    p_invite_token_hash text,
    p_expires_at timestamptz
)
RETURNS TABLE (
    result_code text,
    invitation_id uuid,
    tenant_id uuid,
    project_id uuid,
    email text,
    role text,
    status text,
    audience text,
    allowed_surfaces text[],
    policy_version text,
    expires_at timestamptz,
    correlation_id uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $create_invitation$
DECLARE
    event_time timestamptz := clock_timestamp();
    command_context record;
    existing_invitation public.project_member_invitations%ROWTYPE;
    inserted_invitation public.project_member_invitations%ROWTYPE;
    canonical_email text;
    invitation_audience text;
    row_inserted integer;
BEGIN
    correlation_id := gen_random_uuid();
    canonical_email := lower(btrim(p_email));
    IF p_invitation_id IS NULL OR p_project_id IS NULL
       OR p_email IS NULL OR canonical_email = '' OR p_email <> canonical_email
       OR p_role IS NULL OR p_role NOT IN (
           'project_owner', 'analyst', 'reviewer', 'knowledge_architect',
           'content_operator', 'client_viewer'
       )
       OR p_invite_token_hash IS NULL
       OR p_invite_token_hash !~ '^[0-9a-f]{64}$'
       OR p_expires_at IS NULL THEN
        RAISE EXCEPTION 'auth_command_invalid_argument'
            USING ERRCODE = 'GA001';
    END IF;
    PERFORM public.geno_v2_require_auth_writes_enabled();
    SELECT * INTO command_context
    FROM public.geno_v2_lock_auth_command_context(true, true);
    IF NOT public.geno_v2_auth_context_has_project_permission(
        command_context.project_scopes,
        p_project_id,
        'member.manage'
    ) THEN
        RAISE EXCEPTION 'auth_command_not_authorized'
            USING ERRCODE = 'GA003';
    END IF;
    IF NOT public.geno_v2_lock_auth_command_project(
        command_context.tenant_id,
        p_project_id
    ) OR NOT EXISTS (
        SELECT 1 FROM public.projects AS project_row
        WHERE project_row.id = p_project_id
          AND project_row.tenant_id = command_context.tenant_id
          AND project_row.status <> 'archived'
    ) THEN
        RAISE EXCEPTION 'auth_command_not_authorized'
            USING ERRCODE = 'GA003';
    END IF;

    invitation_audience := CASE
        WHEN p_role = 'client_viewer' THEN 'customer'
        ELSE 'admin'
    END;
    SELECT invitation.* INTO existing_invitation
    FROM public.project_member_invitations AS invitation
    WHERE invitation.id = p_invitation_id
    FOR UPDATE;
    IF FOUND THEN
        IF existing_invitation.tenant_id <> command_context.tenant_id
           OR existing_invitation.project_id <> p_project_id
           OR existing_invitation.email <> canonical_email
           OR existing_invitation.role <> p_role
           OR existing_invitation.invite_token_hash <> p_invite_token_hash
           OR existing_invitation.audience <> invitation_audience
           OR existing_invitation.allowed_surfaces
                <> ARRAY[invitation_audience]::text[]
           OR existing_invitation.policy_version <> 'auth_surface_policy_v1'
           OR existing_invitation.invited_by <> command_context.actor_id
           OR existing_invitation.expires_at <> p_expires_at THEN
            RAISE EXCEPTION 'auth_command_idempotency_conflict'
                USING ERRCODE = 'GA004';
        END IF;
        IF existing_invitation.status = 'pending'
           AND existing_invitation.expires_at <= event_time THEN
            UPDATE public.project_member_invitations AS invitation
            SET status = 'expired',
                revoked_at = event_time,
                revoke_reason = 'member_invitation_expired',
                updated_at = greatest(
                    event_time,
                    invitation.updated_at + interval '1 microsecond'
                )
            WHERE invitation.id = existing_invitation.id
            RETURNING invitation.* INTO inserted_invitation;
            PERFORM public.geno_v2_write_auth_command_audit(
                'auth.invitation.expired',
                inserted_invitation.tenant_id,
                inserted_invitation.project_id,
                command_context.actor_id,
                'user',
                'project_member_invitation',
                inserted_invitation.id::text,
                '{}'::jsonb,
                jsonb_build_object(
                    'status', 'expired',
                    'correlation_id', correlation_id
                ),
                'member_invitation_expired'
            );
            result_code := 'expired';
        ELSIF existing_invitation.status = 'pending' THEN
            inserted_invitation := existing_invitation;
            result_code := 'replayed';
        ELSIF existing_invitation.status = 'expired' THEN
            inserted_invitation := existing_invitation;
            result_code := 'expired';
        ELSE
            RAISE EXCEPTION 'auth_command_state_conflict'
                USING ERRCODE = 'GA005';
        END IF;
    ELSE
        IF p_expires_at <= event_time
           OR p_expires_at > event_time + interval '30 days' THEN
            RAISE EXCEPTION 'auth_command_invalid_argument'
                USING ERRCODE = 'GA001';
        END IF;
        SELECT invitation.* INTO existing_invitation
        FROM public.project_member_invitations AS invitation
        WHERE invitation.tenant_id = command_context.tenant_id
          AND invitation.project_id = p_project_id
          AND invitation.email = canonical_email
          AND invitation.status = 'pending'
        FOR UPDATE;
        IF FOUND THEN
            IF existing_invitation.expires_at > event_time THEN
                RAISE EXCEPTION 'auth_command_state_conflict'
                    USING ERRCODE = 'GA005';
            END IF;
            UPDATE public.project_member_invitations AS invitation
            SET status = 'expired',
                revoked_at = event_time,
                revoke_reason = 'member_invitation_expired',
                updated_at = greatest(
                    event_time,
                    invitation.updated_at + interval '1 microsecond'
                )
            WHERE invitation.id = existing_invitation.id;
            PERFORM public.geno_v2_write_auth_command_audit(
                'auth.invitation.expired',
                existing_invitation.tenant_id,
                existing_invitation.project_id,
                command_context.actor_id,
                'user',
                'project_member_invitation',
                existing_invitation.id::text,
                '{}'::jsonb,
                jsonb_build_object(
                    'status', 'expired',
                    'correlation_id', correlation_id
                ),
                'member_invitation_expired'
            );
        END IF;
        PERFORM 1
        FROM public.project_members AS member
        WHERE member.tenant_id = command_context.tenant_id
          AND member.project_id = p_project_id
          AND member.user_id = canonical_email;
        IF FOUND THEN
            RAISE EXCEPTION 'auth_command_state_conflict'
                USING ERRCODE = 'GA005';
        END IF;

        BEGIN
            INSERT INTO public.project_member_invitations (
                id,
                tenant_id,
                project_id,
                email,
                role,
                invite_token_hash,
                audience,
                allowed_surfaces,
                policy_version,
                invited_by,
                expires_at,
                created_at,
                updated_at
            ) VALUES (
                p_invitation_id,
                command_context.tenant_id,
                p_project_id,
                canonical_email,
                p_role,
                p_invite_token_hash,
                invitation_audience,
                ARRAY[invitation_audience]::text[],
                'auth_surface_policy_v1',
                command_context.actor_id,
                p_expires_at,
                event_time,
                event_time
            )
            ON CONFLICT (id) DO NOTHING
            RETURNING * INTO inserted_invitation;
            GET DIAGNOSTICS row_inserted = ROW_COUNT;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'auth_command_state_conflict'
                USING ERRCODE = 'GA005';
        END;

        IF row_inserted = 0 THEN
            SELECT invitation.* INTO existing_invitation
            FROM public.project_member_invitations AS invitation
            WHERE invitation.id = p_invitation_id
            FOR UPDATE;
            IF NOT FOUND
               OR existing_invitation.tenant_id <> command_context.tenant_id
               OR existing_invitation.project_id <> p_project_id
               OR existing_invitation.email <> canonical_email
               OR existing_invitation.role <> p_role
               OR existing_invitation.status <> 'pending'
               OR existing_invitation.invite_token_hash <> p_invite_token_hash
               OR existing_invitation.audience <> invitation_audience
               OR existing_invitation.allowed_surfaces
                    <> ARRAY[invitation_audience]::text[]
               OR existing_invitation.policy_version <> 'auth_surface_policy_v1'
               OR existing_invitation.invited_by <> command_context.actor_id
               OR existing_invitation.expires_at <> p_expires_at THEN
                RAISE EXCEPTION 'auth_command_idempotency_conflict'
                    USING ERRCODE = 'GA004';
            END IF;
            inserted_invitation := existing_invitation;
            result_code := 'replayed';
        ELSE
            result_code := 'created';
            PERFORM public.geno_v2_write_auth_command_audit(
                'auth.invitation.created',
                command_context.tenant_id,
                p_project_id,
                command_context.actor_id,
                'user',
                'project_member_invitation',
                p_invitation_id::text,
                jsonb_build_object('role', p_role),
                jsonb_build_object(
                    'status', 'pending',
                    'correlation_id', correlation_id
                ),
                NULL
            );
        END IF;
    END IF;

    invitation_id := inserted_invitation.id;
    tenant_id := inserted_invitation.tenant_id;
    project_id := inserted_invitation.project_id;
    email := inserted_invitation.email;
    role := inserted_invitation.role;
    status := inserted_invitation.status;
    audience := inserted_invitation.audience;
    allowed_surfaces := inserted_invitation.allowed_surfaces;
    policy_version := inserted_invitation.policy_version;
    expires_at := inserted_invitation.expires_at;
    RETURN NEXT;
END;
$create_invitation$;

CREATE FUNCTION geno_v2_revoke_project_member_invitation(
    p_invitation_id uuid,
    p_reason_code text
)
RETURNS TABLE (
    result_code text,
    invitation_id uuid,
    status text,
    changed_at timestamptz,
    correlation_id uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $revoke_invitation$
DECLARE
    event_time timestamptz := clock_timestamp();
    command_context record;
    invitation_row public.project_member_invitations%ROWTYPE;
BEGIN
    correlation_id := gen_random_uuid();
    IF p_invitation_id IS NULL OR p_reason_code IS NULL OR p_reason_code NOT IN (
        'member_invitation_cancelled',
        'member_invitation_replaced',
        'member_invitation_security'
    ) THEN
        RAISE EXCEPTION 'auth_command_invalid_argument'
            USING ERRCODE = 'GA001';
    END IF;
    SELECT * INTO command_context
    FROM public.geno_v2_lock_auth_command_context(true, true);

    SELECT invitation.* INTO invitation_row
    FROM public.project_member_invitations AS invitation
    WHERE invitation.id = p_invitation_id
    FOR UPDATE;
    IF NOT FOUND
       OR invitation_row.tenant_id <> command_context.tenant_id
       OR NOT public.geno_v2_auth_context_has_project_permission(
           command_context.project_scopes,
           invitation_row.project_id,
           'member.manage'
       ) THEN
        RAISE EXCEPTION 'auth_command_not_authorized'
            USING ERRCODE = 'GA003';
    END IF;

    invitation_id := invitation_row.id;
    IF invitation_row.status <> 'pending' THEN
        result_code := 'already_terminal';
        status := invitation_row.status;
        changed_at := coalesce(
            invitation_row.accepted_at,
            invitation_row.revoked_at,
            invitation_row.updated_at
        );
        RETURN NEXT;
        RETURN;
    END IF;

    UPDATE public.project_member_invitations AS invitation
    SET status = 'revoked',
        revoked_at = event_time,
        revoke_reason = p_reason_code,
        updated_at = greatest(
            event_time,
            invitation.updated_at + interval '1 microsecond'
        )
    WHERE invitation.id = p_invitation_id
    RETURNING invitation.* INTO invitation_row;
    PERFORM public.geno_v2_write_auth_command_audit(
        'auth.invitation.revoked',
        invitation_row.tenant_id,
        invitation_row.project_id,
        command_context.actor_id,
        'user',
        'project_member_invitation',
        invitation_row.id::text,
        '{}'::jsonb,
        jsonb_build_object(
            'status', 'revoked',
            'correlation_id', correlation_id
        ),
        p_reason_code
    );
    result_code := 'revoked';
    status := invitation_row.status;
    changed_at := invitation_row.revoked_at;
    RETURN NEXT;
END;
$revoke_invitation$;

CREATE FUNCTION geno_v2_expire_project_member_invitation(p_invitation_id uuid)
RETURNS TABLE (
    result_code text,
    invitation_id uuid,
    status text,
    changed_at timestamptz,
    correlation_id uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $expire_invitation$
DECLARE
    event_time timestamptz := clock_timestamp();
    command_context record;
    invitation_row public.project_member_invitations%ROWTYPE;
BEGIN
    correlation_id := gen_random_uuid();
    IF p_invitation_id IS NULL THEN
        RAISE EXCEPTION 'auth_command_invalid_argument'
            USING ERRCODE = 'GA001';
    END IF;
    SELECT * INTO command_context
    FROM public.geno_v2_lock_auth_command_context(true, true);

    SELECT invitation.* INTO invitation_row
    FROM public.project_member_invitations AS invitation
    WHERE invitation.id = p_invitation_id
    FOR UPDATE;
    IF NOT FOUND
       OR invitation_row.tenant_id <> command_context.tenant_id
       OR NOT public.geno_v2_auth_context_has_project_permission(
           command_context.project_scopes,
           invitation_row.project_id,
           'member.manage'
       ) THEN
        RAISE EXCEPTION 'auth_command_not_authorized'
            USING ERRCODE = 'GA003';
    END IF;

    invitation_id := invitation_row.id;
    IF invitation_row.status <> 'pending' THEN
        result_code := 'already_terminal';
        status := invitation_row.status;
        changed_at := coalesce(
            invitation_row.accepted_at,
            invitation_row.revoked_at,
            invitation_row.updated_at
        );
        RETURN NEXT;
        RETURN;
    END IF;
    IF invitation_row.expires_at > event_time THEN
        RAISE EXCEPTION 'auth_command_state_conflict'
            USING ERRCODE = 'GA005';
    END IF;

    UPDATE public.project_member_invitations AS invitation
    SET status = 'expired',
        revoked_at = event_time,
        revoke_reason = 'member_invitation_expired',
        updated_at = greatest(
            event_time,
            invitation.updated_at + interval '1 microsecond'
        )
    WHERE invitation.id = p_invitation_id
    RETURNING invitation.* INTO invitation_row;
    PERFORM public.geno_v2_write_auth_command_audit(
        'auth.invitation.expired',
        invitation_row.tenant_id,
        invitation_row.project_id,
        command_context.actor_id,
        'user',
        'project_member_invitation',
        invitation_row.id::text,
        '{}'::jsonb,
        jsonb_build_object(
            'status', 'expired',
            'correlation_id', correlation_id
        ),
        'member_invitation_expired'
    );
    result_code := 'expired';
    status := invitation_row.status;
    changed_at := invitation_row.revoked_at;
    RETURN NEXT;
END;
$expire_invitation$;

CREATE FUNCTION geno_v2_build_locked_auth_scope(
    p_tenant_id uuid,
    p_actor_id text
)
RETURNS TABLE (
    project_ids jsonb,
    tenant_roles jsonb,
    project_scopes jsonb,
    flat_roles jsonb,
    flat_permissions jsonb
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $build_scope$
DECLARE
    resolved_tenant_roles jsonb;
BEGIN
    PERFORM 1
    FROM public.tenants AS tenant_row
    WHERE tenant_row.id = p_tenant_id
      AND tenant_row.status = 'active'
    FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'auth_command_invariant_violation'
            USING ERRCODE = 'GA006';
    END IF;
    PERFORM 1
    FROM public.projects AS project_row
    WHERE project_row.tenant_id = p_tenant_id
    ORDER BY project_row.id
    FOR SHARE;
    PERFORM 1
    FROM public.tenant_members AS member
    WHERE member.tenant_id = p_tenant_id
      AND member.user_id = p_actor_id
    ORDER BY member.id
    FOR SHARE;
    PERFORM 1
    FROM public.project_members AS member
    WHERE member.tenant_id = p_tenant_id
      AND member.user_id = p_actor_id
    ORDER BY member.project_id, member.id
    FOR SHARE;
    PERFORM 1
    FROM public.runtime_project_access_grants AS grant_row
    WHERE grant_row.tenant_id = p_tenant_id
      AND grant_row.actor_id = p_actor_id
    ORDER BY grant_row.project_id, grant_row.id
    FOR SHARE;

    SELECT coalesce(jsonb_agg(member.role ORDER BY member.role), '[]'::jsonb)
    INTO resolved_tenant_roles
    FROM public.tenant_members AS member
    WHERE member.tenant_id = p_tenant_id
      AND member.user_id = p_actor_id
      AND member.status = 'active';

    RETURN QUERY
    WITH backed_roles AS (
        SELECT
            member.project_id,
            member.role AS role_name,
            'direct_member'::text AS scope_source
        FROM public.project_members AS member
        JOIN public.projects AS project_row
          ON project_row.id = member.project_id
         AND project_row.tenant_id = member.tenant_id
         AND project_row.status <> 'archived'
        WHERE member.tenant_id = p_tenant_id
          AND member.user_id = p_actor_id
          AND member.status = 'active'
        UNION ALL
        SELECT
            grant_row.project_id,
            grant_row.canonical_role,
            'tenant_role'::text
        FROM public.runtime_project_access_grants AS grant_row
        JOIN public.projects AS project_row
          ON project_row.id = grant_row.project_id
         AND project_row.tenant_id = grant_row.tenant_id
         AND project_row.status <> 'archived'
        WHERE grant_row.tenant_id = p_tenant_id
          AND grant_row.actor_id = p_actor_id
          AND grant_row.status = 'active'
    ),
    scoped_projects AS (
        SELECT DISTINCT backed.project_id
        FROM backed_roles AS backed
    ),
    scopes AS (
        SELECT
            scoped.project_id,
            (
                SELECT jsonb_agg(role_item.role_name ORDER BY role_item.role_name)
                FROM (
                    SELECT DISTINCT backed.role_name
                    FROM backed_roles AS backed
                    WHERE backed.project_id = scoped.project_id
                ) AS role_item
            ) AS roles,
            (
                SELECT jsonb_agg(permission_item.permission_name
                    ORDER BY permission_item.permission_name)
                FROM (
                    SELECT DISTINCT permission.permission_name
                    FROM backed_roles AS backed
                    CROSS JOIN LATERAL unnest(
                        public.geno_v2_permissions_for_role(backed.role_name)
                    ) AS permission(permission_name)
                    WHERE backed.project_id = scoped.project_id
                ) AS permission_item
            ) AS permissions,
            (
                SELECT jsonb_agg(capability_item.capability
                    ORDER BY capability_item.capability)
                FROM (
                    SELECT DISTINCT CASE
                        WHEN backed.role_name = 'client_viewer'
                            THEN 'portal.customer.access'
                        ELSE 'portal.admin.access'
                    END AS capability
                    FROM backed_roles AS backed
                    WHERE backed.project_id = scoped.project_id
                ) AS capability_item
            ) AS portal_capabilities,
            (
                SELECT jsonb_agg(source_item.scope_source
                    ORDER BY source_item.scope_source)
                FROM (
                    SELECT DISTINCT backed.scope_source
                    FROM backed_roles AS backed
                    WHERE backed.project_id = scoped.project_id
                ) AS source_item
            ) AS scope_sources
        FROM scoped_projects AS scoped
    ),
    all_roles AS (
        SELECT tenant_role.role_name
        FROM jsonb_array_elements_text(resolved_tenant_roles)
            AS tenant_role(role_name)
        UNION
        SELECT backed.role_name FROM backed_roles AS backed
    ),
    all_permissions AS (
        SELECT DISTINCT permission.permission_name
        FROM backed_roles AS backed
        CROSS JOIN LATERAL unnest(
            public.geno_v2_permissions_for_role(backed.role_name)
        ) AS permission(permission_name)
    )
    SELECT
        coalesce((
            SELECT jsonb_agg(scoped.project_id::text ORDER BY scoped.project_id::text)
            FROM scoped_projects AS scoped
        ), '[]'::jsonb),
        resolved_tenant_roles,
        coalesce((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'project_id', scope_row.project_id::text,
                    'roles', scope_row.roles,
                    'permissions', scope_row.permissions,
                    'portal_capabilities', scope_row.portal_capabilities,
                    'scope_sources', scope_row.scope_sources
                ) ORDER BY scope_row.project_id::text
            )
            FROM scopes AS scope_row
        ), '[]'::jsonb),
        coalesce((
            SELECT jsonb_agg(role_item.role_name ORDER BY role_item.role_name)
            FROM all_roles AS role_item
        ), '[]'::jsonb),
        coalesce((
            SELECT jsonb_agg(permission_item.permission_name
                ORDER BY permission_item.permission_name)
            FROM all_permissions AS permission_item
        ), '[]'::jsonb);
END;
$build_scope$;

CREATE FUNCTION geno_v2_redeem_auth_invitation(
    p_attempt_id uuid,
    p_session_id uuid,
    p_invitation_id uuid,
    p_invite_token_hash text,
    p_requested_surface text,
    p_idempotency_key_hash text,
    p_session_token_hash text,
    p_session_expires_at timestamptz,
    p_delivery_ciphertext bytea,
    p_delivery_key_id text,
    p_delivery_nonce bytea,
    p_delivery_expires_at timestamptz
)
RETURNS TABLE (
    result_code text,
    attempt_id uuid,
    session_id uuid,
    actor_id text,
    tenant_id uuid,
    project_ids jsonb,
    tenant_roles jsonb,
    project_scopes jsonb,
    delivery_ciphertext bytea,
    delivery_key_id text,
    delivery_nonce bytea,
    delivery_expires_at timestamptz,
    replay_count integer,
    recommended_surface text,
    correlation_id uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $redeem$
DECLARE
    event_time timestamptz := clock_timestamp();
    request_fingerprint text;
    invitation_row public.project_member_invitations%ROWTYPE;
    attempt_row public.auth_invitation_redemption_attempts%ROWTYPE;
    session_row public.runtime_sessions%ROWTYPE;
    member_row public.project_members%ROWTYPE;
    scope_snapshot record;
    pending_reauth record;
    resolved_reauth_count integer := 0;
    security_state_changed boolean := false;
    auth_writes_enabled boolean;
BEGIN
    correlation_id := gen_random_uuid();
    IF p_invitation_id IS NULL
       OR p_invite_token_hash IS NULL
       OR p_invite_token_hash !~ '^[0-9a-f]{64}$'
       OR p_requested_surface IS NULL
       OR p_requested_surface NOT IN ('admin', 'customer')
       OR p_idempotency_key_hash IS NULL
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'auth_command_invalid_argument'
            USING ERRCODE = 'GA001';
    END IF;
    auth_writes_enabled := public.geno_v2_lock_auth_write_control();
    request_fingerprint := public.geno_v2_auth_redeem_request_hash(
        p_invitation_id,
        p_invite_token_hash,
        p_requested_surface
    );

    SELECT invitation.* INTO invitation_row
    FROM public.project_member_invitations AS invitation
    WHERE invitation.id = p_invitation_id;
    IF NOT FOUND OR invitation_row.invite_token_hash <> p_invite_token_hash THEN
        result_code := 'invalid';
        RETURN NEXT;
        RETURN;
    END IF;
    IF NOT public.geno_v2_lock_auth_command_project(
        invitation_row.tenant_id,
        invitation_row.project_id
    ) THEN
        result_code := 'invalid';
        RETURN NEXT;
        RETURN;
    END IF;
    SELECT invitation.* INTO invitation_row
    FROM public.project_member_invitations AS invitation
    WHERE invitation.id = p_invitation_id
    FOR UPDATE;
    IF NOT FOUND OR invitation_row.invite_token_hash <> p_invite_token_hash THEN
        result_code := 'invalid';
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT attempt.* INTO attempt_row
    FROM public.auth_invitation_redemption_attempts AS attempt
    WHERE attempt.invitation_id = p_invitation_id
      AND attempt.idempotency_key_hash = p_idempotency_key_hash
    FOR UPDATE;
    IF FOUND THEN
        IF attempt_row.request_hash <> request_fingerprint
           OR attempt_row.token_fingerprint <> p_invite_token_hash
           OR attempt_row.requested_surface <> p_requested_surface THEN
            RAISE EXCEPTION 'auth_command_idempotency_conflict'
                USING ERRCODE = 'GA004';
        END IF;
        IF attempt_row.status <> 'succeeded' THEN
            RAISE EXCEPTION 'auth_command_state_conflict'
                USING ERRCODE = 'GA005';
        END IF;
        IF invitation_row.status <> 'accepted'
           OR invitation_row.accepted_by_attempt_id <> attempt_row.id
           OR attempt_row.session_id IS NULL THEN
            RAISE EXCEPTION 'auth_command_invariant_violation'
                USING ERRCODE = 'GA006';
        END IF;

        SELECT session.* INTO session_row
        FROM public.runtime_sessions AS session
        WHERE session.id = attempt_row.session_id
          AND session.redemption_attempt_id = attempt_row.id
        FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'auth_command_invariant_violation'
                USING ERRCODE = 'GA006';
        END IF;

        IF session_row.status <> 'active' OR session_row.expires_at <= event_time THEN
            IF session_row.status = 'active' AND session_row.expires_at <= event_time THEN
                UPDATE public.runtime_sessions AS session
                SET status = 'expired',
                    updated_at = greatest(
                        event_time,
                        session.updated_at + interval '1 microsecond'
                    )
                WHERE session.id = session_row.id;
                security_state_changed := true;
            END IF;
            IF attempt_row.delivery_ciphertext IS NOT NULL THEN
                UPDATE public.auth_invitation_redemption_attempts AS attempt
                SET delivery_ciphertext = NULL,
                    delivery_key_id = NULL,
                    delivery_nonce = NULL,
                    secret_erased_at = coalesce(attempt.secret_erased_at, event_time),
                    updated_at = greatest(
                        event_time,
                        attempt.updated_at + interval '1 microsecond'
                    )
                WHERE attempt.id = attempt_row.id;
                security_state_changed := true;
            END IF;
            IF security_state_changed THEN
                PERFORM public.geno_v2_write_auth_command_audit(
                    'auth.redemption.delivery_erased',
                    invitation_row.tenant_id,
                    invitation_row.project_id,
                    invitation_row.email,
                    'user',
                    'auth_redemption_attempt',
                    attempt_row.id::text,
                    '{}'::jsonb,
                    jsonb_build_object(
                        'result_code', 'session_unavailable',
                        'correlation_id', correlation_id
                    ),
                    'session_unavailable'
                );
            END IF;
            result_code := 'session_unavailable';
            RETURN NEXT;
            RETURN;
        END IF;
        IF attempt_row.delivery_ciphertext IS NULL
           OR attempt_row.delivery_key_id IS NULL
           OR attempt_row.delivery_nonce IS NULL
           OR attempt_row.delivery_expires_at IS NULL THEN
            result_code := 'session_unavailable';
            RETURN NEXT;
            RETURN;
        END IF;
        IF attempt_row.delivery_expires_at <= event_time THEN
            UPDATE public.auth_invitation_redemption_attempts AS attempt
            SET delivery_ciphertext = NULL,
                delivery_key_id = NULL,
                delivery_nonce = NULL,
                secret_erased_at = coalesce(attempt.secret_erased_at, event_time),
                updated_at = greatest(
                    event_time,
                    attempt.updated_at + interval '1 microsecond'
                )
            WHERE attempt.id = attempt_row.id;
            PERFORM public.geno_v2_write_auth_command_audit(
                'auth.redemption.delivery_erased',
                invitation_row.tenant_id,
                invitation_row.project_id,
                invitation_row.email,
                'user',
                'auth_redemption_attempt',
                attempt_row.id::text,
                '{}'::jsonb,
                jsonb_build_object(
                    'result_code', 'recovery_expired',
                    'correlation_id', correlation_id
                ),
                'recovery_expired'
            );
            result_code := 'recovery_expired';
            RETURN NEXT;
            RETURN;
        END IF;
        IF attempt_row.replay_count >= 3 THEN
            UPDATE public.auth_invitation_redemption_attempts AS attempt
            SET delivery_ciphertext = NULL,
                delivery_key_id = NULL,
                delivery_nonce = NULL,
                secret_erased_at = coalesce(attempt.secret_erased_at, event_time),
                updated_at = greatest(
                    event_time,
                    attempt.updated_at + interval '1 microsecond'
                )
            WHERE attempt.id = attempt_row.id;
            PERFORM public.geno_v2_write_auth_command_audit(
                'auth.redemption.delivery_erased',
                invitation_row.tenant_id,
                invitation_row.project_id,
                invitation_row.email,
                'user',
                'auth_redemption_attempt',
                attempt_row.id::text,
                '{}'::jsonb,
                jsonb_build_object(
                    'result_code', 'replay_limit_exceeded',
                    'correlation_id', correlation_id
                ),
                'replay_limit_exceeded'
            );
            result_code := 'replay_limit_exceeded';
            RETURN NEXT;
            RETURN;
        END IF;

        IF NOT auth_writes_enabled THEN
            RAISE EXCEPTION 'auth_writes_temporarily_disabled'
                USING ERRCODE = '42501',
                      DETAIL = 'Privilege-expanding auth writes are disabled.';
        END IF;
        UPDATE public.auth_invitation_redemption_attempts AS attempt
        SET replay_count = attempt.replay_count + 1,
            updated_at = greatest(
                event_time,
                attempt.updated_at + interval '1 microsecond'
            )
        WHERE attempt.id = attempt_row.id
        RETURNING attempt.* INTO attempt_row;
        PERFORM public.geno_v2_write_auth_command_audit(
            'auth.redemption.replayed',
            invitation_row.tenant_id,
            invitation_row.project_id,
            invitation_row.email,
            'user',
            'auth_redemption_attempt',
            attempt_row.id::text,
            jsonb_build_object('session_id', session_row.id),
            jsonb_build_object(
                'replay_count', attempt_row.replay_count,
                'correlation_id', correlation_id
            ),
            NULL
        );
        result_code := 'replayed';
        attempt_id := attempt_row.id;
        session_id := session_row.id;
        actor_id := session_row.actor_id;
        tenant_id := session_row.tenant_id;
        project_ids := session_row.project_ids;
        tenant_roles := session_row.tenant_roles;
        project_scopes := session_row.project_scopes;
        delivery_ciphertext := attempt_row.delivery_ciphertext;
        delivery_key_id := attempt_row.delivery_key_id;
        delivery_nonce := attempt_row.delivery_nonce;
        delivery_expires_at := attempt_row.delivery_expires_at;
        replay_count := attempt_row.replay_count;
        RETURN NEXT;
        RETURN;
    END IF;

    IF invitation_row.status = 'pending'
       AND invitation_row.expires_at <= event_time THEN
        UPDATE public.project_member_invitations AS invitation
        SET status = 'expired',
            revoked_at = event_time,
            revoke_reason = 'member_invitation_expired',
            updated_at = greatest(
                event_time,
                invitation.updated_at + interval '1 microsecond'
            )
        WHERE invitation.id = invitation_row.id;
        PERFORM public.geno_v2_write_auth_command_audit(
            'auth.invitation.expired',
            invitation_row.tenant_id,
            invitation_row.project_id,
            'schema-v2-auth-redeem',
            'service',
            'project_member_invitation',
            invitation_row.id::text,
            '{}'::jsonb,
            jsonb_build_object(
                'status', 'expired',
                'correlation_id', correlation_id
            ),
            'member_invitation_expired'
        );
        result_code := 'invalid';
        RETURN NEXT;
        RETURN;
    END IF;
    IF invitation_row.status = 'accepted' THEN
        RAISE EXCEPTION 'auth_command_state_conflict'
            USING ERRCODE = 'GA005';
    END IF;
    IF invitation_row.status <> 'pending'
       OR invitation_row.policy_version <> 'auth_surface_policy_v1'
       OR NOT EXISTS (
           SELECT 1
           FROM public.tenants AS tenant_row
           JOIN public.projects AS project_row
             ON project_row.tenant_id = tenant_row.id
           WHERE tenant_row.id = invitation_row.tenant_id
             AND project_row.id = invitation_row.project_id
             AND tenant_row.status = 'active'
             AND project_row.status <> 'archived'
       ) THEN
        result_code := 'invalid';
        RETURN NEXT;
        RETURN;
    END IF;
    IF p_requested_surface <> invitation_row.audience
       OR NOT (p_requested_surface = ANY(invitation_row.allowed_surfaces)) THEN
        result_code := 'surface_mismatch';
        recommended_surface := invitation_row.audience;
        RETURN NEXT;
        RETURN;
    END IF;

    IF p_attempt_id IS NULL OR p_session_id IS NULL
       OR p_session_token_hash IS NULL
       OR p_session_token_hash !~ '^[0-9a-f]{64}$'
       OR p_session_expires_at IS NULL
       OR p_session_expires_at <= event_time + interval '60 seconds'
       OR p_session_expires_at > event_time + interval '30 days'
       OR p_delivery_ciphertext IS NULL
       OR octet_length(p_delivery_ciphertext) NOT BETWEEN 1 AND 16384
       OR p_delivery_key_id IS NULL
       OR p_delivery_key_id !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'
       OR p_delivery_nonce IS NULL
       OR octet_length(p_delivery_nonce) <> 12
       OR p_delivery_expires_at IS NULL
       OR p_delivery_expires_at <= event_time
       OR p_delivery_expires_at > event_time + interval '1 hour'
       OR p_delivery_expires_at > p_session_expires_at THEN
        RAISE EXCEPTION 'auth_command_invalid_argument'
            USING ERRCODE = 'GA001';
    END IF;
    IF NOT auth_writes_enabled THEN
        RAISE EXCEPTION 'auth_writes_temporarily_disabled'
            USING ERRCODE = '42501',
                  DETAIL = 'Privilege-expanding auth writes are disabled.';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.auth_invitation_redemption_attempts AS attempt
        WHERE attempt.id = p_attempt_id
    ) OR EXISTS (
        SELECT 1 FROM public.runtime_sessions AS session
        WHERE session.id = p_session_id
           OR session.session_token_hash = p_session_token_hash
    ) THEN
        RAISE EXCEPTION 'auth_command_idempotency_conflict'
            USING ERRCODE = 'GA004';
    END IF;

    BEGIN
        INSERT INTO public.auth_invitation_redemption_attempts (
            id,
            tenant_id,
            project_id,
            invitation_id,
            requested_surface,
            idempotency_key_hash,
            request_hash,
            token_fingerprint,
            created_at,
            updated_at
        ) VALUES (
            p_attempt_id,
            invitation_row.tenant_id,
            invitation_row.project_id,
            invitation_row.id,
            p_requested_surface,
            p_idempotency_key_hash,
            request_fingerprint,
            p_invite_token_hash,
            event_time,
            event_time
        );
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'auth_command_idempotency_conflict'
            USING ERRCODE = 'GA004';
    END;

    SELECT * INTO scope_snapshot
    FROM public.geno_v2_build_locked_auth_scope(
        invitation_row.tenant_id,
        invitation_row.email
    );
    SELECT member.* INTO member_row
    FROM public.project_members AS member
    WHERE member.tenant_id = invitation_row.tenant_id
      AND member.project_id = invitation_row.project_id
      AND member.user_id = invitation_row.email;
    IF FOUND THEN
        IF member_row.status <> 'active' OR member_row.role <> invitation_row.role THEN
            RAISE EXCEPTION 'auth_command_state_conflict'
                USING ERRCODE = 'GA005';
        END IF;
    ELSE
        BEGIN
            INSERT INTO public.project_members (
                tenant_id,
                project_id,
                user_id,
                role,
                status,
                invited_by,
                created_at,
                updated_at
            ) VALUES (
                invitation_row.tenant_id,
                invitation_row.project_id,
                invitation_row.email,
                invitation_row.role,
                'active',
                invitation_row.invited_by,
                event_time,
                event_time
            );
        EXCEPTION WHEN unique_violation THEN
            SELECT member.* INTO member_row
            FROM public.project_members AS member
            WHERE member.tenant_id = invitation_row.tenant_id
              AND member.project_id = invitation_row.project_id
              AND member.user_id = invitation_row.email;
            IF NOT FOUND
               OR member_row.status <> 'active'
               OR member_row.role <> invitation_row.role THEN
                RAISE EXCEPTION 'auth_command_state_conflict'
                    USING ERRCODE = 'GA005';
            END IF;
        END;
    END IF;

    SELECT * INTO scope_snapshot
    FROM public.geno_v2_build_locked_auth_scope(
        invitation_row.tenant_id,
        invitation_row.email
    );
    IF NOT (scope_snapshot.project_ids ? invitation_row.project_id::text)
       OR NOT EXISTS (
           SELECT 1
           FROM jsonb_array_elements(scope_snapshot.project_scopes) AS scope(value)
           WHERE scope.value->>'project_id' = invitation_row.project_id::text
             AND scope.value->'roles' ? invitation_row.role
             AND scope.value->'portal_capabilities'
                ? ('portal.' || invitation_row.audience || '.access')
       ) THEN
        RAISE EXCEPTION 'auth_command_invariant_violation'
            USING ERRCODE = 'GA006';
    END IF;

    BEGIN
    INSERT INTO public.runtime_sessions (
        id,
        session_token_hash,
        actor_id,
        actor_type,
        tenant_id,
        project_ids,
        roles,
        permissions,
        tenant_roles,
        project_scopes,
        scope_version,
        authz_policy_version,
        redemption_attempt_id,
        auth_method,
        status,
        issued_by,
        issued_at,
        expires_at,
        metadata,
        created_at,
        updated_at
    ) VALUES (
        p_session_id,
        p_session_token_hash,
        invitation_row.email,
        'user',
        invitation_row.tenant_id,
        scope_snapshot.project_ids,
        scope_snapshot.flat_roles,
        scope_snapshot.flat_permissions,
        scope_snapshot.tenant_roles,
        scope_snapshot.project_scopes,
        'runtime_session_scope_v2',
        'auth_surface_policy_v1',
        p_attempt_id,
        'session',
        'active',
        'auth.invitation.redeem.v1',
        event_time,
        p_session_expires_at,
        jsonb_build_object(
            'source', 'invitation_redeem',
            'invitation_id', invitation_row.id
        ),
        event_time,
        event_time
    );
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'auth_command_idempotency_conflict'
            USING ERRCODE = 'GA004';
    END;
    UPDATE public.auth_invitation_redemption_attempts AS attempt
    SET session_id = p_session_id,
        status = 'succeeded',
        delivery_ciphertext = p_delivery_ciphertext,
        delivery_key_id = p_delivery_key_id,
        delivery_nonce = p_delivery_nonce,
        delivery_expires_at = p_delivery_expires_at,
        updated_at = greatest(
            event_time,
            attempt.updated_at + interval '1 microsecond'
        )
    WHERE attempt.id = p_attempt_id
      AND attempt.status = 'preparing'
    RETURNING attempt.* INTO attempt_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'auth_command_invariant_violation'
            USING ERRCODE = 'GA006';
    END IF;
    UPDATE public.project_member_invitations AS invitation
    SET status = 'accepted',
        accepted_by_attempt_id = p_attempt_id,
        accepted_at = event_time,
        updated_at = greatest(
            event_time,
            invitation.updated_at + interval '1 microsecond'
        )
    WHERE invitation.id = invitation_row.id
      AND invitation.status = 'pending'
    RETURNING invitation.* INTO invitation_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'auth_command_invariant_violation'
            USING ERRCODE = 'GA006';
    END IF;
    FOR pending_reauth IN
        SELECT queue.id
        FROM public.runtime_session_reauth_queue AS queue
        WHERE queue.tenant_id = invitation_row.tenant_id
          AND queue.actor_id = invitation_row.email
          AND queue.status = 'pending'
        ORDER BY queue.session_id, queue.id
        FOR UPDATE
    LOOP
        UPDATE public.runtime_session_reauth_queue AS queue
        SET status = 'resolved',
            resolved_at = event_time,
            resolved_by_session_id = p_session_id
        WHERE queue.id = pending_reauth.id;
        resolved_reauth_count := resolved_reauth_count + 1;
    END LOOP;
    IF resolved_reauth_count > 0 THEN
        PERFORM public.geno_v2_write_auth_command_audit(
            'auth.reauthentication.resolved',
            invitation_row.tenant_id,
            NULL,
            invitation_row.email,
            'user',
            'runtime_session',
            p_session_id::text,
            '{}'::jsonb,
            jsonb_build_object(
                'resolved_count', resolved_reauth_count,
                'correlation_id', correlation_id
            ),
            NULL
        );
    END IF;
    PERFORM public.geno_v2_write_auth_command_audit(
        'auth.invitation.redeemed',
        invitation_row.tenant_id,
        invitation_row.project_id,
        invitation_row.email,
        'user',
        'project_member_invitation',
        invitation_row.id::text,
        jsonb_build_object('attempt_id', p_attempt_id),
        jsonb_build_object(
            'session_id', p_session_id,
            'status', 'accepted',
            'resolved_reauth_count', resolved_reauth_count,
            'correlation_id', correlation_id
        ),
        NULL
    );

    result_code := 'succeeded';
    attempt_id := p_attempt_id;
    session_id := p_session_id;
    actor_id := invitation_row.email;
    tenant_id := invitation_row.tenant_id;
    project_ids := scope_snapshot.project_ids;
    tenant_roles := scope_snapshot.tenant_roles;
    project_scopes := scope_snapshot.project_scopes;
    delivery_ciphertext := p_delivery_ciphertext;
    delivery_key_id := p_delivery_key_id;
    delivery_nonce := p_delivery_nonce;
    delivery_expires_at := p_delivery_expires_at;
    replay_count := 0;
    RETURN NEXT;
END;
$redeem$;

CREATE FUNCTION geno_v2_confirm_current_auth_delivery()
RETURNS TABLE (
    result_code text,
    attempt_id uuid,
    session_id uuid,
    confirmed_at timestamptz,
    secret_erased_at timestamptz,
    correlation_id uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $confirm_delivery$
DECLARE
    event_time timestamptz := clock_timestamp();
    command_context record;
    session_row public.runtime_sessions%ROWTYPE;
    attempt_row public.auth_invitation_redemption_attempts%ROWTYPE;
BEGIN
    correlation_id := gen_random_uuid();
    SELECT * INTO command_context
    FROM public.geno_v2_lock_auth_command_context(false, false);
    IF NOT FOUND THEN
        result_code := 'session_unavailable';
        RETURN NEXT;
        RETURN;
    END IF;
    SELECT session.* INTO session_row
    FROM public.runtime_sessions AS session
    WHERE session.id = command_context.session_id
      AND session.status = 'active'
    FOR UPDATE;
    IF NOT FOUND THEN
        result_code := 'session_unavailable';
        RETURN NEXT;
        RETURN;
    END IF;
    SELECT attempt.* INTO attempt_row
    FROM public.auth_invitation_redemption_attempts AS attempt
    WHERE attempt.id = session_row.redemption_attempt_id
      AND attempt.session_id = session_row.id
      AND attempt.status = 'succeeded'
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'auth_command_invariant_violation'
            USING ERRCODE = 'GA006';
    END IF;

    IF attempt_row.delivery_confirmed_at IS NOT NULL THEN
        result_code := 'already_confirmed';
        attempt_id := attempt_row.id;
        session_id := session_row.id;
        confirmed_at := attempt_row.delivery_confirmed_at;
        secret_erased_at := attempt_row.secret_erased_at;
        RETURN NEXT;
        RETURN;
    END IF;
    IF attempt_row.delivery_ciphertext IS NULL
       OR attempt_row.delivery_key_id IS NULL
       OR attempt_row.delivery_nonce IS NULL THEN
        result_code := 'session_unavailable';
        RETURN NEXT;
        RETURN;
    END IF;

    UPDATE public.auth_invitation_redemption_attempts AS attempt
    SET delivery_confirmed_at = event_time,
        delivery_ciphertext = NULL,
        delivery_key_id = NULL,
        delivery_nonce = NULL,
        secret_erased_at = event_time,
        updated_at = greatest(
            event_time,
            attempt.updated_at + interval '1 microsecond'
        )
    WHERE attempt.id = attempt_row.id
    RETURNING attempt.* INTO attempt_row;
    PERFORM public.geno_v2_write_auth_command_audit(
        'auth.redemption.delivery_confirmed',
        session_row.tenant_id,
        NULL,
        session_row.actor_id,
        'user',
        'auth_redemption_attempt',
        attempt_row.id::text,
        '{}'::jsonb,
        jsonb_build_object(
            'session_id', session_row.id,
            'correlation_id', correlation_id
        ),
        NULL
    );
    result_code := 'confirmed';
    attempt_id := attempt_row.id;
    session_id := session_row.id;
    confirmed_at := attempt_row.delivery_confirmed_at;
    secret_erased_at := attempt_row.secret_erased_at;
    RETURN NEXT;
END;
$confirm_delivery$;

CREATE FUNCTION geno_v2_erase_current_auth_delivery_secret()
RETURNS TABLE (
    result_code text,
    attempt_id uuid,
    session_id uuid,
    secret_erased_at timestamptz,
    correlation_id uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $erase_delivery$
DECLARE
    event_time timestamptz := clock_timestamp();
    command_context record;
    session_row public.runtime_sessions%ROWTYPE;
    attempt_row public.auth_invitation_redemption_attempts%ROWTYPE;
BEGIN
    correlation_id := gen_random_uuid();
    SELECT * INTO command_context
    FROM public.geno_v2_lock_auth_command_context(false, false);
    IF NOT FOUND THEN
        result_code := 'session_unavailable';
        RETURN NEXT;
        RETURN;
    END IF;
    SELECT session.* INTO session_row
    FROM public.runtime_sessions AS session
    WHERE session.id = command_context.session_id
      AND session.status = 'active'
    FOR UPDATE;
    IF NOT FOUND THEN
        result_code := 'session_unavailable';
        RETURN NEXT;
        RETURN;
    END IF;
    SELECT attempt.* INTO attempt_row
    FROM public.auth_invitation_redemption_attempts AS attempt
    WHERE attempt.id = session_row.redemption_attempt_id
      AND attempt.session_id = session_row.id
      AND attempt.status = 'succeeded'
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'auth_command_invariant_violation'
            USING ERRCODE = 'GA006';
    END IF;

    IF attempt_row.delivery_ciphertext IS NULL THEN
        IF attempt_row.secret_erased_at IS NULL
           OR attempt_row.delivery_key_id IS NOT NULL
           OR attempt_row.delivery_nonce IS NOT NULL THEN
            RAISE EXCEPTION 'auth_command_invariant_violation'
                USING ERRCODE = 'GA006';
        END IF;
        result_code := 'already_erased';
        attempt_id := attempt_row.id;
        session_id := session_row.id;
        secret_erased_at := attempt_row.secret_erased_at;
        RETURN NEXT;
        RETURN;
    END IF;

    UPDATE public.auth_invitation_redemption_attempts AS attempt
    SET delivery_ciphertext = NULL,
        delivery_key_id = NULL,
        delivery_nonce = NULL,
        secret_erased_at = event_time,
        updated_at = greatest(
            event_time,
            attempt.updated_at + interval '1 microsecond'
        )
    WHERE attempt.id = attempt_row.id
    RETURNING attempt.* INTO attempt_row;
    PERFORM public.geno_v2_write_auth_command_audit(
        'auth.redemption.delivery_erased',
        session_row.tenant_id,
        NULL,
        session_row.actor_id,
        'user',
        'auth_redemption_attempt',
        attempt_row.id::text,
        '{}'::jsonb,
        jsonb_build_object(
            'session_id', session_row.id,
            'correlation_id', correlation_id
        ),
        'explicit_secret_erasure'
    );
    result_code := 'erased';
    attempt_id := attempt_row.id;
    session_id := session_row.id;
    secret_erased_at := attempt_row.secret_erased_at;
    RETURN NEXT;
END;
$erase_delivery$;

CREATE FUNCTION geno_v2_logout_current_session()
RETURNS TABLE (
    result_code text,
    session_id uuid,
    revoked_at timestamptz,
    correlation_id uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $logout$
DECLARE
    event_time timestamptz := clock_timestamp();
    command_context record;
    session_row public.runtime_sessions%ROWTYPE;
    attempt_row public.auth_invitation_redemption_attempts%ROWTYPE;
BEGIN
    correlation_id := gen_random_uuid();
    SELECT * INTO command_context
    FROM public.geno_v2_lock_auth_command_context(false, false);
    IF NOT FOUND THEN
        result_code := 'no_active_session';
        RETURN NEXT;
        RETURN;
    END IF;
    SELECT session.* INTO session_row
    FROM public.runtime_sessions AS session
    WHERE session.id = command_context.session_id
      AND session.status = 'active'
    FOR UPDATE;
    IF NOT FOUND THEN
        result_code := 'no_active_session';
        RETURN NEXT;
        RETURN;
    END IF;
    SELECT attempt.* INTO attempt_row
    FROM public.auth_invitation_redemption_attempts AS attempt
    WHERE attempt.id = session_row.redemption_attempt_id
      AND attempt.session_id = session_row.id
      AND attempt.status = 'succeeded'
    FOR UPDATE;
    IF FOUND AND attempt_row.delivery_ciphertext IS NOT NULL THEN
        UPDATE public.auth_invitation_redemption_attempts AS attempt
        SET delivery_ciphertext = NULL,
            delivery_key_id = NULL,
            delivery_nonce = NULL,
            secret_erased_at = coalesce(attempt.secret_erased_at, event_time),
            updated_at = greatest(
                event_time,
                attempt.updated_at + interval '1 microsecond'
            )
        WHERE attempt.id = attempt_row.id;
    END IF;
    UPDATE public.runtime_sessions AS session
    SET status = 'revoked',
        revoked_at = event_time,
        revoked_by = 'auth.logout.v1',
        revoke_reason = 'auth_logout',
        updated_at = greatest(
            event_time,
            session.updated_at + interval '1 microsecond'
        )
    WHERE session.id = session_row.id
      AND session.status = 'active'
    RETURNING session.* INTO session_row;
    IF NOT FOUND THEN
        result_code := 'no_active_session';
        RETURN NEXT;
        RETURN;
    END IF;
    PERFORM public.geno_v2_write_auth_command_audit(
        'auth.logout',
        session_row.tenant_id,
        NULL,
        session_row.actor_id,
        'user',
        'runtime_session',
        session_row.id::text,
        '{}'::jsonb,
        jsonb_build_object('correlation_id', correlation_id),
        'auth_logout'
    );
    result_code := 'logged_out';
    session_id := session_row.id;
    revoked_at := session_row.revoked_at;
    RETURN NEXT;
END;
$logout$;

CREATE FUNCTION geno_v2_resolve_current_reauth_queue()
RETURNS TABLE (
    result_code text,
    session_id uuid,
    resolved_count integer,
    correlation_id uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $resolve_reauth$
DECLARE
    event_time timestamptz := clock_timestamp();
    command_context record;
    pending_row record;
BEGIN
    correlation_id := gen_random_uuid();
    resolved_count := 0;
    SELECT * INTO command_context
    FROM public.geno_v2_lock_auth_command_context(false, false);
    IF NOT FOUND THEN
        result_code := 'no_pending';
        RETURN NEXT;
        RETURN;
    END IF;
    session_id := command_context.session_id;
    FOR pending_row IN
        SELECT queue.id
        FROM public.runtime_session_reauth_queue AS queue
        WHERE queue.tenant_id = command_context.tenant_id
          AND queue.actor_id = command_context.actor_id
          AND queue.status = 'pending'
        ORDER BY queue.session_id, queue.id
        FOR UPDATE
    LOOP
        UPDATE public.runtime_session_reauth_queue AS queue
        SET status = 'resolved',
            resolved_at = event_time,
            resolved_by_session_id = command_context.session_id
        WHERE queue.id = pending_row.id;
        resolved_count := resolved_count + 1;
    END LOOP;
    IF resolved_count = 0 THEN
        result_code := 'no_pending';
        RETURN NEXT;
        RETURN;
    END IF;
    PERFORM public.geno_v2_write_auth_command_audit(
        'auth.reauthentication.resolved',
        command_context.tenant_id,
        NULL,
        command_context.actor_id,
        'user',
        'runtime_session',
        command_context.session_id::text,
        '{}'::jsonb,
        jsonb_build_object(
            'resolved_count', resolved_count,
            'correlation_id', correlation_id
        ),
        NULL
    );
    result_code := 'resolved';
    RETURN NEXT;
END;
$resolve_reauth$;

ALTER FUNCTION geno_v2_auth_redeem_request_hash(uuid, text, text)
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_consume_auth_preflight_bucket(
    text, integer, integer, timestamptz
) OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_lock_auth_command_context(boolean, boolean)
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_lock_auth_command_project(uuid, uuid)
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_auth_context_has_project_permission(jsonb, uuid, text)
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_write_auth_command_audit(
    text, uuid, uuid, text, text, text, text, jsonb, jsonb, text
) OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_preflight_auth_invitation(uuid, text, text, text)
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_create_project_member_invitation(
    uuid, uuid, text, text, text, timestamptz
) OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_revoke_project_member_invitation(uuid, text)
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_expire_project_member_invitation(uuid)
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_build_locked_auth_scope(uuid, text)
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_redeem_auth_invitation(
    uuid, uuid, uuid, text, text, text, text, timestamptz,
    bytea, text, bytea, timestamptz
) OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_confirm_current_auth_delivery()
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_erase_current_auth_delivery_secret()
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_logout_current_session() OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_resolve_current_reauth_queue()
    OWNER TO geno_v2_authz_owner;

GRANT EXECUTE ON FUNCTION public.digest(bytea, text) TO geno_v2_authz_owner;

GRANT INSERT (
    id, tenant_id, project_id, email, role, status, invite_token_hash,
    audience, allowed_surfaces, policy_version, invited_by, expires_at,
    created_at, updated_at
) ON project_member_invitations TO geno_v2_authz_owner;
GRANT UPDATE (
    status, accepted_by_attempt_id, accepted_at, revoked_at, revoke_reason, updated_at
) ON project_member_invitations TO geno_v2_authz_owner;
GRANT INSERT (
    id, tenant_id, project_id, invitation_id, requested_surface,
    idempotency_key_hash, request_hash, token_fingerprint, status,
    created_at, updated_at
) ON auth_invitation_redemption_attempts TO geno_v2_authz_owner;
GRANT UPDATE (
    session_id, status, replay_count, delivery_ciphertext, delivery_key_id,
    delivery_nonce, delivery_expires_at, delivery_confirmed_at,
    secret_erased_at, updated_at
) ON auth_invitation_redemption_attempts TO geno_v2_authz_owner;
GRANT INSERT (
    id, session_token_hash, actor_id, actor_type, tenant_id, project_ids,
    roles, permissions, tenant_roles, project_scopes, scope_version,
    authz_policy_version, redemption_attempt_id, auth_method, status,
    issued_by, issued_at, expires_at, metadata, created_at, updated_at
) ON runtime_sessions TO geno_v2_authz_owner;
GRANT INSERT (
    tenant_id, project_id, user_id, role, status, invited_by, created_at, updated_at
) ON project_members TO geno_v2_authz_owner;
GRANT UPDATE (status) ON tenants, projects, tenant_members, project_members,
    runtime_project_access_grants TO geno_v2_authz_owner;
GRANT SELECT, INSERT, UPDATE ON auth_preflight_rate_limits TO geno_v2_authz_owner;
GRANT SELECT ON runtime_session_reauth_queue TO geno_v2_authz_owner;
GRANT UPDATE (status, resolved_at, resolved_by_session_id)
    ON runtime_session_reauth_queue TO geno_v2_authz_owner;
GRANT INSERT ON audit_events TO geno_v2_authz_owner;

REVOKE ALL ON FUNCTION geno_v2_auth_redeem_request_hash(uuid, text, text)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_consume_auth_preflight_bucket(
    text, integer, integer, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_lock_auth_command_context(boolean, boolean)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_lock_auth_command_project(uuid, uuid)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_auth_context_has_project_permission(jsonb, uuid, text)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_write_auth_command_audit(
    text, uuid, uuid, text, text, text, text, jsonb, jsonb, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_build_locked_auth_scope(uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_preflight_auth_invitation(uuid, text, text, text)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_create_project_member_invitation(
    uuid, uuid, text, text, text, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_revoke_project_member_invitation(uuid, text)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_expire_project_member_invitation(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_redeem_auth_invitation(
    uuid, uuid, uuid, text, text, text, text, timestamptz,
    bytea, text, bytea, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_confirm_current_auth_delivery() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_erase_current_auth_delivery_secret() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_logout_current_session() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_resolve_current_reauth_queue() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION geno_v2_preflight_auth_invitation(uuid, text, text, text)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_create_project_member_invitation(
    uuid, uuid, text, text, text, timestamptz
) TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_revoke_project_member_invitation(uuid, text)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_expire_project_member_invitation(uuid)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_redeem_auth_invitation(
    uuid, uuid, uuid, text, text, text, text, timestamptz,
    bytea, text, bytea, timestamptz
) TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_confirm_current_auth_delivery()
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_erase_current_auth_delivery_secret()
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_logout_current_session() TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_resolve_current_reauth_queue()
    TO geno_v2_runtime;

COMMENT ON FUNCTION geno_v2_preflight_auth_invitation(uuid, text, text, text) IS
    'Fixed v1 dual-bucket preflight: 600 seconds, invitation limit 20, source-HMAC limit 100.';
COMMENT ON FUNCTION geno_v2_redeem_auth_invitation(
    uuid, uuid, uuid, text, text, text, text, timestamptz,
    bytea, text, bytea, timestamptz
) IS
    'Atomic invitation redemption; exact replay returns only the original attempt, session, and encrypted delivery fields.';
COMMENT ON FUNCTION geno_v2_lock_auth_command_context(boolean, boolean) IS
    'Authz-owner lock helper; locks authorization sources before validating and locking the current session.';
COMMENT ON FUNCTION geno_v2_lock_auth_write_control() IS
    'First lock for auth commands; returns the write state while holding the singleton FOR SHARE through transaction end.';
COMMENT ON FUNCTION geno_v2_lock_auth_command_project(uuid, uuid) IS
    'Authz-owner Tenant-then-all-Projects UUID-ordered NO KEY UPDATE lock; verifies the target and remains compatible with grant FKs.';
COMMENT ON FUNCTION geno_v2_build_locked_auth_scope(uuid, text) IS
    'Authz-owner complete tenant scope snapshot builder with deterministic source row locks.';

DO $auth_command_catalog_assert$
DECLARE
    public_command_oids oid[] := ARRAY[
        'public.geno_v2_preflight_auth_invitation(uuid,text,text,text)'::regprocedure::oid,
        'public.geno_v2_create_project_member_invitation(uuid,uuid,text,text,text,timestamptz)'::regprocedure::oid,
        'public.geno_v2_revoke_project_member_invitation(uuid,text)'::regprocedure::oid,
        'public.geno_v2_expire_project_member_invitation(uuid)'::regprocedure::oid,
        'public.geno_v2_redeem_auth_invitation(uuid,uuid,uuid,text,text,text,text,timestamptz,bytea,text,bytea,timestamptz)'::regprocedure::oid,
        'public.geno_v2_confirm_current_auth_delivery()'::regprocedure::oid,
        'public.geno_v2_erase_current_auth_delivery_secret()'::regprocedure::oid,
        'public.geno_v2_logout_current_session()'::regprocedure::oid,
        'public.geno_v2_resolve_current_reauth_queue()'::regprocedure::oid
    ];
    internal_helper_oids oid[] := ARRAY[
        'public.geno_v2_lock_auth_write_control()'::regprocedure::oid,
        'public.geno_v2_require_auth_writes_enabled()'::regprocedure::oid,
        'public.geno_v2_auth_redeem_request_hash(uuid,text,text)'::regprocedure::oid,
        'public.geno_v2_consume_auth_preflight_bucket(text,integer,integer,timestamptz)'::regprocedure::oid,
        'public.geno_v2_lock_auth_command_context(boolean,boolean)'::regprocedure::oid,
        'public.geno_v2_lock_auth_command_project(uuid,uuid)'::regprocedure::oid,
        'public.geno_v2_auth_context_has_project_permission(jsonb,uuid,text)'::regprocedure::oid,
        'public.geno_v2_write_auth_command_audit(text,uuid,uuid,text,text,text,text,jsonb,jsonb,text)'::regprocedure::oid,
        'public.geno_v2_build_locked_auth_scope(uuid,text)'::regprocedure::oid
    ];
    all_command_oids oid[];
    authz_owner_oid oid;
    runtime_oid oid;
    api_login_oid oid;
    function_oid oid;
    sensitive_table text;
BEGIN
    all_command_oids := public_command_oids || internal_helper_oids;
    SELECT oid INTO authz_owner_oid FROM pg_roles WHERE rolname = 'geno_v2_authz_owner';
    SELECT oid INTO runtime_oid FROM pg_roles WHERE rolname = 'geno_v2_runtime';
    SELECT oid INTO api_login_oid FROM pg_roles WHERE rolname = 'geno_v2_api_login';
    IF authz_owner_oid IS NULL OR runtime_oid IS NULL OR api_login_oid IS NULL THEN
        RAISE EXCEPTION 'auth_command_catalog_verification_failed'
            USING ERRCODE = '55000';
    END IF;

    FOREACH function_oid IN ARRAY all_command_oids LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_proc AS procedure
            WHERE procedure.oid = function_oid
              AND procedure.proowner = authz_owner_oid
              AND procedure.prosecdef
              AND 'search_path=pg_catalog' = ANY(procedure.proconfig)
        ) OR EXISTS (
            SELECT 1
            FROM aclexplode(coalesce(
                (SELECT procedure.proacl FROM pg_proc AS procedure
                 WHERE procedure.oid = function_oid),
                acldefault('f', authz_owner_oid)
            )) AS privilege
            WHERE privilege.grantee = 0
              AND privilege.privilege_type = 'EXECUTE'
        ) THEN
            RAISE EXCEPTION 'auth_command_catalog_verification_failed'
                USING ERRCODE = '55000';
        END IF;
    END LOOP;

    FOREACH function_oid IN ARRAY public_command_oids LOOP
        IF NOT has_function_privilege(runtime_oid, function_oid, 'EXECUTE') THEN
            RAISE EXCEPTION 'auth_command_catalog_verification_failed'
                USING ERRCODE = '55000';
        END IF;
    END LOOP;
    FOREACH function_oid IN ARRAY internal_helper_oids LOOP
        IF has_function_privilege(runtime_oid, function_oid, 'EXECUTE') THEN
            RAISE EXCEPTION 'auth_command_catalog_verification_failed'
                USING ERRCODE = '55000';
        END IF;
    END LOOP;

    FOREACH sensitive_table IN ARRAY ARRAY[
        'project_member_invitations',
        'auth_invitation_redemption_attempts',
        'runtime_sessions',
        'runtime_session_reauth_queue',
        'auth_preflight_rate_limits',
        'auth_runtime_write_controls',
        'project_members',
        'runtime_project_access_grants'
    ] LOOP
        IF has_table_privilege(
            runtime_oid,
            ('public.' || sensitive_table)::regclass,
            'INSERT'
        ) OR has_table_privilege(
            runtime_oid,
            ('public.' || sensitive_table)::regclass,
            'UPDATE'
        ) OR has_table_privilege(
            runtime_oid,
            ('public.' || sensitive_table)::regclass,
            'DELETE'
        ) THEN
            RAISE EXCEPTION 'auth_command_catalog_verification_failed'
                USING ERRCODE = '55000';
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM pg_authid AS role_row
        WHERE role_row.oid = api_login_oid
          AND (role_row.rolcanlogin OR role_row.rolpassword IS NOT NULL)
    ) OR NOT EXISTS (
        SELECT 1 FROM public.auth_runtime_write_controls AS control
        WHERE control.singleton AND NOT control.writes_enabled
    ) THEN
        RAISE EXCEPTION 'auth_command_catalog_verification_failed'
            USING ERRCODE = '55000';
    END IF;
END;
$auth_command_catalog_assert$;

INSERT INTO audit_events (
    event_type,
    actor_type,
    actor_id,
    target_type,
    target_id,
    input_refs,
    output_refs,
    method_version,
    reason
) VALUES (
    'auth.commands.enabled',
    'system',
    'schema-v2-installer',
    'auth_runtime_write_control',
    'singleton',
    '{}'::jsonb,
    jsonb_build_object(
        'writes_enabled', true,
        'correlation_id', gen_random_uuid()
    ),
    'auth_commands_v1',
    'auth_command_install_verified'
);

UPDATE auth_runtime_write_controls
SET writes_enabled = true,
    reason = 'auth_commands_v1_installed',
    updated_by = 'schema-v2-installer',
    updated_at = greatest(
        clock_timestamp(),
        updated_at + interval '1 microsecond'
    )
WHERE singleton;
