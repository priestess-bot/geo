from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import hashlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.contracts import (
    ModelAudience,
    ModelCaptureMethod,
    ModelGatewayResult,
    ModelPolicy,
)
from geo_core.model_gateway.releases import ModelRoute
from geo_core.prompts.application_models import RuntimePromptProgram
from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.bootstrap_contracts import thaw_mapping
from geo_core.prompts.compiler_versions import BOOTSTRAP_COMPILER_VERSION
from geo_core.prompts.program import (
    ProgramBinding,
    ProgramReleaseState,
    PromptProgram,
    PromptProgramRelease,
)
from geo_core.prompts.program_contracts import ProgramKind, ProgramReleaseStatus
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.corpus import (
    CorpusCandidateEntry,
    CorpusRole,
    CorpusVersion,
    corpus_candidate_set_hash,
    corpus_version_content_hash,
)
from geo_core.synthetic_lab.domain import SyntheticLabContractError
from geo_core.synthetic_lab.execution import SyntheticTaskExecutor
from geo_core.synthetic_lab.execution_contracts import (
    FrozenEvidence,
    FrozenPromptRef,
    OfflineExperimentRunTask,
    RuntimeInputSnapshot,
    StyleProfileBuildTask,
    SyntheticExecutionStale,
    SyntheticModelInvocation,
    SyntheticModelResult,
)
from geo_core.synthetic_lab.execution_gateway import (
    GovernedSyntheticModelCallExecutor,
    ModelCallExecutionAdapter,
    PromptProgramExecutionResolver,
)
from geo_core.synthetic_lab.postgres_codec import decode_object, encode_object
from geo_core.secrets.models import SecretVersionHandle
from geo_core.synthetic_lab.offline_experiment import (
    FrozenExperimentQuestion,
    create_offline_experiment_plan,
)
from geo_core.synthetic_lab.revision import ReviewRunStatus
from tests.unit.synthetic_lab.execution_prompt_contract_support import (
    _CaptureModelCallApplication,
    _GovernedApplication,
    _GovernedRuntime,
    _NoopRecovery,
)


PROJECT_ID = UUID("34000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 7, 23, 16, 0, tzinfo=UTC)


@dataclass
class _RuntimeApplication:
    runtime: RuntimePromptProgram

    def resolve_runtime_binding(self, *, project_id, purpose: str) -> RuntimePromptProgram:
        assert project_id == PROJECT_ID
        del purpose
        return self.runtime


class _GovernedModel:
    def __init__(self) -> None:
        self.inputs: list[Mapping[str, object]] = []

    def execute(self, invocation) -> SyntheticModelResult:
        value = invocation.structured_input
        self.inputs.append(value)
        evidence = value["evidence"]
        assert isinstance(evidence, tuple)
        first = evidence[0]
        assert isinstance(first, Mapping)
        reference = str(first["ref"])
        common = {
            "subject_id": value["subject_id"],
            "evidence_refs": [reference],
            "citation_refs": [reference]
            if invocation.prompt.frozen.program_kind is ProgramKind.OFFLINE_ANSWER
            else [],
            "output_locale": "en-AU",
            "automatic_action_authorised": False,
            "injection_detected": False,
            "untrusted_instruction_followed": False,
        }
        if invocation.prompt.frozen.program_kind is ProgramKind.STYLE_PROFILE:
            output = {
                **common,
                "sample_manifest_hash": value["sample_manifest_hash"],
                "voice_traits": ["plain-spoken"],
                "lexical_patterns": ["Australian spelling"],
                "structure_patterns": ["context before assessment"],
                "avoid_patterns": ["unsupported superlatives"],
            }
        else:
            output = {
                **common,
                "answer_text": "The frozen context supports the measured option.",
                "metric_value": 0.75,
            }
        return SyntheticModelResult(
            model_attempt_id=uuid4(),
            model_call_id=uuid4(),
            output=output,
            provider="openai",
            configured_model="test-model-v1",
            reported_model="test-model-v1",
            model_identity_hash=_hash("model-identity"),
            request_hash=canonical_hash({"step": invocation.step_key}),
            response_hash=canonical_hash(output),
        )


@pytest.mark.parametrize(
    "kind",
    (
        ProgramKind.STYLE_PROFILE,
        ProgramKind.OFFLINE_ANSWER,
        ProgramKind.GENERATION,
        ProgramKind.REVISION,
        ProgramKind.STYLE_JUDGE,
    ),
)
def test_real_resolver_accepts_exact_bootstrap_schema_pair(kind: ProgramKind) -> None:
    runtime, frozen = _runtime(kind)
    spec = default_prompt_bootstrap_spec(kind)
    fixture = next(item for item in spec.fixtures if item.expected_valid)
    resolver = PromptProgramExecutionResolver(_RuntimeApplication(runtime))

    resolved = resolver.resolve(
        frozen=frozen,
        structured_input=thaw_mapping(fixture.input_value),
        output_schema=spec.schemas.output_schema,
        application_output_schema=spec.schemas.application_output_schema,
    )

    assert canonical_hash(resolved.output_schema) == canonical_hash(spec.schemas.output_schema)
    assert canonical_hash(resolved.application_output_schema) == canonical_hash(
        spec.schemas.application_output_schema
    )


def test_real_resolver_rejects_old_schema_hash_and_stale_binding() -> None:
    runtime, frozen = _runtime(ProgramKind.STYLE_PROFILE)
    resolver = PromptProgramExecutionResolver(_RuntimeApplication(runtime))
    spec = default_prompt_bootstrap_spec(ProgramKind.STYLE_PROFILE)
    fixture = next(item for item in spec.fixtures if item.expected_valid)
    values = thaw_mapping(fixture.input_value)
    old_simple_schema = {
        "type": "object",
        "properties": {"voice_traits": {"type": "array", "items": {"type": "string"}}},
        "required": ["voice_traits"],
        "additionalProperties": False,
    }

    with pytest.raises(SyntheticExecutionStale, match="schema"):
        resolver.resolve(
            frozen=frozen,
            structured_input=values,
            output_schema=old_simple_schema,
            application_output_schema=spec.schemas.application_output_schema,
        )
    with pytest.raises(SyntheticExecutionStale, match="schema"):
        resolver.resolve(
            frozen=frozen,
            structured_input=values,
            output_schema=spec.schemas.output_schema,
            application_output_schema=old_simple_schema,
        )
    with pytest.raises(SyntheticExecutionStale, match="identity"):
        resolver.resolve(
            frozen=replace(frozen, release_hash=_hash("wrong-release")),
            structured_input=values,
            output_schema=spec.schemas.output_schema,
            application_output_schema=spec.schemas.application_output_schema,
        )

    stale = replace(
        runtime,
        binding=replace(
            runtime.binding,
            binding_version=2,
            previous_binding_id=runtime.binding.id,
        ),
    )
    with pytest.raises(SyntheticExecutionStale, match="identity"):
        PromptProgramExecutionResolver(_RuntimeApplication(stale)).resolve(
            frozen=frozen,
            structured_input=values,
            output_schema=spec.schemas.output_schema,
            application_output_schema=spec.schemas.application_output_schema,
        )


def test_model_call_adapter_passes_portable_and_application_schema_pair() -> None:
    runtime, frozen = _runtime(ProgramKind.STYLE_PROFILE)
    spec = default_prompt_bootstrap_spec(ProgramKind.STYLE_PROFILE)
    fixture = next(item for item in spec.fixtures if item.expected_valid)
    structured_input = thaw_mapping(fixture.input_value)
    prompt = PromptProgramExecutionResolver(_RuntimeApplication(runtime)).resolve(
        frozen=frozen,
        structured_input=structured_input,
        output_schema=spec.schemas.output_schema,
        application_output_schema=spec.schemas.application_output_schema,
    )
    inputs = _runtime_inputs(frozen, profile_id=uuid4())
    application = _CaptureModelCallApplication()
    adapter = ModelCallExecutionAdapter(application)

    with pytest.raises(RuntimeError, match="captured"):
        adapter.execute(
            SyntheticModelInvocation(
                lease=_lease(uuid4(), "style.profile.build"),
                expected_job_version=1,
                parent_task_input_hash=_hash("parent-task"),
                runtime_inputs=inputs,
                prompt=prompt,
                admitted_by=uuid4(),
                step_key="style-profile:build:v1",
                structured_input=structured_input,
            )
        )

    assert application.command is not None
    request = application.command.request
    assert canonical_hash(request.output_schema) == canonical_hash(spec.schemas.output_schema)
    assert canonical_hash(request.application_output_schema) == canonical_hash(
        spec.schemas.application_output_schema
    )


def test_governed_child_executor_admits_exact_prompt_before_provider_execution() -> None:
    runtime, frozen = _runtime(ProgramKind.STYLE_PROFILE)
    spec = default_prompt_bootstrap_spec(ProgramKind.STYLE_PROFILE)
    fixture = next(item for item in spec.fixtures if item.expected_valid)
    structured_input = thaw_mapping(fixture.input_value)
    prompt = PromptProgramExecutionResolver(_RuntimeApplication(runtime)).resolve(
        frozen=frozen,
        structured_input=structured_input,
        output_schema=spec.schemas.output_schema,
        application_output_schema=spec.schemas.application_output_schema,
    )
    invocation = SyntheticModelInvocation(
        lease=_lease(uuid4(), "synthetic.model.call"),
        expected_job_version=1,
        parent_task_input_hash=_hash("parent-task"),
        runtime_inputs=_runtime_inputs(frozen, profile_id=uuid4()),
        prompt=prompt,
        admitted_by=uuid4(),
        step_key="style-profile:build:v1",
        structured_input=structured_input,
    )
    secret = SecretVersionHandle(
        reference_id=uuid4(),
        project_id=PROJECT_ID,
        purpose="provider.openai",
        version=1,
    )
    job = SimpleNamespace(
        project_id=PROJECT_ID,
        job_id=invocation.lease.job_id,
        job_kind=invocation.lease.kind,
        job_version=7,
        lease_token=invocation.lease.lease_token,
        fencing_generation=invocation.lease.fencing_generation,
        runtime_manifest_id=frozen.runtime_manifest_id,
        runtime_manifest_hash=frozen.runtime_manifest_hash,
        runtime_option_id=frozen.runtime_option_id,
        runtime_option_hash=frozen.runtime_option_hash,
        route=frozen.route,
        prompt_binding_id=frozen.binding_id,
        prompt_release_id=frozen.release_id,
        prompt_release_hash=frozen.release_hash,
        prompt_state_id=frozen.frozen_state_id,
        prompt_state_version=frozen.frozen_state_version,
        purpose=frozen.purpose,
        usage_audience=ModelAudience.INTERNAL_WORKER,
        prompt_bundle_hash=prompt.prompt_bundle_hash,
        output_schema_hash=canonical_hash(prompt.output_schema),
        application_output_schema_hash=canonical_hash(prompt.application_output_schema),
        maximum_paid_calls=1,
        maximum_concurrent_calls=1,
        provider_secret_handle=secret,
    )
    result = ModelGatewayResult(
        output={"voice_traits": ["plain-spoken"]},
        call_log_id=uuid4(),
        provider_request_id="provider-request",
        configured_model=frozen.configured_model,
        provider_reported_model=frozen.configured_model,
        prompt_tokens=1,
        completion_tokens=1,
        cost_usd=None,
        finish_reason="stop",
        response_hash=_hash("response"),
        provider=frozen.route.provider,
        adapter_release_id=frozen.route.adapter_release_id,
        adapter_release_hash=frozen.route.adapter_release_hash,
        model_release_id=frozen.route.model_release_id,
        model_release_hash=frozen.route.model_release_hash,
    )
    application = _GovernedApplication(result)
    loaded = SimpleNamespace(
        job=job,
        policy=ModelPolicy(),
        composition=SimpleNamespace(
            adapters={
                (frozen.route.provider, frozen.route.adapter_release_id): SimpleNamespace(
                    runtime=SimpleNamespace(capture_method=ModelCaptureMethod.PROVIDER_API)
                )
            }
        ),
        application=application,
    )
    gateway = _GovernedRuntime(loaded)

    observed = GovernedSyntheticModelCallExecutor(
        runtime=gateway,
        result_recovery=_NoopRecovery(),
        clock=lambda: NOW,
    ).execute(invocation)

    assert observed.model_call_id == result.call_log_id
    assert len(gateway.admissions) == 1
    admission = gateway.admissions[0]
    assert admission.admitted_by == invocation.admitted_by
    assert admission.prompt.state_id == frozen.frozen_state_id
    assert admission.prompt.state_version == frozen.frozen_state_version
    assert admission.prompt.output_schema_hash == canonical_hash(prompt.output_schema)
    assert admission.prompt.application_output_schema_hash == canonical_hash(
        prompt.application_output_schema
    )
    assert admission.maximum_paid_calls == admission.maximum_concurrent_calls == 1
    assert gateway.loads == [(PROJECT_ID, invocation.lease.job_id)]
    assert application.command is not None
    assert application.command.expected_job_version == 7
    assert application.command.route == frozen.route
    assert application.command.request.provider_secret_handle == secret
    assert application.command.request.capture_method is ModelCaptureMethod.PROVIDER_API


def test_governed_child_executor_rejects_changed_admitted_route_before_execution() -> None:
    runtime, frozen = _runtime(ProgramKind.STYLE_PROFILE)
    spec = default_prompt_bootstrap_spec(ProgramKind.STYLE_PROFILE)
    fixture = next(item for item in spec.fixtures if item.expected_valid)
    prompt = PromptProgramExecutionResolver(_RuntimeApplication(runtime)).resolve(
        frozen=frozen,
        structured_input=thaw_mapping(fixture.input_value),
        output_schema=spec.schemas.output_schema,
        application_output_schema=spec.schemas.application_output_schema,
    )
    invocation = SyntheticModelInvocation(
        lease=_lease(uuid4(), "synthetic.model.call"),
        expected_job_version=1,
        parent_task_input_hash=_hash("parent-task"),
        runtime_inputs=_runtime_inputs(frozen, profile_id=uuid4()),
        prompt=prompt,
        admitted_by=uuid4(),
        step_key="style-profile:build:v1",
        structured_input=thaw_mapping(fixture.input_value),
    )
    job = SimpleNamespace(
        project_id=PROJECT_ID,
        job_id=invocation.lease.job_id,
        job_kind=invocation.lease.kind,
        lease_token=invocation.lease.lease_token,
        fencing_generation=invocation.lease.fencing_generation,
        runtime_manifest_id=frozen.runtime_manifest_id,
        runtime_manifest_hash=frozen.runtime_manifest_hash,
        runtime_option_id=frozen.runtime_option_id,
        runtime_option_hash=frozen.runtime_option_hash,
        route=replace(frozen.route, provider="deepseek"),
        prompt_binding_id=frozen.binding_id,
        prompt_release_id=frozen.release_id,
        prompt_release_hash=frozen.release_hash,
        prompt_state_id=frozen.frozen_state_id,
        prompt_state_version=frozen.frozen_state_version,
        purpose=frozen.purpose,
        usage_audience=ModelAudience.INTERNAL_WORKER,
        prompt_bundle_hash=prompt.prompt_bundle_hash,
        output_schema_hash=canonical_hash(prompt.output_schema),
        application_output_schema_hash=canonical_hash(prompt.application_output_schema),
        maximum_paid_calls=1,
        maximum_concurrent_calls=1,
    )
    application = _GovernedApplication(
        ModelGatewayResult(
            output={},
            call_log_id=uuid4(),
            provider_request_id=None,
            configured_model=frozen.configured_model,
            provider_reported_model=frozen.configured_model,
            prompt_tokens=None,
            completion_tokens=None,
            cost_usd=None,
            finish_reason="stop",
            response_hash=_hash("unused"),
        )
    )
    gateway = _GovernedRuntime(
        SimpleNamespace(
            job=job,
            policy=ModelPolicy(),
            composition=SimpleNamespace(adapters={}),
            application=application,
        )
    )

    with pytest.raises(SyntheticExecutionStale, match="admission differs"):
        GovernedSyntheticModelCallExecutor(
            runtime=gateway,
            result_recovery=_NoopRecovery(),
        ).execute(invocation)

    assert application.command is None


def test_style_profile_executor_uses_governed_envelope_and_full_validation() -> None:
    runtime, frozen = _runtime(ProgramKind.STYLE_PROFILE)
    task = _style_task(frozen)
    model = _GovernedModel()
    executor = SyntheticTaskExecutor(
        prompts=PromptProgramExecutionResolver(_RuntimeApplication(runtime)),
        model_gateway=model,
    )

    output = executor.run(
        lease=_lease(task.job_id, "style.profile.build"),
        task=task,
        checkpoint=lambda: task.runtime_inputs,
    )

    assert output.profile_version_id == task.profile_version_id
    assert len(output.model_call_ids) == 1
    structured = model.inputs[0]
    assert structured["subject_id"] == "style:reddit"
    assert structured["allowed_subject_ids"] == ("style:reddit", "competitor:style")
    evidence = structured["evidence"]
    assert isinstance(evidence, tuple)
    assert [item["evidence_scope"] for item in evidence] == [
        "primary_subject",
        "competitor_subject",
    ]


def test_offline_executor_uses_exact_corpus_evidence_for_all_paired_slots() -> None:
    runtime, frozen = _runtime(ProgramKind.OFFLINE_ANSWER)
    task = _offline_task(frozen)
    model = _GovernedModel()
    executor = SyntheticTaskExecutor(
        prompts=PromptProgramExecutionResolver(_RuntimeApplication(runtime)),
        model_gateway=model,
    )

    output = executor.run(
        lease=_lease(task.job_id, "offline_experiment.run"),
        task=task,
        checkpoint=lambda: task.runtime_inputs,
    )

    assert len(output.slot_results) == 30
    assert all(item.valid for item in output.slot_results)
    assert output.summary is not None
    assert output.summary.planned_pair_count == 10
    assert output.summary.valid_pair_count == 10
    assert output.summary.completion_ratio == 1
    assert output.summary.slot_membership_hash == canonical_hash(
        [{"slot_id": item.slot_id, "result_hash": item.result_hash} for item in output.slot_results]
    )
    assert len(model.inputs) == 30
    for value in model.inputs:
        expected = f"corpus:{value['corpus_version_id']}:{value['corpus_hash']}"
        evidence = value["evidence"]
        assert isinstance(evidence, tuple)
        assert evidence[0]["ref"] == expected
        assert value["subject_id"] == value["question_cluster_key"]

    type_name, payload, _payload_hash = encode_object(output)
    fields = payload["fields"]
    assert isinstance(fields, dict)
    fields.pop("summary")
    legacy = decode_object(type_name, payload)
    assert isinstance(legacy, type(output))
    assert legacy.summary is None


def test_profile_and_offline_tasks_reject_the_wrong_program_kind() -> None:
    _runtime_value, style_judge = _runtime(ProgramKind.STYLE_JUDGE)
    with pytest.raises(SyntheticLabContractError, match="style_profile Prompt"):
        _style_task(style_judge)
    with pytest.raises(SyntheticLabContractError, match="Prompt purpose"):
        replace(style_judge, purpose="synthetic_lab.generation")


def _runtime(kind: ProgramKind) -> tuple[RuntimePromptProgram, FrozenPromptRef]:
    spec = default_prompt_bootstrap_spec(kind)
    owner_id = uuid4()
    program = PromptProgram(
        id=uuid4(),
        project_id=PROJECT_ID,
        program_kind=kind,
        purpose=spec.purpose,
        owner_id=owner_id,
    )
    release = PromptProgramRelease.compile(
        id=uuid4(),
        program=program,
        version=1,
        system_template=spec.system_template,
        user_template=spec.user_template,
        schemas=spec.schemas,
        model_policy=spec.model_policy,
        test_set_id=uuid4(),
        test_set_version=1,
        test_set_hash=_hash(f"{kind.value}:test-set"),
        compiler_version=BOOTSTRAP_COMPILER_VERSION,
    )
    state = ProgramReleaseState(
        id=uuid4(),
        release_id=release.id,
        release_hash=release.release_hash,
        version=4,
        previous_state_id=uuid4(),
        status=ProgramReleaseStatus.FROZEN,
        acted_by=owner_id,
        acted_at=NOW,
        evidence_ref=f"test:{kind.value}",
    )
    binding = ProgramBinding(
        id=uuid4(),
        project_id=PROJECT_ID,
        purpose=release.purpose,
        program_kind=kind,
        program_id=program.id,
        release_id=release.id,
        release_version=release.version,
        release_hash=release.release_hash,
        frozen_state_id=state.id,
        binding_version=1,
        previous_binding_id=None,
        bound_by=owner_id,
        bound_at=NOW,
    )
    frozen = FrozenPromptRef(
        project_id=PROJECT_ID,
        binding_id=binding.id,
        binding_version=binding.binding_version,
        frozen_state_id=state.id,
        frozen_state_version=state.version,
        release_id=release.id,
        release_version=release.version,
        release_hash=release.release_hash,
        program_kind=kind,
        purpose=release.purpose,
        route=ModelRoute(
            provider="openai",
            adapter_release_id="openai-v1",
            adapter_release_hash=_hash("adapter"),
            model_release_id="test-model-v1",
            model_release_hash=_hash("model"),
        ),
        configured_model="test-model-v1",
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash=_hash("manifest"),
        runtime_option_id=uuid4(),
        runtime_option_hash=_hash("option"),
        model_policy=ModelPolicy(),
        model_policy_hash=release.model_policy.policy_hash,
    )
    return RuntimePromptProgram(release, state, binding), frozen


def _runtime_inputs(frozen: FrozenPromptRef, *, profile_id: UUID) -> RuntimeInputSnapshot:
    return RuntimeInputSnapshot(
        project_id=PROJECT_ID,
        fact_snapshot_id=uuid4(),
        fact_snapshot_hash=_hash("facts"),
        profile_version_id=profile_id,
        profile_hash=_hash("profile"),
        prompt_release_id=frozen.release_id,
        prompt_release_hash=frozen.release_hash,
        facts_current_approved=True,
        profile_frozen=True,
        prompt_frozen=True,
    )


def _style_task(frozen: FrozenPromptRef) -> StyleProfileBuildTask:
    profile_id = uuid4()
    return StyleProfileBuildTask(
        project_id=PROJECT_ID,
        job_id=uuid4(),
        model_job_version=1,
        requested_by=uuid4(),
        profile_version_id=profile_id,
        profile_id=uuid4(),
        version_number=1,
        channel="reddit",
        locale="en-AU",
        corpus_hash=_hash("style-corpus"),
        approved_sample_count=200,
        sample_manifest_hash=_hash("sample-manifest"),
        sample_style_evidence=(
            FrozenEvidence(
                ref="sample:primary",
                subject_id="style:reddit",
                summary="Approved anonymous Australian English sample.",
            ),
            FrozenEvidence(
                ref="sample:competitor",
                subject_id="competitor:style",
                summary="Approved comparison style sample.",
            ),
        ),
        runtime_inputs=_runtime_inputs(frozen, profile_id=profile_id),
        prompt=frozen,
    )


def _offline_task(frozen: FrozenPromptRef) -> OfflineExperimentRunTask:
    fact_id, profile_id = uuid4(), uuid4()
    fact_hash, profile_hash = _hash("facts"), _hash("profile")
    corpora = tuple(
        _corpus(
            role,
            frozen=frozen,
            fact_id=fact_id,
            fact_hash=fact_hash,
            profile_id=profile_id,
            profile_hash=profile_hash,
        )
        for role in CorpusRole
    )
    question = FrozenExperimentQuestion(
        project_id=PROJECT_ID,
        question_version_id=uuid4(),
        ordinal=1,
        question_hash=_hash("question"),
        question_cluster_key="pressure-washer-comparison",
    )
    plan = create_offline_experiment_plan(
        id=uuid4(),
        project_id=PROJECT_ID,
        question_set_id=uuid4(),
        question_set_hash=_hash("question-set"),
        protocol_id=uuid4(),
        protocol_hash=_hash("protocol"),
        prompt_release_id=frozen.release_id,
        prompt_release_hash=frozen.release_hash,
        approved_fact_snapshot_id=fact_id,
        approved_fact_snapshot_hash=fact_hash,
        profile_version_id=profile_id,
        profile_hash=profile_hash,
        model_policy_hash=frozen.model_policy_hash,
        model_provider="openai",
        configured_model="test-model-v1",
        reported_model="test-model-v1",
        model_identity_hash=_hash("model-identity"),
        metric_method_release="metric-v1",
        metric_method_hash=_hash("metric"),
        seed_namespace_hash=_hash("seed"),
        questions=(question,),
        corpora=corpora,
    )
    runtime = _runtime_inputs(frozen, profile_id=profile_id)
    runtime = replace(
        runtime,
        fact_snapshot_id=fact_id,
        fact_snapshot_hash=fact_hash,
        profile_hash=profile_hash,
    )
    return OfflineExperimentRunTask(
        project_id=PROJECT_ID,
        job_id=uuid4(),
        model_job_version=1,
        requested_by=uuid4(),
        result_id=uuid4(),
        plan=plan,
        question_text={question.question_version_id: "Which option best fits this use case?"},
        corpus_context={item.id: f"Frozen context for {item.role.value}." for item in corpora},
        runtime_inputs=runtime,
        prompt=frozen,
    )


def _corpus(
    role: CorpusRole,
    *,
    frozen: FrozenPromptRef,
    fact_id: UUID,
    fact_hash: str,
    profile_id: UUID,
    profile_hash: str,
) -> CorpusVersion:
    candidates: tuple[CorpusCandidateEntry, ...] = ()
    if role is not CorpusRole.NO_CORPUS_BASELINE:
        candidates = (
            CorpusCandidateEntry(
                project_id=PROJECT_ID,
                resolution_id=uuid4(),
                candidate_id=uuid4(),
                candidate_output_hash=_hash(f"candidate:{role.value}"),
                status=ReviewRunStatus.PASSED,
                warning_codes=(),
                channel="reddit",
                scenario_mode="autonomous_scenario",
                competitor_scenario=True,
                model_key="test-model-v1",
                model_identity_hash=_hash("model-identity"),
                question_cluster_key="pressure-washer-comparison",
            ),
        )
    candidate_hash = corpus_candidate_set_hash(candidates)
    return CorpusVersion(
        id=uuid4(),
        project_id=PROJECT_ID,
        corpus_id=uuid4(),
        version_number=1,
        role=role,
        approved_fact_snapshot_id=fact_id,
        approved_fact_snapshot_hash=fact_hash,
        profile_version_id=profile_id,
        profile_hash=profile_hash,
        prompt_release_id=frozen.release_id,
        prompt_release_hash=frozen.release_hash,
        candidates=candidates,
        candidate_set_hash=candidate_hash,
        guard_evidence_hash=_hash(f"guard:{role.value}"),
        content_hash=corpus_version_content_hash(
            role=role,
            approved_fact_snapshot_id=fact_id,
            approved_fact_snapshot_hash=fact_hash,
            profile_version_id=profile_id,
            profile_hash=profile_hash,
            prompt_release_id=frozen.release_id,
            prompt_release_hash=frozen.release_hash,
            candidate_set_hash=candidate_hash,
        ),
    )


def _lease(job_id: UUID, kind: str) -> WorkerLease:
    return WorkerLease(
        job_id=job_id,
        project_id=PROJECT_ID,
        kind=kind,
        worker_id="synthetic-prompt-test",
        lease_token=uuid4(),
        fencing_generation=1,
        attempt_count=1,
        max_attempts=3,
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
