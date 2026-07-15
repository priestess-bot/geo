"""Pure monitoring rules with frozen denominators and non-causal reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Mapping, Sequence
from uuid import UUID


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
S3_URI_PATTERN = re.compile(r"^s3://[^/]+/.+$")
REPORT_METHODOLOGY = (
    "Observational monitoring only; results are non-causal and do not prove that a "
    "placement caused any change."
)
METRIC_METHOD_VERSION = "geo-observational-v1"

READER_ROLES = frozenset({"owner", "admin", "analyst", "viewer", "customer"})
CONTRIBUTOR_ROLES = frozenset({"owner", "admin", "analyst"})
APPROVER_ROLES = frozenset({"owner", "admin"})


class MonitoringRuleViolation(ValueError):
    """A monitoring command violates a stable business rule."""


class MonitoringForbidden(RuntimeError):
    """The authenticated project role cannot perform the command."""


class MonitoringNotFound(RuntimeError):
    """A project-scoped monitoring resource does not exist."""


class MonitoringConflict(RuntimeError):
    """An immutable slot or idempotency key has conflicting content."""


class MonitoringPersistenceUnavailable(RuntimeError):
    """PostgreSQL could not complete a monitoring operation."""


class Platform(StrEnum):
    CHATGPT_SEARCH = "chatgpt_search"
    GOOGLE_AI_OVERVIEWS = "google_ai_overviews"
    GOOGLE_SEARCH = "google_search"
    PERPLEXITY = "perplexity"
    GEMINI = "gemini"
    OTHER = "other"


class Device(StrEnum):
    DESKTOP = "desktop"
    MOBILE = "mobile"
    TABLET = "tablet"


class MeasurementWindow(StrEnum):
    BASELINE = "baseline"
    T28 = "t28"
    T56 = "t56"
    T84 = "t84"
    AD_HOC = "ad_hoc"


class ProtocolStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    FROZEN = "frozen"


class SuggestionStatus(StrEnum):
    SUGGESTED = "suggested"
    APPROVED = "approved"
    REJECTED = "rejected"


class ResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class VerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MonitoringProtocol:
    id: UUID
    project_id: UUID
    campaign_id: UUID
    market_profile_id: UUID
    name: str
    platform: Platform
    locale: str
    device: Device
    sample_size: int
    window_days: int
    status: ProtocolStatus
    protocol_hash: str | None
    created_at: datetime
    approved_at: datetime | None = None
    frozen_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.locale.strip():
            raise MonitoringRuleViolation("protocol name and locale are required")
        if not 1 <= self.sample_size <= 1000:
            raise MonitoringRuleViolation("sample size must be between 1 and 1000")
        if not 1 <= self.window_days <= 365:
            raise MonitoringRuleViolation("window days must be between 1 and 365")


@dataclass(frozen=True)
class QuerySuggestion:
    id: UUID
    project_id: UUID
    protocol_id: UUID
    query_text: str
    query_kind: str
    rationale: str
    status: SuggestionStatus
    created_at: datetime
    monitoring_query_id: UUID | None = None


@dataclass(frozen=True)
class ProtocolQuery:
    id: UUID
    project_id: UUID
    protocol_id: UUID
    monitoring_query_id: UUID
    query_text: str
    query_kind: str
    locale: str
    ordinal: int


@dataclass(frozen=True)
class VerifiedCitationTarget:
    submission_id: UUID
    destination_id: UUID
    destination_key: str
    publication_channel: str
    url: str
    verified_at: datetime


@dataclass(frozen=True)
class CitationDraft:
    url: str
    title: str | None
    verification_status: VerificationStatus
    verified_at: datetime | None
    destination_id: UUID | None = None
    submission_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.url.startswith(("https://", "http://")):
            raise MonitoringRuleViolation("citation URL must use HTTP or HTTPS")
        if (self.verification_status == VerificationStatus.PASSED) != (
            self.verified_at is not None
        ):
            raise MonitoringRuleViolation(
                "passed citation verification requires exactly one verified_at value"
            )
        if self.verification_status == VerificationStatus.PASSED and (
            self.submission_id is None or self.destination_id is None
        ):
            raise MonitoringRuleViolation(
                "passed citations require verified submission and destination lineage"
            )


@dataclass(frozen=True)
class ObservationDraft:
    monitoring_query_id: UUID
    measurement_window: MeasurementWindow
    sample_index: int
    result_status: ResultStatus
    eligible: bool
    ineligible_reasons: tuple[str, ...]
    url_verification_status: VerificationStatus
    recommendation_present: bool
    primary_product_mentioned: bool
    competitor_mentioned: bool
    raw_answer: str | None
    raw_result: Mapping[str, object]
    citations: tuple[CitationDraft, ...]
    artifact_uri: str | None
    artifact_hash: str | None
    configured_model: str
    provider_reported_model: str | None
    ui_surface: str
    ui_metadata: Mapping[str, object]
    confounding_factors: tuple[str, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_result", MappingProxyType(dict(self.raw_result)))
        object.__setattr__(self, "ui_metadata", MappingProxyType(dict(self.ui_metadata)))
        if self.sample_index < 1:
            raise MonitoringRuleViolation("sample index must be positive")
        if not self.configured_model.strip() or not self.ui_surface.strip():
            raise MonitoringRuleViolation("configured model and UI surface are required")
        if not self.eligible and not self.ineligible_reasons:
            raise MonitoringRuleViolation("ineligible observations require a reason")
        if self.result_status == ResultStatus.FAILED and self.eligible:
            raise MonitoringRuleViolation("failed observations cannot be eligible")
        if (self.artifact_uri is None) != (self.artifact_hash is None):
            raise MonitoringRuleViolation("artifact URI and hash must be supplied together")
        if self.artifact_uri and not S3_URI_PATTERN.fullmatch(self.artifact_uri):
            raise MonitoringRuleViolation("observation artifact must use an s3:// URI")
        if self.artifact_hash and not SHA256_PATTERN.fullmatch(self.artifact_hash):
            raise MonitoringRuleViolation("observation artifact hash must be lowercase SHA-256")

    def payload_hash(self) -> str:
        return canonical_hash(
            {
                "monitoring_query_id": str(self.monitoring_query_id),
                "measurement_window": self.measurement_window.value,
                "sample_index": self.sample_index,
                "result_status": self.result_status.value,
                "eligible": self.eligible,
                "ineligible_reasons": list(self.ineligible_reasons),
                "url_verification_status": self.url_verification_status.value,
                "recommendation_present": self.recommendation_present,
                "primary_product_mentioned": self.primary_product_mentioned,
                "competitor_mentioned": self.competitor_mentioned,
                "raw_answer": self.raw_answer,
                "raw_result": dict(self.raw_result),
                "citations": [
                    {
                        "url": item.url,
                        "title": item.title,
                        "verification_status": item.verification_status.value,
                        "verified_at": item.verified_at.isoformat() if item.verified_at else None,
                        "destination_id": str(item.destination_id) if item.destination_id else None,
                        "submission_id": str(item.submission_id) if item.submission_id else None,
                    }
                    for item in self.citations
                ],
                "artifact_uri": self.artifact_uri,
                "artifact_hash": self.artifact_hash,
                "configured_model": self.configured_model,
                "provider_reported_model": self.provider_reported_model,
                "ui_surface": self.ui_surface,
                "ui_metadata": dict(self.ui_metadata),
                "confounding_factors": list(self.confounding_factors),
                "observed_at": self.observed_at.isoformat(),
            }
        )


@dataclass(frozen=True)
class ObservationCitation:
    id: UUID
    url: str
    title: str | None
    verification_status: VerificationStatus
    destination_id: UUID | None
    submission_id: UUID | None
    verified_placement: bool


@dataclass(frozen=True)
class MonitoringObservation:
    id: UUID
    project_id: UUID
    protocol_id: UUID
    campaign_id: UUID
    draft: ObservationDraft
    payload_hash: str
    citations: tuple[ObservationCitation, ...]
    created_at: datetime
    replayed: bool = False

    @property
    def included_in_metrics(self) -> bool:
        return (
            self.draft.result_status == ResultStatus.SUCCEEDED
            and self.draft.eligible
        )


@dataclass(frozen=True)
class MetricSnapshot:
    id: UUID
    project_id: UUID
    protocol_id: UUID
    campaign_id: UUID
    measurement_window: MeasurementWindow
    expected_sample_count: int
    eligible_sample_count: int
    recommendation_share: Decimal
    product_mention_share: Decimal
    placement_citation_share: Decimal
    qualified_destination_coverage: Decimal
    verified_placement_coverage: Decimal
    competitive_delta: Decimal
    status: str
    confounded_reasons: tuple[str, ...]
    input_hash: str
    method_version: str
    computed_at: datetime


@dataclass(frozen=True)
class MonitoringReport:
    id: UUID
    project_id: UUID
    protocol_id: UUID
    campaign_id: UUID
    metric_snapshot_id: UUID
    title: str
    body: str
    methodology_statement: str
    report_hash: str
    status: str
    generated_at: datetime
    approved_at: datetime | None


@dataclass(frozen=True)
class VerifiedUrl:
    campaign_id: UUID
    protocol_ids: tuple[UUID, ...]
    url: str
    title: str | None
    destination_id: UUID | None
    first_verified_at: datetime
    observation_count: int


@dataclass(frozen=True)
class CampaignDestinationState:
    selected_destination_ids: frozenset[UUID]
    qualified_destination_ids: frozenset[UUID]
    verified_destination_ids: frozenset[UUID]


def canonical_hash(value: object) -> str:
    serialized = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def protocol_hash(protocol: MonitoringProtocol, queries: Sequence[ProtocolQuery]) -> str:
    return canonical_hash(
        {
            "market_profile_id": str(protocol.market_profile_id),
            "campaign_id": str(protocol.campaign_id),
            "platform": protocol.platform.value,
            "locale": protocol.locale,
            "device": protocol.device.value,
            "sample_size": protocol.sample_size,
            "window_days": protocol.window_days,
            "queries": [
                {
                    "id": str(item.monitoring_query_id),
                    "text": item.query_text,
                    "kind": item.query_kind,
                    "locale": item.locale,
                    "ordinal": item.ordinal,
                }
                for item in sorted(queries, key=lambda item: item.ordinal)
            ],
        }
    )


def calculate_metric_snapshot(
    *,
    snapshot_id: UUID,
    protocol: MonitoringProtocol,
    query_count: int,
    window: MeasurementWindow,
    observations: Sequence[MonitoringObservation],
    destination_state: CampaignDestinationState,
    computed_at: datetime,
) -> MetricSnapshot:
    if protocol.status != ProtocolStatus.FROZEN or not protocol.protocol_hash:
        raise MonitoringRuleViolation("metrics require a frozen monitoring protocol")
    expected = query_count * protocol.sample_size
    if expected <= 0:
        raise MonitoringRuleViolation("frozen protocol has no approved query inventory")
    window_observations = [
        item
        for item in observations
        if item.draft.measurement_window == window
        and item.project_id == protocol.project_id
        and item.protocol_id == protocol.id
        and item.campaign_id == protocol.campaign_id
    ]
    included = [item for item in window_observations if item.included_in_metrics]
    denominator = len(included)
    reasons: set[str] = set()
    if denominator != expected:
        reasons.add("incomplete_or_ineligible_sample_set")
    if any(item.draft.result_status == ResultStatus.FAILED for item in window_observations):
        reasons.add("failed_samples")
    collection_configs = {
        (
            item.draft.configured_model,
            item.draft.provider_reported_model,
            item.draft.ui_surface,
        )
        for item in included
    }
    if len(collection_configs) > 1:
        reasons.add("mixed_collection_configuration")
    if any(item.draft.confounding_factors for item in window_observations):
        reasons.add("declared_confounding_factors")
    if not destination_state.selected_destination_ids:
        reasons.add("no_selected_destinations")
    if not destination_state.qualified_destination_ids:
        reasons.add("no_qualified_destinations")

    observations_with_valid_campaign_citation = 0
    for observation in included:
        has_valid_campaign_citation = False
        if observation.draft.url_verification_status != VerificationStatus.PASSED:
            continue
        for citation in observation.citations:
            if (
                citation.verified_placement
                and citation.submission_id is not None
                and citation.verification_status == VerificationStatus.PASSED
                and citation.destination_id in destination_state.selected_destination_ids
            ):
                has_valid_campaign_citation = True
        observations_with_valid_campaign_citation += int(has_valid_campaign_citation)

    recommendation_share = _ratio(
        sum(item.draft.recommendation_present for item in included), denominator
    )
    product_share = _ratio(
        sum(item.draft.primary_product_mentioned for item in included), denominator
    )
    competitor_share = _ratio(
        sum(item.draft.competitor_mentioned for item in included), denominator
    )
    selected_denominator = len(destination_state.selected_destination_ids)
    qualified_denominator = len(destination_state.qualified_destination_ids)
    input_hash = canonical_hash(
        {
            "protocol_hash": protocol.protocol_hash,
            "window": window.value,
            "observation_hashes": sorted(item.payload_hash for item in window_observations),
            "selected_destination_ids": sorted(
                map(str, destination_state.selected_destination_ids)
            ),
            "qualified_destination_ids": sorted(
                map(str, destination_state.qualified_destination_ids)
            ),
            "verified_destination_ids": sorted(
                map(str, destination_state.verified_destination_ids)
            ),
            "method_version": METRIC_METHOD_VERSION,
        }
    )
    return MetricSnapshot(
        id=snapshot_id,
        project_id=protocol.project_id,
        protocol_id=protocol.id,
        campaign_id=protocol.campaign_id,
        measurement_window=window,
        expected_sample_count=expected,
        eligible_sample_count=denominator,
        recommendation_share=recommendation_share,
        product_mention_share=product_share,
        placement_citation_share=_ratio(
            observations_with_valid_campaign_citation, denominator
        ),
        qualified_destination_coverage=_ratio(
            len(destination_state.qualified_destination_ids), selected_denominator
        ),
        verified_placement_coverage=_ratio(
            len(
                destination_state.verified_destination_ids
                & destination_state.qualified_destination_ids
            ),
            qualified_denominator,
        ),
        competitive_delta=_quantize(product_share - competitor_share),
        status="confounded" if reasons else "complete",
        confounded_reasons=tuple(sorted(reasons)),
        input_hash=input_hash,
        method_version=METRIC_METHOD_VERSION,
        computed_at=computed_at,
    )


def render_report(snapshot: MetricSnapshot, title: str) -> tuple[str, str]:
    if not title.strip():
        raise MonitoringRuleViolation("report title is required")
    confounded = (
        " This window is confounded: " + ", ".join(snapshot.confounded_reasons) + "."
        if snapshot.confounded_reasons
        else ""
    )
    body = (
        f"Window {snapshot.measurement_window.value} contains "
        f"{snapshot.eligible_sample_count} eligible observations against a frozen denominator "
        f"of {snapshot.expected_sample_count}. Recommendation share was "
        f"{snapshot.recommendation_share}; product mention share was "
        f"{snapshot.product_mention_share}; placement citation share was "
        f"{snapshot.placement_citation_share}; qualified destination coverage was "
        f"{snapshot.qualified_destination_coverage}; verified placement coverage was "
        f"{snapshot.verified_placement_coverage}; competitive delta was "
        f"{snapshot.competitive_delta}.{confounded} {REPORT_METHODOLOGY}"
    )
    return body, canonical_hash(
        {
            "title": title.strip(),
            "body": body,
            "methodology_statement": REPORT_METHODOLOGY,
            "metric_snapshot_id": str(snapshot.id),
        }
    )


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0.000000")
    return _quantize(Decimal(numerator) / Decimal(denominator))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
