"""Versioned observational statistics for frozen monitoring protocols."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from typing import Sequence
from uuid import UUID

from geo_core.monitoring.comparisons import (
    classify_comparison as classify_comparison,
    evaluate_comparison as evaluate_comparison,
)
from geo_core.monitoring.domain import (
    METRIC_METHOD_VERSION,
    OBSERVATION_MEMBERSHIP_VERSION,
    REPORT_METHODOLOGY,
    STATISTICS_CONTRACT_VERSION,
    CampaignDestinationState,
    MeasurementWindow,
    MetricObservationMembership,
    MonitoringObservation,
    MonitoringProtocol,
    MonitoringRuleViolation,
    ProtocolQuery,
    ProtocolStatus,
    ResultStatus,
    VerificationStatus,
    canonical_hash,
)
from geo_core.monitoring.source_contract import SOURCE_CONTRACT_VERSION, SourceStratumKey
from geo_core.monitoring.statistics_models import (
    BinaryEstimate,
    ComparisonConclusion as ComparisonConclusion,
    ComparisonDecision as ComparisonDecision,
    FrozenComparisonCriteria as FrozenComparisonCriteria,
    MetricSnapshot,
    QueryMetricResult,
    ReasonCounts,
    analysis_stratum_hash,
)


SIX_PLACES = Decimal("0.000001")
WILSON_Z = Decimal("1.959963984540054")


def calculate_metric_snapshot(
    *,
    snapshot_id: UUID,
    protocol: MonitoringProtocol,
    queries: Sequence[ProtocolQuery],
    query_cluster_key: str,
    window: MeasurementWindow,
    source_stratum: SourceStratumKey,
    observations: Sequence[MonitoringObservation],
    destination_state: CampaignDestinationState,
    computed_at: datetime,
) -> MetricSnapshot:
    _validate_protocol(protocol, source_stratum)
    cluster_key = query_cluster_key.strip()
    cluster_queries = tuple(
        sorted(
            (item for item in queries if item.query_cluster_key == cluster_key),
            key=lambda item: str(item.monitoring_query_id),
        )
    )
    if not cluster_queries:
        raise MonitoringRuleViolation("query cluster is not frozen into the protocol")
    source_hash = source_stratum.canonical_hash()
    selected_observations = select_metric_observations(
        protocol=protocol,
        queries=cluster_queries,
        query_cluster_key=cluster_key,
        window=window,
        source_stratum=source_stratum,
        observations=observations,
    )
    membership = metric_observation_membership(snapshot_id, selected_observations)
    membership_hash = observation_membership_hash(membership)
    minimum = protocol.minimum_valid_repeats
    assert minimum is not None
    query_results = tuple(
        _query_result(
            query=query,
            expected=protocol.sample_size,
            minimum=minimum,
            observations=tuple(
                item
                for item in selected_observations
                if item.draft.monitoring_query_id == query.monitoring_query_id
            ),
            destination_state=destination_state,
        )
        for query in cluster_queries
    )
    valid = tuple(item for item in selected_observations if item.included_in_metrics)
    expected = len(cluster_queries) * protocol.sample_size
    sampled = len(selected_observations)
    invalid = sampled - len(valid)
    missing = expected - sampled
    if missing < 0:
        raise MonitoringRuleViolation("observations exceed the frozen sample denominator")
    recommendation = _estimate(sum(item.draft.recommendation_present for item in valid), len(valid))
    product = _estimate(sum(item.draft.primary_product_mentioned for item in valid), len(valid))
    citation = _estimate(
        sum(_has_verified_campaign_citation(item, destination_state) for item in valid),
        len(valid),
    )
    competitor = _estimate(sum(item.draft.competitor_mentioned for item in valid), len(valid))
    invalid_counts = _sum_reason_counts(query_results)
    confounding_factors = tuple(
        sorted({value for item in query_results for value in item.confounding_factors})
    )
    reasons = _confounded_reasons(selected_observations, destination_state)
    sufficient = sum(item.meets_threshold for item in query_results)
    if sufficient < len(query_results):
        status = "insufficient_evidence"
    else:
        status = "confounded" if reasons else "complete"
    worst = min(
        query_results,
        key=lambda item: (
            item.product_mention.share,
            item.recommendation.share,
            item.placement_citation.share,
            str(item.monitoring_query_id),
        ),
    )
    recommendation_range = _query_range(query_results, "recommendation")
    product_range = _query_range(query_results, "product_mention")
    citation_range = _query_range(query_results, "placement_citation")
    selected_ids = tuple(sorted(destination_state.selected_destination_ids, key=str))
    qualified_ids = tuple(
        sorted(
            destination_state.qualified_destination_ids
            & destination_state.selected_destination_ids,
            key=str,
        )
    )
    verified_ids = tuple(
        sorted(destination_state.verified_destination_ids & set(qualified_ids), key=str)
    )
    analysis_hash = analysis_stratum_hash(source_hash, cluster_key)
    input_hash = canonical_hash(
        {
            "protocol_hash": protocol.protocol_hash,
            "statistics_contract_version": protocol.statistics_contract_version,
            "minimum_valid_repeats": minimum,
            "method_version": METRIC_METHOD_VERSION,
            "measurement_window": window.value,
            "source_stratum": source_stratum.canonical_value(),
            "source_stratum_hash": source_hash,
            "query_cluster_key": cluster_key,
            "analysis_stratum_hash": analysis_hash,
            "queries": [
                {
                    "monitoring_query_id": str(item.monitoring_query_id),
                    "query_text_snapshot": item.query_text,
                    "query_cluster_key": item.query_cluster_key,
                }
                for item in cluster_queries
            ],
            "observation_membership_version": OBSERVATION_MEMBERSHIP_VERSION,
            "observation_membership_hash": membership_hash,
            "observation_membership_count": len(membership),
            "observation_membership": [item.canonical_value() for item in membership],
            "selected_destination_ids": list(map(str, selected_ids)),
            "qualified_destination_ids": list(map(str, qualified_ids)),
            "verified_destination_ids": list(map(str, verified_ids)),
        }
    )
    draft_snapshot = MetricSnapshot(
        id=snapshot_id,
        project_id=protocol.project_id,
        protocol_id=protocol.id,
        campaign_id=protocol.campaign_id,
        measurement_window=window,
        source_stratum=source_stratum,
        source_stratum_hash=source_hash,
        expected_sample_count=expected,
        eligible_sample_count=len(valid),
        recommendation_share=recommendation.share,
        product_mention_share=product.share,
        placement_citation_share=citation.share,
        qualified_destination_coverage=_ratio(len(qualified_ids), len(selected_ids)),
        verified_placement_coverage=_ratio(len(verified_ids), len(qualified_ids)),
        competitive_delta=_quantize(product.share - competitor.share),
        status=status,
        confounded_reasons=reasons,
        input_hash=input_hash,
        method_version=METRIC_METHOD_VERSION,
        computed_at=computed_at,
        statistics_contract_version=STATISTICS_CONTRACT_VERSION,
        query_cluster_key=cluster_key,
        analysis_stratum_hash=analysis_hash,
        minimum_valid_repeats=minimum,
        sampled_sample_count=sampled,
        invalid_sample_count=invalid,
        missing_sample_count=missing,
        sampling_completion_ratio=_ratio(sampled, expected),
        valid_completion_ratio=_ratio(len(valid), expected),
        query_count=len(query_results),
        sufficient_query_count=sufficient,
        invalid_reason_counts=invalid_counts,
        declared_confounding_factors=confounding_factors,
        query_results=query_results,
        recommendation_ci_low=recommendation.ci_low,
        recommendation_ci_high=recommendation.ci_high,
        product_mention_ci_low=product.ci_low,
        product_mention_ci_high=product.ci_high,
        placement_citation_ci_low=citation.ci_low,
        placement_citation_ci_high=citation.ci_high,
        recommendation_query_min=recommendation_range[0],
        recommendation_query_max=recommendation_range[1],
        product_mention_query_min=product_range[0],
        product_mention_query_max=product_range[1],
        placement_citation_query_min=citation_range[0],
        placement_citation_query_max=citation_range[1],
        worst_query_id=worst.monitoring_query_id,
        selected_destination_ids=selected_ids,
        qualified_destination_ids=qualified_ids,
        verified_destination_ids=verified_ids,
        observation_membership_version=OBSERVATION_MEMBERSHIP_VERSION,
        observation_membership_hash=membership_hash,
        observation_membership_count=len(membership),
    )
    result_hash = canonical_hash(draft_snapshot.result_value())
    return replace(draft_snapshot, result_hash=result_hash)


def select_metric_observations(
    *,
    protocol: MonitoringProtocol,
    queries: Sequence[ProtocolQuery],
    query_cluster_key: str,
    window: MeasurementWindow,
    source_stratum: SourceStratumKey,
    observations: Sequence[MonitoringObservation],
) -> tuple[MonitoringObservation, ...]:
    query_ids = {item.monitoring_query_id for item in queries}
    source_hash = source_stratum.canonical_hash()
    return tuple(
        sorted(
            (
                item
                for item in observations
                if item.draft.measurement_window == window
                and item.project_id == protocol.project_id
                and item.protocol_id == protocol.id
                and item.campaign_id == protocol.campaign_id
                and item.draft.source_stratum_hash == source_hash
                and item.draft.monitoring_query_id in query_ids
                and item.draft.query_cluster_key == query_cluster_key
            ),
            key=lambda item: (
                str(item.draft.monitoring_query_id),
                item.draft.sample_index,
                str(item.id),
            ),
        )
    )


def metric_observation_membership(
    snapshot_id: UUID, observations: Sequence[MonitoringObservation]
) -> tuple[MetricObservationMembership, ...]:
    ordered = sorted(
        observations,
        key=lambda item: (
            str(item.draft.monitoring_query_id),
            item.draft.sample_index,
            str(item.id),
        ),
    )
    return tuple(
        MetricObservationMembership(
            snapshot_id=snapshot_id,
            observation_id=item.id,
            payload_hash=item.payload_hash,
            ordinal=index,
        )
        for index, item in enumerate(ordered, start=1)
    )


def observation_membership_hash(
    membership: Sequence[MetricObservationMembership],
) -> str:
    ordered = sorted(membership, key=lambda item: item.ordinal)
    if [item.ordinal for item in ordered] != list(range(1, len(ordered) + 1)):
        raise MonitoringRuleViolation("metric observation membership ordinals must be contiguous")
    manifest = "".join(
        f"{item.ordinal}:{item.observation_id}:{item.payload_hash}\n" for item in ordered
    )
    return hashlib.sha256(manifest.encode("ascii")).hexdigest()


def render_report(snapshot: MetricSnapshot, title: str) -> tuple[str, str]:
    if not title.strip():
        raise MonitoringRuleViolation("report title is required")
    if snapshot.status == "insufficient_evidence":
        conclusion = (
            "Insufficient evidence: at least one frozen query did not meet the valid "
            "repeat threshold. No directional conclusion is reported."
        )
    else:
        conclusion = "The snapshot is descriptive and does not establish direction causally."
    confounded = (
        " Confounders: " + ", ".join(snapshot.confounded_reasons) + "."
        if snapshot.confounded_reasons
        else ""
    )
    body = (
        f"Window {snapshot.measurement_window.value}, analysis stratum "
        f"{snapshot.analysis_stratum_hash or 'legacy'}, contains "
        f"{snapshot.eligible_sample_count} valid observations against "
        f"{snapshot.expected_sample_count} expected. Recommendation share was "
        f"{snapshot.recommendation_share} (95% Wilson interval "
        f"{snapshot.recommendation_ci_low} to {snapshot.recommendation_ci_high}); "
        f"product mention share was {snapshot.product_mention_share} "
        f"({snapshot.product_mention_ci_low} to {snapshot.product_mention_ci_high}); "
        f"placement citation share was {snapshot.placement_citation_share} "
        f"({snapshot.placement_citation_ci_low} to {snapshot.placement_citation_ci_high}). "
        f"Worst frozen query: {snapshot.worst_query_id}. {conclusion}{confounded} "
        f"{REPORT_METHODOLOGY}"
    )
    return body, canonical_hash(
        {
            "title": title.strip(),
            "body": body,
            "methodology_statement": REPORT_METHODOLOGY,
            "metric_snapshot_id": str(snapshot.id),
            "metric_result_hash": snapshot.result_hash,
        }
    )


def _validate_protocol(protocol: MonitoringProtocol, source_stratum: SourceStratumKey) -> None:
    if protocol.status != ProtocolStatus.FROZEN or not protocol.protocol_hash:
        raise MonitoringRuleViolation("metrics require a frozen monitoring protocol")
    if protocol.statistics_contract_version != STATISTICS_CONTRACT_VERSION:
        raise MonitoringRuleViolation("metrics require a statistics-v2 protocol")
    if source_stratum.source_contract_version != SOURCE_CONTRACT_VERSION:
        raise MonitoringRuleViolation("metrics require source stratum contract v3")
    if source_stratum.canonical_hash() not in {
        item.canonical_hash() for item in protocol.source_strata
    }:
        raise MonitoringRuleViolation(
            "metrics require a source stratum frozen into the monitoring protocol"
        )


def _query_result(
    *,
    query: ProtocolQuery,
    expected: int,
    minimum: int,
    observations: tuple[MonitoringObservation, ...],
    destination_state: CampaignDestinationState,
) -> QueryMetricResult:
    sample_indexes = [item.draft.sample_index for item in observations]
    if len(set(sample_indexes)) != len(sample_indexes) or any(
        not 1 <= index <= expected for index in sample_indexes
    ):
        raise MonitoringRuleViolation("query samples violate the frozen slot inventory")
    valid = tuple(item for item in observations if item.included_in_metrics)
    invalid = len(observations) - len(valid)
    missing = expected - len(observations)
    reasons: Counter[str] = Counter()
    for item in observations:
        if item.included_in_metrics:
            continue
        item_reasons = set(item.draft.ineligible_reasons)
        if item.draft.result_status == ResultStatus.FAILED:
            item_reasons.add("capture_failed")
        if not item_reasons:
            item_reasons.add("excluded_from_metrics")
        reasons.update(item_reasons)
    confounders = tuple(
        sorted({value for item in observations for value in item.draft.confounding_factors})
    )
    recommendation = _estimate(sum(item.draft.recommendation_present for item in valid), len(valid))
    product = _estimate(sum(item.draft.primary_product_mentioned for item in valid), len(valid))
    citation = _estimate(
        sum(_has_verified_campaign_citation(item, destination_state) for item in valid),
        len(valid),
    )
    competitor = _estimate(sum(item.draft.competitor_mentioned for item in valid), len(valid))
    assert query.query_cluster_key is not None
    return QueryMetricResult(
        monitoring_query_id=query.monitoring_query_id,
        query_text_snapshot=query.query_text,
        query_cluster_key=query.query_cluster_key,
        expected_sample_count=expected,
        sampled_sample_count=len(observations),
        valid_sample_count=len(valid),
        invalid_sample_count=invalid,
        missing_sample_count=missing,
        meets_threshold=len(valid) >= minimum,
        invalid_reason_counts=tuple(sorted(reasons.items())),
        confounding_factors=confounders,
        recommendation=recommendation,
        product_mention=product,
        placement_citation=citation,
        competitor=competitor,
        competitive_delta=_quantize(product.share - competitor.share),
    )


def _estimate(numerator: int, denominator: int) -> BinaryEstimate:
    share = _ratio(numerator, denominator)
    if denominator == 0:
        return BinaryEstimate(numerator, denominator, share, Decimal(0), Decimal(1))
    n = Decimal(denominator)
    exact_share = Decimal(numerator) / n
    z_squared = WILSON_Z * WILSON_Z
    denominator_adjustment = Decimal(1) + z_squared / n
    center = (exact_share + z_squared / (Decimal(2) * n)) / denominator_adjustment
    margin = (
        WILSON_Z
        * ((exact_share * (Decimal(1) - exact_share) / n + z_squared / (Decimal(4) * n * n)).sqrt())
        / denominator_adjustment
    )
    return BinaryEstimate(
        numerator=numerator,
        denominator=denominator,
        share=share,
        ci_low=_quantize(max(Decimal(0), center - margin)),
        ci_high=_quantize(min(Decimal(1), center + margin)),
    )


def _has_verified_campaign_citation(
    observation: MonitoringObservation, destination_state: CampaignDestinationState
) -> bool:
    if observation.draft.url_verification_status != VerificationStatus.PASSED:
        return False
    return any(
        citation.verified_placement
        and citation.submission_id is not None
        and citation.verification_status == VerificationStatus.PASSED
        and citation.destination_id in destination_state.selected_destination_ids
        for citation in observation.citations
    )


def _confounded_reasons(
    observations: Sequence[MonitoringObservation],
    destination_state: CampaignDestinationState,
) -> tuple[str, ...]:
    reasons: set[str] = set()
    if any(item.draft.result_status == ResultStatus.FAILED for item in observations):
        reasons.add("failed_samples")
    if any(item.draft.confounding_factors for item in observations):
        reasons.add("declared_confounding_factors")
    if not destination_state.selected_destination_ids:
        reasons.add("no_selected_destinations")
    if not destination_state.qualified_destination_ids:
        reasons.add("no_qualified_destinations")
    return tuple(sorted(reasons))


def _sum_reason_counts(results: Sequence[QueryMetricResult]) -> ReasonCounts:
    counts: Counter[str] = Counter()
    for item in results:
        counts.update(dict(item.invalid_reason_counts))
    return tuple(sorted(counts.items()))


def _query_range(results: Sequence[QueryMetricResult], field: str) -> tuple[Decimal, Decimal]:
    values = [getattr(item, field).share for item in results]
    return min(values), max(values)


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0.000000")
    return _quantize(Decimal(numerator) / Decimal(denominator))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(SIX_PLACES, rounding=ROUND_HALF_UP)
