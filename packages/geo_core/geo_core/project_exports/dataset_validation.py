"""Cross-record scope, lineage, approval, and ordering validation."""

from __future__ import annotations

from collections.abc import Callable, Hashable
import hashlib
import json
from typing import Iterable, Mapping, TypeVar
from uuid import UUID

from geo_core.monitoring.source_contract import SOURCE_CONTRACT_VERSION
from geo_core.project_exports.constants import (
    LEGACY_STATISTICS_CONTRACT_VERSION,
    METRIC_METHOD_VERSION,
)
from geo_core.project_exports.contracts import (
    AnyMetricSnapshotExportRecord,
    LegacyMetricSnapshotExportRecord,
    MetricSnapshotExportRecord,
    ProjectExportData,
    ProjectExportScope,
    ProtocolExportRecord,
    ProtocolSourceStratumExportRecord,
)
from geo_core.project_exports.errors import ProjectExportRuleViolation
from geo_core.project_exports.membership_contracts import (
    MetricObservationMembershipExportRecord,
    observation_membership_hash,
    validate_membership_order,
)
from geo_core.project_exports.result_hash import metric_result_hash


_Record = TypeVar("_Record")
_Key = TypeVar("_Key", bound=Hashable)


def validate_dataset(scope: ProjectExportScope, data: ProjectExportData, *, customer: bool) -> None:
    collections: tuple[tuple[str, tuple[object, ...]], ...] = (
        ("protocol", data.protocols),
        ("protocol source stratum", data.protocol_source_strata),
        ("query", data.queries),
        ("observation", data.observations),
        ("citation", data.citations),
        ("metric snapshot", data.metric_snapshots),
        ("metric observation membership", data.metric_observation_memberships),
        ("approved report", data.approved_reports),
        ("verified URL", data.verified_urls),
    )
    for label, records in collections:
        for record in records:
            if getattr(record, "project_id") != scope.project_id:
                raise ProjectExportRuleViolation(f"{label} crosses the requested project scope")
            if (
                scope.campaign_id is not None
                and getattr(record, "campaign_id") != scope.campaign_id
            ):
                raise ProjectExportRuleViolation(f"{label} crosses the requested campaign scope")

    protocols = _unique_by("protocol id", data.protocols, lambda item: item.id)
    _unique_by("query id", data.queries, lambda item: item.id)
    queries = _unique_by(
        "protocol query", data.queries, lambda item: (item.protocol_id, item.monitoring_query_id)
    )
    source_strata = _unique_by(
        "protocol source stratum",
        data.protocol_source_strata,
        lambda item: (item.protocol_id, item.source_stratum_hash),
    )
    _unique_by("query ordinal", data.queries, lambda item: (item.protocol_id, item.ordinal))
    observations = _unique_by("observation id", data.observations, lambda item: item.id)
    _unique_by(
        "observation slot",
        data.observations,
        lambda item: (
            item.protocol_id,
            item.measurement_window,
            item.source_stratum_hash,
            item.query_cluster_key,
            item.monitoring_query_id,
            item.sample_index,
        ),
    )
    _unique_by(
        "citation slot", data.citations, lambda item: (item.observation_id, item.citation_index)
    )
    snapshots = _unique_by("metric snapshot id", data.metric_snapshots, lambda item: item.id)
    _unique_by(
        "metric membership observation",
        data.metric_observation_memberships,
        lambda item: (item.snapshot_id, item.observation_id),
    )
    _unique_by(
        "metric membership ordinal",
        data.metric_observation_memberships,
        lambda item: (item.snapshot_id, item.ordinal),
    )
    _unique_by("approved report id", data.approved_reports, lambda item: item.id)
    _unique_by("verified URL", data.verified_urls, lambda item: (item.campaign_id, item.url))

    for query in data.queries:
        protocol = _required_reference(protocols, query.protocol_id, "query protocol")
        _same_lineage(query, protocol, "query protocol")
    for stratum in data.protocol_source_strata:
        protocol = _required_reference(protocols, stratum.protocol_id, "source stratum protocol")
        _same_lineage(stratum, protocol, "source stratum protocol")
        if stratum.source_stratum_hash != _canonical_hash(_source_stratum_value(stratum)):
            raise ProjectExportRuleViolation(
                "protocol source stratum hash does not match its public fields"
            )
    strata_by_protocol: dict[UUID, list[dict[str, object]]] = {}
    for stratum in data.protocol_source_strata:
        strata_by_protocol.setdefault(stratum.protocol_id, []).append(
            _source_stratum_value(stratum)
        )
    for protocol in data.protocols:
        if protocol.source_strata_hash is None:
            if strata_by_protocol.get(protocol.id):
                raise ProjectExportRuleViolation(
                    "protocol with source strata requires source_strata_hash"
                )
            continue
        values = strata_by_protocol.get(protocol.id, [])
        inventory_hash = _canonical_hash(sorted(values, key=_canonical_hash))
        if inventory_hash != protocol.source_strata_hash:
            raise ProjectExportRuleViolation(
                "protocol source_strata_hash does not match exported inventory"
            )
    for observation in data.observations:
        protocol = _required_reference(protocols, observation.protocol_id, "observation protocol")
        _same_lineage(observation, protocol, "observation protocol")
        query = _required_reference(
            queries,
            (observation.protocol_id, observation.monitoring_query_id),
            "observation protocol query",
        )
        _same_lineage(observation, query, "observation protocol query")
        if observation.query_cluster_key != query.query_cluster_key:
            raise ProjectExportRuleViolation("observation query cluster differs from frozen query")
        if observation.source_stratum_hash is not None:
            _required_reference(
                source_strata,
                (observation.protocol_id, observation.source_stratum_hash),
                "observation source stratum",
            )
    for citation in data.citations:
        observation = _required_reference(
            observations, citation.observation_id, "citation observation"
        )
        _same_lineage(citation, observation, "citation observation")
    memberships_by_snapshot: dict[UUID, list[MetricObservationMembershipExportRecord]] = {}
    for membership in data.metric_observation_memberships:
        snapshot = _required_reference(
            snapshots, membership.snapshot_id, "membership metric snapshot"
        )
        observation = _required_reference(
            observations, membership.observation_id, "membership observation"
        )
        _same_lineage(membership, snapshot, "membership metric snapshot")
        _same_lineage(membership, observation, "membership observation")
        if (
            membership.protocol_id != snapshot.protocol_id
            or membership.protocol_id != observation.protocol_id
            or membership.payload_hash != observation.payload_hash
        ):
            raise ProjectExportRuleViolation(
                "metric membership crosses protocol or payload lineage"
            )
        memberships_by_snapshot.setdefault(membership.snapshot_id, []).append(membership)
    for snapshot in data.metric_snapshots:
        protocol = _required_reference(protocols, snapshot.protocol_id, "metric protocol")
        _same_lineage(snapshot, protocol, "metric protocol")
        source_stratum = (
            _required_reference(
                source_strata,
                (snapshot.protocol_id, snapshot.source_stratum_hash),
                "metric source stratum",
            )
            if snapshot.source_stratum_hash is not None
            else None
        )
        if isinstance(snapshot, LegacyMetricSnapshotExportRecord):
            if memberships_by_snapshot.get(snapshot.id):
                raise ProjectExportRuleViolation(
                    "legacy metric cannot claim observation membership"
                )
            if protocol.statistics_contract_version != LEGACY_STATISTICS_CONTRACT_VERSION:
                raise ProjectExportRuleViolation(
                    "legacy metric statistics contract differs from protocol"
                )
            continue
        memberships = memberships_by_snapshot.get(snapshot.id, [])
        if snapshot.observation_membership_version is None:
            if memberships:
                raise ProjectExportRuleViolation(
                    "historical metric without a membership header cannot claim members"
                )
            if source_stratum is None:
                raise ProjectExportRuleViolation("statistics-v2 metric requires source stratum")
            if snapshot.result_hash != metric_result_hash(
                snapshot, _source_stratum_value(source_stratum)
            ):
                raise ProjectExportRuleViolation(
                    "historical metric result_hash does not match its public result"
                )
            continue
        validate_membership_order(memberships)
        if (
            len(memberships) != snapshot.observation_membership_count
            or observation_membership_hash(memberships) != snapshot.observation_membership_hash
        ):
            raise ProjectExportRuleViolation(
                "metric observation membership header does not match exact rows"
            )
        member_observations = [
            observations[membership.observation_id] for membership in memberships
        ]
        if any(
            observation.measurement_window != snapshot.measurement_window
            or observation.source_stratum_hash != snapshot.source_stratum_hash
            or observation.query_cluster_key != snapshot.query_cluster_key
            for observation in member_observations
        ):
            raise ProjectExportRuleViolation(
                "metric observation membership crosses its analysis stratum"
            )
        if source_stratum is None:
            raise ProjectExportRuleViolation("statistics-v2 metric requires source stratum")
        if snapshot.result_hash != metric_result_hash(
            snapshot, _source_stratum_value(source_stratum)
        ):
            raise ProjectExportRuleViolation(
                "metric result_hash does not match its exported public result"
            )
        query_ids = {
            query.monitoring_query_id
            for query in data.queries
            if query.protocol_id == snapshot.protocol_id
            and query.query_cluster_key == snapshot.query_cluster_key
        }
        if {item.monitoring_query_id for item in snapshot.query_results_snapshot} != query_ids:
            raise ProjectExportRuleViolation(
                "metric query results must exactly match the frozen query cluster"
            )
        queries_by_id = {
            query.monitoring_query_id: query
            for query in data.queries
            if query.protocol_id == snapshot.protocol_id
            and query.query_cluster_key == snapshot.query_cluster_key
        }
        if any(
            item.query_text_snapshot != queries_by_id[item.monitoring_query_id].query_text
            or item.expected_sample_count != protocol.sample_size
            for item in snapshot.query_results_snapshot
        ):
            raise ProjectExportRuleViolation(
                "metric query result differs from frozen protocol query"
            )
        if (
            protocol.statistics_contract_version != snapshot.statistics_contract_version
            or protocol.statistics_method_version != snapshot.method_version
            or protocol.minimum_valid_repeats != snapshot.minimum_valid_repeats
        ):
            raise ProjectExportRuleViolation(
                "metric statistics contract differs from frozen protocol"
            )
        snapshot_observations = member_observations
        expected_confounding_reasons: set[str] = set()
        if any(item.result_status == "failed" for item in snapshot_observations):
            expected_confounding_reasons.add("failed_samples")
        if any(item.confounding_factors for item in snapshot_observations):
            expected_confounding_reasons.add("declared_confounding_factors")
        if not snapshot.selected_destination_ids:
            expected_confounding_reasons.add("no_selected_destinations")
        if not snapshot.qualified_destination_ids:
            expected_confounding_reasons.add("no_qualified_destinations")
        if set(snapshot.confounded_reasons) != expected_confounding_reasons:
            raise ProjectExportRuleViolation(
                "metric confounded reasons differ from exported observations"
            )
    for report in data.approved_reports:
        snapshot = _required_reference(
            snapshots, report.metric_snapshot_id, "approved report metric snapshot"
        )
        _same_lineage(report, snapshot, "approved report metric snapshot")
        if report.protocol_id != snapshot.protocol_id:
            raise ProjectExportRuleViolation("approved report crosses metric protocol lineage")
    for verified_url in data.verified_urls:
        for protocol_id in verified_url.protocol_ids:
            protocol = _required_reference(protocols, protocol_id, "verified URL protocol")
            _same_lineage(verified_url, protocol, "verified URL protocol")

    if customer:
        _validate_customer_approved_projection(data, snapshots, protocols)


def _validate_customer_approved_projection(
    data: ProjectExportData,
    snapshots: Mapping[UUID, AnyMetricSnapshotExportRecord],
    protocols: Mapping[UUID, ProtocolExportRecord],
) -> None:
    if any(isinstance(item, LegacyMetricSnapshotExportRecord) for item in snapshots.values()):
        raise ProjectExportRuleViolation("customer export cannot include legacy metric snapshots")
    current_snapshots = {
        key: item for key, item in snapshots.items() if isinstance(item, MetricSnapshotExportRecord)
    }
    approved_snapshot_ids = {item.metric_snapshot_id for item in data.approved_reports}
    if set(snapshots) != approved_snapshot_ids:
        raise ProjectExportRuleViolation(
            "customer export metric snapshots must exactly match approved reports"
        )
    approved_protocol_ids = {current_snapshots[item].protocol_id for item in approved_snapshot_ids}
    if set(protocols) != approved_protocol_ids:
        raise ProjectExportRuleViolation(
            "customer export protocols must exactly match approved report lineage"
        )
    if any(
        protocol.status != "frozen"
        or protocol.protocol_hash is None
        or protocol.frozen_at is None
        or protocol.statistics_contract_version != METRIC_METHOD_VERSION
        for protocol in protocols.values()
    ):
        raise ProjectExportRuleViolation("customer export protocols must be frozen")
    partitions = [
        (
            snapshot.campaign_id,
            snapshot.protocol_id,
            snapshot.measurement_window,
            snapshot.source_stratum_hash,
            snapshot.query_cluster_key,
        )
        for snapshot in current_snapshots.values()
    ]
    if len(partitions) != len(set(partitions)) or len(data.approved_reports) != len(snapshots):
        raise ProjectExportRuleViolation(
            "customer export must contain one latest approved report per analysis partition"
        )
    groups = {
        (
            snapshot.protocol_id,
            snapshot.measurement_window,
            snapshot.source_stratum_hash,
            snapshot.query_cluster_key,
        )
        for snapshot in current_snapshots.values()
    }
    if any(
        (
            item.protocol_id,
            item.measurement_window,
            item.source_stratum_hash,
            item.query_cluster_key,
        )
        not in groups
        for item in data.observations
    ):
        raise ProjectExportRuleViolation(
            "customer export observations must belong to an approved report snapshot"
        )
    customer_member_ids = {
        membership.observation_id
        for membership in data.metric_observation_memberships
        if membership.snapshot_id in current_snapshots
    }
    if {item.id for item in data.observations} != customer_member_ids:
        raise ProjectExportRuleViolation(
            "customer observations must exactly match approved snapshot membership"
        )
    verified_destination_ids = {
        destination_id
        for snapshot in current_snapshots.values()
        for destination_id in snapshot.verified_destination_ids
    }
    if any(
        item.destination_id is None or item.destination_id not in verified_destination_ids
        for item in data.verified_urls
    ):
        raise ProjectExportRuleViolation(
            "customer verified URLs must come from latest approved snapshot destinations"
        )


def _unique_by(
    label: str, records: Iterable[_Record], key: Callable[[_Record], _Key]
) -> dict[_Key, _Record]:
    result: dict[_Key, _Record] = {}
    for item in records:
        value = key(item)
        if value in result:
            raise ProjectExportRuleViolation(
                f"duplicate {label} prevents deterministic export ordering"
            )
        result[value] = item
    return result


def _required_reference(records: Mapping[_Key, _Record], key: _Key, label: str) -> _Record:
    try:
        return records[key]
    except KeyError as exc:
        raise ProjectExportRuleViolation(f"missing {label} lineage") from exc


def _same_lineage(left: object, right: object, label: str) -> None:
    if getattr(left, "project_id") != getattr(right, "project_id") or getattr(
        left, "campaign_id"
    ) != getattr(right, "campaign_id"):
        raise ProjectExportRuleViolation(f"{label} crosses project or campaign lineage")


def _source_stratum_value(item: ProtocolSourceStratumExportRecord) -> dict[str, object]:
    value: dict[str, object] = {
        "capture_method": item.capture_method,
        "platform": item.platform,
        "surface": item.surface,
        "surface_kind": item.surface_kind,
        "engine": item.engine,
        "configured_model": {
            "state": item.configured_model_state,
            "value": item.configured_model,
        },
        "reported_model": {
            "state": item.reported_model_state,
            "value": item.reported_model,
        },
        "locale": item.locale,
        "region": item.region,
        "language": item.language,
        "device": item.device,
        "client_kind": item.client_kind,
        "search_enabled": item.search_enabled,
        "search_mode": item.search_mode,
    }
    if item.source_contract_version == SOURCE_CONTRACT_VERSION:
        value["platform_detail"] = item.platform_detail
        value["surface_detail"] = item.surface_detail
    return value


def _canonical_hash(value: object) -> str:
    serialized = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
