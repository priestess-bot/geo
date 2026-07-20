"""Row-to-domain mapping for monitoring PostgreSQL adapters."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from geo_core.monitoring.domain import (
    BinaryEstimate,
    Device,
    MeasurementWindow,
    MetricSnapshot,
    MonitoringProtocol,
    MonitoringReport,
    ObservationCitation,
    Platform,
    ProtocolQuery,
    ProtocolStatus,
    QueryMetricResult,
    QuerySuggestion,
    SuggestionStatus,
    VerificationStatus,
)
from geo_core.monitoring.source_contract import (
    CaptureMethod,
    ClientKind,
    LEGACY_SOURCE_STRATUM_CONTRACT_VERSION,
    ModelIdentity,
    ModelIdentityState,
    ObservationDevice,
    ObservationPlatform,
    ObservationSurface,
    SOURCE_CONTRACT_VERSION,
    SearchMode,
    SourceStratumKey,
    SurfaceKind,
)


def source_stratum_from_value(value: Mapping[str, Any]) -> SourceStratumKey:
    configured = cast(Mapping[str, Any], value["configured_model"])
    reported = cast(Mapping[str, Any], value["reported_model"])
    detail_keys = {"platform_detail", "surface_detail"}
    present_detail_keys = detail_keys.intersection(value)
    if present_detail_keys and present_detail_keys != detail_keys:
        raise ValueError("source stratum detail keys must be present together")
    legacy = not present_detail_keys
    return SourceStratumKey(
        capture_method=CaptureMethod(str(value["capture_method"])),
        platform=ObservationPlatform(str(value["platform"])),
        surface=ObservationSurface(str(value["surface"])),
        surface_kind=SurfaceKind(str(value["surface_kind"])),
        engine=str(value["engine"]),
        configured_model=ModelIdentity(
            ModelIdentityState(str(configured["state"])),
            cast(str | None, configured.get("value")),
        ),
        reported_model=ModelIdentity(
            ModelIdentityState(str(reported["state"])),
            cast(str | None, reported.get("value")),
        ),
        locale=str(value["locale"]),
        region=str(value["region"]),
        language=str(value["language"]),
        device=ObservationDevice(str(value["device"])),
        client_kind=ClientKind(str(value["client_kind"])),
        search_enabled=bool(value["search_enabled"]),
        search_mode=SearchMode(str(value["search_mode"])),
        platform_detail=(
            cast(str | None, value.get("platform_detail")) if not legacy else None
        ),
        surface_detail=(
            cast(str | None, value.get("surface_detail")) if not legacy else None
        ),
        source_contract_version=(
            LEGACY_SOURCE_STRATUM_CONTRACT_VERSION if legacy else SOURCE_CONTRACT_VERSION
        ),
    )


def protocol_from_row(row: Mapping[str, Any]) -> MonitoringProtocol:
    source_strata_value = cast(list[Mapping[str, Any]], row.get("source_strata_snapshot") or [])
    return MonitoringProtocol(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        campaign_id=cast(UUID, row["campaign_id"]),
        market_profile_id=cast(UUID, row["market_profile_id"]),
        name=str(row["name"]),
        platform=Platform(str(row["platform"])),
        locale=str(row["locale"]),
        device=Device(str(row["device"])),
        sample_size=int(row["sample_size"]),
        window_days=int(row["window_days"]),
        status=ProtocolStatus(str(row["status"])),
        protocol_hash=cast(str | None, row["protocol_hash"]),
        created_at=cast(datetime, row["created_at"]),
        approved_at=cast(datetime | None, row["approved_at"]),
        frozen_at=cast(datetime | None, row["frozen_at"]),
        source_strata=tuple(source_stratum_from_value(item) for item in source_strata_value),
        source_strata_hash=cast(str | None, row.get("source_strata_hash")),
        minimum_valid_repeats=cast(int | None, row.get("minimum_valid_repeats")),
        statistics_method_version=cast(str | None, row.get("statistics_method_version")),
        statistics_contract_version=str(row.get("statistics_contract_version") or "legacy-v1"),
        question_set_id=cast(UUID | None, row.get("question_set_id")),
        question_set_hash=cast(str | None, row.get("question_set_hash")),
        question_set_bound_by=cast(UUID | None, row.get("question_set_bound_by")),
        question_set_bound_at=cast(datetime | None, row.get("question_set_bound_at")),
    )


def suggestion_from_row(row: Mapping[str, Any]) -> QuerySuggestion:
    return QuerySuggestion(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        protocol_id=cast(UUID, row["protocol_id"]),
        query_text=str(row["query_text"]),
        query_kind=str(row["query_kind"]),
        rationale=str(row["rationale"]),
        status=SuggestionStatus(str(row["status"])),
        created_at=cast(datetime, row["created_at"]),
        monitoring_query_id=cast(UUID | None, row.get("monitoring_query_id")),
        query_cluster_key=cast(str | None, row.get("query_cluster_key")),
    )


def protocol_query_from_row(row: Mapping[str, Any]) -> ProtocolQuery:
    return ProtocolQuery(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        protocol_id=cast(UUID, row["protocol_id"]),
        monitoring_query_id=cast(UUID, row["monitoring_query_id"]),
        query_text=str(row["query_text_snapshot"]),
        query_kind=str(row["query_kind_snapshot"]),
        locale=str(row["locale_snapshot"]),
        ordinal=int(row["ordinal"]),
        query_cluster_key=cast(str | None, row.get("query_cluster_key")),
        question_set_item_id=cast(UUID | None, row.get("question_set_item_id")),
        question_candidate_id=cast(UUID | None, row.get("question_candidate_id")),
    )


def citation_from_row(row: Mapping[str, Any]) -> ObservationCitation:
    return ObservationCitation(
        id=cast(UUID, row["id"]),
        citation_index=int(row["citation_index"]),
        url=str(row["url"]),
        title=cast(str | None, row["title"]),
        verification_status=VerificationStatus(str(row["verification_status"])),
        destination_id=cast(UUID | None, row["destination_id"]),
        submission_id=cast(UUID | None, row["submission_id"]),
        verified_placement=bool(row["verified_placement"]),
    )


def metric_from_row(row: Mapping[str, Any]) -> MetricSnapshot:
    source_value = cast(Mapping[str, Any] | None, row.get("source_stratum"))
    query_values = cast(list[Mapping[str, Any]], row.get("query_results_snapshot") or [])
    return MetricSnapshot(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        protocol_id=cast(UUID, row["protocol_id"]),
        campaign_id=cast(UUID, row["campaign_id"]),
        measurement_window=MeasurementWindow(str(row["measurement_window"])),
        source_stratum=(source_stratum_from_value(source_value) if source_value else None),
        source_stratum_hash=cast(str | None, row.get("source_stratum_hash")),
        expected_sample_count=int(row["expected_sample_count"]),
        eligible_sample_count=int(row["eligible_sample_count"]),
        recommendation_share=Decimal(row["recommendation_share"]),
        product_mention_share=Decimal(row["product_mention_share"]),
        placement_citation_share=Decimal(row["placement_citation_share"]),
        qualified_destination_coverage=Decimal(row["qualified_destination_coverage"]),
        verified_placement_coverage=Decimal(row["verified_placement_coverage"]),
        competitive_delta=Decimal(row["competitive_delta"]),
        status=str(row["status"]),
        confounded_reasons=tuple(row["confounded_reasons"]),
        input_hash=str(row["input_hash"]),
        method_version=str(row["method_version"]),
        computed_at=cast(datetime, row["computed_at"]),
        statistics_contract_version=str(row.get("statistics_contract_version") or "legacy-v1"),
        query_cluster_key=cast(str | None, row.get("query_cluster_key")),
        analysis_stratum_hash=cast(str | None, row.get("analysis_stratum_hash")),
        minimum_valid_repeats=cast(int | None, row.get("minimum_valid_repeats")),
        sampled_sample_count=cast(int | None, row.get("sampled_sample_count")),
        invalid_sample_count=cast(int | None, row.get("invalid_sample_count")),
        missing_sample_count=cast(int | None, row.get("missing_sample_count")),
        sampling_completion_ratio=_optional_decimal(row.get("sampling_completion_ratio")),
        valid_completion_ratio=_optional_decimal(row.get("valid_completion_ratio")),
        query_count=cast(int | None, row.get("query_count")),
        sufficient_query_count=cast(int | None, row.get("sufficient_query_count")),
        invalid_reason_counts=_reason_counts(row.get("invalid_reason_counts")),
        declared_confounding_factors=tuple(row.get("declared_confounding_factors") or ()),
        query_results=tuple(_query_metric_result(value) for value in query_values),
        recommendation_ci_low=_optional_decimal(row.get("recommendation_ci_low")),
        recommendation_ci_high=_optional_decimal(row.get("recommendation_ci_high")),
        product_mention_ci_low=_optional_decimal(row.get("product_mention_ci_low")),
        product_mention_ci_high=_optional_decimal(row.get("product_mention_ci_high")),
        placement_citation_ci_low=_optional_decimal(row.get("placement_citation_ci_low")),
        placement_citation_ci_high=_optional_decimal(row.get("placement_citation_ci_high")),
        recommendation_query_min=_optional_decimal(row.get("recommendation_query_min")),
        recommendation_query_max=_optional_decimal(row.get("recommendation_query_max")),
        product_mention_query_min=_optional_decimal(row.get("product_mention_query_min")),
        product_mention_query_max=_optional_decimal(row.get("product_mention_query_max")),
        placement_citation_query_min=_optional_decimal(row.get("placement_citation_query_min")),
        placement_citation_query_max=_optional_decimal(row.get("placement_citation_query_max")),
        worst_query_id=cast(UUID | None, row.get("worst_query_id")),
        selected_destination_ids=tuple(row.get("selected_destination_ids") or ()),
        qualified_destination_ids=tuple(row.get("qualified_destination_ids") or ()),
        verified_destination_ids=tuple(row.get("verified_destination_ids") or ()),
        result_hash=cast(str | None, row.get("result_hash")),
        observation_membership_version=cast(str | None, row.get("observation_membership_version")),
        observation_membership_hash=cast(str | None, row.get("observation_membership_hash")),
        observation_membership_count=cast(int | None, row.get("observation_membership_count")),
    )


def _query_metric_result(value: Mapping[str, Any]) -> QueryMetricResult:
    return QueryMetricResult(
        monitoring_query_id=UUID(str(value["monitoring_query_id"])),
        query_text_snapshot=str(value["query_text_snapshot"]),
        query_cluster_key=str(value["query_cluster_key"]),
        expected_sample_count=int(value["expected_sample_count"]),
        sampled_sample_count=int(value["sampled_sample_count"]),
        valid_sample_count=int(value["valid_sample_count"]),
        invalid_sample_count=int(value["invalid_sample_count"]),
        missing_sample_count=int(value["missing_sample_count"]),
        meets_threshold=bool(value["meets_threshold"]),
        invalid_reason_counts=_reason_counts(value["invalid_reason_counts"]),
        confounding_factors=tuple(value["confounding_factors"]),
        recommendation=_binary_estimate(cast(Mapping[str, Any], value["recommendation"])),
        product_mention=_binary_estimate(cast(Mapping[str, Any], value["product_mention"])),
        placement_citation=_binary_estimate(cast(Mapping[str, Any], value["placement_citation"])),
        competitor=_binary_estimate(cast(Mapping[str, Any], value["competitor"])),
        competitive_delta=Decimal(str(value["competitive_delta"])),
    )


def _binary_estimate(value: Mapping[str, Any]) -> BinaryEstimate:
    return BinaryEstimate(
        numerator=int(value["numerator"]),
        denominator=int(value["denominator"]),
        share=Decimal(str(value["share"])),
        ci_low=Decimal(str(value["ci_low"])),
        ci_high=Decimal(str(value["ci_high"])),
    )


def _reason_counts(value: object) -> tuple[tuple[str, int], ...]:
    raw_counts = cast(Mapping[str, int | str], value or {})
    return tuple(sorted((str(reason), int(count)) for reason, count in raw_counts.items()))


def _optional_decimal(value: object) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def report_from_row(row: Mapping[str, Any]) -> MonitoringReport:
    return MonitoringReport(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        protocol_id=cast(UUID, row["protocol_id"]),
        campaign_id=cast(UUID, row["campaign_id"]),
        metric_snapshot_id=cast(UUID, row["metric_snapshot_id"]),
        title=str(row["title"]),
        body=str(row["body"]),
        methodology_statement=str(row["methodology_statement"]),
        report_hash=str(row["report_hash"]),
        status=str(row["status"]),
        generated_at=cast(datetime, row["generated_at"]),
        approved_at=cast(datetime | None, row["approved_at"]),
    )
