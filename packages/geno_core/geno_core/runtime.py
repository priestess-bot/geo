from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Callable

from geno_core.object_store import RequestFn, S3CompatibleObjectStore
from geno_core.repository import DbConnection, PostgresEvidenceRepository


class RuntimePersistenceError(RuntimeError):
    """Raised when runtime persistence cannot be configured."""


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


def build_repository_from_env(
    env: Mapping[str, str] | None = None,
    *,
    connector: Callable[[str], DbConnection] | None = None,
) -> PostgresEvidenceRepository:
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
