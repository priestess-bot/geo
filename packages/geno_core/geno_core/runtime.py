from __future__ import annotations

import json
import os
import queue
import threading
from collections.abc import Mapping
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from geno_core.object_store import RequestFn, S3CompatibleObjectStore
from geno_core.repository import DbConnection, PostgresEvidenceRepository
from geno_core.schema_compatibility import (
    SchemaCompatibilityConnection,
    SchemaCompatibilityResult,
    check_schema_compatibility_from_env,
)


class RuntimePersistenceError(RuntimeError):
    """Raised when runtime persistence cannot be configured."""


RUNTIME_DB_POOL_ENABLED_ENV = "GENO_RUNTIME_DB_POOL_ENABLED"
RUNTIME_DB_POOL_MAX_SIZE_ENV = "GENO_RUNTIME_DB_POOL_MAX_SIZE"
RUNTIME_DB_POOL_TIMEOUT_SECONDS_ENV = "GENO_RUNTIME_DB_POOL_TIMEOUT_SECONDS"
RUNTIME_DB_POOL_ENABLED_VALUES = {"1", "true", "yes", "on"}
DEFAULT_RUNTIME_DB_POOL_MAX_SIZE = 10
DEFAULT_RUNTIME_DB_POOL_TIMEOUT_SECONDS = 5.0
RUNTIME_PROJECT_ACCESS_CONTROL_ENV = "GENO_RUNTIME_PROJECT_ACCESS_CONTROL"
RUNTIME_AUTH_MODE_ENV = "GENO_RUNTIME_AUTH_MODE"
RUNTIME_JWT_SECRET_ENV = "GENO_RUNTIME_JWT_SECRET"
RUNTIME_JWKS_JSON_ENV = "GENO_RUNTIME_JWKS_JSON"
RUNTIME_JWKS_URL_ENV = "GENO_RUNTIME_JWKS_URL"
RUNTIME_OIDC_DISCOVERY_URL_ENV = "GENO_RUNTIME_OIDC_DISCOVERY_URL"
RUNTIME_JWKS_CACHE_TTL_SECONDS_ENV = "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS"
RUNTIME_JWKS_STALE_IF_ERROR_SECONDS_ENV = "GENO_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS"
RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS_ENV = "GENO_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS"
RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS_ENV = "GENO_RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS"
RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS_ENV = "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS"
RUNTIME_JWT_ISSUER_ENV = "GENO_RUNTIME_JWT_ISSUER"
RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_BASE_URL_ENV = "GENO_NOTIFICATION_EMAIL_PREFERENCE_BASE_URL"
RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_SECRET_ENV = "GENO_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_SECRET"
RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_TTL_SECONDS_ENV = "GENO_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_TTL_SECONDS"
OBJECT_STORE_AUTO_CREATE_BUCKET_ENV = "OBJECT_STORE_AUTO_CREATE_BUCKET"
OBJECT_STORE_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
OBJECT_STORE_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
RUNTIME_PROJECT_ACCESS_CONTROL_ENABLED_VALUES = {"1", "true", "yes", "on"}
RUNTIME_AUTH_MODES = {"header", "jwt", "jwks"}


@dataclass(frozen=True)
class RuntimeComponentDiagnostic:
    name: str
    status: str
    detail: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class RuntimeDiagnostics:
    status: str
    checks: tuple[RuntimeComponentDiagnostic, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _pool_enabled(runtime_env: Mapping[str, str]) -> bool:
    return runtime_env.get(RUNTIME_DB_POOL_ENABLED_ENV, "").strip().lower() in RUNTIME_DB_POOL_ENABLED_VALUES


def _positive_int_from_env(runtime_env: Mapping[str, str], key: str, default: int) -> int:
    raw_value = runtime_env.get(key, str(default)).strip() or str(default)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimePersistenceError(f"{key} must be a positive integer") from exc
    if value < 1:
        raise RuntimePersistenceError(f"{key} must be a positive integer")
    return value


def _non_negative_float_from_env(runtime_env: Mapping[str, str], key: str, default: float) -> float:
    raw_value = runtime_env.get(key, str(default)).strip() or str(default)
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimePersistenceError(f"{key} must be a non-negative number") from exc
    if value < 0:
        raise RuntimePersistenceError(f"{key} must be a non-negative number")
    return value


def _positive_float_from_env(runtime_env: Mapping[str, str], key: str, default: float) -> float:
    raw_value = runtime_env.get(key, str(default)).strip() or str(default)
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimePersistenceError(f"{key} must be a positive number") from exc
    if value <= 0:
        raise RuntimePersistenceError(f"{key} must be a positive number")
    return value


def _redacted_url_status(database_url: str) -> str:
    if not database_url:
        return "missing"
    return "configured"


def connect_postgres_from_env(
    env: Mapping[str, str] | None = None,
    *,
    connector: Callable[[str], DbConnection] | None = None,
) -> DbConnection:
    runtime_env = os.environ if env is None else env
    database_url = runtime_env.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimePersistenceError("DATABASE_URL is required when persistence is enabled")
    if connector is not None:
        return connector(database_url)
    try:
        import psycopg
    except ModuleNotFoundError as exc:
        raise RuntimePersistenceError(
            "psycopg is required for PostgreSQL persistence; install apps/api/requirements.txt"
        ) from exc
    return psycopg.connect(database_url)


def validate_runtime_schema_compatibility(
    env: Mapping[str, str] | None = None,
    *,
    connector: Callable[[str], SchemaCompatibilityConnection] | None = None,
) -> SchemaCompatibilityResult:
    """Shared API/worker startup boundary for the opt-in Schema v2 check."""
    return check_schema_compatibility_from_env(env, connector=connector)


class _PooledDbConnection:
    def __init__(self, pool: "RuntimePostgresConnectionPool", connection: DbConnection) -> None:
        self._pool = pool
        self._connection = connection
        self._released = False

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)

    def close(self) -> None:
        if self._released:
            return
        self._released = True
        self._pool.release(self._connection)


class RuntimePostgresConnectionPool:
    """Small process-local PostgreSQL connection pool for API runtime requests."""

    def __init__(
        self,
        *,
        database_url: str,
        connector: Callable[[str], DbConnection],
        max_size: int = DEFAULT_RUNTIME_DB_POOL_MAX_SIZE,
        timeout_seconds: float = DEFAULT_RUNTIME_DB_POOL_TIMEOUT_SECONDS,
    ) -> None:
        if max_size < 1:
            raise RuntimePersistenceError(f"{RUNTIME_DB_POOL_MAX_SIZE_ENV} must be a positive integer")
        if timeout_seconds < 0:
            raise RuntimePersistenceError(f"{RUNTIME_DB_POOL_TIMEOUT_SECONDS_ENV} must be a non-negative number")
        self.database_url = database_url
        self.max_size = max_size
        self.timeout_seconds = timeout_seconds
        self._connector = connector
        self._available: queue.LifoQueue[DbConnection] = queue.LifoQueue(maxsize=max_size)
        self._lock = threading.Lock()
        self._created = 0

    def acquire(self) -> _PooledDbConnection:
        try:
            return _PooledDbConnection(self, self._available.get_nowait())
        except queue.Empty:
            pass

        with self._lock:
            if self._created < self.max_size:
                self._created += 1
                should_create = True
            else:
                should_create = False

        if should_create:
            try:
                return _PooledDbConnection(self, self._connector(self.database_url))
            except Exception:
                with self._lock:
                    self._created -= 1
                raise

        try:
            connection = self._available.get(timeout=self.timeout_seconds)
        except queue.Empty as exc:
            raise RuntimePersistenceError(
                f"Timed out waiting for PostgreSQL connection from runtime pool after {self.timeout_seconds:g}s"
            ) from exc
        return _PooledDbConnection(self, connection)

    def release(self, connection: DbConnection) -> None:
        if not self._reset_connection(connection):
            self._close_connection(connection)
            with self._lock:
                self._created -= 1
            return
        try:
            self._available.put_nowait(connection)
        except queue.Full:
            self._close_connection(connection)
            with self._lock:
                self._created -= 1

    def closeall(self) -> None:
        while True:
            try:
                connection = self._available.get_nowait()
            except queue.Empty:
                break
            self._close_connection(connection)
            with self._lock:
                self._created -= 1

    @staticmethod
    def _reset_connection(connection: DbConnection) -> bool:
        rollback = getattr(connection, "rollback", None)
        commit = getattr(connection, "commit", None)
        try:
            if callable(rollback):
                rollback()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                      set_config(%s, %s, false),
                      set_config(%s, %s, false),
                      set_config(%s, %s, false),
                      set_config(%s, %s, false)
                    """,
                    (
                        "geno.runtime_project_access_control",
                        "",
                        "geno.runtime_actor_id",
                        "",
                        "geno.runtime_project_id",
                        "",
                        "geno.runtime_invitation_token_hash",
                        "",
                    ),
                )
            if callable(commit):
                commit()
        except Exception:
            return False
        return True

    @staticmethod
    def _close_connection(connection: DbConnection) -> None:
        close = getattr(connection, "close", None)
        if callable(close):
            close()


_RUNTIME_POSTGRES_POOL: RuntimePostgresConnectionPool | None = None
_RUNTIME_POSTGRES_POOL_CONFIG: tuple[str, int, float] | None = None
_RUNTIME_POSTGRES_POOL_LOCK = threading.Lock()


def _default_postgres_connector() -> Callable[[str], DbConnection]:
    def connector(database_url: str) -> DbConnection:
        return connect_postgres_from_env({"DATABASE_URL": database_url})

    return connector


def _runtime_postgres_pool_from_env(
    env: Mapping[str, str],
    *,
    connector: Callable[[str], DbConnection] | None = None,
) -> RuntimePostgresConnectionPool:
    global _RUNTIME_POSTGRES_POOL, _RUNTIME_POSTGRES_POOL_CONFIG
    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimePersistenceError("DATABASE_URL is required when persistence is enabled")
    max_size = _positive_int_from_env(env, RUNTIME_DB_POOL_MAX_SIZE_ENV, DEFAULT_RUNTIME_DB_POOL_MAX_SIZE)
    timeout_seconds = _non_negative_float_from_env(
        env,
        RUNTIME_DB_POOL_TIMEOUT_SECONDS_ENV,
        DEFAULT_RUNTIME_DB_POOL_TIMEOUT_SECONDS,
    )
    config = (database_url, max_size, timeout_seconds)
    pool_connector = connector or _default_postgres_connector()
    with _RUNTIME_POSTGRES_POOL_LOCK:
        if _RUNTIME_POSTGRES_POOL is None or _RUNTIME_POSTGRES_POOL_CONFIG != config:
            if _RUNTIME_POSTGRES_POOL is not None:
                _RUNTIME_POSTGRES_POOL.closeall()
            _RUNTIME_POSTGRES_POOL = RuntimePostgresConnectionPool(
                database_url=database_url,
                connector=pool_connector,
                max_size=max_size,
                timeout_seconds=timeout_seconds,
            )
            _RUNTIME_POSTGRES_POOL_CONFIG = config
        return _RUNTIME_POSTGRES_POOL


def runtime_postgres_pool_snapshot(env: Mapping[str, str] | None = None) -> dict[str, object]:
    runtime_env = os.environ if env is None else env
    enabled = _pool_enabled(runtime_env)
    snapshot: dict[str, object] = {"enabled": enabled}
    if enabled:
        snapshot["max_size"] = _positive_int_from_env(
            runtime_env,
            RUNTIME_DB_POOL_MAX_SIZE_ENV,
            DEFAULT_RUNTIME_DB_POOL_MAX_SIZE,
        )
        snapshot["timeout_seconds"] = _non_negative_float_from_env(
            runtime_env,
            RUNTIME_DB_POOL_TIMEOUT_SECONDS_ENV,
            DEFAULT_RUNTIME_DB_POOL_TIMEOUT_SECONDS,
        )
    with _RUNTIME_POSTGRES_POOL_LOCK:
        if _RUNTIME_POSTGRES_POOL is not None:
            snapshot["created_connections"] = _RUNTIME_POSTGRES_POOL._created
            snapshot["available_connections"] = _RUNTIME_POSTGRES_POOL._available.qsize()
        else:
            snapshot["created_connections"] = 0
            snapshot["available_connections"] = 0
    return snapshot


def build_repository_from_env(
    env: Mapping[str, str] | None = None,
    *,
    connector: Callable[[str], DbConnection] | None = None,
) -> PostgresEvidenceRepository:
    runtime_env = os.environ if env is None else env
    try:
        preference_token_ttl_seconds = int(
            runtime_env.get(RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_TTL_SECONDS_ENV, "2592000").strip()
            or "2592000"
        )
    except ValueError as exc:
        raise RuntimePersistenceError(f"{RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_TTL_SECONDS_ENV} must be an integer") from exc
    repository_kwargs = {
        "email_preference_base_url": runtime_env.get(RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_BASE_URL_ENV, "").strip(),
        "email_preference_token_secret": runtime_env.get(
            RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_SECRET_ENV,
            "",
        ),
        "email_preference_token_ttl_seconds": max(1, preference_token_ttl_seconds),
    }
    if _pool_enabled(runtime_env):
        return PostgresEvidenceRepository(
            _runtime_postgres_pool_from_env(runtime_env, connector=connector).acquire(),
            **repository_kwargs,
        )
    return PostgresEvidenceRepository(connect_postgres_from_env(env, connector=connector), **repository_kwargs)


def _object_store_secret_from_env(env: Mapping[str, str], name: str) -> str:
    direct_value = env.get(name, "").strip()
    file_name = f"{name}_FILE"
    secret_path = env.get(file_name, "").strip()
    if direct_value and secret_path:
        raise RuntimePersistenceError(f"{name} and {file_name} cannot both be configured")
    if not secret_path:
        return direct_value
    try:
        value = Path(secret_path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimePersistenceError(f"Unable to read {file_name}") from exc
    if not value:
        raise RuntimePersistenceError(f"{file_name} is empty")
    return value


def _object_store_auto_create_bucket(env: Mapping[str, str]) -> bool:
    raw_value = env.get(OBJECT_STORE_AUTO_CREATE_BUCKET_ENV, "1").strip().lower()
    if raw_value in OBJECT_STORE_TRUE_VALUES:
        return True
    if raw_value in OBJECT_STORE_FALSE_VALUES:
        return False
    raise RuntimePersistenceError(
        f"{OBJECT_STORE_AUTO_CREATE_BUCKET_ENV} must be one of "
        f"{sorted(OBJECT_STORE_TRUE_VALUES | OBJECT_STORE_FALSE_VALUES)}"
    )


def build_object_store_from_env(
    env: Mapping[str, str] | None = None,
    *,
    requester: RequestFn | None = None,
) -> S3CompatibleObjectStore:
    runtime_env = os.environ if env is None else env
    return S3CompatibleObjectStore(
        endpoint=runtime_env.get("OBJECT_STORE_ENDPOINT", "").strip(),
        bucket=runtime_env.get("OBJECT_STORE_BUCKET", "geno-reports").strip(),
        access_key=_object_store_secret_from_env(runtime_env, "OBJECT_STORE_ACCESS_KEY"),
        secret_key=_object_store_secret_from_env(runtime_env, "OBJECT_STORE_SECRET_KEY"),
        region=runtime_env.get("OBJECT_STORE_REGION", "us-east-1").strip(),
        auto_create_bucket=_object_store_auto_create_bucket(runtime_env),
        requester=requester,
    )


def runtime_database_diagnostic(
    env: Mapping[str, str] | None = None,
    *,
    connector: Callable[[str], DbConnection] | None = None,
) -> RuntimeComponentDiagnostic:
    runtime_env = os.environ if env is None else env
    database_url = runtime_env.get("DATABASE_URL", "").strip()
    metadata: dict[str, object] = {
        "database_url": _redacted_url_status(database_url),
        "pool": runtime_postgres_pool_snapshot(runtime_env),
    }
    if not database_url:
        return RuntimeComponentDiagnostic(
            name="database",
            status="fail",
            detail="DATABASE_URL is not configured",
            metadata=metadata,
        )
    repository: PostgresEvidenceRepository | None = None
    try:
        repository = build_repository_from_env(runtime_env, connector=connector)
        with repository.connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            fetchone = getattr(cursor, "fetchone", None)
            if callable(fetchone):
                fetchone()
    except Exception as exc:
        return RuntimeComponentDiagnostic(
            name="database",
            status="fail",
            detail=str(exc),
            metadata=metadata,
        )
    finally:
        if repository is not None:
            close_repository_connection(repository)
    return RuntimeComponentDiagnostic(
        name="database",
        status="pass",
        detail="PostgreSQL connection check succeeded",
        metadata=metadata,
    )


def runtime_object_store_diagnostic(
    env: Mapping[str, str] | None = None,
) -> RuntimeComponentDiagnostic:
    runtime_env = os.environ if env is None else env
    endpoint = runtime_env.get("OBJECT_STORE_ENDPOINT", "").strip()
    bucket = runtime_env.get("OBJECT_STORE_BUCKET", "geno-reports").strip()
    try:
        access_key = _object_store_secret_from_env(runtime_env, "OBJECT_STORE_ACCESS_KEY")
        secret_key = _object_store_secret_from_env(runtime_env, "OBJECT_STORE_SECRET_KEY")
        auto_create_bucket = _object_store_auto_create_bucket(runtime_env)
    except RuntimePersistenceError as exc:
        return RuntimeComponentDiagnostic(
            name="object_store",
            status="fail",
            detail=str(exc),
            metadata={
                "endpoint": "configured" if endpoint else "missing",
                "bucket": bucket or "missing",
                "network_check": "not_run",
            },
        )
    metadata: dict[str, object] = {
        "endpoint": "configured" if endpoint else "missing",
        "bucket": bucket or "missing",
        "access_key": "configured" if access_key else "missing",
        "secret_key": "configured" if secret_key else "missing",
        "auto_create_bucket": auto_create_bucket,
        "network_check": "not_run",
    }
    if not endpoint:
        return RuntimeComponentDiagnostic(
            name="object_store",
            status="warn",
            detail="OBJECT_STORE_ENDPOINT is not configured; artifact archive paths will fail if used",
            metadata=metadata,
        )
    if not bucket or not access_key or not secret_key:
        return RuntimeComponentDiagnostic(
            name="object_store",
            status="warn",
            detail="Object store credentials or bucket are incomplete",
            metadata=metadata,
        )
    return RuntimeComponentDiagnostic(
        name="object_store",
        status="pass",
        detail="Object store configuration is present",
        metadata=metadata,
    )


def runtime_auth_diagnostic(env: Mapping[str, str] | None = None) -> RuntimeComponentDiagnostic:
    runtime_env = os.environ if env is None else env
    access_control_enabled = (
        runtime_env.get(RUNTIME_PROJECT_ACCESS_CONTROL_ENV, "").strip().lower()
        in RUNTIME_PROJECT_ACCESS_CONTROL_ENABLED_VALUES
    )
    auth_mode = runtime_env.get(RUNTIME_AUTH_MODE_ENV, "header").strip().lower() or "header"
    jwt_secret_configured = bool(runtime_env.get(RUNTIME_JWT_SECRET_ENV, "").strip())
    jwks_json = runtime_env.get(RUNTIME_JWKS_JSON_ENV, "").strip()
    jwks_url = runtime_env.get(RUNTIME_JWKS_URL_ENV, "").strip()
    oidc_discovery_url = runtime_env.get(RUNTIME_OIDC_DISCOVERY_URL_ENV, "").strip()
    jwt_issuer = runtime_env.get(RUNTIME_JWT_ISSUER_ENV, "").strip()
    jwks_url_valid = False
    if jwks_url:
        parsed_url = urlparse(jwks_url)
        jwks_url_valid = parsed_url.scheme in {"http", "https"} and bool(parsed_url.netloc)
    oidc_discovery_url_valid = False
    if oidc_discovery_url:
        parsed_url = urlparse(oidc_discovery_url)
        oidc_discovery_url_valid = parsed_url.scheme in {"http", "https"} and bool(parsed_url.netloc)
    jwt_issuer_url_valid = False
    if jwt_issuer:
        parsed_issuer = urlparse(jwt_issuer)
        jwt_issuer_url_valid = parsed_issuer.scheme in {"http", "https"} and bool(parsed_issuer.netloc)
    jwks_key_count: int | None = None
    if jwks_json:
        try:
            jwks_payload = json.loads(jwks_json)
        except ValueError:
            jwks_payload = None
        if isinstance(jwks_payload, dict) and isinstance(jwks_payload.get("keys"), list):
            jwks_key_count = len(jwks_payload["keys"])
    metadata: dict[str, object] = {
        "project_access_control_enabled": access_control_enabled,
        "auth_mode": auth_mode,
        "jwt_secret": "configured" if jwt_secret_configured else "missing",
        "jwks_json": "configured" if jwks_json else "missing",
        "jwks_url": "configured" if jwks_url else "missing",
        "jwks_url_network_check": "not_run",
        "jwks_stale_if_error_seconds": runtime_env.get(RUNTIME_JWKS_STALE_IF_ERROR_SECONDS_ENV, "0").strip() or "0",
        "oidc_discovery_url": "configured" if oidc_discovery_url else "missing",
        "oidc_discovery_source": "explicit" if oidc_discovery_url else ("jwt_issuer" if jwt_issuer else "missing"),
        "oidc_discovery_network_check": "not_run",
        "oidc_discovery_stale_if_error_seconds": runtime_env.get(
            RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS_ENV,
            "0",
        ).strip()
        or "0",
        "jwt_issuer": "configured" if jwt_issuer else "missing",
        "jwks_key_count": jwks_key_count if jwks_key_count is not None else "unknown",
    }
    if auth_mode not in RUNTIME_AUTH_MODES:
        return RuntimeComponentDiagnostic(
            name="runtime_auth",
            status="fail",
            detail="GENO_RUNTIME_AUTH_MODE must be header, jwt, or jwks",
            metadata=metadata,
        )
    if access_control_enabled and auth_mode == "jwt" and not jwt_secret_configured:
        return RuntimeComponentDiagnostic(
            name="runtime_auth",
            status="fail",
            detail="GENO_RUNTIME_JWT_SECRET is required when JWT auth mode is enabled",
            metadata=metadata,
        )
    if auth_mode == "jwks" and jwks_url and not jwks_json:
        if not jwks_url_valid:
            return RuntimeComponentDiagnostic(
                name="runtime_auth",
                status="fail",
                detail="GENO_RUNTIME_JWKS_URL must be an http or https URL",
                metadata=metadata,
            )
        try:
            _non_negative_float_from_env(runtime_env, RUNTIME_JWKS_CACHE_TTL_SECONDS_ENV, 300.0)
            _non_negative_float_from_env(runtime_env, RUNTIME_JWKS_STALE_IF_ERROR_SECONDS_ENV, 0.0)
            _positive_float_from_env(runtime_env, RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS_ENV, 2.0)
        except RuntimePersistenceError as exc:
            return RuntimeComponentDiagnostic(
                name="runtime_auth",
                status="fail",
                detail=str(exc),
                metadata=metadata,
            )
    if auth_mode == "jwks" and not jwks_json and not jwks_url and oidc_discovery_url:
        if not oidc_discovery_url_valid:
            return RuntimeComponentDiagnostic(
                name="runtime_auth",
                status="fail",
                detail="GENO_RUNTIME_OIDC_DISCOVERY_URL must be an http or https URL",
                metadata=metadata,
            )
        try:
            _non_negative_float_from_env(runtime_env, RUNTIME_JWKS_CACHE_TTL_SECONDS_ENV, 300.0)
            _non_negative_float_from_env(runtime_env, RUNTIME_JWKS_STALE_IF_ERROR_SECONDS_ENV, 0.0)
            _non_negative_float_from_env(runtime_env, RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS_ENV, 300.0)
            _non_negative_float_from_env(runtime_env, RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS_ENV, 0.0)
            _positive_float_from_env(runtime_env, RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS_ENV, 2.0)
        except RuntimePersistenceError as exc:
            return RuntimeComponentDiagnostic(
                name="runtime_auth",
                status="fail",
                detail=str(exc),
                metadata=metadata,
            )
    if auth_mode == "jwks" and not jwks_json and not jwks_url and not oidc_discovery_url and jwt_issuer:
        if not jwt_issuer_url_valid:
            return RuntimeComponentDiagnostic(
                name="runtime_auth",
                status="fail",
                detail="GENO_RUNTIME_JWT_ISSUER must be an http or https URL when used for OIDC discovery",
                metadata=metadata,
            )
        try:
            _non_negative_float_from_env(runtime_env, RUNTIME_JWKS_CACHE_TTL_SECONDS_ENV, 300.0)
            _non_negative_float_from_env(runtime_env, RUNTIME_JWKS_STALE_IF_ERROR_SECONDS_ENV, 0.0)
            _non_negative_float_from_env(runtime_env, RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS_ENV, 300.0)
            _non_negative_float_from_env(runtime_env, RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS_ENV, 0.0)
            _positive_float_from_env(runtime_env, RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS_ENV, 2.0)
        except RuntimePersistenceError as exc:
            return RuntimeComponentDiagnostic(
                name="runtime_auth",
                status="fail",
                detail=str(exc),
                metadata=metadata,
            )
    if access_control_enabled and auth_mode == "jwks":
        if not jwks_json and not jwks_url and not oidc_discovery_url and not jwt_issuer:
            return RuntimeComponentDiagnostic(
                name="runtime_auth",
                status="fail",
                detail=(
                    "GENO_RUNTIME_JWKS_JSON, GENO_RUNTIME_JWKS_URL, GENO_RUNTIME_OIDC_DISCOVERY_URL, "
                    "or URL-form GENO_RUNTIME_JWT_ISSUER is required when JWKS auth mode is enabled"
                ),
                metadata=metadata,
            )
        if jwks_json and jwks_key_count is None:
            return RuntimeComponentDiagnostic(
                name="runtime_auth",
                status="fail",
                detail="GENO_RUNTIME_JWKS_JSON must be valid JWKS JSON with a keys array",
                metadata=metadata,
            )
        if jwks_json and jwks_key_count < 1:
            return RuntimeComponentDiagnostic(
                name="runtime_auth",
                status="fail",
                detail="GENO_RUNTIME_JWKS_JSON must contain at least one key",
                metadata=metadata,
            )
    if not access_control_enabled:
        return RuntimeComponentDiagnostic(
            name="runtime_auth",
            status="warn",
            detail="Runtime project access control is disabled",
            metadata=metadata,
        )
    return RuntimeComponentDiagnostic(
        name="runtime_auth",
        status="pass",
        detail="Runtime project access control configuration is valid",
        metadata=metadata,
    )


def build_runtime_diagnostics(
    env: Mapping[str, str] | None = None,
    *,
    connector: Callable[[str], DbConnection] | None = None,
) -> RuntimeDiagnostics:
    checks = (
        runtime_database_diagnostic(env, connector=connector),
        runtime_object_store_diagnostic(env),
        runtime_auth_diagnostic(env),
    )
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        status = "fail"
    elif "warn" in statuses:
        status = "warn"
    else:
        status = "pass"
    return RuntimeDiagnostics(status=status, checks=checks)


def close_repository_connection(repository: PostgresEvidenceRepository) -> None:
    connection = getattr(repository, "connection", None)
    close = getattr(connection, "close", None)
    if callable(close):
        close()


def close_runtime_postgres_pool() -> None:
    global _RUNTIME_POSTGRES_POOL, _RUNTIME_POSTGRES_POOL_CONFIG
    with _RUNTIME_POSTGRES_POOL_LOCK:
        if _RUNTIME_POSTGRES_POOL is not None:
            _RUNTIME_POSTGRES_POOL.closeall()
        _RUNTIME_POSTGRES_POOL = None
        _RUNTIME_POSTGRES_POOL_CONFIG = None
