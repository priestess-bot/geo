"""Deterministic three-arm paired offline experiment contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from uuid import UUID

from geo_core.synthetic_lab.corpus import (
    CorpusRole,
    CorpusVersion,
)
from geo_core.synthetic_lab.domain import (
    SyntheticLabContractError,
    SyntheticLabScopeError,
    SyntheticOnly,
    _as_enum,
    _canonical_hash,
    _require_hash,
    _require_text,
    _require_uuid,
    assert_same_project,
    assert_synthetic_boundary,
)


DEFAULT_REPETITIONS_PER_QUESTION = 10
DEFAULT_MINIMUM_VALID_PAIR_RATIO = 0.8


class ExperimentArm(StrEnum):
    NO_CORPUS_BASELINE = "no_corpus_baseline"
    CURRENT_APPROVED_CORPUS = "current_approved_corpus"
    NEW_CANDIDATE_CORPUS = "new_candidate_corpus"


ARM_ROLE = {
    ExperimentArm.NO_CORPUS_BASELINE: CorpusRole.NO_CORPUS_BASELINE,
    ExperimentArm.CURRENT_APPROVED_CORPUS: CorpusRole.CURRENT_APPROVED,
    ExperimentArm.NEW_CANDIDATE_CORPUS: CorpusRole.NEW_CANDIDATE,
}


@dataclass(frozen=True, kw_only=True)
class FrozenExperimentQuestion(SyntheticOnly):
    project_id: UUID
    question_version_id: UUID
    ordinal: int
    question_hash: str
    question_cluster_key: str

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "experiment Question Project ID")
        _require_uuid(self.question_version_id, "experiment Question version ID")
        if self.ordinal < 1:
            raise SyntheticLabContractError("experiment Question ordinal must be positive")
        _require_hash(self.question_hash, "experiment Question hash")
        _require_text(self.question_cluster_key, "experiment Question cluster")


@dataclass(frozen=True, kw_only=True)
class OfflineExperimentPlan(SyntheticOnly):
    id: UUID
    project_id: UUID
    question_set_id: UUID
    question_set_hash: str
    question_manifest_hash: str
    protocol_id: UUID
    protocol_hash: str
    prompt_release_id: UUID
    prompt_release_hash: str
    approved_fact_snapshot_id: UUID
    approved_fact_snapshot_hash: str
    profile_version_id: UUID
    profile_hash: str
    model_policy_hash: str
    model_provider: str
    configured_model: str
    reported_model: str
    model_identity_hash: str
    metric_method_release: str
    metric_method_hash: str
    seed_namespace_hash: str
    repetitions_per_question: int
    minimum_valid_pair_ratio: float
    questions: tuple[FrozenExperimentQuestion, ...]
    corpora: tuple[CorpusVersion, ...]
    input_hash: str

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.id, "Offline Experiment ID"),
            (self.project_id, "Offline Experiment Project ID"),
            (self.question_set_id, "Offline Experiment QuestionSet ID"),
            (self.protocol_id, "Offline Experiment Protocol ID"),
            (self.prompt_release_id, "Offline Experiment Prompt Release ID"),
            (self.approved_fact_snapshot_id, "Offline Experiment Fact snapshot ID"),
            (self.profile_version_id, "Offline Experiment Profile version ID"),
        ):
            _require_uuid(uuid_value, label)
        for hash_value, label in (
            (self.question_set_hash, "Offline Experiment QuestionSet hash"),
            (self.question_manifest_hash, "Offline Experiment Question manifest hash"),
            (self.protocol_hash, "Offline Experiment Protocol hash"),
            (self.prompt_release_hash, "Offline Experiment Prompt Release hash"),
            (self.approved_fact_snapshot_hash, "Offline Experiment Fact snapshot hash"),
            (self.profile_hash, "Offline Experiment Profile hash"),
            (self.model_policy_hash, "Offline Experiment model policy hash"),
            (self.model_identity_hash, "Offline Experiment model identity hash"),
            (self.metric_method_hash, "Offline Experiment metric method hash"),
            (self.seed_namespace_hash, "Offline Experiment seed namespace hash"),
            (self.input_hash, "Offline Experiment input hash"),
        ):
            _require_hash(hash_value, label)
        for text_value, label in (
            (self.model_provider, "Offline Experiment model provider"),
            (self.configured_model, "Offline Experiment configured model"),
            (self.reported_model, "Offline Experiment reported model"),
            (self.metric_method_release, "Offline Experiment metric method release"),
        ):
            _require_text(text_value, label)
        if self.repetitions_per_question != DEFAULT_REPETITIONS_PER_QUESTION:
            raise SyntheticLabContractError(
                "Offline Experiment requires exactly 10 repetitions per Question and arm"
            )
        if not 0 < self.minimum_valid_pair_ratio <= 1:
            raise SyntheticLabContractError("minimum valid pair ratio must be in (0, 1]")
        questions = tuple(self.questions)
        corpora = tuple(self.corpora)
        object.__setattr__(self, "questions", questions)
        object.__setattr__(self, "corpora", corpora)
        if not questions:
            raise SyntheticLabContractError("Offline Experiment requires frozen Questions")
        if len({item.question_version_id for item in questions}) != len(questions):
            raise SyntheticLabContractError("Offline Experiment Questions must be unique")
        if {item.ordinal for item in questions} != set(range(1, len(questions) + 1)):
            raise SyntheticLabContractError(
                "Offline Experiment Question ordinals must be contiguous from 1"
            )
        if len(corpora) != 3 or {item.role for item in corpora} != set(CorpusRole):
            raise SyntheticLabContractError(
                "Offline Experiment requires baseline, current-approved and candidate Corpora"
            )
        assert_same_project(self, *questions, *corpora)
        assert_synthetic_boundary(self, *questions, *corpora)
        if question_manifest_hash(questions) != self.question_manifest_hash:
            raise SyntheticLabContractError(
                "Offline Experiment Questions do not match their manifest hash"
            )
        if any(
            corpus.approved_fact_snapshot_id != self.approved_fact_snapshot_id
            or corpus.approved_fact_snapshot_hash != self.approved_fact_snapshot_hash
            or corpus.profile_version_id != self.profile_version_id
            or corpus.profile_hash != self.profile_hash
            for corpus in corpora
        ):
            raise SyntheticLabScopeError(
                "three experiment Corpora must share the frozen Fact/Profile context"
            )
        expected_hash = offline_experiment_input_hash(self)
        if self.input_hash != expected_hash:
            raise SyntheticLabContractError(
                "Offline Experiment inputs do not match their frozen hash"
            )


@dataclass(frozen=True, kw_only=True)
class PlannedExperimentSlot(SyntheticOnly):
    project_id: UUID
    experiment_id: UUID
    experiment_input_hash: str
    pair_id: str
    slot_id: str
    question_version_id: UUID
    question_hash: str
    question_cluster_key: str
    repetition: int
    arm: ExperimentArm
    corpus_version_id: UUID
    corpus_hash: str
    deterministic_seed: int
    input_hash: str

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.project_id, "slot Project ID"),
            (self.experiment_id, "slot Experiment ID"),
            (self.question_version_id, "slot Question version ID"),
            (self.corpus_version_id, "slot Corpus Version ID"),
        ):
            _require_uuid(uuid_value, label)
        for hash_value, label in (
            (self.experiment_input_hash, "slot Experiment input hash"),
            (self.pair_id, "paired slot identity"),
            (self.slot_id, "planned slot identity"),
            (self.question_hash, "slot Question hash"),
            (self.corpus_hash, "slot Corpus hash"),
            (self.input_hash, "planned slot input hash"),
        ):
            _require_hash(hash_value, label)
        _require_text(self.question_cluster_key, "slot Question cluster")
        object.__setattr__(self, "arm", _as_enum(self.arm, ExperimentArm, "experiment arm"))
        if not 1 <= self.repetition <= DEFAULT_REPETITIONS_PER_QUESTION:
            raise SyntheticLabContractError("slot repetition must be between 1 and 10")
        if not 0 <= self.deterministic_seed < 2**64:
            raise SyntheticLabContractError("deterministic seed must be an unsigned 64-bit value")


@dataclass(frozen=True, kw_only=True)
class OfflineSlotResult(SyntheticOnly):
    project_id: UUID
    experiment_id: UUID
    slot_id: str
    pair_id: str
    arm: ExperimentArm
    input_hash: str
    valid: bool
    metric_value: float | None
    model_call_id: UUID | None
    request_hash: str | None
    response_hash: str | None
    answer_hash: str | None
    citation_hash: str | None
    invalid_reason: str | None
    result_hash: str

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "slot result Project ID")
        _require_uuid(self.experiment_id, "slot result Experiment ID")
        for hash_value, label in (
            (self.slot_id, "slot result identity"),
            (self.pair_id, "slot result pair identity"),
            (self.input_hash, "slot result input hash"),
            (self.result_hash, "slot result hash"),
        ):
            _require_hash(hash_value, label)
        arm = _as_enum(self.arm, ExperimentArm, "slot result arm")
        object.__setattr__(self, "arm", arm)
        evidence = (
            self.model_call_id,
            self.request_hash,
            self.response_hash,
            self.answer_hash,
            self.citation_hash,
        )
        if self.valid:
            if self.metric_value is None or not math.isfinite(self.metric_value):
                raise SyntheticLabContractError("valid slot result requires a finite metric")
            if any(value is None for value in evidence):
                raise SyntheticLabContractError(
                    "valid slot result requires complete model-call and artifact hashes"
                )
            _require_uuid(self.model_call_id, "slot result model call ID")  # type: ignore[arg-type]
            for value in evidence[1:]:
                _require_hash(value, "slot result evidence hash")  # type: ignore[arg-type]
            if self.invalid_reason is not None:
                raise SyntheticLabContractError("valid slot result cannot carry invalid reason")
        else:
            if self.metric_value is not None or any(value is not None for value in evidence):
                raise SyntheticLabContractError(
                    "invalid slot result cannot enter model output or metric denominators"
                )
            _require_text(self.invalid_reason or "", "slot invalid reason")
        if self.result_hash != slot_result_hash(
            slot_id=self.slot_id,
            pair_id=self.pair_id,
            arm=arm,
            input_hash=self.input_hash,
            valid=self.valid,
            metric_value=self.metric_value,
            model_call_id=self.model_call_id,
            request_hash=self.request_hash,
            response_hash=self.response_hash,
            answer_hash=self.answer_hash,
            citation_hash=self.citation_hash,
            invalid_reason=self.invalid_reason,
        ):
            raise SyntheticLabContractError("slot result does not match its deterministic hash")


def question_manifest_hash(questions: tuple[FrozenExperimentQuestion, ...]) -> str:
    return _canonical_hash(
        [
            {
                "question_version_id": str(item.question_version_id),
                "ordinal": item.ordinal,
                "question_hash": item.question_hash,
                "question_cluster_key": item.question_cluster_key,
            }
            for item in sorted(questions, key=lambda value: value.ordinal)
        ]
    )


def offline_experiment_input_hash(plan: OfflineExperimentPlan) -> str:
    return _offline_experiment_input_hash_values(
        project_id=plan.project_id,
        question_set_id=plan.question_set_id,
        question_set_hash=plan.question_set_hash,
        question_manifest_hash=plan.question_manifest_hash,
        protocol_id=plan.protocol_id,
        protocol_hash=plan.protocol_hash,
        prompt_release_id=plan.prompt_release_id,
        prompt_release_hash=plan.prompt_release_hash,
        approved_fact_snapshot_id=plan.approved_fact_snapshot_id,
        approved_fact_snapshot_hash=plan.approved_fact_snapshot_hash,
        profile_version_id=plan.profile_version_id,
        profile_hash=plan.profile_hash,
        model_policy_hash=plan.model_policy_hash,
        model_provider=plan.model_provider,
        configured_model=plan.configured_model,
        reported_model=plan.reported_model,
        model_identity_hash=plan.model_identity_hash,
        metric_method_release=plan.metric_method_release,
        metric_method_hash=plan.metric_method_hash,
        seed_namespace_hash=plan.seed_namespace_hash,
        repetitions_per_question=plan.repetitions_per_question,
        minimum_valid_pair_ratio=plan.minimum_valid_pair_ratio,
        corpora=plan.corpora,
    )


def create_offline_experiment_plan(
    *,
    id: UUID,
    project_id: UUID,
    question_set_id: UUID,
    question_set_hash: str,
    protocol_id: UUID,
    protocol_hash: str,
    prompt_release_id: UUID,
    prompt_release_hash: str,
    approved_fact_snapshot_id: UUID,
    approved_fact_snapshot_hash: str,
    profile_version_id: UUID,
    profile_hash: str,
    model_policy_hash: str,
    model_provider: str,
    configured_model: str,
    reported_model: str,
    model_identity_hash: str,
    metric_method_release: str,
    metric_method_hash: str,
    seed_namespace_hash: str,
    questions: tuple[FrozenExperimentQuestion, ...],
    corpora: tuple[CorpusVersion, ...],
    repetitions_per_question: int = DEFAULT_REPETITIONS_PER_QUESTION,
    minimum_valid_pair_ratio: float = DEFAULT_MINIMUM_VALID_PAIR_RATIO,
) -> OfflineExperimentPlan:
    manifest_hash = question_manifest_hash(questions)
    input_hash = _offline_experiment_input_hash_values(
        project_id=project_id,
        question_set_id=question_set_id,
        question_set_hash=question_set_hash,
        question_manifest_hash=manifest_hash,
        protocol_id=protocol_id,
        protocol_hash=protocol_hash,
        prompt_release_id=prompt_release_id,
        prompt_release_hash=prompt_release_hash,
        approved_fact_snapshot_id=approved_fact_snapshot_id,
        approved_fact_snapshot_hash=approved_fact_snapshot_hash,
        profile_version_id=profile_version_id,
        profile_hash=profile_hash,
        model_policy_hash=model_policy_hash,
        model_provider=model_provider,
        configured_model=configured_model,
        reported_model=reported_model,
        model_identity_hash=model_identity_hash,
        metric_method_release=metric_method_release,
        metric_method_hash=metric_method_hash,
        seed_namespace_hash=seed_namespace_hash,
        repetitions_per_question=repetitions_per_question,
        minimum_valid_pair_ratio=minimum_valid_pair_ratio,
        corpora=corpora,
    )
    return OfflineExperimentPlan(
        id=id,
        project_id=project_id,
        question_set_id=question_set_id,
        question_set_hash=question_set_hash,
        question_manifest_hash=manifest_hash,
        protocol_id=protocol_id,
        protocol_hash=protocol_hash,
        prompt_release_id=prompt_release_id,
        prompt_release_hash=prompt_release_hash,
        approved_fact_snapshot_id=approved_fact_snapshot_id,
        approved_fact_snapshot_hash=approved_fact_snapshot_hash,
        profile_version_id=profile_version_id,
        profile_hash=profile_hash,
        model_policy_hash=model_policy_hash,
        model_provider=model_provider,
        configured_model=configured_model,
        reported_model=reported_model,
        model_identity_hash=model_identity_hash,
        metric_method_release=metric_method_release,
        metric_method_hash=metric_method_hash,
        seed_namespace_hash=seed_namespace_hash,
        repetitions_per_question=repetitions_per_question,
        minimum_valid_pair_ratio=minimum_valid_pair_ratio,
        questions=questions,
        corpora=corpora,
        input_hash=input_hash,
    )


def _offline_experiment_input_hash_values(
    *,
    project_id: UUID,
    question_set_id: UUID,
    question_set_hash: str,
    question_manifest_hash: str,
    protocol_id: UUID,
    protocol_hash: str,
    prompt_release_id: UUID,
    prompt_release_hash: str,
    approved_fact_snapshot_id: UUID,
    approved_fact_snapshot_hash: str,
    profile_version_id: UUID,
    profile_hash: str,
    model_policy_hash: str,
    model_provider: str,
    configured_model: str,
    reported_model: str,
    model_identity_hash: str,
    metric_method_release: str,
    metric_method_hash: str,
    seed_namespace_hash: str,
    repetitions_per_question: int,
    minimum_valid_pair_ratio: float,
    corpora: tuple[CorpusVersion, ...],
) -> str:
    return _canonical_hash(
        {
            "project_id": str(project_id),
            "question_set_id": str(question_set_id),
            "question_set_hash": question_set_hash,
            "question_manifest_hash": question_manifest_hash,
            "protocol_id": str(protocol_id),
            "protocol_hash": protocol_hash,
            "prompt_release_id": str(prompt_release_id),
            "prompt_release_hash": prompt_release_hash,
            "approved_fact_snapshot_id": str(approved_fact_snapshot_id),
            "approved_fact_snapshot_hash": approved_fact_snapshot_hash,
            "profile_version_id": str(profile_version_id),
            "profile_hash": profile_hash,
            "model_policy_hash": model_policy_hash,
            "model_provider": model_provider,
            "configured_model": configured_model,
            "reported_model": reported_model,
            "model_identity_hash": model_identity_hash,
            "metric_method_release": metric_method_release,
            "metric_method_hash": metric_method_hash,
            "seed_namespace_hash": seed_namespace_hash,
            "repetitions_per_question": repetitions_per_question,
            "minimum_valid_pair_ratio": minimum_valid_pair_ratio,
            "corpora": [
                {
                    "role": item.role.value,
                    "id": str(item.id),
                    "version": item.version_number,
                    "hash": item.content_hash,
                }
                for item in sorted(corpora, key=lambda value: value.role.value)
            ],
        }
    )


def planned_experiment_slots(plan: OfflineExperimentPlan) -> tuple[PlannedExperimentSlot, ...]:
    corpora = {item.role: item for item in plan.corpora}
    slots: list[PlannedExperimentSlot] = []
    for question in sorted(plan.questions, key=lambda item: item.ordinal):
        for repetition in range(1, plan.repetitions_per_question + 1):
            pair_id = _canonical_hash(
                {
                    "experiment_input_hash": plan.input_hash,
                    "question_version_id": str(question.question_version_id),
                    "question_hash": question.question_hash,
                    "repetition": repetition,
                }
            )
            seed = int(pair_id[:16], 16)
            for arm in ExperimentArm:
                corpus = corpora[ARM_ROLE[arm]]
                slot_id = _canonical_hash(
                    {"pair_id": pair_id, "arm": arm.value, "corpus_hash": corpus.content_hash}
                )
                input_hash = _canonical_hash(
                    {
                        "experiment_input_hash": plan.input_hash,
                        "pair_id": pair_id,
                        "arm": arm.value,
                        "corpus_hash": corpus.content_hash,
                        "seed": seed,
                    }
                )
                slots.append(
                    PlannedExperimentSlot(
                        project_id=plan.project_id,
                        experiment_id=plan.id,
                        experiment_input_hash=plan.input_hash,
                        pair_id=pair_id,
                        slot_id=slot_id,
                        question_version_id=question.question_version_id,
                        question_hash=question.question_hash,
                        question_cluster_key=question.question_cluster_key,
                        repetition=repetition,
                        arm=arm,
                        corpus_version_id=corpus.id,
                        corpus_hash=corpus.content_hash,
                        deterministic_seed=seed,
                        input_hash=input_hash,
                    )
                )
    return tuple(slots)


def make_slot_result(
    slot: PlannedExperimentSlot,
    *,
    valid: bool,
    metric_value: float | None = None,
    model_call_id: UUID | None = None,
    request_hash: str | None = None,
    response_hash: str | None = None,
    answer_hash: str | None = None,
    citation_hash: str | None = None,
    invalid_reason: str | None = None,
) -> OfflineSlotResult:
    result_hash = slot_result_hash(
        slot_id=slot.slot_id,
        pair_id=slot.pair_id,
        arm=slot.arm,
        input_hash=slot.input_hash,
        valid=valid,
        metric_value=metric_value,
        model_call_id=model_call_id,
        request_hash=request_hash,
        response_hash=response_hash,
        answer_hash=answer_hash,
        citation_hash=citation_hash,
        invalid_reason=invalid_reason,
    )
    return OfflineSlotResult(
        project_id=slot.project_id,
        experiment_id=slot.experiment_id,
        slot_id=slot.slot_id,
        pair_id=slot.pair_id,
        arm=slot.arm,
        input_hash=slot.input_hash,
        valid=valid,
        metric_value=metric_value,
        model_call_id=model_call_id,
        request_hash=request_hash,
        response_hash=response_hash,
        answer_hash=answer_hash,
        citation_hash=citation_hash,
        invalid_reason=invalid_reason,
        result_hash=result_hash,
    )


def slot_result_hash(**values: object) -> str:
    payload = dict(values)
    arm = payload.get("arm")
    if isinstance(arm, ExperimentArm):
        payload["arm"] = arm.value
    call_id = payload.get("model_call_id")
    if isinstance(call_id, UUID):
        payload["model_call_id"] = str(call_id)
    return _canonical_hash(payload)


__all__ = [
    "DEFAULT_MINIMUM_VALID_PAIR_RATIO",
    "DEFAULT_REPETITIONS_PER_QUESTION",
    "ExperimentArm",
    "FrozenExperimentQuestion",
    "OfflineExperimentPlan",
    "OfflineSlotResult",
    "PlannedExperimentSlot",
    "create_offline_experiment_plan",
    "make_slot_result",
    "offline_experiment_input_hash",
    "planned_experiment_slots",
    "question_manifest_hash",
    "slot_result_hash",
]
