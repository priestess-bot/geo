"""Support for the exact native Style Profile parent/child integration path."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geo_core.jobs.lifecycle import JobStatus
from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.model_gateway import (
    ModelAudience,
    ModelCallBudget,
    ModelCaptureMethod,
    ModelGatewayRequest,
    ModelGatewayResult,
)
from geo_core.model_gateway.application import ModelCallApplication
from geo_core.model_gateway.application_support import ExecuteModelCall
from geo_core.model_gateway.contracts import ModelPolicy
from geo_core.model_gateway.ports import (
    ModelCallAttemptKind,
    ModelCallJobAdmission,
    canonical_json_hash,
)
from geo_core.model_gateway.postgres import build_model_gateway_persistence
from geo_core.model_gateway.prompt_admission import (
    ModelCallAdmissionMode,
    PromptAdmissionState,
    PromptReleaseAdmission,
)
from geo_core.model_gateway.provider_adapters.artifacts import MinioProviderArtifactSink
from geo_core.model_gateway.releases import ModelRoute
from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.child_model_calls import (
    SyntheticChildCallStatus,
    SyntheticChildModelCallTask,
    child_task_from_invocation,
)
from geo_core.synthetic_lab.child_task_artifacts import SyntheticChildTaskArtifactRef
from geo_core.synthetic_lab.execution_contracts import (
    FrozenEvidence,
    FrozenPromptRef,
    ResolvedSyntheticPrompt,
    StyleProfileBuildOutput,
    StyleProfileBuildTask,
    SyntheticModelInvocation,
)
from geo_core.synthetic_lab.ports import RuntimeInputSnapshot
from geo_core.synthetic_lab.postgres_child_model_calls import (
    PostgresSyntheticChildCallRepository,
)
from tests.integration.model_gateway_postgres_fixtures import RegisteredRuntimeFixture
from tests.integration.model_gateway_postgres_support import (
    attach_provider_artifacts,
    provider_artifact_sink,
)


@dataclass(frozen=True)
class StyleNativeDatabase:
    admin_url: str
    app_url: str
    worker_url: str
    ids: dict[str, UUID]


class _MemoryChildArtifacts:
    def __init__(self) -> None:
        self._tasks: dict[str, SyntheticChildModelCallTask] = {}

    def put(self, task: SyntheticChildModelCallTask) -> SyntheticChildTaskArtifactRef:
        uri = f"s3://synthetic-integration/child-tasks/{task.child_job_id}.json"
        self._tasks[uri] = task
        return SyntheticChildTaskArtifactRef(uri, canonical_hash(task.value()))

    def load(
        self,
        reference: SyntheticChildTaskArtifactRef,
        *,
        project_id: UUID,
        child_job_id: UUID,
        expected_input_hash: str,
    ) -> SyntheticChildModelCallTask:
        task = self._tasks[reference.uri]
        if (
            task.project_id != project_id
            or task.child_job_id != child_job_id
            or task.input_hash != expected_input_hash
            or reference.artifact_hash != canonical_hash(task.value())
        ):
            raise AssertionError("Synthetic child artifact lineage changed")
        return task


class _UnusedChildResults:
    def load(self, **_kwargs: object) -> object:
        raise AssertionError("queued child must not load a result")

    def load_dify(self, **_kwargs: object) -> object:
        raise AssertionError("native child must not load a Dify result")


class _StyleGateway:
    def __init__(
        self,
        *,
        output: dict[str, object],
        runtime: RegisteredRuntimeFixture,
        sink: MinioProviderArtifactSink,
    ) -> None:
        self._output = output
        self._runtime = runtime
        self._sink = sink

    def generate(
        self,
        route: ModelRoute,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult:
        del policy
        assert route == self._runtime.route
        budget.consume()
        result = ModelGatewayResult(
            output=self._output,
            call_log_id=uuid4(),
            provider_request_id="style-profile-integration-request",
            configured_model=self._runtime.selection.configured_model,
            provider_reported_model=self._runtime.selection.configured_model,
            prompt_tokens=181,
            completion_tokens=73,
            cost_usd=Decimal("0.0034"),
            finish_reason="completed",
            response_hash=hash_value("style-profile-provider-response"),
            provider=route.provider,
            adapter_release_id=route.adapter_release_id,
            adapter_release_hash=route.adapter_release_hash,
            model_release_id=route.model_release_id,
            model_release_hash=route.model_release_hash,
            raw_artifact_policy_hash=self._runtime.adapter.data_policy_hash,
            raw_artifact_storage_decision=self._runtime.adapter.data_policy.storage.value,
            raw_artifact_cache_decision=self._runtime.adapter.data_policy.cache.value,
            raw_artifact_display_decision=self._runtime.adapter.data_policy.display.value,
            raw_artifact_redistribution_decision=(
                self._runtime.adapter.data_policy.redistribution.value
            ),
            raw_artifact_retention_days=self._runtime.adapter.data_policy.retention_days,
            usage_purpose="synthetic_lab.style_profile",
            usage_audience=ModelAudience.INTERNAL_WORKER,
            capture_method=ModelCaptureMethod.PROVIDER_API,
            usage_details={"input_tokens": 181, "output_tokens": 73, "total_tokens": 254},
        )
        return attach_provider_artifacts(
            sink=self._sink,
            route=route,
            adapter=self._runtime.adapter,
            request=request,
            result=result,
        )


def build_style_task(
    project_id: UUID,
    *,
    requested_by: UUID,
    runtime: RegisteredRuntimeFixture,
) -> StyleProfileBuildTask:
    prompt_release_id = uuid4()
    prompt_release_hash = hash_value("profile-prompt-v1")
    inputs = RuntimeInputSnapshot(
        project_id=project_id,
        fact_snapshot_id=uuid4(),
        fact_snapshot_hash=hash_value("facts-v1"),
        profile_version_id=uuid4(),
        profile_hash=hash_value("profile-draft-v1"),
        prompt_release_id=prompt_release_id,
        prompt_release_hash=prompt_release_hash,
        facts_current_approved=True,
        profile_frozen=False,
        prompt_frozen=True,
    )
    selection = runtime.selection
    prompt = FrozenPromptRef(
        project_id=project_id,
        binding_id=uuid4(),
        binding_version=1,
        frozen_state_id=uuid4(),
        frozen_state_version=4,
        release_id=prompt_release_id,
        release_version=1,
        release_hash=prompt_release_hash,
        program_kind=ProgramKind.STYLE_PROFILE,
        purpose="synthetic_lab.style_profile",
        route=runtime.route,
        configured_model=selection.configured_model,
        runtime_manifest_id=selection.runtime_manifest_id,
        runtime_manifest_hash=selection.runtime_manifest_hash,
        runtime_option_id=selection.runtime_option_id,
        runtime_option_hash=selection.runtime_option_hash,
        model_policy=selection.policy,
        model_policy_hash=hash_value("style-profile-policy-v1"),
    )
    return StyleProfileBuildTask(
        project_id=project_id,
        job_id=uuid4(),
        model_job_version=1,
        requested_by=requested_by,
        profile_version_id=inputs.profile_version_id,
        profile_id=uuid4(),
        version_number=1,
        channel="reddit",
        locale="en-AU",
        corpus_hash=hash_value("corpus-v1"),
        approved_sample_count=200,
        sample_manifest_hash=hash_value("sample-manifest-v1"),
        sample_style_evidence=tuple(
            FrozenEvidence(
                ref=f"sample-manifest:{index:02d}",
                subject_id="style:reddit",
                summary=f"Approved anonymous Australian English style evidence {index}.",
            )
            for index in range(1, 25)
        ),
        runtime_inputs=inputs,
        prompt=prompt,
    )


def seed_style_prompt(admin_url: str, task: StyleProfileBuildTask) -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.STYLE_PROFILE)
    program_id = uuid4()
    state_ids = (uuid4(), uuid4(), uuid4(), task.prompt.frozen_state_id)
    with psycopg.connect(admin_url) as connection:
        connection.execute("SET LOCAL session_replication_role = replica")
        connection.execute(
            """INSERT INTO prompt_programs(id, project_id, program_kind, purpose, owner_id)
               VALUES (%s, %s, 'style_profile', %s, %s)""",
            (program_id, task.project_id, task.prompt.purpose, task.requested_by),
        )
        connection.execute(
            """INSERT INTO prompt_program_releases(
                   id, project_id, program_id, program_kind, purpose, version, owner_id,
                   system_template, user_template, variable_schema_version, variable_schema,
                   input_schema_version, input_schema, output_schema_version, output_schema,
                   output_schema_hash, application_output_schema_version,
                   application_output_schema, application_output_schema_hash,
                   model_policy_version, model_policy, model_policy_hash, test_set_id,
                   test_set_version, test_set_hash, compiler_version, system_template_hash,
                   user_template_hash, release_hash
               ) VALUES (
                   %s, %s, %s, 'style_profile', %s, 1,
                   %s, %s, %s,
                   %s, %s,
                   %s, %s,
                   %s, %s, %s,
                   %s, %s, %s,
                   %s, %s, %s,
                   %s, 1, %s, %s, %s, %s, %s
               )""",
            (
                task.prompt.release_id, task.project_id, program_id, task.prompt.purpose,
                task.requested_by, spec.system_template, spec.user_template,
                spec.variable_schema_version, Jsonb(_plain(spec.variable_schema)),
                spec.input_schema_version, Jsonb(_plain(spec.input_schema)),
                spec.output_schema_version, Jsonb(_plain(spec.output_schema)),
                canonical_json_hash(spec.output_schema),
                spec.application_output_schema_version,
                Jsonb(_plain(spec.application_output_schema)),
                canonical_json_hash(spec.application_output_schema),
                spec.model_policy.version, Jsonb(_plain(spec.model_policy.policy)),
                task.prompt.model_policy_hash, spec.test_set_id, spec.test_set_hash,
                spec.compiler_version, hash_value(spec.system_template),
                hash_value(spec.user_template), task.prompt.release_hash,
            ),
        )
        for version, (state_id, status) in enumerate(
            zip(state_ids, ("draft", "tested", "approved", "frozen"), strict=True), 1
        ):
            connection.execute(
                """INSERT INTO prompt_program_release_states(
                       id, project_id, release_id, release_hash, version,
                       previous_state_id, status, acted_by, acted_at, evidence_ref
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                             clock_timestamp(), %s)""",
                (
                    state_id, task.project_id, task.prompt.release_id,
                    task.prompt.release_hash, version,
                    state_ids[version - 2] if version > 1 else None, status,
                    task.requested_by,
                    None if status == "draft" else f"integration:{status}",
                ),
            )
        connection.execute(
            """INSERT INTO prompt_program_bindings(
                   id, project_id, purpose, program_kind, program_id, release_id,
                   release_version, release_hash, frozen_state_id, binding_version,
                   previous_binding_id, bound_by, bound_at
               ) VALUES (%s, %s, %s, 'style_profile', %s, %s, 1, %s, %s, 1,
                         NULL, %s, clock_timestamp())""",
            (
                task.prompt.binding_id, task.project_id, task.prompt.purpose,
                program_id, task.prompt.release_id, task.prompt.release_hash,
                task.prompt.frozen_state_id, task.requested_by,
            ),
        )


def complete_native_child(
    *,
    database: StyleNativeDatabase,
    directory: Path,
    task: StyleProfileBuildTask,
    parent_lease: WorkerLease,
    runtime: RegisteredRuntimeFixture,
) -> tuple[StyleProfileBuildOutput, UUID]:
    spec = default_prompt_bootstrap_spec(ProgramKind.STYLE_PROFILE)
    subject_id = f"style:{task.channel}"
    structured_input = _structured_input(task, subject_id)
    resolved = ResolvedSyntheticPrompt(
        frozen=task.prompt,
        messages=(
            {"role": "system", "content": spec.system_template},
            {"role": "user", "content": json.dumps(structured_input, sort_keys=True)},
        ),
        output_schema=spec.output_schema,
        application_output_schema=spec.application_output_schema,
        prompt_bundle_hash=canonical_hash(
            {"release_hash": task.prompt.release_hash, "input": structured_input}
        ),
        structured_input_hash=canonical_hash(structured_input),
    )
    invocation = SyntheticModelInvocation(
        lease=parent_lease,
        expected_job_version=task.model_job_version,
        parent_task_input_hash=task.input_hash,
        runtime_inputs=task.runtime_inputs,
        prompt=resolved,
        admitted_by=task.requested_by,
        step_key="style-profile:build:v1",
        structured_input=structured_input,
        deterministic_seed=41,
        max_output_tokens=2048,
    )
    child_task = child_task_from_invocation(invocation)
    repository = PostgresSyntheticChildCallRepository(
        lambda: psycopg.connect(database.worker_url, row_factory=dict_row),
        artifacts=_MemoryChildArtifacts(),
        results=_UnusedChildResults(),
    )
    state = repository.resolve_or_stage(child_task, parent_lease=parent_lease)
    assert state.status is SyntheticChildCallStatus.QUEUED
    store = PostgresDurableJobStore(
        lambda: psycopg.connect(database.worker_url, row_factory=dict_row)
    )
    claim = store.claim(
        job_id=child_task.child_job_id,
        project_id=task.project_id,
        expected_kind="synthetic.model.call",
        worker_id="synthetic-style-profile-child-worker",
        lease_for=timedelta(minutes=2),
    )
    assert claim.disposition == "claimed" and claim.lease is not None
    child_lease = claim.lease
    assert repository.load_claimed(child_lease) == child_task
    prompt = _prompt_admission(task, resolved)
    model_persistence = build_model_gateway_persistence(database.worker_url)
    assert model_persistence is not None
    admission = _model_admission(task, child_task, child_lease, runtime, prompt, resolved)
    model_persistence.admit_job(
        admission,
        prompt=prompt,
        admitted_by=task.requested_by,
        admitted_at=datetime.now(UTC),
    )
    output = _style_output(task, subject_id)
    application = ModelCallApplication(
        gateway=_StyleGateway(
            output=output,
            runtime=runtime,
            sink=provider_artifact_sink(
                database_url=database.worker_url, directory=directory
            ),
        ),
        release_registry=model_persistence.load_release_registry(),
        uow_factory=model_persistence.uow_factory,
    )
    execution = application.execute(
        _model_command(task, child_task, child_lease, runtime, resolved),
        policy=runtime.selection.policy,
    )
    assert execution.result is not None
    with store.fenced_transaction(child_lease) as connection:
        store.complete_in_transaction(
            connection,
            child_lease,
            result_ref=f"model-gateway://attempt/{execution.attempt.spec.id}",
            details={"model_attempt_id": str(execution.attempt.spec.id)},
        )
    with psycopg.connect(database.admin_url) as connection:
        try:
            connection.execute(
                """INSERT INTO synthetic_lab_model_call_children
                   SELECT * FROM synthetic_lab_model_call_children
                   WHERE project_id = %s AND child_job_id = %s""",
                (task.project_id, child_task.child_job_id),
            )
        except psycopg.Error as error:
            if error.sqlstate not in {"40001", "23505"}:
                raise
        else:
            raise AssertionError("duplicate Synthetic child was accepted")
    summary = json.dumps(output, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return (
        StyleProfileBuildOutput(
            project_id=task.project_id,
            profile_version_id=task.profile_version_id,
            profile_hash=task.runtime_inputs.profile_hash,
            artifact_hash=canonical_hash(output),
            model_call_ids=(execution.result.call_log_id,),
            profile_summary=summary,
        ),
        child_task.child_job_id,
    )


def _structured_input(task: StyleProfileBuildTask, subject_id: str) -> dict[str, object]:
    return {
        "subject_id": subject_id,
        "allowed_subject_ids": [subject_id],
        "evidence": [
            {**item.prompt_value(), "evidence_scope": "primary_subject"}
            for item in task.sample_style_evidence
        ],
        "output_locale": task.locale,
        "untrusted_text": "",
        "prompt_injection_present": False,
        "channel": task.channel,
        "locale": task.locale,
        "corpus_hash": task.corpus_hash,
        "approved_sample_count": task.approved_sample_count,
        "sample_manifest_hash": task.sample_manifest_hash,
    }


def _style_output(task: StyleProfileBuildTask, subject_id: str) -> dict[str, object]:
    return {
        "subject_id": subject_id,
        "evidence_refs": [item.ref for item in task.sample_style_evidence],
        "citation_refs": [],
        "output_locale": task.locale,
        "automatic_action_authorised": False,
        "injection_detected": False,
        "untrusted_instruction_followed": False,
        "sample_manifest_hash": task.sample_manifest_hash,
        "voice_traits": ["plain-spoken", "specific"],
        "lexical_patterns": ["Australian English – measured comparison"],
        "structure_patterns": ["context before assessment", "short conclusion"],
        "avoid_patterns": ["unsupported superlatives"],
    }


def _prompt_admission(
    task: StyleProfileBuildTask, resolved: ResolvedSyntheticPrompt
) -> PromptReleaseAdmission:
    return PromptReleaseAdmission(
        project_id=task.project_id,
        admission_mode=ModelCallAdmissionMode.RUNTIME_FROZEN,
        binding_id=task.prompt.binding_id,
        state_id=task.prompt.frozen_state_id,
        state_version=task.prompt.frozen_state_version,
        release_id=task.prompt.release_id,
        release_hash=task.prompt.release_hash,
        purpose=task.prompt.purpose,
        output_schema_hash=canonical_json_hash(resolved.output_schema),
        application_output_schema_hash=canonical_json_hash(
            resolved.application_output_schema
        ),
        test_set_hash=None,
        state_status=PromptAdmissionState.FROZEN,
    )


def _model_admission(
    task: StyleProfileBuildTask,
    child: SyntheticChildModelCallTask,
    lease: WorkerLease,
    runtime: RegisteredRuntimeFixture,
    prompt: PromptReleaseAdmission,
    resolved: ResolvedSyntheticPrompt,
) -> ModelCallJobAdmission:
    selection, policy, data = runtime.selection, runtime.selection.policy, runtime.adapter.data_policy
    assert policy.policy_version_id is not None and policy.policy_version_hash is not None
    return ModelCallJobAdmission(
        project_id=task.project_id, job_id=child.child_job_id,
        job_kind="synthetic.model.call", job_version=task.model_job_version,
        admission_mode=prompt.admission_mode, status=JobStatus.RUNNING,
        lease_token=lease.lease_token, fencing_generation=lease.fencing_generation,
        purpose=task.prompt.purpose, usage_audience=ModelAudience.INTERNAL_WORKER,
        route=runtime.route, provider_secret_handle=selection.provider_secret_handle,
        runtime_manifest_id=selection.runtime_manifest_id,
        runtime_manifest_hash=selection.runtime_manifest_hash,
        runtime_option_id=selection.runtime_option_id,
        runtime_option_hash=selection.runtime_option_hash,
        prompt_binding_id=prompt.binding_id, prompt_release_id=prompt.release_id,
        prompt_release_hash=prompt.release_hash, prompt_state_id=prompt.state_id,
        prompt_state_version=prompt.state_version, prompt_test_set_hash=None,
        prompt_bundle_hash=resolved.prompt_bundle_hash,
        output_schema_hash=prompt.output_schema_hash,
        application_output_schema_hash=prompt.application_output_schema_hash,
        policy_version_id=policy.policy_version_id,
        policy_version_hash=policy.policy_version_hash,
        maximum_paid_calls=1, maximum_concurrent_calls=1,
        raw_artifact_policy_hash=runtime.adapter.data_policy_hash,
        raw_artifact_storage_decision=data.storage.value,
        raw_artifact_cache_decision=data.cache.value,
        raw_artifact_display_decision=data.display.value,
        raw_artifact_redistribution_decision=data.redistribution.value,
        raw_artifact_retention_days=data.retention_days,
    )


def _model_command(
    task: StyleProfileBuildTask,
    child: SyntheticChildModelCallTask,
    lease: WorkerLease,
    runtime: RegisteredRuntimeFixture,
    resolved: ResolvedSyntheticPrompt,
) -> ExecuteModelCall:
    selection = runtime.selection
    return ExecuteModelCall(
        project_id=task.project_id, job_id=child.child_job_id,
        expected_job_version=task.model_job_version, lease_token=lease.lease_token,
        fencing_generation=lease.fencing_generation, route=runtime.route,
        runtime_manifest_id=selection.runtime_manifest_id,
        runtime_manifest_hash=selection.runtime_manifest_hash,
        runtime_option_id=selection.runtime_option_id,
        runtime_option_hash=selection.runtime_option_hash,
        prompt_binding_id=task.prompt.binding_id,
        prompt_release_id=task.prompt.release_id,
        prompt_release_hash=task.prompt.release_hash,
        request=ModelGatewayRequest(
            messages=resolved.messages, configured_model=selection.configured_model,
            prompt_bundle_hash=resolved.prompt_bundle_hash, project_id=task.project_id,
            purpose=task.prompt.purpose, usage_audience=ModelAudience.INTERNAL_WORKER,
            temperature=0, max_output_tokens=2048,
            output_schema=resolved.output_schema,
            application_output_schema=resolved.application_output_schema,
            seed=41, capture_method=ModelCaptureMethod.PROVIDER_API,
            provider_secret_handle=selection.provider_secret_handle,
        ),
        attempt_kind=ModelCallAttemptKind.INITIAL,
        attempt_idempotency_key=f"synthetic:{child.child_job_id}:style-profile",
    )


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = [
    "StyleNativeDatabase",
    "build_style_task",
    "complete_native_child",
    "hash_value",
    "seed_style_prompt",
]
