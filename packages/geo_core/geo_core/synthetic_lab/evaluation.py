"""Fact, subject and style evaluation rules for synthetic Candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from geo_core.synthetic_lab.domain import (
    SyntheticLabContractError,
    SyntheticLabScopeError,
    SyntheticOnly,
    _as_enum,
    _require_hash,
    _require_text,
    _require_uuid,
    assert_same_project,
    assert_synthetic_boundary,
)
from geo_core.synthetic_lab.generation import (
    FrozenExecutionLineage,
    GenerationBatch,
    assert_same_frozen_context,
)


class FactStatus(StrEnum):
    CURRENT_APPROVED = "current_approved"
    DERIVED_OR_UNKNOWN = "derived_or_unknown"
    EXPLICIT_CONFLICT = "explicit_conflict"
    SUBJECT_MIXUP = "subject_mixup"


class EvaluationDisposition(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    REVISE = "revise"


class CandidateOutput(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def project_id(self) -> UUID: ...

    @property
    def review_run_id(self) -> UUID: ...

    @property
    def review_case_id(self) -> UUID: ...

    @property
    def generation_batch_id(self) -> UUID: ...

    @property
    def batch_number(self) -> int: ...

    @property
    def output_hash(self) -> str: ...


@dataclass(frozen=True, kw_only=True)
class ClaimAssessment(SyntheticOnly):
    claim_hash: str
    status: FactStatus
    fact_id: UUID | None = None
    fact_hash: str | None = None
    expected_subject_id: UUID | None = None
    observed_subject_id: UUID | None = None
    output_annotation: str | None = None

    def __post_init__(self) -> None:
        _require_hash(self.claim_hash, "claim hash")
        status = _as_enum(self.status, FactStatus, "Fact status")
        object.__setattr__(self, "status", status)
        fact_bound = self.fact_id is not None or self.fact_hash is not None
        if fact_bound:
            if self.fact_id is None or self.fact_hash is None:
                raise SyntheticLabContractError("Fact assessment must bind both Fact ID and hash")
            _require_uuid(self.fact_id, "assessment Fact ID")
            _require_hash(self.fact_hash, "assessment Fact hash")
        if status in {FactStatus.CURRENT_APPROVED, FactStatus.EXPLICIT_CONFLICT}:
            if not fact_bound:
                raise SyntheticLabContractError(
                    f"{status.value} assessment requires frozen Fact lineage"
                )
        if status == FactStatus.DERIVED_OR_UNKNOWN:
            if fact_bound:
                raise SyntheticLabContractError(
                    "derived_or_unknown assessment cannot invent a Fact binding"
                )
            if self.output_annotation != FactStatus.DERIVED_OR_UNKNOWN.value:
                raise SyntheticLabContractError(
                    "derived_or_unknown output must retain its explicit annotation"
                )
        elif self.output_annotation is not None:
            raise SyntheticLabContractError(
                "only derived_or_unknown assessments carry an output annotation"
            )
        if status == FactStatus.SUBJECT_MIXUP:
            if self.expected_subject_id is None or self.observed_subject_id is None:
                raise SyntheticLabContractError(
                    "subject_mixup requires expected and observed subject identities"
                )
            _require_uuid(self.expected_subject_id, "expected subject ID")
            _require_uuid(self.observed_subject_id, "observed subject ID")
            if self.expected_subject_id == self.observed_subject_id:
                raise SyntheticLabContractError("subject_mixup identities must actually differ")
        elif self.expected_subject_id is not None or self.observed_subject_id is not None:
            raise SyntheticLabContractError("subject identities are only valid for subject_mixup")


@dataclass(frozen=True, kw_only=True)
class CandidateEvaluation(SyntheticOnly):
    id: UUID
    project_id: UUID
    review_run_id: UUID
    review_case_id: UUID
    generation_batch_id: UUID
    candidate_id: UUID
    candidate_output_hash: str
    call_lineage: FrozenExecutionLineage
    evaluator_release: str
    evaluator_hash: str
    evidence_artifact_hash: str
    claim_assessments: tuple[ClaimAssessment, ...]
    style_score: float
    style_passed: bool
    correctable_issue_codes: tuple[str, ...] = ()
    soft_issue_codes: tuple[str, ...] = ()
    disposition: EvaluationDisposition = field(init=False)
    warning_codes: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.id, "Evaluation ID"),
            (self.project_id, "Evaluation Project ID"),
            (self.review_run_id, "Evaluation Review Run ID"),
            (self.review_case_id, "Evaluation Review Case ID"),
            (self.generation_batch_id, "Evaluation Generation Batch ID"),
            (self.candidate_id, "Evaluation Candidate ID"),
        ):
            _require_uuid(uuid_value, label)
        for hash_value, label in (
            (self.candidate_output_hash, "evaluated Candidate output hash"),
            (self.evaluator_hash, "evaluator release hash"),
            (self.evidence_artifact_hash, "Evaluation evidence artifact hash"),
        ):
            _require_hash(hash_value, label)
        _require_text(self.evaluator_release, "evaluator release")
        if not 0 <= self.style_score <= 5:
            raise SyntheticLabContractError("style score must be between 0 and 5")
        assessments = tuple(self.claim_assessments)
        correctable = _validated_codes(
            self.correctable_issue_codes,
            label="correctable issue",
        )
        soft = _validated_codes(self.soft_issue_codes, label="soft issue")
        object.__setattr__(self, "claim_assessments", assessments)
        object.__setattr__(self, "correctable_issue_codes", correctable)
        object.__setattr__(self, "soft_issue_codes", soft)
        if set(correctable).intersection(soft):
            raise SyntheticLabContractError(
                "an Evaluation issue cannot be both correctable and soft"
            )
        if not self.style_passed and not correctable:
            raise SyntheticLabContractError(
                "failed style evaluation requires a correctable issue code"
            )
        assert_same_project(self, self.call_lineage)
        assert_synthetic_boundary(self, self.call_lineage, *assessments)
        if self.call_lineage.program_kind not in {
            "claim_extraction",
            "conflict_check",
            "style_judge",
            "arbiter",
        }:
            raise SyntheticLabContractError(
                "Evaluation requires a claim/conflict/style/arbiter Prompt call"
            )
        if (
            self.call_lineage.review_run_id != self.review_run_id
            or self.call_lineage.review_case_id != self.review_case_id
        ):
            raise SyntheticLabScopeError(
                "Evaluation and model call do not share Review Run/Case lineage"
            )
        fact_statuses = {assessment.status for assessment in assessments}
        requires_revision = bool(
            fact_statuses.intersection({FactStatus.EXPLICIT_CONFLICT, FactStatus.SUBJECT_MIXUP})
            or correctable
            or not self.style_passed
        )
        warning_codes = list(soft)
        if FactStatus.DERIVED_OR_UNKNOWN in fact_statuses:
            warning_codes.append(FactStatus.DERIVED_OR_UNKNOWN.value)
        warnings = tuple(sorted(set(warning_codes)))
        if requires_revision:
            disposition = EvaluationDisposition.REVISE
            warnings = ()
        elif warnings:
            disposition = EvaluationDisposition.WARNING
        else:
            disposition = EvaluationDisposition.PASS
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "warning_codes", warnings)

    @property
    def output_allowed(self) -> bool:
        """Warnings are valid outputs; revision-required Candidates are not."""

        return self.disposition in {
            EvaluationDisposition.PASS,
            EvaluationDisposition.WARNING,
        }


def _validated_codes(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    codes = tuple(values)
    if len(codes) != len(set(codes)) or any(not code.strip() for code in codes):
        raise SyntheticLabContractError(f"{label} codes must be unique non-empty values")
    return codes


def assert_evaluation_for_candidate(
    batch: GenerationBatch,
    candidate: CandidateOutput,
    evaluation: CandidateEvaluation,
) -> None:
    assert_same_project(batch, candidate, evaluation)
    assert_synthetic_boundary(batch, evaluation)
    if (
        candidate.id != evaluation.candidate_id
        or candidate.output_hash != evaluation.candidate_output_hash
        or candidate.review_run_id != evaluation.review_run_id
        or candidate.review_case_id != evaluation.review_case_id
        or candidate.generation_batch_id != evaluation.generation_batch_id
        or batch.id != evaluation.generation_batch_id
        or batch.review_run_id != evaluation.review_run_id
        or batch.review_case_id != evaluation.review_case_id
    ):
        raise SyntheticLabScopeError("Evaluation does not match the frozen Candidate/Batch lineage")
    assert_same_frozen_context(batch.call_lineage, evaluation.call_lineage)


__all__ = [
    "CandidateEvaluation",
    "CandidateOutput",
    "ClaimAssessment",
    "EvaluationDisposition",
    "FactStatus",
    "assert_evaluation_for_candidate",
]
