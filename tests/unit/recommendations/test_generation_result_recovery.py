from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

from geo_core.model_gateway.artifact_recovery import RecoveredProviderArtifact
from geo_core.recommendations.generation_result_recovery import (
    GovernedRecommendationModelResultLoader,
    ProviderArtifactRecommendationRecoveryAdapter,
)
from geo_core.recommendations.generation_worker_contracts import (
    RecommendationModelResultRef,
)

from .generation_test_support import NOW, worker_lease
from .test_generation_artifacts import _task
from geo_core.recommendations.generation_worker_contracts import (
    RECOMMENDATION_PARENT_JOB_KIND,
)


class _Recovery:
    def __init__(self, recovered: RecoveredProviderArtifact) -> None:
        self.recovered = recovered
        self.requests: list[object] = []

    def recover_child_derived(self, request):
        self.requests.append(request)
        return self.recovered


class _ProviderRecovery:
    def __init__(self, recovered: RecoveredProviderArtifact) -> None:
        self.recovered = recovered
        self.requests: list[object] = []

    def recover_derived(self, request):
        self.requests.append(request)
        return self.recovered


def test_parent_recovers_model_output_with_exact_fence_schema_and_purpose() -> None:
    task = _task()
    parent = worker_lease(RECOMMENDATION_PARENT_JOB_KIND, job_id=task.parent_job_id)
    reference = _reference()
    provider = _ProviderRecovery(_recovered(reference))
    loader = GovernedRecommendationModelResultLoader(
        ProviderArtifactRecommendationRecoveryAdapter(provider)
    )

    result = loader.load(parent_lease=parent, task=task, reference=reference)

    request = provider.requests[0]
    assert request.source_model_job_id == task.child_job_id
    assert request.recovery_job_id == parent.job_id
    assert request.lease_token == parent.lease_token
    assert request.fencing_generation == parent.fencing_generation
    assert request.purpose == "recommendations.recommendation"
    assert request.output_schema == task.prompt.output_schema
    assert result.output == {"recommendation_type": "gap"}
    assert result.call_log_id == reference.model_call_log_id
    assert result.derived_artifact_reference == reference.artifact_uri


def test_parent_rejects_recovered_artifact_with_changed_manifest_lineage() -> None:
    task = _task()
    parent = worker_lease(RECOMMENDATION_PARENT_JOB_KIND, job_id=task.parent_job_id)
    reference = _reference()
    recovery = _Recovery(
        replace(_recovered(reference), manifest_hash="0" * 64)
    )

    with pytest.raises(ValueError, match="lineage changed"):
        GovernedRecommendationModelResultLoader(recovery).load(
            parent_lease=parent,
            task=task,
            reference=reference,
        )


def _reference() -> RecommendationModelResultRef:
    return RecommendationModelResultRef(
        model_attempt_id=uuid4(),
        model_call_log_id=uuid4(),
        response_hash="a" * 64,
        output_hash="b" * 64,
        artifact_uri="s3://model-artifacts/derived/manifest.json",
        artifact_manifest_hash="c" * 64,
        artifact_content_hash="d" * 64,
    )


def _recovered(reference: RecommendationModelResultRef) -> RecoveredProviderArtifact:
    return RecoveredProviderArtifact(
        model_call_attempt_id=reference.model_attempt_id,
        artifact_id=uuid4(),
        manifest_hash=reference.artifact_manifest_hash,
        content_hash=reference.artifact_content_hash,
        output_hash=reference.output_hash,
        output={"recommendation_type": "gap"},
        recovery_receipt_id=uuid4(),
        recovery_receipt_hash="e" * 64,
        recovered_at=NOW,
    )
