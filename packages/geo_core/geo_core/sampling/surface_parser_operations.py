"""Parsing and fidelity operations for governed consumer-surface artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
import json
from types import MappingProxyType
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from geo_core.sampling.contracts import SamplingRuleViolation, canonical_hash
from geo_core.sampling.manual_artifact_governance import (
    StrictManualArtifactGovernance,
    wipe_bytearray,
)
from geo_core.sampling.surface_parser_contracts import (
    ARTIFACT_SCHEMA_VERSION,
    REQUIRED_FIXTURE_BLOCK_REASONS,
    ConsumerSurface,
    SurfaceArtifactCaptureKind,
    SurfaceBlockReason,
    SurfaceCitation,
    SurfaceParseOutcome,
    SurfaceParseResult,
    SurfaceParseSummary,
    SurfaceParserFidelityScore,
    SurfaceParserGoldCase,
    SurfaceParserRelease,
    _BLOCK_OUTCOME,
    _host,
    _https_url,
    _text,
)
from geo_core.sampling.surface_parser_releases import SURFACE_PARSER_RELEASES


def parse_surface_artifact(
    release: SurfaceParserRelease,
    artifact: Mapping[str, object],
    *,
    capture_kind: SurfaceArtifactCaptureKind,
) -> SurfaceParseResult:
    """Parse one redacted normalized artifact under an exact release."""

    try:
        values = _artifact_values(artifact, release)
    except (SamplingRuleViolation, TypeError, ValueError):
        return _blocked_result(
            release,
            capture_kind=capture_kind,
            reason=SurfaceBlockReason.INVALID_ARTIFACT,
        )
    blocking_state = cast(SurfaceBlockReason | None, values["blocking_state"])
    if blocking_state is not None:
        return _blocked_result(
            release,
            capture_kind=capture_kind,
            reason=blocking_state,
        )
    if not values["page_ready"]:
        return _blocked_result(
            release,
            capture_kind=capture_kind,
            reason=SurfaceBlockReason.PAGE_INCOMPLETE,
        )
    markers = values["surface_markers"]
    assert isinstance(markers, tuple)
    known_markers = {item.surface_marker for item in SURFACE_PARSER_RELEASES}
    foreign_markers = set(markers) & (known_markers - {release.surface_marker})
    if foreign_markers:
        return _blocked_result(
            release,
            capture_kind=capture_kind,
            reason=SurfaceBlockReason.WRONG_SURFACE,
        )
    answer_blocks = values["answer_blocks"]
    citations = values["citations"]
    assert isinstance(answer_blocks, tuple)
    assert isinstance(citations, tuple)
    surface_present = release.surface_marker in markers
    if not surface_present:
        ordinary = cast(tuple[str, ...], values["ordinary_result_markers"])
        if "ordinary_results_ready" not in ordinary or answer_blocks or citations or markers:
            return _blocked_result(
                release,
                capture_kind=capture_kind,
                reason=SurfaceBlockReason.SELECTOR_DRIFT,
            )
        return SurfaceParseResult(
            parser_release_id=release.id,
            parser_release_hash=release.release_hash,
            platform=release.platform,
            surface=release.surface,
            capture_kind=capture_kind,
            outcome=SurfaceParseOutcome.SURFACE_NOT_PRESENT,
            block_reason=None,
            answer_text=None,
            answer_locators=(),
            citations=(),
            content_eligible=True,
        )
    if len(markers) != 1 or not answer_blocks:
        return _blocked_result(
            release,
            capture_kind=capture_kind,
            reason=SurfaceBlockReason.SELECTOR_DRIFT,
        )
    answer_text = "\n".join(item[0] for item in answer_blocks)
    answer_locators = tuple(item[1] for item in answer_blocks)
    return SurfaceParseResult(
        parser_release_id=release.id,
        parser_release_hash=release.release_hash,
        platform=release.platform,
        surface=release.surface,
        capture_kind=capture_kind,
        outcome=SurfaceParseOutcome.CAPTURED,
        block_reason=None,
        answer_text=answer_text,
        answer_locators=answer_locators,
        citations=citations,
        content_eligible=True,
    )


def parse_governed_manual_surface_artifact(
    release: SurfaceParserRelease,
    *,
    evidence_kind: str,
    content_type: str,
    content: bytearray,
    governance_policy_key: str,
    pre_redacted_attestation: bool,
) -> SurfaceParseResult:
    """Parse only the redacted derivative produced by the manual governor."""

    if evidence_kind != "transcript_export" or content_type != "application/json":
        raise SamplingRuleViolation(
            "surface parsing requires a structured transcript JSON artifact"
        )
    governed = StrictManualArtifactGovernance().govern(
        evidence_kind=evidence_kind,
        content_type=content_type,
        content=content,
        governance_policy_key=governance_policy_key,
        pre_redacted_attestation=pre_redacted_attestation,
    )
    try:
        payload = json.loads(bytes(governed.payload))
        if not isinstance(payload, dict) or payload.get("source_kind") != "json":
            raise SamplingRuleViolation("governed surface artifact envelope is invalid")
        artifact = payload.get("content")
        if not isinstance(artifact, dict):
            raise SamplingRuleViolation("governed surface artifact content is invalid")
        return parse_surface_artifact(
            release,
            artifact,
            capture_kind=SurfaceArtifactCaptureKind.MANUAL_UI,
        )
    finally:
        wipe_bytearray(governed.payload)


def score_surface_parser_release(
    release: SurfaceParserRelease,
    cases: Sequence[SurfaceParserGoldCase],
) -> SurfaceParserFidelityScore:
    if not cases:
        raise SamplingRuleViolation("surface parser fidelity suite cannot be empty")
    classifications = 0
    captured_count = 0
    absence_count = 0
    ordinary_false_positives = 0
    blocked_as_absence = 0
    expected_answer_characters = 0
    matching_answer_characters = 0
    expected_citation_items = 0
    matching_citation_items = 0
    reason_counts = {reason: 0 for reason in REQUIRED_FIXTURE_BLOCK_REASONS}
    case_results: list[dict[str, object]] = []
    for case in cases:
        result = parse_surface_artifact(
            release,
            case.artifact,
            capture_kind=SurfaceArtifactCaptureKind.FIXTURE,
        )
        classification_match = (
            result.outcome is case.expected_outcome
            and result.block_reason is case.expected_block_reason
        )
        classifications += int(classification_match)
        captured_count += int(case.expected_outcome is SurfaceParseOutcome.CAPTURED)
        absence_count += int(case.expected_outcome is SurfaceParseOutcome.SURFACE_NOT_PRESENT)
        if case.expected_block_reason in reason_counts:
            reason_counts[case.expected_block_reason] += 1
        ordinary_false_positives += int(
            case.expected_outcome is SurfaceParseOutcome.SURFACE_NOT_PRESENT
            and result.outcome is SurfaceParseOutcome.CAPTURED
        )
        blocked_as_absence += int(
            case.expected_block_reason is not None
            and result.outcome is SurfaceParseOutcome.SURFACE_NOT_PRESENT
        )
        expected_answer = case.expected_answer_text or ""
        actual_answer = result.answer_text or ""
        expected_answer_characters += len(expected_answer)
        matching_answer_characters += _matching_prefix_length(expected_answer, actual_answer)
        actual_citations = tuple((item.url, item.title) for item in result.citations)
        expected_citation_items += max(len(case.expected_citations), len(actual_citations))
        matching_citation_items += sum(
            expected == actual
            for expected, actual in zip(case.expected_citations, actual_citations, strict=False)
        )
        case_results.append(
            {
                "case_id": case.case_id,
                "result_hash": result.parser_result_hash,
                "classification_match": classification_match,
            }
        )
    fixture_count = len(cases)
    classification_accuracy = Decimal(classifications) / Decimal(fixture_count)
    answer_completeness = (
        Decimal(matching_answer_characters) / Decimal(expected_answer_characters)
        if expected_answer_characters
        else Decimal(1)
    )
    citation_accuracy = (
        Decimal(matching_citation_items) / Decimal(expected_citation_items)
        if expected_citation_items
        else Decimal(1)
    )
    fixture_ready = (
        fixture_count >= 30
        and captured_count >= 10
        and absence_count >= 5
        and all(reason_counts[reason] >= 2 for reason in REQUIRED_FIXTURE_BLOCK_REASONS)
        and classification_accuracy >= Decimal("0.95")
        and answer_completeness >= Decimal("0.99")
        and citation_accuracy == Decimal(1)
        and ordinary_false_positives == 0
        and blocked_as_absence == 0
    )
    score_value = {
        "parser_release_id": str(release.id),
        "parser_release_hash": release.release_hash,
        "fixture_count": fixture_count,
        "captured_count": captured_count,
        "absence_count": absence_count,
        "block_reason_counts": {
            reason.value: reason_counts[reason] for reason in REQUIRED_FIXTURE_BLOCK_REASONS
        },
        "classification_accuracy": str(classification_accuracy),
        "answer_text_completeness": str(answer_completeness),
        "citation_accuracy": str(citation_accuracy),
        "ordinary_result_false_positive_count": ordinary_false_positives,
        "blocked_as_valid_absence_count": blocked_as_absence,
        "fixture_ready": fixture_ready,
        "cases": case_results,
    }
    return SurfaceParserFidelityScore(
        parser_release_id=release.id,
        parser_release_hash=release.release_hash,
        fixture_count=fixture_count,
        captured_count=captured_count,
        absence_count=absence_count,
        block_reason_counts=MappingProxyType(reason_counts),
        classification_accuracy=classification_accuracy,
        answer_text_completeness=answer_completeness,
        citation_accuracy=citation_accuracy,
        ordinary_result_false_positive_count=ordinary_false_positives,
        blocked_as_valid_absence_count=blocked_as_absence,
        fixture_ready=fixture_ready,
        score_hash=canonical_hash(score_value),
    )


def surface_parse_summary_from_mapping(value: object) -> SurfaceParseSummary | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise SamplingRuleViolation("surface parse summary is invalid")
    expected = set(SurfaceParseSummary.__dataclass_fields__) - {"summary_hash"}
    persisted = set(value)
    if persisted != expected | {"schema_version", "summary_hash"}:
        raise SamplingRuleViolation("surface parse summary fields are invalid")
    if value.get("schema_version") != "surface-parse-summary-v1":
        raise SamplingRuleViolation("surface parse summary version is invalid")
    try:
        summary = SurfaceParseSummary(
            parser_release_id=UUID(str(value.get("parser_release_id"))),
            parser_release_hash=str(value.get("parser_release_hash")),
            platform=str(value.get("platform")),
            surface=ConsumerSurface(str(value.get("surface"))),
            capture_kind=SurfaceArtifactCaptureKind(str(value.get("capture_kind"))),
            outcome=SurfaceParseOutcome(str(value.get("outcome"))),
            block_reason=(
                None
                if value.get("block_reason") is None
                else SurfaceBlockReason(str(value.get("block_reason")))
            ),
            content_eligible=_boolean(value.get("content_eligible")),
            automated_capture=_boolean(value.get("automated_capture")),
            live_capture_eligible=_boolean(value.get("live_capture_eligible")),
            answer_text_hash=(
                None
                if value.get("answer_text_hash") is None
                else str(value.get("answer_text_hash"))
            ),
            answer_character_count=_nonnegative_integer(value.get("answer_character_count")),
            citation_count=_nonnegative_integer(value.get("citation_count")),
            citation_set_hash=str(value.get("citation_set_hash")),
            locator_set_hash=str(value.get("locator_set_hash")),
            parser_result_hash=str(value.get("parser_result_hash")),
        )
    except (TypeError, ValueError) as error:
        raise SamplingRuleViolation("surface parse summary is invalid") from error
    if summary.summary_hash != value.get("summary_hash"):
        raise SamplingRuleViolation("surface parse summary hash differs")
    return summary


def _artifact_values(
    artifact: Mapping[str, object], release: SurfaceParserRelease
) -> dict[str, object]:
    expected = {
        "schema_version",
        "platform",
        "surface",
        "final_url",
        "page_ready",
        "surface_markers",
        "ordinary_result_markers",
        "answer_blocks",
        "citations",
        "blocking_state",
        "follow_up_count",
    }
    if set(artifact) != expected:
        raise SamplingRuleViolation("surface artifact fields are invalid")
    if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise SamplingRuleViolation("surface artifact version is invalid")
    if (
        artifact.get("platform") != release.platform
        or artifact.get("surface") != release.surface.value
    ):
        raise SamplingRuleViolation("surface artifact identity differs from parser release")
    final_url = _https_url(
        _text_value(artifact.get("final_url"), "surface artifact final URL", maximum=2_000)
    )
    if _host(urlsplit(final_url).hostname or "") not in release.allowed_hosts:
        raise SamplingRuleViolation("surface artifact final URL is outside release allowlist")
    page_ready = artifact.get("page_ready")
    if not isinstance(page_ready, bool):
        raise SamplingRuleViolation("surface artifact page readiness is invalid")
    markers = _string_tuple(artifact.get("surface_markers"), "surface markers")
    ordinary = _string_tuple(artifact.get("ordinary_result_markers"), "ordinary result markers")
    answer_blocks = _answer_blocks(artifact.get("answer_blocks"))
    citations = _citations(artifact.get("citations"))
    blocking_raw = artifact.get("blocking_state")
    blocking = (
        None
        if blocking_raw is None
        else SurfaceBlockReason(_text_value(blocking_raw, "surface blocking state", maximum=100))
    )
    follow_up_count = _nonnegative_integer(artifact.get("follow_up_count"))
    return {
        "final_url": final_url,
        "page_ready": page_ready,
        "surface_markers": markers,
        "ordinary_result_markers": ordinary,
        "answer_blocks": answer_blocks,
        "citations": citations,
        "blocking_state": blocking,
        "follow_up_count": follow_up_count,
    }


def _answer_blocks(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or len(value) > 100:
        raise SamplingRuleViolation("surface answer blocks are invalid")
    result: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"text", "locator"}:
            raise SamplingRuleViolation("surface answer block is invalid")
        result.append(
            (
                _text_value(item.get("text"), "surface answer block", maximum=50_000),
                _text_value(item.get("locator"), "surface answer locator", maximum=500),
            )
        )
    if len({locator for _, locator in result}) != len(result):
        raise SamplingRuleViolation("surface answer locators must be unique")
    return tuple(result)


def _citations(value: object) -> tuple[SurfaceCitation, ...]:
    if not isinstance(value, list) or len(value) > 200:
        raise SamplingRuleViolation("surface citations are invalid")
    result: list[SurfaceCitation] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {
            "url",
            "title",
            "position",
            "locator",
        }:
            raise SamplingRuleViolation("surface citation is invalid")
        result.append(
            SurfaceCitation(
                url=_text_value(item.get("url"), "surface citation URL", maximum=2_000),
                title=_text_value(item.get("title"), "surface citation title", maximum=500),
                position=_positive_integer(item.get("position")),
                locator=_text_value(item.get("locator"), "surface citation locator", maximum=500),
            )
        )
    ordered = tuple(sorted(result, key=lambda item: item.position))
    if ordered and tuple(item.position for item in ordered) != tuple(range(1, len(ordered) + 1)):
        raise SamplingRuleViolation("surface citation order is incomplete")
    if len({item.locator for item in ordered}) != len(ordered):
        raise SamplingRuleViolation("surface citation locators must be unique")
    return ordered


def _blocked_result(
    release: SurfaceParserRelease,
    *,
    capture_kind: SurfaceArtifactCaptureKind,
    reason: SurfaceBlockReason,
) -> SurfaceParseResult:
    return SurfaceParseResult(
        parser_release_id=release.id,
        parser_release_hash=release.release_hash,
        platform=release.platform,
        surface=release.surface,
        capture_kind=capture_kind,
        outcome=_BLOCK_OUTCOME[reason],
        block_reason=reason,
        answer_text=None,
        answer_locators=(),
        citations=(),
        content_eligible=False,
    )


def _matching_prefix_length(expected: str, actual: str) -> int:
    return next(
        (
            index
            for index, values in enumerate(zip(expected, actual, strict=False))
            if values[0] != values[1]
        ),
        min(len(expected), len(actual)),
    )


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 100:
        raise SamplingRuleViolation(f"{label} are invalid")
    items = tuple(_text_value(item, label, maximum=200) for item in value)
    if len(set(items)) != len(items):
        raise SamplingRuleViolation(f"{label} must be unique")
    return items


def _text_value(value: object, label: str, *, maximum: int = 200) -> str:
    if not isinstance(value, str):
        raise SamplingRuleViolation(f"{label} is invalid")
    return _text(value, label, maximum=maximum)


def _positive_integer(value: object) -> int:
    result = _nonnegative_integer(value)
    if result < 1:
        raise SamplingRuleViolation("surface artifact integer must be positive")
    return result


def _nonnegative_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SamplingRuleViolation("surface artifact integer is invalid")
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise SamplingRuleViolation("surface parse boolean is invalid")
    return value
