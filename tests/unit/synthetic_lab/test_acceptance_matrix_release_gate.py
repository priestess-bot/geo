from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
from uuid import UUID, uuid5

import pytest

from geo_core.synthetic_lab.acceptance_matrix import (
    CASES_PER_CHANNEL,
    COMPETITOR_CASES_PER_CHANNEL,
    GUIDED_REFERENCE_PREFIX,
    MODE_CASES_PER_CHANNEL,
    REQUIRED_ACCEPTANCE_RISKS,
    AcceptanceMatrixInput,
    ChannelProfileBinding,
    build_acceptance_matrix,
)
from geo_core.synthetic_lab.domain import STANDARD_STYLE_CHANNELS, SyntheticLabContractError
from geo_core.synthetic_lab.release_gate import (
    AcceptanceCaseOutcome,
    OperatorReviewEvidence,
    evaluate_lab_release_gate,
)
from geo_core.synthetic_lab.review_cases import ScenarioMode
from geo_core.synthetic_lab.revision import ReviewRunStatus


PROJECT_ID = UUID("20000000-0000-0000-0000-000000000001")
PROMPT_RELEASE_ID = UUID("20000000-0000-0000-0000-000000000002")
REVIEWED_AT = datetime(2026, 7, 23, 9, tzinfo=UTC)


def test_builder_is_deterministic_and_meets_every_channel_matrix() -> None:
    first = build_acceptance_matrix(_inputs())
    second = build_acceptance_matrix(_inputs())

    assert first.matrix_hash == second.matrix_hash
    assert first.manifest.manifest_hash == second.manifest.manifest_hash
    assert [item.id for item in first.cases] == [item.id for item in second.cases]
    assert len(first.suites) == 9
    assert len(first.cases) == 360
    for channel in STANDARD_STYLE_CHANNELS:
        cases = tuple(item for item in first.cases if item.channel == channel)
        assert len(cases) == CASES_PER_CHANNEL
        assert sum(item.mode is ScenarioMode.AUTONOMOUS for item in cases) == (
            MODE_CASES_PER_CHANNEL
        )
        assert sum(item.mode is ScenarioMode.GUIDED for item in cases) == MODE_CASES_PER_CHANNEL
        assert sum(item.competitor_scenario for item in cases) == COMPETITOR_CASES_PER_CHANNEL
        assert {risk for item in cases for risk in item.expected_risks}.issuperset(
            REQUIRED_ACCEPTANCE_RISKS
        )
        assert all(item.creative_reference is None for item in cases[:20])
        assert all(
            (item.creative_reference or "").startswith(GUIDED_REFERENCE_PREFIX)
            for item in cases[20:]
        )
    assert first.manifest.fixture_schema_baseline is True
    assert first.manifest.real_sample_threshold_evidence is False
    assert first.manifest.human_review_evidence is False
    assert first.publication_eligible is False


def test_matrix_hash_changes_with_exact_question_set_identity() -> None:
    baseline = build_acceptance_matrix(_inputs())
    changed = build_acceptance_matrix(
        replace(_inputs(), question_set_hash=_hash("question-set-v2"))
    )

    assert baseline.matrix_hash != changed.matrix_hash
    assert baseline.cases[0].id != changed.cases[0].id


def test_matrix_requires_one_exact_profile_for_every_standard_channel() -> None:
    inputs = _inputs()
    profiles = dict(inputs.profiles)
    profiles.pop("reddit")

    with pytest.raises(SyntheticLabContractError, match="all nine Profiles"):
        replace(inputs, profiles=profiles)


def test_release_gate_passes_per_channel_and_keeps_warning_strata_separate() -> None:
    matrix = build_acceptance_matrix(_inputs())
    outcomes = _passing_outcomes(matrix, warning_count=2)

    receipt = evaluate_lab_release_gate(
        matrix=matrix,
        prompt_release_id=PROMPT_RELEASE_ID,
        prompt_release_hash=_hash("prompt-release-v1"),
        outcomes=outcomes,
        operator_reviews=_reviews(approved=True),
    )

    assert receipt.prompt_release_ready is True
    assert receipt.profile_releases_ready is True
    assert receipt.automatic_approval is False
    assert receipt.automatic_freeze is False
    for result in receipt.channel_results.values():
        assert result.release_ready is True
        assert result.passed_count == 38
        assert result.pass_rate == 0.95
        assert result.warning_count == 2
        assert result.warning_ratio == 0.05
        assert result.warning_by_code == {"derived_or_unknown": 2}
        assert sum(result.warning_by_scenario_mode.values()) == 2
        assert result.warning_by_risk


def test_one_channel_failure_cannot_be_hidden_by_global_average() -> None:
    matrix = build_acceptance_matrix(_inputs())
    values = list(_passing_outcomes(matrix, warning_count=0))
    amazon_case = next(item for item in matrix.cases if item.channel == "amazon")
    index = next(index for index, item in enumerate(values) if item.case_id == amazon_case.id)
    values[index] = replace(values[index], subject_mixup_count=1)

    receipt = evaluate_lab_release_gate(
        matrix=matrix,
        prompt_release_id=PROMPT_RELEASE_ID,
        prompt_release_hash=_hash("prompt-release-v1"),
        outcomes=tuple(values),
        operator_reviews=_reviews(approved=True),
    )

    assert receipt.channel_results["amazon"].release_ready is False
    assert all(
        result.release_ready
        for channel, result in receipt.channel_results.items()
        if channel != "amazon"
    )
    assert receipt.prompt_release_ready is False
    assert receipt.profile_releases_ready is False


def test_release_gate_rejects_missing_case_and_non_independent_review() -> None:
    matrix = build_acceptance_matrix(_inputs())
    with pytest.raises(SyntheticLabContractError, match="every fixed Case"):
        evaluate_lab_release_gate(
            matrix=matrix,
            prompt_release_id=PROMPT_RELEASE_ID,
            prompt_release_hash=_hash("prompt-release-v1"),
            outcomes=_passing_outcomes(matrix, warning_count=0)[:-1],
            operator_reviews=_reviews(approved=True),
        )

    actor = UUID("20000000-0000-0000-0000-000000000010")
    with pytest.raises(SyntheticLabContractError, match="independent"):
        OperatorReviewEvidence(
            channel="reddit",
            submitted_by=actor,
            reviewed_by=actor,
            reviewed_at=REVIEWED_AT,
            approved=True,
            evidence_hash=_hash("review-reddit"),
        )


def _inputs() -> AcceptanceMatrixInput:
    profiles = {
        channel: ChannelProfileBinding(
            channel=channel,
            profile_version_id=uuid5(PROJECT_ID, f"profile:{channel}"),
            profile_hash=_hash(f"profile:{channel}:v1"),
        )
        for channel in STANDARD_STYLE_CHANNELS
    }
    return AcceptanceMatrixInput(
        project_id=PROJECT_ID,
        question_set_version_id=UUID("20000000-0000-0000-0000-000000000003"),
        question_set_hash=_hash("question-set-v1"),
        fact_snapshot_id=UUID("20000000-0000-0000-0000-000000000004"),
        fact_snapshot_hash=_hash("facts-v1"),
        subject="Advinsys Product A",
        competitor_subject="Competitor Product B",
        profiles=profiles,
    )


def _passing_outcomes(matrix, *, warning_count: int) -> tuple[AcceptanceCaseOutcome, ...]:
    channel_ordinals: dict[str, int] = {}
    values = []
    for case in matrix.cases:
        channel_ordinals[case.channel] = channel_ordinals.get(case.channel, 0) + 1
        warning = channel_ordinals[case.channel] <= warning_count
        values.append(
            AcceptanceCaseOutcome(
                case_id=case.id,
                status=(
                    ReviewRunStatus.COMPLETED_WITH_WARNING
                    if warning
                    else ReviewRunStatus.PASSED
                ),
                style_score=4.5,
                subject_mixup_count=0,
                source_replication_violation_count=0,
                warning_codes=("derived_or_unknown",) if warning else (),
            )
        )
    return tuple(values)


def _reviews(*, approved: bool) -> dict[str, OperatorReviewEvidence]:
    submitter = UUID("20000000-0000-0000-0000-000000000010")
    return {
        channel: OperatorReviewEvidence(
            channel=channel,
            submitted_by=submitter,
            reviewed_by=uuid5(PROJECT_ID, f"reviewer:{channel}"),
            reviewed_at=REVIEWED_AT,
            approved=approved,
            evidence_hash=_hash(f"review:{channel}"),
        )
        for channel in STANDARD_STYLE_CHANNELS
    }


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
