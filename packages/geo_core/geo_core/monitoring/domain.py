"""Pure monitoring rules with frozen denominators and non-causal reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Mapping, Sequence
from uuid import UUID

from geo_core.monitoring.source_contract import (
    CaptureMethod,
    ObservationSource,
    SourceStratumKey,
)


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
S3_URI_PATTERN = re.compile(r"^s3://[^/]+/.+$")
REPORT_METHODOLOGY = (
    "Observational monitoring only; results are non-causal and do not prove that a "
    "placement caused any change."
)
METRIC_METHOD_VERSION = "geo-observation-statistics-v2"
STATISTICS_CONTRACT_VERSION = "geo-observation-statistics-v2"
LEGACY_STATISTICS_CONTRACT_VERSION = "legacy-v1"
OBSERVATION_MEMBERSHIP_VERSION = "metric-observation-membership-v1"

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
    GOOGLE_AI_MODE = "google_ai_mode"
    GOOGLE_SEARCH = "google_search"
    PERPLEXITY = "perplexity"
    PERPLEXITY_ANSWER = "perplexity_answer"
    GEMINI = "gemini"
    BING_SEARCH = "bing_search"
    BING_COPILOT = "bing_copilot"
    CLAUDE_AI = "claude_ai"
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
    source_strata: tuple[SourceStratumKey, ...] = ()
    source_strata_hash: str | None = None
    minimum_valid_repeats: int | None = None
    statistics_method_version: str | None = None
    statistics_contract_version: str = LEGACY_STATISTICS_CONTRACT_VERSION
    question_set_id: UUID | None = None
    question_set_hash: str | None = None
    question_set_bound_by: UUID | None = None
    question_set_bound_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.locale.strip():
            raise MonitoringRuleViolation("protocol name and locale are required")
        if not 1 <= self.sample_size <= 1000:
            raise MonitoringRuleViolation("sample size must be between 1 and 1000")
        if not 1 <= self.window_days <= 365:
            raise MonitoringRuleViolation("window days must be between 1 and 365")
        hashes = tuple(item.canonical_hash() for item in self.source_strata)
        if len(set(hashes)) != len(hashes):
            raise MonitoringRuleViolation("protocol source strata must be unique")
        expected_hash = source_strata_inventory_hash(self.source_strata)
        if self.source_strata_hash is not None and self.source_strata_hash != expected_hash:
            raise MonitoringRuleViolation("protocol source strata hash does not match inventory")
        if (
            self.status == ProtocolStatus.FROZEN
            and self.source_strata
            and (self.source_strata_hash != expected_hash)
        ):
            raise MonitoringRuleViolation(
                "frozen protocols require a canonical source strata inventory"
            )
        if self.statistics_contract_version not in {
            LEGACY_STATISTICS_CONTRACT_VERSION,
            STATISTICS_CONTRACT_VERSION,
        }:
            raise MonitoringRuleViolation("protocol statistics contract is unsupported")
        if self.statistics_contract_version == STATISTICS_CONTRACT_VERSION:
            minimum = max(3, (4 * self.sample_size + 4) // 5)
            if self.sample_size < 3:
                raise MonitoringRuleViolation(
                    "statistics-v2 protocols require at least three repeats per query"
                )
            if self.minimum_valid_repeats is None or not (
                minimum <= self.minimum_valid_repeats <= self.sample_size
            ):
                raise MonitoringRuleViolation(
                    "minimum valid repeats must meet the frozen 80 percent threshold"
                )
            if self.statistics_method_version != METRIC_METHOD_VERSION:
                raise MonitoringRuleViolation(
                    "statistics-v2 protocol method version does not match"
                )
        elif self.minimum_valid_repeats is not None or (self.statistics_method_version is not None):
            raise MonitoringRuleViolation("legacy protocols cannot claim a statistics-v2 threshold")


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
    query_cluster_key: str | None = None


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
    query_cluster_key: str | None = None
    question_set_item_id: UUID | None = None
    question_candidate_id: UUID | None = None


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
    requested_eligible: bool
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
    configured_model: str | None
    provider_reported_model: str | None
    ui_surface: str
    ui_metadata: Mapping[str, object]
    confounding_factors: tuple[str, ...]
    observed_at: datetime
    source: ObservationSource
    query_cluster_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_result", MappingProxyType(dict(self.raw_result)))
        object.__setattr__(self, "ui_metadata", MappingProxyType(dict(self.ui_metadata)))
        if self.sample_index < 1:
            raise MonitoringRuleViolation("sample index must be positive")
        object.__setattr__(
            self,
            "query_cluster_key",
            self.query_cluster_key.strip() if self.query_cluster_key else None,
        )
        if not self.ui_surface.strip():
            raise MonitoringRuleViolation("observation surface is required")
        if self.result_status == ResultStatus.FAILED and self.eligible:
            raise MonitoringRuleViolation("failed observations cannot be eligible")
        if (self.artifact_uri is None) != (self.artifact_hash is None):
            raise MonitoringRuleViolation("artifact URI and hash must be supplied together")
        if self.artifact_uri and not S3_URI_PATTERN.fullmatch(self.artifact_uri):
            raise MonitoringRuleViolation("observation artifact must use an s3:// URI")
        if self.artifact_hash and not SHA256_PATTERN.fullmatch(self.artifact_hash):
            raise MonitoringRuleViolation("observation artifact hash must be lowercase SHA-256")
        if self.source.capture_method == CaptureMethod.OFFICIAL_REPORT_IMPORT:
            raise MonitoringRuleViolation(
                "official report imports use the dedicated report projection"
            )
        hard_violations = self.source.hard_violations()
        if hard_violations:
            raise MonitoringRuleViolation(
                "invalid observation source: " + ", ".join(hard_violations)
            )
        source_reasons = self.source.eligibility_reasons(
            result_succeeded=self.result_status == ResultStatus.SUCCEEDED
        )
        if self.eligible and source_reasons:
            raise MonitoringRuleViolation(
                "eligible observation is missing source evidence: " + ", ".join(source_reasons)
            )
        expected_eligible = self.requested_eligible and not source_reasons
        if self.eligible != expected_eligible:
            raise MonitoringRuleViolation("stored eligibility must be derived by the server")
        if not self.eligible:
            combined_reasons = tuple(sorted(set(self.ineligible_reasons) | set(source_reasons)))
            if not combined_reasons:
                raise MonitoringRuleViolation("ineligible observations require a reason")
            object.__setattr__(self, "ineligible_reasons", combined_reasons)
        if self.source.capture_method != CaptureMethod.UNKNOWN:
            legacy_model = self.source.configured_model.value
            legacy_reported_model = self.source.reported_model.value
            if self.configured_model != legacy_model:
                raise MonitoringRuleViolation("configured model does not match source identity")
            if self.provider_reported_model != legacy_reported_model:
                raise MonitoringRuleViolation("reported model does not match source identity")
            if self.ui_surface != self.source.surface.value:
                raise MonitoringRuleViolation("UI surface does not match source identity")
            evidence = self.source.raw_evidence
            if evidence.answer != (self.raw_answer.strip() if self.raw_answer else None):
                raise MonitoringRuleViolation("raw answer does not match source evidence")
            if evidence.kind.value == "inline_response" and dict(
                evidence.inline_response or {}
            ) != dict(self.raw_result):
                raise MonitoringRuleViolation("raw result does not match source evidence")
            if (evidence.artifact_uri, evidence.artifact_hash) != (
                self.artifact_uri,
                self.artifact_hash,
            ):
                raise MonitoringRuleViolation("raw artifact does not match source evidence")

    @property
    def source_stratum_hash(self) -> str:
        return self.source.source_identity_hash()

    def payload_hash(self) -> str:
        return canonical_hash(
            {
                "monitoring_query_id": str(self.monitoring_query_id),
                "measurement_window": self.measurement_window.value,
                "sample_index": self.sample_index,
                "result_status": self.result_status.value,
                "requested_eligible": self.requested_eligible,
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
                "source": self.source.canonical_value(),
                "query_cluster_key": self.query_cluster_key,
            }
        )


@dataclass(frozen=True)
class ObservationCitation:
    id: UUID
    citation_index: int
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
    captured_by: UUID
    created_at: datetime
    replayed: bool = False

    @property
    def included_in_metrics(self) -> bool:
        return (
            self.draft.result_status == ResultStatus.SUCCEEDED
            and self.draft.eligible
            and self.draft.source.capture_method
            not in {CaptureMethod.SYNTHETIC, CaptureMethod.UNKNOWN}
        )


@dataclass(frozen=True)
class MetricObservationMembership:
    snapshot_id: UUID
    observation_id: UUID
    payload_hash: str
    ordinal: int

    def __post_init__(self) -> None:
        if self.ordinal < 1:
            raise MonitoringRuleViolation("metric observation ordinal must be positive")
        if not SHA256_PATTERN.fullmatch(self.payload_hash):
            raise MonitoringRuleViolation(
                "metric observation payload hash must be lowercase SHA-256"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "observation_id": str(self.observation_id),
            "payload_hash": self.payload_hash,
            "ordinal": self.ordinal,
        }


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


def source_strata_inventory_hash(strata: Sequence[SourceStratumKey]) -> str:
    return canonical_hash(
        sorted((item.canonical_value() for item in strata), key=lambda item: canonical_hash(item))
    )


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
            "minimum_valid_repeats": protocol.minimum_valid_repeats,
            "statistics_method_version": protocol.statistics_method_version,
            "statistics_contract_version": protocol.statistics_contract_version,
            "source_strata": sorted(
                (item.canonical_value() for item in protocol.source_strata),
                key=lambda item: canonical_hash(item),
            ),
            "source_strata_hash": protocol.source_strata_hash,
            "question_set_id": (
                str(protocol.question_set_id) if protocol.question_set_id is not None else None
            ),
            "question_set_hash": protocol.question_set_hash,
            "queries": [
                {
                    "id": str(item.monitoring_query_id),
                    "text": item.query_text,
                    "kind": item.query_kind,
                    "locale": item.locale,
                    "ordinal": item.ordinal,
                    "query_cluster_key": item.query_cluster_key,
                    "question_set_item_id": (
                        str(item.question_set_item_id)
                        if item.question_set_item_id is not None
                        else None
                    ),
                }
                for item in sorted(queries, key=lambda item: item.ordinal)
            ],
        }
    )


from geo_core.monitoring.statistics import (  # noqa: E402
    BinaryEstimate as BinaryEstimate,
    MetricSnapshot as MetricSnapshot,
    QueryMetricResult as QueryMetricResult,
    analysis_stratum_hash as analysis_stratum_hash,
    calculate_metric_snapshot as calculate_metric_snapshot,
    metric_observation_membership as metric_observation_membership,
    observation_membership_hash as observation_membership_hash,
    render_report as render_report,
    select_metric_observations as select_metric_observations,
)
