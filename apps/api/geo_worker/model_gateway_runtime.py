"""Fail-closed task-worker composition for the governed Model Gateway."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from geo_core.model_gateway import (
    ModelCallRuntimeFactory,
    build_secret_store_credential_resolver,
)
from geo_core.model_gateway.postgres import PostgresModelGatewayPersistence
from geo_core.model_gateway.postgres_runtime_catalog import PostgresRuntimeCatalog
from geo_core.model_gateway.postgres_artifact_composition import (
    ProviderArtifactWorkerComposition,
    build_provider_artifact_worker_composition,
)
from geo_core.model_gateway.provider_adapters.artifacts import (
    ProviderArtifactObjectStore,
)


@dataclass(frozen=True)
class GovernedModelGatewayWorkerRuntime:
    """Shared worker dependencies; secret-bearing objects stay process-local."""

    persistence: PostgresModelGatewayPersistence
    catalog: PostgresRuntimeCatalog
    artifacts: ProviderArtifactWorkerComposition
    model_calls: ModelCallRuntimeFactory

    def __repr__(self) -> str:
        return "GovernedModelGatewayWorkerRuntime([REDACTED])"


def build_governed_model_gateway_worker_runtime(
    *,
    database_url: str,
    object_store: ProviderArtifactObjectStore,
    worker_id: str,
    worker_actor_id: UUID,
    secret_store_master_keyring_path: str | Path,
    secret_store_request_hash_key_path: str | Path,
    provider_artifact_keyring_path: str | Path,
    connect_timeout: int = 5,
) -> GovernedModelGatewayWorkerRuntime:
    normalized_database_url = database_url.strip()
    normalized_worker_id = worker_id.strip()
    if not normalized_database_url or not normalized_worker_id:
        raise RuntimeError("Model Gateway worker database URL and identity are required")
    if worker_actor_id.int == 0:
        raise RuntimeError("Model Gateway worker actor ID cannot be zero")
    persistence = PostgresModelGatewayPersistence(
        normalized_database_url,
        connect_timeout=connect_timeout,
    )
    catalog = PostgresRuntimeCatalog(
        normalized_database_url,
        persistence=persistence,
        connect_timeout=connect_timeout,
    )
    artifacts = build_provider_artifact_worker_composition(
        database_url=normalized_database_url,
        object_store=object_store,
        worker_id=normalized_worker_id,
        keyring_path=str(provider_artifact_keyring_path),
        connect_timeout=connect_timeout,
    )
    credential_resolver = build_secret_store_credential_resolver(
        database_url=normalized_database_url,
        master_keyring_path=secret_store_master_keyring_path,
        request_hash_key_path=secret_store_request_hash_key_path,
        worker_actor_id=worker_actor_id,
    )
    model_calls = ModelCallRuntimeFactory(
        catalog=catalog,
        persistence=persistence,
        credential_resolver=credential_resolver,
        artifact_sink=artifacts.sink,
    )
    return GovernedModelGatewayWorkerRuntime(
        persistence=persistence,
        catalog=catalog,
        artifacts=artifacts,
        model_calls=model_calls,
    )


__all__ = [
    "GovernedModelGatewayWorkerRuntime",
    "build_governed_model_gateway_worker_runtime",
]
