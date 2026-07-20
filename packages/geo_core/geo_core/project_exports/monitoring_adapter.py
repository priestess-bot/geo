"""Public-field conversion from Monitoring domain records to F027 records."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from geo_core.monitoring.domain import (
    MetricObservationMembership,
    MetricSnapshot,
    MonitoringObservation,
    MonitoringProtocol,
    MonitoringReport,
    ProtocolQuery,
    VerifiedUrl,
)
from geo_core.monitoring.source_contract import SourceStratumKey
from geo_core.monitoring.statistics_models import BinaryEstimate, QueryMetricResult
from geo_core.project_exports.contracts import (
    ApprovedReportExportRecord,
    CitationExportRecord,
    ObservationExportRecord,
    ProtocolExportRecord,
    ProtocolSourceStratumExportRecord,
    QueryExportRecord,
    VerifiedUrlExportRecord,
)
from geo_core.project_exports.legacy_statistics_contracts import (
    AnyMetricSnapshotExportRecord,
    LegacyMetricSnapshotExportRecord,
)
from geo_core.project_exports.membership_contracts import (
    MetricObservationMembershipExportRecord,
)
from geo_core.project_exports.statistics_contracts import (
    InvalidReasonCountExportRecord,
    MetricEstimateExportRecord,
    MetricSnapshotExportRecord,
    QueryMetricResultExportRecord,
)


def protocol_record(protocol: MonitoringProtocol) -> ProtocolExportRecord:
    return ProtocolExportRecord(
        id=protocol.id,
        project_id=protocol.project_id,
        campaign_id=protocol.campaign_id,
        name=protocol.name,
        platform=protocol.platform.value,
        locale=protocol.locale,
        device=protocol.device.value,
        sample_size=protocol.sample_size,
        window_days=protocol.window_days,
        status=protocol.status.value,
        protocol_hash=protocol.protocol_hash,
        source_strata_hash=protocol.source_strata_hash,
        minimum_valid_repeats=protocol.minimum_valid_repeats,
        statistics_method_version=protocol.statistics_method_version,
        statistics_contract_version=protocol.statistics_contract_version,
        approved_at=protocol.approved_at,
        frozen_at=protocol.frozen_at,
    )


def source_stratum_record(
    protocol: MonitoringProtocol, source: SourceStratumKey
) -> ProtocolSourceStratumExportRecord:
    return ProtocolSourceStratumExportRecord(
        project_id=protocol.project_id,
        campaign_id=protocol.campaign_id,
        protocol_id=protocol.id,
        source_stratum_hash=source.canonical_hash(),
        source_contract_version=source.source_contract_version,
        capture_method=source.capture_method.value,
        platform=source.platform.value,
        platform_detail=source.platform_detail,
        surface=source.surface.value,
        surface_detail=source.surface_detail,
        surface_kind=source.surface_kind.value,
        engine=source.engine,
        configured_model_state=source.configured_model.state.value,
        configured_model=source.configured_model.value,
        reported_model_state=source.reported_model.state.value,
        reported_model=source.reported_model.value,
        locale=source.locale,
        region=source.region,
        language=source.language,
        device=source.device.value,
        client_kind=source.client_kind.value,
        search_enabled=source.search_enabled,
        search_mode=source.search_mode.value,
    )


def query_record(protocol: MonitoringProtocol, query: ProtocolQuery) -> QueryExportRecord:
    return QueryExportRecord(
        id=query.id,
        project_id=query.project_id,
        campaign_id=protocol.campaign_id,
        protocol_id=query.protocol_id,
        monitoring_query_id=query.monitoring_query_id,
        query_text=query.query_text,
        query_kind=query.query_kind,
        locale=query.locale,
        ordinal=query.ordinal,
        query_cluster_key=query.query_cluster_key,
    )


def observation_record(item: MonitoringObservation) -> ObservationExportRecord:
    draft = item.draft
    source = draft.source
    return ObservationExportRecord(
        id=item.id,
        project_id=item.project_id,
        campaign_id=item.campaign_id,
        protocol_id=item.protocol_id,
        monitoring_query_id=draft.monitoring_query_id,
        query_cluster_key=draft.query_cluster_key,
        measurement_window=draft.measurement_window.value,
        source_stratum_hash=(
            draft.source_stratum_hash if source.capture_method.value != "unknown" else None
        ),
        sample_index=draft.sample_index,
        result_status=draft.result_status.value,
        eligible=draft.eligible,
        url_verification_status=draft.url_verification_status.value,
        recommendation_present=draft.recommendation_present,
        primary_product_mentioned=draft.primary_product_mentioned,
        competitor_mentioned=draft.competitor_mentioned,
        ineligible_reasons=draft.ineligible_reasons,
        confounding_factors=draft.confounding_factors,
        capture_method=source.capture_method.value,
        platform=source.platform.value,
        surface=source.surface.value,
        engine=source.run.engine,
        answer_text=draft.raw_answer,
        payload_hash=item.payload_hash,
        observed_at=draft.observed_at,
    )


def citation_records(
    observation: MonitoringObservation,
) -> tuple[CitationExportRecord, ...]:
    drafts = {index: item for index, item in enumerate(observation.draft.citations)}
    result: list[CitationExportRecord] = []
    for citation in observation.citations:
        draft = drafts[citation.citation_index]
        result.append(
            CitationExportRecord(
                observation_id=observation.id,
                citation_index=citation.citation_index,
                project_id=observation.project_id,
                campaign_id=observation.campaign_id,
                protocol_id=observation.protocol_id,
                url=citation.url,
                title=citation.title,
                verification_status=citation.verification_status.value,
                verified_placement=citation.verified_placement,
                destination_id=citation.destination_id,
                submission_id=citation.submission_id,
                verified_at=draft.verified_at,
            )
        )
    return tuple(result)


def membership_record(
    snapshot: MetricSnapshot, item: MetricObservationMembership
) -> MetricObservationMembershipExportRecord:
    return MetricObservationMembershipExportRecord(
        snapshot_id=item.snapshot_id,
        project_id=snapshot.project_id,
        campaign_id=snapshot.campaign_id,
        protocol_id=snapshot.protocol_id,
        observation_id=item.observation_id,
        ordinal=item.ordinal,
        payload_hash=item.payload_hash,
    )


def metric_record(snapshot: MetricSnapshot) -> AnyMetricSnapshotExportRecord:
    if snapshot.statistics_contract_version == "legacy-v1":
        return _legacy_metric_record(snapshot)
    return MetricSnapshotExportRecord(
        id=snapshot.id,
        project_id=snapshot.project_id,
        campaign_id=snapshot.campaign_id,
        protocol_id=snapshot.protocol_id,
        measurement_window=snapshot.measurement_window.value,
        source_stratum_hash=cast(str, snapshot.source_stratum_hash),
        statistics_contract_version=snapshot.statistics_contract_version,
        query_cluster_key=cast(str, snapshot.query_cluster_key),
        analysis_stratum_hash=cast(str, snapshot.analysis_stratum_hash),
        observation_membership_version=snapshot.observation_membership_version,
        observation_membership_count=snapshot.observation_membership_count,
        observation_membership_hash=snapshot.observation_membership_hash,
        minimum_valid_repeats=cast(int, snapshot.minimum_valid_repeats),
        expected_sample_count=snapshot.expected_sample_count,
        sampled_sample_count=cast(int, snapshot.sampled_sample_count),
        eligible_sample_count=snapshot.eligible_sample_count,
        invalid_sample_count=cast(int, snapshot.invalid_sample_count),
        missing_sample_count=cast(int, snapshot.missing_sample_count),
        sampling_completion_ratio=cast(Decimal, snapshot.sampling_completion_ratio),
        valid_completion_ratio=cast(Decimal, snapshot.valid_completion_ratio),
        query_count=cast(int, snapshot.query_count),
        sufficient_query_count=cast(int, snapshot.sufficient_query_count),
        recommendation_share=snapshot.recommendation_share,
        product_mention_share=snapshot.product_mention_share,
        placement_citation_share=snapshot.placement_citation_share,
        qualified_destination_coverage=snapshot.qualified_destination_coverage,
        verified_placement_coverage=snapshot.verified_placement_coverage,
        competitive_delta=snapshot.competitive_delta,
        recommendation_ci_low=cast(Decimal, snapshot.recommendation_ci_low),
        recommendation_ci_high=cast(Decimal, snapshot.recommendation_ci_high),
        product_mention_ci_low=cast(Decimal, snapshot.product_mention_ci_low),
        product_mention_ci_high=cast(Decimal, snapshot.product_mention_ci_high),
        placement_citation_ci_low=cast(Decimal, snapshot.placement_citation_ci_low),
        placement_citation_ci_high=cast(Decimal, snapshot.placement_citation_ci_high),
        recommendation_query_min=cast(Decimal, snapshot.recommendation_query_min),
        recommendation_query_max=cast(Decimal, snapshot.recommendation_query_max),
        product_mention_query_min=cast(Decimal, snapshot.product_mention_query_min),
        product_mention_query_max=cast(Decimal, snapshot.product_mention_query_max),
        placement_citation_query_min=cast(Decimal, snapshot.placement_citation_query_min),
        placement_citation_query_max=cast(Decimal, snapshot.placement_citation_query_max),
        worst_query_id=snapshot.worst_query_id,
        invalid_reason_counts=tuple(
            InvalidReasonCountExportRecord(reason, count)
            for reason, count in snapshot.invalid_reason_counts
        ),
        declared_confounding_factors=snapshot.declared_confounding_factors,
        query_results_snapshot=tuple(_query_result_record(item) for item in snapshot.query_results),
        selected_destination_ids=snapshot.selected_destination_ids,
        qualified_destination_ids=snapshot.qualified_destination_ids,
        verified_destination_ids=snapshot.verified_destination_ids,
        status=snapshot.status,
        confounded_reasons=snapshot.confounded_reasons,
        input_hash=snapshot.input_hash,
        result_hash=cast(str, snapshot.result_hash),
        method_version=snapshot.method_version,
        computed_at=snapshot.computed_at,
    )


def report_record(report: MonitoringReport) -> ApprovedReportExportRecord:
    return ApprovedReportExportRecord(
        id=report.id,
        project_id=report.project_id,
        campaign_id=report.campaign_id,
        protocol_id=report.protocol_id,
        metric_snapshot_id=report.metric_snapshot_id,
        title=report.title,
        body=report.body,
        methodology_statement=report.methodology_statement,
        report_hash=report.report_hash,
        generated_at=report.generated_at,
        approved_at=cast(datetime, report.approved_at),
    )


def verified_url_record(project_id: UUID, item: VerifiedUrl) -> VerifiedUrlExportRecord:
    return VerifiedUrlExportRecord(
        project_id=project_id,
        campaign_id=item.campaign_id,
        protocol_ids=item.protocol_ids,
        url=item.url,
        title=item.title,
        destination_id=item.destination_id,
        first_verified_at=item.first_verified_at,
        observation_count=item.observation_count,
    )


def _estimate_record(item: BinaryEstimate) -> MetricEstimateExportRecord:
    return MetricEstimateExportRecord(
        numerator=item.numerator,
        denominator=item.denominator,
        share=item.share,
        ci_low=item.ci_low,
        ci_high=item.ci_high,
    )


def _query_result_record(item: QueryMetricResult) -> QueryMetricResultExportRecord:
    return QueryMetricResultExportRecord(
        monitoring_query_id=item.monitoring_query_id,
        query_text_snapshot=item.query_text_snapshot,
        query_cluster_key=item.query_cluster_key,
        expected_sample_count=item.expected_sample_count,
        sampled_sample_count=item.sampled_sample_count,
        valid_sample_count=item.valid_sample_count,
        invalid_sample_count=item.invalid_sample_count,
        missing_sample_count=item.missing_sample_count,
        meets_threshold=item.meets_threshold,
        invalid_reason_counts=tuple(
            InvalidReasonCountExportRecord(reason, count)
            for reason, count in item.invalid_reason_counts
        ),
        confounding_factors=item.confounding_factors,
        recommendation=_estimate_record(item.recommendation),
        product_mention=_estimate_record(item.product_mention),
        placement_citation=_estimate_record(item.placement_citation),
        competitor=_estimate_record(item.competitor),
        competitive_delta=item.competitive_delta,
    )


def _legacy_metric_record(snapshot: MetricSnapshot) -> LegacyMetricSnapshotExportRecord:
    return LegacyMetricSnapshotExportRecord(
        id=snapshot.id,
        project_id=snapshot.project_id,
        campaign_id=snapshot.campaign_id,
        protocol_id=snapshot.protocol_id,
        measurement_window=snapshot.measurement_window.value,
        source_stratum_hash=snapshot.source_stratum_hash,
        statistics_contract_version=snapshot.statistics_contract_version,
        query_cluster_key=None,
        analysis_stratum_hash=None,
        observation_membership_version=None,
        observation_membership_count=None,
        observation_membership_hash=None,
        minimum_valid_repeats=None,
        expected_sample_count=snapshot.expected_sample_count,
        sampled_sample_count=None,
        eligible_sample_count=snapshot.eligible_sample_count,
        invalid_sample_count=None,
        missing_sample_count=None,
        sampling_completion_ratio=None,
        valid_completion_ratio=None,
        query_count=None,
        sufficient_query_count=None,
        recommendation_share=snapshot.recommendation_share,
        product_mention_share=snapshot.product_mention_share,
        placement_citation_share=snapshot.placement_citation_share,
        qualified_destination_coverage=snapshot.qualified_destination_coverage,
        verified_placement_coverage=snapshot.verified_placement_coverage,
        competitive_delta=snapshot.competitive_delta,
        recommendation_ci_low=None,
        recommendation_ci_high=None,
        product_mention_ci_low=None,
        product_mention_ci_high=None,
        placement_citation_ci_low=None,
        placement_citation_ci_high=None,
        recommendation_query_min=None,
        recommendation_query_max=None,
        product_mention_query_min=None,
        product_mention_query_max=None,
        placement_citation_query_min=None,
        placement_citation_query_max=None,
        worst_query_id=None,
        invalid_reason_counts=None,
        declared_confounding_factors=None,
        query_results_snapshot=None,
        selected_destination_ids=None,
        qualified_destination_ids=None,
        verified_destination_ids=None,
        status=snapshot.status,
        confounded_reasons=snapshot.confounded_reasons,
        input_hash=snapshot.input_hash,
        result_hash=None,
        method_version=snapshot.method_version,
        computed_at=snapshot.computed_at,
    )
