"""Canonical JSON projection and normalized CSV rendering for F027."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
from uuid import UUID

from geo_core.project_exports.constants import METRIC_METHOD_VERSION, PROJECT_EXPORT_SCHEMA_VERSION
from geo_core.project_exports.contracts import (
    ApprovedReportExportRecord,
    AnyMetricSnapshotExportRecord,
    CitationExportRecord,
    ObservationExportRecord,
    ProjectExportInput,
    ProjectExportRuleViolation,
    ProtocolExportRecord,
    ProtocolSourceStratumExportRecord,
    QueryExportRecord,
    VerifiedUrlExportRecord,
)
from geo_core.project_exports.membership_contracts import (
    MetricObservationMembershipExportRecord,
)
from geo_core.project_exports.legacy_statistics_contracts import (
    LegacyMetricSnapshotExportRecord,
)
from geo_core.project_exports.statistics_contracts import (
    MetricEstimateExportRecord,
    QueryMetricResultExportRecord,
)


@dataclass(frozen=True)
class SortedExportData:
    protocols: tuple[ProtocolExportRecord, ...]
    source_strata: tuple[ProtocolSourceStratumExportRecord, ...]
    queries: tuple[QueryExportRecord, ...]
    observations: tuple[ObservationExportRecord, ...]
    citations: tuple[CitationExportRecord, ...]
    snapshots: tuple[AnyMetricSnapshotExportRecord, ...]
    memberships: tuple[MetricObservationMembershipExportRecord, ...]
    reports: tuple[ApprovedReportExportRecord, ...]
    verified_urls: tuple[VerifiedUrlExportRecord, ...]


def sort_export_data(source: ProjectExportInput) -> SortedExportData:
    data = source.data
    return SortedExportData(
        protocols=tuple(sorted(data.protocols, key=lambda item: str(item.id))),
        source_strata=tuple(
            sorted(
                data.protocol_source_strata,
                key=lambda item: (str(item.protocol_id), item.source_stratum_hash),
            )
        ),
        queries=tuple(
            sorted(
                data.queries,
                key=lambda item: (str(item.protocol_id), item.ordinal, str(item.id)),
            )
        ),
        observations=tuple(
            sorted(
                data.observations,
                key=lambda item: (
                    str(item.protocol_id),
                    item.measurement_window,
                    item.source_stratum_hash or "",
                    item.query_cluster_key or "",
                    str(item.monitoring_query_id),
                    item.sample_index,
                    str(item.id),
                ),
            )
        ),
        citations=tuple(
            sorted(data.citations, key=lambda item: (str(item.observation_id), item.citation_index))
        ),
        snapshots=tuple(
            sorted(
                data.metric_snapshots,
                key=lambda item: (
                    str(item.protocol_id),
                    item.measurement_window,
                    item.source_stratum_hash or "",
                    item.query_cluster_key or "",
                    time_text(item.computed_at),
                    str(item.id),
                ),
            )
        ),
        memberships=tuple(
            sorted(
                data.metric_observation_memberships,
                key=lambda item: (str(item.snapshot_id), item.ordinal),
            )
        ),
        reports=tuple(
            sorted(
                data.approved_reports,
                key=lambda item: (
                    str(item.protocol_id),
                    time_text(item.approved_at),
                    str(item.id),
                ),
            )
        ),
        verified_urls=tuple(
            sorted(data.verified_urls, key=lambda item: (str(item.campaign_id), item.url))
        ),
    )


def json_projection(
    source: ProjectExportInput, data: SortedExportData
) -> tuple[dict[str, object], int]:
    citations_by_observation: dict[UUID, list[CitationExportRecord]] = {}
    for citation in data.citations:
        citations_by_observation.setdefault(citation.observation_id, []).append(citation)
    strata_by_protocol: dict[UUID, list[ProtocolSourceStratumExportRecord]] = {}
    for stratum in data.source_strata:
        strata_by_protocol.setdefault(stratum.protocol_id, []).append(stratum)
    memberships_by_snapshot: dict[UUID, list[MetricObservationMembershipExportRecord]] = {}
    for membership in data.memberships:
        memberships_by_snapshot.setdefault(membership.snapshot_id, []).append(membership)

    counts = _record_counts(data)
    value: dict[str, object] = {
        "schema_version": PROJECT_EXPORT_SCHEMA_VERSION,
        "audience": source.audience.value,
        "scope": {
            "project_id": str(source.scope.project_id),
            "campaign_id": str(source.scope.campaign_id) if source.scope.campaign_id else None,
        },
        "metric_method_version": METRIC_METHOD_VERSION,
        "record_counts": counts,
        "protocols": [
            {
                **_protocol_json(item),
                "source_strata": [
                    _source_stratum_json(stratum) for stratum in strata_by_protocol.get(item.id, [])
                ],
            }
            for item in data.protocols
        ],
        "queries": [_query_json(item) for item in data.queries],
        "observations": [
            {
                **_observation_json(item),
                "citations": [
                    _citation_json(citation)
                    for citation in citations_by_observation.get(item.id, [])
                ],
            }
            for item in data.observations
        ],
        "metric_snapshots": [
            _snapshot_json(item, memberships_by_snapshot.get(item.id, []))
            for item in data.snapshots
        ],
        "approved_reports": [_report_json(item) for item in data.reports],
        "verified_urls": [_verified_url_json(item) for item in data.verified_urls],
    }
    return value, sum(counts.values())


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def time_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _record_counts(data: SortedExportData) -> dict[str, int]:
    snapshots = data.snapshots
    return {
        "protocols": len(data.protocols),
        "protocol_source_strata": len(data.source_strata),
        "queries": len(data.queries),
        "observations": len(data.observations),
        "observation_ineligible_reasons": sum(
            len(item.ineligible_reasons) for item in data.observations
        ),
        "observation_confounding_factors": sum(
            len(item.confounding_factors) for item in data.observations
        ),
        "citations": len(data.citations),
        "metric_snapshots": len(snapshots),
        "metric_observation_memberships": len(data.memberships),
        "metric_invalid_reason_counts": sum(
            len(item.invalid_reason_counts or ()) for item in snapshots
        ),
        "metric_declared_confounding_factors": sum(
            len(item.declared_confounding_factors or ()) for item in snapshots
        ),
        "metric_confounded_reasons": sum(len(item.confounded_reasons) for item in snapshots),
        "metric_destinations": sum(
            len(item.selected_destination_ids or ())
            + len(item.qualified_destination_ids or ())
            + len(item.verified_destination_ids or ())
            for item in snapshots
        ),
        "metric_query_results": sum(len(item.query_results_snapshot or ()) for item in snapshots),
        "metric_query_invalid_reason_counts": sum(
            len(result.invalid_reason_counts)
            for item in snapshots
            for result in (item.query_results_snapshot or ())
        ),
        "metric_query_confounding_factors": sum(
            len(result.confounding_factors)
            for item in snapshots
            for result in (item.query_results_snapshot or ())
        ),
        "approved_reports": len(data.reports),
        "verified_urls": len(data.verified_urls),
        "verified_url_protocols": sum(len(item.protocol_ids) for item in data.verified_urls),
    }


def _protocol_json(item: ProtocolExportRecord) -> dict[str, object]:
    return {
        **_scope_json(item),
        "id": str(item.id),
        "name": item.name,
        "platform": item.platform,
        "locale": item.locale,
        "device": item.device,
        "sample_size": item.sample_size,
        "window_days": item.window_days,
        "status": item.status,
        "protocol_hash": item.protocol_hash,
        "source_strata_hash": item.source_strata_hash,
        "minimum_valid_repeats": item.minimum_valid_repeats,
        "statistics_method_version": item.statistics_method_version,
        "statistics_contract_version": item.statistics_contract_version,
        "approved_at": time_text(item.approved_at) if item.approved_at else None,
        "frozen_at": time_text(item.frozen_at) if item.frozen_at else None,
    }


def _source_stratum_json(item: ProtocolSourceStratumExportRecord) -> dict[str, object]:
    return {
        "schema_version": PROJECT_EXPORT_SCHEMA_VERSION,
        "source_stratum_hash": item.source_stratum_hash,
        "source_contract_version": item.source_contract_version,
        "capture_method": item.capture_method,
        "platform": item.platform,
        "platform_detail": item.platform_detail,
        "surface": item.surface,
        "surface_detail": item.surface_detail,
        "surface_kind": item.surface_kind,
        "engine": item.engine,
        "configured_model": {"state": item.configured_model_state, "value": item.configured_model},
        "reported_model": {"state": item.reported_model_state, "value": item.reported_model},
        "locale": item.locale,
        "region": item.region,
        "language": item.language,
        "device": item.device,
        "client_kind": item.client_kind,
        "search_enabled": item.search_enabled,
        "search_mode": item.search_mode,
    }


def _query_json(item: QueryExportRecord) -> dict[str, object]:
    return {
        **_scope_json(item),
        "id": str(item.id),
        "protocol_id": str(item.protocol_id),
        "monitoring_query_id": str(item.monitoring_query_id),
        "query_text": item.query_text,
        "query_kind": item.query_kind,
        "locale": item.locale,
        "ordinal": item.ordinal,
        "query_cluster_key": item.query_cluster_key,
    }


def _observation_json(item: ObservationExportRecord) -> dict[str, object]:
    return {
        **_scope_json(item),
        "id": str(item.id),
        "protocol_id": str(item.protocol_id),
        "monitoring_query_id": str(item.monitoring_query_id),
        "query_cluster_key": item.query_cluster_key,
        "measurement_window": item.measurement_window,
        "source_stratum_hash": item.source_stratum_hash,
        "sample_index": item.sample_index,
        "result_status": item.result_status,
        "eligible": item.eligible,
        "url_verification_status": item.url_verification_status,
        "recommendation_present": item.recommendation_present,
        "primary_product_mentioned": item.primary_product_mentioned,
        "competitor_mentioned": item.competitor_mentioned,
        "ineligible_reasons": sorted(item.ineligible_reasons),
        "confounding_factors": sorted(item.confounding_factors),
        "capture_method": item.capture_method,
        "platform": item.platform,
        "surface": item.surface,
        "engine": item.engine,
        "answer_text": item.answer_text,
        "payload_hash": item.payload_hash,
        "observed_at": time_text(item.observed_at),
    }


def _citation_json(item: CitationExportRecord) -> dict[str, object]:
    return {
        "schema_version": PROJECT_EXPORT_SCHEMA_VERSION,
        "observation_id": str(item.observation_id),
        "citation_index": item.citation_index,
        "project_id": str(item.project_id),
        "campaign_id": str(item.campaign_id),
        "protocol_id": str(item.protocol_id),
        "url": item.url,
        "title": item.title,
        "verification_status": item.verification_status,
        "verified_placement": item.verified_placement,
        "destination_id": str(item.destination_id) if item.destination_id else None,
        "submission_id": str(item.submission_id) if item.submission_id else None,
        "verified_at": time_text(item.verified_at) if item.verified_at else None,
    }


def _snapshot_json(
    item: AnyMetricSnapshotExportRecord,
    memberships: list[MetricObservationMembershipExportRecord],
) -> dict[str, object]:
    value = _json_scalars(
        item,
        {
            "invalid_reason_counts",
            "declared_confounding_factors",
            "query_results_snapshot",
            "selected_destination_ids",
            "qualified_destination_ids",
            "verified_destination_ids",
            "confounded_reasons",
        },
    )
    if isinstance(item, LegacyMetricSnapshotExportRecord):
        value.update(
            {
                "invalid_reason_counts": None,
                "declared_confounding_factors": None,
                "query_results_snapshot": None,
                "selected_destination_ids": None,
                "qualified_destination_ids": None,
                "verified_destination_ids": None,
                "confounded_reasons": sorted(item.confounded_reasons),
                "observation_memberships": None,
            }
        )
        return value
    value.update(
        {
            "invalid_reason_counts": {
                entry.reason: entry.count
                for entry in sorted(item.invalid_reason_counts, key=lambda entry: entry.reason)
            },
            "declared_confounding_factors": sorted(item.declared_confounding_factors),
            "query_results_snapshot": [
                _query_result_json(result)
                for result in sorted(
                    item.query_results_snapshot, key=lambda result: str(result.monitoring_query_id)
                )
            ],
            "selected_destination_ids": sorted(map(str, item.selected_destination_ids)),
            "qualified_destination_ids": sorted(map(str, item.qualified_destination_ids)),
            "verified_destination_ids": sorted(map(str, item.verified_destination_ids)),
            "confounded_reasons": sorted(item.confounded_reasons),
            "observation_memberships": (
                [_json_scalars(membership, set()) for membership in memberships]
                if item.observation_membership_version is not None
                else None
            ),
        }
    )
    return value


def _query_result_json(item: QueryMetricResultExportRecord) -> dict[str, object]:
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
        "recommendation": _estimate_json(item.recommendation),
        "product_mention": _estimate_json(item.product_mention),
        "placement_citation": _estimate_json(item.placement_citation),
        "competitor": _estimate_json(item.competitor),
        "competitive_delta": float(item.competitive_delta),
    }


def _estimate_json(item: MetricEstimateExportRecord) -> dict[str, object]:
    return {
        "numerator": item.numerator,
        "denominator": item.denominator,
        "share": float(item.share),
        "ci_low": float(item.ci_low),
        "ci_high": float(item.ci_high),
    }


def _report_json(item: ApprovedReportExportRecord) -> dict[str, object]:
    return {
        **_scope_json(item),
        "id": str(item.id),
        "protocol_id": str(item.protocol_id),
        "metric_snapshot_id": str(item.metric_snapshot_id),
        "title": item.title,
        "body": item.body,
        "methodology_statement": item.methodology_statement,
        "report_hash": item.report_hash,
        "generated_at": time_text(item.generated_at),
        "approved_at": time_text(item.approved_at),
    }


def _verified_url_json(item: VerifiedUrlExportRecord) -> dict[str, object]:
    return {
        **_scope_json(item),
        "protocol_ids": sorted(map(str, item.protocol_ids)),
        "url": item.url,
        "title": item.title,
        "destination_id": str(item.destination_id) if item.destination_id else None,
        "first_verified_at": time_text(item.first_verified_at),
        "observation_count": item.observation_count,
    }


def _flat(item: object, excluded: set[str] | None = None) -> dict[str, object]:
    excluded = excluded or set()
    return {
        "schema_version": PROJECT_EXPORT_SCHEMA_VERSION,
        **{key: value for key, value in item.__dict__.items() if key not in excluded},
    }


def _json_scalars(item: object, excluded: set[str]) -> dict[str, object]:
    value = _flat(item, excluded)
    return {key: _json_scalar(field) for key, field in value.items()}


def _json_scalar(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return time_text(value)
    raise ProjectExportRuleViolation(f"JSON does not support scalar type {type(value).__name__}")


def _scope_json(item: object) -> dict[str, object]:
    return {
        "schema_version": PROJECT_EXPORT_SCHEMA_VERSION,
        "project_id": str(getattr(item, "project_id")),
        "campaign_id": str(getattr(item, "campaign_id")),
    }
