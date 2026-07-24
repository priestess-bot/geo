"""Fail-closed composition contract for the Recommendation Internal API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import importlib
import os
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.recommendations import (
    ApprovedRecommendation,
    CommandReceipt,
    DownstreamDraftKind,
    InputChangeReason,
    InvalidatedRecommendation,
    PreparedDraftAction,
    RecommendationApplication,
    RecommendationDecision,
    RecommendationScope,
    RecommendationForbidden,
    RecommendationNotFound,
    RecommendationType,
    RecommendationWorkflow,
    ReviewedRecommendation,
)
from geo_core.recommendations.generation_admission import (
    RecommendationGenerationSelection,
    RecommendationGenerationSubmissionApplication,
)
from geo_core.recommendations.generation_contracts import (
    GenerationExecution,
    RecommendationGenerationJob,
)
from geo_core.recommendations.resolution import RecommendationEvidenceSelector


@dataclass(frozen=True)
class RecommendationPageRead:
    items: tuple[RecommendationWorkflow, ...]
    total: int
    limit: int
    offset: int


class RecommendationApi(Protocol):
    def enqueue_generation_job(
        self,
        principal: AccessPrincipal,
        *,
        selection: RecommendationGenerationSelection,
        idempotency_key: str,
    ) -> GenerationExecution: ...

    def get_generation_job(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> GenerationExecution: ...

    def cancel_generation_job(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> RecommendationGenerationJob: ...

    def create_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_type: RecommendationType,
        scope: RecommendationScope,
        decision: RecommendationDecision,
        evidence_selectors: tuple[RecommendationEvidenceSelector, ...],
        proposed_draft_kind: DownstreamDraftKind | None,
        valid_until: datetime,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[RecommendationWorkflow]: ...

    def get_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
    ) -> RecommendationWorkflow: ...

    def list_recommendations(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> RecommendationPageRead: ...

    def submit_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[RecommendationWorkflow]: ...

    def review_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        notes: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[ReviewedRecommendation]: ...

    def approve_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[ApprovedRecommendation]: ...

    def reject_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        reason: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[RecommendationWorkflow]: ...

    def expire_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        reason: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[InvalidatedRecommendation]: ...

    def reconcile_stale(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        change_reason: InputChangeReason,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[InvalidatedRecommendation]: ...

    def prepare_draft_action(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        draft_id: UUID,
        change_reason: InputChangeReason,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[PreparedDraftAction]: ...


def build_recommendation_api() -> RecommendationApi | None:
    """Resolve the future PostgreSQL builder without importing it at module load."""

    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    module_name = "geo_core.recommendations.postgres"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        return None
    builder = getattr(module, "build_recommendation_api", None)
    if not callable(builder):
        return None
    return cast(RecommendationApi, builder(database_url=database_url))


def memory_recommendation_api(
    application: RecommendationApplication,
    *,
    generation: RecommendationGenerationSubmissionApplication | None = None,
) -> RecommendationApi:
    """Add a scoped read projection to the in-memory application for API tests."""

    return cast(RecommendationApi, _MemoryRecommendationApi(application, generation=generation))


class _MemoryRecommendationApi:
    _MUTATIONS = frozenset(
        {
            "create_recommendation",
            "submit_recommendation",
            "review_recommendation",
            "approve_recommendation",
            "reject_recommendation",
            "expire_recommendation",
            "reconcile_stale",
            "prepare_draft_action",
        }
    )

    def __init__(
        self,
        application: RecommendationApplication,
        *,
        generation: RecommendationGenerationSubmissionApplication | None,
    ) -> None:
        self._application = application
        self._generation = generation
        self._workflows: dict[tuple[UUID, UUID], RecommendationWorkflow] = {}

    def enqueue_generation_job(
        self,
        principal: AccessPrincipal,
        *,
        selection: RecommendationGenerationSelection,
        idempotency_key: str,
    ) -> GenerationExecution:
        return self._require_generation().enqueue(
            principal,
            selection=selection,
            idempotency_key=idempotency_key,
        )

    def get_generation_job(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> GenerationExecution:
        return self._require_generation().get(
            principal,
            project_id=project_id,
            job_id=job_id,
        )

    def cancel_generation_job(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> RecommendationGenerationJob:
        return self._require_generation().cancel(
            principal,
            project_id=project_id,
            job_id=job_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )

    def _require_generation(self) -> RecommendationGenerationSubmissionApplication:
        if self._generation is None:
            raise RecommendationNotFound("Recommendation generation is not configured")
        return self._generation

    def __getattr__(self, name: str) -> Callable[..., object]:
        target = cast(Callable[..., object], getattr(self._application, name))
        if name not in self._MUTATIONS:
            return target

        def invoke(*args: object, **kwargs: object) -> object:
            result = target(*args, **kwargs)
            self._capture(result)
            return result

        return invoke

    def get_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
    ) -> RecommendationWorkflow:
        _require_reader(principal, project_id)
        workflow = self._workflows.get((project_id, recommendation_id))
        if workflow is None:
            raise RecommendationNotFound("Recommendation does not exist in the project scope")
        return workflow

    def list_recommendations(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> RecommendationPageRead:
        _require_reader(principal, project_id)
        values = tuple(
            sorted(
                (
                    workflow
                    for (item_project_id, _), workflow in self._workflows.items()
                    if item_project_id == project_id
                ),
                key=lambda item: (item.recommendation.created_at, str(item.recommendation.id)),
                reverse=True,
            )
        )
        return RecommendationPageRead(values[offset : offset + limit], len(values), limit, offset)

    def _capture(self, result: object) -> None:
        value = getattr(result, "value", result)
        workflow = getattr(value, "workflow", value)
        check = getattr(value, "check", None)
        if check is not None:
            workflow = check.workflow
        if isinstance(workflow, RecommendationWorkflow):
            key = (workflow.recommendation.project_id, workflow.recommendation.id)
            self._workflows[key] = workflow


def _require_reader(principal: AccessPrincipal, project_id: UUID) -> None:
    for membership in principal.memberships:
        if membership.project_id == project_id and membership.tenant_id == principal.tenant_id:
            if membership.role not in {"owner", "admin", "analyst", "viewer"}:
                raise RecommendationForbidden("project role cannot read Recommendations")
            return
    raise RecommendationNotFound("Recommendation project is outside the authenticated scope")


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return direct
