from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
import hashlib
from typing import Callable
from uuid import UUID, uuid4

from geo_core.jobs import JobStatus
from geo_core.model_gateway import (
    AdapterRelease,
    EffectiveModelLocation,
    ModelCaptureMethod,
    ModelAudience,
    ModelGatewayResult,
    ModelLocationControl,
    ModelPolicy,
    ModelRelease,
    ModelReleaseRegistry,
    ModelRoute,
    ReleaseState,
    RequestedModelLocation,
)
from geo_core.model_gateway.application import ModelCallApplication
from geo_core.model_gateway.memory import InMemoryModelCallStore
from geo_core.model_gateway.ports import (
    ExactModelGatewayPort,
    ModelCallJobAdmission,
    canonical_json_hash,
)
from geo_core.model_gateway.prompt_admission import (
    ModelCallAdmissionMode,
    PromptAdmissionState,
    PromptReleaseAdmission,
)
from geo_core.model_gateway.schema_validation import project_provider_output_schema
from geo_core.secrets import SecretVersionHandle
from geo_core.sampling import (
    InMemorySamplingStore,
    SamplingAdmissionCommand,
    SamplingApplication,
    SamplingSourceStratum,
    admit_sampling_suite,
)
from geo_core.sampling.contracts import CaptureMethod, SamplingRun, SamplingSuite, SamplingTask
from geo_core.sampling.execution import SamplingAttempt
from geo_core.sampling.provider_execution import (
    ExecuteProviderSampling,
    ProviderSamplingExecutionService,
    ProviderSamplingPrompt,
)

from tests.unit.model_gateway.model_call_application_test_support import RecordingExactGateway
from tests.unit.model_gateway.provider_adapter_test_support import (
    OUTPUT_SCHEMA,
    SECRET_REFERENCE_ID,
    runtime,
)
from tests.unit.sampling.factories import NOW, make_policy, make_suite


PROMPT_BINDING_ID = UUID("81000000-0000-0000-0000-000000000001")
PROMPT_RELEASE_ID = UUID("82000000-0000-0000-0000-000000000001")
PROMPT_STATE_ID = UUID("83000000-0000-0000-0000-000000000001")
PROMPT_RELEASE_HASH = "c" * 64
PROMPT_BUNDLE_HASH = "d" * 64
QUESTION_TEXT = "question-1"
LOCATION_EVIDENCE_HASH = hashlib.sha256(
    b"provider-location-not-controlled"
).hexdigest()


@dataclass(frozen=True)
class ProviderIdentity:
    provider: str = "openai"
    model: str = "gpt-fixture"
    reported_model: str = "gpt-fixture-reported"
    capture_method: CaptureMethod = CaptureMethod.PROVIDER_API
    search_mode: str = "web"
    surface: str = "web_search"

    @property
    def model_capture_method(self) -> ModelCaptureMethod:
        return ModelCaptureMethod(self.capture_method.value)


@dataclass(frozen=True)
class ProviderExecutionFixture:
    identity: ProviderIdentity
    adapter_release: AdapterRelease
    model_release: ModelRelease
    route: ModelRoute
    sampling_store: InMemorySamplingStore
    model_store: InMemoryModelCallStore
    sampling_application: SamplingApplication
    model_application: ModelCallApplication
    service: ProviderSamplingExecutionService
    suite: SamplingSuite
    run: SamplingRun
    task: SamplingTask
    attempt: SamplingAttempt
    prompt: ProviderSamplingPrompt
    command: ExecuteProviderSampling
    gateway: ExactModelGatewayPort
    policy: ModelPolicy


def model_result(
    identity: ProviderIdentity,
    route: ModelRoute,
    *,
    answer: str = "The fixture recommends it.",
) -> ModelGatewayResult:
    return ModelGatewayResult(
        output={"answer": answer, "recommended": True},
        call_log_id=uuid4(),
        provider_request_id=f"{identity.provider}-response-fixture",
        configured_model=identity.model,
        provider_reported_model=identity.reported_model,
        prompt_tokens=31,
        completion_tokens=9,
        cost_usd=None,
        finish_reason="completed",
        response_hash="e" * 64,
        provider=identity.provider,
        adapter_release_id=route.adapter_release_id,
        adapter_release_hash=route.adapter_release_hash,
        model_release_id=route.model_release_id,
        model_release_hash=route.model_release_hash,
        citations=({"url": "https://example.test/au", "ordinal": 1},),
        tool_events=({"type": "search", "query": "fixture australia"},),
        capture_method=identity.model_capture_method,
        search_mode=identity.search_mode,
        usage_details={"input_tokens": 31, "output_tokens": 9},
        raw_artifact_reference="s3://sampling-fixture/raw/provider-response.manifest.json",
        raw_artifact_manifest_hash="1" * 64,
        raw_artifact_content_hash="e" * 64,
        raw_artifact_byte_size=128,
        derived_artifact_reference=(
            "s3://sampling-fixture/derived/provider-response.manifest.json"
        ),
        derived_artifact_manifest_hash="2" * 64,
        derived_artifact_content_hash=canonical_json_hash(
            {"answer": answer, "recommended": True}
        ),
        derived_artifact_byte_size=64,
        requested_location=RequestedModelLocation(
            country_code="AU",
            region_code=None,
            locale="en-AU",
            language="en",
        ),
        effective_location=EffectiveModelLocation(
            control=ModelLocationControl.NOT_CONTROLLED,
            country_code=None,
            region_code=None,
            locale=None,
            language=None,
            evidence_hash=LOCATION_EVIDENCE_HASH,
        ),
    )


def execution_fixture(
    *,
    identity: ProviderIdentity = ProviderIdentity(),
    adapter_release: AdapterRelease | None = None,
    model_release: ModelRelease | None = None,
    gateway_factory: Callable[[ModelRoute], ExactModelGatewayPort] | None = None,
) -> ProviderExecutionFixture:
    adapter = adapter_release or runtime(
        identity.provider,
        model=identity.model,
        capture_method=identity.model_capture_method,
        search_modes=frozenset({identity.search_mode}),
        supports_search=identity.search_mode != "disabled",
        purpose="geo_measurement",
    ).adapter_release
    model = model_release or ModelRelease(
        provider=identity.provider,
        adapter_release_id=adapter.adapter_release_id,
        model_release_id=f"{identity.provider}-model-fixture-v1",
        release_hash=hashlib.sha256(
            f"{identity.provider}-model-fixture-v1".encode()
        ).hexdigest(),
        configured_model=identity.model,
        state=ReleaseState.APPROVED,
    )
    route = ModelRoute(
        provider=identity.provider,
        adapter_release_id=adapter.adapter_release_id,
        adapter_release_hash=adapter.release_hash,
        model_release_id=model.model_release_id,
        model_release_hash=model.release_hash,
    )
    gateway = (
        gateway_factory(route)
        if gateway_factory is not None
        else RecordingExactGateway([model_result(identity, route)])
    )
    source = SamplingSourceStratum(
        platform=identity.provider,
        surface=identity.surface,
        configured_model=identity.model,
        reported_model=identity.reported_model,
        capture_method=identity.capture_method,
        adapter_release=adapter.adapter_release_id,
        locale="en-AU",
        region="not_controlled",
        language="en",
        search_mode=identity.search_mode,
        account_cohort="not_applicable",
        egress_policy_category="not_applicable",
        location_control="not_controlled",
        location_evidence_hash=LOCATION_EVIDENCE_HASH,
        requested_country="AU",
        requested_region=None,
        requested_locale="en-AU",
        requested_language="en",
        effective_country=None,
        effective_region=None,
        effective_locale=None,
        effective_language=None,
    )
    base_suite = make_suite(project_id=uuid4())
    suite = replace(base_suite, source_stratum=source)
    secret_handle = SecretVersionHandle(
        reference_id=SECRET_REFERENCE_ID,
        project_id=suite.project_id,
        purpose=f"model_provider.{identity.provider}",
        version=1,
    )
    policy = replace(
        make_policy(suite),
        platform=identity.provider,
        capture_method=identity.capture_method,
        adapter_release=adapter.adapter_release_id,
        location_control=source.location_control,
        location_evidence_hash=source.location_evidence_hash,
    )
    grant = admit_sampling_suite(
        suite,
        policy=policy,
        command=SamplingAdmissionCommand(
            idempotency_key=f"admit-provider:{suite.id}",
            purpose="geo_measurement",
            requested_at=NOW,
            requested_not_before=NOW,
        ),
    )
    sampling_store = InMemorySamplingStore()
    sampling_application = SamplingApplication(sampling_store.unit_of_work_factory())
    sampling_application.register_suite(suite)
    run, tasks = sampling_application.create_run(
        project_id=suite.project_id,
        suite_id=suite.id,
        grant=grant,
        run_id=uuid4(),
        created_at=NOW,
    )
    enqueued = sampling_application.enqueue_attempt(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=tasks[0].id,
        expected_task_version=tasks[0].version,
        attempt_id=uuid4(),
        requested_not_before=NOW,
    )
    execute_at = run.admitted_not_before + timedelta(seconds=1)
    claimed = sampling_application.claim_attempt(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=enqueued.task.id,
        attempt_id=enqueued.attempt.id,
        expected_task_version=enqueued.task.version,
        expected_attempt_version=enqueued.attempt.record_version,
        worker_id="provider-sampling-worker",
        now=execute_at,
        lease_for=timedelta(minutes=5),
    )
    token = claimed.attempt.job.lease_token
    assert token is not None
    prompt = ProviderSamplingPrompt(
        binding_id=PROMPT_BINDING_ID,
        release_id=PROMPT_RELEASE_ID,
        release_hash=PROMPT_RELEASE_HASH,
        bundle_hash=PROMPT_BUNDLE_HASH,
        system_message="Return the frozen sampling evidence schema.",
        output_schema=project_provider_output_schema(OUTPUT_SCHEMA),
        application_output_schema=OUTPUT_SCHEMA,
    )
    model_policy = ModelPolicy(
        allowed_providers=frozenset({identity.provider}),
        allowed_adapter_release_ids=frozenset({adapter.adapter_release_id}),
        policy_version_id=uuid4(),
        maximum_paid_calls=1,
        maximum_concurrent_calls=1,
    )
    assert model_policy.policy_version_id is not None
    assert model_policy.policy_version_hash is not None
    model_store = InMemoryModelCallStore()
    model_store.seed_prompt_release(
        PromptReleaseAdmission(
            project_id=suite.project_id,
            admission_mode=ModelCallAdmissionMode.RUNTIME_FROZEN,
            binding_id=prompt.binding_id,
            state_id=PROMPT_STATE_ID,
            state_version=1,
            release_id=prompt.release_id,
            release_hash=prompt.release_hash,
            purpose=run.purpose,
            output_schema_hash=prompt.output_schema_hash,
            application_output_schema_hash=(
                prompt.application_output_schema_hash
            ),
            test_set_hash=None,
            state_status=PromptAdmissionState.FROZEN,
        )
    )
    model_store.seed_job(
        ModelCallJobAdmission(
            project_id=suite.project_id,
            job_id=claimed.attempt.id,
                job_kind="sampling.provider_execute",
                job_version=claimed.attempt.record_version,
                runtime_manifest_id=suite.runtime_manifest_id,
                runtime_manifest_hash=suite.runtime_manifest_hash,
                runtime_option_id=suite.runtime_option_id,
                runtime_option_hash=suite.runtime_option_hash,
                admission_mode=ModelCallAdmissionMode.RUNTIME_FROZEN,
            status=JobStatus.RUNNING,
            lease_token=token,
            fencing_generation=claimed.attempt.job.fencing_generation,
            purpose=run.purpose,
            usage_audience=ModelAudience.INTERNAL_WORKER,
            route=route,
            provider_secret_handle=secret_handle,
            prompt_binding_id=prompt.binding_id,
            prompt_release_id=prompt.release_id,
            prompt_release_hash=prompt.release_hash,
            prompt_state_id=PROMPT_STATE_ID,
            prompt_state_version=1,
            prompt_test_set_hash=None,
            prompt_bundle_hash=prompt.bundle_hash,
            output_schema_hash=prompt.output_schema_hash,
            application_output_schema_hash=canonical_json_hash(OUTPUT_SCHEMA),
            policy_version_id=model_policy.policy_version_id,
            policy_version_hash=model_policy.policy_version_hash,
            maximum_paid_calls=1,
            maximum_concurrent_calls=1,
            raw_artifact_policy_hash=adapter.data_policy_hash,
            raw_artifact_storage_decision=adapter.data_policy.storage.value,
            raw_artifact_cache_decision=adapter.data_policy.cache.value,
            raw_artifact_display_decision=adapter.data_policy.display.value,
            raw_artifact_redistribution_decision=(
                adapter.data_policy.redistribution.value
            ),
            raw_artifact_retention_days=adapter.data_policy.retention_days,
        )
    )
    registry = ModelReleaseRegistry(
        adapter_releases=(adapter,),
        model_releases=(model,),
    )
    model_application = ModelCallApplication(
        gateway=gateway,
        release_registry=registry,
        uow_factory=model_store.unit_of_work_factory(),
        clock=lambda: execute_at + timedelta(seconds=1),
    )
    service = ProviderSamplingExecutionService(
        sampling_uow_factory=sampling_store.unit_of_work_factory(),
        model_calls=model_application,
        clock=lambda: execute_at + timedelta(seconds=2),
    )
    command = ExecuteProviderSampling(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=claimed.task.id,
        attempt_id=claimed.attempt.id,
        expected_task_version=claimed.task.version,
        expected_attempt_version=claimed.attempt.record_version,
        lease_token=token,
        fencing_generation=claimed.attempt.job.fencing_generation,
        route=route,
        provider_secret_handle=secret_handle,
        prompt=prompt,
        question_text=QUESTION_TEXT,
    )
    return ProviderExecutionFixture(
        identity,
        adapter,
        model,
        route,
        sampling_store,
        model_store,
        sampling_application,
        model_application,
        service,
        suite,
        run,
        claimed.task,
        claimed.attempt,
        prompt,
        command,
        gateway,
        model_policy,
    )


def persisted_state_text(fixture: ProviderExecutionFixture) -> str:
    attempts = fixture.model_store.attempts(
        project_id=fixture.suite.project_id,
        job_id=fixture.attempt.id,
    )
    event = (
        fixture.model_store.terminal_event(
            project_id=fixture.suite.project_id,
            attempt_id=attempts[0].spec.id,
        )
        if attempts
        else None
    )
    return repr(
        (
            fixture.sampling_store.attempt(
                project_id=fixture.suite.project_id,
                attempt_id=fixture.attempt.id,
            ),
            fixture.sampling_store.outbox_messages(project_id=fixture.suite.project_id),
            attempts,
            event,
        )
    )
