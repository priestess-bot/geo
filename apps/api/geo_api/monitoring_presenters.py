"""Shared customer-safe presentation of metric and report projections."""

from __future__ import annotations

from typing import Any, cast

from geo_api.monitoring_contracts import MetricResponse, MonitoringReportResponse
from geo_core.monitoring.domain import MetricSnapshot, MonitoringReport


def metric_response(item: MetricSnapshot) -> MetricResponse:
    return MetricResponse(
        id=item.id,
        project_id=item.project_id,
        protocol_id=item.protocol_id,
        campaign_id=item.campaign_id,
        measurement_window=item.measurement_window.value,
        expected_sample_count=item.expected_sample_count,
        eligible_sample_count=item.eligible_sample_count,
        recommendation_share=float(item.recommendation_share),
        product_mention_share=float(item.product_mention_share),
        placement_citation_share=float(item.placement_citation_share),
        qualified_destination_coverage=float(item.qualified_destination_coverage),
        verified_placement_coverage=float(item.verified_placement_coverage),
        competitive_delta=float(item.competitive_delta),
        status=cast(Any, item.status),
        confounded_reasons=list(item.confounded_reasons),
        method_version=item.method_version,
        computed_at=item.computed_at,
    )


def report_response(item: MonitoringReport) -> MonitoringReportResponse:
    return MonitoringReportResponse(
        id=item.id,
        project_id=item.project_id,
        protocol_id=item.protocol_id,
        campaign_id=item.campaign_id,
        metric_snapshot_id=item.metric_snapshot_id,
        title=item.title,
        body=item.body,
        methodology_statement=item.methodology_statement,
        report_hash=item.report_hash,
        status=cast(Any, item.status),
        generated_at=item.generated_at,
        approved_at=item.approved_at,
    )
