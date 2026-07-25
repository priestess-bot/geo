"""Stable contracts for governed consumer-surface parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from urllib.parse import urlsplit
from uuid import UUID

from geo_core.sampling.contracts import (
    SHA256_PATTERN,
    SamplingRuleViolation,
    canonical_hash,
)


SURFACE_PARSER_NAMESPACE = UUID("03df56b0-d344-57d1-9484-d5caebdd1ba2")
ARTIFACT_SCHEMA_VERSION = "consumer-surface-artifact-v1"
PARSER_ENGINE_VERSION = "consumer-surface-parser-v1"


class ConsumerSurface(StrEnum):
    GOOGLE_AI_OVERVIEWS = "google_ai_overviews"
    GOOGLE_AI_MODE = "google_ai_mode"
    BING_COPILOT = "bing_copilot"


class SurfaceParserReleaseStatus(StrEnum):
    CANDIDATE = "candidate"
    FIXTURE_READY = "fixture_ready"


class SurfaceArtifactCaptureKind(StrEnum):
    FIXTURE = "fixture"
    MANUAL_UI = "manual_ui"


class SurfaceParseOutcome(StrEnum):
    CAPTURED = "captured"
    SURFACE_NOT_PRESENT = "surface_not_present"
    CONSENT_REQUIRED = "consent_required"
    LOGIN_REQUIRED = "login_required"
    ACCESS_BLOCKED = "access_blocked"
    GEO_MISMATCH = "geo_mismatch"
    EGRESS_CHANGED = "egress_changed"
    PARSER_FAILED = "parser_failed"
    TIMEOUT = "timeout"


class SurfaceBlockReason(StrEnum):
    CONSENT = "consent"
    LOGIN = "login"
    CAPTCHA = "captcha"
    RATE_LIMIT = "rate_limit"
    BAN = "ban"
    GEO_MISMATCH = "geo_mismatch"
    EGRESS_CHANGED = "egress_changed"
    TIMEOUT = "timeout"
    SELECTOR_DRIFT = "selector_drift"
    PAGE_INCOMPLETE = "page_incomplete"
    INVALID_ARTIFACT = "invalid_artifact"
    WRONG_SURFACE = "wrong_surface"


_BLOCK_OUTCOME: Mapping[SurfaceBlockReason, SurfaceParseOutcome] = MappingProxyType(
    {
        SurfaceBlockReason.CONSENT: SurfaceParseOutcome.CONSENT_REQUIRED,
        SurfaceBlockReason.LOGIN: SurfaceParseOutcome.LOGIN_REQUIRED,
        SurfaceBlockReason.CAPTCHA: SurfaceParseOutcome.ACCESS_BLOCKED,
        SurfaceBlockReason.RATE_LIMIT: SurfaceParseOutcome.ACCESS_BLOCKED,
        SurfaceBlockReason.BAN: SurfaceParseOutcome.ACCESS_BLOCKED,
        SurfaceBlockReason.GEO_MISMATCH: SurfaceParseOutcome.GEO_MISMATCH,
        SurfaceBlockReason.EGRESS_CHANGED: SurfaceParseOutcome.EGRESS_CHANGED,
        SurfaceBlockReason.TIMEOUT: SurfaceParseOutcome.TIMEOUT,
        SurfaceBlockReason.SELECTOR_DRIFT: SurfaceParseOutcome.PARSER_FAILED,
        SurfaceBlockReason.PAGE_INCOMPLETE: SurfaceParseOutcome.PARSER_FAILED,
        SurfaceBlockReason.INVALID_ARTIFACT: SurfaceParseOutcome.PARSER_FAILED,
        SurfaceBlockReason.WRONG_SURFACE: SurfaceParseOutcome.PARSER_FAILED,
    }
)

REQUIRED_FIXTURE_BLOCK_REASONS = (
    SurfaceBlockReason.CONSENT,
    SurfaceBlockReason.LOGIN,
    SurfaceBlockReason.CAPTCHA,
    SurfaceBlockReason.RATE_LIMIT,
    SurfaceBlockReason.GEO_MISMATCH,
    SurfaceBlockReason.EGRESS_CHANGED,
    SurfaceBlockReason.SELECTOR_DRIFT,
)


@dataclass(frozen=True)
class SurfaceParserRelease:
    id: UUID
    release_key: str
    release_version: str
    platform: str
    surface: ConsumerSurface
    surface_marker: str
    allowed_hosts: tuple[str, ...]
    artifact_schema_version: str = ARTIFACT_SCHEMA_VERSION
    parser_engine_version: str = PARSER_ENGINE_VERSION
    status: SurfaceParserReleaseStatus = SurfaceParserReleaseStatus.FIXTURE_READY
    automated_capture_eligible: bool = False
    release_hash: str = field(init=False)

    def __post_init__(self) -> None:
        release_key = _text(self.release_key, "surface parser release key")
        release_version = _text(self.release_version, "surface parser release version")
        platform = _text(self.platform, "surface parser platform")
        marker = _text(self.surface_marker, "surface parser marker")
        surface = ConsumerSurface(self.surface)
        status = SurfaceParserReleaseStatus(self.status)
        hosts = tuple(sorted({_host(item) for item in self.allowed_hosts}))
        if not hosts:
            raise SamplingRuleViolation("surface parser release requires an allowed host")
        if self.automated_capture_eligible:
            raise SamplingRuleViolation(
                "fixture/manual surface parser releases cannot enable automated capture"
            )
        definition = {
            "id": str(self.id),
            "release_key": release_key,
            "release_version": release_version,
            "platform": platform,
            "surface": surface.value,
            "surface_marker": marker,
            "allowed_hosts": list(hosts),
            "artifact_schema_version": self.artifact_schema_version,
            "parser_engine_version": self.parser_engine_version,
            "status": status.value,
            "automated_capture_eligible": False,
        }
        object.__setattr__(self, "release_key", release_key)
        object.__setattr__(self, "release_version", release_version)
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "surface", surface)
        object.__setattr__(self, "surface_marker", marker)
        object.__setattr__(self, "allowed_hosts", hosts)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "release_hash", canonical_hash(definition))


@dataclass(frozen=True)
class SurfaceCitation:
    url: str
    title: str
    position: int
    locator: str

    def __post_init__(self) -> None:
        url = _https_url(self.url)
        title = _text(self.title, "surface citation title", maximum=500)
        locator = _text(self.locator, "surface citation locator", maximum=500)
        if self.position < 1:
            raise SamplingRuleViolation("surface citation position must be positive")
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "locator", locator)

    def canonical_value(self) -> dict[str, object]:
        return {
            "url": self.url,
            "title": self.title,
            "position": self.position,
            "locator": self.locator,
        }


@dataclass(frozen=True, repr=False)
class SurfaceParseResult:
    parser_release_id: UUID
    parser_release_hash: str
    platform: str
    surface: ConsumerSurface
    capture_kind: SurfaceArtifactCaptureKind
    outcome: SurfaceParseOutcome
    block_reason: SurfaceBlockReason | None
    answer_text: str | None = field(repr=False)
    answer_locators: tuple[str, ...]
    citations: tuple[SurfaceCitation, ...] = field(repr=False)
    content_eligible: bool
    automated_capture: bool = False
    live_capture_eligible: bool = False
    parser_result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not SHA256_PATTERN.fullmatch(self.parser_release_hash):
            raise SamplingRuleViolation("surface parser release hash must be SHA-256")
        platform = _text(self.platform, "surface parse platform")
        surface = ConsumerSurface(self.surface)
        capture_kind = SurfaceArtifactCaptureKind(self.capture_kind)
        outcome = SurfaceParseOutcome(self.outcome)
        reason = None if self.block_reason is None else SurfaceBlockReason(self.block_reason)
        answer = _optional_text(self.answer_text, "surface answer", maximum=200_000)
        locators = tuple(
            _text(item, "surface answer locator", maximum=500) for item in self.answer_locators
        )
        citations = tuple(sorted(self.citations, key=lambda item: item.position))
        if len({item.position for item in citations}) != len(citations):
            raise SamplingRuleViolation("surface citation positions must be unique")
        if citations and tuple(item.position for item in citations) != tuple(
            range(1, len(citations) + 1)
        ):
            raise SamplingRuleViolation("surface citation positions must be contiguous")
        if self.automated_capture or self.live_capture_eligible:
            raise SamplingRuleViolation(
                "fixture/manual parser results cannot claim live automated capture"
            )
        if outcome is SurfaceParseOutcome.CAPTURED:
            if reason is not None or answer is None or not locators or not self.content_eligible:
                raise SamplingRuleViolation("captured surface result is incomplete")
        elif outcome is SurfaceParseOutcome.SURFACE_NOT_PRESENT:
            if reason is not None or answer is not None or locators or citations:
                raise SamplingRuleViolation("surface absence cannot include answer evidence")
            if not self.content_eligible:
                raise SamplingRuleViolation("validated surface absence must be content-eligible")
        elif reason is None or self.content_eligible or answer is not None or locators or citations:
            raise SamplingRuleViolation("blocked surface result has invalid eligibility")
        canonical = {
            "parser_release_id": str(self.parser_release_id),
            "parser_release_hash": self.parser_release_hash,
            "platform": platform,
            "surface": surface.value,
            "capture_kind": capture_kind.value,
            "outcome": outcome.value,
            "block_reason": reason.value if reason is not None else None,
            "answer_text": answer,
            "answer_locators": list(locators),
            "citations": [item.canonical_value() for item in citations],
            "content_eligible": self.content_eligible,
            "automated_capture": False,
            "live_capture_eligible": False,
        }
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "surface", surface)
        object.__setattr__(self, "capture_kind", capture_kind)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "block_reason", reason)
        object.__setattr__(self, "answer_text", answer)
        object.__setattr__(self, "answer_locators", locators)
        object.__setattr__(self, "citations", citations)
        object.__setattr__(self, "parser_result_hash", canonical_hash(canonical))


@dataclass(frozen=True)
class SurfaceParseSummary:
    parser_release_id: UUID
    parser_release_hash: str
    platform: str
    surface: ConsumerSurface
    capture_kind: SurfaceArtifactCaptureKind
    outcome: SurfaceParseOutcome
    block_reason: SurfaceBlockReason | None
    content_eligible: bool
    automated_capture: bool
    live_capture_eligible: bool
    answer_text_hash: str | None
    answer_character_count: int
    citation_count: int
    citation_set_hash: str
    locator_set_hash: str
    parser_result_hash: str
    summary_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.parser_release_id, UUID):
            raise SamplingRuleViolation("surface parser release ID must be a UUID")
        platform = _text(self.platform, "surface parse summary platform")
        surface = ConsumerSurface(self.surface)
        capture_kind = SurfaceArtifactCaptureKind(self.capture_kind)
        outcome = SurfaceParseOutcome(self.outcome)
        reason = None if self.block_reason is None else SurfaceBlockReason(self.block_reason)
        for digest in (
            self.parser_release_hash,
            self.citation_set_hash,
            self.locator_set_hash,
            self.parser_result_hash,
        ):
            if not SHA256_PATTERN.fullmatch(digest):
                raise SamplingRuleViolation("surface parse summary hashes must be SHA-256")
        if self.answer_text_hash is not None and not SHA256_PATTERN.fullmatch(
            self.answer_text_hash
        ):
            raise SamplingRuleViolation("surface answer hash must be SHA-256")
        if (
            isinstance(self.answer_character_count, bool)
            or not isinstance(self.answer_character_count, int)
            or isinstance(self.citation_count, bool)
            or not isinstance(self.citation_count, int)
            or self.answer_character_count < 0
            or self.citation_count < 0
        ):
            raise SamplingRuleViolation("surface parse summary counts cannot be negative")
        if not isinstance(self.content_eligible, bool):
            raise SamplingRuleViolation("surface parse summary eligibility must be boolean")
        if not isinstance(self.automated_capture, bool) or not isinstance(
            self.live_capture_eligible, bool
        ):
            raise SamplingRuleViolation("surface parse summary capture flags must be boolean")
        if self.automated_capture or self.live_capture_eligible:
            raise SamplingRuleViolation("manual surface summary cannot claim live capture")
        if (self.answer_text_hash is None) != (self.answer_character_count == 0):
            raise SamplingRuleViolation("surface answer summary is inconsistent")
        if outcome is SurfaceParseOutcome.CAPTURED:
            if (
                reason is not None
                or not self.content_eligible
                or self.answer_text_hash is None
                or self.answer_character_count == 0
            ):
                raise SamplingRuleViolation("captured surface summary is inconsistent")
        elif outcome is SurfaceParseOutcome.SURFACE_NOT_PRESENT:
            if (
                reason is not None
                or not self.content_eligible
                or self.answer_text_hash is not None
                or self.answer_character_count != 0
                or self.citation_count != 0
            ):
                raise SamplingRuleViolation("surface absence summary is inconsistent")
        elif (
            reason is None
            or _BLOCK_OUTCOME[reason] is not outcome
            or self.content_eligible
            or self.answer_text_hash is not None
            or self.answer_character_count != 0
            or self.citation_count != 0
        ):
            raise SamplingRuleViolation("blocked surface summary is inconsistent")
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "surface", surface)
        object.__setattr__(self, "capture_kind", capture_kind)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "block_reason", reason)
        object.__setattr__(self, "summary_hash", canonical_hash(self.canonical_value()))

    @classmethod
    def from_result(cls, result: SurfaceParseResult) -> SurfaceParseSummary:
        answer_hash = (
            canonical_hash({"answer_text": result.answer_text})
            if result.answer_text is not None
            else None
        )
        return cls(
            parser_release_id=result.parser_release_id,
            parser_release_hash=result.parser_release_hash,
            platform=result.platform,
            surface=result.surface,
            capture_kind=result.capture_kind,
            outcome=result.outcome,
            block_reason=result.block_reason,
            content_eligible=result.content_eligible,
            automated_capture=False,
            live_capture_eligible=False,
            answer_text_hash=answer_hash,
            answer_character_count=len(result.answer_text or ""),
            citation_count=len(result.citations),
            citation_set_hash=canonical_hash(
                {"citations": [item.canonical_value() for item in result.citations]}
            ),
            locator_set_hash=canonical_hash(
                {
                    "answer_locators": list(result.answer_locators),
                    "citation_locators": [item.locator for item in result.citations],
                }
            ),
            parser_result_hash=result.parser_result_hash,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "surface-parse-summary-v1",
            "parser_release_id": str(self.parser_release_id),
            "parser_release_hash": self.parser_release_hash,
            "platform": self.platform,
            "surface": self.surface.value,
            "capture_kind": self.capture_kind.value,
            "outcome": self.outcome.value,
            "block_reason": self.block_reason.value if self.block_reason is not None else None,
            "content_eligible": self.content_eligible,
            "automated_capture": self.automated_capture,
            "live_capture_eligible": self.live_capture_eligible,
            "answer_text_hash": self.answer_text_hash,
            "answer_character_count": self.answer_character_count,
            "citation_count": self.citation_count,
            "citation_set_hash": self.citation_set_hash,
            "locator_set_hash": self.locator_set_hash,
            "parser_result_hash": self.parser_result_hash,
        }

    def persisted_value(self) -> dict[str, object]:
        return {**self.canonical_value(), "summary_hash": self.summary_hash}


@dataclass(frozen=True)
class SurfaceParserGoldCase:
    case_id: str
    artifact: Mapping[str, object]
    expected_outcome: SurfaceParseOutcome
    expected_answer_text: str | None
    expected_citations: tuple[tuple[str, str], ...]
    expected_block_reason: SurfaceBlockReason | None


@dataclass(frozen=True)
class SurfaceParserFidelityScore:
    parser_release_id: UUID
    parser_release_hash: str
    fixture_count: int
    captured_count: int
    absence_count: int
    block_reason_counts: Mapping[SurfaceBlockReason, int]
    classification_accuracy: Decimal
    answer_text_completeness: Decimal
    citation_accuracy: Decimal
    ordinary_result_false_positive_count: int
    blocked_as_valid_absence_count: int
    fixture_ready: bool
    score_hash: str


def _text(value: str, label: str, *, maximum: int = 200) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise SamplingRuleViolation(f"{label} is invalid")
    return normalized


def _optional_text(value: str | None, label: str, *, maximum: int) -> str | None:
    return None if value is None else _text(value, label, maximum=maximum)


def _host(value: str) -> str:
    host = value.strip().casefold().rstrip(".")
    if not host or ":" in host or "/" in host:
        raise SamplingRuleViolation("surface parser host is invalid")
    return host


def _https_url(value: str) -> str:
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise SamplingRuleViolation("surface evidence URL must be credential-free HTTPS")
    return normalized
