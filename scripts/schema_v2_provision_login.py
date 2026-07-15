from __future__ import annotations

import argparse
import hmac
import math
import os
import re
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4


DATABASE_NAME = "geo_v2"
API_LOGIN_ROLE = "geo_v2_api_login"
RUNTIME_ROLE = "geo_v2_runtime"
WORKER_LOGIN_ROLE = "geo_v2_worker_login"
WORKER_ROLE = "geo_v2_worker"
INSTALL_LOCK_NAME = "geo:schema-v2:install"
PROVISION_LOCK_NAME = "geo:schema-v2:auth-login-provision"
REQUIRED_BASELINE_FILE = "baseline/0014_auth_login_provision.sql"
WORKER_REQUIRED_BASELINE_FILE = "baseline/0021_worker_login_provision.sql"
MAX_SECRET_BYTES = 4096
MIN_SECRET_CHARS = 32
MAX_SECRET_CHARS = 1024
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
FORBIDDEN_API_SECRET_ENV = (
    "GEO_SCHEMA_V2_API_LOGIN_PASSWORD",
    "SCHEMA_V2_API_LOGIN_PASSWORD",
    "GEO_V2_API_LOGIN_PASSWORD",
    "GEO_SCHEMA_V2_WORKER_LOGIN_PASSWORD",
    "SCHEMA_V2_WORKER_LOGIN_PASSWORD",
    "GEO_V2_WORKER_LOGIN_PASSWORD",
)
FORBIDDEN_CONNECTION_ENV = (
    "DATABASE_URL",
    "SCHEMA_V2_DATABASE_URL",
    "PGSERVICE",
    "PGSERVICEFILE",
)
INSTALLER_PG_ENVIRONMENT = frozenset(
    {"PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"}
)
API_CHECK_PG_ENVIRONMENT = frozenset({"PGHOST", "PGPORT", "PGDATABASE"})
SENSITIVE_TABLES = (
    "project_member_invitations",
    "auth_invitation_redemption_attempts",
    "runtime_sessions",
    "runtime_session_reauth_queue",
    "auth_preflight_rate_limits",
    "auth_runtime_write_controls",
    "auth_login_provision_attempts",
    "auth_login_provision_receipts",
    "project_members",
    "runtime_project_access_grants",
)
WORKER_EXECUTION_FUNCTION_SIGNATURES = frozenset(
    {
        "public.geo_v2_claim_durable_job_dispatch(text, integer, uuid, uuid)",
        "public.geo_v2_heartbeat_durable_job_dispatch(uuid, text, uuid, integer)",
        "public.geo_v2_complete_durable_job_dispatch(uuid, text, uuid)",
        "public.geo_v2_fail_durable_job_dispatch(uuid, text, uuid, text, text, boolean, integer)",
        "public.geo_v2_claim_artifact_finalize(text, integer, uuid)",
        "public.geo_v2_heartbeat_artifact_finalize(uuid, text, uuid, integer)",
        "public.geo_v2_complete_artifact_finalize(uuid, text, uuid, text)",
        "public.geo_v2_fail_artifact_finalize(uuid, text, uuid, text, text, boolean, integer)",
        "public.geo_v2_claim_collection_job(text, integer, uuid)",
        "public.geo_v2_heartbeat_collection_job(uuid, text, uuid, integer)",
        "public.geo_v2_complete_collection_job(uuid, text, uuid, jsonb)",
        "public.geo_v2_fail_collection_job(uuid, text, uuid, text, text, boolean, integer)",
        "public.geo_v2_ack_collection_job_cancel(uuid, text, uuid)",
        "public.geo_v2_claim_visibility_score_run(text, integer, uuid)",
        "public.geo_v2_heartbeat_visibility_score_run(uuid, text, uuid, integer)",
        "public.geo_v2_complete_visibility_score_run(uuid, text, uuid, jsonb)",
        "public.geo_v2_fail_visibility_score_run(uuid, text, uuid, text, text, boolean, integer)",
        "public.geo_v2_ack_visibility_score_run_cancel(uuid, text, uuid)",
        "public.geo_v2_claim_retest_run(text, integer, uuid)",
        "public.geo_v2_heartbeat_retest_run(uuid, text, uuid, integer)",
        "public.geo_v2_complete_retest_run(uuid, text, uuid, uuid, jsonb)",
        "public.geo_v2_fail_retest_run(uuid, text, uuid, text, text, boolean, integer)",
        "public.geo_v2_ack_retest_run_cancel(uuid, text, uuid)",
        "public.geo_v2_claim_knowledge_job(text, integer, uuid, text)",
        "public.geo_v2_heartbeat_knowledge_job(uuid, text, uuid, integer)",
        "public.geo_v2_begin_finalizing_knowledge_job(uuid, text, uuid, text, jsonb)",
        "public.geo_v2_complete_knowledge_job(uuid, text, uuid)",
        "public.geo_v2_fail_knowledge_job(uuid, text, uuid, text, text, boolean, integer)",
        "public.geo_v2_ack_knowledge_job_cancel(uuid, text, uuid)",
        "public.geo_v2_read_knowledge_job_input(uuid, text, uuid)",
        "public.geo_v2_worker_login_startup_ready(text)",
    }
)


class LoginProvisionError(RuntimeError):
    """A stable error that never carries database or credential details."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DatabaseEndpoint:
    host: str
    port: int
    database: str


@dataclass(frozen=True)
class InstallerConfig:
    endpoint: DatabaseEndpoint
    user: str
    password: str


@dataclass(frozen=True)
class LoginProfile:
    kind: str
    login_role: str
    execution_role: str
    readiness_function: str
    required_baseline_files: tuple[str, ...]
    denied_role: str

    @property
    def provision_lock_name(self) -> str:
        return PROVISION_LOCK_NAME

    def error(self, suffix: str) -> str:
        return f"{self.kind}_login_{suffix}"


LOGIN_PROFILES = MappingProxyType({
    "api": LoginProfile(
        kind="api",
        login_role=API_LOGIN_ROLE,
        execution_role=RUNTIME_ROLE,
        readiness_function="geo_v2_auth_login_startup_ready",
        required_baseline_files=(REQUIRED_BASELINE_FILE,),
        denied_role=WORKER_ROLE,
    ),
    "worker": LoginProfile(
        kind="worker",
        login_role=WORKER_LOGIN_ROLE,
        execution_role=WORKER_ROLE,
        readiness_function="geo_v2_worker_login_startup_ready",
        required_baseline_files=(
            REQUIRED_BASELINE_FILE,
            "baseline/0020_collection_geo_scoring.sql",
            WORKER_REQUIRED_BASELINE_FILE,
        ),
        denied_role=RUNTIME_ROLE,
    ),
})


def _login_profile(login_kind: str) -> LoginProfile:
    try:
        return LOGIN_PROFILES[login_kind]
    except KeyError:
        raise LoginProvisionError("login_kind_invalid") from None


@dataclass(frozen=True)
class LatestLoginAttempt:
    operation: str
    status: str
    credential_version: str | None
    outcome: str | None
    login_enabled: bool | None
    smoke_verified: bool | None

    @property
    def active(self) -> bool:
        return (
            self.operation in ("provision", "rotate")
            and self.status == "succeeded"
            and self.outcome == "succeeded"
            and self.credential_version is not None
            and self.login_enabled is True
            and self.smoke_verified is True
        )


def _require_safe_environment(
    env: Mapping[str, str],
    *,
    allowed_pg_environment: frozenset[str],
) -> None:
    if any(env.get(name) for name in FORBIDDEN_API_SECRET_ENV):
        raise LoginProvisionError("api_login_plaintext_environment_forbidden")
    if any(env.get(name) for name in FORBIDDEN_CONNECTION_ENV):
        raise LoginProvisionError("unstructured_database_configuration_forbidden")
    unexpected_pg = sorted(
        name
        for name, value in env.items()
        if name.startswith("PG") and value and name not in allowed_pg_environment
    )
    if unexpected_pg:
        raise LoginProvisionError("unmodeled_libpq_environment_forbidden")


def _endpoint_from_env(env: Mapping[str, str]) -> DatabaseEndpoint:
    required = ("PGHOST", "PGPORT", "PGDATABASE")
    if any(not env.get(name, "") for name in required):
        raise LoginProvisionError("database_endpoint_configuration_incomplete")
    host = env["PGHOST"]
    if not host.strip() or host != host.strip() or "://" in host or "=" in host:
        raise LoginProvisionError("database_endpoint_configuration_invalid")
    try:
        port = int(env["PGPORT"])
    except ValueError:
        raise LoginProvisionError("database_endpoint_configuration_invalid") from None
    if not 1 <= port <= 65535 or env["PGDATABASE"] != DATABASE_NAME:
        raise LoginProvisionError("database_endpoint_configuration_invalid")
    return DatabaseEndpoint(host=host, port=port, database=DATABASE_NAME)


def installer_config_from_env(env: Mapping[str, str] | None = None) -> InstallerConfig:
    runtime_env = os.environ if env is None else env
    _require_safe_environment(
        runtime_env,
        allowed_pg_environment=INSTALLER_PG_ENVIRONMENT,
    )
    endpoint = _endpoint_from_env(runtime_env)
    user = runtime_env.get("PGUSER", "")
    password = runtime_env.get("PGPASSWORD", "")
    if not user or user != user.strip() or not password:
        raise LoginProvisionError("installer_database_configuration_incomplete")
    return InstallerConfig(endpoint=endpoint, user=user, password=password)


def _validate_process_environment_for_connection(
    supplied_env: Mapping[str, str] | None,
    *,
    allowed_pg_environment: frozenset[str],
) -> None:
    if supplied_env is not None and supplied_env is not os.environ:
        _require_safe_environment(
            os.environ,
            allowed_pg_environment=allowed_pg_environment,
        )


def _assert_external_secret_path(path: Path, *, repository_root: Path) -> None:
    try:
        resolved_parent = path.parent.resolve(strict=True)
        repository = repository_root.resolve(strict=True)
    except OSError:
        raise LoginProvisionError("api_login_secret_path_invalid") from None
    resolved = resolved_parent / path.name
    if resolved == repository or repository in resolved.parents:
        raise LoginProvisionError("api_login_secret_must_be_external")


def read_api_login_secret(
    path: Path,
    *,
    repository_root: Path,
    installer_password: str | None = None,
) -> str:
    _assert_external_secret_path(path, repository_root=repository_root)
    try:
        before = path.lstat()
    except OSError:
        raise LoginProvisionError("api_login_secret_unavailable") from None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise LoginProvisionError("api_login_secret_file_type_invalid")
    if stat.S_IMODE(before.st_mode) not in (0o400, 0o600):
        raise LoginProvisionError("api_login_secret_permissions_invalid")
    if before.st_uid != os.geteuid():
        raise LoginProvisionError("api_login_secret_owner_invalid")
    if before.st_size <= 0 or before.st_size > MAX_SECRET_BYTES:
        raise LoginProvisionError("api_login_secret_size_invalid")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise LoginProvisionError("api_login_secret_changed_during_read")
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) not in (0o400, 0o600)
                or opened.st_uid != os.geteuid()
            ):
                raise LoginProvisionError("api_login_secret_changed_during_read")
            payload = os.read(descriptor, MAX_SECRET_BYTES + 1)
        finally:
            os.close(descriptor)
    except LoginProvisionError:
        raise
    except OSError:
        raise LoginProvisionError("api_login_secret_unavailable") from None

    if len(payload) > MAX_SECRET_BYTES or b"\x00" in payload:
        raise LoginProvisionError("api_login_secret_content_invalid")
    if payload.endswith(b"\n"):
        payload = payload[:-1]
    if b"\n" in payload or b"\r" in payload:
        raise LoginProvisionError("api_login_secret_content_invalid")
    try:
        secret = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise LoginProvisionError("api_login_secret_content_invalid") from None
    if secret != secret.strip() or not MIN_SECRET_CHARS <= len(secret) <= MAX_SECRET_CHARS:
        raise LoginProvisionError("api_login_secret_policy_failed")

    classes = sum(
        bool(pattern.search(secret))
        for pattern in (
            re.compile(r"[a-z]"),
            re.compile(r"[A-Z]"),
            re.compile(r"[0-9]"),
            re.compile(r"[^A-Za-z0-9]"),
        )
    )
    weak = re.sub(r"[^a-z0-9]", "", secret.casefold())
    if classes < 3 or any(
        weak.startswith(prefix)
        for prefix in ("password", "changeme", "development", "default", "dev")
    ):
        raise LoginProvisionError("api_login_secret_policy_failed")
    if installer_password is not None and hmac.compare_digest(
        secret.encode("utf-8"),
        installer_password.encode("utf-8"),
    ):
        raise LoginProvisionError("api_login_secret_reuses_installer_credential")
    return secret


def read_login_secret(
    path: Path,
    *,
    repository_root: Path,
    installer_password: str | None = None,
) -> str:
    """Profile-neutral name; the API-named entry point remains supported."""
    return read_api_login_secret(
        path,
        repository_root=repository_root,
        installer_password=installer_password,
    )


def _connect_kwargs(endpoint: DatabaseEndpoint) -> dict[str, object]:
    return {
        "host": endpoint.host,
        "port": endpoint.port,
        "dbname": endpoint.database,
        "connect_timeout": 5,
    }


def _connect_installer(config: InstallerConfig) -> Any:
    try:
        import psycopg

        return psycopg.connect(
            **_connect_kwargs(config.endpoint),
            user=config.user,
            password=config.password,
            autocommit=True,
        )
    except Exception:
        raise LoginProvisionError("installer_database_connection_failed") from None


def _connect_login(
    endpoint: DatabaseEndpoint,
    secret: str,
    profile: LoginProfile,
) -> Any:
    try:
        import psycopg

        return psycopg.connect(
            **_connect_kwargs(endpoint),
            user=profile.login_role,
            password=secret,
        )
    except Exception:
        raise LoginProvisionError(profile.error("authentication_failed")) from None


def _connect_api(endpoint: DatabaseEndpoint, secret: str) -> Any:
    """Backward-compatible API profile connection helper."""
    return _connect_login(endpoint, secret, LOGIN_PROFILES["api"])


def _acquire_lock(cursor: Any, name: str, timeout_seconds: float) -> None:
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise LoginProvisionError("provision_lock_timeout_invalid")
    deadline = time.monotonic() + timeout_seconds
    while True:
        cursor.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
            (name,),
        )
        row = cursor.fetchone()
        if row is not None and bool(row[0]):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LoginProvisionError("provision_advisory_lock_timeout")
        time.sleep(min(0.1, remaining))


def _acquire_provision_locks(
    connection: Any,
    timeout_seconds: float,
    profile: LoginProfile = LOGIN_PROFILES["api"],
) -> None:
    started = time.monotonic()
    with connection.cursor() as cursor:
        _acquire_lock(cursor, INSTALL_LOCK_NAME, timeout_seconds)
        remaining = max(0.0, timeout_seconds - (time.monotonic() - started))
        _acquire_lock(cursor, profile.provision_lock_name, remaining)


def _verify_installed_contract(
    connection: Any,
    profile: LoginProfile = LOGIN_PROFILES["api"],
) -> None:
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT current_user, session_user, current_database(), rolsuper "
                    "FROM pg_roles WHERE rolname = session_user"
                )
                row = cursor.fetchone()
                if (
                    row is None
                    or row[0] != row[1]
                    or row[2] != DATABASE_NAME
                    or not row[3]
                    or row[0]
                    in (
                        API_LOGIN_ROLE,
                        RUNTIME_ROLE,
                        WORKER_LOGIN_ROLE,
                        WORKER_ROLE,
                        "geo_v2_authz_owner",
                    )
                ):
                    raise LoginProvisionError("provision_database_identity_mismatch")
                for required_baseline_file in profile.required_baseline_files:
                    cursor.execute(
                        "SELECT count(*) FROM schema_migration_ledger "
                        "WHERE migration_id = %s",
                        (required_baseline_file,),
                    )
                    if cursor.fetchone() != (1,):
                        raise LoginProvisionError("auth_login_provision_contract_missing")
                cursor.execute(
                    "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                    "rolinherit, rolreplication, rolbypassrls, rolconfig "
                    "FROM pg_roles WHERE rolname = %s",
                    (profile.login_role,),
                )
                role = cursor.fetchone()
                if role is None or any(bool(value) for value in role[1:7]) or role[7] is not None:
                    raise LoginProvisionError(profile.error("role_contract_invalid"))
                cursor.execute(
                    "SELECT parent.rolname, child.rolname, membership.admin_option, "
                    "membership.inherit_option, membership.set_option "
                    "FROM pg_auth_members AS membership "
                    "JOIN pg_roles AS parent ON parent.oid = membership.roleid "
                    "JOIN pg_roles AS child ON child.oid = membership.member "
                    "WHERE parent.rolname = %s OR child.rolname = %s",
                    (profile.login_role, profile.login_role),
                )
                memberships = cursor.fetchall()
                if memberships != [
                    (
                        profile.execution_role,
                        profile.login_role,
                        False,
                        False,
                        True,
                    )
                ]:
                    raise LoginProvisionError(profile.error("membership_contract_invalid"))
                cursor.execute(
                    "SELECT count(*) FROM pg_db_role_setting "
                    "WHERE setrole = (SELECT oid FROM pg_roles WHERE rolname = %s)",
                    (profile.login_role,),
                )
                if cursor.fetchone() != (0,):
                    raise LoginProvisionError(profile.error("role_settings_invalid"))
    except LoginProvisionError:
        raise
    except Exception:
        raise LoginProvisionError("auth_login_provision_contract_verification_failed") from None


def _set_login_credential(
    cursor: Any,
    verifier: str,
    profile: LoginProfile = LOGIN_PROFILES["api"],
) -> None:
    try:
        from psycopg import sql

        cursor.execute("SET LOCAL log_statement = 'none'")
        cursor.execute("SET LOCAL log_min_error_statement = 'panic'")
        cursor.execute("SET LOCAL log_parameter_max_length_on_error = 0")
        cursor.execute("SELECT set_config('pgaudit.log', 'none', true)")
        cursor.execute("SELECT set_config('pgaudit.log_parameter', 'off', true)")
        cursor.execute(
            sql.SQL(
                "ALTER ROLE {} "
                "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                "NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(profile.login_role), sql.Literal(verifier))
        )
        cursor.execute("SELECT 1")
    except Exception:
        raise LoginProvisionError(profile.error("role_update_failed")) from None


def _seal_login(
    cursor: Any,
    profile: LoginProfile = LOGIN_PROFILES["api"],
) -> None:
    from psycopg import sql

    cursor.execute(
        sql.SQL(
            "ALTER ROLE {} "
            "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
            "NOREPLICATION NOBYPASSRLS PASSWORD NULL"
        ).format(sql.Identifier(profile.login_role))
    )
    cursor.execute(
        sql.SQL("ALTER ROLE {} RESET ALL").format(sql.Identifier(profile.login_role))
    )
    cursor.execute(
        sql.SQL("ALTER ROLE {} IN DATABASE geo_v2 RESET ALL").format(
            sql.Identifier(profile.login_role)
        )
    )


def _recover_pending_attempt(
    connection: Any,
    profile: LoginProfile = LOGIN_PROFILES["api"],
) -> bool:
    recovered = False
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, operation, credential_version "
                    "FROM auth_login_provision_attempts "
                    "WHERE login_kind = %s AND status = 'preparing' FOR UPDATE",
                    (profile.kind,),
                )
                pending = cursor.fetchall()
                if not pending:
                    return False
                _seal_login(cursor, profile)
                for attempt_id, operation, credential_version in pending:
                    cursor.execute(
                        "UPDATE auth_login_provision_attempts "
                        "SET status = 'failed', failure_code = %s, "
                        "completed_at = clock_timestamp() WHERE id = %s",
                        ("interrupted_attempt_recovered", attempt_id),
                    )
                    cursor.execute(
                        "INSERT INTO auth_login_provision_receipts ("
                        "attempt_id, login_kind, operation, outcome, credential_version, "
                        "login_enabled, smoke_verified, reason_code) "
                        "VALUES (%s, %s, %s, 'failed', %s, false, false, %s)",
                        (
                            attempt_id,
                            profile.kind,
                            operation,
                            credential_version,
                            "interrupted_attempt_recovered",
                        ),
                    )
                recovered = True
    except Exception:
        raise LoginProvisionError("pending_attempt_recovery_failed") from None
    return recovered


def _latest_login_attempt(
    connection: Any,
    profile: LoginProfile = LOGIN_PROFILES["api"],
) -> LatestLoginAttempt | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT attempt.operation, attempt.status, attempt.credential_version, "
            "receipt.outcome, receipt.login_enabled, receipt.smoke_verified "
            "FROM auth_login_provision_attempts AS attempt "
            "LEFT JOIN auth_login_provision_receipts AS receipt "
            "ON receipt.attempt_id = attempt.id "
            "WHERE attempt.login_kind = %s "
            "ORDER BY attempt.attempt_sequence DESC LIMIT 1",
            (profile.kind,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return LatestLoginAttempt(
        operation=str(row[0]),
        status=str(row[1]),
        credential_version=None if row[2] is None else str(row[2]),
        outcome=None if row[3] is None else str(row[3]),
        login_enabled=None if row[4] is None else bool(row[4]),
        smoke_verified=None if row[5] is None else bool(row[5]),
    )


def _verify_live_role_matches_attempt(
    connection: Any,
    latest: LatestLoginAttempt | None,
    profile: LoginProfile = LOGIN_PROFILES["api"],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolcanlogin, rolpassword IS NOT NULL FROM pg_authid "
            "WHERE rolname = %s",
            (profile.login_role,),
        )
        row = cursor.fetchone()
    if row is None:
        raise LoginProvisionError(profile.error("role_contract_invalid"))
    has_live_credential = row == (True, True)
    expected_active = latest is not None and latest.active
    if expected_active and not has_live_credential:
        raise LoginProvisionError(profile.error("active_state_mismatch"))
    if not expected_active and (bool(row[0]) or bool(row[1])):
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    _seal_login(cursor, profile)
        except Exception:
            raise LoginProvisionError(
                profile.error("untracked_credential_seal_failed")
            ) from None
        raise LoginProvisionError(profile.error("untracked_credential_sealed"))


def _new_scram_verifier(
    connection: Any,
    secret: str,
    profile: LoginProfile = LOGIN_PROFILES["api"],
) -> str:
    try:
        verifier = connection.pgconn.encrypt_password(
            secret.encode("utf-8"),
            profile.login_role.encode("utf-8"),
            b"scram-sha-256",
        )
        value = verifier.decode("ascii")
    except Exception:
        raise LoginProvisionError(profile.error("verifier_generation_failed")) from None
    if not value.startswith("SCRAM-SHA-256$"):
        raise LoginProvisionError(profile.error("verifier_generation_failed"))
    return value


def _smoke_login(
    endpoint: DatabaseEndpoint,
    secret: str,
    *,
    credential_version: str | None = None,
    require_receipt: bool = False,
    profile: LoginProfile = LOGIN_PROFILES["api"],
) -> None:
    import psycopg
    from psycopg import sql

    connection = _connect_login(endpoint, secret, profile)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), session_user, current_user")
            if cursor.fetchone() != (
                DATABASE_NAME,
                profile.login_role,
                profile.login_role,
            ):
                raise LoginProvisionError(profile.error("identity_smoke_failed"))
            cursor.execute(
                "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                "rolinherit, rolreplication, rolbypassrls, rolconfig "
                "FROM pg_roles WHERE rolname = session_user"
            )
            if cursor.fetchone() != (
                True,
                False,
                False,
                False,
                False,
                False,
                False,
                None,
            ):
                raise LoginProvisionError(profile.error("role_attributes_smoke_failed"))
            cursor.execute(
                "SELECT parent.rolname, child.rolname, membership.admin_option, "
                "membership.inherit_option, membership.set_option "
                "FROM pg_auth_members AS membership "
                "JOIN pg_roles AS parent ON parent.oid = membership.roleid "
                "JOIN pg_roles AS child ON child.oid = membership.member "
                "WHERE parent.rolname = %s OR child.rolname = %s",
                (profile.login_role, profile.login_role),
            )
            if cursor.fetchall() != [
                (
                    profile.execution_role,
                    profile.login_role,
                    False,
                    False,
                    True,
                )
            ]:
                raise LoginProvisionError(profile.error("membership_smoke_failed"))
            cursor.execute(
                "SELECT has_database_privilege(session_user, current_database(), 'CONNECT'), "
                "has_database_privilege(session_user, current_database(), 'TEMPORARY'), "
                "(SELECT count(*) FROM pg_db_role_setting WHERE setrole = ("
                "SELECT oid FROM pg_roles WHERE rolname = session_user))"
            )
            if cursor.fetchone() != (True, False, 0):
                raise LoginProvisionError(profile.error("database_acl_smoke_failed"))
            cursor.execute(
                "SELECT has_schema_privilege(session_user, 'public', 'USAGE'), "
                "EXISTS (SELECT 1 FROM pg_class AS relation "
                "JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relkind IN ('r', 'p', 'v', 'm', 'f') AND ("
                "has_table_privilege(session_user, relation.oid, 'SELECT') OR "
                "has_table_privilege(session_user, relation.oid, 'INSERT') OR "
                "has_table_privilege(session_user, relation.oid, 'UPDATE') OR "
                "has_table_privilege(session_user, relation.oid, 'DELETE'))), "
                "EXISTS (SELECT 1 FROM pg_class AS sequence "
                "JOIN pg_namespace AS namespace ON namespace.oid = sequence.relnamespace "
                "WHERE namespace.nspname = 'public' AND sequence.relkind = 'S' AND ("
                "has_sequence_privilege(session_user, sequence.oid, 'USAGE') OR "
                "has_sequence_privilege(session_user, sequence.oid, 'SELECT') OR "
                "has_sequence_privilege(session_user, sequence.oid, 'UPDATE'))), "
                "EXISTS (SELECT 1 FROM pg_proc AS procedure "
                "JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace "
                "WHERE namespace.nspname = 'public' "
                "AND has_function_privilege(session_user, procedure.oid, 'EXECUTE'))"
            )
            if cursor.fetchone() != (False, False, False, False):
                raise LoginProvisionError(profile.error("direct_privilege_smoke_failed"))

            cursor.execute("SAVEPOINT denied_role_probe")
            try:
                cursor.execute(
                    sql.SQL("SET LOCAL ROLE {}").format(
                        sql.Identifier(profile.denied_role)
                    )
                )
            except psycopg.errors.InsufficientPrivilege:
                cursor.execute("ROLLBACK TO SAVEPOINT denied_role_probe")
                cursor.execute("RELEASE SAVEPOINT denied_role_probe")
            else:
                raise LoginProvisionError(profile.error("forbidden_role_settable"))

            cursor.execute(
                sql.SQL("SET LOCAL ROLE {}").format(
                    sql.Identifier(profile.execution_role)
                )
            )
            cursor.execute("SELECT current_user, current_setting('role', true)")
            if cursor.fetchone() != (
                profile.execution_role,
                profile.execution_role,
            ):
                raise LoginProvisionError(profile.error("role_smoke_failed"))

            if profile.kind == "worker":
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_class AS relation "
                    "JOIN pg_namespace AS namespace "
                    "ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = 'public' "
                    "AND relation.relkind IN ('r', 'p', 'v', 'm', 'f') AND ("
                    "has_table_privilege(current_user, relation.oid, 'SELECT') OR "
                    "has_table_privilege(current_user, relation.oid, 'INSERT') OR "
                    "has_table_privilege(current_user, relation.oid, 'UPDATE') OR "
                    "has_table_privilege(current_user, relation.oid, 'DELETE'))), "
                    "EXISTS (SELECT 1 FROM pg_class AS sequence "
                    "JOIN pg_namespace AS namespace "
                    "ON namespace.oid = sequence.relnamespace "
                    "WHERE namespace.nspname = 'public' AND sequence.relkind = 'S' AND ("
                    "has_sequence_privilege(current_user, sequence.oid, 'USAGE') OR "
                    "has_sequence_privilege(current_user, sequence.oid, 'SELECT') OR "
                    "has_sequence_privilege(current_user, sequence.oid, 'UPDATE')))"
                )
                if cursor.fetchone() != (False, False):
                    raise LoginProvisionError("worker_login_direct_data_acl_smoke_failed")
                cursor.execute(
                    "SELECT format('%I.%I(%s)', namespace.nspname, "
                    "procedure.proname, oidvectortypes(procedure.proargtypes)) "
                    "FROM pg_proc AS procedure "
                    "JOIN pg_namespace AS namespace "
                    "ON namespace.oid = procedure.pronamespace "
                    "WHERE namespace.nspname = 'public' "
                    "AND has_function_privilege(current_user, procedure.oid, 'EXECUTE')"
                )
                executable_functions = {str(row[0]) for row in cursor.fetchall()}
                if executable_functions != WORKER_EXECUTION_FUNCTION_SIGNATURES:
                    raise LoginProvisionError("worker_login_function_acl_smoke_failed")

            for table_name in SENSITIVE_TABLES:
                cursor.execute(
                    "SELECT has_table_privilege(%s, %s, 'SELECT'), "
                    "has_table_privilege(%s, %s, 'INSERT'), "
                    "has_table_privilege(%s, %s, 'UPDATE'), "
                    "has_table_privilege(%s, %s, 'DELETE')",
                    tuple(
                        value
                        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
                        for value in (profile.execution_role, f"public.{table_name}")
                    ),
                )
                privileges = cursor.fetchone()
                if profile.kind == "api":
                    privileges = privileges[1:]
                if any(bool(value) for value in privileges):
                    raise LoginProvisionError(profile.error("sensitive_dml_smoke_failed"))

            if profile.kind == "api":
                cursor.execute("SELECT count(*) FROM geo_v2_resolve_session_context()")
                if cursor.fetchone() != (0,):
                    raise LoginProvisionError("api_login_anonymous_context_smoke_failed")
            if require_receipt:
                cursor.execute(
                    sql.SQL("SELECT {}(%s)").format(
                        sql.Identifier(profile.readiness_function)
                    ),
                    (credential_version,),
                )
                if cursor.fetchone() != (True,):
                    raise LoginProvisionError(profile.error("startup_readiness_failed"))
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user, session_user, current_setting('role', true)")
            current_user, session_user, active_role = cursor.fetchone()
            if (
                current_user != profile.login_role
                or session_user != profile.login_role
                or active_role not in (None, "none")
            ):
                raise LoginProvisionError(profile.error("connection_cleanup_smoke_failed"))
    except LoginProvisionError:
        raise
    except Exception:
        raise LoginProvisionError(profile.error("smoke_failed")) from None
    finally:
        try:
            connection.rollback()
            connection.close()
        except Exception:
            pass


def _validate_version(value: str) -> str:
    if VERSION_RE.fullmatch(value) is None:
        raise LoginProvisionError("credential_version_invalid")
    return value


def provision_or_rotate(
    operation: str,
    *,
    credential_file: Path,
    credential_version: str,
    initiated_by: str,
    repository_root: Path,
    lock_timeout_seconds: float,
    drain_confirmed: bool,
    env: Mapping[str, str] | None = None,
    login_kind: str = "api",
) -> UUID:
    profile = _login_profile(login_kind)
    if operation not in ("provision", "rotate"):
        raise LoginProvisionError("provision_operation_invalid")
    if operation == "rotate" and not drain_confirmed:
        raise LoginProvisionError("rotation_requires_drain_confirmation")
    version = _validate_version(credential_version)
    if not initiated_by.strip():
        raise LoginProvisionError("provision_initiator_invalid")

    config = installer_config_from_env(env)
    _validate_process_environment_for_connection(
        env,
        allowed_pg_environment=INSTALLER_PG_ENVIRONMENT,
    )
    secret = read_api_login_secret(
        credential_file,
        repository_root=repository_root,
        installer_password=config.password,
    )
    connection = _connect_installer(config)
    attempt_id = uuid4()
    try:
        _acquire_provision_locks(connection, lock_timeout_seconds, profile)
        _verify_installed_contract(connection, profile)
        _recover_pending_attempt(connection, profile)
        latest = _latest_login_attempt(connection, profile)
        _verify_live_role_matches_attempt(connection, latest, profile)
        latest_active = latest is not None and latest.active
        if operation == "provision" and latest_active:
            raise LoginProvisionError(profile.error("already_provisioned"))
        if operation == "rotate" and not latest_active:
            raise LoginProvisionError(profile.error("rotation_source_missing"))
        previous_version = latest.credential_version if latest_active else None
        verifier = _new_scram_verifier(connection, secret, profile)
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO auth_login_provision_attempts ("
                        "id, login_kind, operation, credential_version, "
                        "previous_credential_version, initiated_by) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (
                            attempt_id,
                            profile.kind,
                            operation,
                            version,
                            previous_version,
                            initiated_by,
                        ),
                    )
                    _set_login_credential(cursor, verifier, profile)
        finally:
            verifier = ""

        try:
            _smoke_login(config.endpoint, secret, profile=profile)
        except LoginProvisionError:
            try:
                with connection.transaction():
                    with connection.cursor() as cursor:
                        _seal_login(cursor, profile)
                        cursor.execute(
                            "UPDATE auth_login_provision_attempts "
                            "SET status = 'failed', failure_code = %s, "
                            "completed_at = clock_timestamp() WHERE id = %s",
                            ("new_credential_smoke_failed", attempt_id),
                        )
                        cursor.execute(
                            "INSERT INTO auth_login_provision_receipts ("
                            "attempt_id, login_kind, operation, outcome, credential_version, "
                            "login_enabled, smoke_verified, reason_code) "
                            "VALUES (%s, %s, %s, 'failed', %s, false, false, %s)",
                            (
                                attempt_id,
                                profile.kind,
                                operation,
                                version,
                                "new_credential_smoke_failed",
                            ),
                        )
            except Exception:
                raise LoginProvisionError(
                    profile.error("smoke_compensation_failed")
                ) from None
            raise LoginProvisionError(profile.error("smoke_failed")) from None

        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE auth_login_provision_attempts "
                    "SET status = 'succeeded', completed_at = clock_timestamp() "
                    "WHERE id = %s",
                    (attempt_id,),
                )
                cursor.execute(
                    "INSERT INTO auth_login_provision_receipts ("
                    "attempt_id, login_kind, operation, outcome, credential_version, "
                    "login_enabled, smoke_verified, reason_code) "
                    "VALUES (%s, %s, %s, 'succeeded', %s, true, true, %s)",
                    (
                        attempt_id,
                        profile.kind,
                        operation,
                        version,
                        "login_smoke_succeeded",
                    ),
                )
        return attempt_id
    except LoginProvisionError:
        raise
    except Exception:
        raise LoginProvisionError(profile.error("provision_failed")) from None
    finally:
        secret = ""
        try:
            connection.close()
        except Exception:
            pass


def disable_login(
    *,
    initiated_by: str,
    lock_timeout_seconds: float,
    env: Mapping[str, str] | None = None,
    login_kind: str = "api",
) -> UUID:
    profile = _login_profile(login_kind)
    if not initiated_by.strip():
        raise LoginProvisionError("provision_initiator_invalid")
    config = installer_config_from_env(env)
    _validate_process_environment_for_connection(
        env,
        allowed_pg_environment=INSTALLER_PG_ENVIRONMENT,
    )
    connection = _connect_installer(config)
    attempt_id = uuid4()
    try:
        _acquire_provision_locks(connection, lock_timeout_seconds, profile)
        _verify_installed_contract(connection, profile)
        _recover_pending_attempt(connection, profile)
        latest = _latest_login_attempt(connection, profile)
        _verify_live_role_matches_attempt(connection, latest, profile)
        previous_version = latest.credential_version if latest and latest.active else None
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO auth_login_provision_attempts ("
                    "id, login_kind, operation, credential_version, "
                    "previous_credential_version, initiated_by) "
                    "VALUES (%s, %s, 'disable', NULL, %s, %s)",
                    (attempt_id, profile.kind, previous_version, initiated_by),
                )
                _seal_login(cursor, profile)
                cursor.execute(
                    "UPDATE auth_login_provision_attempts "
                    "SET status = 'succeeded', completed_at = clock_timestamp() "
                    "WHERE id = %s",
                    (attempt_id,),
                )
                cursor.execute(
                    "INSERT INTO auth_login_provision_receipts ("
                    "attempt_id, login_kind, operation, outcome, credential_version, "
                    "login_enabled, smoke_verified, reason_code) "
                    "VALUES (%s, %s, 'disable', 'disabled', NULL, false, false, %s)",
                    (attempt_id, profile.kind, "login_disabled"),
                )
        return attempt_id
    except LoginProvisionError:
        raise
    except Exception:
        raise LoginProvisionError(profile.error("disable_failed")) from None
    finally:
        connection.close()


def check_login(
    *,
    credential_file: Path,
    credential_version: str,
    repository_root: Path,
    env: Mapping[str, str] | None = None,
    login_kind: str = "api",
) -> None:
    profile = _login_profile(login_kind)
    runtime_env = os.environ if env is None else env
    if runtime_env.get("PGUSER") or runtime_env.get("PGPASSWORD"):
        raise LoginProvisionError(profile.error("installer_environment_forbidden"))
    _require_safe_environment(
        runtime_env,
        allowed_pg_environment=API_CHECK_PG_ENVIRONMENT,
    )
    _validate_process_environment_for_connection(
        env,
        allowed_pg_environment=API_CHECK_PG_ENVIRONMENT,
    )
    endpoint = _endpoint_from_env(runtime_env)
    secret = read_api_login_secret(
        credential_file,
        repository_root=repository_root,
    )
    try:
        _smoke_login(
            endpoint,
            secret,
            credential_version=_validate_version(credential_version),
            require_receipt=True,
            profile=profile,
        )
    finally:
        secret = ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provision a sealed Schema v2 LOGIN")
    parser.add_argument("--lock-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--initiated-by", default="schema-v2-login-provisioner")
    parser.add_argument("--login-kind", choices=tuple(LOGIN_PROFILES), default="api")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("provision", "rotate", "check"):
        child = subparsers.add_parser(command)
        child.add_argument("--credential-file", type=Path, required=True)
        child.add_argument("--credential-version", required=True)
        if command == "rotate":
            child.add_argument("--drain-confirmed", action="store_true")
    subparsers.add_parser("disable")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[1]
    try:
        if args.command in ("provision", "rotate"):
            provision_or_rotate(
                args.command,
                credential_file=args.credential_file,
                credential_version=args.credential_version,
                initiated_by=args.initiated_by,
                repository_root=repository_root,
                lock_timeout_seconds=args.lock_timeout_seconds,
                drain_confirmed=bool(getattr(args, "drain_confirmed", False)),
                login_kind=args.login_kind,
            )
        elif args.command == "disable":
            disable_login(
                initiated_by=args.initiated_by,
                lock_timeout_seconds=args.lock_timeout_seconds,
                login_kind=args.login_kind,
            )
        else:
            check_login(
                credential_file=args.credential_file,
                credential_version=args.credential_version,
                repository_root=repository_root,
                login_kind=args.login_kind,
            )
    except LoginProvisionError as exc:
        print(exc.code, file=sys.stderr)
        return 2
    print(f"{args.login_kind}_login_{args.command}_succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
