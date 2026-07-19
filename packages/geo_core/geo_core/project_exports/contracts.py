"""Strict, public-field-only inputs for project-level audit exports."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from enum import StrEnum
from typing import Any, Iterable, Mapping, TypeVar, cast
from uuid import UUID

from geo_core.monitoring.source_contract import (
    LEGACY_SOURCE_STRATUM_CONTRACT_VERSION,
    SOURCE_CONTRACT_VERSION,
)
from geo_core.project_exports.constants import (
    LEGACY_STATISTICS_CONTRACT_VERSION,
    METRIC_METHOD_VERSION,
)
from geo_core.project_exports.errors import ProjectExportRuleViolation
from geo_core.project_exports.field_validation import (
    aware_time as _time,
    boolean as _bool,
    lineage_ids as _lineage_ids,
    optional_sha256 as _optional_hash,
    optional_text as _optional_text,
    optional_time as _optional_time,
    optional_uuid as _optional_uuid,
    positive_int as _positive_int,
    required_text as _required_text,
    sha256 as _hash,
    uuid_value as _uuid,
)
from geo_core.project_exports.legacy_statistics_contracts import (
    AnyMetricSnapshotExportRecord,
    LegacyMetricSnapshotExportRecord,
)
from geo_core.project_exports.membership_contracts import (
    MetricObservationMembershipExportRecord,
)
from geo_core.project_exports.statistics_contracts import MetricSnapshotExportRecord


_Record = TypeVar("_Record")


class ExportAudience(StrEnum):
    ADMIN = "admin"
    CUSTOMER = "customer"


@dataclass(frozen=True)
class ProjectExportScope:
    project_id: UUID
    campaign_id: UUID | None = None

    def __post_init__(self) -> None:
        _uuid(self.project_id, "scope project_id")
        _optional_uuid(self.campaign_id, "scope campaign_id")


@dataclass(frozen=True)
class ProtocolExportRecord:
    id: UUID
    project_id: UUID
    campaign_id: UUID
    name: str
    platform: str
    locale: str
    device: str
    sample_size: int
    window_days: int
    status: str
    protocol_hash: str | None
    source_strata_hash: str | None
    minimum_valid_repeats: int | None
    statistics_method_version: str | None
    statistics_contract_version: str
    approved_at: datetime | None
    frozen_at: datetime | None

    def __post_init__(self) -> None:
        _lineage_ids(self)
        _uuid(self.id, "protocol id")
        _required_text(self.name, "protocol name")
        for name in ("platform", "locale", "device", "status"):
            _required_text(getattr(self, name), f"protocol {name}")
        _positive_int(self.sample_size, "protocol sample_size")
        _positive_int(self.window_days, "protocol window_days")
        _optional_hash(self.protocol_hash, "protocol_hash")
        _optional_hash(self.source_strata_hash, "source_strata_hash")
        if self.statistics_contract_version == METRIC_METHOD_VERSION:
            threshold = max(3, (4 * self.sample_size + 4) // 5)
            if (
                self.minimum_valid_repeats is None
                or not threshold <= self.minimum_valid_repeats <= self.sample_size
                or self.statistics_method_version != METRIC_METHOD_VERSION
            ):
                raise ProjectExportRuleViolation(
                    "statistics-v2 protocol threshold or method is inconsistent"
                )
        elif self.statistics_contract_version == LEGACY_STATISTICS_CONTRACT_VERSION:
            if self.minimum_valid_repeats is not None or self.statistics_method_version is not None:
                raise ProjectExportRuleViolation(
                    "legacy protocol cannot claim statistics-v2 fields"
                )
        else:
            raise ProjectExportRuleViolation("protocol statistics contract is unsupported")
        _optional_time(self.approved_at, "protocol approved_at")
        _optional_time(self.frozen_at, "protocol frozen_at")


@dataclass(frozen=True)
class QueryExportRecord:
    id: UUID
    project_id: UUID
    campaign_id: UUID
    protocol_id: UUID
    monitoring_query_id: UUID
    query_text: str
    query_kind: str
    locale: str
    ordinal: int
    query_cluster_key: str | None

    def __post_init__(self) -> None:
        _lineage_ids(self)
        _uuid(self.id, "query row id")
        _uuid(self.protocol_id, "query protocol_id")
        _uuid(self.monitoring_query_id, "query monitoring_query_id")
        _required_text(self.query_text, "query_text")
        _required_text(self.query_kind, "query_kind")
        _required_text(self.locale, "query locale")
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ProjectExportRuleViolation("query ordinal must be a non-negative integer")
        _optional_text(self.query_cluster_key, "query_cluster_key")


@dataclass(frozen=True)
class ProtocolSourceStratumExportRecord:
    project_id: UUID
    campaign_id: UUID
    protocol_id: UUID
    source_stratum_hash: str
    source_contract_version: str
    capture_method: str
    platform: str
    platform_detail: str | None
    surface: str
    surface_detail: str | None
    surface_kind: str
    engine: str
    configured_model_state: str
    configured_model: str | None
    reported_model_state: str
    reported_model: str | None
    locale: str
    region: str
    language: str
    device: str
    client_kind: str
    search_enabled: bool
    search_mode: str

    def __post_init__(self) -> None:
        _lineage_ids(self)
        _uuid(self.protocol_id, "source stratum protocol_id")
        _hash(self.source_stratum_hash, "protocol source_stratum_hash")
        if self.source_contract_version not in {
            LEGACY_SOURCE_STRATUM_CONTRACT_VERSION,
            SOURCE_CONTRACT_VERSION,
        }:
            raise ProjectExportRuleViolation("protocol source stratum contract is unsupported")
        for label in (
            "capture_method",
            "platform",
            "surface",
            "surface_kind",
            "engine",
            "configured_model_state",
            "reported_model_state",
            "locale",
            "region",
            "language",
            "device",
            "client_kind",
            "search_mode",
        ):
            _required_text(getattr(self, label), f"protocol source stratum {label}")
        _bool(self.search_enabled, "protocol source stratum search_enabled")
        _optional_text(self.configured_model, "configured_model")
        _optional_text(self.reported_model, "reported_model")
        _optional_text(self.platform_detail, "platform_detail")
        _optional_text(self.surface_detail, "surface_detail")
        if self.source_contract_version == LEGACY_SOURCE_STRATUM_CONTRACT_VERSION:
            if self.platform_detail is not None or self.surface_detail is not None:
                raise ProjectExportRuleViolation(
                    "legacy protocol source stratum cannot carry detail fields"
                )
            return
        if (self.platform == "other") != (self.platform_detail is not None):
            raise ProjectExportRuleViolation(
                "platform_detail is required exactly for OTHER platform"
            )
        if (self.surface == "other") != (self.surface_detail is not None):
            raise ProjectExportRuleViolation("surface_detail is required exactly for OTHER surface")


@dataclass(frozen=True)
class ObservationExportRecord:
    id: UUID
    project_id: UUID
    campaign_id: UUID
    protocol_id: UUID
    monitoring_query_id: UUID
    query_cluster_key: str | None
    measurement_window: str
    source_stratum_hash: str | None
    sample_index: int
    result_status: str
    eligible: bool
    url_verification_status: str
    recommendation_present: bool
    primary_product_mentioned: bool
    competitor_mentioned: bool
    ineligible_reasons: tuple[str, ...]
    confounding_factors: tuple[str, ...]
    capture_method: str
    platform: str
    surface: str
    engine: str | None
    answer_text: str | None
    payload_hash: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _lineage_ids(self)
        _uuid(self.id, "observation id")
        _uuid(self.protocol_id, "observation protocol_id")
        _uuid(self.monitoring_query_id, "observation monitoring_query_id")
        _optional_text(self.query_cluster_key, "observation query_cluster_key")
        _optional_hash(self.source_stratum_hash, "observation source_stratum_hash")
        _hash(self.payload_hash, "observation payload_hash")
        _positive_int(self.sample_index, "observation sample_index")
        _required_text(self.measurement_window, "observation measurement_window")
        _required_text(self.capture_method, "observation capture_method")
        _required_text(self.platform, "observation platform")
        _required_text(self.surface, "observation surface")
        if self.result_status not in {"succeeded", "failed"}:
            raise ProjectExportRuleViolation(
                "observation result_status must be succeeded or failed"
            )
        if self.url_verification_status not in {"passed", "failed", "unknown"}:
            raise ProjectExportRuleViolation("observation url_verification_status is unsupported")
        _optional_text(self.engine, "observation engine")
        _optional_text(self.answer_text, "observation answer_text", allow_empty=True)
        _bool(self.eligible, "observation eligible")
        _bool(self.recommendation_present, "observation recommendation_present")
        _bool(self.primary_product_mentioned, "observation primary_product_mentioned")
        _bool(self.competitor_mentioned, "observation competitor_mentioned")
        for name in ("ineligible_reasons", "confounding_factors"):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise ProjectExportRuleViolation(f"observation {name} must be a tuple")
            for value in values:
                _required_text(value, f"observation {name}")
            if len(set(values)) != len(values):
                raise ProjectExportRuleViolation(f"observation {name} must be unique")
        _time(self.observed_at, "observation observed_at")
        if self.eligible and (self.source_stratum_hash is None or self.query_cluster_key is None):
            raise ProjectExportRuleViolation(
                "eligible observation requires source stratum and query cluster"
            )
        if self.eligible and self.ineligible_reasons:
            raise ProjectExportRuleViolation("eligible observation has ineligible reasons")


@dataclass(frozen=True)
class CitationExportRecord:
    observation_id: UUID
    citation_index: int
    project_id: UUID
    campaign_id: UUID
    protocol_id: UUID
    url: str
    title: str | None
    verification_status: str
    verified_placement: bool
    destination_id: UUID | None
    submission_id: UUID | None
    verified_at: datetime | None

    def __post_init__(self) -> None:
        _lineage_ids(self)
        _uuid(self.observation_id, "citation observation_id")
        _uuid(self.protocol_id, "citation protocol_id")
        _optional_uuid(self.destination_id, "citation destination_id")
        _optional_uuid(self.submission_id, "citation submission_id")
        if not isinstance(self.citation_index, int) or isinstance(self.citation_index, bool):
            raise ProjectExportRuleViolation("citation_index must be an integer")
        if self.citation_index < 0:
            raise ProjectExportRuleViolation("citation_index must be non-negative")
        if not self.url.startswith(("https://", "http://")):
            raise ProjectExportRuleViolation("citation URL must use HTTP or HTTPS")
        if self.verification_status not in {"passed", "failed", "unknown"}:
            raise ProjectExportRuleViolation("citation verification_status is unsupported")
        _optional_text(self.title, "citation title", allow_empty=True)
        _bool(self.verified_placement, "citation verified_placement")
        _optional_time(self.verified_at, "citation verified_at")
        if self.verified_placement and (
            self.verification_status != "passed"
            or self.destination_id is None
            or self.submission_id is None
            or self.verified_at is None
        ):
            raise ProjectExportRuleViolation(
                "verified placement citation requires passed status and complete lineage"
            )


@dataclass(frozen=True)
class ApprovedReportExportRecord:
    id: UUID
    project_id: UUID
    campaign_id: UUID
    protocol_id: UUID
    metric_snapshot_id: UUID
    title: str
    body: str
    methodology_statement: str
    report_hash: str
    generated_at: datetime
    approved_at: datetime

    def __post_init__(self) -> None:
        _lineage_ids(self)
        _uuid(self.id, "approved report id")
        _uuid(self.protocol_id, "approved report protocol_id")
        _uuid(self.metric_snapshot_id, "approved report metric_snapshot_id")
        _required_text(self.title, "report title")
        _required_text(self.body, "report body")
        _required_text(self.methodology_statement, "report methodology_statement")
        _hash(self.report_hash, "report_hash")
        _time(self.generated_at, "report generated_at")
        _time(self.approved_at, "report approved_at")


@dataclass(frozen=True)
class VerifiedUrlExportRecord:
    project_id: UUID
    campaign_id: UUID
    protocol_ids: tuple[UUID, ...]
    url: str
    title: str | None
    destination_id: UUID | None
    first_verified_at: datetime
    observation_count: int

    def __post_init__(self) -> None:
        _lineage_ids(self)
        _optional_uuid(self.destination_id, "verified URL destination_id")
        if not self.url.startswith(("https://", "http://")):
            raise ProjectExportRuleViolation("verified URL must use HTTP or HTTPS")
        if not self.protocol_ids or len(set(self.protocol_ids)) != len(self.protocol_ids):
            raise ProjectExportRuleViolation(
                "verified URL protocol_ids must be a non-empty unique tuple"
            )
        if not isinstance(self.protocol_ids, tuple):
            raise ProjectExportRuleViolation("verified URL protocol_ids must be a tuple")
        for protocol_id in self.protocol_ids:
            _uuid(protocol_id, "verified URL protocol_id")
        _optional_text(self.title, "verified URL title", allow_empty=True)
        _positive_int(self.observation_count, "verified URL observation_count")
        _time(self.first_verified_at, "verified URL first_verified_at")


@dataclass(frozen=True)
class ProjectExportData:
    protocols: tuple[ProtocolExportRecord, ...]
    protocol_source_strata: tuple[ProtocolSourceStratumExportRecord, ...]
    queries: tuple[QueryExportRecord, ...]
    observations: tuple[ObservationExportRecord, ...]
    citations: tuple[CitationExportRecord, ...]
    metric_snapshots: tuple[AnyMetricSnapshotExportRecord, ...]
    metric_observation_memberships: tuple[MetricObservationMembershipExportRecord, ...]
    approved_reports: tuple[ApprovedReportExportRecord, ...]
    verified_urls: tuple[VerifiedUrlExportRecord, ...]

    def __post_init__(self) -> None:
        for name in (
            "protocols",
            "protocol_source_strata",
            "queries",
            "observations",
            "citations",
            "metric_snapshots",
            "metric_observation_memberships",
            "approved_reports",
            "verified_urls",
        ):
            if not isinstance(getattr(self, name), tuple):
                raise ProjectExportRuleViolation(f"export collection {name} must be a tuple")

    @classmethod
    def from_mappings(
        cls,
        *,
        protocols: Iterable[Mapping[str, object]] = (),
        protocol_source_strata: Iterable[Mapping[str, object]] = (),
        queries: Iterable[Mapping[str, object]] = (),
        observations: Iterable[Mapping[str, object]] = (),
        citations: Iterable[Mapping[str, object]] = (),
        metric_snapshots: Iterable[Mapping[str, object]] = (),
        metric_observation_memberships: Iterable[Mapping[str, object]] = (),
        approved_reports: Iterable[Mapping[str, object]] = (),
        verified_urls: Iterable[Mapping[str, object]] = (),
    ) -> ProjectExportData:
        """Build typed rows and reject every non-whitelisted adapter field."""
        return cls(
            protocols=_strict_records(ProtocolExportRecord, protocols),
            protocol_source_strata=_strict_records(
                ProtocolSourceStratumExportRecord, protocol_source_strata
            ),
            queries=_strict_records(QueryExportRecord, queries),
            observations=_strict_records(ObservationExportRecord, observations),
            citations=_strict_records(CitationExportRecord, citations),
            metric_snapshots=_strict_metric_records(metric_snapshots),
            metric_observation_memberships=_strict_records(
                MetricObservationMembershipExportRecord,
                metric_observation_memberships,
            ),
            approved_reports=_strict_records(ApprovedReportExportRecord, approved_reports),
            verified_urls=_strict_records(VerifiedUrlExportRecord, verified_urls),
        )


@dataclass(frozen=True)
class AdminProjectExportInput:
    scope: ProjectExportScope
    data: ProjectExportData

    def __post_init__(self) -> None:
        from geo_core.project_exports.dataset_validation import validate_dataset

        validate_dataset(self.scope, self.data, customer=False)

    @property
    def audience(self) -> ExportAudience:
        return ExportAudience.ADMIN


@dataclass(frozen=True)
class CustomerApprovedProjectExportInput:
    scope: ProjectExportScope
    data: ProjectExportData

    def __post_init__(self) -> None:
        from geo_core.project_exports.dataset_validation import validate_dataset

        validate_dataset(self.scope, self.data, customer=True)

    @property
    def audience(self) -> ExportAudience:
        return ExportAudience.CUSTOMER


CustomerLatestApprovedProjectExportInput = CustomerApprovedProjectExportInput
ProjectExportInput = AdminProjectExportInput | CustomerApprovedProjectExportInput


def _strict_records(
    record_type: type[_Record], payloads: Iterable[Mapping[str, object]]
) -> tuple[_Record, ...]:
    allowed = {field.name for field in fields(cast(Any, record_type))}
    result: list[_Record] = []
    for index, payload in enumerate(payloads):
        supplied = set(payload)
        unexpected = supplied - allowed
        missing = allowed - supplied
        if unexpected:
            raise ProjectExportRuleViolation(
                f"{record_type.__name__}[{index}] contains non-whitelisted fields: "
                + ", ".join(sorted(unexpected))
            )
        if missing:
            raise ProjectExportRuleViolation(
                f"{record_type.__name__}[{index}] is missing fields: " + ", ".join(sorted(missing))
            )
        result.append(record_type(**payload))
    return tuple(result)


def _strict_metric_records(
    payloads: Iterable[Mapping[str, object]],
) -> tuple[AnyMetricSnapshotExportRecord, ...]:
    result: list[AnyMetricSnapshotExportRecord] = []
    for payload in payloads:
        record_type = (
            LegacyMetricSnapshotExportRecord
            if payload.get("statistics_contract_version") == LEGACY_STATISTICS_CONTRACT_VERSION
            else MetricSnapshotExportRecord
        )
        result.extend(_strict_records(record_type, (payload,)))
    return tuple(result)
