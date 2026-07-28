from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

from geo_core.jobs.lifecycle import JobStatus
from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.application_events import success_event
from geo_core.model_gateway.application_support import (
    ModelCallExecution,
    attempt_draft,
    request_identity,
)
from geo_core.model_gateway.artifact_recovery import (
    ProviderArtifactRecoveryRequest,
    RecoveredProviderArtifact,
)
from geo_core.model_gateway.contracts import (
    ModelAudience,
    ModelCaptureMethod,
    ModelGatewayResult,
    ModelPolicy,
)
from geo_core.model_gateway.ports import (
    ModelCallAttempt,
    ModelCallJobAdmission,
)
from geo_core.model_gateway.releases import ModelRoute
from geo_core.model_gateway.runtime_execution import (
    AdmittedModelCallJob,
    LoadedModelCallRuntime,
    NewModelCallJobAdmissionRequest,
)
from geo_core.prompts.bootstrap_catalog import (
    default_prompt_bootstrap_spec,
    prompt_bootstrap_catalog_hash,
)
from geo_core.prompts.bootstrap_contracts import thaw_mapping
from geo_core.prompts.program import ProgramKind, render_program_release
from geo_core.prompts.program_contracts import _canonical_hash
from geo_core.prompts.test_execution_contracts import (
    PROMPT_TEST_JOB_KIND,
    PromptTestModelSelection,
    PromptTestRunTask,
)
from geo_core.prompts.test_model_executor import (
    ModelGatewayPromptTestCaseExecutor,
    PROMPT_TEST_MAXIMUM_CONCURRENT_CALLS,
    PROMPT_TEST_MAXIMUM_PAID_CALLS,
)
from geo_core.secrets.models import SecretVersionHandle


NOW = datetime(2026, 7, 23, 13, 0, tzinfo=UTC)


def test_five_cases_share_one_retry_capable_job_budget() -> None:
    task, lease = _task_and_lease()
    outputs = [thaw_mapping(item.expected_output) for item in task.test_spec.fixtures]
    application = _Application(outputs)
    runtime = _Runtime(task, lease, application)
    recovery = _Recovery()
    executor = ModelGatewayPromptTestCaseExecutor(
        runtime=runtime,
        result_recovery=recovery,
        clock=lambda: NOW,
    )

    results = []
    for fixture in task.test_spec.fixtures:
        prompt = render_program_release(
            release=task.test_spec.compile_draft(
                project_id=task.project_id,
                owner_id=task.requested_by,
            ).release,
            variables={
                "request_json": json.dumps(
                    thaw_mapping(fixture.input_value),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            },
        )
        results.append(
            executor.execute(
                lease=lease,
                task=task,
                prompt=prompt,
                fixture_id=fixture.fixture_id,
                fixture_hash=fixture.fixture_hash,
                output_schema=task.test_spec.schemas.output_schema,
                application_output_schema=(
                    task.test_spec.schemas.application_output_schema
                ),
            )
        )

    assert len(results) == 5
    assert PROMPT_TEST_MAXIMUM_PAID_CALLS == len(task.test_spec.fixtures) * 3
    assert len(application.commands) == 5
    assert len({item.prompt_test_case_id for item in application.commands}) == 5
    assert {item.job_id for item in application.commands} == {task.job_id}
    assert all(item.runtime_option_id == task.model.runtime_selection_id for item in application.commands)
    assert all(item.runtime_option_hash == task.model.runtime_selection_hash for item in application.commands)
    assert all(item.prompt_test_set_hash == task.test_set_hash for item in application.commands)
    assert all(
        item.request.output_schema == task.test_spec.schemas.output_schema
        and item.request.application_output_schema
        == task.test_spec.schemas.application_output_schema
        for item in application.commands
    )
    assert all(item.maximum_paid_calls == PROMPT_TEST_MAXIMUM_PAID_CALLS for item in runtime.requests)
    assert all(
        item.maximum_concurrent_calls == PROMPT_TEST_MAXIMUM_CONCURRENT_CALLS
        for item in runtime.requests
    )
    assert all(
        item.output_schema_hash == _canonical_hash(task.test_spec.schemas.output_schema)
        and item.application_output_schema_hash
        == _canonical_hash(task.test_spec.schemas.application_output_schema)
        and item.prompt.application_output_schema_hash
        == _canonical_hash(task.test_spec.schemas.application_output_schema)
        for item in runtime.requests
    )
    assert recovery.requests == []


def test_replayed_success_recovers_exact_derived_output_without_a_new_result() -> None:
    task, lease = _task_and_lease()
    fixture = task.test_spec.fixtures[0]
    expected = thaw_mapping(fixture.expected_output)
    application = _Application([expected], replay=True)
    runtime = _Runtime(task, lease, application)
    recovery = _Recovery(expected)
    executor = ModelGatewayPromptTestCaseExecutor(
        runtime=runtime,
        result_recovery=recovery,
        clock=lambda: NOW,
    )
    draft = task.test_spec.compile_draft(
        project_id=task.project_id,
        owner_id=task.requested_by,
    )
    prompt = render_program_release(
        release=draft.release,
        variables={"request_json": json.dumps(thaw_mapping(fixture.input_value))},
    )

    result = executor.execute(
        lease=lease,
        task=task,
        prompt=prompt,
        fixture_id=fixture.fixture_id,
        fixture_hash=fixture.fixture_hash,
        output_schema=task.test_spec.schemas.output_schema,
        application_output_schema=task.test_spec.schemas.application_output_schema,
    )

    assert dict(result.output) == expected
    assert len(application.commands) == 1
    assert len(recovery.requests) == 1
    assert recovery.requests[0].model_call_attempt_id == result.model_call_id
    assert recovery.requests[0].expected_output_hash == _canonical_hash(expected)
    assert recovery.requests[0].lease_token == lease.lease_token
    assert (
        recovery.requests[0].application_output_schema
        == task.test_spec.schemas.application_output_schema
    )


class _Runtime:
    def __init__(
        self,
        task: PromptTestRunTask,
        lease: WorkerLease,
        application: "_Application",
    ) -> None:
        self.requests: list[NewModelCallJobAdmissionRequest] = []
        self.job = _job(task, lease)
        self.application = application
        self.application.job = self.job
        self.application.policy = task.model.policy

    def load_or_admit_claimed_job(
        self, request: NewModelCallJobAdmissionRequest
    ) -> AdmittedModelCallJob:
        self.requests.append(request)
        return AdmittedModelCallJob(self.job, None)

    def load(self, *, project_id: UUID, job_id: UUID) -> LoadedModelCallRuntime:
        assert project_id == self.job.project_id and job_id == self.job.job_id
        return LoadedModelCallRuntime(
            self.job,
            self.application.policy,
            cast(Any, None),
            cast(Any, self.application),
        )


class _Application:
    def __init__(self, outputs: list[dict[str, object]], *, replay: bool = False) -> None:
        self.outputs = outputs
        self.replay = replay
        self.commands: list[Any] = []
        self.job: ModelCallJobAdmission
        self.policy: ModelPolicy

    def execute(self, command: Any, *, policy: ModelPolicy) -> ModelCallExecution:
        self.commands.append(command)
        output = self.outputs[len(self.commands) - 1]
        identity = request_identity(command, policy=policy)
        attempt_id = uuid5(command.prompt_test_case_id, "attempt:1")
        attempt = ModelCallAttempt(
            attempt_draft(
                command,
                identity=identity,
                attempt_id=attempt_id,
                job=self.job,
            ),
            attempt_number=len(self.commands),
            reserved_at=NOW,
        )
        result = ModelGatewayResult(
            output=output,
            call_log_id=uuid5(attempt_id, "call-log"),
            provider_request_id="fixture-request",
            configured_model=command.request.configured_model,
            provider_reported_model=None,
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=Decimal("0.001"),
            finish_reason="completed",
            response_hash=_canonical_hash({"attempt_id": str(attempt_id)}),
            provider=command.route.provider,
            adapter_release_id=command.route.adapter_release_id,
            adapter_release_hash=command.route.adapter_release_hash,
            model_release_id=command.route.model_release_id,
            model_release_hash=command.route.model_release_hash,
            raw_artifact_policy_hash=self.job.raw_artifact_policy_hash,
            raw_artifact_storage_decision="allowed",
            raw_artifact_cache_decision="allowed",
            raw_artifact_display_decision="allowed",
            raw_artifact_redistribution_decision="prohibited",
            raw_artifact_retention_days=30,
            usage_purpose="prompt_release_test",
            usage_audience=ModelAudience.INTERNAL_WORKER,
            capture_method=command.request.capture_method,
            search_mode=command.request.search_mode,
        )
        event = success_event(
            event_id=uuid5(attempt_id, "terminal"),
            occurred_at=NOW,
            attempt=attempt,
            result=result,
        )
        return ModelCallExecution(
            attempt=attempt,
            terminal_event=event,
            result=None if self.replay else result,
            replayed=self.replay,
        )


class _Recovery:
    def __init__(self, output: dict[str, object] | None = None) -> None:
        self.output = output
        self.requests: list[ProviderArtifactRecoveryRequest] = []

    def recover_derived(
        self, request: ProviderArtifactRecoveryRequest
    ) -> RecoveredProviderArtifact:
        self.requests.append(request)
        assert self.output is not None
        return RecoveredProviderArtifact(
            model_call_attempt_id=request.model_call_attempt_id,
            artifact_id=uuid5(request.model_call_attempt_id, "artifact"),
            manifest_hash="a" * 64,
            content_hash="b" * 64,
            output_hash=request.expected_output_hash,
            output=self.output,
            recovery_receipt_id=uuid5(request.model_call_attempt_id, "receipt"),
            recovery_receipt_hash="c" * 64,
            recovered_at=NOW,
        )


def _task_and_lease() -> tuple[PromptTestRunTask, WorkerLease]:
    project_id, owner_id, job_id = uuid4(), uuid4(), uuid4()
    spec = default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION)
    draft = spec.compile_draft(project_id=project_id, owner_id=owner_id)
    policy_id = uuid4()
    policy = ModelPolicy(
        allowed_providers=frozenset({"openai"}),
        allowed_adapter_release_ids=frozenset({"openai-adapter-v1"}),
        policy_version_id=policy_id,
        maximum_paid_calls=PROMPT_TEST_MAXIMUM_PAID_CALLS,
        maximum_concurrent_calls=1,
    )
    assert policy.policy_version_hash is not None
    selection = PromptTestModelSelection(
        runtime_selection_id=uuid4(),
        runtime_selection_hash="1" * 64,
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash="2" * 64,
        route=ModelRoute(
            provider="openai",
            adapter_release_id="openai-adapter-v1",
            adapter_release_hash="3" * 64,
            model_release_id="openai-model-v1",
            model_release_hash="4" * 64,
        ),
        configured_model="gpt-fixture",
        capture_method=ModelCaptureMethod.PROVIDER_API,
        policy_version_id=policy_id,
        policy_version_hash=policy.policy_version_hash,
        policy=policy,
        provider_secret_handle=SecretVersionHandle(
            reference_id=uuid4(),
            project_id=project_id,
            purpose="model_provider.openai",
            version=1,
        ),
    )
    task = PromptTestRunTask(
        project_id=project_id,
        job_id=job_id,
        program_id=draft.program.id,
        release_id=draft.release.id,
        release_version=draft.release.version,
        release_hash=draft.release.release_hash,
        expected_state_id=uuid4(),
        expected_state_version=1,
        requested_by=owner_id,
        requested_at=NOW,
        test_spec=spec,
        catalog_hash=prompt_bootstrap_catalog_hash(),
        model=selection,
    )
    lease = WorkerLease(
        job_id,
        project_id,
        PROMPT_TEST_JOB_KIND,
        "prompt-worker",
        uuid4(),
        1,
        1,
        3,
    )
    return task, lease


def _job(task: PromptTestRunTask, lease: WorkerLease) -> ModelCallJobAdmission:
    return ModelCallJobAdmission(
        project_id=task.project_id,
        job_id=task.job_id,
        job_kind=PROMPT_TEST_JOB_KIND,
        job_version=1,
        admission_mode="prompt_release_test",
        status=JobStatus.RUNNING,
        lease_token=lease.lease_token,
        fencing_generation=lease.fencing_generation,
        purpose="prompt_release_test",
        usage_audience=ModelAudience.INTERNAL_WORKER,
        route=task.model.route,
        provider_secret_handle=task.model.provider_secret_handle,
        runtime_manifest_id=task.model.runtime_manifest_id,
        runtime_manifest_hash=task.model.runtime_manifest_hash,
        runtime_option_id=task.model.runtime_selection_id,
        runtime_option_hash=task.model.runtime_selection_hash,
        prompt_binding_id=None,
        prompt_release_id=task.release_id,
        prompt_release_hash=task.release_hash,
        prompt_state_id=task.expected_state_id,
        prompt_state_version=task.expected_state_version,
        prompt_test_set_hash=task.test_set_hash,
        prompt_bundle_hash=task.input_hash,
        output_schema_hash=_canonical_hash(task.test_spec.schemas.output_schema),
        application_output_schema_hash=_canonical_hash(
            task.test_spec.schemas.application_output_schema
        ),
        policy_version_id=task.model.policy_version_id,
        policy_version_hash=task.model.policy_version_hash,
        maximum_paid_calls=PROMPT_TEST_MAXIMUM_PAID_CALLS,
        maximum_concurrent_calls=1,
        raw_artifact_policy_hash="6" * 64,
        raw_artifact_storage_decision="allowed",
        raw_artifact_cache_decision="allowed",
        raw_artifact_display_decision="allowed",
        raw_artifact_redistribution_decision="prohibited",
        raw_artifact_retention_days=30,
    )
