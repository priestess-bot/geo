"""Production composition for durable Recommendation model generation Jobs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.model_gateway.runtime_execution import (
    ModelCallJobAdmitter,
    ModelCallRuntimeLoader,
)
from geo_core.recommendations.generation_artifact_contracts import (
    RecommendationTaskArtifactStore,
)
from geo_core.recommendations.generation_prompt import (
    RecommendationPromptProgramResolver,
)
from geo_core.recommendations.generation_result_recovery import (
    GovernedRecommendationModelResultLoader,
)
from geo_core.recommendations.generation_worker_contracts import (
    RECOMMENDATION_ARBITER_MODEL_JOB_KIND,
    RECOMMENDATION_PARENT_JOB_KIND,
    RECOMMENDATION_PRIMARY_MODEL_JOB_KIND,
)
from geo_core.recommendations.postgres.generation_worker import (
    RecommendationModelChildHandler,
    RecommendationParentHandler,
)
from geo_core.recommendations.postgres.generation_worker_repository import (
    PostgresRecommendationGenerationWorkerRepository,
)
from geo_core.workflow_runtime import PostgresWorkflowRuntimeRepository, WorkflowExecutor


def build_recommendation_generation_worker_handlers(
    *,
    store: PostgresDurableJobStore,
    connection_factory: Callable[[], Any],
    prompts: RecommendationPromptProgramResolver,
    artifacts: RecommendationTaskArtifactStore,
    model_results: GovernedRecommendationModelResultLoader,
    model_job_admitter: ModelCallJobAdmitter,
    model_runtime_loader: ModelCallRuntimeLoader,
    workflow_executor: WorkflowExecutor | None,
    lease_for: timedelta,
    poll_delay: timedelta = timedelta(seconds=5),
) -> Mapping[str, object]:
    """Build only governed parent/child handlers; no memory or provider fallback."""

    if lease_for < timedelta(seconds=30) or poll_delay <= timedelta(0):
        raise ValueError("Recommendation worker lease or poll delay is invalid")
    repository = PostgresRecommendationGenerationWorkerRepository(
        connection_factory,
        prompts=prompts,
        artifacts=artifacts,
        model_results=model_results,
        workflow_releases=PostgresWorkflowRuntimeRepository(store),
    )
    parent = RecommendationParentHandler(
        store=store,
        repository=repository,
        poll_delay=poll_delay,
    )
    child = RecommendationModelChildHandler(
        store=store,
        repository=repository,
        model_job_admitter=model_job_admitter,
        model_runtime_loader=model_runtime_loader,
        workflow_executor=workflow_executor,
        lease_for=lease_for,
    )
    return {
        RECOMMENDATION_PARENT_JOB_KIND: parent,
        RECOMMENDATION_PRIMARY_MODEL_JOB_KIND: child,
        RECOMMENDATION_ARBITER_MODEL_JOB_KIND: child,
    }


__all__ = ["build_recommendation_generation_worker_handlers"]
