"""Row-to-domain mapping for monitoring PostgreSQL adapters."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from geo_core.monitoring.domain import (
    Device,
    MeasurementWindow,
    MetricSnapshot,
    MonitoringProtocol,
    MonitoringReport,
    ObservationCitation,
    Platform,
    ProtocolQuery,
    ProtocolStatus,
    QuerySuggestion,
    SuggestionStatus,
    VerificationStatus,
)


def protocol_from_row(row: Mapping[str, Any]) -> MonitoringProtocol:
    return MonitoringProtocol(
        id=cast(UUID, row["id"]), project_id=cast(UUID, row["project_id"]),
        campaign_id=cast(UUID, row["campaign_id"]),
        market_profile_id=cast(UUID, row["market_profile_id"]), name=str(row["name"]),
        platform=Platform(str(row["platform"])), locale=str(row["locale"]),
        device=Device(str(row["device"])), sample_size=int(row["sample_size"]),
        window_days=int(row["window_days"]), status=ProtocolStatus(str(row["status"])),
        protocol_hash=cast(str | None, row["protocol_hash"]),
        created_at=cast(datetime, row["created_at"]),
        approved_at=cast(datetime | None, row["approved_at"]),
        frozen_at=cast(datetime | None, row["frozen_at"]),
    )


def suggestion_from_row(row: Mapping[str, Any]) -> QuerySuggestion:
    return QuerySuggestion(
        id=cast(UUID, row["id"]), project_id=cast(UUID, row["project_id"]),
        protocol_id=cast(UUID, row["protocol_id"]), query_text=str(row["query_text"]),
        query_kind=str(row["query_kind"]), rationale=str(row["rationale"]),
        status=SuggestionStatus(str(row["status"])), created_at=cast(datetime, row["created_at"]),
        monitoring_query_id=cast(UUID | None, row.get("monitoring_query_id")),
    )


def protocol_query_from_row(row: Mapping[str, Any]) -> ProtocolQuery:
    return ProtocolQuery(
        id=cast(UUID, row["id"]), project_id=cast(UUID, row["project_id"]),
        protocol_id=cast(UUID, row["protocol_id"]),
        monitoring_query_id=cast(UUID, row["monitoring_query_id"]),
        query_text=str(row["query_text_snapshot"]),
        query_kind=str(row["query_kind_snapshot"]), locale=str(row["locale_snapshot"]),
        ordinal=int(row["ordinal"]),
    )


def citation_from_row(row: Mapping[str, Any]) -> ObservationCitation:
    return ObservationCitation(
        id=cast(UUID, row["id"]), url=str(row["url"]),
        title=cast(str | None, row["title"]),
        verification_status=VerificationStatus(str(row["verification_status"])),
        destination_id=cast(UUID | None, row["destination_id"]),
        submission_id=cast(UUID | None, row["submission_id"]),
        verified_placement=bool(row["verified_placement"]),
    )


def metric_from_row(row: Mapping[str, Any]) -> MetricSnapshot:
    return MetricSnapshot(
        id=cast(UUID, row["id"]), project_id=cast(UUID, row["project_id"]),
        protocol_id=cast(UUID, row["protocol_id"]),
        campaign_id=cast(UUID, row["campaign_id"]),
        measurement_window=MeasurementWindow(str(row["measurement_window"])),
        expected_sample_count=int(row["expected_sample_count"]),
        eligible_sample_count=int(row["eligible_sample_count"]),
        recommendation_share=Decimal(row["recommendation_share"]),
        product_mention_share=Decimal(row["product_mention_share"]),
        placement_citation_share=Decimal(row["placement_citation_share"]),
        qualified_destination_coverage=Decimal(row["qualified_destination_coverage"]),
        verified_placement_coverage=Decimal(row["verified_placement_coverage"]),
        competitive_delta=Decimal(row["competitive_delta"]), status=str(row["status"]),
        confounded_reasons=tuple(row["confounded_reasons"]), input_hash=str(row["input_hash"]),
        method_version=str(row["method_version"]), computed_at=cast(datetime, row["computed_at"]),
    )


def report_from_row(row: Mapping[str, Any]) -> MonitoringReport:
    return MonitoringReport(
        id=cast(UUID, row["id"]), project_id=cast(UUID, row["project_id"]),
        protocol_id=cast(UUID, row["protocol_id"]),
        campaign_id=cast(UUID, row["campaign_id"]),
        metric_snapshot_id=cast(UUID, row["metric_snapshot_id"]), title=str(row["title"]),
        body=str(row["body"]), methodology_statement=str(row["methodology_statement"]),
        report_hash=str(row["report_hash"]), status=str(row["status"]),
        generated_at=cast(datetime, row["generated_at"]),
        approved_at=cast(datetime | None, row["approved_at"]),
    )
