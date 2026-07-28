"""Persistence contract shared by Recommendation parent and child workers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.recommendations.generation_artifacts import RecommendationTaskArtifactRef
from geo_core.recommendations.generation_contracts import (
    RecommendationGenerationResult,
    RecommendationGenerationSpec,
    ResolvedGenerationPrompt,
)
from geo_core.recommendations.generation_worker_contracts import (
    RecommendationDifyResultRef,
    RecommendationModelResultRef,
    RecommendationModelRole,
    RecommendationModelTask,
    RecommendationParentClaim,
)


class RecommendationGenerationWorkerRepository(Protocol):
    def load_parent(self, lease: WorkerLease) -> RecommendationParentClaim: ...

    def assert_current_inputs(self, spec: RecommendationGenerationSpec) -> None: ...

    def resolve_prompt(
        self,
        *,
        spec: RecommendationGenerationSpec,
        role: RecommendationModelRole,
        structured_input: Mapping[str, object],
        output_schema: Mapping[str, object],
        application_output_schema: Mapping[str, object],
    ) -> ResolvedGenerationPrompt: ...

    def resolve_workflow_release(
        self,
        *,
        task_role: RecommendationModelRole,
        prompt: ResolvedGenerationPrompt,
    ) -> tuple[UUID, str] | None: ...

    def reserve_model_task(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
    ) -> None: ...

    def prepare_model_task(
        self, task: RecommendationModelTask
    ) -> RecommendationTaskArtifactRef: ...

    def activate_model_task(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
        artifact: RecommendationTaskArtifactRef,
    ) -> None: ...

    def load_model_task(self, lease: WorkerLease) -> RecommendationModelTask: ...

    def record_model_success(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
        reference: RecommendationModelResultRef | RecommendationDifyResultRef,
    ) -> None: ...

    def record_model_failure(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
        status: str,
        error_code: str,
    ) -> None: ...

    def wake_parent(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
    ) -> None: ...

    def finalize_parent(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        result: RecommendationGenerationResult,
    ) -> None: ...


__all__ = ["RecommendationGenerationWorkerRepository"]
