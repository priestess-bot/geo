"""Frozen contracts for lease-owned Synthetic Lab production execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, TypeAlias
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.contracts import ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.prompts.bootstrap_templates import bootstrap_template
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.domain import (
    AU_ENGLISH_LOCALE,
    MIN_PROFILE_SAMPLE_COUNT,
    STANDARD_STYLE_CHANNELS,
    SyntheticLabContractError,
    _require_hash,
    _require_text,
    _require_uuid,
)
from geo_core.synthetic_lab.generation import GenerationBatch
from geo_core.synthetic_lab.offline_experiment import (
    OfflineExperimentPlan,
    OfflineSlotResult,
)
from geo_core.synthetic_lab.ports import RuntimeInputSnapshot
from geo_core.synthetic_lab.review_cases import ReviewCase
from geo_core.synthetic_lab.revision import (
    CandidateResolution,
    CandidateRevision,
)
from geo_core.synthetic_lab.evaluation import CandidateEvaluation
from geo_core.synthetic_lab.execution_evidence_validation import (
    validate_review_subject_inventory,
)
from geo_core.synthetic_lab.execution_json import freeze_execution_mapping as _freeze_mapping
from geo_core.synthetic_lab.execution_task_hashing import (
    offline_task_value as _offline_task_value,
    review_task_value as _review_task_value,
    style_task_value as _style_task_value,
)


class SyntheticExecutionError(RuntimeError):
    """A production execution contract failed without exposing model content."""


class SyntheticExecutionStale(SyntheticExecutionError):
    """A Fact, Profile, Prompt binding or immutable task changed."""


@dataclass(frozen=True, kw_only=True)
class FrozenPromptRef:
    project_id: UUID
    binding_id: UUID
    binding_version: int
    frozen_state_id: UUID
    frozen_state_version: int
    release_id: UUID
    release_version: int
    release_hash: str
    program_kind: ProgramKind
    purpose: str
    route: ModelRoute
    configured_model: str
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    model_policy: ModelPolicy
    model_policy_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.project_id, "Prompt project"),
            (self.binding_id, "Prompt binding"),
            (self.frozen_state_id, "Prompt frozen state"),
            (self.release_id, "Prompt Release"),
            (self.runtime_manifest_id, "runtime manifest"),
            (self.runtime_option_id, "runtime option"),
        ):
            _require_uuid(value, label)
        if (
            self.binding_version < 1
            or self.frozen_state_version < 1
            or self.release_version < 1
        ):
            raise SyntheticLabContractError(
                "Prompt binding, frozen-state and Release versions must be positive"
            )
        object.__setattr__(self, "program_kind", ProgramKind(self.program_kind))
        _require_hash(self.release_hash, "Prompt Release")
        _require_hash(self.runtime_manifest_hash, "runtime manifest")
        _require_hash(self.runtime_option_hash, "runtime option")
        _require_hash(self.model_policy_hash, "Prompt model policy")
        _require_text(self.purpose, "Prompt purpose")
        if self.purpose != bootstrap_template(self.program_kind).purpose:
            raise SyntheticLabContractError(
                "Prompt purpose must match the exact governed Program kind"
            )
        _require_text(self.configured_model, "configured model")
        if self.route.provider.strip() == "":
            raise SyntheticLabContractError("Prompt route provider is required")

    @property
    def identity_hash(self) -> str:
        return canonical_hash(
            {
                "project_id": self.project_id,
                "binding_id": self.binding_id,
                "binding_version": self.binding_version,
                "frozen_state_id": self.frozen_state_id,
                "frozen_state_version": self.frozen_state_version,
                "release_id": self.release_id,
                "release_version": self.release_version,
                "release_hash": self.release_hash,
                "program_kind": self.program_kind,
                "purpose": self.purpose,
                "route": self.route,
                "configured_model": self.configured_model,
                "runtime_manifest_id": self.runtime_manifest_id,
                "runtime_manifest_hash": self.runtime_manifest_hash,
                "runtime_option_id": self.runtime_option_id,
                "runtime_option_hash": self.runtime_option_hash,
                "model_policy_hash": self.model_policy_hash,
            }
        )


@dataclass(frozen=True, kw_only=True)
class ResolvedSyntheticPrompt:
    frozen: FrozenPromptRef
    messages: tuple[dict[str, str], ...]
    output_schema: Mapping[str, object]
    application_output_schema: Mapping[str, object]
    prompt_bundle_hash: str
    structured_input_hash: str

    def __post_init__(self) -> None:
        if not self.messages or any(
            set(message) != {"role", "content"}
            or not message["role"].strip()
            or not message["content"].strip()
            for message in self.messages
        ):
            raise SyntheticLabContractError("resolved Prompt messages are invalid")
        object.__setattr__(self, "output_schema", _freeze_mapping(self.output_schema))
        object.__setattr__(
            self,
            "application_output_schema",
            _freeze_mapping(self.application_output_schema),
        )
        _require_hash(self.prompt_bundle_hash, "Prompt bundle")
        _require_hash(self.structured_input_hash, "Prompt structured input")


@dataclass(frozen=True, kw_only=True)
class SyntheticModelInvocation:
    lease: WorkerLease
    expected_job_version: int
    parent_task_input_hash: str
    runtime_inputs: RuntimeInputSnapshot
    prompt: ResolvedSyntheticPrompt
    admitted_by: UUID
    step_key: str
    structured_input: Mapping[str, object]
    deterministic_seed: int | None = None
    max_output_tokens: int = 4096

    def __post_init__(self) -> None:
        if self.expected_job_version < 1:
            raise SyntheticLabContractError("model-call Job version must be positive")
        if self.prompt.frozen.project_id != self.lease.project_id:
            raise SyntheticLabContractError("model Prompt and Job belong to different Projects")
        if self.runtime_inputs.project_id != self.lease.project_id:
            raise SyntheticLabContractError("model runtime inputs and Job belong to different Projects")
        _require_uuid(self.admitted_by, "model-call admission actor")
        _require_hash(self.parent_task_input_hash, "parent Synthetic task input")
        _require_text(self.step_key, "deterministic model step key")
        object.__setattr__(self, "structured_input", _freeze_mapping(self.structured_input))
        if self.deterministic_seed is not None and not 0 <= self.deterministic_seed < 2**64:
            raise SyntheticLabContractError("deterministic model seed is out of range")
        if self.max_output_tokens < 1:
            raise SyntheticLabContractError("model output token limit must be positive")


@dataclass(frozen=True, kw_only=True)
class SyntheticModelResult:
    model_attempt_id: UUID
    model_call_id: UUID
    output: Mapping[str, object]
    provider: str
    configured_model: str
    reported_model: str
    model_identity_hash: str
    request_hash: str
    response_hash: str

    def __post_init__(self) -> None:
        _require_uuid(self.model_attempt_id, "model-call attempt")
        _require_uuid(self.model_call_id, "model call")
        object.__setattr__(self, "output", _freeze_mapping(self.output))
        for value, label in (
            (self.provider, "model provider"),
            (self.configured_model, "configured model"),
            (self.reported_model, "reported model"),
        ):
            _require_text(value, label)
        for value, label in (
            (self.model_identity_hash, "model identity"),
            (self.request_hash, "model request"),
            (self.response_hash, "model response"),
        ):
            _require_hash(value, label)


@dataclass(frozen=True, kw_only=True)
class FrozenEvidence:
    ref: str
    subject_id: str
    summary: str
    fact_id: UUID | None = None
    fact_hash: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.ref, "evidence reference"),
            (self.subject_id, "evidence subject"),
            (self.summary, "evidence summary"),
        ):
            _require_text(value, label)
        if (self.fact_id is None) != (self.fact_hash is None):
            raise SyntheticLabContractError("Fact evidence requires both ID and hash")
        if self.fact_id is not None:
            _require_uuid(self.fact_id, "evidence Fact")
            _require_hash(self.fact_hash or "", "evidence Fact")

    def prompt_value(self) -> dict[str, str]:
        return {"ref": self.ref, "subject_id": self.subject_id, "summary": self.summary}


@dataclass(frozen=True, kw_only=True)
class StyleProfileBuildTask:
    project_id: UUID
    job_id: UUID
    model_job_version: int
    requested_by: UUID
    profile_version_id: UUID
    profile_id: UUID
    version_number: int
    channel: str
    locale: str
    corpus_hash: str
    approved_sample_count: int
    sample_manifest_hash: str
    sample_style_evidence: tuple[FrozenEvidence, ...]
    runtime_inputs: RuntimeInputSnapshot
    prompt: FrozenPromptRef
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_task_identity(self.project_id, self.job_id, self.model_job_version)
        _require_uuid(self.requested_by, "Style Profile execution requester")
        _require_uuid(self.profile_version_id, "target Profile version")
        _require_uuid(self.profile_id, "target Profile")
        if self.version_number < 1:
            raise SyntheticLabContractError("target Profile version must be positive")
        if self.channel not in STANDARD_STYLE_CHANNELS or self.locale != AU_ENGLISH_LOCALE:
            raise SyntheticLabContractError("Style Profile task channel/locale is unsupported")
        if self.approved_sample_count < MIN_PROFILE_SAMPLE_COUNT:
            raise SyntheticLabContractError("Style Profile build requires at least 200 samples")
        for value, label in (
            (self.corpus_hash, "Style Profile corpus"),
            (self.sample_manifest_hash, "Style sample manifest"),
        ):
            _require_hash(value, label)
        evidence = tuple(self.sample_style_evidence)
        object.__setattr__(self, "sample_style_evidence", evidence)
        if not evidence or len({item.ref for item in evidence}) != len(evidence):
            raise SyntheticLabContractError("Style Profile evidence must be non-empty and unique")
        _validate_task_runtime(self.project_id, self.job_id, self.runtime_inputs, self.prompt)
        if self.prompt.program_kind is not ProgramKind.STYLE_PROFILE:
            raise SyntheticLabContractError(
                "Style Profile task requires the exact style_profile Prompt"
            )
        object.__setattr__(self, "input_hash", canonical_hash(_style_task_value(self)))


@dataclass(frozen=True, kw_only=True)
class ReviewCaseRunTask:
    project_id: UUID
    job_id: UUID
    model_job_version: int
    requested_by: UUID
    review_run_id: UUID
    review_suite_hash: str
    case: ReviewCase
    subject_id: UUID
    evidence: tuple[FrozenEvidence, ...]
    style_profile_summary: str
    style_pass_threshold: float
    runtime_inputs: RuntimeInputSnapshot
    prompts: Mapping[ProgramKind, FrozenPromptRef]
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_task_identity(self.project_id, self.job_id, self.model_job_version)
        _require_uuid(self.requested_by, "Review Case execution requester")
        _require_uuid(self.review_run_id, "Review Run")
        _require_hash(self.review_suite_hash, "Review Suite")
        _require_uuid(self.subject_id, "Review Case subject identity")
        _require_text(self.style_profile_summary, "Style Profile summary")
        if not 0 <= self.style_pass_threshold <= 5:
            raise SyntheticLabContractError("style pass threshold must be between 0 and 5")
        evidence = tuple(self.evidence)
        object.__setattr__(self, "evidence", evidence)
        if not evidence or len({item.ref for item in evidence}) != len(evidence):
            raise SyntheticLabContractError("Review Case evidence must be non-empty and unique")
        validate_review_subject_inventory(self.subject_id, evidence)
        prompts = MappingProxyType({ProgramKind(key): value for key, value in self.prompts.items()})
        object.__setattr__(self, "prompts", prompts)
        required = {
            ProgramKind.GENERATION,
            ProgramKind.CLAIM_EXTRACTION,
            ProgramKind.CONFLICT_CHECK,
            ProgramKind.REVISION,
            ProgramKind.STYLE_JUDGE,
            ProgramKind.ARBITER,
        }
        if set(prompts) != required or any(ref.program_kind != kind for kind, ref in prompts.items()):
            raise SyntheticLabContractError("Review Case task requires six exact Prompt bindings")
        if self.case.project_id != self.project_id:
            raise SyntheticLabContractError("Review Case task crosses Project scope")
        _validate_task_runtime(
            self.project_id,
            self.job_id,
            self.runtime_inputs,
            prompts[ProgramKind.GENERATION],
        )
        if any(ref.project_id != self.project_id for ref in prompts.values()):
            raise SyntheticLabContractError("Review Case Prompt belongs to another Project")
        if len({ref.model_policy_hash for ref in prompts.values()}) != 1:
            raise SyntheticLabContractError("Review Case Prompt model policies are not frozen alike")
        object.__setattr__(self, "input_hash", canonical_hash(_review_task_value(self)))


@dataclass(frozen=True, kw_only=True)
class OfflineExperimentRunTask:
    project_id: UUID
    job_id: UUID
    model_job_version: int
    requested_by: UUID
    result_id: UUID
    plan: OfflineExperimentPlan
    question_text: Mapping[UUID, str]
    corpus_context: Mapping[UUID, str]
    runtime_inputs: RuntimeInputSnapshot
    prompt: FrozenPromptRef
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_task_identity(self.project_id, self.job_id, self.model_job_version)
        _require_uuid(self.requested_by, "Offline Experiment execution requester")
        _require_uuid(self.result_id, "Offline Experiment result")
        if self.plan.project_id != self.project_id:
            raise SyntheticLabContractError("Offline Experiment task crosses Project scope")
        questions = dict(self.question_text)
        corpora = dict(self.corpus_context)
        if set(questions) != {item.question_version_id for item in self.plan.questions}:
            raise SyntheticLabContractError("Offline Experiment question material is incomplete")
        if set(corpora) != {item.id for item in self.plan.corpora}:
            raise SyntheticLabContractError("Offline Experiment Corpus material is incomplete")
        if any(not value.strip() for value in (*questions.values(), *corpora.values())):
            raise SyntheticLabContractError("Offline Experiment material cannot be empty")
        object.__setattr__(self, "question_text", MappingProxyType(questions))
        object.__setattr__(self, "corpus_context", MappingProxyType(corpora))
        _validate_task_runtime(self.project_id, self.job_id, self.runtime_inputs, self.prompt)
        if self.prompt.program_kind is not ProgramKind.OFFLINE_ANSWER:
            raise SyntheticLabContractError(
                "Offline Experiment task requires the exact offline_answer Prompt"
            )
        object.__setattr__(self, "input_hash", canonical_hash(_offline_task_value(self)))


@dataclass(frozen=True, kw_only=True)
class StyleProfileBuildOutput:
    project_id: UUID
    profile_version_id: UUID
    profile_hash: str
    artifact_hash: str
    model_call_ids: tuple[UUID, ...]
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "Profile result Project")
        _require_uuid(self.profile_version_id, "Profile result version")
        _require_hash(self.profile_hash, "Profile result")
        _require_hash(self.artifact_hash, "Profile artifact")
        if len(self.model_call_ids) != 1:
            raise SyntheticLabContractError("Profile build requires exactly one model call")
        object.__setattr__(
            self,
            "result_hash",
            canonical_hash(
                {
                    "project_id": self.project_id,
                    "profile_version_id": self.profile_version_id,
                    "profile_hash": self.profile_hash,
                    "artifact_hash": self.artifact_hash,
                    "model_call_ids": self.model_call_ids,
                }
            ),
        )


@dataclass(frozen=True, kw_only=True)
class ReviewCaseRunOutput:
    project_id: UUID
    review_run_id: UUID
    review_case_id: UUID
    batches: tuple[GenerationBatch, ...]
    revisions: tuple[CandidateRevision, ...]
    evaluations: tuple[CandidateEvaluation, ...]
    resolution: CandidateResolution
    model_call_ids: tuple[UUID, ...]
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.project_id, "Review result Project"),
            (self.review_run_id, "Review result Run"),
            (self.review_case_id, "Review result Case"),
        ):
            _require_uuid(value, label)
        if not self.batches or not self.evaluations or not self.model_call_ids:
            raise SyntheticLabContractError("Review result is missing execution evidence")
        if self.resolution.review_case_id != self.review_case_id:
            raise SyntheticLabContractError("Review result resolution belongs to another Case")
        object.__setattr__(
            self,
            "result_hash",
            canonical_hash(
                {
                    "project_id": self.project_id,
                    "review_run_id": self.review_run_id,
                    "review_case_id": self.review_case_id,
                    "batches": self.batches,
                    "revisions": self.revisions,
                    "evaluations": self.evaluations,
                    "resolution": self.resolution,
                    "model_call_ids": self.model_call_ids,
                }
            ),
        )


@dataclass(frozen=True, kw_only=True)
class OfflineExperimentRunOutput:
    project_id: UUID
    experiment_id: UUID
    result_id: UUID
    slot_results: tuple[OfflineSlotResult, ...]
    model_call_ids: tuple[UUID, ...]
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.project_id, "Experiment result Project"),
            (self.experiment_id, "Experiment"),
            (self.result_id, "Experiment result"),
        ):
            _require_uuid(value, label)
        if not self.slot_results:
            raise SyntheticLabContractError("Offline Experiment produced no slot results")
        object.__setattr__(
            self,
            "result_hash",
            canonical_hash(
                {
                    "project_id": self.project_id,
                    "experiment_id": self.experiment_id,
                    "result_id": self.result_id,
                    "slot_results": self.slot_results,
                    "model_call_ids": self.model_call_ids,
                }
            ),
        )


SyntheticExecutionTask: TypeAlias = (
    StyleProfileBuildTask | ReviewCaseRunTask | OfflineExperimentRunTask
)
SyntheticExecutionOutput: TypeAlias = (
    StyleProfileBuildOutput | ReviewCaseRunOutput | OfflineExperimentRunOutput
)


class SyntheticPromptResolverPort(Protocol):
    def resolve(
        self,
        *,
        frozen: FrozenPromptRef,
        structured_input: Mapping[str, object],
        output_schema: Mapping[str, object],
        application_output_schema: Mapping[str, object],
    ) -> ResolvedSyntheticPrompt: ...

    def assert_current(self, frozen: FrozenPromptRef) -> None: ...


class SyntheticModelCallPort(Protocol):
    def execute(self, invocation: SyntheticModelInvocation) -> SyntheticModelResult: ...


class SyntheticExecutionRepositoryPort(Protocol):
    def load(self, lease: WorkerLease) -> SyntheticExecutionTask: ...

    def finalize(
        self,
        *,
        connection: object,
        lease: WorkerLease,
        task: SyntheticExecutionTask,
        output: SyntheticExecutionOutput,
        runtime: RuntimeInputSnapshot,
    ) -> None: ...


class SyntheticExecutionTaskStagingPort(Protocol):
    """Persist an exact executable task in the enqueue transaction."""

    def stage(
        self,
        task: SyntheticExecutionTask,
        expected_job_input_hash: str,
    ) -> None: ...


ExecutionCheckpoint: TypeAlias = Callable[[], RuntimeInputSnapshot]


def prompt_refs(task: SyntheticExecutionTask) -> tuple[FrozenPromptRef, ...]:
    if isinstance(task, ReviewCaseRunTask):
        return tuple(task.prompts[kind] for kind in sorted(task.prompts, key=lambda item: item.value))
    return (task.prompt,)
def _validate_task_identity(project_id: UUID, job_id: UUID, version: int) -> None:
    _require_uuid(project_id, "execution task Project")
    _require_uuid(job_id, "execution task Job")
    if version < 1:
        raise SyntheticLabContractError("execution task model Job version must be positive")


def _validate_task_runtime(
    project_id: UUID,
    job_id: UUID,
    runtime: RuntimeInputSnapshot,
    prompt: FrozenPromptRef,
) -> None:
    if runtime.project_id != project_id or prompt.project_id != project_id:
        raise SyntheticLabContractError("execution runtime crosses Project scope")
    del job_id
    if (
        runtime.prompt_release_id != prompt.release_id
        or runtime.prompt_release_hash != prompt.release_hash
    ):
        raise SyntheticLabContractError("primary Prompt does not match frozen runtime inputs")


__all__ = [
    "ExecutionCheckpoint", "FrozenEvidence", "FrozenPromptRef",
    "OfflineExperimentRunOutput", "OfflineExperimentRunTask", "ResolvedSyntheticPrompt",
    "ReviewCaseRunOutput", "ReviewCaseRunTask",
    "StyleProfileBuildOutput", "StyleProfileBuildTask",
    "SyntheticExecutionError", "SyntheticExecutionOutput", "SyntheticExecutionRepositoryPort",
    "SyntheticExecutionTaskStagingPort", "SyntheticExecutionStale", "SyntheticExecutionTask",
    "SyntheticModelCallPort", "SyntheticModelInvocation", "SyntheticModelResult",
    "SyntheticPromptResolverPort",
    "prompt_refs",
]
