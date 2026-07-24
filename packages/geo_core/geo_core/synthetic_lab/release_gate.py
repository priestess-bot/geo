"""Per-channel immutable release eligibility receipt for Synthetic Lab results."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from geo_core.synthetic_lab.acceptance_matrix import (
    CASES_PER_CHANNEL,
    COMPETITOR_CASES_PER_CHANNEL,
    MODE_CASES_PER_CHANNEL,
    AcceptanceMatrix,
)
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.domain import (
    STANDARD_STYLE_CHANNELS,
    SyntheticLabContractError,
    SyntheticOnly,
    _as_enum,
    _require_aware_datetime,
    _require_hash,
    _require_uuid,
)
from geo_core.synthetic_lab.review_cases import ScenarioMode
from geo_core.synthetic_lab.revision import ReviewRunStatus


MIN_CHANNEL_PASS_RATE = 0.95
MIN_CHANNEL_STYLE_MEAN = 4.2


@dataclass(frozen=True, kw_only=True)
class AcceptanceCaseOutcome(SyntheticOnly):
    case_id: UUID
    status: ReviewRunStatus
    style_score: float
    subject_mixup_count: int
    source_replication_violation_count: int
    warning_codes: tuple[str, ...] = ()
    outcome_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid(self.case_id, "acceptance outcome Case")
        status = _as_enum(self.status, ReviewRunStatus, "acceptance outcome status")
        object.__setattr__(self, "status", status)
        if not 0 <= self.style_score <= 5:
            raise SyntheticLabContractError("acceptance outcome style score is outside [0, 5]")
        if self.subject_mixup_count < 0 or self.source_replication_violation_count < 0:
            raise SyntheticLabContractError("acceptance safety violation count cannot be negative")
        warnings = tuple(sorted(set(self.warning_codes)))
        object.__setattr__(self, "warning_codes", warnings)
        if any(not value.strip() for value in warnings):
            raise SyntheticLabContractError("acceptance warning code cannot be empty")
        if status is ReviewRunStatus.COMPLETED_WITH_WARNING and not warnings:
            raise SyntheticLabContractError("warning outcome requires a warning code")
        if status is not ReviewRunStatus.COMPLETED_WITH_WARNING and warnings:
            raise SyntheticLabContractError("only warning outcomes can carry warning codes")
        object.__setattr__(self, "outcome_hash", canonical_hash(self.value()))

    def value(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "style_score": self.style_score,
            "subject_mixup_count": self.subject_mixup_count,
            "source_replication_violation_count": self.source_replication_violation_count,
            "warning_codes": self.warning_codes,
        }


@dataclass(frozen=True, kw_only=True)
class OperatorReviewEvidence(SyntheticOnly):
    channel: str
    submitted_by: UUID
    reviewed_by: UUID
    reviewed_at: datetime
    approved: bool
    evidence_hash: str

    def __post_init__(self) -> None:
        if self.channel not in STANDARD_STYLE_CHANNELS:
            raise SyntheticLabContractError("operator review channel is not standard")
        _require_uuid(self.submitted_by, "release candidate submitter")
        _require_uuid(self.reviewed_by, "release candidate reviewer")
        if self.submitted_by == self.reviewed_by:
            raise SyntheticLabContractError("release review must be independent of the submitter")
        _require_aware_datetime(self.reviewed_at, "release review time")
        _require_hash(self.evidence_hash, "release review evidence")


@dataclass(frozen=True, kw_only=True)
class ChannelReleaseGateResult(SyntheticOnly):
    channel: str
    fixed_case_count: int
    autonomous_count: int
    guided_count: int
    competitor_count: int
    competitor_ratio: float
    passed_count: int
    warning_count: int
    failed_count: int
    pass_rate: float
    warning_ratio: float
    style_mean: float
    subject_mixup_count: int
    source_replication_violation_count: int
    warning_by_code: Mapping[str, int]
    warning_by_scenario_mode: Mapping[str, int]
    warning_by_risk: Mapping[str, int]
    independent_operator_review: bool
    release_ready: bool
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.channel not in STANDARD_STYLE_CHANNELS:
            raise SyntheticLabContractError("release Gate channel is not standard")
        for name in ("warning_by_code", "warning_by_scenario_mode", "warning_by_risk"):
            values = MappingProxyType(dict(getattr(self, name)))
            object.__setattr__(self, name, values)
            if any(not key.strip() or value < 1 for key, value in values.items()):
                raise SyntheticLabContractError("release Gate warning stratum is invalid")
        if self.passed_count + self.warning_count + self.failed_count != self.fixed_case_count:
            raise SyntheticLabContractError("release Gate outcome counts do not balance")
        expected_ready = all(
            (
                self.fixed_case_count >= CASES_PER_CHANNEL,
                self.autonomous_count >= MODE_CASES_PER_CHANNEL,
                self.guided_count >= MODE_CASES_PER_CHANNEL,
                self.competitor_count >= COMPETITOR_CASES_PER_CHANNEL,
                self.competitor_ratio >= 0.30,
                self.pass_rate >= MIN_CHANNEL_PASS_RATE,
                self.subject_mixup_count == 0,
                self.source_replication_violation_count == 0,
                self.style_mean >= MIN_CHANNEL_STYLE_MEAN,
                self.independent_operator_review,
            )
        )
        if self.release_ready != expected_ready:
            raise SyntheticLabContractError("release Gate readiness does not match its evidence")
        object.__setattr__(self, "result_hash", canonical_hash(self.value()))

    def value(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in (
                "channel",
                "fixed_case_count",
                "autonomous_count",
                "guided_count",
                "competitor_count",
                "competitor_ratio",
                "passed_count",
                "warning_count",
                "failed_count",
                "pass_rate",
                "warning_ratio",
                "style_mean",
                "subject_mixup_count",
                "source_replication_violation_count",
                "warning_by_code",
                "warning_by_scenario_mode",
                "warning_by_risk",
                "independent_operator_review",
                "release_ready",
            )
        }


@dataclass(frozen=True, kw_only=True)
class LabReleaseGateReceipt(SyntheticOnly):
    project_id: UUID
    matrix_hash: str
    matrix_manifest_hash: str
    prompt_release_id: UUID
    prompt_release_hash: str
    channel_profile_hashes: Mapping[str, str]
    channel_results: Mapping[str, ChannelReleaseGateResult]
    prompt_release_ready: bool
    profile_releases_ready: bool
    automatic_approval: bool = field(default=False, init=False)
    automatic_freeze: bool = field(default=False, init=False)
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "release Gate Project")
        _require_uuid(self.prompt_release_id, "release Gate Prompt Release")
        for value, label in (
            (self.matrix_hash, "release Gate matrix"),
            (self.matrix_manifest_hash, "release Gate matrix manifest"),
            (self.prompt_release_hash, "release Gate Prompt Release"),
        ):
            _require_hash(value, label)
        profiles = MappingProxyType(dict(self.channel_profile_hashes))
        results = MappingProxyType(dict(self.channel_results))
        object.__setattr__(self, "channel_profile_hashes", profiles)
        object.__setattr__(self, "channel_results", results)
        if set(profiles) != set(STANDARD_STYLE_CHANNELS) or set(results) != set(
            STANDARD_STYLE_CHANNELS
        ):
            raise SyntheticLabContractError("release Gate receipt requires all nine channels")
        if any(key != result.channel for key, result in results.items()):
            raise SyntheticLabContractError("release Gate result mapping changed channel")
        all_ready = all(item.release_ready for item in results.values())
        if self.prompt_release_ready != all_ready or self.profile_releases_ready != all_ready:
            raise SyntheticLabContractError("one failed channel must block Prompt and Profile readiness")
        object.__setattr__(self, "receipt_hash", canonical_hash(self.value()))

    def value(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "matrix_hash": self.matrix_hash,
            "matrix_manifest_hash": self.matrix_manifest_hash,
            "prompt_release_id": self.prompt_release_id,
            "prompt_release_hash": self.prompt_release_hash,
            "channel_profile_hashes": self.channel_profile_hashes,
            "channel_results": self.channel_results,
            "prompt_release_ready": self.prompt_release_ready,
            "profile_releases_ready": self.profile_releases_ready,
            "automatic_approval": False,
            "automatic_freeze": False,
        }


def evaluate_lab_release_gate(
    *,
    matrix: AcceptanceMatrix,
    prompt_release_id: UUID,
    prompt_release_hash: str,
    outcomes: tuple[AcceptanceCaseOutcome, ...],
    operator_reviews: Mapping[str, OperatorReviewEvidence],
) -> LabReleaseGateReceipt:
    by_case = {item.case_id: item for item in outcomes}
    expected_ids = {item.id for item in matrix.cases}
    if len(by_case) != len(outcomes) or set(by_case) != expected_ids:
        raise SyntheticLabContractError("release Gate requires one outcome for every fixed Case")
    reviews = dict(operator_reviews)
    if set(reviews) != set(STANDARD_STYLE_CHANNELS) or any(
        key != value.channel for key, value in reviews.items()
    ):
        raise SyntheticLabContractError("release Gate requires one review per channel")
    results = {
        channel: _channel_result(matrix, channel, by_case, reviews[channel])
        for channel in sorted(STANDARD_STYLE_CHANNELS)
    }
    all_ready = all(result.release_ready for result in results.values())
    return LabReleaseGateReceipt(
        project_id=matrix.inputs.project_id,
        matrix_hash=matrix.matrix_hash,
        matrix_manifest_hash=matrix.manifest.manifest_hash,
        prompt_release_id=prompt_release_id,
        prompt_release_hash=prompt_release_hash,
        channel_profile_hashes={
            channel: binding.profile_hash
            for channel, binding in matrix.inputs.profiles.items()
        },
        channel_results=results,
        prompt_release_ready=all_ready,
        profile_releases_ready=all_ready,
    )


def _channel_result(
    matrix: AcceptanceMatrix,
    channel: str,
    outcomes: Mapping[UUID, AcceptanceCaseOutcome],
    review: OperatorReviewEvidence,
) -> ChannelReleaseGateResult:
    cases = tuple(item for item in matrix.cases if item.channel == channel)
    values = tuple(outcomes[item.id] for item in cases)
    passed = sum(item.status is ReviewRunStatus.PASSED for item in values)
    warnings = tuple(
        (case, outcome)
        for case, outcome in zip(cases, values, strict=True)
        if outcome.status is ReviewRunStatus.COMPLETED_WITH_WARNING
    )
    failed = sum(item.status is ReviewRunStatus.FAILED for item in values)
    competitors = sum(item.competitor_scenario for item in cases)
    count = len(cases)
    warning_by_code = Counter(
        code for _case, outcome in warnings for code in outcome.warning_codes
    )
    warning_by_mode = Counter(case.mode.value for case, _outcome in warnings)
    warning_by_risk = Counter(risk for case, _outcome in warnings for risk in case.expected_risks)
    style_mean = sum(item.style_score for item in values) / count
    pass_rate = passed / count
    ready = all(
        (
            count >= CASES_PER_CHANNEL,
            sum(item.mode is ScenarioMode.AUTONOMOUS for item in cases)
            >= MODE_CASES_PER_CHANNEL,
            sum(item.mode is ScenarioMode.GUIDED for item in cases) >= MODE_CASES_PER_CHANNEL,
            competitors / count >= 0.30,
            pass_rate >= MIN_CHANNEL_PASS_RATE,
            sum(item.subject_mixup_count for item in values) == 0,
            sum(item.source_replication_violation_count for item in values) == 0,
            style_mean >= MIN_CHANNEL_STYLE_MEAN,
            review.approved,
        )
    )
    return ChannelReleaseGateResult(
        channel=channel,
        fixed_case_count=count,
        autonomous_count=sum(item.mode is ScenarioMode.AUTONOMOUS for item in cases),
        guided_count=sum(item.mode is ScenarioMode.GUIDED for item in cases),
        competitor_count=competitors,
        competitor_ratio=competitors / count,
        passed_count=passed,
        warning_count=len(warnings),
        failed_count=failed,
        pass_rate=pass_rate,
        warning_ratio=len(warnings) / count,
        style_mean=style_mean,
        subject_mixup_count=sum(item.subject_mixup_count for item in values),
        source_replication_violation_count=sum(
            item.source_replication_violation_count for item in values
        ),
        warning_by_code=dict(warning_by_code),
        warning_by_scenario_mode=dict(warning_by_mode),
        warning_by_risk=dict(warning_by_risk),
        independent_operator_review=review.approved,
        release_ready=ready,
    )


__all__ = [
    "AcceptanceCaseOutcome",
    "ChannelReleaseGateResult",
    "LabReleaseGateReceipt",
    "MIN_CHANNEL_PASS_RATE",
    "MIN_CHANNEL_STYLE_MEAN",
    "OperatorReviewEvidence",
    "evaluate_lab_release_gate",
]
