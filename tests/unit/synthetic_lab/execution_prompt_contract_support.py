"""Test doubles shared by Synthetic execution Prompt contract tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from types import SimpleNamespace
from uuid import UUID, uuid4

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.contracts import ModelGatewayResult, ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.prompts.application_models import RuntimePromptProgram
from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.compiler_versions import BOOTSTRAP_COMPILER_VERSION
from geo_core.prompts.program import (
    ProgramBinding,
    ProgramReleaseState,
    PromptProgram,
    PromptProgramRelease,
)
from geo_core.prompts.program_contracts import ProgramKind, ProgramReleaseStatus
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.execution_contracts import (
    FrozenEvidence,
    FrozenPromptRef,
    RuntimeInputSnapshot,
    StyleProfileBuildTask,
    SyntheticModelResult,
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
    def __init__(self, *, large_style_profile: bool = False) -> None:
        self.inputs: list[Mapping[str, object]] = []
        self.structured_input_hashes: list[str] = []
        self.large_style_profile = large_style_profile

    def execute(self, invocation) -> SyntheticModelResult:
        value = invocation.structured_input
        self.inputs.append(value)
        self.structured_input_hashes.append(invocation.prompt.structured_input_hash)
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
            patterns = (
                [f"plain-spoken-{index}-" + ("x" * 170) for index in range(12)]
                if self.large_style_profile
                else ["plain-spoken"]
            )
            output = {
                **common,
                "sample_manifest_hash": value["sample_manifest_hash"],
                "voice_traits": patterns,
                "lexical_patterns": [
                    item.replace("plain-spoken", "Australian-spelling")
                    for item in patterns
                ],
                "structure_patterns": [
                    item.replace("plain-spoken", "context-first")
                    for item in patterns
                ],
                "avoid_patterns": [
                    item.replace("plain-spoken", "unsupported-superlative")
                    for item in patterns
                ],
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


class _CaptureModelCallApplication:
    def __init__(self) -> None:
        self.command = None

    def execute(self, command, *, policy):
        del policy
        self.command = command
        raise RuntimeError("captured before external execution")


class _GovernedRuntime:
    def __init__(self, loaded) -> None:
        self.loaded = loaded
        self.admissions = []
        self.loads = []

    def load_or_admit_claimed_job(self, request):
        self.admissions.append(request)
        return SimpleNamespace(job=self.loaded.job)

    def load(self, *, project_id, job_id):
        self.loads.append((project_id, job_id))
        return self.loaded


class _GovernedApplication:
    def __init__(self, result: ModelGatewayResult) -> None:
        self.result = result
        self.command = None

    def execute(self, command, *, policy):
        del policy
        self.command = command
        return SimpleNamespace(
            attempt=SimpleNamespace(spec=SimpleNamespace(id=uuid4())),
            result=self.result,
        )


class _NoopRecovery:
    def recover_derived(self, request):
        del request
        raise AssertionError("non-replayed model call must not recover an artifact")


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


__all__ = [
    "NOW",
    "PROJECT_ID",
    "_CaptureModelCallApplication",
    "_GovernedApplication",
    "_GovernedModel",
    "_GovernedRuntime",
    "_NoopRecovery",
    "_RuntimeApplication",
    "_hash",
    "_lease",
    "_runtime",
    "_runtime_inputs",
    "_style_task",
]
