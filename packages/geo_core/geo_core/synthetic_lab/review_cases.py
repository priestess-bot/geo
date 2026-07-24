"""Frozen Review Suite and Review Case contracts for the synthetic lab."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from geo_core.synthetic_lab.domain import (
    SyntheticLabContractError,
    SyntheticLabScopeError,
    SyntheticLabTransitionError,
    SyntheticOnly,
    _as_enum,
    _canonical_hash,
    _require_channel,
    _require_hash,
    _require_text,
    _require_uuid,
    assert_same_project,
)


class ScenarioMode(StrEnum):
    AUTONOMOUS = "autonomous_scenario"
    GUIDED = "guided_scenario"


class ReviewSuiteStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"
    RETIRED = "retired"


REVIEW_SUITE_TRANSITIONS: Mapping[ReviewSuiteStatus, Mapping[str, ReviewSuiteStatus]] = {
    ReviewSuiteStatus.DRAFT: MappingProxyType({"freeze": ReviewSuiteStatus.FROZEN}),
    ReviewSuiteStatus.FROZEN: MappingProxyType({"retire": ReviewSuiteStatus.RETIRED}),
    ReviewSuiteStatus.RETIRED: MappingProxyType({}),
}


@dataclass(frozen=True, kw_only=True)
class ReviewSuite(SyntheticOnly):
    id: UUID
    project_id: UUID
    suite_id: UUID
    version_number: int
    channel: str
    case_count: int
    case_set_hash: str
    status: ReviewSuiteStatus = ReviewSuiteStatus.DRAFT

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "Review Suite version ID"),
            (self.project_id, "Review Suite Project ID"),
            (self.suite_id, "Review Suite identity"),
        ):
            _require_uuid(value, label)
        if self.version_number < 1:
            raise SyntheticLabContractError("Review Suite version number must be positive")
        status = _as_enum(self.status, ReviewSuiteStatus, "Review Suite status")
        if self.case_count < 0 or (status is not ReviewSuiteStatus.DRAFT and self.case_count < 1):
            raise SyntheticLabContractError(
                "Review Suite Case count is invalid for its lifecycle state"
            )
        _require_channel(self.channel)
        _require_hash(self.case_set_hash, "Review Suite Case set hash")
        object.__setattr__(
            self,
            "status",
            status,
        )


@dataclass(frozen=True, kw_only=True)
class ReviewCase(SyntheticOnly):
    id: UUID
    project_id: UUID
    review_suite_version_id: UUID
    review_suite_version_number: int
    case_key: str
    ordinal: int
    mode: ScenarioMode
    channel: str
    persona: str
    use_case: str
    subject: str
    question_set_version_id: UUID
    question_set_hash: str
    fact_snapshot_id: UUID
    fact_snapshot_hash: str
    profile_version_id: UUID
    profile_hash: str
    competitor_scenario: bool
    expected_risks: tuple[str, ...]
    creative_reference: str | None
    content_hash: str

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.id, "Review Case ID"),
            (self.project_id, "Review Case Project ID"),
            (self.review_suite_version_id, "Review Case Suite version ID"),
            (self.question_set_version_id, "Review Case QuestionSet version ID"),
            (self.fact_snapshot_id, "Review Case Fact snapshot ID"),
            (self.profile_version_id, "Review Case Style Profile version ID"),
        ):
            _require_uuid(uuid_value, label)
        if self.review_suite_version_number < 1:
            raise SyntheticLabContractError("Review Case Suite version must be positive")
        if self.ordinal < 1:
            raise SyntheticLabContractError("Review Case ordinal must be positive")
        for text_value, label in (
            (self.case_key, "Review Case key"),
            (self.persona, "Review Case persona"),
            (self.use_case, "Review Case use case"),
            (self.subject, "Review Case subject"),
        ):
            _require_text(text_value, label)
        _require_channel(self.channel)
        for hash_value, label in (
            (self.question_set_hash, "Review Case QuestionSet hash"),
            (self.fact_snapshot_hash, "Review Case Fact snapshot hash"),
            (self.profile_hash, "Review Case Style Profile hash"),
            (self.content_hash, "Review Case content hash"),
        ):
            _require_hash(hash_value, label)
        mode = _as_enum(self.mode, ScenarioMode, "Review Case scenario mode")
        object.__setattr__(self, "mode", mode)
        risks = tuple(self.expected_risks)
        if len(risks) != len(set(risks)) or any(not risk.strip() for risk in risks):
            raise SyntheticLabContractError(
                "Review Case expected risks must be unique non-empty values"
            )
        object.__setattr__(self, "expected_risks", risks)
        reference = (self.creative_reference or "").strip()
        if mode == ScenarioMode.GUIDED and not reference:
            raise SyntheticLabContractError("guided Review Case requires a creative reference")
        if mode == ScenarioMode.AUTONOMOUS and self.creative_reference is not None:
            raise SyntheticLabContractError(
                "autonomous Review Case cannot carry a creative reference"
            )
        expected_hash = review_case_content_hash(
            case_key=self.case_key,
            ordinal=self.ordinal,
            mode=mode,
            channel=self.channel,
            persona=self.persona,
            use_case=self.use_case,
            subject=self.subject,
            question_set_version_id=self.question_set_version_id,
            question_set_hash=self.question_set_hash,
            fact_snapshot_id=self.fact_snapshot_id,
            fact_snapshot_hash=self.fact_snapshot_hash,
            profile_version_id=self.profile_version_id,
            profile_hash=self.profile_hash,
            competitor_scenario=self.competitor_scenario,
            expected_risks=risks,
            creative_reference=self.creative_reference,
        )
        if self.content_hash != expected_hash:
            raise SyntheticLabContractError("Review Case content does not match its frozen hash")


def review_case_content_hash(
    *,
    case_key: str,
    ordinal: int,
    mode: ScenarioMode | str,
    channel: str,
    persona: str,
    use_case: str,
    subject: str,
    question_set_version_id: UUID,
    question_set_hash: str,
    fact_snapshot_id: UUID,
    fact_snapshot_hash: str,
    profile_version_id: UUID,
    profile_hash: str,
    competitor_scenario: bool,
    expected_risks: tuple[str, ...],
    creative_reference: str | None,
) -> str:
    scenario_mode = _as_enum(mode, ScenarioMode, "Review Case scenario mode")
    return _canonical_hash(
        {
            "case_key": case_key,
            "ordinal": ordinal,
            "mode": scenario_mode.value,
            "channel": channel,
            "persona": persona,
            "use_case": use_case,
            "subject": subject,
            "question_set_version_id": str(question_set_version_id),
            "question_set_hash": question_set_hash,
            "fact_snapshot_id": str(fact_snapshot_id),
            "fact_snapshot_hash": fact_snapshot_hash,
            "profile_version_id": str(profile_version_id),
            "profile_hash": profile_hash,
            "competitor_scenario": competitor_scenario,
            "expected_risks": list(expected_risks),
            "creative_reference": creative_reference,
        }
    )


def review_case_set_hash(cases: tuple[ReviewCase, ...]) -> str:
    ordered = sorted(cases, key=lambda case: (case.ordinal, case.case_key, str(case.id)))
    return _canonical_hash(
        [
            {
                "id": str(case.id),
                "case_key": case.case_key,
                "ordinal": case.ordinal,
                "content_hash": case.content_hash,
            }
            for case in ordered
        ]
    )


def assert_review_suite_case_set(
    suite: ReviewSuite,
    cases: tuple[ReviewCase, ...],
) -> None:
    if not cases:
        raise SyntheticLabContractError("Review Suite requires at least one Case")
    assert_same_project(suite, *cases)
    if len({case.id for case in cases}) != len(cases):
        raise SyntheticLabContractError("Review Suite Case IDs must be unique")
    if len({case.case_key for case in cases}) != len(cases):
        raise SyntheticLabContractError("Review Suite Case keys must be unique")
    if len({case.ordinal for case in cases}) != len(cases):
        raise SyntheticLabContractError("Review Suite Case ordinals must be unique")
    if any(
        case.review_suite_version_id != suite.id
        or case.review_suite_version_number != suite.version_number
        or case.channel != suite.channel
        for case in cases
    ):
        raise SyntheticLabScopeError("Review Case does not match its frozen Suite version")
    if len(cases) != suite.case_count:
        raise SyntheticLabContractError("Review Suite Case count does not match")
    if review_case_set_hash(cases) != suite.case_set_hash:
        raise SyntheticLabContractError("Review Suite Case set does not match its frozen hash")


def assert_next_review_suite_version(previous: ReviewSuite, current: ReviewSuite) -> None:
    assert_same_project(previous, current)
    if current.suite_id != previous.suite_id or current.id == previous.id:
        raise SyntheticLabScopeError("Review Suite versions do not share immutable identity")
    if current.channel != previous.channel:
        raise SyntheticLabScopeError("Review Suite identity cannot change channel")
    if current.version_number != previous.version_number + 1:
        raise SyntheticLabContractError("Review Suite version history must be contiguous")


def transition_review_suite(
    suite: ReviewSuite,
    *,
    command: str,
    cases: tuple[ReviewCase, ...] | None = None,
) -> ReviewSuite:
    target = REVIEW_SUITE_TRANSITIONS[suite.status].get(command)
    if target is None:
        raise SyntheticLabTransitionError(
            f"Review Suite command {command!r} is not allowed from {suite.status.value!r}"
        )
    if target == ReviewSuiteStatus.FROZEN:
        if cases is None:
            raise SyntheticLabContractError("freezing Review Suite requires its Cases")
        assert_review_suite_case_set(suite, cases)
    elif cases is not None:
        raise SyntheticLabContractError("retiring Review Suite does not accept a Case set")
    return replace(suite, status=target)


__all__ = [
    "ReviewCase",
    "ReviewSuite",
    "ReviewSuiteStatus",
    "ScenarioMode",
    "assert_next_review_suite_version",
    "assert_review_suite_case_set",
    "review_case_content_hash",
    "review_case_set_hash",
    "transition_review_suite",
]
