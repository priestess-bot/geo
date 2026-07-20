"""Normalized CSV projections for deterministic F027 bundles."""

from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal
import io
from typing import Mapping, Sequence
from uuid import UUID

from geo_core.csv_security import neutralize_spreadsheet_formula
from geo_core.project_exports.constants import PROJECT_EXPORT_SCHEMA_VERSION
from geo_core.project_exports.contracts import (
    AnyMetricSnapshotExportRecord,
    ProjectExportRuleViolation,
)
from geo_core.project_exports.schemas import CSV_SCHEMAS, ColumnSchema
from geo_core.project_exports.serialization import SortedExportData, time_text


def csv_projections(data: SortedExportData) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {
        "protocols.csv": [_flat(item) for item in data.protocols],
        "protocol_source_strata.csv": [_flat(item) for item in data.source_strata],
        "queries.csv": [_flat(item) for item in data.queries],
        "observations.csv": [
            _flat(item, {"ineligible_reasons", "confounding_factors"})
            for item in data.observations
        ],
        "observation_ineligible_reasons.csv": [
            _versioned(observation_id=item.id, reason=reason)
            for item in data.observations
            for reason in sorted(item.ineligible_reasons)
        ],
        "observation_confounding_factors.csv": [
            _versioned(observation_id=item.id, factor=factor)
            for item in data.observations
            for factor in sorted(item.confounding_factors)
        ],
        "citations.csv": [_flat(item) for item in data.citations],
        "metric_snapshots.csv": [_flat_snapshot(item) for item in data.snapshots],
        "metric_observation_memberships.csv": [_flat(item) for item in data.memberships],
        "metric_invalid_reason_counts.csv": [
            _versioned(metric_snapshot_id=item.id, reason=value.reason, count=value.count)
            for item in data.snapshots
            for value in sorted(item.invalid_reason_counts or (), key=lambda value: value.reason)
        ],
        "metric_declared_confounding_factors.csv": [
            _versioned(metric_snapshot_id=item.id, factor=value)
            for item in data.snapshots
            for value in sorted(item.declared_confounding_factors or ())
        ],
        "metric_confounded_reasons.csv": [
            _versioned(metric_snapshot_id=item.id, reason=value)
            for item in data.snapshots
            for value in sorted(item.confounded_reasons)
        ],
        "metric_destinations.csv": _destination_rows(data.snapshots),
        "metric_query_results.csv": _query_result_rows(data.snapshots),
        "metric_query_invalid_reason_counts.csv": _query_invalid_rows(data.snapshots),
        "metric_query_confounding_factors.csv": _query_confounder_rows(data.snapshots),
        "approved_reports.csv": [_flat(item) for item in data.reports],
        "verified_urls.csv": [_flat(item, {"protocol_ids"}) for item in data.verified_urls],
        "verified_url_protocols.csv": [
            _versioned(
                project_id=item.project_id,
                campaign_id=item.campaign_id,
                url=item.url,
                protocol_id=protocol_id,
            )
            for item in data.verified_urls
            for protocol_id in sorted(item.protocol_ids, key=str)
        ],
    }
    if set(result) != set(CSV_SCHEMAS):
        raise ProjectExportRuleViolation("CSV projection inventory differs from frozen schemas")
    return result


def render_csv(schema: ColumnSchema, rows: Sequence[Mapping[str, object]]) -> bytes:
    names = [name for name, _ in schema]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=names, extrasaction="raise", lineterminator="\r\n"
    )
    writer.writeheader()
    for row in rows:
        if set(row) != set(names):
            raise ProjectExportRuleViolation("CSV projection does not match its frozen schema")
        writer.writerow({name: _csv_scalar(row[name]) for name in names})
    return buffer.getvalue().encode("utf-8")


def _flat(item: object, excluded: set[str] | None = None) -> dict[str, object]:
    excluded = excluded or set()
    return {
        "schema_version": PROJECT_EXPORT_SCHEMA_VERSION,
        **{key: value for key, value in item.__dict__.items() if key not in excluded},
    }


def _flat_snapshot(item: AnyMetricSnapshotExportRecord) -> dict[str, object]:
    return _flat(
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


def _destination_rows(
    snapshots: Sequence[AnyMetricSnapshotExportRecord],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for snapshot in snapshots:
        for set_name in ("selected", "qualified", "verified"):
            values = getattr(snapshot, f"{set_name}_destination_ids")
            rows.extend(
                _versioned(
                    metric_snapshot_id=snapshot.id,
                    destination_set=set_name,
                    destination_id=destination_id,
                )
                for destination_id in sorted(values or (), key=str)
            )
    return rows


def _query_result_rows(
    snapshots: Sequence[AnyMetricSnapshotExportRecord],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for snapshot in snapshots:
        for item in sorted(
            snapshot.query_results_snapshot or (),
            key=lambda value: str(value.monitoring_query_id),
        ):
            row = _versioned(
                metric_snapshot_id=snapshot.id,
                monitoring_query_id=item.monitoring_query_id,
                query_text_snapshot=item.query_text_snapshot,
                query_cluster_key=item.query_cluster_key,
                expected_sample_count=item.expected_sample_count,
                sampled_sample_count=item.sampled_sample_count,
                valid_sample_count=item.valid_sample_count,
                invalid_sample_count=item.invalid_sample_count,
                missing_sample_count=item.missing_sample_count,
                meets_threshold=item.meets_threshold,
                competitive_delta=item.competitive_delta,
            )
            for name in ("recommendation", "product_mention", "placement_citation", "competitor"):
                estimate = getattr(item, name)
                for field in ("numerator", "denominator", "share", "ci_low", "ci_high"):
                    row[f"{name}_{field}"] = getattr(estimate, field)
            rows.append(row)
    return rows


def _query_invalid_rows(
    snapshots: Sequence[AnyMetricSnapshotExportRecord],
) -> list[dict[str, object]]:
    return [
        _versioned(
            metric_snapshot_id=snapshot.id,
            monitoring_query_id=result.monitoring_query_id,
            reason=value.reason,
            count=value.count,
        )
        for snapshot in snapshots
        for result in sorted(
            snapshot.query_results_snapshot or (),
            key=lambda value: str(value.monitoring_query_id),
        )
        for value in sorted(result.invalid_reason_counts, key=lambda value: value.reason)
    ]


def _query_confounder_rows(
    snapshots: Sequence[AnyMetricSnapshotExportRecord],
) -> list[dict[str, object]]:
    return [
        _versioned(
            metric_snapshot_id=snapshot.id,
            monitoring_query_id=result.monitoring_query_id,
            factor=factor,
        )
        for snapshot in snapshots
        for result in sorted(
            snapshot.query_results_snapshot or (),
            key=lambda value: str(value.monitoring_query_id),
        )
        for factor in sorted(result.confounding_factors)
    ]


def _versioned(**values: object) -> dict[str, object]:
    return {"schema_version": PROJECT_EXPORT_SCHEMA_VERSION, **values}


def _csv_scalar(value: object) -> str | int:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return time_text(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ProjectExportRuleViolation("CSV cannot contain NaN or infinite Decimal values")
        return format(value, ".6f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        return neutralize_spreadsheet_formula(value)
    if isinstance(value, int):
        return value
    raise ProjectExportRuleViolation(f"CSV does not support scalar type {type(value).__name__}")
