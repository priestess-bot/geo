from __future__ import annotations

import os
import queue
import threading
from collections.abc import Mapping
from typing import Callable

from geno_core.object_store import RequestFn, S3CompatibleObjectStore
from geno_core.repository import DbConnection, PostgresEvidenceRepository


class RuntimePersistenceError(RuntimeError):
    """Raised when runtime persistence cannot be configured."""


RUNTIME_DB_POOL_ENABLED_ENV = "GENO_RUNTIME_DB_POOL_ENABLED"
RUNTIME_DB_POOL_MAX_SIZE_ENV = "GENO_RUNTIME_DB_POOL_MAX_SIZE"
RUNTIME_DB_POOL_TIMEOUT_SECONDS_ENV = "GENO_RUNTIME_DB_POOL_TIMEOUT_SECONDS"
RUNTIME_DB_POOL_ENABLED_VALUES = {"1", "true", "yes", "on"}
DEFAULT_RUNTIME_DB_POOL_MAX_SIZE = 10
DEFAULT_RUNTIME_DB_POOL_TIMEOUT_SECONDS = 5.0


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
                      set_config(%s, %s, false)
                    """,
                    (
                        "geno.runtime_project_access_control",
                        "",
                        "geno.runtime_actor_id",
                        "",
                        "geno.runtime_project_id",
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


def build_repository_from_env(
    env: Mapping[str, str] | None = None,
    *,
    connector: Callable[[str], DbConnection] | None = None,
) -> PostgresEvidenceRepository:
    runtime_env = os.environ if env is None else env
    if _pool_enabled(runtime_env):
        return PostgresEvidenceRepository(_runtime_postgres_pool_from_env(runtime_env, connector=connector).acquire())
    return PostgresEvidenceRepository(connect_postgres_from_env(env, connector=connector))


def build_object_store_from_env(
    env: Mapping[str, str] | None = None,
    *,
    requester: RequestFn | None = None,
) -> S3CompatibleObjectStore:
    runtime_env = os.environ if env is None else env
    return S3CompatibleObjectStore(
        endpoint=runtime_env.get("OBJECT_STORE_ENDPOINT", "").strip(),
        bucket=runtime_env.get("OBJECT_STORE_BUCKET", "geno-reports").strip(),
        access_key=runtime_env.get("OBJECT_STORE_ACCESS_KEY", "").strip(),
        secret_key=runtime_env.get("OBJECT_STORE_SECRET_KEY", "").strip(),
        region=runtime_env.get("OBJECT_STORE_REGION", "us-east-1").strip(),
        requester=requester,
    )


def close_repository_connection(repository: PostgresEvidenceRepository) -> None:
    close = getattr(repository.connection, "close", None)
    if callable(close):
        close()


def close_runtime_postgres_pool() -> None:
    global _RUNTIME_POSTGRES_POOL, _RUNTIME_POSTGRES_POOL_CONFIG
    with _RUNTIME_POSTGRES_POOL_LOCK:
        if _RUNTIME_POSTGRES_POOL is not None:
            _RUNTIME_POSTGRES_POOL.closeall()
        _RUNTIME_POSTGRES_POOL = None
        _RUNTIME_POSTGRES_POOL_CONFIG = None
