"""Frozen contracts for lease-owned Synthetic Lab production execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, TypeAlias
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.corpus import CorpusCandidateEntry, CorpusRole
from geo_core.synthetic_lab.domain import (
    AU_ENGLISH_LOCALE,
    MIN_PROFILE_SAMPLE_COUNT,
    STANDARD_STYLE_CHANNELS,
    SyntheticLabContractError,
    _require_hash,
    _require_text,
    _require_uuid,
)
from geo_core.synthetic_lab.offline_experiment import (
    OfflineExperimentPlan,
)
from geo_core.synthetic_lab.ports import RuntimeInputSnapshot
from geo_core.synthetic_lab.review_cases import ReviewCase
from geo_core.synthetic_lab.execution_evidence_validation import (
    validate_review_subject_inventory,
)
from geo_core.synthetic_lab.execution_model_contracts import (
    FrozenPromptRef,
    ResolvedSyntheticPrompt,
    SyntheticModelInvocation,
    SyntheticModelResult,
)
from geo_core.synthetic_lab.execution_outputs import (
    CorpusFinalizeOutput,
    OfflineExperimentRunOutput,
    ReviewCaseRunOutput,
    StyleProfileBuildOutput,
)
from geo_core.synthetic_lab.execution_task_hashing import (
    corpus_task_value as _corpus_task_value,
    offline_task_value as _offline_task_value,
    review_task_value as _review_task_value,
    style_task_value as _style_task_value,
)


class SyntheticExecutionError(RuntimeError):
    """A production execution contract failed without exposing model content."""


class SyntheticExecutionStale(SyntheticExecutionError):
    """A Fact, Profile, Prompt binding or immutable task changed."""


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
        if set(prompts) != required or any(
            ref.program_kind != kind for kind, ref in prompts.items()
        ):
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
            raise SyntheticLabContractError(
                "Review Case Prompt model policies are not frozen alike"
            )
        object.__setattr__(self, "input_hash", canonical_hash(_review_task_value(self)))


@dataclass(frozen=True, kw_only=True)
class CorpusFinalizeTask:
    project_id: UUID
    job_id: UUID
    model_job_version: int
    requested_by: UUID
    corpus_version_id: UUID
    corpus_id: UUID
    version_number: int
    role: CorpusRole
    candidates: tuple[CorpusCandidateEntry, ...]
    candidate_text: Mapping[UUID, str]
    source_review_job_ids: tuple[UUID, ...]
    source_corpus_job_id: UUID | None
    runtime_inputs: RuntimeInputSnapshot
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_task_identity(self.project_id, self.job_id, self.model_job_version)
        for value, label in (
            (self.requested_by, "Corpus execution requester"),
            (self.corpus_version_id, "Corpus version"),
            (self.corpus_id, "Corpus identity"),
        ):
            _require_uuid(value, label)
        if self.version_number < 1:
            raise SyntheticLabContractError("Corpus version number must be positive")
        role = CorpusRole(self.role)
        object.__setattr__(self, "role", role)
        if role is CorpusRole.NO_CORPUS_BASELINE:
            raise SyntheticLabContractError(
                "no-corpus baseline is derived by Offline Experiment admission"
            )
        candidates = tuple(self.candidates)
        texts = dict(self.candidate_text)
        review_jobs = tuple(self.source_review_job_ids)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "candidate_text", MappingProxyType(texts))
        object.__setattr__(self, "source_review_job_ids", review_jobs)
        if not candidates or any(item.project_id != self.project_id for item in candidates):
            raise SyntheticLabContractError("Corpus task requires same-Project Candidates")
        candidate_ids = {item.candidate_id for item in candidates}
        if len(candidate_ids) != len(candidates) or set(texts) != candidate_ids:
            raise SyntheticLabContractError("Corpus Candidate text manifest is incomplete")
        if any(
            not text.strip()
            or len(text) > 100_000
            or canonical_hash(text) != item.candidate_output_hash
            for item in candidates
            for text in (texts[item.candidate_id],)
        ):
            raise SyntheticLabContractError("Corpus Candidate text changed or is invalid")
        if sum(len(value) for value in texts.values()) > 2_000_000:
            raise SyntheticLabContractError("Corpus Candidate text manifest is too large")
        if role is CorpusRole.NEW_CANDIDATE:
            if (
                not review_jobs
                or len(set(review_jobs)) != len(review_jobs)
                or self.source_corpus_job_id is not None
            ):
                raise SyntheticLabContractError(
                    "candidate Corpus requires unique Review Job lineage only"
                )
            for job_id in review_jobs:
                _require_uuid(job_id, "Corpus source Review Job")
        elif review_jobs or self.source_corpus_job_id is None:
            raise SyntheticLabContractError(
                "approved Corpus requires exactly one candidate Corpus source"
            )
        if self.source_corpus_job_id is not None:
            _require_uuid(self.source_corpus_job_id, "Corpus source Job")
        if self.runtime_inputs.project_id != self.project_id:
            raise SyntheticLabContractError("Corpus runtime crosses Project scope")
        object.__setattr__(self, "input_hash", canonical_hash(_corpus_task_value(self)))


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
    question_corpus_context: Mapping[tuple[UUID, UUID], str] = field(default_factory=dict)
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_task_identity(self.project_id, self.job_id, self.model_job_version)
        _require_uuid(self.requested_by, "Offline Experiment execution requester")
        _require_uuid(self.result_id, "Offline Experiment result")
        if self.plan.project_id != self.project_id:
            raise SyntheticLabContractError("Offline Experiment task crosses Project scope")
        questions = dict(self.question_text)
        corpora = dict(self.corpus_context)
        question_corpora = dict(self.question_corpus_context)
        if set(questions) != {item.question_version_id for item in self.plan.questions}:
            raise SyntheticLabContractError("Offline Experiment question material is incomplete")
        if set(corpora) != {item.id for item in self.plan.corpora}:
            raise SyntheticLabContractError("Offline Experiment Corpus material is incomplete")
        if any(not value.strip() for value in (*questions.values(), *corpora.values())):
            raise SyntheticLabContractError("Offline Experiment material cannot be empty")
        expected_contexts = {
            (corpus.id, question.question_version_id)
            for corpus in self.plan.corpora
            for question in self.plan.questions
        }
        if question_corpora and set(question_corpora) != expected_contexts:
            raise SyntheticLabContractError(
                "Offline Experiment Question/Corpus material is incomplete"
            )
        if any(not value.strip() or len(value) > 100_000 for value in question_corpora.values()):
            raise SyntheticLabContractError(
                "Offline Experiment Question/Corpus material is invalid"
            )
        object.__setattr__(self, "question_text", MappingProxyType(questions))
        object.__setattr__(self, "corpus_context", MappingProxyType(corpora))
        object.__setattr__(
            self,
            "question_corpus_context",
            MappingProxyType(question_corpora),
        )
        _validate_task_runtime(self.project_id, self.job_id, self.runtime_inputs, self.prompt)
        if self.prompt.program_kind is not ProgramKind.OFFLINE_ANSWER:
            raise SyntheticLabContractError(
                "Offline Experiment task requires the exact offline_answer Prompt"
            )
        object.__setattr__(self, "input_hash", canonical_hash(_offline_task_value(self)))


SyntheticExecutionTask: TypeAlias = (
    StyleProfileBuildTask | ReviewCaseRunTask | CorpusFinalizeTask | OfflineExperimentRunTask
)
SyntheticExecutionOutput: TypeAlias = (
    StyleProfileBuildOutput
    | ReviewCaseRunOutput
    | CorpusFinalizeOutput
    | OfflineExperimentRunOutput
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
        return tuple(
            task.prompts[kind] for kind in sorted(task.prompts, key=lambda item: item.value)
        )
    if isinstance(task, CorpusFinalizeTask):
        return ()
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
    "CorpusFinalizeOutput",
    "CorpusFinalizeTask",
    "ExecutionCheckpoint",
    "FrozenEvidence",
    "FrozenPromptRef",
    "OfflineExperimentRunOutput",
    "OfflineExperimentRunTask",
    "ResolvedSyntheticPrompt",
    "ReviewCaseRunOutput",
    "ReviewCaseRunTask",
    "StyleProfileBuildOutput",
    "StyleProfileBuildTask",
    "SyntheticExecutionError",
    "SyntheticExecutionOutput",
    "SyntheticExecutionRepositoryPort",
    "SyntheticExecutionTaskStagingPort",
    "SyntheticExecutionStale",
    "SyntheticExecutionTask",
    "SyntheticModelCallPort",
    "SyntheticModelInvocation",
    "SyntheticModelResult",
    "SyntheticPromptResolverPort",
    "prompt_refs",
]
