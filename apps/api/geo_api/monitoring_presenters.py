"""Shared customer-safe presentation of metric and report projections."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

from geo_api.monitoring_contracts import (
    BinaryEstimateResponse,
    MetricResponse,
    MonitoringReportResponse,
    QueryMetricResultResponse,
)
from geo_core.monitoring.domain import BinaryEstimate, MetricSnapshot, MonitoringReport
from geo_api.monitoring_source_adapters import source_stratum_contract


def metric_response(item: MetricSnapshot) -> MetricResponse:
    return MetricResponse(
        id=item.id,
        project_id=item.project_id,
        protocol_id=item.protocol_id,
        campaign_id=item.campaign_id,
        measurement_window=item.measurement_window.value,
        capture_method=cast(
            Any,
            item.source_stratum.capture_method.value
            if item.source_stratum is not None
            else "unknown",
        ),
        source_stratum=(
            source_stratum_contract(item.source_stratum)
            if item.source_stratum is not None
            else None
        ),
        source_stratum_hash=item.source_stratum_hash,
        statistics_contract_version=item.statistics_contract_version,
        query_cluster_key=item.query_cluster_key,
        analysis_stratum_hash=item.analysis_stratum_hash,
        minimum_valid_repeats=item.minimum_valid_repeats,
        expected_sample_count=item.expected_sample_count,
        sampled_sample_count=item.sampled_sample_count,
        eligible_sample_count=item.eligible_sample_count,
        invalid_sample_count=item.invalid_sample_count,
        missing_sample_count=item.missing_sample_count,
        sampling_completion_ratio=_optional_float(item.sampling_completion_ratio),
        valid_completion_ratio=_optional_float(item.valid_completion_ratio),
        query_count=item.query_count,
        sufficient_query_count=item.sufficient_query_count,
        invalid_reason_counts=dict(item.invalid_reason_counts),
        declared_confounding_factors=list(item.declared_confounding_factors),
        query_results=[
            QueryMetricResultResponse(
                monitoring_query_id=result.monitoring_query_id,
                query_text_snapshot=result.query_text_snapshot,
                query_cluster_key=result.query_cluster_key,
                expected_sample_count=result.expected_sample_count,
                sampled_sample_count=result.sampled_sample_count,
                valid_sample_count=result.valid_sample_count,
                invalid_sample_count=result.invalid_sample_count,
                missing_sample_count=result.missing_sample_count,
                meets_threshold=result.meets_threshold,
                invalid_reason_counts=dict(result.invalid_reason_counts),
                confounding_factors=list(result.confounding_factors),
                recommendation=_estimate_response(result.recommendation),
                product_mention=_estimate_response(result.product_mention),
                placement_citation=_estimate_response(result.placement_citation),
                competitor=_estimate_response(result.competitor),
                competitive_delta=float(result.competitive_delta),
            )
            for result in item.query_results
        ],
        recommendation_share=float(item.recommendation_share),
        recommendation_ci_low=_optional_float(item.recommendation_ci_low),
        recommendation_ci_high=_optional_float(item.recommendation_ci_high),
        product_mention_share=float(item.product_mention_share),
        product_mention_ci_low=_optional_float(item.product_mention_ci_low),
        product_mention_ci_high=_optional_float(item.product_mention_ci_high),
        placement_citation_share=float(item.placement_citation_share),
        placement_citation_ci_low=_optional_float(item.placement_citation_ci_low),
        placement_citation_ci_high=_optional_float(item.placement_citation_ci_high),
        recommendation_query_min=_optional_float(item.recommendation_query_min),
        recommendation_query_max=_optional_float(item.recommendation_query_max),
        product_mention_query_min=_optional_float(item.product_mention_query_min),
        product_mention_query_max=_optional_float(item.product_mention_query_max),
        placement_citation_query_min=_optional_float(item.placement_citation_query_min),
        placement_citation_query_max=_optional_float(item.placement_citation_query_max),
        worst_query_id=item.worst_query_id,
        selected_destination_ids=list(item.selected_destination_ids),
        qualified_destination_ids=list(item.qualified_destination_ids),
        verified_destination_ids=list(item.verified_destination_ids),
        qualified_destination_coverage=float(item.qualified_destination_coverage),
        verified_placement_coverage=float(item.verified_placement_coverage),
        competitive_delta=float(item.competitive_delta),
        status=cast(Any, item.status),
        confounded_reasons=list(item.confounded_reasons),
        input_hash=item.input_hash,
        method_version=item.method_version,
        result_hash=item.result_hash,
        observation_membership_version=item.observation_membership_version,
        observation_membership_hash=item.observation_membership_hash,
        observation_membership_count=item.observation_membership_count,
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


def _estimate_response(item: BinaryEstimate) -> BinaryEstimateResponse:
    return BinaryEstimateResponse(
        numerator=item.numerator,
        denominator=item.denominator,
        share=float(item.share),
        ci_low=float(item.ci_low),
        ci_high=float(item.ci_high),
    )


def _optional_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
