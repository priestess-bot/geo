"""Canonical F021 result projection used to verify exported snapshot hashes."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from typing import Mapping

from geo_core.project_exports.statistics_contracts import (
    MetricEstimateExportRecord,
    MetricSnapshotExportRecord,
    QueryMetricResultExportRecord,
)


def metric_result_hash(
    snapshot: MetricSnapshotExportRecord,
    source_stratum: Mapping[str, object],
) -> str:
    serialized = json.dumps(
        metric_result_value(snapshot, source_stratum),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def metric_result_value(
    snapshot: MetricSnapshotExportRecord,
    source_stratum: Mapping[str, object],
) -> dict[str, object]:
    value: dict[str, object] = {
        "statistics_contract_version": snapshot.statistics_contract_version,
        "method_version": snapshot.method_version,
        "input_hash": snapshot.input_hash,
        "source_stratum": dict(source_stratum),
        "source_stratum_hash": snapshot.source_stratum_hash,
        "query_cluster_key": snapshot.query_cluster_key,
        "analysis_stratum_hash": snapshot.analysis_stratum_hash,
        "measurement_window": snapshot.measurement_window,
        "minimum_valid_repeats": snapshot.minimum_valid_repeats,
        "expected_sample_count": snapshot.expected_sample_count,
        "sampled_sample_count": snapshot.sampled_sample_count,
        "eligible_sample_count": snapshot.eligible_sample_count,
        "invalid_sample_count": snapshot.invalid_sample_count,
        "missing_sample_count": snapshot.missing_sample_count,
        "sampling_completion_ratio": _number(snapshot.sampling_completion_ratio),
        "valid_completion_ratio": _number(snapshot.valid_completion_ratio),
        "query_count": snapshot.query_count,
        "sufficient_query_count": snapshot.sufficient_query_count,
        "invalid_reason_counts": {
            item.reason: item.count
            for item in sorted(snapshot.invalid_reason_counts, key=lambda item: item.reason)
        },
        "declared_confounding_factors": sorted(snapshot.declared_confounding_factors),
        "query_results": [
            _query_value(item)
            for item in sorted(
                snapshot.query_results_snapshot, key=lambda item: str(item.monitoring_query_id)
            )
        ],
        "recommendation_share": _number(snapshot.recommendation_share),
        "recommendation_ci_low": _number(snapshot.recommendation_ci_low),
        "recommendation_ci_high": _number(snapshot.recommendation_ci_high),
        "product_mention_share": _number(snapshot.product_mention_share),
        "product_mention_ci_low": _number(snapshot.product_mention_ci_low),
        "product_mention_ci_high": _number(snapshot.product_mention_ci_high),
        "placement_citation_share": _number(snapshot.placement_citation_share),
        "placement_citation_ci_low": _number(snapshot.placement_citation_ci_low),
        "placement_citation_ci_high": _number(snapshot.placement_citation_ci_high),
        "recommendation_query_min": _number(snapshot.recommendation_query_min),
        "recommendation_query_max": _number(snapshot.recommendation_query_max),
        "product_mention_query_min": _number(snapshot.product_mention_query_min),
        "product_mention_query_max": _number(snapshot.product_mention_query_max),
        "placement_citation_query_min": _number(snapshot.placement_citation_query_min),
        "placement_citation_query_max": _number(snapshot.placement_citation_query_max),
        "qualified_destination_coverage": _number(snapshot.qualified_destination_coverage),
        "verified_placement_coverage": _number(snapshot.verified_placement_coverage),
        "competitive_delta": _number(snapshot.competitive_delta),
        "worst_query_id": str(snapshot.worst_query_id) if snapshot.worst_query_id else None,
        "selected_destination_ids": sorted(map(str, snapshot.selected_destination_ids)),
        "qualified_destination_ids": sorted(map(str, snapshot.qualified_destination_ids)),
        "verified_destination_ids": sorted(map(str, snapshot.verified_destination_ids)),
        "status": snapshot.status,
        "confounded_reasons": sorted(snapshot.confounded_reasons),
    }
    if snapshot.observation_membership_version is not None:
        value.update(
            {
                "observation_membership_version": snapshot.observation_membership_version,
                "observation_membership_count": snapshot.observation_membership_count,
                "observation_membership_hash": snapshot.observation_membership_hash,
            }
        )
    return value


def _query_value(item: QueryMetricResultExportRecord) -> dict[str, object]:
    return {
        "monitoring_query_id": str(item.monitoring_query_id),
        "query_text_snapshot": item.query_text_snapshot,
        "query_cluster_key": item.query_cluster_key,
        "expected_sample_count": item.expected_sample_count,
        "sampled_sample_count": item.sampled_sample_count,
        "valid_sample_count": item.valid_sample_count,
        "invalid_sample_count": item.invalid_sample_count,
        "missing_sample_count": item.missing_sample_count,
        "meets_threshold": item.meets_threshold,
        "invalid_reason_counts": {
            value.reason: value.count
            for value in sorted(item.invalid_reason_counts, key=lambda value: value.reason)
        },
        "confounding_factors": sorted(item.confounding_factors),
        "recommendation": _estimate_value(item.recommendation),
        "product_mention": _estimate_value(item.product_mention),
        "placement_citation": _estimate_value(item.placement_citation),
        "competitor": _estimate_value(item.competitor),
        "competitive_delta": _number(item.competitive_delta),
    }


def _estimate_value(item: MetricEstimateExportRecord) -> dict[str, object]:
    return {
        "numerator": item.numerator,
        "denominator": item.denominator,
        "share": _number(item.share),
        "ci_low": _number(item.ci_low),
        "ci_high": _number(item.ci_high),
    }


def _number(value: Decimal) -> float:
    return float(value)
