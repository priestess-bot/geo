-- Deployment-time worker LOGIN provisioning boundary. The generic immutable
-- attempt/receipt ledger is installed by 0014 and the worker execution role,
-- narrow job functions, and sealed LOGIN placeholder are installed by 0020.
-- This file adds only the worker startup proof and closes the catalog boundary.

CREATE FUNCTION geo_v2_worker_login_startup_ready(p_credential_version text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $worker_login_startup_ready$
    SELECT coalesce((
        SELECT
            p_credential_version IS NOT NULL
            AND p_credential_version ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
            AND session_user = 'geo_v2_worker_login'
            AND current_setting('role', true) = 'geo_v2_worker'
            AND attempt.status = 'succeeded'
            AND attempt.operation IN ('provision', 'rotate')
            AND receipt.login_kind = 'worker'
            AND receipt.operation = attempt.operation
            AND receipt.outcome = 'succeeded'
            AND receipt.login_enabled
            AND receipt.smoke_verified
            AND receipt.credential_version = attempt.credential_version
            AND receipt.credential_version = p_credential_version
            AND EXISTS (
                SELECT 1
                FROM pg_roles AS role_row
                WHERE role_row.rolname = 'geo_v2_worker_login'
                  AND role_row.rolcanlogin
                  AND NOT role_row.rolsuper
                  AND NOT role_row.rolcreatedb
                  AND NOT role_row.rolcreaterole
                  AND NOT role_row.rolinherit
                  AND NOT role_row.rolreplication
                  AND NOT role_row.rolbypassrls
                  AND role_row.rolconfig IS NULL
            )
        FROM public.auth_login_provision_attempts AS attempt
        LEFT JOIN public.auth_login_provision_receipts AS receipt
          ON receipt.attempt_id = attempt.id
        WHERE attempt.login_kind = 'worker'
        ORDER BY attempt.attempt_sequence DESC
        LIMIT 1
    ), false);
$worker_login_startup_ready$;

ALTER FUNCTION geo_v2_worker_login_startup_ready(text)
    OWNER TO geo_v2_authz_owner;
REVOKE ALL ON FUNCTION geo_v2_worker_login_startup_ready(text)
    FROM PUBLIC, geo_v2_runtime, geo_v2_worker_login;
GRANT EXECUTE ON FUNCTION geo_v2_worker_login_startup_ready(text)
    TO geo_v2_worker;

REVOKE ALL ON auth_login_provision_attempts,
    auth_login_provision_receipts
    FROM PUBLIC, geo_v2_runtime, geo_v2_worker, geo_v2_worker_login;

-- A baseline install never activates a deployment identity. The external
-- provisioner may enable LOGIN only after it has recorded a preparing attempt.
ALTER ROLE geo_v2_worker_login
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
    NOREPLICATION NOBYPASSRLS PASSWORD NULL;
ALTER ROLE geo_v2_worker_login RESET ALL;
ALTER ROLE geo_v2_worker_login IN DATABASE geo_v2 RESET ALL;

INSERT INTO audit_events (
    event_type, actor_type, actor_id, target_type, target_id,
    input_refs, output_refs, method_version, reason
) VALUES (
    'auth.worker_login.provision_contract_installed',
    'system',
    'schema-v2-installer',
    'auth_login_provision_contract',
    'worker-v1',
    '{}'::jsonb,
    jsonb_build_object('login_enabled', false),
    'worker_login_provision_v1',
    'sealed_until_explicit_external_provisioning'
);

DO $worker_login_provision_catalog_assert$
DECLARE
    authz_owner_oid oid;
    runtime_oid oid;
    worker_oid oid;
    worker_login_oid oid;
    readiness_oid oid := 'geo_v2_worker_login_startup_ready(text)'::regprocedure;
BEGIN
    SELECT oid INTO authz_owner_oid FROM pg_roles WHERE rolname = 'geo_v2_authz_owner';
    SELECT oid INTO runtime_oid FROM pg_roles WHERE rolname = 'geo_v2_runtime';
    SELECT oid INTO worker_oid FROM pg_roles WHERE rolname = 'geo_v2_worker';
    SELECT oid INTO worker_login_oid FROM pg_roles WHERE rolname = 'geo_v2_worker_login';

    IF authz_owner_oid IS NULL OR runtime_oid IS NULL OR worker_oid IS NULL
       OR worker_login_oid IS NULL
       OR EXISTS (
            SELECT 1 FROM pg_authid AS role_row
            WHERE role_row.oid = worker_login_oid
              AND (role_row.rolcanlogin OR role_row.rolpassword IS NOT NULL
                   OR role_row.rolsuper OR role_row.rolcreatedb
                   OR role_row.rolcreaterole OR role_row.rolinherit
                   OR role_row.rolreplication OR role_row.rolbypassrls)
       )
       OR EXISTS (
            SELECT 1 FROM pg_db_role_setting AS setting
            WHERE setting.setrole = worker_login_oid
       )
       OR EXISTS (
            SELECT 1 FROM pg_roles AS role_row
            WHERE role_row.oid = worker_login_oid AND role_row.rolconfig IS NOT NULL
       )
       OR NOT EXISTS (
            SELECT 1 FROM pg_auth_members AS membership
            WHERE membership.roleid = worker_oid
              AND membership.member = worker_login_oid
              AND NOT membership.admin_option
              AND NOT membership.inherit_option
              AND membership.set_option
       )
       OR EXISTS (
            SELECT 1 FROM pg_auth_members AS membership
            WHERE (membership.roleid = worker_login_oid
                   OR membership.member = worker_login_oid)
              AND NOT (membership.roleid = worker_oid
                       AND membership.member = worker_login_oid)
       ) THEN
        RAISE EXCEPTION 'worker_login_provision_catalog_verification_failed'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_proc AS procedure
        WHERE procedure.oid = readiness_oid
          AND procedure.proowner = authz_owner_oid
          AND procedure.prosecdef
          AND procedure.proconfig = ARRAY['search_path=pg_catalog']::text[]
    )
    OR EXISTS (
        SELECT 1
        FROM aclexplode(coalesce(
            (SELECT procedure.proacl FROM pg_proc AS procedure
             WHERE procedure.oid = readiness_oid),
            acldefault('f', authz_owner_oid)
        )) AS privilege
        WHERE privilege.grantee = 0
          AND privilege.privilege_type = 'EXECUTE'
    )
    OR NOT has_function_privilege(worker_oid, readiness_oid, 'EXECUTE')
    OR has_function_privilege(runtime_oid, readiness_oid, 'EXECUTE')
    OR has_function_privilege(worker_login_oid, readiness_oid, 'EXECUTE')
    OR has_schema_privilege(worker_login_oid, 'public', 'USAGE')
    OR EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND (
              has_table_privilege(worker_login_oid, relation.oid, 'SELECT')
              OR has_table_privilege(worker_login_oid, relation.oid, 'INSERT')
              OR has_table_privilege(worker_login_oid, relation.oid, 'UPDATE')
              OR has_table_privilege(worker_login_oid, relation.oid, 'DELETE')
          )
    )
    OR EXISTS (
        SELECT 1
        FROM pg_class AS sequence
        JOIN pg_namespace AS namespace ON namespace.oid = sequence.relnamespace
        WHERE namespace.nspname = 'public'
          AND sequence.relkind = 'S'
          AND (
              has_sequence_privilege(worker_login_oid, sequence.oid, 'USAGE')
              OR has_sequence_privilege(worker_login_oid, sequence.oid, 'SELECT')
              OR has_sequence_privilege(worker_login_oid, sequence.oid, 'UPDATE')
          )
    )
    OR EXISTS (
        SELECT 1
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = 'public'
          AND has_function_privilege(worker_login_oid, procedure.oid, 'EXECUTE')
    )
    OR has_table_privilege(worker_oid, 'auth_login_provision_attempts', 'SELECT')
    OR has_table_privilege(worker_oid, 'auth_login_provision_receipts', 'SELECT')
    OR has_table_privilege(worker_oid, 'auth_login_provision_attempts', 'INSERT')
    OR has_table_privilege(worker_oid, 'auth_login_provision_receipts', 'INSERT')
    OR has_table_privilege(worker_oid, 'auth_login_provision_attempts', 'UPDATE')
    OR has_table_privilege(worker_oid, 'auth_login_provision_receipts', 'UPDATE')
    OR has_table_privilege(worker_oid, 'auth_login_provision_attempts', 'DELETE')
    OR has_table_privilege(worker_oid, 'auth_login_provision_receipts', 'DELETE') THEN
        RAISE EXCEPTION 'worker_login_provision_catalog_verification_failed'
            USING ERRCODE = '55000';
    END IF;
END;
$worker_login_provision_catalog_assert$;

