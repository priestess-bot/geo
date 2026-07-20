"""Byte, manifest, schema, scope, and ordering verification for F027 bundles."""

from __future__ import annotations

import csv
from dataclasses import dataclass, fields
from datetime import datetime
import hashlib
import io
import json
from typing import Any, Mapping, Sequence, cast
from uuid import UUID

from geo_core.project_exports.constants import (
    DATA_JSON_PATH,
    LEGACY_STATISTICS_CONTRACT_VERSION,
    MANIFEST_PATH,
    METRIC_METHOD_VERSION,
    PROJECT_EXPORT_MANIFEST_SCHEMA_VERSION,
    PROJECT_EXPORT_SCHEMA_VERSION,
)
from geo_core.project_exports.contracts import (
    ApprovedReportExportRecord,
    CitationExportRecord,
    MetricSnapshotExportRecord,
    ObservationExportRecord,
    ProtocolExportRecord,
    QueryExportRecord,
    VerifiedUrlExportRecord,
)
from geo_core.project_exports.errors import ProjectExportVerificationError
from geo_core.project_exports.membership_verification import verify_metric_memberships
from geo_core.project_exports.schemas import CSV_SCHEMAS
from geo_core.project_exports.schema_verification import verify_descriptor
from geo_core.project_exports.serialization import canonical_json_bytes
from geo_core.project_exports.source_stratum_verification import (
    source_strata_inventory_hash,
    verify_source_stratum,
)
from geo_core.project_exports.statistics_contracts import (
    MetricEstimateExportRecord,
    QueryMetricResultExportRecord,
)


@dataclass(frozen=True)
class VerifiedProjectExport:
    manifest_hash: str
    data: dict[str, object]


def verify_project_export(files: Mapping[str, bytes]) -> VerifiedProjectExport:
    manifest_content = required_file(files, MANIFEST_PATH)
    manifest = json_object(manifest_content, "manifest")
    exact_keys(
        manifest,
        {
            "schema_version",
            "export_schema_version",
            "audience",
            "scope",
            "generated_at",
            "metric_method_version",
            "files",
            "manifest_hash",
        },
        "manifest",
    )
    if manifest["schema_version"] != PROJECT_EXPORT_MANIFEST_SCHEMA_VERSION:
        raise ProjectExportVerificationError("unsupported manifest schema_version")
    if manifest["export_schema_version"] != PROJECT_EXPORT_SCHEMA_VERSION:
        raise ProjectExportVerificationError("unsupported export schema_version")
    if manifest["metric_method_version"] != METRIC_METHOD_VERSION:
        raise ProjectExportVerificationError("manifest metric method version mismatch")
    if manifest["audience"] not in {"admin", "customer"}:
        raise ProjectExportVerificationError("manifest audience is unsupported")
    timestamp_text(manifest["generated_at"], "manifest generated_at")
    if canonical_json_bytes(manifest) != manifest_content:
        raise ProjectExportVerificationError("manifest JSON is not canonical")
    supplied_hash = sha_text(manifest["manifest_hash"], "manifest_hash")
    manifest_payload = dict(manifest)
    del manifest_payload["manifest_hash"]
    if hashlib.sha256(canonical_json_bytes(manifest_payload)).hexdigest() != supplied_hash:
        raise ProjectExportVerificationError("canonical manifest hash mismatch")

    descriptors = _descriptors(manifest["files"])
    expected_paths = {DATA_JSON_PATH, *CSV_SCHEMAS}
    if {cast(str, item["path"]) for item in descriptors} != expected_paths:
        raise ProjectExportVerificationError("manifest file inventory is not the frozen F027 set")
    if set(files) != expected_paths | {MANIFEST_PATH}:
        raise ProjectExportVerificationError("bundle contains missing or unmanifested files")
    for descriptor in descriptors:
        verify_descriptor(files, descriptor)

    data_content = required_file(files, DATA_JSON_PATH)
    data = json_object(data_content, "project export")
    if canonical_json_bytes(data) != data_content:
        raise ProjectExportVerificationError("project JSON is not canonical")
    _validate_data(data, manifest)
    descriptor_by_path = {cast(str, item["path"]): item for item in descriptors}
    record_counts = mapping(data["record_counts"], "record_counts")
    json_rows = sum(
        integer(value, f"record_counts.{name}") for name, value in record_counts.items()
    )
    if descriptor_by_path[DATA_JSON_PATH]["row_count"] != json_rows:
        raise ProjectExportVerificationError("project JSON record count does not match manifest")
    for path, schema in CSV_SCHEMAS.items():
        rows = _csv_rows(required_file(files, path), [name for name, _ in schema])
        if descriptor_by_path[path]["row_count"] != len(rows):
            raise ProjectExportVerificationError(f"{path} row count does not match manifest")
        count_key = path.removesuffix(".csv")
        if len(rows) != integer(record_counts[count_key], f"record_counts.{count_key}"):
            raise ProjectExportVerificationError(
                f"{path} row count differs from the canonical JSON projection"
            )
    return VerifiedProjectExport(manifest_hash=supplied_hash, data=data)


def _validate_data(data: Mapping[str, object], manifest: Mapping[str, object]) -> None:
    exact_keys(
        data,
        {
            "schema_version",
            "audience",
            "scope",
            "metric_method_version",
            "record_counts",
            "protocols",
            "queries",
            "observations",
            "metric_snapshots",
            "approved_reports",
            "verified_urls",
        },
        "project export",
    )
    if data["schema_version"] != PROJECT_EXPORT_SCHEMA_VERSION:
        raise ProjectExportVerificationError("project JSON schema version mismatch")
    if data["metric_method_version"] != METRIC_METHOD_VERSION:
        raise ProjectExportVerificationError("project JSON metric method version mismatch")
    if data["scope"] != manifest["scope"] or data["audience"] != manifest["audience"]:
        raise ProjectExportVerificationError("project JSON scope or audience differs from manifest")
    scope = mapping(data["scope"], "scope")
    exact_keys(scope, {"project_id", "campaign_id"}, "scope")
    project_id = uuid_text(scope["project_id"], "scope project_id")
    campaign_id = scope["campaign_id"]
    if campaign_id is not None:
        campaign_id = uuid_text(campaign_id, "scope campaign_id")

    protocols = object_list(data["protocols"], "protocols")
    queries = object_list(data["queries"], "queries")
    observations = object_list(data["observations"], "observations")
    observations_by_id = {uuid_text(item["id"], "observation id"): item for item in observations}
    if len(observations_by_id) != len(observations):
        raise ProjectExportVerificationError("observation ids must be unique")
    snapshots = object_list(data["metric_snapshots"], "metric snapshots")
    reports = object_list(data["approved_reports"], "approved reports")
    urls = object_list(data["verified_urls"], "verified URLs")
    nested_counts = {
        "protocol_source_strata": 0,
        "observation_ineligible_reasons": 0,
        "observation_confounding_factors": 0,
        "citations": 0,
        "metric_observation_memberships": 0,
        "metric_invalid_reason_counts": 0,
        "metric_declared_confounding_factors": 0,
        "metric_confounded_reasons": 0,
        "metric_destinations": 0,
        "metric_query_results": 0,
        "metric_query_invalid_reason_counts": 0,
        "metric_query_confounding_factors": 0,
        "verified_url_protocols": 0,
    }
    for protocol in protocols:
        exact_keys(protocol, _record_keys(ProtocolExportRecord) | {"source_strata"}, "protocol")
        _record_scope(protocol, project_id, campaign_id, "protocol")
        strata = object_list(protocol["source_strata"], "protocol source strata")
        _sorted_unique(
            strata, lambda item: text(item["source_stratum_hash"], "stratum hash"), "source strata"
        )
        for stratum in strata:
            exact_keys(
                stratum,
                {
                    "schema_version",
                    "source_stratum_hash",
                    "source_contract_version",
                    "capture_method",
                    "platform",
                    "platform_detail",
                    "surface",
                    "surface_detail",
                    "surface_kind",
                    "engine",
                    "configured_model",
                    "reported_model",
                    "locale",
                    "region",
                    "language",
                    "device",
                    "client_kind",
                    "search_enabled",
                    "search_mode",
                },
                "protocol source stratum",
            )
            for model in ("configured_model", "reported_model"):
                exact_keys(mapping(stratum[model], model), {"state", "value"}, model)
            verify_source_stratum(stratum)
        if protocol["source_strata_hash"] is None:
            if strata:
                raise ProjectExportVerificationError(
                    "protocol without an inventory hash cannot export source strata"
                )
        else:
            expected_inventory_hash = source_strata_inventory_hash(strata)
            if protocol["source_strata_hash"] != expected_inventory_hash:
                raise ProjectExportVerificationError(
                    "protocol source strata inventory hash cannot be reproduced"
                )
        nested_counts["protocol_source_strata"] += len(strata)
    for query in queries:
        exact_keys(query, _record_keys(QueryExportRecord), "query")
        _record_scope(query, project_id, campaign_id, "query")
    for observation in observations:
        exact_keys(
            observation, _record_keys(ObservationExportRecord) | {"citations"}, "observation"
        )
        _record_scope(observation, project_id, campaign_id, "observation")
        for field_name, counter in (
            ("ineligible_reasons", "observation_ineligible_reasons"),
            ("confounding_factors", "observation_confounding_factors"),
        ):
            values = sorted_unique_text(observation[field_name], f"observation {field_name}")
            nested_counts[counter] += len(values)
        citations = object_list(observation["citations"], "observation citations")
        _sorted_unique(
            citations, lambda item: integer(item["citation_index"], "citation index"), "citations"
        )
        for citation in citations:
            exact_keys(citation, _record_keys(CitationExportRecord), "citation")
            _record_scope(citation, project_id, campaign_id, "citation")
        nested_counts["citations"] += len(citations)
    for snapshot in snapshots:
        exact_keys(
            snapshot,
            _record_keys(MetricSnapshotExportRecord) | {"observation_memberships"},
            "metric snapshot",
        )
        _record_scope(snapshot, project_id, campaign_id, "metric snapshot")
        nested_counts["metric_confounded_reasons"] += len(
            sorted_unique_text(snapshot["confounded_reasons"], "metric confounded_reasons")
        )
        if snapshot["statistics_contract_version"] == LEGACY_STATISTICS_CONTRACT_VERSION:
            legacy_null_fields = {
                "query_cluster_key",
                "analysis_stratum_hash",
                "minimum_valid_repeats",
                "observation_membership_version",
                "observation_membership_count",
                "observation_membership_hash",
                "sampled_sample_count",
                "invalid_sample_count",
                "missing_sample_count",
                "sampling_completion_ratio",
                "valid_completion_ratio",
                "query_count",
                "sufficient_query_count",
                "invalid_reason_counts",
                "declared_confounding_factors",
                "query_results_snapshot",
                "recommendation_ci_low",
                "recommendation_ci_high",
                "product_mention_ci_low",
                "product_mention_ci_high",
                "placement_citation_ci_low",
                "placement_citation_ci_high",
                "recommendation_query_min",
                "recommendation_query_max",
                "product_mention_query_min",
                "product_mention_query_max",
                "placement_citation_query_min",
                "placement_citation_query_max",
                "worst_query_id",
                "selected_destination_ids",
                "qualified_destination_ids",
                "verified_destination_ids",
                "result_hash",
            }
            if any(snapshot[name] is not None for name in legacy_null_fields):
                raise ProjectExportVerificationError(
                    "legacy metric fabricates statistics-v2 fields"
                )
            if snapshot["observation_memberships"] is not None:
                raise ProjectExportVerificationError(
                    "legacy metric fabricates observation membership"
                )
            continue
        if snapshot["statistics_contract_version"] != METRIC_METHOD_VERSION:
            raise ProjectExportVerificationError("metric statistics contract is unsupported")
        memberships = verify_metric_memberships(
            snapshot,
            observations_by_id=observations_by_id,
            project_id=project_id,
            campaign_id=campaign_id,
        )
        nested_counts["metric_observation_memberships"] += len(memberships)
        reasons = mapping(snapshot["invalid_reason_counts"], "metric invalid reasons")
        _positive_count_mapping(reasons, "metric invalid reasons")
        nested_counts["metric_invalid_reason_counts"] += len(reasons)
        nested_counts["metric_declared_confounding_factors"] += len(
            sorted_unique_text(
                snapshot["declared_confounding_factors"],
                "metric declared_confounding_factors",
            )
        )
        for field_name in (
            "selected_destination_ids",
            "qualified_destination_ids",
            "verified_destination_ids",
        ):
            nested_counts["metric_destinations"] += len(
                sorted_unique_text(snapshot[field_name], field_name)
            )
        query_results = object_list(snapshot["query_results_snapshot"], "query results")
        _sorted_unique(
            query_results,
            lambda item: uuid_text(item["monitoring_query_id"], "query result id"),
            "query results",
        )
        for result in query_results:
            exact_keys(
                result,
                _record_keys(QueryMetricResultExportRecord, include_schema=False),
                "query result",
            )
            invalid = mapping(result["invalid_reason_counts"], "query invalid reasons")
            _positive_count_mapping(invalid, "query invalid reasons")
            nested_counts["metric_query_invalid_reason_counts"] += len(invalid)
            nested_counts["metric_query_confounding_factors"] += len(
                sorted_unique_text(result["confounding_factors"], "query confounding factors")
            )
            for estimate_name in (
                "recommendation",
                "product_mention",
                "placement_citation",
                "competitor",
            ):
                exact_keys(
                    mapping(result[estimate_name], estimate_name),
                    _record_keys(MetricEstimateExportRecord, include_schema=False),
                    f"query {estimate_name}",
                )
        nested_counts["metric_query_results"] += len(query_results)
    for report in reports:
        exact_keys(report, _record_keys(ApprovedReportExportRecord), "approved report")
        _record_scope(report, project_id, campaign_id, "approved report")
    for url in urls:
        exact_keys(url, _record_keys(VerifiedUrlExportRecord), "verified URL")
        _record_scope(url, project_id, campaign_id, "verified URL")
        nested_counts["verified_url_protocols"] += len(
            sorted_unique_text(url["protocol_ids"], "verified URL protocol IDs")
        )

    _assert_collection_order(protocols, queries, observations, snapshots, reports, urls)
    expected_counts = {
        "protocols": len(protocols),
        "queries": len(queries),
        "observations": len(observations),
        "metric_snapshots": len(snapshots),
        "approved_reports": len(reports),
        "verified_urls": len(urls),
        **nested_counts,
    }
    if mapping(data["record_counts"], "record_counts") != expected_counts:
        raise ProjectExportVerificationError("project JSON record_counts do not match content")


def _assert_collection_order(
    protocols: list[dict[str, object]],
    queries: list[dict[str, object]],
    observations: list[dict[str, object]],
    snapshots: list[dict[str, object]],
    reports: list[dict[str, object]],
    urls: list[dict[str, object]],
) -> None:
    _sorted_unique(protocols, lambda item: text(item["id"], "protocol id"), "protocols")
    _sorted_unique(
        queries,
        lambda item: (
            text(item["protocol_id"], "query protocol"),
            integer(item["ordinal"], "query ordinal"),
            text(item["id"], "query id"),
        ),
        "queries",
    )
    _sorted_unique(
        observations,
        lambda item: (
            text(item["protocol_id"], "observation protocol"),
            text(item["measurement_window"], "observation window"),
            item["source_stratum_hash"] or "",
            item["query_cluster_key"] or "",
            text(item["monitoring_query_id"], "observation query"),
            integer(item["sample_index"], "observation sample"),
            text(item["id"], "observation id"),
        ),
        "observations",
    )
    _sorted_unique(
        snapshots,
        lambda item: (
            text(item["protocol_id"], "snapshot protocol"),
            text(item["measurement_window"], "snapshot window"),
            item["source_stratum_hash"] or "",
            item["query_cluster_key"] or "",
            text(item["computed_at"], "snapshot computed_at"),
            text(item["id"], "snapshot id"),
        ),
        "metric snapshots",
    )
    _sorted_unique(
        reports,
        lambda item: (
            text(item["protocol_id"], "report protocol"),
            text(item["approved_at"], "report approved_at"),
            text(item["id"], "report id"),
        ),
        "approved reports",
    )
    _sorted_unique(
        urls,
        lambda item: (
            text(item["campaign_id"], "verified URL campaign"),
            text(item["url"], "verified URL"),
        ),
        "verified URLs",
    )


def _descriptors(value: object) -> list[dict[str, object]]:
    descriptors = object_list(value, "manifest files")
    paths = [text(item.get("path"), "manifest file path") for item in descriptors]
    if paths != sorted(paths) or len(set(paths)) != len(paths):
        raise ProjectExportVerificationError("manifest files are not uniquely sorted")
    return descriptors


def _record_keys(record_type: type[object], *, include_schema: bool = True) -> set[str]:
    result = {field.name for field in fields(cast(Any, record_type))}
    if include_schema:
        result.add("schema_version")
    return result


def _record_scope(
    value: Mapping[str, object], project_id: str, campaign_id: object, label: str
) -> None:
    if value["schema_version"] != PROJECT_EXPORT_SCHEMA_VERSION:
        raise ProjectExportVerificationError(f"{label} schema version mismatch")
    if value["project_id"] != project_id:
        raise ProjectExportVerificationError(f"{label} crosses project scope")
    if campaign_id is not None and value["campaign_id"] != campaign_id:
        raise ProjectExportVerificationError(f"{label} crosses campaign scope")


def _positive_count_mapping(value: Mapping[str, object], label: str) -> None:
    if any(not key or integer(count, label) <= 0 for key, count in value.items()):
        raise ProjectExportVerificationError(f"{label} must contain positive integer counts")


def _csv_rows(content: bytes, expected_header: Sequence[str]) -> list[dict[str, str]]:
    try:
        value = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectExportVerificationError("CSV is not valid UTF-8") from exc
    reader = csv.DictReader(io.StringIO(value, newline=""))
    if reader.fieldnames != list(expected_header):
        raise ProjectExportVerificationError("CSV header does not match frozen column order")
    return list(reader)


def json_object(content: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(content.decode("utf-8"), parse_constant=_reject_non_finite)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectExportVerificationError(f"{label} is not canonical UTF-8 JSON") from exc
    return mapping(value, label)


def _reject_non_finite(token: str) -> object:
    raise ProjectExportVerificationError(f"JSON contains non-finite number {token}")


def required_file(files: Mapping[str, bytes], path: str) -> bytes:
    try:
        value = files[path]
    except KeyError as exc:
        raise ProjectExportVerificationError(f"missing export file {path}") from exc
    if not isinstance(value, bytes):
        raise ProjectExportVerificationError(f"export file {path} must be bytes")
    return value


def mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProjectExportVerificationError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def object_list(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ProjectExportVerificationError(f"{label} must be a JSON array")
    return [mapping(item, label) for item in value]


def exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ProjectExportVerificationError(f"{label} does not match the public field whitelist")


def text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectExportVerificationError(f"{label} must be non-empty text")
    return value


def uuid_text(value: object, label: str) -> str:
    result = text(value, label)
    try:
        parsed = UUID(result)
    except ValueError as exc:
        raise ProjectExportVerificationError(f"{label} must be a UUID") from exc
    if str(parsed) != result:
        raise ProjectExportVerificationError(f"{label} must be a canonical UUID")
    return result


def sha_text(value: object, label: str) -> str:
    result = text(value, label)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ProjectExportVerificationError(f"{label} must be a lowercase SHA-256")
    return result


def timestamp_text(value: object, label: str) -> str:
    result = text(value, label)
    if not result.endswith("Z"):
        raise ProjectExportVerificationError(f"{label} must be a canonical UTC timestamp")
    try:
        datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProjectExportVerificationError(f"{label} must be an ISO timestamp") from exc
    return result


def integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProjectExportVerificationError(f"{label} must be an integer")
    return value


def sorted_unique_text(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ProjectExportVerificationError(f"{label} must be an array")
    result = [text(item, label) for item in value]
    if result != sorted(result) or len(set(result)) != len(result):
        raise ProjectExportVerificationError(f"{label} must be uniquely sorted")
    return result


def _sorted_unique(values: Sequence[dict[str, object]], key: object, label: str) -> None:
    key_function = key
    keys = [key_function(item) for item in values]  # type: ignore[operator]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise ProjectExportVerificationError(f"{label} must have deterministic unique ordering")
