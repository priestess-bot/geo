"""Task-worker-only composition for governed Provider artifact persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from geo_core.model_gateway.artifact_deletion import ProviderArtifactDeletionService
from geo_core.model_gateway.postgres_artifacts import (
    PostgresProviderArtifactKeyVault,
    PostgresProviderArtifactLifecycleRepository,
    load_provider_artifact_keyring,
)
from geo_core.model_gateway.postgres_artifact_recovery import (
    PostgresProviderArtifactRecovery,
)
from geo_core.model_gateway.provider_adapters.artifacts import (
    IndependentProviderArtifactEncryptor,
    MinioProviderArtifactSink,
    ProviderArtifactObjectStore,
)
from geo_core.secrets import EnvelopeCipher, SecretConfigurationError


@dataclass(frozen=True)
class ProviderArtifactWorkerComposition:
    sink: MinioProviderArtifactSink
    lifecycle: PostgresProviderArtifactLifecycleRepository
    deletion: ProviderArtifactDeletionService
    key_vault: PostgresProviderArtifactKeyVault
    recovery: PostgresProviderArtifactRecovery


def build_provider_artifact_worker_composition(
    *,
    database_url: str,
    object_store: ProviderArtifactObjectStore,
    worker_id: str,
    keyring_path: str | None = None,
    connect_timeout: int = 5,
) -> ProviderArtifactWorkerComposition:
    normalized = database_url.strip()
    if not normalized:
        raise ValueError("Provider artifact PostgreSQL URL is required")
    keyring = load_provider_artifact_keyring(keyring_path)
    if keyring is None:
        raise SecretConfigurationError(
            "GEO_PROVIDER_ARTIFACT_KEYRING_FILE is required in the task worker"
        )

    def connect() -> Any:
        return psycopg.connect(
            normalized,
            connect_timeout=connect_timeout,
            row_factory=dict_row,
        )

    cipher = EnvelopeCipher(keyring)
    vault = PostgresProviderArtifactKeyVault(connect=connect, cipher=cipher)
    lifecycle = PostgresProviderArtifactLifecycleRepository(connect=connect)
    sink = MinioProviderArtifactSink(
        object_store=object_store,
        encryptor=IndependentProviderArtifactEncryptor(vault),
        lifecycle_repository=lifecycle,
    )
    deletion = ProviderArtifactDeletionService(
        repository=lifecycle,
        object_store=object_store,
        worker_id=worker_id,
    )
    recovery = PostgresProviderArtifactRecovery(
        connect=connect,
        cipher=cipher,
        object_store=object_store,
    )
    return ProviderArtifactWorkerComposition(
        sink,
        lifecycle,
        deletion,
        vault,
        recovery,
    )


__all__ = [
    "ProviderArtifactWorkerComposition",
    "build_provider_artifact_worker_composition",
]
