"""Compatibility facade for PostgreSQL Secret Store composition."""

from .postgres_api import (
    PsycopgSecretStoreApi,
    SecretStorePostgresRuntime,
    build_secret_store_api,
    build_secret_store_postgres_runtime,
)
from .postgres_keyring import retire_master_key_version
from .postgres_maintenance import PostgresSecretMaintenance
from .postgres_restore import (
    SecretStoreRestoreVerification,
    verify_secret_store_restore,
)
from .postgres_uow import PostgresSecretUnitOfWork, PostgresSecretUnitOfWorkFactory

__all__ = [
    "PostgresSecretUnitOfWork",
    "PostgresSecretUnitOfWorkFactory",
    "PostgresSecretMaintenance",
    "PsycopgSecretStoreApi",
    "SecretStorePostgresRuntime",
    "SecretStoreRestoreVerification",
    "build_secret_store_api",
    "build_secret_store_postgres_runtime",
    "retire_master_key_version",
    "verify_secret_store_restore",
]
