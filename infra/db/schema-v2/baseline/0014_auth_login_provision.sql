-- Deployment-time API LOGIN provisioning contract. This baseline records
-- lifecycle state and installs guards only; it never accepts or installs a
-- deployment credential.

CREATE TABLE auth_login_provision_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    login_kind text NOT NULL,
    operation text NOT NULL,
    status text NOT NULL DEFAULT 'preparing',
    credential_version text,
    previous_credential_version text,
    initiated_by text NOT NULL,
    failure_code text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    CONSTRAINT auth_login_attempt_kind_canonical
        CHECK (login_kind IN ('api', 'worker')),
    CONSTRAINT auth_login_attempt_operation_canonical
        CHECK (operation IN ('provision', 'rotate', 'disable')),
    CONSTRAINT auth_login_attempt_status_canonical
        CHECK (status IN ('preparing', 'succeeded', 'failed')),
    CONSTRAINT auth_login_attempt_credential_version_canonical
        CHECK (
            credential_version IS NULL
            OR credential_version ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
        ),
    CONSTRAINT auth_login_attempt_previous_version_canonical
        CHECK (
            previous_credential_version IS NULL
            OR previous_credential_version ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
        ),
    CONSTRAINT auth_login_attempt_operation_version_coherent
        CHECK (
            (operation IN ('provision', 'rotate') AND credential_version IS NOT NULL)
            OR (operation = 'disable' AND credential_version IS NULL)
        ),
    CONSTRAINT auth_login_attempt_previous_version_coherent
        CHECK (
            (operation = 'provision' AND previous_credential_version IS NULL)
            OR (operation = 'rotate' AND previous_credential_version IS NOT NULL)
            OR operation = 'disable'
        ),
    CONSTRAINT auth_login_attempt_initiator_nonempty
        CHECK (btrim(initiated_by) <> ''),
    CONSTRAINT auth_login_attempt_terminal_coherent
        CHECK (
            (status = 'preparing'
                AND completed_at IS NULL
                AND failure_code IS NULL)
            OR (status = 'succeeded'
                AND completed_at IS NOT NULL
                AND completed_at >= created_at
                AND failure_code IS NULL)
            OR (status = 'failed'
                AND completed_at IS NOT NULL
                AND completed_at >= created_at
                AND failure_code IS NOT NULL
                AND btrim(failure_code) <> '')
        )
);

CREATE UNIQUE INDEX auth_login_one_preparing_attempt_idx
    ON auth_login_provision_attempts (login_kind)
    WHERE status = 'preparing';
CREATE INDEX auth_login_attempts_created_idx
    ON auth_login_provision_attempts (attempt_sequence DESC);

CREATE TABLE auth_login_provision_receipts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id uuid NOT NULL UNIQUE,
    login_kind text NOT NULL,
    operation text NOT NULL,
    outcome text NOT NULL,
    credential_version text,
    login_enabled boolean NOT NULL,
    smoke_verified boolean NOT NULL,
    reason_code text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT auth_login_receipt_attempt_fkey
        FOREIGN KEY (attempt_id) REFERENCES auth_login_provision_attempts(id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT auth_login_receipt_kind_canonical
        CHECK (login_kind IN ('api', 'worker')),
    CONSTRAINT auth_login_receipt_operation_canonical
        CHECK (operation IN ('provision', 'rotate', 'disable')),
    CONSTRAINT auth_login_receipt_outcome_canonical
        CHECK (outcome IN ('succeeded', 'failed', 'disabled')),
    CONSTRAINT auth_login_receipt_credential_version_canonical
        CHECK (
            credential_version IS NULL
            OR credential_version ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
        ),
    CONSTRAINT auth_login_receipt_reason_nonempty
        CHECK (btrim(reason_code) <> ''),
    CONSTRAINT auth_login_receipt_outcome_coherent
        CHECK (
            (operation IN ('provision', 'rotate')
                AND outcome = 'succeeded'
                AND credential_version IS NOT NULL
                AND login_enabled
                AND smoke_verified)
            OR (operation IN ('provision', 'rotate')
                AND outcome = 'failed'
                AND credential_version IS NOT NULL
                AND NOT login_enabled
                AND NOT smoke_verified)
            OR (operation = 'disable'
                AND outcome = 'disabled'
                AND NOT login_enabled
                AND NOT smoke_verified)
            OR (operation = 'disable'
                AND outcome = 'failed'
                AND NOT login_enabled
                AND NOT smoke_verified)
        )
);

CREATE INDEX auth_login_receipts_created_idx
    ON auth_login_provision_receipts (created_at DESC, id DESC);
CREATE UNIQUE INDEX auth_login_successful_credential_version_idx
    ON auth_login_provision_receipts (login_kind, credential_version)
    WHERE outcome = 'succeeded';

CREATE FUNCTION geno_v2_guard_auth_login_provision_attempt()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard_auth_login_attempt$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'preparing'
           OR NEW.completed_at IS NOT NULL
           OR NEW.failure_code IS NOT NULL THEN
            RAISE EXCEPTION 'auth_login_attempt_must_start_preparing'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'auth_login_attempt_history_is_immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.attempt_sequence IS DISTINCT FROM OLD.attempt_sequence
       OR NEW.login_kind IS DISTINCT FROM OLD.login_kind
       OR NEW.operation IS DISTINCT FROM OLD.operation
       OR NEW.credential_version IS DISTINCT FROM OLD.credential_version
       OR NEW.previous_credential_version IS DISTINCT FROM OLD.previous_credential_version
       OR NEW.initiated_by IS DISTINCT FROM OLD.initiated_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'auth_login_attempt_identity_is_immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status <> 'preparing'
       OR NEW.status NOT IN ('succeeded', 'failed')
       OR NEW.completed_at IS NULL THEN
        RAISE EXCEPTION 'auth_login_attempt_allows_only_preparing_to_terminal'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_auth_login_attempt$;

CREATE FUNCTION geno_v2_reject_auth_login_receipt_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $reject_auth_login_receipt_mutation$
BEGIN
    RAISE EXCEPTION 'auth_login_provision_receipts_are_append_only'
        USING ERRCODE = '55000';
END;
$reject_auth_login_receipt_mutation$;

CREATE FUNCTION geno_v2_validate_auth_login_provision_lineage()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $validate_auth_login_provision_lineage$
DECLARE
    target_attempt_id uuid;
    attempt_row public.auth_login_provision_attempts%ROWTYPE;
    receipt_row public.auth_login_provision_receipts%ROWTYPE;
BEGIN
    IF TG_TABLE_NAME = 'auth_login_provision_attempts' THEN
        target_attempt_id := NEW.id;
    ELSE
        target_attempt_id := NEW.attempt_id;
    END IF;
    SELECT attempt.* INTO attempt_row
    FROM public.auth_login_provision_attempts AS attempt
    WHERE attempt.id = target_attempt_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'auth_login_provision_lineage_missing_attempt'
            USING ERRCODE = '23514';
    END IF;

    SELECT receipt.* INTO receipt_row
    FROM public.auth_login_provision_receipts AS receipt
    WHERE receipt.attempt_id = attempt_row.id;

    IF attempt_row.status = 'preparing' THEN
        IF FOUND THEN
            RAISE EXCEPTION 'preparing_auth_login_attempt_has_receipt'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;

    IF NOT FOUND
       OR receipt_row.login_kind <> attempt_row.login_kind
       OR receipt_row.operation <> attempt_row.operation
       OR receipt_row.credential_version IS DISTINCT FROM attempt_row.credential_version
       OR (attempt_row.status = 'failed' AND receipt_row.outcome <> 'failed')
       OR (attempt_row.status = 'succeeded'
           AND attempt_row.operation = 'disable'
           AND receipt_row.outcome <> 'disabled')
       OR (attempt_row.status = 'succeeded'
           AND attempt_row.operation IN ('provision', 'rotate')
           AND receipt_row.outcome <> 'succeeded') THEN
        RAISE EXCEPTION 'auth_login_provision_lineage_mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$validate_auth_login_provision_lineage$;

CREATE FUNCTION geno_v2_audit_auth_login_provision_receipt()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $audit_auth_login_provision_receipt$
BEGIN
    INSERT INTO public.audit_events (
        event_type, actor_type, actor_id, target_type, target_id,
        input_refs, output_refs, method_version, reason
    ) VALUES (
        'auth.' || NEW.login_kind || '_login.' || NEW.outcome,
        'service',
        'schema-v2-login-provisioner',
        'auth_login_provision_attempt',
        NEW.attempt_id::text,
        jsonb_build_object('login_kind', NEW.login_kind, 'operation', NEW.operation),
        jsonb_build_object(
            'receipt_id', NEW.id,
            'credential_version', NEW.credential_version,
            'login_enabled', NEW.login_enabled,
            'smoke_verified', NEW.smoke_verified
        ),
        'auth_login_provision_v1',
        NEW.reason_code
    );
    RETURN NEW;
END;
$audit_auth_login_provision_receipt$;

CREATE FUNCTION geno_v2_auth_login_startup_ready(p_credential_version text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $auth_login_startup_ready$
    SELECT coalesce((
        SELECT
            p_credential_version IS NOT NULL
            AND p_credential_version ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
            AND session_user = 'geno_v2_api_login'
            AND current_setting('role', true) = 'geno_v2_runtime'
            AND attempt.status = 'succeeded'
            AND attempt.operation IN ('provision', 'rotate')
            AND receipt.outcome = 'succeeded'
            AND receipt.login_enabled
            AND receipt.smoke_verified
            AND receipt.credential_version = p_credential_version
            AND EXISTS (
            SELECT 1
            FROM pg_roles AS role_row
            WHERE role_row.rolname = 'geno_v2_api_login'
              AND role_row.rolcanlogin
            )
        FROM public.auth_login_provision_attempts AS attempt
        LEFT JOIN public.auth_login_provision_receipts AS receipt
          ON receipt.attempt_id = attempt.id
        WHERE attempt.login_kind = 'api'
        ORDER BY attempt.attempt_sequence DESC
        LIMIT 1
    ), false);
$auth_login_startup_ready$;

ALTER FUNCTION geno_v2_guard_auth_login_provision_attempt()
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_reject_auth_login_receipt_mutation()
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_validate_auth_login_provision_lineage()
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_audit_auth_login_provision_receipt()
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_auth_login_startup_ready(text)
    OWNER TO geno_v2_authz_owner;

REVOKE ALL ON auth_login_provision_attempts,
    auth_login_provision_receipts FROM PUBLIC, geno_v2_runtime;
REVOKE ALL ON FUNCTION geno_v2_guard_auth_login_provision_attempt() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_reject_auth_login_receipt_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_validate_auth_login_provision_lineage() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_audit_auth_login_provision_receipt() FROM PUBLIC;
REVOKE ALL ON FUNCTION geno_v2_auth_login_startup_ready(text) FROM PUBLIC;
GRANT SELECT ON auth_login_provision_attempts,
    auth_login_provision_receipts TO geno_v2_authz_owner;
GRANT EXECUTE ON FUNCTION geno_v2_auth_login_startup_ready(text)
    TO geno_v2_runtime;

CREATE TRIGGER auth_login_attempts_guard_state
BEFORE INSERT OR UPDATE OR DELETE ON auth_login_provision_attempts
FOR EACH ROW EXECUTE FUNCTION geno_v2_guard_auth_login_provision_attempt();

CREATE TRIGGER auth_login_receipts_reject_mutation
BEFORE UPDATE OR DELETE ON auth_login_provision_receipts
FOR EACH ROW EXECUTE FUNCTION geno_v2_reject_auth_login_receipt_mutation();

CREATE CONSTRAINT TRIGGER auth_login_attempts_validate_lineage
AFTER INSERT OR UPDATE ON auth_login_provision_attempts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_auth_login_provision_lineage();

CREATE CONSTRAINT TRIGGER auth_login_receipts_validate_lineage
AFTER INSERT ON auth_login_provision_receipts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_auth_login_provision_lineage();

CREATE TRIGGER auth_login_receipts_write_audit
AFTER INSERT ON auth_login_provision_receipts
FOR EACH ROW EXECUTE FUNCTION geno_v2_audit_auth_login_provision_receipt();

ALTER TABLE auth_login_provision_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_login_provision_attempts FORCE ROW LEVEL SECURITY;
ALTER TABLE auth_login_provision_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_login_provision_receipts FORCE ROW LEVEL SECURITY;

INSERT INTO audit_events (
    event_type, actor_type, actor_id, target_type, target_id,
    input_refs, output_refs, method_version, reason
) VALUES (
    'auth.api_login.provision_contract_installed',
    'system',
    'schema-v2-installer',
    'auth_login_provision_contract',
    'v1',
    '{}'::jsonb,
    jsonb_build_object('login_enabled', false),
    'auth_login_provision_v1',
    'sealed_until_explicit_external_provisioning'
);

ALTER ROLE geno_v2_api_login
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
    NOREPLICATION NOBYPASSRLS PASSWORD NULL;
ALTER ROLE geno_v2_api_login RESET ALL;
ALTER ROLE geno_v2_api_login IN DATABASE geno_v2 RESET ALL;

DO $auth_login_provision_catalog_assert$
DECLARE
    authz_owner_oid oid;
    runtime_oid oid;
    api_login_oid oid;
    startup_function_oid oid := 'geno_v2_auth_login_startup_ready(text)'::regprocedure;
BEGIN
    SELECT oid INTO authz_owner_oid FROM pg_roles WHERE rolname = 'geno_v2_authz_owner';
    SELECT oid INTO runtime_oid FROM pg_roles WHERE rolname = 'geno_v2_runtime';
    SELECT oid INTO api_login_oid FROM pg_roles WHERE rolname = 'geno_v2_api_login';

    IF authz_owner_oid IS NULL OR runtime_oid IS NULL OR api_login_oid IS NULL
       OR EXISTS (
            SELECT 1 FROM pg_authid AS role_row
            WHERE role_row.oid = api_login_oid
              AND (role_row.rolcanlogin OR role_row.rolpassword IS NOT NULL
                   OR role_row.rolsuper OR role_row.rolcreatedb
                   OR role_row.rolcreaterole OR role_row.rolinherit
                   OR role_row.rolreplication OR role_row.rolbypassrls)
       ) OR EXISTS (
            SELECT 1 FROM pg_db_role_setting AS setting
            WHERE setting.setrole = api_login_oid
       ) OR EXISTS (
            SELECT 1 FROM pg_roles AS role_row
            WHERE role_row.oid = api_login_oid AND role_row.rolconfig IS NOT NULL
       ) OR NOT EXISTS (
            SELECT 1 FROM pg_auth_members AS membership
            WHERE membership.roleid = runtime_oid
              AND membership.member = api_login_oid
              AND NOT membership.admin_option
              AND NOT membership.inherit_option
              AND membership.set_option
       ) OR EXISTS (
            SELECT 1 FROM pg_auth_members AS membership
            WHERE (membership.roleid = api_login_oid OR membership.member = api_login_oid)
              AND NOT (membership.roleid = runtime_oid AND membership.member = api_login_oid)
       ) THEN
        RAISE EXCEPTION 'auth_login_provision_catalog_verification_failed'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_proc AS procedure
        WHERE procedure.oid = startup_function_oid
          AND procedure.proowner = authz_owner_oid
          AND procedure.prosecdef
          AND 'search_path=pg_catalog' = ANY(procedure.proconfig)
    ) OR EXISTS (
        SELECT 1
        FROM aclexplode(coalesce(
            (SELECT procedure.proacl FROM pg_proc AS procedure
             WHERE procedure.oid = startup_function_oid),
            acldefault('f', authz_owner_oid)
        )) AS privilege
        WHERE privilege.grantee = 0
          AND privilege.privilege_type = 'EXECUTE'
    ) OR NOT has_function_privilege(runtime_oid, startup_function_oid, 'EXECUTE')
       OR has_schema_privilege(api_login_oid, 'public', 'USAGE')
       OR EXISTS (
            SELECT 1
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
              AND (
                  has_table_privilege(api_login_oid, relation.oid, 'SELECT')
                  OR has_table_privilege(api_login_oid, relation.oid, 'INSERT')
                  OR has_table_privilege(api_login_oid, relation.oid, 'UPDATE')
                  OR has_table_privilege(api_login_oid, relation.oid, 'DELETE')
              )
       ) OR EXISTS (
            SELECT 1
            FROM pg_class AS sequence
            JOIN pg_namespace AS namespace ON namespace.oid = sequence.relnamespace
            WHERE namespace.nspname = 'public'
              AND sequence.relkind = 'S'
              AND (
                  has_sequence_privilege(api_login_oid, sequence.oid, 'USAGE')
                  OR has_sequence_privilege(api_login_oid, sequence.oid, 'SELECT')
                  OR has_sequence_privilege(api_login_oid, sequence.oid, 'UPDATE')
              )
       ) OR EXISTS (
            SELECT 1
            FROM pg_proc AS procedure
            JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = 'public'
              AND has_function_privilege(api_login_oid, procedure.oid, 'EXECUTE')
       )
       OR has_table_privilege(runtime_oid, 'auth_login_provision_attempts', 'SELECT')
       OR has_table_privilege(runtime_oid, 'auth_login_provision_receipts', 'SELECT')
       OR has_table_privilege(runtime_oid, 'auth_login_provision_attempts', 'INSERT')
       OR has_table_privilege(runtime_oid, 'auth_login_provision_receipts', 'INSERT')
       OR has_table_privilege(runtime_oid, 'auth_login_provision_attempts', 'UPDATE')
       OR has_table_privilege(runtime_oid, 'auth_login_provision_receipts', 'UPDATE')
       OR has_table_privilege(runtime_oid, 'auth_login_provision_attempts', 'DELETE')
       OR has_table_privilege(runtime_oid, 'auth_login_provision_receipts', 'DELETE') THEN
        RAISE EXCEPTION 'auth_login_provision_catalog_verification_failed'
            USING ERRCODE = '55000';
    END IF;
END;
$auth_login_provision_catalog_assert$;
