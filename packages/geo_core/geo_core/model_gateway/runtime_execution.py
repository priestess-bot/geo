"""Admission and worker composition from the database-backed runtime catalog."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from geo_core.jobs.lifecycle import JobStatus
from geo_core.model_gateway.application import ModelCallApplication
from geo_core.model_gateway.contracts import ModelAudience, ModelPolicy, ModelRouteError
from geo_core.model_gateway.ports import (
    ModelCallJobAdmission,
    ModelCallUnitOfWorkFactory,
    PromptReleaseAdmission,
)
from geo_core.model_gateway.provider_adapters.artifacts import ProviderArtifactSink
from geo_core.model_gateway.provider_adapters.base import (
    CredentialResolver,
    ProviderAdapterRuntime,
)
from geo_core.model_gateway.provider_adapters.composition import (
    ExactProviderAdapterConfig,
    ExactProviderComposition,
    TransportFactory,
    build_exact_provider_composition,
)
from geo_core.model_gateway.runtime_catalog import (
    ApprovedRuntimeCatalog,
    FrozenRuntimeOption,
    NewModelCallJobSelection,
    select_approved_runtime,
)
from geo_core.model_gateway.runtime_errors import ModelCallJobAdmissionNotFound


MODEL_CALL_JOB_ADMISSION_VERSION = 1


class ModelCallAdmissionPersistence(Protocol):
    @property
    def uow_factory(self) -> ModelCallUnitOfWorkFactory: ...

    def admit_job(
        self,
        job: ModelCallJobAdmission,
        *,
        prompt: PromptReleaseAdmission,
        admitted_by: UUID,
        admitted_at: datetime,
    ) -> ModelCallJobAdmission: ...

    def load_job_admission(self, *, project_id: UUID, job_id: UUID) -> ModelCallJobAdmission: ...

    def refresh_job_admission_lease(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        job_version: int,
        lease_token: UUID,
        fencing_generation: int,
    ) -> ModelCallJobAdmission: ...


@dataclass(frozen=True)
class NewModelCallJobAdmissionRequest:
    """Server-owned facts required to admit one already-claimed Durable Job."""

    project_id: UUID
    job_id: UUID
    job_kind: str
    lease_token: UUID
    fencing_generation: int
    runtime_selection_id: UUID
    required_purpose: str
    search_mode: str | None
    usage_audience: ModelAudience
    prompt: PromptReleaseAdmission
    prompt_bundle_hash: str
    output_schema_hash: str
    application_output_schema_hash: str
    maximum_paid_calls: int
    maximum_concurrent_calls: int
    admitted_by: UUID
    admitted_at: datetime

    @property
    def portable_output_schema_hash(self) -> str:
        return self.output_schema_hash


@dataclass(frozen=True)
class AdmittedModelCallJob:
    job: ModelCallJobAdmission
    selection: NewModelCallJobSelection | None


@dataclass(frozen=True)
class LoadedModelCallRuntime:
    job: ModelCallJobAdmission
    policy: ModelPolicy
    composition: ExactProviderComposition
    application: ModelCallApplication


class ModelCallJobAdmitter(Protocol):
    def admit_claimed_job(
        self, request: NewModelCallJobAdmissionRequest
    ) -> AdmittedModelCallJob: ...

    def load_or_admit_claimed_job(
        self, request: NewModelCallJobAdmissionRequest
    ) -> AdmittedModelCallJob: ...


class ModelCallRuntimeLoader(Protocol):
    def load(self, *, project_id: UUID, job_id: UUID) -> LoadedModelCallRuntime: ...


class ModelCallRuntimeFactory:
    """Resolve new Jobs via approved state and load old Jobs via frozen lineage."""

    def __init__(
        self,
        *,
        catalog: ApprovedRuntimeCatalog,
        persistence: ModelCallAdmissionPersistence,
        credential_resolver: CredentialResolver,
        artifact_sink: ProviderArtifactSink,
        transport_factory: TransportFactory | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._catalog = catalog
        self._persistence = persistence
        self._credential_resolver = credential_resolver
        self._artifact_sink = artifact_sink
        self._transport_factory = transport_factory
        self._clock = clock

    def admit_claimed_job(self, request: NewModelCallJobAdmissionRequest) -> AdmittedModelCallJob:
        selection = select_approved_runtime(
            catalog=self._catalog,
            project_id=request.project_id,
            runtime_selection_id=request.runtime_selection_id,
            required_purpose=request.required_purpose,
            search_mode=request.search_mode,
        )
        policy = selection.policy
        maximum_paid = policy.maximum_paid_calls
        maximum_concurrent = policy.maximum_concurrent_calls
        if (
            maximum_paid is None
            or maximum_concurrent is None
            or request.maximum_paid_calls > maximum_paid
            or request.maximum_concurrent_calls > maximum_concurrent
        ):
            raise ModelRouteError("model-call Job budget exceeds the approved runtime policy")
        prompt = request.prompt
        if (
            prompt.project_id != request.project_id
            or prompt.purpose != request.required_purpose
            or prompt.output_schema_hash != request.output_schema_hash
            or prompt.application_output_schema_hash
            != request.application_output_schema_hash
        ):
            raise ModelRouteError("model-call Prompt differs from Job admission request")
        data_policy = selection.adapter_release.data_policy
        job = ModelCallJobAdmission(
            project_id=request.project_id,
            job_id=request.job_id,
            job_kind=request.job_kind,
            job_version=MODEL_CALL_JOB_ADMISSION_VERSION,
            admission_mode=prompt.admission_mode,
            status=JobStatus.RUNNING,
            lease_token=request.lease_token,
            fencing_generation=request.fencing_generation,
            purpose=request.required_purpose,
            usage_audience=request.usage_audience,
            route=selection.route,
            provider_secret_handle=selection.provider_secret_handle,
            runtime_manifest_id=selection.runtime_manifest_id,
            runtime_manifest_hash=selection.runtime_manifest_hash,
            runtime_option_id=selection.runtime_option_id,
            runtime_option_hash=selection.runtime_option_hash,
            prompt_binding_id=prompt.binding_id,
            prompt_release_id=prompt.release_id,
            prompt_release_hash=prompt.release_hash,
            prompt_state_id=prompt.state_id,
            prompt_state_version=prompt.state_version,
            prompt_test_set_hash=prompt.test_set_hash,
            prompt_bundle_hash=request.prompt_bundle_hash,
            output_schema_hash=request.output_schema_hash,
            application_output_schema_hash=request.application_output_schema_hash,
            policy_version_id=_policy_id(policy),
            policy_version_hash=_policy_hash(policy),
            maximum_paid_calls=request.maximum_paid_calls,
            maximum_concurrent_calls=request.maximum_concurrent_calls,
            raw_artifact_policy_hash=selection.adapter_release.data_policy_hash,
            raw_artifact_storage_decision=data_policy.storage.value,
            raw_artifact_cache_decision=data_policy.cache.value,
            raw_artifact_display_decision=data_policy.display.value,
            raw_artifact_redistribution_decision=data_policy.redistribution.value,
            raw_artifact_retention_days=data_policy.retention_days,
        )
        admitted = self._persistence.admit_job(
            job,
            prompt=prompt,
            admitted_by=request.admitted_by,
            admitted_at=request.admitted_at,
        )
        return AdmittedModelCallJob(admitted, selection)

    def load_or_admit_claimed_job(
        self, request: NewModelCallJobAdmissionRequest
    ) -> AdmittedModelCallJob:
        """Resume frozen lineage; only a typed absence may create an admission."""
        try:
            job = self._persistence.load_job_admission(
                project_id=request.project_id,
                job_id=request.job_id,
            )
        except ModelCallJobAdmissionNotFound:
            return self.admit_claimed_job(request)
        if (
            job.lease_token != request.lease_token
            or job.fencing_generation != request.fencing_generation
        ):
            _validate_resume_request(request, job, require_current_lease=False)
            job = self._persistence.refresh_job_admission_lease(
                project_id=request.project_id,
                job_id=request.job_id,
                job_version=MODEL_CALL_JOB_ADMISSION_VERSION,
                lease_token=request.lease_token,
                fencing_generation=request.fencing_generation,
            )
        _validate_resume_request(request, job)
        return AdmittedModelCallJob(job, None)

    def load(self, *, project_id: UUID, job_id: UUID) -> LoadedModelCallRuntime:
        job = self._persistence.load_job_admission(
            project_id=project_id,
            job_id=job_id,
        )
        frozen = self._catalog.load_frozen_runtime_option(job=job)
        _validate_frozen_runtime(job, frozen)
        runtime = ProviderAdapterRuntime(
            adapter_release=frozen.adapter_release,
            capture_method=frozen.adapter_release.expected_capture_method,
            allowed_purposes=frozen.allowed_purposes,
            allowed_models=frozenset({frozen.model_release.configured_model}),
            allowed_search_modes=frozen.allowed_search_modes,
        )
        config = ExactProviderAdapterConfig(
            runtime=runtime,
            secret_reference_id=frozen.secret_reference_id,
            microsoft_endpoint=frozen.microsoft_endpoint,
            microsoft_agent_reference=frozen.microsoft_agent_reference,
        )
        composition = build_exact_provider_composition(
            configs=(config,),
            model_releases=(frozen.model_release,),
            credential_resolver=self._credential_resolver,
            artifact_sink=self._artifact_sink,
            transport_factory=self._transport_factory,
        )
        application = (
            ModelCallApplication(
                gateway=composition.router,
                release_registry=composition.router.release_registry,
                uow_factory=self._persistence.uow_factory,
            )
            if self._clock is None
            else ModelCallApplication(
                gateway=composition.router,
                release_registry=composition.router.release_registry,
                uow_factory=self._persistence.uow_factory,
                clock=self._clock,
            )
        )
        return LoadedModelCallRuntime(job, frozen.policy, composition, application)


def _validate_frozen_runtime(job: ModelCallJobAdmission, frozen: FrozenRuntimeOption) -> None:
    mismatches = (
        frozen.manifest_id != job.runtime_manifest_id,
        frozen.manifest_hash != job.runtime_manifest_hash,
        frozen.option_id != job.runtime_option_id,
        frozen.option_hash != job.runtime_option_hash,
        frozen.adapter_release.provider != job.route.provider,
        frozen.adapter_release.adapter_release_id != job.route.adapter_release_id,
        frozen.adapter_release.release_hash != job.route.adapter_release_hash,
        frozen.model_release.model_release_id != job.route.model_release_id,
        frozen.model_release.release_hash != job.route.model_release_hash,
        frozen.secret_reference_id != job.provider_secret_handle.reference_id,
        job.purpose not in frozen.allowed_purposes,
        frozen.policy.policy_version_id != job.policy_version_id,
        frozen.policy.policy_version_hash != job.policy_version_hash,
    )
    if any(mismatches):
        raise ModelRouteError("stored Job differs from its frozen runtime option")


def _validate_resume_request(
    request: NewModelCallJobAdmissionRequest,
    job: ModelCallJobAdmission,
    *,
    require_current_lease: bool = True,
) -> None:
    prompt = request.prompt
    mismatches = (
        job.project_id != request.project_id,
        job.job_id != request.job_id,
        job.job_kind != request.job_kind,
        job.job_version != MODEL_CALL_JOB_ADMISSION_VERSION,
        require_current_lease and job.status is not JobStatus.RUNNING,
        require_current_lease and job.lease_token != request.lease_token,
        require_current_lease and job.fencing_generation != request.fencing_generation,
        job.runtime_option_id != request.runtime_selection_id,
        job.purpose != request.required_purpose,
        job.usage_audience is not request.usage_audience,
        job.prompt_binding_id != prompt.binding_id,
        job.prompt_release_id != prompt.release_id,
        job.prompt_release_hash != prompt.release_hash,
        job.prompt_state_id != prompt.state_id,
        job.prompt_state_version != prompt.state_version,
        job.prompt_test_set_hash != prompt.test_set_hash,
        job.prompt_bundle_hash != request.prompt_bundle_hash,
        job.output_schema_hash != request.output_schema_hash,
        job.application_output_schema_hash
        != request.application_output_schema_hash,
        job.maximum_paid_calls != request.maximum_paid_calls,
        job.maximum_concurrent_calls != request.maximum_concurrent_calls,
    )
    if any(mismatches):
        raise ModelRouteError(
            "claimed Durable Job differs from its existing Model Gateway admission"
        )


def _policy_id(policy: ModelPolicy) -> UUID:
    if policy.policy_version_id is None:
        raise ModelRouteError("runtime policy version ID is unavailable")
    return policy.policy_version_id


def _policy_hash(policy: ModelPolicy) -> str:
    if policy.policy_version_hash is None:
        raise ModelRouteError("runtime policy version hash is unavailable")
    return policy.policy_version_hash


__all__ = [
    "AdmittedModelCallJob",
    "LoadedModelCallRuntime",
    "MODEL_CALL_JOB_ADMISSION_VERSION",
    "ModelCallAdmissionPersistence",
    "ModelCallJobAdmitter",
    "ModelCallRuntimeFactory",
    "ModelCallRuntimeLoader",
    "NewModelCallJobAdmissionRequest",
]
