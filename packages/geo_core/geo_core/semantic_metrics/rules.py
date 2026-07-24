"""Deterministic semantic metric rules that model judges cannot override."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import re
from urllib.parse import SplitResult, urlsplit, urlunsplit

from geo_core.semantic_metrics.contracts import (
    CitationInput,
    EvidenceLocator,
    EvidenceLocatorKind,
    MetricObservation,
    SemanticMetricRuleViolation,
    SubjectAssertion,
    SubjectInventory,
)


@dataclass(frozen=True)
class MentionMatch:
    alias: str
    locator: EvidenceLocator


def brand_mentions(
    observation: MetricObservation, subjects: SubjectInventory
) -> tuple[MentionMatch, ...]:
    return find_alias_mentions(observation, subjects.brand_aliases)


def product_mentions(
    observation: MetricObservation, subjects: SubjectInventory
) -> tuple[MentionMatch, ...]:
    return find_alias_mentions(observation, subjects.product_aliases)


def competitor_mentions(
    observation: MetricObservation, subjects: SubjectInventory
) -> tuple[MentionMatch, ...]:
    return find_alias_mentions(
        observation,
        tuple(alias for _, aliases in subjects.competitors for alias in aliases),
    )


def find_alias_mentions(
    observation: MetricObservation, aliases: tuple[str, ...]
) -> tuple[MentionMatch, ...]:
    matches: list[MentionMatch] = []
    occupied: list[tuple[int, int]] = []
    for alias in sorted(set(aliases), key=lambda item: (-len(item), item.casefold())):
        pattern = re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(observation.answer_text):
            span = (match.start(), match.end())
            if any(start < span[1] and span[0] < end for start, end in occupied):
                continue
            occupied.append(span)
            matches.append(
                MentionMatch(
                    alias=alias,
                    locator=EvidenceLocator(
                        kind=EvidenceLocatorKind.ANSWER_SPAN,
                        reference_id=str(observation.id),
                        version=observation.artifact_version,
                        content_hash=observation.payload_hash,
                        start=match.start(),
                        end=match.end(),
                    ),
                )
            )
    return tuple(sorted(matches, key=lambda item: (item.locator.start or 0, item.locator.end or 0)))


def competitor_relative_position(
    observation: MetricObservation, subjects: SubjectInventory
) -> Decimal:
    primary = (*brand_mentions(observation, subjects), *product_mentions(observation, subjects))
    competitors = competitor_mentions(observation, subjects)
    primary_position = min(
        (item.locator.start for item in primary if item.locator.start is not None),
        default=None,
    )
    competitor_position = min(
        (item.locator.start for item in competitors if item.locator.start is not None),
        default=None,
    )
    if primary_position is None and competitor_position is None:
        return Decimal(0)
    if competitor_position is None:
        return Decimal(1)
    if primary_position is None:
        return Decimal(-1)
    if primary_position < competitor_position:
        return Decimal(1)
    if competitor_position < primary_position:
        return Decimal(-1)
    return Decimal(0)


def subject_mixups(observation: MetricObservation) -> tuple[SubjectAssertion, ...]:
    invalid: list[SubjectAssertion] = []
    for assertion in observation.subject_assertions:
        locator = assertion.locator
        if locator.reference_id != str(observation.id):
            raise SemanticMetricRuleViolation("subject assertion belongs to another observation")
        assert locator.start is not None and locator.end is not None
        if (
            locator.version != observation.artifact_version
            or locator.content_hash != observation.payload_hash
            or locator.end > len(observation.answer_text)
            or (
                locator.redacted_quote_hash is not None
                and _sha256(observation.answer_text[locator.start : locator.end])
                != locator.redacted_quote_hash
            )
        ):
            raise SemanticMetricRuleViolation("subject assertion span does not match answer text")
        if assertion.claimed_subject_key != assertion.catalog_subject_key:
            invalid.append(assertion)
    return tuple(invalid)


def citation_order_valid(citations: tuple[CitationInput, ...]) -> bool:
    return [item.ordinal for item in citations] == list(range(1, len(citations) + 1))


def citation_position_score(citation: CitationInput) -> Decimal:
    return Decimal(1) / Decimal(citation.ordinal)


def canonical_url(value: str) -> str:
    raw = value.strip()
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise SemanticMetricRuleViolation("metric citation URL must be absolute HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise SemanticMetricRuleViolation("metric citation URL cannot contain credentials")
    scheme = parsed.scheme.lower()
    host = parsed.hostname.casefold().encode("idna").decode("ascii")
    try:
        port = parsed.port
    except ValueError as error:
        raise SemanticMetricRuleViolation("metric citation URL port is invalid") from error
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit(SplitResult(scheme, netloc, path, parsed.query, ""))


def verified_url_hit(citation: CitationInput, verified_urls: tuple[str, ...]) -> bool:
    canonical_verified = {canonical_url(item) for item in verified_urls}
    return canonical_url(citation.url) in canonical_verified


def source_domain(citation: CitationInput) -> str:
    parsed = urlsplit(canonical_url(citation.url))
    assert parsed.hostname is not None
    return parsed.hostname


def source_domain_diversity(citations: tuple[CitationInput, ...]) -> int:
    return len({source_domain(item) for item in citations})


def source_type_diversity(citations: tuple[CitationInput, ...]) -> int:
    return len({item.source_type for item in citations})


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
