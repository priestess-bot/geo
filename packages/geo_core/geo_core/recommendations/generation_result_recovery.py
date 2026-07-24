"""Recover Recommendation child outputs through the governed Model Gateway path."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
import re
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway import (
    ModelAudience,
    ModelGatewayResult,
)
from geo_core.model_gateway.artifact_recovery import (
    ProviderArtifactRecoveryPort,
    ProviderArtifactRecoveryRequest,
    RecoveredProviderArtifact,
)
from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.recommendations.generation_worker_contracts import (
    RecommendationModelResultRef,
    RecommendationModelTask,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class RecommendationModelArtifactRecoveryRequest:
    project_id: UUID
    source_model_job_id: UUID
    recovery_parent_job_id: UUID
    lease_token: UUID
    fencing_generation: int
    model_call_attempt_id: UUID
    expected_output_hash: str
    output_schema: Mapping[str, object] = field(repr=False)
    application_output_schema: Mapping[str, object] = field(repr=False)
    purpose: str
    output_schema_hash: str = field(init=False)
    application_output_schema_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if min(
            self.project_id.int,
            self.source_model_job_id.int,
            self.recovery_parent_job_id.int,
            self.lease_token.int,
            self.model_call_attempt_id.int,
        ) == 0:
            raise ValueError("Recommendation artifact recovery UUIDs cannot be zero")
        if self.source_model_job_id == self.recovery_parent_job_id:
            raise ValueError("Recommendation recovery source must be a child Job")
        if self.fencing_generation < 1 or not self.purpose.strip():
            raise ValueError("Recommendation artifact recovery fence and purpose are required")
        if _SHA256.fullmatch(self.expected_output_hash) is None:
            raise ValueError("Recommendation recovery output hash must be SHA-256")
        object.__setattr__(self, "output_schema", MappingProxyType(dict(self.output_schema)))
        object.__setattr__(
            self,
            "application_output_schema",
            MappingProxyType(dict(self.application_output_schema)),
        )
        object.__setattr__(
            self,
            "output_schema_hash",
            canonical_json_hash(self.output_schema),
        )
        object.__setattr__(
            self,
            "application_output_schema_hash",
            canonical_json_hash(self.application_output_schema),
        )


class RecommendationModelArtifactRecoveryPort(Protocol):
    def recover_child_derived(
        self, request: RecommendationModelArtifactRecoveryRequest
    ) -> RecoveredProviderArtifact: ...


class ProviderArtifactRecommendationRecoveryAdapter:
    """Map the two-Job Recommendation fence into Model Gateway recovery."""

    def __init__(self, recovery: ProviderArtifactRecoveryPort) -> None:
        self._recovery = recovery

    def recover_child_derived(
        self, request: RecommendationModelArtifactRecoveryRequest
    ) -> RecoveredProviderArtifact:
        return self._recovery.recover_derived(
            ProviderArtifactRecoveryRequest(
                project_id=request.project_id,
                source_model_job_id=request.source_model_job_id,
                recovery_job_id=request.recovery_parent_job_id,
                lease_token=request.lease_token,
                fencing_generation=request.fencing_generation,
                model_call_attempt_id=request.model_call_attempt_id,
                expected_output_hash=request.expected_output_hash,
                output_schema=request.output_schema,
                application_output_schema=request.application_output_schema,
                purpose=request.purpose,
            )
        )


class GovernedRecommendationModelResultLoader:
    """Materialize only a verified derived artifact under the parent Job fence."""

    def __init__(self, recovery: RecommendationModelArtifactRecoveryPort) -> None:
        self._recovery = recovery

    def load(
        self,
        *,
        parent_lease: WorkerLease,
        task: RecommendationModelTask,
        reference: RecommendationModelResultRef,
    ) -> ModelGatewayResult:
        if (
            parent_lease.project_id != task.project_id
            or parent_lease.job_id != task.parent_job_id
        ):
            raise ValueError("Recommendation result recovery crosses parent Job scope")
        recovered = self._recovery.recover_child_derived(
            RecommendationModelArtifactRecoveryRequest(
                project_id=task.project_id,
                source_model_job_id=task.child_job_id,
                recovery_parent_job_id=parent_lease.job_id,
                lease_token=parent_lease.lease_token,
                fencing_generation=parent_lease.fencing_generation,
                model_call_attempt_id=reference.model_attempt_id,
                expected_output_hash=reference.output_hash,
                output_schema=task.prompt.output_schema,
                application_output_schema=task.prompt.application_output_schema,
                purpose=task.prompt.binding.purpose,
            )
        )
        if (
            recovered.model_call_attempt_id != reference.model_attempt_id
            or recovered.manifest_hash != reference.artifact_manifest_hash
            or recovered.content_hash != reference.artifact_content_hash
            or recovered.output_hash != reference.output_hash
        ):
            raise ValueError("Recommendation recovered artifact lineage changed")
        route = task.prompt.route
        return ModelGatewayResult(
            output=dict(recovered.output),
            call_log_id=reference.model_call_log_id,
            provider_request_id=None,
            configured_model=task.prompt.configured_model,
            provider_reported_model=None,
            prompt_tokens=None,
            completion_tokens=None,
            cost_usd=None,
            finish_reason=None,
            response_hash=reference.response_hash,
            provider=route.provider,
            adapter_release_id=route.adapter_release_id,
            adapter_release_hash=route.adapter_release_hash,
            model_release_id=route.model_release_id,
            model_release_hash=route.model_release_hash,
            derived_artifact_reference=reference.artifact_uri,
            derived_artifact_manifest_hash=reference.artifact_manifest_hash,
            derived_artifact_content_hash=reference.artifact_content_hash,
            usage_purpose=task.prompt.binding.purpose,
            usage_audience=ModelAudience.INTERNAL_WORKER,
            capture_method=task.prompt.capture_method,
            search_mode=task.prompt.search_mode,
        )


__all__ = [
    "GovernedRecommendationModelResultLoader",
    "ProviderArtifactRecommendationRecoveryAdapter",
    "RecommendationModelArtifactRecoveryPort",
    "RecommendationModelArtifactRecoveryRequest",
]
