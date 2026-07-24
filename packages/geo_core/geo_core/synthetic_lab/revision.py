"""Two-round revision, one-regeneration and terminal result contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from collections.abc import Iterable
from typing import Mapping
from uuid import UUID

from geo_core.synthetic_lab.domain import (
    SyntheticLabContractError,
    SyntheticLabScopeError,
    SyntheticOnly,
    _as_enum,
    _canonical_hash,
    _require_channel,
    _require_hash,
    _require_text,
    _require_uuid,
    assert_same_project,
    assert_synthetic_boundary,
)
from geo_core.synthetic_lab.evaluation import (
    CandidateEvaluation,
    CandidateOutput,
    EvaluationDisposition,
    assert_evaluation_for_candidate,
)
from geo_core.synthetic_lab.generation import (
    FrozenCallLineage,
    GeneratedCandidate,
    GenerationBatch,
    GenerationBatchKind,
    assert_same_frozen_context,
)
from geo_core.synthetic_lab.review_cases import ScenarioMode


MAX_REVISION_ROUNDS = 2


class ReviewRunStatus(StrEnum):
    PASSED = "passed"
    COMPLETED_WITH_WARNING = "completed_with_warning"
    FAILED = "failed"


class WorkflowAction(StrEnum):
    COMPLETE = "complete"
    REVISE = "revise"
    REGENERATE = "regenerate"
    FAIL = "fail"


@dataclass(frozen=True, kw_only=True)
class RevisedCandidate(SyntheticOnly):
    id: UUID
    project_id: UUID
    review_run_id: UUID
    review_case_id: UUID
    generation_batch_id: UUID
    batch_number: int
    revision_id: UUID
    revision_round: int
    parent_candidate_id: UUID
    parent_output_hash: str
    output_hash: str
    artifact_hash: str

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.id, "revised Candidate ID"),
            (self.project_id, "revised Candidate Project ID"),
            (self.review_run_id, "revised Candidate Review Run ID"),
            (self.review_case_id, "revised Candidate Review Case ID"),
            (self.generation_batch_id, "revised Candidate Generation Batch ID"),
            (self.revision_id, "Revision ID"),
            (self.parent_candidate_id, "parent Candidate ID"),
        ):
            _require_uuid(uuid_value, label)
        if self.batch_number != 1:
            raise SyntheticLabContractError(
                "regenerated Candidates cannot enter another revision cycle"
            )
        if not 1 <= self.revision_round <= MAX_REVISION_ROUNDS:
            raise SyntheticLabContractError("Revision round must be 1 or 2")
        for hash_value, label in (
            (self.parent_output_hash, "parent Candidate output hash"),
            (self.output_hash, "revised Candidate output hash"),
            (self.artifact_hash, "revised Candidate artifact hash"),
        ):
            _require_hash(hash_value, label)
        if self.output_hash == self.parent_output_hash:
            raise SyntheticLabContractError("Revision must change the Candidate output")


@dataclass(frozen=True, kw_only=True)
class CandidateRevision(SyntheticOnly):
    id: UUID
    project_id: UUID
    review_run_id: UUID
    review_case_id: UUID
    generation_batch_id: UUID
    round_number: int
    parent_candidate_id: UUID
    parent_output_hash: str
    issue_codes: tuple[str, ...]
    issue_set_hash: str
    call_lineage: FrozenCallLineage
    revised_candidate: RevisedCandidate

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "Revision ID"),
            (self.project_id, "Revision Project ID"),
            (self.review_run_id, "Revision Review Run ID"),
            (self.review_case_id, "Revision Review Case ID"),
            (self.generation_batch_id, "Revision Generation Batch ID"),
            (self.parent_candidate_id, "Revision parent Candidate ID"),
        ):
            _require_uuid(value, label)
        if not 1 <= self.round_number <= MAX_REVISION_ROUNDS:
            raise SyntheticLabContractError("Revision round must be 1 or 2")
        _require_hash(self.parent_output_hash, "Revision parent output hash")
        _require_hash(self.issue_set_hash, "Revision issue-set hash")
        issues = tuple(self.issue_codes)
        object.__setattr__(self, "issue_codes", issues)
        if (
            not issues
            or len(issues) != len(set(issues))
            or any(not issue.strip() for issue in issues)
        ):
            raise SyntheticLabContractError("Revision issue codes must be unique non-empty values")
        if self.issue_set_hash != revision_issue_set_hash(issues):
            raise SyntheticLabContractError("Revision issues do not match their frozen hash")
        assert_same_project(self, self.call_lineage, self.revised_candidate)
        assert_synthetic_boundary(self, self.call_lineage, self.revised_candidate)
        if self.call_lineage.program_kind != "revision":
            raise SyntheticLabContractError("Revision requires a revision Prompt call")
        if (
            self.call_lineage.review_run_id != self.review_run_id
            or self.call_lineage.review_case_id != self.review_case_id
        ):
            raise SyntheticLabScopeError(
                "Revision and model call do not share Review Run/Case lineage"
            )
        revised = self.revised_candidate
        if (
            revised.revision_id != self.id
            or revised.revision_round != self.round_number
            or revised.parent_candidate_id != self.parent_candidate_id
            or revised.parent_output_hash != self.parent_output_hash
            or revised.review_run_id != self.review_run_id
            or revised.review_case_id != self.review_case_id
            or revised.generation_batch_id != self.generation_batch_id
        ):
            raise SyntheticLabScopeError(
                "revised Candidate does not match its immutable Revision lineage"
            )


@dataclass(frozen=True, kw_only=True)
class WorkflowDecision(SyntheticOnly):
    project_id: UUID
    review_run_id: UUID
    review_case_id: UUID
    candidate_id: UUID
    action: WorkflowAction
    next_revision_round: int | None = None
    final_status: ReviewRunStatus | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.project_id, "workflow Project ID"),
            (self.review_run_id, "workflow Review Run ID"),
            (self.review_case_id, "workflow Review Case ID"),
            (self.candidate_id, "workflow Candidate ID"),
        ):
            _require_uuid(value, label)
        action = _as_enum(self.action, WorkflowAction, "workflow action")
        object.__setattr__(self, "action", action)
        if self.final_status is not None:
            object.__setattr__(
                self,
                "final_status",
                _as_enum(self.final_status, ReviewRunStatus, "Review Run status"),
            )
        if action == WorkflowAction.REVISE:
            if self.next_revision_round not in {1, 2} or self.final_status is not None:
                raise SyntheticLabContractError(
                    "revise decision requires the next round and no final status"
                )
        elif action == WorkflowAction.REGENERATE:
            if self.next_revision_round is not None or self.final_status is not None:
                raise SyntheticLabContractError(
                    "regenerate decision cannot carry revision or final status"
                )
        elif self.next_revision_round is not None or self.final_status is None:
            raise SyntheticLabContractError(
                "terminal workflow decision requires only a final status"
            )
        elif action == WorkflowAction.COMPLETE and self.final_status not in {
            ReviewRunStatus.PASSED,
            ReviewRunStatus.COMPLETED_WITH_WARNING,
        }:
            raise SyntheticLabContractError("complete decision requires pass or warning")
        elif action == WorkflowAction.FAIL and self.final_status != ReviewRunStatus.FAILED:
            raise SyntheticLabContractError("fail decision requires failed status")


@dataclass(frozen=True, kw_only=True)
class CandidateResolution(SyntheticOnly):
    id: UUID
    project_id: UUID
    review_run_id: UUID
    review_case_id: UUID
    candidate_id: UUID
    candidate_output_hash: str
    evaluation_id: UUID
    evaluation_evidence_hash: str
    channel: str
    scenario_mode: ScenarioMode
    status: ReviewRunStatus
    warning_codes: tuple[str, ...] = ()
    failure_code: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "Candidate Resolution ID"),
            (self.project_id, "Candidate Resolution Project ID"),
            (self.review_run_id, "Candidate Resolution Review Run ID"),
            (self.review_case_id, "Candidate Resolution Review Case ID"),
            (self.candidate_id, "Candidate Resolution Candidate ID"),
            (self.evaluation_id, "Candidate Resolution Evaluation ID"),
        ):
            _require_uuid(value, label)
        _require_hash(self.candidate_output_hash, "resolved Candidate output hash")
        _require_hash(self.evaluation_evidence_hash, "resolved Evaluation evidence hash")
        _require_channel(self.channel)
        mode = _as_enum(self.scenario_mode, ScenarioMode, "resolution scenario mode")
        status = _as_enum(self.status, ReviewRunStatus, "Candidate Resolution status")
        object.__setattr__(self, "scenario_mode", mode)
        object.__setattr__(self, "status", status)
        warnings = tuple(self.warning_codes)
        object.__setattr__(self, "warning_codes", warnings)
        if len(warnings) != len(set(warnings)) or any(not code.strip() for code in warnings):
            raise SyntheticLabContractError(
                "Candidate Resolution warning codes must be unique non-empty values"
            )
        if status == ReviewRunStatus.PASSED:
            if warnings or self.failure_code is not None:
                raise SyntheticLabContractError("passed Candidate cannot carry warning/failure")
        elif status == ReviewRunStatus.COMPLETED_WITH_WARNING:
            if not warnings or self.failure_code is not None:
                raise SyntheticLabContractError(
                    "warning Candidate requires warnings and no failure"
                )
        else:
            if warnings:
                raise SyntheticLabContractError("failed Candidate cannot carry warnings")
            _require_text(self.failure_code or "", "Candidate failure code")

    @property
    def offline_experiment_eligible(self) -> bool:
        return self.status in {
            ReviewRunStatus.PASSED,
            ReviewRunStatus.COMPLETED_WITH_WARNING,
        }

    @property
    def included_in_overall_metrics(self) -> bool:
        return self.offline_experiment_eligible


@dataclass(frozen=True, kw_only=True)
class ReviewRunResult(SyntheticOnly):
    id: UUID
    project_id: UUID
    review_run_id: UUID
    resolutions: tuple[CandidateResolution, ...]
    status: ReviewRunStatus = field(init=False)
    total_count: int = field(init=False)
    passed_count: int = field(init=False)
    warning_count: int = field(init=False)
    failed_count: int = field(init=False)
    offline_eligible_count: int = field(init=False)
    warning_ratio: float = field(init=False)
    warning_by_code: Mapping[str, int] = field(init=False)
    warning_by_channel: Mapping[str, int] = field(init=False)
    warning_by_scenario_mode: Mapping[str, int] = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid(self.id, "Review Run Result ID")
        _require_uuid(self.project_id, "Review Run Result Project ID")
        _require_uuid(self.review_run_id, "Review Run Result Review Run ID")
        resolutions = tuple(self.resolutions)
        object.__setattr__(self, "resolutions", resolutions)
        if not resolutions:
            raise SyntheticLabContractError("Review Run Result requires Candidate resolutions")
        assert_same_project(self, *resolutions)
        assert_synthetic_boundary(self, *resolutions)
        if any(resolution.review_run_id != self.review_run_id for resolution in resolutions):
            raise SyntheticLabScopeError("Resolution belongs to a different Review Run")
        if len({resolution.review_case_id for resolution in resolutions}) != len(resolutions):
            raise SyntheticLabContractError(
                "Review Run Result requires one selected Resolution per Case"
            )
        passed = sum(item.status == ReviewRunStatus.PASSED for item in resolutions)
        warning_items = tuple(
            item for item in resolutions if item.status == ReviewRunStatus.COMPLETED_WITH_WARNING
        )
        failed = sum(item.status == ReviewRunStatus.FAILED for item in resolutions)
        status = (
            ReviewRunStatus.FAILED
            if failed
            else ReviewRunStatus.COMPLETED_WITH_WARNING
            if warning_items
            else ReviewRunStatus.PASSED
        )
        warning_count = len(warning_items)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "total_count", len(resolutions))
        object.__setattr__(self, "passed_count", passed)
        object.__setattr__(self, "warning_count", warning_count)
        object.__setattr__(self, "failed_count", failed)
        object.__setattr__(self, "offline_eligible_count", passed + warning_count)
        object.__setattr__(self, "warning_ratio", warning_count / len(resolutions))
        object.__setattr__(
            self,
            "warning_by_code",
            MappingProxyType(_count_warning_codes(warning_items)),
        )
        object.__setattr__(
            self,
            "warning_by_channel",
            MappingProxyType(_count_values(item.channel for item in warning_items)),
        )
        object.__setattr__(
            self,
            "warning_by_scenario_mode",
            MappingProxyType(_count_values(item.scenario_mode.value for item in warning_items)),
        )


def revision_issue_set_hash(issue_codes: tuple[str, ...]) -> str:
    return _canonical_hash({"issue_codes": sorted(issue_codes)})


def assert_revision_chain(
    batch: GenerationBatch,
    initial_candidate: GeneratedCandidate,
    revisions: tuple[CandidateRevision, ...],
) -> CandidateOutput:
    if len(revisions) > MAX_REVISION_ROUNDS:
        raise SyntheticLabContractError("Candidate cannot exceed two Revision rounds")
    if initial_candidate not in batch.candidates:
        raise SyntheticLabScopeError("initial Candidate does not belong to Generation Batch")
    if revisions and batch.kind != GenerationBatchKind.INITIAL:
        raise SyntheticLabContractError("regenerated Batch cannot enter Revision")
    current: CandidateOutput = initial_candidate
    for expected_round, revision in enumerate(revisions, start=1):
        assert_same_project(batch, current, revision)
        assert_same_frozen_context(batch.call_lineage, revision.call_lineage)
        if revision.round_number != expected_round:
            raise SyntheticLabContractError("Revision rounds must be contiguous from 1")
        if (
            revision.parent_candidate_id != current.id
            or revision.parent_output_hash != current.output_hash
            or revision.review_run_id != batch.review_run_id
            or revision.review_case_id != batch.review_case_id
            or revision.generation_batch_id != batch.id
        ):
            raise SyntheticLabScopeError("Revision chain changed Candidate/Batch lineage")
        current = revision.revised_candidate
    return current


def decide_next_step(
    batch: GenerationBatch,
    initial_candidate: GeneratedCandidate,
    revisions: tuple[CandidateRevision, ...],
    evaluation: CandidateEvaluation,
) -> WorkflowDecision:
    current = assert_revision_chain(batch, initial_candidate, revisions)
    assert_evaluation_for_candidate(batch, current, evaluation)
    if evaluation.disposition == EvaluationDisposition.PASS:
        return _decision(current, WorkflowAction.COMPLETE, ReviewRunStatus.PASSED)
    if evaluation.disposition == EvaluationDisposition.WARNING:
        return _decision(
            current,
            WorkflowAction.COMPLETE,
            ReviewRunStatus.COMPLETED_WITH_WARNING,
        )
    if batch.kind == GenerationBatchKind.REGENERATED:
        return _decision(current, WorkflowAction.FAIL, ReviewRunStatus.FAILED)
    if len(revisions) < MAX_REVISION_ROUNDS:
        return WorkflowDecision(
            project_id=current.project_id,
            review_run_id=current.review_run_id,
            review_case_id=current.review_case_id,
            candidate_id=current.id,
            action=WorkflowAction.REVISE,
            next_revision_round=len(revisions) + 1,
        )
    return WorkflowDecision(
        project_id=current.project_id,
        review_run_id=current.review_run_id,
        review_case_id=current.review_case_id,
        candidate_id=current.id,
        action=WorkflowAction.REGENERATE,
    )


def resolution_from_decision(
    *,
    resolution_id: UUID,
    decision: WorkflowDecision,
    evaluation: CandidateEvaluation,
    channel: str,
    scenario_mode: ScenarioMode,
    failure_code: str = "revision_exhausted_after_regeneration",
) -> CandidateResolution:
    if decision.action not in {WorkflowAction.COMPLETE, WorkflowAction.FAIL}:
        raise SyntheticLabContractError("non-terminal decision cannot create a Resolution")
    if decision.final_status is None:
        raise SyntheticLabContractError("terminal decision is missing final status")
    assert_same_project(decision, evaluation)
    assert_synthetic_boundary(decision, evaluation)
    if (
        decision.candidate_id != evaluation.candidate_id
        or decision.review_run_id != evaluation.review_run_id
        or decision.review_case_id != evaluation.review_case_id
    ):
        raise SyntheticLabScopeError(
            "decision and Evaluation resolve different Candidate/Run/Case lineage"
        )
    expected_status = {
        EvaluationDisposition.PASS: ReviewRunStatus.PASSED,
        EvaluationDisposition.WARNING: ReviewRunStatus.COMPLETED_WITH_WARNING,
        EvaluationDisposition.REVISE: ReviewRunStatus.FAILED,
    }[evaluation.disposition]
    if decision.final_status != expected_status:
        raise SyntheticLabContractError(
            "terminal decision status does not match Evaluation disposition"
        )
    warnings = (
        evaluation.warning_codes
        if decision.final_status == ReviewRunStatus.COMPLETED_WITH_WARNING
        else ()
    )
    return CandidateResolution(
        id=resolution_id,
        project_id=evaluation.project_id,
        review_run_id=evaluation.review_run_id,
        review_case_id=evaluation.review_case_id,
        candidate_id=evaluation.candidate_id,
        candidate_output_hash=evaluation.candidate_output_hash,
        evaluation_id=evaluation.id,
        evaluation_evidence_hash=evaluation.evidence_artifact_hash,
        channel=channel,
        scenario_mode=scenario_mode,
        status=decision.final_status,
        warning_codes=warnings,
        failure_code=failure_code if decision.final_status == ReviewRunStatus.FAILED else None,
    )


def _decision(
    candidate: CandidateOutput,
    action: WorkflowAction,
    status: ReviewRunStatus,
) -> WorkflowDecision:
    return WorkflowDecision(
        project_id=candidate.project_id,
        review_run_id=candidate.review_run_id,
        review_case_id=candidate.review_case_id,
        candidate_id=candidate.id,
        action=action,
        final_status=status,
    )


def _count_warning_codes(items: tuple[CandidateResolution, ...]) -> dict[str, int]:
    return _count_values(code for item in items for code in item.warning_codes)


def _count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


__all__ = [
    "MAX_REVISION_ROUNDS",
    "CandidateResolution",
    "CandidateRevision",
    "ReviewRunResult",
    "ReviewRunStatus",
    "RevisedCandidate",
    "WorkflowAction",
    "WorkflowDecision",
    "assert_revision_chain",
    "decide_next_step",
    "resolution_from_decision",
    "revision_issue_set_hash",
]
