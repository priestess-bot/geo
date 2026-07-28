"""Selector-only admission for governed Recommendation generation Jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.recommendations.application_support import require_project_role
from geo_core.recommendations.errors import RecommendationRuleViolation
from geo_core.recommendations.evidence import RecommendationScope
from geo_core.recommendations.generation_application import (
    RecommendationGenerationApplication,
)
from geo_core.recommendations.generation_contracts import (
    GenerationExecution,
    RecommendationGenerationConflict,
    RecommendationGenerationJob,
    RecommendationGenerationSpec,
)
from geo_core.recommendations.models import require_aware
from geo_core.recommendations.resolution import (
    RecommendationEvidenceSelector,
    freeze_evidence_selectors,
)


_CONTRIBUTOR_ROLES = frozenset({"owner", "admin", "analyst"})
_READER_ROLES = frozenset({"owner", "admin", "analyst", "viewer"})


@dataclass(frozen=True)
class GenerationModelSelector:
    """One project-scoped runtime option; all release truth remains server-owned."""

    runtime_selection_id: UUID
    search_mode: str | None = None

    def __post_init__(self) -> None:
        search_mode = self.search_mode.strip().lower() if self.search_mode is not None else None
        if search_mode is not None:
            if (
                not search_mode
                or len(search_mode) > 64
                or not search_mode.replace("_", "").replace("-", "").isalnum()
            ):
                raise RecommendationRuleViolation("generation model search mode is unsupported")
        object.__setattr__(self, "search_mode", search_mode)


@dataclass(frozen=True)
class RecommendationGenerationSelection:
    """Only identities and user intent cross the API trust boundary."""

    project_id: UUID
    scope: RecommendationScope
    evidence_selectors: tuple[RecommendationEvidenceSelector, ...]
    prompt_binding_id: UUID
    model: GenerationModelSelector
    valid_until: datetime
    minimum_real_observations: int = 3
    arbiter_prompt_binding_id: UUID | None = None
    arbiter_model: GenerationModelSelector | None = None

    def __post_init__(self) -> None:
        if self.scope.project_id != self.project_id:
            raise RecommendationRuleViolation("generation selection crosses Project scope")
        object.__setattr__(
            self,
            "evidence_selectors",
            freeze_evidence_selectors(self.evidence_selectors),
        )
        if len(self.evidence_selectors) > 100:
            raise RecommendationRuleViolation(
                "Recommendation generation accepts at most 100 evidence selectors; "
                "reduce the selection and retry"
            )
        require_aware(self.valid_until, "generation validity time")
        if not 1 <= self.minimum_real_observations <= 1000:
            raise RecommendationRuleViolation("minimum real observation count is out of bounds")
        if (self.arbiter_prompt_binding_id is None) != (self.arbiter_model is None):
            raise RecommendationRuleViolation(
                "arbiter Prompt and model selectors must be supplied together"
            )


class RecommendationGenerationAdmissionPort(Protocol):
    """Resolve current project-scoped evidence, Prompt and Model catalog truth."""

    def resolve(
        self,
        *,
        selection: RecommendationGenerationSelection,
        created_by: str,
    ) -> RecommendationGenerationSpec: ...


class RecommendationGenerationSubmissionApplication:
    """Public application boundary: enqueue, read and cancel only."""

    def __init__(
        self,
        *,
        generation: RecommendationGenerationApplication,
        admission: RecommendationGenerationAdmissionPort,
    ) -> None:
        self._generation = generation
        self._admission = admission

    def enqueue(
        self,
        principal: AccessPrincipal,
        *,
        selection: RecommendationGenerationSelection,
        idempotency_key: str,
        recovery_of_attempt_id: UUID | None = None,
        dify_reconciliation_token: str | None = None,
    ) -> GenerationExecution:
        require_project_role(
            principal,
            selection.project_id,
            allowed=_CONTRIBUTOR_ROLES,
        )
        if recovery_of_attempt_id is not None or dify_reconciliation_token is not None:
            raise RecommendationGenerationConflict(
                "Dify unknown-outcome recovery requires PostgreSQL-backed atomic admission"
            )
        spec = self._admission.resolve(
            selection=selection,
            created_by=str(principal.identity_id),
        )
        return self._generation.enqueue(spec, idempotency_key=idempotency_key)

    def get(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> GenerationExecution:
        require_project_role(principal, project_id, allowed=_READER_ROLES)
        return self._generation.get(project_id=project_id, job_id=job_id)

    def cancel(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> RecommendationGenerationJob:
        require_project_role(principal, project_id, allowed=_CONTRIBUTOR_ROLES)
        return self._generation.cancel(
            project_id=project_id,
            job_id=job_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )


__all__ = [
    "GenerationModelSelector",
    "RecommendationGenerationAdmissionPort",
    "RecommendationGenerationSelection",
    "RecommendationGenerationSubmissionApplication",
]
