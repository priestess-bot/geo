"""Ports and small transfer types for Recommendation generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from geo_core.model_gateway.application import ModelCallExecution
from geo_core.model_gateway.application_support import ExecuteModelCall
from geo_core.model_gateway.contracts import ModelCaptureMethod, ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.recommendations.decision import RecommendationDecision
from geo_core.recommendations.evidence import FactRef, RecommendationScope
from geo_core.recommendations.generation_contracts import (
    FrozenPromptBinding,
    GenerationJobOwnership,
    GenerationJobStatus,
    RecommendationGenerationJob,
    RecommendationGenerationResult,
    RecommendationGenerationSpec,
    ResolvedGenerationPrompt,
)
from geo_core.recommendations.models import RecommendationType


@dataclass(frozen=True)
class SelectedRecommendationRef:
    kind: str
    resource_id: str


@dataclass(frozen=True)
class ParsedRecommendationOutput:
    recommendation_type: RecommendationType
    scope: RecommendationScope
    selected_refs: tuple[SelectedRecommendationRef, ...]
    decision: RecommendationDecision


class RecommendationPromptResolverPort(Protocol):
    """Render one exact current binding; stale bindings must fail closed."""

    def resolve(
        self,
        *,
        binding: FrozenPromptBinding,
        route: ModelRoute,
        configured_model: str,
        model_policy: ModelPolicy,
        capture_method: ModelCaptureMethod,
        search_mode: str | None,
        structured_input: Mapping[str, object],
        output_schema: Mapping[str, object],
        application_output_schema: Mapping[str, object],
    ) -> ResolvedGenerationPrompt: ...


class RecommendationFactResolverPort(Protocol):
    def current_facts(
        self,
        *,
        project_id: UUID,
        frozen_facts: tuple[FactRef, ...],
    ) -> tuple[FactRef, ...]: ...


class ModelGatewayApplicationPort(Protocol):
    """Structural match for ModelCallApplication; raw adapters are not accepted."""

    def execute(
        self,
        command: ExecuteModelCall,
        *,
        policy: ModelPolicy,
    ) -> ModelCallExecution: ...


class RecommendationGenerationRepositoryPort(Protocol):
    def create_job(
        self,
        *,
        job_id: UUID,
        spec: RecommendationGenerationSpec,
        idempotency_key_hash: str,
    ) -> tuple[RecommendationGenerationJob, bool]: ...

    def claim_job(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        worker_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> RecommendationGenerationJob: ...

    def get_job(self, *, project_id: UUID, job_id: UUID) -> RecommendationGenerationJob: ...

    def request_cancel(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        expected_version: int | None = None,
        idempotency_key_hash: str | None = None,
    ) -> RecommendationGenerationJob: ...

    def require_owned(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        ownership: GenerationJobOwnership,
        now: datetime,
    ) -> RecommendationGenerationJob: ...

    def reserve_model_call(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        ownership: GenerationJobOwnership,
        now: datetime,
    ) -> RecommendationGenerationJob: ...

    def finish_job(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        ownership: GenerationJobOwnership,
        now: datetime,
        status: GenerationJobStatus,
        expected_input_hash: str,
        result: RecommendationGenerationResult | None,
        error_code: str | None,
    ) -> RecommendationGenerationJob: ...

    def result(
        self, *, project_id: UUID, job_id: UUID
    ) -> RecommendationGenerationResult | None: ...


__all__ = [
    "ModelGatewayApplicationPort",
    "ParsedRecommendationOutput",
    "RecommendationFactResolverPort",
    "RecommendationGenerationRepositoryPort",
    "RecommendationPromptResolverPort",
    "SelectedRecommendationRef",
]
