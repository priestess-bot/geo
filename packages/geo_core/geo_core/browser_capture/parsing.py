"""Deterministic classification of one captured consumer-surface page."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping
from uuid import UUID

from geo_core.browser_capture.domain import (
    BrowserCaptureError,
    EgressOutcome,
    EgressVerification,
    allowed_final_url,
)
from geo_core.connectors.contracts import canonical_hash


class CaptureOutcome(StrEnum):
    CAPTURED = "captured"
    SURFACE_NOT_PRESENT = "surface_not_present"
    CONSENT_REQUIRED = "consent_required"
    LOGIN_REQUIRED = "login_required"
    ACCESS_BLOCKED = "access_blocked"
    GEO_MISMATCH = "geo_mismatch"
    GEO_UNVERIFIED = "geo_unverified"
    EGRESS_CHANGED = "egress_changed"
    PARSER_FAILED = "parser_failed"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class SurfaceRelease:
    id: UUID
    platform: str
    surface: str
    release_hash: str
    parser_release: str
    allowed_hosts: tuple[str, ...]


@dataclass(frozen=True)
class Citation:
    title: str
    url: str
    position: int
    locator: str

    def value(self) -> dict[str, object]:
        return {
            "title": self.title,
            "url": self.url,
            "position": self.position,
            "locator": self.locator,
        }


@dataclass(frozen=True)
class PageSignals:
    final_url: str
    page_complete: bool
    detected_surface: str | None
    answer_text: str | None
    answer_locator: str | None
    citations: tuple[Citation, ...]
    page_country: str | None
    block_reason: str | None = None
    timed_out: bool = False


@dataclass(frozen=True)
class ParsedObservation:
    outcome: CaptureOutcome
    eligible: bool
    answer_text: str | None
    citations: tuple[Citation, ...]
    evidence_locators: Mapping[str, object]
    observation_hash: str


def parse_capture(
    *,
    release: SurfaceRelease,
    egress: EgressVerification,
    signals: PageSignals,
) -> ParsedObservation:
    allowed_final_url(signals.final_url, release.allowed_hosts)
    if egress.outcome is EgressOutcome.GEO_MISMATCH:
        outcome = CaptureOutcome.GEO_MISMATCH
    elif egress.outcome is EgressOutcome.GEO_UNVERIFIED:
        outcome = CaptureOutcome.GEO_UNVERIFIED
    elif egress.outcome is EgressOutcome.EGRESS_CHANGED:
        outcome = CaptureOutcome.EGRESS_CHANGED
    elif not egress.eligible:
        outcome = CaptureOutcome.GEO_UNVERIFIED
    elif (signals.page_country or "").upper() != "AU":
        outcome = CaptureOutcome.GEO_MISMATCH
    elif signals.timed_out:
        outcome = CaptureOutcome.TIMEOUT
    elif signals.block_reason:
        outcome = _blocked_outcome(signals.block_reason)
    elif not signals.page_complete:
        outcome = CaptureOutcome.PARSER_FAILED
    elif signals.detected_surface is None:
        if signals.answer_text or signals.citations:
            raise BrowserCaptureError("Surface absence carries answer evidence")
        outcome = CaptureOutcome.SURFACE_NOT_PRESENT
    elif signals.detected_surface != release.surface:
        outcome = CaptureOutcome.PARSER_FAILED
    elif not signals.answer_text or not signals.answer_locator:
        outcome = CaptureOutcome.PARSER_FAILED
    else:
        outcome = CaptureOutcome.CAPTURED
    eligible = outcome in {CaptureOutcome.CAPTURED, CaptureOutcome.SURFACE_NOT_PRESENT}
    answer = signals.answer_text if outcome is CaptureOutcome.CAPTURED else None
    citations = signals.citations if outcome is CaptureOutcome.CAPTURED else ()
    locators: dict[str, object] = {
        "answer": signals.answer_locator if answer else None,
        "citations": [item.locator for item in citations],
        "final_url": signals.final_url,
        "page_country": signals.page_country,
        "egress_verification_id": str(egress.id),
    }
    value = {
        "surface_release_id": str(release.id),
        "surface_release_hash": release.release_hash,
        "parser_release": release.parser_release,
        "outcome": outcome.value,
        "eligible": eligible,
        "answer_text": answer,
        "citations": [item.value() for item in citations],
        "evidence_locators": locators,
        "egress_verification_hash": egress.verification_hash,
    }
    return ParsedObservation(
        outcome=outcome,
        eligible=eligible,
        answer_text=answer,
        citations=citations,
        evidence_locators=locators,
        observation_hash=canonical_hash(value),
    )


def _blocked_outcome(reason: str) -> CaptureOutcome:
    normalized = reason.strip().casefold()
    if normalized == "consent":
        return CaptureOutcome.CONSENT_REQUIRED
    if normalized == "login":
        return CaptureOutcome.LOGIN_REQUIRED
    if normalized in {"captcha", "rate_limit", "ban"}:
        return CaptureOutcome.ACCESS_BLOCKED
    return CaptureOutcome.PARSER_FAILED


__all__ = [
    "CaptureOutcome",
    "Citation",
    "PageSignals",
    "ParsedObservation",
    "SurfaceRelease",
    "parse_capture",
]
