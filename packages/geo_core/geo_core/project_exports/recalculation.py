"""Independent F021-aligned KPI recalculation from rendered F027 bytes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from typing import Mapping

from geo_core.project_exports.constants import (
    LEGACY_STATISTICS_CONTRACT_VERSION,
    METRIC_METHOD_VERSION,
)
from geo_core.project_exports.errors import ProjectExportVerificationError
from geo_core.project_exports.verification import (
    mapping,
    object_list,
    text,
    verify_project_export,
)


@dataclass(frozen=True)
class RecalculatedMetric:
    metric_snapshot_id: str
    analysis_stratum_hash: str
    query_cluster_key: str
    eligible_sample_count: int
    recommendation_share: Decimal
    mention_share: Decimal
    verified_citation_rate: Decimal
    method_version: str


@dataclass(frozen=True)
class ProjectExportRecalculation:
    manifest_hash: str
    metrics: tuple[RecalculatedMetric, ...]
    unrecalculable: tuple[UnrecalculableMetric, ...]


@dataclass(frozen=True)
class UnrecalculableMetric:
    metric_snapshot_id: str
    reason: str


def recalculate_project_export(
    files: Mapping[str, bytes],
) -> ProjectExportRecalculation:
    """Verify every byte and reproduce three KPIs per full analysis stratum."""
    verified = verify_project_export(files)
    metrics, unrecalculable = _recalculate_metrics(verified.data)
    return ProjectExportRecalculation(
        manifest_hash=verified.manifest_hash,
        metrics=metrics,
        unrecalculable=unrecalculable,
    )


def _recalculate_metrics(
    data: Mapping[str, object],
) -> tuple[tuple[RecalculatedMetric, ...], tuple[UnrecalculableMetric, ...]]:
    observations = object_list(data["observations"], "observations")
    observations_by_id = {
        text(item["id"], "observation id"): item for item in observations
    }
    queries = object_list(data["queries"], "queries")
    snapshots = object_list(data["metric_snapshots"], "metric snapshots")
    result: list[RecalculatedMetric] = []
    unrecalculable: list[UnrecalculableMetric] = []
    for snapshot in snapshots:
        if snapshot["statistics_contract_version"] == LEGACY_STATISTICS_CONTRACT_VERSION:
            unrecalculable.append(
                UnrecalculableMetric(
                    metric_snapshot_id=text(snapshot["id"], "metric snapshot id"),
                    reason="legacy_statistics_contract_has_no_frozen_analysis_stratum",
                )
            )
            continue
        if snapshot["observation_membership_version"] is None:
            unrecalculable.append(
                UnrecalculableMetric(
                    metric_snapshot_id=text(snapshot["id"], "metric snapshot id"),
                    reason="historical_statistics_v2_has_no_frozen_observation_membership",
                )
            )
            continue
        method_version = text(snapshot["method_version"], "metric method_version")
        if method_version != METRIC_METHOD_VERSION:
            raise ProjectExportVerificationError("metric snapshot method version mismatch")
        if snapshot["statistics_contract_version"] != METRIC_METHOD_VERSION:
            raise ProjectExportVerificationError("statistics contract version mismatch")
        expected_analysis_hash = hashlib.sha256(
            json.dumps(
                {
                    "query_cluster_key": snapshot["query_cluster_key"],
                    "source_stratum_hash": snapshot["source_stratum_hash"],
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        if snapshot["analysis_stratum_hash"] != expected_analysis_hash:
            raise ProjectExportVerificationError("analysis stratum hash cannot be reproduced")
        group = (
            snapshot["project_id"], snapshot["campaign_id"], snapshot["protocol_id"],
            snapshot["measurement_window"], snapshot["source_stratum_hash"],
            snapshot["query_cluster_key"],
        )
        memberships = object_list(
            snapshot["observation_memberships"], "metric observation memberships"
        )
        stratum: list[dict[str, object]] = []
        for membership in memberships:
            observation_id = text(
                membership["observation_id"], "membership observation id"
            )
            try:
                observation = observations_by_id[observation_id]
            except KeyError as exc:
                raise ProjectExportVerificationError(
                    "metric membership observation is missing"
                ) from exc
            if membership["payload_hash"] != observation["payload_hash"]:
                raise ProjectExportVerificationError(
                    "metric membership payload hash cannot be reproduced"
                )
            if (
                observation["project_id"], observation["campaign_id"],
                observation["protocol_id"], observation["measurement_window"],
                observation["source_stratum_hash"], observation["query_cluster_key"],
            ) != group:
                raise ProjectExportVerificationError(
                    "metric membership crosses its analysis stratum"
                )
            stratum.append(observation)
        included = [
            item for item in stratum
            if _boolean(item["eligible"], "observation eligible")
            and item["result_status"] == "succeeded"
        ]
        denominator = len(included)
        recommendation = _ratio(
            sum(_boolean(item["recommendation_present"], "recommendation flag") for item in included),
            denominator,
        )
        mention = _ratio(
            sum(_boolean(item["primary_product_mentioned"], "mention flag") for item in included),
            denominator,
        )
        selected = set(_text_list(snapshot["selected_destination_ids"], "selected destinations"))
        cited = 0
        for observation in included:
            if observation["url_verification_status"] != "passed":
                continue
            citations = object_list(observation["citations"], "observation citations")
            if _has_valid_citation(citations, selected):
                cited += 1
        verified_citation_rate = _ratio(cited, denominator)
        metric = RecalculatedMetric(
            metric_snapshot_id=text(snapshot["id"], "metric snapshot id"),
            analysis_stratum_hash=text(snapshot["analysis_stratum_hash"], "analysis stratum hash"),
            query_cluster_key=text(snapshot["query_cluster_key"], "query cluster key"),
            eligible_sample_count=denominator,
            recommendation_share=recommendation,
            mention_share=mention,
            verified_citation_rate=verified_citation_rate,
            method_version=method_version,
        )
        if _integer(snapshot["sampled_sample_count"], "sampled_sample_count") != len(stratum):
            raise ProjectExportVerificationError("sampled sample count cannot be reproduced")
        if _integer(snapshot["eligible_sample_count"], "eligible_sample_count") != denominator:
            raise ProjectExportVerificationError("eligible sample count cannot be reproduced")
        for field, expected in (
            ("recommendation_share", recommendation),
            ("product_mention_share", mention),
            ("placement_citation_share", verified_citation_rate),
        ):
            if _decimal(snapshot[field], field) != expected:
                raise ProjectExportVerificationError(f"{field} cannot be reproduced")
        expected_invalid = len(stratum) - denominator
        if _integer(snapshot["invalid_sample_count"], "invalid_sample_count") != expected_invalid:
            raise ProjectExportVerificationError("invalid sample count cannot be reproduced")
        expected_count = _integer(snapshot["expected_sample_count"], "expected_sample_count")
        if _integer(snapshot["missing_sample_count"], "missing_sample_count") != (
            expected_count - len(stratum)
        ):
            raise ProjectExportVerificationError("missing sample count cannot be reproduced")
        _verify_query_rows(snapshot, stratum, selected, queries)
        result.append(metric)
    return tuple(result), tuple(unrecalculable)


def _verify_query_rows(
    snapshot: Mapping[str, object],
    stratum: list[dict[str, object]],
    selected: set[str],
    queries: list[dict[str, object]],
) -> None:
    query_results = object_list(snapshot["query_results_snapshot"], "query results")
    frozen_queries = {
        item["monitoring_query_id"]: item
        for item in queries
        if item["protocol_id"] == snapshot["protocol_id"]
        and item["query_cluster_key"] == snapshot["query_cluster_key"]
    }
    if {item["monitoring_query_id"] for item in query_results} != set(frozen_queries):
        raise ProjectExportVerificationError(
            "per-query results do not match the frozen query cluster"
        )
    for query_result in query_results:
        query_id = query_result["monitoring_query_id"]
        if query_result["query_text_snapshot"] != frozen_queries[query_id]["query_text"]:
            raise ProjectExportVerificationError("query text snapshot cannot be reproduced")
        sampled = [
            item for item in stratum if item["monitoring_query_id"] == query_id
        ]
        query_observations = [
            item
            for item in sampled
            if _boolean(item["eligible"], "observation eligible")
            and item["result_status"] == "succeeded"
        ]
        denominator = len(query_observations)
        if (
            _integer(query_result["sampled_sample_count"], "query sampled count")
            != len(sampled)
            or _integer(query_result["valid_sample_count"], "query valid count")
            != denominator
            or _integer(query_result["invalid_sample_count"], "query invalid count")
            != len(sampled) - denominator
        ):
            raise ProjectExportVerificationError("per-query sample counts cannot be reproduced")
        query_expected = _integer(
            query_result["expected_sample_count"], "query expected count"
        )
        if _integer(query_result["missing_sample_count"], "query missing count") != (
            query_expected - len(sampled)
        ):
            raise ProjectExportVerificationError("per-query missing count cannot be reproduced")
        for estimate_name, field in (
            ("recommendation", "recommendation_present"),
            ("product_mention", "primary_product_mentioned"),
            ("competitor", "competitor_mentioned"),
            ("placement_citation", ""),
        ):
            estimate = mapping(query_result[estimate_name], estimate_name)
            numerator = (
                sum(
                    item["url_verification_status"] == "passed"
                    and _has_valid_citation(
                        object_list(item["citations"], "observation citations"),
                        selected,
                    )
                    for item in query_observations
                )
                if estimate_name == "placement_citation"
                else sum(_boolean(item[field], field) for item in query_observations)
            )
            if (
                _integer(estimate["numerator"], f"{estimate_name} numerator") != numerator
                or _integer(estimate["denominator"], f"{estimate_name} denominator")
                != denominator
                or _decimal(estimate["share"], f"{estimate_name} share")
                != _ratio(numerator, denominator)
            ):
                raise ProjectExportVerificationError(
                    f"per-query {estimate_name} estimate cannot be reproduced"
                )


def _has_valid_citation(
    citations: list[dict[str, object]], selected: set[str]
) -> bool:
    return any(
        _boolean(citation["verified_placement"], "verified placement")
        and citation["verification_status"] == "passed"
        and citation["submission_id"] is not None
        and citation["destination_id"] in selected
        for citation in citations
    )


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0.000000")
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ProjectExportVerificationError(f"{label} must be a boolean")
    return value


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProjectExportVerificationError(f"{label} must be an integer")
    return value


def _decimal(value: object, label: str) -> Decimal:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ProjectExportVerificationError(f"{label} must be a JSON number")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ProjectExportVerificationError(f"{label} must be finite")
    return result.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _text_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ProjectExportVerificationError(f"{label} must be an array")
    return [text(item, label) for item in value]
