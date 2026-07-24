from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
from typing import Callable
from uuid import UUID, uuid4

from geo_core.jobs.lifecycle import JobStatus
from geo_core.model_gateway import (
    ModelCallBudget,
    ModelAudience,
    ModelCaptureMethod,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
    ModelRelease,
    ModelReleaseRegistry,
    ModelRoute,
    ReleaseState,
)
from geo_core.model_gateway.application import ExecuteModelCall, ModelCallApplication
from geo_core.model_gateway.memory import InMemoryModelCallStore
from geo_core.model_gateway.ports import (
    ModelCallAttemptKind,
    ModelCallJobAdmission,
    ModelCallLineage,
    canonical_json_hash,
)
from geo_core.model_gateway.prompt_admission import (
    ModelCallAdmissionMode,
    PromptAdmissionState,
    PromptReleaseAdmission,
)
from geo_core.model_gateway.schema_validation import project_provider_output_schema
from geo_core.secrets import SecretVersionHandle

from .provider_adapter_test_support import OUTPUT_SCHEMA, SECRET_REFERENCE_ID, runtime


MODEL = "fixture-openai-model"
NOW = datetime(2026, 7, 23, 9, 30, tzinfo=UTC)
PROJECT_ID = UUID("10000000-0000-0000-0000-000000000001")
JOB_ID = UUID("20000000-0000-0000-0000-000000000001")
LEASE_TOKEN = UUID("30000000-0000-0000-0000-000000000001")
PROMPT_BINDING_ID = UUID("40000000-0000-0000-0000-000000000001")
PROMPT_RELEASE_ID = UUID("50000000-0000-0000-0000-000000000001")
PROMPT_STATE_ID = UUID("60000000-0000-0000-0000-000000000001")
PROMPT_RELEASE_HASH = "a" * 64
PROMPT_BUNDLE_HASH = "b" * 64
PROMPT_TEST_SET_HASH = "c" * 64
PROMPT_TEST_CASE_ID = UUID("65000000-0000-0000-0000-000000000001")
PROMPT_TEST_CASE_HASH = "d" * 64
POLICY_VERSION_ID = UUID("70000000-0000-0000-0000-000000000001")
RUNTIME_MANIFEST_ID = UUID("71000000-0000-0000-0000-000000000001")
RUNTIME_OPTION_ID = UUID("72000000-0000-0000-0000-000000000001")
RUNTIME_MANIFEST_HASH = "e" * 64
RUNTIME_OPTION_HASH = "f" * 64
SECRET_MARKER = "fixture-secret-must-never-persist"


class RecordingExactGateway:
    def __init__(
        self,
        actions: list[ModelGatewayResult | Exception],
        *,
        before_call: Callable[[], None] | None = None,
        consume_paid_call: bool = True,
    ) -> None:
        self.actions = actions
        self.before_call = before_call
        self.consume_paid_call = consume_paid_call
        self.calls = 0
        self.routes: list[ModelRoute] = []

    def generate(
        self,
        route: ModelRoute,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult:
        del request, policy
        self.calls += 1
        self.routes.append(route)
        if self.before_call is not None:
            self.before_call()
        if self.consume_paid_call:
            budget.consume()
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


@dataclass(frozen=True)
class ApplicationFixture:
    store: InMemoryModelCallStore
    gateway: RecordingExactGateway
    application: ModelCallApplication
    route: ModelRoute
    command: ExecuteModelCall
    result: ModelGatewayResult
    policy: ModelPolicy


def application_fixture(
    *,
    actions: list[ModelGatewayResult | Exception] | None = None,
    maximum_paid_calls: int = 3,
    before_call: Callable[[], None] | None = None,
    consume_paid_call: bool = True,
    prompt_frozen: bool = True,
    prompt_test: bool = False,
    maximum_concurrent_calls: int = 1,
    application_output_schema: Mapping[str, object] = OUTPUT_SCHEMA,
) -> ApplicationFixture:
    admission_mode = (
        ModelCallAdmissionMode.PROMPT_RELEASE_TEST
        if prompt_test
        else ModelCallAdmissionMode.RUNTIME_FROZEN
    )
    purpose = "prompt_release_test" if prompt_test else "cross_engine_sampling"
    adapter = runtime("openai", model=MODEL).adapter_release
    model_release_id = "openai-model-fixture-v1"
    model_hash = hashlib.sha256(model_release_id.encode()).hexdigest()
    model = ModelRelease(
        provider="openai",
        adapter_release_id=adapter.adapter_release_id,
        model_release_id=model_release_id,
        release_hash=model_hash,
        configured_model=MODEL,
        state=ReleaseState.APPROVED,
    )
    route = ModelRoute(
        provider="openai",
        adapter_release_id=adapter.adapter_release_id,
        adapter_release_hash=adapter.release_hash,
        model_release_id=model.model_release_id,
        model_release_hash=model.release_hash,
    )
    result = ModelGatewayResult(
        output={"answer": "Recommended by the fixture.", "recommended": True},
        call_log_id=uuid4(),
        provider_request_id="provider-request-fixture",
        configured_model=MODEL,
        provider_reported_model="fixture-openai-model-reported",
        prompt_tokens=37,
        completion_tokens=11,
        cost_usd=Decimal("0.0042"),
        finish_reason="completed",
        response_hash="e" * 64,
        provider="openai",
        adapter_release_id=adapter.adapter_release_id,
        adapter_release_hash=adapter.release_hash,
        model_release_id=model.model_release_id,
        model_release_hash=model.release_hash,
        citations=({"url": "https://example.test/source", "ordinal": 1},),
        tool_events=({"type": "web_search_call", "query": "product australia"},),
        capture_method=ModelCaptureMethod.PROVIDER_API,
        search_mode="web",
        usage_details={"input_tokens": 37, "output_tokens": 11, "total_tokens": 48},
        raw_artifact_policy_hash=adapter.data_policy_hash,
        raw_artifact_storage_decision=adapter.data_policy.storage.value,
        raw_artifact_cache_decision=adapter.data_policy.cache.value,
        raw_artifact_display_decision=adapter.data_policy.display.value,
        raw_artifact_redistribution_decision=adapter.data_policy.redistribution.value,
        raw_artifact_retention_days=adapter.data_policy.retention_days,
        usage_purpose=purpose,
        usage_audience=ModelAudience.INTERNAL_WORKER,
    )
    gateway = RecordingExactGateway(
        list(actions) if actions is not None else [result],
        before_call=before_call,
        consume_paid_call=consume_paid_call,
    )
    secret_handle = SecretVersionHandle(
        reference_id=SECRET_REFERENCE_ID,
        project_id=PROJECT_ID,
        purpose="model_provider.openai",
        version=1,
    )
    provider_output_schema = project_provider_output_schema(
        application_output_schema
    )
    request = ModelGatewayRequest(
        messages=(
            {"role": "system", "content": f"Never persist {SECRET_MARKER}."},
            {"role": "user", "content": "Is this recommended in Australia?"},
        ),
        configured_model=MODEL,
        prompt_bundle_hash=PROMPT_BUNDLE_HASH,
        project_id=PROJECT_ID,
        purpose=purpose,
        output_schema=provider_output_schema,
        application_output_schema=application_output_schema,
        search_mode="web",
        capture_method=ModelCaptureMethod.PROVIDER_API,
        provider_secret_handle=secret_handle,
    )
    policy = ModelPolicy(
        allowed_providers=frozenset({"openai"}),
        allowed_adapter_release_ids=frozenset({adapter.adapter_release_id}),
        policy_version_id=POLICY_VERSION_ID,
        maximum_paid_calls=maximum_paid_calls,
        maximum_concurrent_calls=maximum_concurrent_calls,
    )
    assert policy.policy_version_hash is not None
    command = ExecuteModelCall(
        project_id=PROJECT_ID,
        job_id=JOB_ID,
        expected_job_version=4,
        lease_token=LEASE_TOKEN,
        fencing_generation=2,
        route=route,
        runtime_manifest_id=RUNTIME_MANIFEST_ID,
        runtime_manifest_hash=RUNTIME_MANIFEST_HASH,
        runtime_option_id=RUNTIME_OPTION_ID,
        runtime_option_hash=RUNTIME_OPTION_HASH,
        prompt_binding_id=None if prompt_test else PROMPT_BINDING_ID,
        prompt_release_id=PROMPT_RELEASE_ID,
        prompt_release_hash=PROMPT_RELEASE_HASH,
        request=request,
        attempt_kind=ModelCallAttemptKind.INITIAL,
        attempt_idempotency_key="attempt-initial-fixture",
        admission_mode=admission_mode,
        prompt_state_id=PROMPT_STATE_ID if prompt_test else None,
        prompt_state_version=1 if prompt_test else None,
        prompt_test_set_hash=PROMPT_TEST_SET_HASH if prompt_test else None,
        prompt_test_case_id=PROMPT_TEST_CASE_ID if prompt_test else None,
        prompt_test_case_hash=PROMPT_TEST_CASE_HASH if prompt_test else None,
    )
    schema_hash = canonical_json_hash(provider_output_schema)
    application_schema_hash = canonical_json_hash(application_output_schema)
    store = InMemoryModelCallStore()
    store.seed_prompt_release(
        PromptReleaseAdmission(
            project_id=PROJECT_ID,
            admission_mode=admission_mode,
            binding_id=None if prompt_test else PROMPT_BINDING_ID,
            state_id=PROMPT_STATE_ID,
            state_version=1,
            release_id=PROMPT_RELEASE_ID,
            release_hash=PROMPT_RELEASE_HASH,
            purpose=request.purpose,
            output_schema_hash=schema_hash,
            application_output_schema_hash=application_schema_hash,
            test_set_hash=PROMPT_TEST_SET_HASH if prompt_test else None,
            state_status=(
                PromptAdmissionState.DRAFT
                if prompt_test
                else PromptAdmissionState.FROZEN
            ),
            current=prompt_frozen,
        )
    )
    store.seed_job(
        ModelCallJobAdmission(
            project_id=PROJECT_ID,
            job_id=JOB_ID,
            job_kind="prompt.test.execute" if prompt_test else "sampling.task.run",
            job_version=4,
            admission_mode=admission_mode,
            status=JobStatus.RUNNING,
            lease_token=LEASE_TOKEN,
            fencing_generation=2,
            purpose=request.purpose,
            usage_audience=ModelAudience.INTERNAL_WORKER,
            route=route,
            provider_secret_handle=secret_handle,
            runtime_manifest_id=RUNTIME_MANIFEST_ID,
            runtime_manifest_hash=RUNTIME_MANIFEST_HASH,
            runtime_option_id=RUNTIME_OPTION_ID,
            runtime_option_hash=RUNTIME_OPTION_HASH,
            prompt_binding_id=None if prompt_test else PROMPT_BINDING_ID,
            prompt_release_id=PROMPT_RELEASE_ID,
            prompt_release_hash=PROMPT_RELEASE_HASH,
            prompt_state_id=PROMPT_STATE_ID,
            prompt_state_version=1,
            prompt_test_set_hash=PROMPT_TEST_SET_HASH if prompt_test else None,
            prompt_bundle_hash=PROMPT_BUNDLE_HASH,
            output_schema_hash=schema_hash,
            application_output_schema_hash=application_schema_hash,
            policy_version_id=POLICY_VERSION_ID,
            policy_version_hash=policy.policy_version_hash,
            maximum_paid_calls=maximum_paid_calls,
            maximum_concurrent_calls=maximum_concurrent_calls,
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
    application = ModelCallApplication(
        gateway=gateway,
        release_registry=ModelReleaseRegistry(
            adapter_releases=(adapter,),
            model_releases=(model,),
        ),
        uow_factory=store.unit_of_work_factory(),
        clock=lambda: NOW,
    )
    return ApplicationFixture(store, gateway, application, route, command, result, policy)


def empty_lineage_for(command: ExecuteModelCall) -> ModelCallLineage:
    empty_hash = canonical_json_hash(())
    return ModelCallLineage(
        search_mode=command.request.search_mode,
        capture_method=command.request.capture_method,
        citation_count=0,
        citation_lineage_hash=empty_hash,
        search_event_count=0,
        search_lineage_hash=empty_hash,
        usage_details_hash=canonical_json_hash({}),
        raw_artifact_reference_hash=None,
        raw_artifact_policy_hash=runtime("openai", model=MODEL).adapter_release.data_policy_hash,
        raw_artifact_storage_decision="allowed",
        raw_artifact_cache_decision="allowed",
        raw_artifact_display_decision="allowed",
        raw_artifact_redistribution_decision="prohibited",
        raw_artifact_retention_days=30,
        usage_purpose=command.request.purpose,
        usage_audience=command.request.usage_audience,
        effective_location=None,
    )
