from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json

import pytest

from geo_core.sampling import (
    REQUIRED_FIXTURE_BLOCK_REASONS,
    SURFACE_PARSER_RELEASES,
    SurfaceArtifactCaptureKind,
    SurfaceBlockReason,
    SurfaceParseOutcome,
    SurfaceParseSummary,
    SurfaceParserGoldCase,
    SamplingRuleViolation,
    parse_governed_manual_surface_artifact,
    parse_surface_artifact,
    release_matches_source,
    score_surface_parser_release,
)


@pytest.mark.parametrize("release", SURFACE_PARSER_RELEASES)
def test_each_surface_release_passes_its_own_thirty_case_gold_suite(release) -> None:
    cases = _gold_cases(release)

    score = score_surface_parser_release(release, cases)

    assert score.fixture_count == 30
    assert score.captured_count == 11
    assert score.absence_count == 5
    assert all(score.block_reason_counts[item] == 2 for item in REQUIRED_FIXTURE_BLOCK_REASONS)
    assert score.classification_accuracy == Decimal(1)
    assert score.answer_text_completeness == Decimal(1)
    assert score.citation_accuracy == Decimal(1)
    assert score.ordinary_result_false_positive_count == 0
    assert score.blocked_as_valid_absence_count == 0
    assert score.fixture_ready is True


def test_parser_releases_are_independent_and_cannot_pool_fixture_counts() -> None:
    release_ids = {item.id for item in SURFACE_PARSER_RELEASES}
    release_hashes = {item.release_hash for item in SURFACE_PARSER_RELEASES}
    assert len(release_ids) == len(SURFACE_PARSER_RELEASES) == 3
    assert len(release_hashes) == len(SURFACE_PARSER_RELEASES)

    for release in SURFACE_PARSER_RELEASES:
        score = score_surface_parser_release(release, _gold_cases(release)[:29])
        assert score.fixture_count == 29
        assert score.fixture_ready is False


@pytest.mark.parametrize("release", SURFACE_PARSER_RELEASES)
def test_featured_or_ordinary_result_is_valid_absence_not_an_ai_answer(release) -> None:
    artifact = _artifact(release)
    artifact["surface_markers"] = []
    artifact["ordinary_result_markers"] = [
        "ordinary_results_ready",
        "featured_snippet",
        "knowledge_panel",
    ]
    artifact["answer_blocks"] = []
    artifact["citations"] = []

    result = parse_surface_artifact(
        release,
        artifact,
        capture_kind=SurfaceArtifactCaptureKind.FIXTURE,
    )

    assert result.outcome is SurfaceParseOutcome.SURFACE_NOT_PRESENT
    assert result.content_eligible is True
    assert result.automated_capture is False
    assert result.live_capture_eligible is False


def test_cross_surface_marker_and_selector_drift_fail_closed() -> None:
    release, other = SURFACE_PARSER_RELEASES[:2]
    artifact = _artifact(release)
    artifact["surface_markers"] = [other.surface_marker]

    result = parse_surface_artifact(
        release,
        artifact,
        capture_kind=SurfaceArtifactCaptureKind.FIXTURE,
    )

    assert result.outcome is SurfaceParseOutcome.PARSER_FAILED
    assert result.block_reason is SurfaceBlockReason.WRONG_SURFACE
    assert result.content_eligible is False


@pytest.mark.parametrize(
    ("field", "mutation"),
    (
        ("surface_markers", [123]),
        ("answer_blocks", [{"text": None, "locator": "dom://answer/1"}]),
        ("answer_blocks", [{"text": "Answer", "locator": 7}]),
        (
            "citations",
            [{"url": None, "title": "Source", "position": 1, "locator": "dom://citation/1"}],
        ),
        (
            "citations",
            [{"url": "https://example.com", "title": 9, "position": 1, "locator": "dom://citation/1"}],
        ),
    ),
)
def test_structured_artifact_rejects_non_string_text_fields(
    field: str, mutation: object
) -> None:
    release = SURFACE_PARSER_RELEASES[0]
    artifact = _artifact(release)
    artifact[field] = mutation

    result = parse_surface_artifact(
        release,
        artifact,
        capture_kind=SurfaceArtifactCaptureKind.FIXTURE,
    )

    assert result.outcome is SurfaceParseOutcome.PARSER_FAILED
    assert result.block_reason is SurfaceBlockReason.INVALID_ARTIFACT
    assert result.content_eligible is False


@pytest.mark.parametrize("collection", ["answer_blocks", "citations"])
def test_duplicate_evidence_locators_fail_closed(collection: str) -> None:
    release = SURFACE_PARSER_RELEASES[0]
    artifact = _artifact(release)
    if collection == "answer_blocks":
        artifact[collection] = [
            {"text": "First", "locator": "dom://same"},
            {"text": "Second", "locator": "dom://same"},
        ]
    else:
        artifact[collection] = [
            {"url": "https://example.com/1", "title": "One", "position": 1, "locator": "dom://same"},
            {"url": "https://example.com/2", "title": "Two", "position": 2, "locator": "dom://same"},
        ]

    result = parse_surface_artifact(
        release,
        artifact,
        capture_kind=SurfaceArtifactCaptureKind.FIXTURE,
    )

    assert result.outcome is SurfaceParseOutcome.PARSER_FAILED
    assert result.block_reason is SurfaceBlockReason.INVALID_ARTIFACT


def test_persisted_summary_rejects_inconsistent_outcome_and_eligibility() -> None:
    release = SURFACE_PARSER_RELEASES[0]
    result = parse_surface_artifact(
        release,
        _artifact(release),
        capture_kind=SurfaceArtifactCaptureKind.MANUAL_UI,
    )
    summary = SurfaceParseSummary.from_result(result)
    values = summary.persisted_value()
    values["outcome"] = "surface_not_present"

    with pytest.raises(
        SamplingRuleViolation,
        match="surface absence summary is inconsistent",
    ):
        SurfaceParseSummary(
            parser_release_id=summary.parser_release_id,
            parser_release_hash=summary.parser_release_hash,
            platform=summary.platform,
            surface=summary.surface,
            capture_kind=summary.capture_kind,
            outcome=SurfaceParseOutcome(str(values["outcome"])),
            block_reason=summary.block_reason,
            content_eligible=summary.content_eligible,
            automated_capture=summary.automated_capture,
            live_capture_eligible=summary.live_capture_eligible,
            answer_text_hash=summary.answer_text_hash,
            answer_character_count=summary.answer_character_count,
            citation_count=summary.citation_count,
            citation_set_hash=summary.citation_set_hash,
            locator_set_hash=summary.locator_set_hash,
            parser_result_hash=summary.parser_result_hash,
        )


def test_mutated_answer_and_citation_prevent_fixture_ready_release() -> None:
    release = SURFACE_PARSER_RELEASES[0]
    cases = list(_gold_cases(release))
    first = cases[0]
    mutated_artifact = deepcopy(dict(first.artifact))
    mutated_artifact["answer_blocks"] = [
        {"text": "Truncated", "locator": "dom://answer/1"}
    ]
    mutated_artifact["citations"] = [
        {
            "url": "https://example.net/wrong",
            "title": "Wrong source",
            "position": 1,
            "locator": "dom://citation/1",
        }
    ]
    cases[0] = SurfaceParserGoldCase(
        case_id=first.case_id,
        artifact=mutated_artifact,
        expected_outcome=first.expected_outcome,
        expected_answer_text=first.expected_answer_text,
        expected_citations=first.expected_citations,
        expected_block_reason=first.expected_block_reason,
    )

    score = score_surface_parser_release(release, cases)

    assert score.answer_text_completeness < Decimal("0.99")
    assert score.citation_accuracy < Decimal(1)
    assert score.fixture_ready is False


def test_block_mutation_cannot_be_counted_as_valid_surface_absence() -> None:
    release = SURFACE_PARSER_RELEASES[0]
    cases = list(_gold_cases(release))
    blocked = cases[-1]
    mutated = deepcopy(dict(blocked.artifact))
    mutated["blocking_state"] = None
    mutated["ordinary_result_markers"] = ["ordinary_results_ready"]
    cases[-1] = SurfaceParserGoldCase(
        case_id=blocked.case_id,
        artifact=mutated,
        expected_outcome=blocked.expected_outcome,
        expected_answer_text=None,
        expected_citations=(),
        expected_block_reason=blocked.expected_block_reason,
    )

    score = score_surface_parser_release(release, cases)

    assert score.blocked_as_valid_absence_count == 1
    assert score.fixture_ready is False


def test_manual_parser_reads_only_governed_json_and_summary_is_text_free() -> None:
    release = SURFACE_PARSER_RELEASES[0]
    artifact = _artifact(release)
    artifact["answer_blocks"] = [
        {
            "text": "Contact buyer@example.com for the detailed answer.",
            "locator": "dom://answer/1",
        }
    ]
    content = bytearray(json.dumps(artifact).encode())

    result = parse_governed_manual_surface_artifact(
        release,
        evidence_kind="transcript_export",
        content_type="application/json",
        content=content,
        governance_policy_key="manual-evidence-redaction-v1",
        pre_redacted_attestation=False,
    )
    summary = SurfaceParseSummary.from_result(result)

    assert result.answer_text == "Contact [REDACTED_EMAIL] for the detailed answer."
    assert "buyer@example.com" not in repr(result)
    assert "answer_text" not in summary.persisted_value()
    persisted = json.dumps(summary.persisted_value(), sort_keys=True)
    assert "buyer@example.com" not in persisted
    assert "Official source" not in persisted
    assert "https://example.com" not in persisted
    assert summary.capture_kind is SurfaceArtifactCaptureKind.MANUAL_UI
    assert summary.automated_capture is False
    assert summary.live_capture_eligible is False
    assert summary.answer_text_hash is not None


@pytest.mark.parametrize(
    ("release_index", "platform", "surface"),
    (
        (0, "google", "ai_overviews"),
        (1, "google_search", "ai_mode"),
        (2, "bing", "copilot"),
    ),
)
def test_release_source_matching_keeps_surfaces_separate(
    release_index: int, platform: str, surface: str
) -> None:
    release = SURFACE_PARSER_RELEASES[release_index]
    assert release_matches_source(release, platform=platform, surface=surface)
    other = SURFACE_PARSER_RELEASES[(release_index + 1) % 3]
    assert not release_matches_source(other, platform=platform, surface=surface)


def _gold_cases(release) -> tuple[SurfaceParserGoldCase, ...]:
    cases: list[SurfaceParserGoldCase] = []
    expected_answer = f"A governed {release.surface.value} answer for Australian review."
    expected_citations = (
        ("https://example.com/official", "Official source"),
        ("https://example.org/reference", "Reference source"),
    )
    for index in range(11):
        artifact = _artifact(release)
        artifact["answer_blocks"] = [
            {"text": expected_answer, "locator": "dom://answer/1"}
        ]
        cases.append(
            SurfaceParserGoldCase(
                case_id=f"captured-{index}",
                artifact=artifact,
                expected_outcome=SurfaceParseOutcome.CAPTURED,
                expected_answer_text=expected_answer,
                expected_citations=expected_citations,
                expected_block_reason=None,
            )
        )
    for index in range(5):
        artifact = _artifact(release)
        artifact["surface_markers"] = []
        artifact["ordinary_result_markers"] = [
            "ordinary_results_ready",
            "featured_snippet" if index % 2 else "knowledge_panel",
        ]
        artifact["answer_blocks"] = []
        artifact["citations"] = []
        cases.append(
            SurfaceParserGoldCase(
                case_id=f"absence-{index}",
                artifact=artifact,
                expected_outcome=SurfaceParseOutcome.SURFACE_NOT_PRESENT,
                expected_answer_text=None,
                expected_citations=(),
                expected_block_reason=None,
            )
        )
    for reason in REQUIRED_FIXTURE_BLOCK_REASONS:
        for index in range(2):
            artifact = _artifact(release)
            artifact["blocking_state"] = reason.value
            artifact["surface_markers"] = []
            artifact["answer_blocks"] = []
            artifact["citations"] = []
            cases.append(
                SurfaceParserGoldCase(
                    case_id=f"{reason.value}-{index}",
                    artifact=artifact,
                    expected_outcome=_outcome(reason),
                    expected_answer_text=None,
                    expected_citations=(),
                    expected_block_reason=reason,
                )
            )
    return tuple(cases)


def _artifact(release) -> dict[str, object]:
    return {
        "schema_version": "consumer-surface-artifact-v1",
        "platform": release.platform,
        "surface": release.surface.value,
        "final_url": (
            "https://www.google.com/search?q=fixture"
            if release.platform == "google"
            else "https://www.bing.com/search?q=fixture"
        ),
        "page_ready": True,
        "surface_markers": [release.surface_marker],
        "ordinary_result_markers": ["ordinary_results_ready"],
        "answer_blocks": [
            {
                "text": f"A governed {release.surface.value} answer for Australian review.",
                "locator": "dom://answer/1",
            }
        ],
        "citations": [
            {
                "url": "https://example.com/official",
                "title": "Official source",
                "position": 1,
                "locator": "dom://citation/1",
            },
            {
                "url": "https://example.org/reference",
                "title": "Reference source",
                "position": 2,
                "locator": "dom://citation/2",
            },
        ],
        "blocking_state": None,
        "follow_up_count": 2,
    }


def _outcome(reason: SurfaceBlockReason) -> SurfaceParseOutcome:
    if reason is SurfaceBlockReason.CONSENT:
        return SurfaceParseOutcome.CONSENT_REQUIRED
    if reason is SurfaceBlockReason.LOGIN:
        return SurfaceParseOutcome.LOGIN_REQUIRED
    if reason in {SurfaceBlockReason.CAPTCHA, SurfaceBlockReason.RATE_LIMIT}:
        return SurfaceParseOutcome.ACCESS_BLOCKED
    if reason is SurfaceBlockReason.GEO_MISMATCH:
        return SurfaceParseOutcome.GEO_MISMATCH
    if reason is SurfaceBlockReason.EGRESS_CHANGED:
        return SurfaceParseOutcome.EGRESS_CHANGED
    return SurfaceParseOutcome.PARSER_FAILED
