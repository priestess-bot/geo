"""Shared-worker handler map for non-browser Synthetic Lab execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.synthetic_lab.child_model_calls import (
    SYNTHETIC_MODEL_CHILD_KIND,
    SyntheticChildLifecyclePort,
)
from geo_core.synthetic_lab.child_model_worker import (
    SyntheticChildExecutionRepository,
    SyntheticChildModelCallHandler,
)
from geo_core.synthetic_lab.execution import SyntheticTaskExecutor
from geo_core.synthetic_lab.execution_contracts import (
    SyntheticModelCallPort,
    SyntheticPromptResolverPort,
)
from geo_core.synthetic_lab.execution_gateway import (
    GovernedSyntheticModelCallExecutor,
    SyntheticModelRuntimePort,
)
from geo_core.synthetic_lab.execution_worker import SyntheticExecutionHandler
from geo_core.synthetic_lab.ports import RuntimeInputPort
from geo_core.synthetic_lab.postgres_execution import PostgresSyntheticExecutionRepository
from geo_core.synthetic_lab.postgres_execution_runtime import (
    PostgresRuntimePromptApplication,
    PostgresSyntheticRuntimeInputPort,
)
from geo_core.synthetic_lab.postgres_child_model_calls import (
    build_synthetic_child_repository,
)
from geo_core.synthetic_lab.child_model_calls import SyntheticChildModelCallCoordinator
from geo_core.synthetic_lab.child_task_artifacts import (
    ChildTaskObjectStore,
    EncryptedSyntheticChildTaskArtifactStore,
)
from geo_core.synthetic_lab.artifact_keyring import load_synthetic_artifact_keyring
from geo_core.synthetic_lab.execution_gateway import PromptProgramExecutionResolver
from geo_core.synthetic_lab.model_result_recovery import (
    GovernedSyntheticChildResultLoader,
    ProviderArtifactSyntheticRecoveryAdapter,
)
from geo_core.model_gateway.artifact_recovery import ProviderArtifactRecoveryPort
from geo_core.workflow_runtime import PostgresWorkflowRuntimeRepository, WorkflowExecutor
from geo_core.synthetic_lab.dify_execution import HybridSyntheticModelCallExecutor


class SyntheticJobHandler(Protocol):
    def handle(self, lease: WorkerLease) -> Mapping[str, object]: ...


def build_synthetic_worker_handlers(
    *,
    store: PostgresDurableJobStore,
    connection_factory: Callable[[], Any],
    runtime_inputs: RuntimeInputPort,
    prompts: SyntheticPromptResolverPort,
    child_calls: SyntheticModelCallPort,
    child_lifecycle: SyntheticChildLifecyclePort,
    child_repository: SyntheticChildExecutionRepository,
    child_model_gateway: SyntheticModelCallPort,
    lease_for: timedelta,
) -> Mapping[str, SyntheticJobHandler]:
    """Build the non-browser handlers owned by the shared worker."""

    repository = PostgresSyntheticExecutionRepository(connection_factory)
    executor = SyntheticTaskExecutor(prompts=prompts, model_gateway=child_calls)
    handler = SyntheticExecutionHandler(
        store=store,
        repository=repository,
        runtime_inputs=runtime_inputs,
        prompts=prompts,
        executor=executor,
        lease_for=lease_for,
        children=child_lifecycle,
    )
    child_handler = SyntheticChildModelCallHandler(
        store=store,
        repository=child_repository,
        runtime_inputs=runtime_inputs,
        prompts=prompts,
        model_gateway=child_model_gateway,
        lease_for=lease_for,
    )
    return {
        "style.profile.build": handler,
        "review.case.run": handler,
        "corpus.finalize": handler,
        "offline_experiment.run": handler,
        SYNTHETIC_MODEL_CHILD_KIND: child_handler,
    }


def build_governed_synthetic_worker_handlers(
    *,
    store: PostgresDurableJobStore,
    connection_factory: Callable[[], Any],
    runtime_inputs: RuntimeInputPort,
    prompts: SyntheticPromptResolverPort,
    child_calls: SyntheticModelCallPort,
    child_lifecycle: SyntheticChildLifecyclePort,
    child_repository: SyntheticChildExecutionRepository,
    model_runtime: SyntheticModelRuntimePort,
    result_recovery: ProviderArtifactRecoveryPort,
    workflow_executor: WorkflowExecutor | None = None,
    lease_for: timedelta,
) -> Mapping[str, SyntheticJobHandler]:
    """Build production handlers with claim-time Model Gateway admission only."""

    return build_synthetic_worker_handlers(
        store=store,
        connection_factory=connection_factory,
        runtime_inputs=runtime_inputs,
        prompts=prompts,
        child_calls=child_calls,
        child_lifecycle=child_lifecycle,
        child_repository=child_repository,
        child_model_gateway=HybridSyntheticModelCallExecutor(
            native=GovernedSyntheticModelCallExecutor(
                runtime=model_runtime,
                result_recovery=result_recovery,
            ),
            workflows=workflow_executor,
        ),
        lease_for=lease_for,
    )


def build_synthetic_production_worker_handlers(
    *,
    database_url: str,
    store: PostgresDurableJobStore,
    model_runtime: SyntheticModelRuntimePort,
    provider_result_recovery: ProviderArtifactRecoveryPort,
    object_store: ChildTaskObjectStore,
    synthetic_artifact_keyring_path: str,
    lease_for: timedelta,
    workflow_executor: WorkflowExecutor | None = None,
) -> Mapping[str, SyntheticJobHandler]:
    """Compose every real dependency required by non-browser Synthetic jobs."""

    normalized_url = database_url.strip()
    if not normalized_url:
        raise ValueError("Synthetic worker PostgreSQL URL is required")
    keyring_path = synthetic_artifact_keyring_path.strip()
    if not keyring_path:
        raise ValueError("Synthetic worker artifact keyring path is required")

    def connect() -> Any:
        return psycopg.connect(normalized_url, row_factory=dict_row)

    artifacts = EncryptedSyntheticChildTaskArtifactStore(
        object_store=object_store,
        keyring=load_synthetic_artifact_keyring(keyring_path),
    )
    results = GovernedSyntheticChildResultLoader(
        ProviderArtifactSyntheticRecoveryAdapter(provider_result_recovery)
    )
    children = build_synthetic_child_repository(
        normalized_url,
        artifacts=artifacts,
        results=results,
    )
    prompts = PromptProgramExecutionResolver(PostgresRuntimePromptApplication(connect))
    return build_governed_synthetic_worker_handlers(
        store=store,
        connection_factory=connect,
        runtime_inputs=PostgresSyntheticRuntimeInputPort(connect),
        prompts=prompts,
        child_calls=SyntheticChildModelCallCoordinator(
            children,
            workflow_releases=(
                PostgresWorkflowRuntimeRepository(store)
                if workflow_executor is not None
                else None
            ),
        ),
        child_lifecycle=children,
        child_repository=children,
        model_runtime=model_runtime,
        result_recovery=provider_result_recovery,
        workflow_executor=workflow_executor,
        lease_for=lease_for,
    )


__all__ = [
    "SyntheticJobHandler",
    "build_governed_synthetic_worker_handlers",
    "build_synthetic_production_worker_handlers",
    "build_synthetic_worker_handlers",
]
