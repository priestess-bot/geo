"""Framework-bound composition for durable Workflow C sampling operations."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.model_gateway.artifact_recovery import ProviderArtifactRecoveryPort
from geo_core.model_gateway.runtime_execution import ModelCallRuntimeFactory
from geo_core.sampling.postgres_worker import (
    MANUAL_IMPORT_KIND,
    PROVIDER_EXECUTE_KIND,
    PostgresManualSamplingOperation,
    PostgresProviderSamplingOperation,
)
from geo_core.sampling.postgres_worker_repository import (
    PostgresWorkflowCSamplingRepository,
)
from geo_core.workflow_c_artifacts.composition import (
    build_workflow_c_artifact_reader_composition,
)
from geo_core.workflow_c_job_specs import PostgresWorkflowCJobSpecRepository


def build_workflow_c_sampling_operations(
    *,
    database_url: str,
    store: PostgresDurableJobStore,
    model_runtime: ModelCallRuntimeFactory,
    provider_result_recovery: ProviderArtifactRecoveryPort,
    workflow_c_artifact_keyring_path: str,
    lease_for: timedelta,
) -> dict[str, object]:
    """Build exactly the durable Provider and approved-manual samplers."""

    normalized_url = database_url.strip()
    keyring = workflow_c_artifact_keyring_path.strip()
    if not normalized_url or not keyring:
        raise ValueError("Workflow C sampling PostgreSQL URL and keyring are required")

    def connect() -> Any:
        return psycopg.connect(normalized_url, row_factory=dict_row)

    artifacts = build_workflow_c_artifact_reader_composition(
        connection_factory=connect,
        keyring_path=keyring,
    )
    specs = PostgresWorkflowCJobSpecRepository(connect)
    repository = PostgresWorkflowCSamplingRepository(connect)
    return {
        PROVIDER_EXECUTE_KIND: PostgresProviderSamplingOperation(
            store=store,
            specs=specs,
            repository=repository,
            model_runtime=model_runtime,
            result_recovery=provider_result_recovery,
            lease_for=lease_for,
        ),
        MANUAL_IMPORT_KIND: PostgresManualSamplingOperation(
            store=store,
            specs=specs,
            repository=repository,
            artifacts=artifacts.reader,
        ),
    }


__all__ = ["build_workflow_c_sampling_operations"]
