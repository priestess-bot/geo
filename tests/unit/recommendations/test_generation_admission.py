from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.recommendations import (
    GenerationModelSelector,
    RecommendationEvidenceKind,
    RecommendationEvidenceSelector,
    RecommendationForbidden,
    RecommendationGenerationSelection,
    RecommendationGenerationSubmissionApplication,
)
from geo_core.recommendations.generation_application import (
    RecommendationGenerationApplication,
)
from geo_core.recommendations.generation_contracts import RecommendationGenerationSpec
from geo_core.recommendations.generation_memory import (
    InMemoryRecommendationGenerationRepository,
)
from tests.unit.recommendations.generation_test_support import (
    FactResolverStub,
    GatewayApplicationStub,
    NOW,
    PROJECT_ID,
    PromptResolverStub,
    generation_spec,
)


TENANT_ID = UUID("50000000-0000-0000-0000-000000000005")


@dataclass
class AdmissionStub:
    spec: RecommendationGenerationSpec
    calls: int = 0

    def resolve(self, *, selection, created_by: str) -> RecommendationGenerationSpec:
        self.calls += 1
        assert selection.project_id == self.spec.project_id
        assert created_by
        return self.spec


def test_submission_boundary_only_resolves_then_enqueues_reads_and_cancels() -> None:
    repository = InMemoryRecommendationGenerationRepository()
    spec = generation_spec()
    admission = AdmissionStub(spec)
    generation = RecommendationGenerationApplication(
        repository=repository,
        prompts=PromptResolverStub(),
        facts=FactResolverStub(),
        model_gateway=GatewayApplicationStub(),
    )
    application = RecommendationGenerationSubmissionApplication(
        generation=generation,
        admission=admission,
    )
    selection = RecommendationGenerationSelection(
        project_id=PROJECT_ID,
        scope=spec.evidence.scope,
        evidence_selectors=(
            RecommendationEvidenceSelector(
                RecommendationEvidenceKind.OBSERVATION,
                spec.evidence.observations[0].resource_id,
            ),
        ),
        prompt_binding_id=spec.prompt_binding.binding_id,
        model=GenerationModelSelector(
            runtime_selection_id=uuid4(),
        ),
        valid_until=NOW + timedelta(days=30),
    )

    queued = application.enqueue(
        _principal("analyst"),
        selection=selection,
        idempotency_key="recommendation:generation:one",
    )
    loaded = application.get(
        _principal("viewer"),
        project_id=PROJECT_ID,
        job_id=queued.job.id,
    )
    cancelled = application.cancel(
        _principal("admin"),
        project_id=PROJECT_ID,
        job_id=queued.job.id,
        expected_version=queued.job.version,
        idempotency_key="recommendation:generation:cancel",
    )
    replay = application.cancel(
        _principal("admin"),
        project_id=PROJECT_ID,
        job_id=queued.job.id,
        expected_version=queued.job.version,
        idempotency_key="recommendation:generation:cancel",
    )

    assert admission.calls == 1
    assert loaded.job == queued.job
    assert cancelled.cancel_requested is True
    assert cancelled.status.value == "cancelled"
    assert replay == cancelled


def test_submission_boundary_enforces_project_role_before_resolution() -> None:
    spec = generation_spec()
    admission = AdmissionStub(spec)
    generation = RecommendationGenerationApplication(
        repository=InMemoryRecommendationGenerationRepository(),
        prompts=PromptResolverStub(),
        facts=FactResolverStub(),
        model_gateway=GatewayApplicationStub(),
    )
    application = RecommendationGenerationSubmissionApplication(
        generation=generation,
        admission=admission,
    )
    selection = RecommendationGenerationSelection(
        project_id=PROJECT_ID,
        scope=spec.evidence.scope,
        evidence_selectors=(
            RecommendationEvidenceSelector(
                RecommendationEvidenceKind.FACT,
                spec.evidence.facts[0].resource_id,
            ),
        ),
        prompt_binding_id=spec.prompt_binding.binding_id,
        model=GenerationModelSelector(
            runtime_selection_id=uuid4(),
        ),
        valid_until=spec.valid_until,
    )

    with pytest.raises(RecommendationForbidden):
        application.enqueue(
            _principal("viewer"),
            selection=selection,
            idempotency_key="recommendation:generation:forbidden",
        )
    assert admission.calls == 0


def _principal(role: str) -> AccessPrincipal:
    identity = uuid4()
    return AccessPrincipal(
        identity_id=identity,
        actor_id=str(identity),
        tenant_id=TENANT_ID,
        memberships=(MembershipRecord(PROJECT_ID, TENANT_ID, role),),
        auth_method="test",
    )
