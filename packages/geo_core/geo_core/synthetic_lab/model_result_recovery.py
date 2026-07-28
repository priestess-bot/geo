"""Governed recovery of completed Synthetic child model-call results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.artifact_recovery import (
    ProviderArtifactRecoveryPort,
    ProviderArtifactRecoveryRequest,
    RecoveredProviderArtifact,
)
from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.child_model_calls import SyntheticChildModelCallTask
from geo_core.synthetic_lab.execution_contracts import (
    SyntheticExecutionBackend,
    SyntheticExecutionError,
    SyntheticModelResult,
    SyntheticWorkflowResult,
)
from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.bootstrap_validation import validate_bootstrap_output
from geo_core.workflow_runtime.contracts import canonical_json_hash as workflow_output_hash


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SyntheticModelArtifactRecoveryRequest:
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
            raise ValueError("Synthetic artifact recovery UUIDs cannot be zero")
        if self.source_model_job_id == self.recovery_parent_job_id:
            raise ValueError("Synthetic recovery source must be a child Job")
        if self.fencing_generation < 1 or not self.purpose.strip():
            raise ValueError("Synthetic recovery fence and purpose are required")
        if _SHA256.fullmatch(self.expected_output_hash) is None:
            raise ValueError("Synthetic recovery output hash must be SHA-256")
        object.__setattr__(self, "output_schema", MappingProxyType(dict(self.output_schema)))
        object.__setattr__(
            self,
            "application_output_schema",
            MappingProxyType(dict(self.application_output_schema)),
        )
        object.__setattr__(
            self, "output_schema_hash", canonical_json_hash(self.output_schema)
        )
        object.__setattr__(
            self,
            "application_output_schema_hash",
            canonical_json_hash(self.application_output_schema),
        )


class SyntheticModelArtifactRecoveryPort(Protocol):
    def recover_child_derived(
        self, request: SyntheticModelArtifactRecoveryRequest
    ) -> RecoveredProviderArtifact: ...


class ProviderArtifactSyntheticRecoveryAdapter:
    """Map a parent/child Synthetic fence into Model Gateway artifact recovery."""

    def __init__(self, recovery: ProviderArtifactRecoveryPort) -> None:
        self._recovery = recovery

    def recover_child_derived(
        self, request: SyntheticModelArtifactRecoveryRequest
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


class GovernedSyntheticChildResultLoader:
    """Return a completed child output only after artifact and lineage verification."""

    def __init__(self, recovery: SyntheticModelArtifactRecoveryPort) -> None:
        self._recovery = recovery

    def load(
        self,
        *,
        parent_lease: WorkerLease,
        task: SyntheticChildModelCallTask,
        model_attempt_id: UUID,
        model_call_id: UUID,
        output_hash: str,
        response_hash: str,
        configured_model: str,
        reported_model: str | None,
    ) -> SyntheticModelResult:
        if (
            parent_lease.project_id != task.project_id
            or parent_lease.job_id != task.parent_job_id
            or parent_lease.kind != task.parent_job_kind
        ):
            raise SyntheticExecutionError("Synthetic child result recovery crosses parent lease")
        frozen = task.prompt.frozen
        if configured_model != frozen.configured_model:
            raise SyntheticExecutionError("Synthetic child terminal configured model changed")
        recovered = self._recovery.recover_child_derived(
            SyntheticModelArtifactRecoveryRequest(
                project_id=task.project_id,
                source_model_job_id=task.child_job_id,
                recovery_parent_job_id=parent_lease.job_id,
                lease_token=parent_lease.lease_token,
                fencing_generation=parent_lease.fencing_generation,
                model_call_attempt_id=model_attempt_id,
                expected_output_hash=output_hash,
                output_schema=task.prompt.output_schema,
                application_output_schema=task.prompt.application_output_schema,
                purpose=frozen.purpose,
            )
        )
        if (
            recovered.model_call_attempt_id != model_attempt_id
            or recovered.output_hash != output_hash
            or canonical_hash(recovered.output) != output_hash
        ):
            raise SyntheticExecutionError("recovered Synthetic child artifact lineage changed")
        provider = frozen.route.provider
        effective_reported = reported_model or configured_model
        identity_hash = canonical_hash(
            {
                "provider": provider,
                "adapter_release_id": frozen.route.adapter_release_id,
                "adapter_release_hash": frozen.route.adapter_release_hash,
                "model_release_id": frozen.route.model_release_id,
                "model_release_hash": frozen.route.model_release_hash,
                "configured_model": configured_model,
                "reported_model": effective_reported,
            }
        )
        request_hash = canonical_hash(
            {
                "job_id": task.child_job_id,
                "step_key": task.step_key,
                "prompt_bundle_hash": task.prompt.prompt_bundle_hash,
                "structured_input_hash": task.prompt.structured_input_hash,
                "seed": task.deterministic_seed,
            }
        )
        return SyntheticModelResult(
            model_attempt_id=model_attempt_id,
            model_call_id=model_call_id,
            output=recovered.output,
            provider=provider,
            configured_model=configured_model,
            reported_model=effective_reported,
            model_identity_hash=identity_hash,
            request_hash=request_hash,
            response_hash=response_hash,
        )

    def load_dify(
        self,
        *,
        parent_lease: WorkerLease,
        task: SyntheticChildModelCallTask,
        attempt_id: UUID,
        output: Mapping[str, object],
        output_hash: str,
        configured_model: str,
        reported_model: str | None,
        runtime_release_id: UUID,
        runtime_release_hash: str,
        published_snapshot_id: UUID | None = None,
        published_snapshot_hash: str | None = None,
    ) -> SyntheticWorkflowResult:
        if (
            parent_lease.project_id != task.project_id
            or parent_lease.job_id != task.parent_job_id
            or parent_lease.kind != task.parent_job_kind
        ):
            raise SyntheticExecutionError("Synthetic Dify recovery crosses parent lease")
        if configured_model != task.prompt.frozen.configured_model:
            raise SyntheticExecutionError("Synthetic Dify configured model changed")
        if task.execution_backend is not SyntheticExecutionBackend.DIFY:
            raise SyntheticExecutionError("Synthetic Dify result changed the frozen backend")
        if (
            runtime_release_id != task.workflow_release_id
            or runtime_release_hash != task.workflow_release_hash
        ):
            raise SyntheticExecutionError("Synthetic Dify Workflow Release changed")
        # Dify persists UTF-8 canonical JSON. Synthetic's general hash escapes
        # non-ASCII and therefore differs for ordinary punctuation such as curly quotes.
        if workflow_output_hash(output) != output_hash:
            raise SyntheticExecutionError("Synthetic Dify output hash changed")
        try:
            validate_bootstrap_output(
                default_prompt_bootstrap_spec(task.prompt.frozen.program_kind),
                input_value=task.structured_input,
                output=output,
            )
        except Exception as exc:
            raise SyntheticExecutionError(
                "recovered Synthetic Dify result failed its frozen contract"
            ) from exc
        effective_reported = reported_model or configured_model
        return SyntheticWorkflowResult(
            workflow_attempt_id=attempt_id,
            workflow_release_id=runtime_release_id,
            workflow_release_hash=runtime_release_hash,
            output=output,
            configured_model=configured_model,
            reported_model=effective_reported,
            model_identity_hash=canonical_hash(
                {
                    "provider": "dify",
                    "runtime_release_id": runtime_release_id,
                    "runtime_release_hash": runtime_release_hash,
                    "configured_model": configured_model,
                    "reported_model": effective_reported,
                }
            ),
            request_hash=canonical_hash(
                {
                    "parent_task_input_hash": task.parent_task_input_hash,
                    "step_key": task.step_key,
                    "prompt_bundle_hash": task.prompt.prompt_bundle_hash,
                    "structured_input_hash": task.prompt.structured_input_hash,
                }
            ),
            response_hash=output_hash,
            published_snapshot_id=published_snapshot_id,
            published_snapshot_hash=published_snapshot_hash,
        )


__all__ = [
    "GovernedSyntheticChildResultLoader",
    "ProviderArtifactSyntheticRecoveryAdapter",
    "SyntheticModelArtifactRecoveryPort",
    "SyntheticModelArtifactRecoveryRequest",
]
