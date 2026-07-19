"""F027-UNIT-01 and F027-RECALC-01 project export acceptance tests."""

from __future__ import annotations

import csv
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import io
import json
from uuid import UUID

import pytest

from geo_core.project_exports import (
    AdminProjectExportInput,
    ApprovedReportExportRecord,
    CitationExportRecord,
    CustomerApprovedProjectExportInput,
    InvalidReasonCountExportRecord,
    LEGACY_STATISTICS_CONTRACT_VERSION,
    LegacyMetricSnapshotExportRecord,
    METRIC_METHOD_VERSION,
    MetricEstimateExportRecord,
    MetricObservationMembershipExportRecord,
    MetricSnapshotExportRecord,
    OBSERVATION_MEMBERSHIP_VERSION,
    ObservationExportRecord,
    ProjectExportData,
    ProjectExportRuleViolation,
    ProjectExportScope,
    ProjectExportVerificationError,
    ProtocolExportRecord,
    ProtocolSourceStratumExportRecord,
    QueryExportRecord,
    QueryMetricResultExportRecord,
    VerifiedUrlExportRecord,
    build_project_export,
    metric_result_hash,
    observation_membership_hash,
    recalculate_project_export,
    wilson_interval,
)
from geo_core.project_exports.bundle import CSV_SCHEMAS, canonical_json_bytes


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000001")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000002")
PROTOCOL_ID = UUID("00000000-0000-0000-0000-000000000003")
QUERY_ROW_ID = UUID("00000000-0000-0000-0000-000000000004")
QUERY_ID = UUID("00000000-0000-0000-0000-000000000005")
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000006")
REPORT_ID = UUID("00000000-0000-0000-0000-000000000007")
DESTINATION_ID = UUID("00000000-0000-0000-0000-000000000008")
OTHER_DESTINATION_ID = UUID("00000000-0000-0000-0000-000000000009")
SUBMISSION_ID = UUID("00000000-0000-0000-0000-000000000010")
OBSERVATION_IDS = tuple(UUID(f"00000000-0000-0000-0000-{value:012d}") for value in range(11, 14))
NOW = datetime(2026, 7, 19, 8, 30, tzinfo=UTC)
GENERATED_AT = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)


def test_f027_unit_01_is_deterministic_and_preserves_json_and_csv_types() -> None:
    data = _data()
    current_snapshot = _current_snapshot(data)
    first = build_project_export(
        AdminProjectExportInput(ProjectExportScope(PROJECT_ID, CAMPAIGN_ID), data),
        generated_at=GENERATED_AT,
    )
    shuffled = replace(
        data,
        observations=tuple(reversed(data.observations)),
        citations=tuple(reversed(data.citations)),
        metric_snapshots=(
            replace(
                current_snapshot,
                selected_destination_ids=tuple(reversed(current_snapshot.selected_destination_ids)),
                confounded_reasons=tuple(reversed(current_snapshot.confounded_reasons)),
            ),
        ),
    )
    second = build_project_export(
        AdminProjectExportInput(ProjectExportScope(PROJECT_ID, CAMPAIGN_ID), shuffled),
        generated_at=GENERATED_AT,
    )

    assert first.as_mapping() == second.as_mapping()
    value = json.loads(first.file("project-export.json"))
    assert isinstance(value["observations"][0]["eligible"], bool)
    assert isinstance(value["observations"][0]["sample_index"], int)
    assert isinstance(value["metric_snapshots"][0]["recommendation_share"], float)
    assert isinstance(value["observations"][0]["citations"], list)
    assert isinstance(value["protocols"][0]["source_strata"], list)
    assert value["metric_snapshots"][0]["selected_destination_ids"] == sorted(
        [str(DESTINATION_ID), str(OTHER_DESTINATION_ID)]
    )
    assert value["metric_snapshots"][0]["query_cluster_key"] == "mower-recommendation"
    assert (
        value["metric_snapshots"][0]["query_results_snapshot"][0]["recommendation"]["denominator"]
        == 2
    )
    rows = _csv(first.file("observations.csv"))
    assert rows[0]["answer_text"] == 'A "quoted", multi-line\nanswer'
    assert rows[0]["eligible"] == "true"
    assert list(rows[0]) == [name for name, _ in CSV_SCHEMAS["observations.csv"]]
    snapshot_header = _csv(first.file("metric_snapshots.csv"))[0]
    assert "selected_destination_ids" not in snapshot_header
    destination_rows = _csv(first.file("metric_destinations.csv"))
    assert len(destination_rows) == 4
    assert {row["destination_set"] for row in destination_rows} == {
        "selected",
        "qualified",
        "verified",
    }
    assert _csv(first.file("metric_query_results.csv"))[0]["recommendation_share"] == "0.500000"


def test_f027_unit_01_manifest_counts_hashes_columns_and_canonical_hash() -> None:
    bundle = _bundle()
    manifest = json.loads(bundle.file("manifest.json"))
    manifest_hash = manifest.pop("manifest_hash")
    assert manifest_hash == hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    assert manifest["metric_method_version"] == METRIC_METHOD_VERSION
    assert [item["path"] for item in manifest["files"]] == sorted(
        ["project-export.json", *CSV_SCHEMAS]
    )
    for descriptor in manifest["files"]:
        content = bundle.file(descriptor["path"])
        assert descriptor["byte_count"] == len(content)
        assert descriptor["sha256"] == hashlib.sha256(content).hexdigest()
        if descriptor["path"].endswith(".csv"):
            assert descriptor["row_count"] == len(_csv(content))
            assert descriptor["columns"] == [
                {"name": name, "type": value_type}
                for name, value_type in CSV_SCHEMAS[descriptor["path"]]
            ]


def test_f027_unit_01_strict_adapter_mapping_rejects_internal_fields() -> None:
    protocol = asdict(_data().protocols[0])
    protocol["database_password"] = "must-not-leak"
    with pytest.raises(ProjectExportRuleViolation, match="non-whitelisted.*database_password"):
        ProjectExportData.from_mappings(protocols=(protocol,))

    wrong_type = asdict(_data().protocols[0])
    wrong_type["project_id"] = str(PROJECT_ID)
    with pytest.raises(ProjectExportRuleViolation, match="project_id must be a UUID"):
        ProjectExportData.from_mappings(protocols=(wrong_type,))


def test_f027_unit_01_project_scope_without_campaign_is_explicit() -> None:
    bundle = build_project_export(
        AdminProjectExportInput(ProjectExportScope(PROJECT_ID), _data()),
        generated_at=GENERATED_AT,
    )
    manifest = json.loads(bundle.file("manifest.json"))
    assert manifest["scope"] == {
        "project_id": str(PROJECT_ID),
        "campaign_id": None,
    }


@pytest.mark.parametrize("field", ["project_id", "campaign_id"])
def test_f027_unit_01_rejects_cross_scope_records(field: str) -> None:
    data = _data()
    replacement = UUID("10000000-0000-0000-0000-000000000001")
    crossed = (
        replace(data.protocols[0], project_id=replacement)
        if field == "project_id"
        else replace(data.protocols[0], campaign_id=replacement)
    )
    with pytest.raises(ProjectExportRuleViolation, match="crosses the requested|lineage"):
        AdminProjectExportInput(
            ProjectExportScope(PROJECT_ID, CAMPAIGN_ID),
            replace(data, protocols=(crossed,)),
        )


def test_f027_unit_01_rejects_ambiguous_ordering_and_nan() -> None:
    data = _data()
    current_snapshot = _current_snapshot(data)
    with pytest.raises(ProjectExportRuleViolation, match="deterministic export ordering"):
        AdminProjectExportInput(
            ProjectExportScope(PROJECT_ID, CAMPAIGN_ID),
            replace(data, observations=data.observations + (data.observations[0],)),
        )
    with pytest.raises(ProjectExportRuleViolation, match="finite Decimal"):
        replace(current_snapshot, recommendation_share=Decimal("NaN"))
    with pytest.raises(ProjectExportRuleViolation, match="timezone-aware"):
        build_project_export(
            AdminProjectExportInput(ProjectExportScope(PROJECT_ID), data),
            generated_at=datetime(2026, 7, 19),
        )


def test_f027_unit_01_customer_contract_is_approved_only() -> None:
    data = _data()
    CustomerApprovedProjectExportInput(ProjectExportScope(PROJECT_ID, CAMPAIGN_ID), data)
    with pytest.raises(ProjectExportRuleViolation, match="exactly match approved reports"):
        CustomerApprovedProjectExportInput(
            ProjectExportScope(PROJECT_ID, CAMPAIGN_ID),
            replace(data, approved_reports=()),
        )
    with pytest.raises(ProjectExportRuleViolation, match="must be frozen"):
        CustomerApprovedProjectExportInput(
            ProjectExportScope(PROJECT_ID, CAMPAIGN_ID),
            replace(data, protocols=(replace(data.protocols[0], status="draft"),)),
        )
    with pytest.raises(ProjectExportRuleViolation, match="latest approved snapshot destinations"):
        CustomerApprovedProjectExportInput(
            ProjectExportScope(PROJECT_ID, CAMPAIGN_ID),
            replace(
                data,
                verified_urls=(
                    replace(data.verified_urls[0], destination_id=OTHER_DESTINATION_ID),
                ),
            ),
        )
    duplicate_snapshot = replace(
        data.metric_snapshots[0],
        id=UUID("30000000-0000-0000-0000-000000000001"),
    )
    duplicate_report = replace(
        data.approved_reports[0],
        id=UUID("30000000-0000-0000-0000-000000000002"),
        metric_snapshot_id=duplicate_snapshot.id,
    )
    duplicate_memberships = tuple(
        replace(item, snapshot_id=duplicate_snapshot.id)
        for item in data.metric_observation_memberships
    )
    with pytest.raises(ProjectExportRuleViolation, match="one latest approved report"):
        CustomerApprovedProjectExportInput(
            ProjectExportScope(PROJECT_ID, CAMPAIGN_ID),
            replace(
                data,
                metric_snapshots=data.metric_snapshots + (duplicate_snapshot,),
                metric_observation_memberships=(
                    data.metric_observation_memberships + duplicate_memberships
                ),
                approved_reports=data.approved_reports + (duplicate_report,),
            ),
        )


def test_f027_unit_01_f021_statistics_contract_handles_multi_reason_invalids() -> None:
    data = _data()
    current_snapshot = _current_snapshot(data)
    second_reason = InvalidReasonCountExportRecord("source_contract_invalid", 1)
    query_result = replace(
        current_snapshot.query_results_snapshot[0],
        invalid_reason_counts=(
            current_snapshot.invalid_reason_counts[0],
            second_reason,
        ),
    )
    snapshot = replace(
        current_snapshot,
        invalid_reason_counts=(
            current_snapshot.invalid_reason_counts[0],
            second_reason,
        ),
        query_results_snapshot=(query_result,),
    )
    snapshot = replace(snapshot, result_hash=metric_result_hash(snapshot, _stratum_value()))
    AdminProjectExportInput(
        ProjectExportScope(PROJECT_ID, CAMPAIGN_ID),
        replace(data, metric_snapshots=(snapshot,)),
    )
    zero = MetricEstimateExportRecord(
        numerator=0,
        denominator=0,
        share=Decimal("0.000000"),
        ci_low=Decimal("0.000000"),
        ci_high=Decimal("1.000000"),
    )
    assert zero.ci_high == Decimal("1.000000")
    with pytest.raises(ProjectExportRuleViolation, match="analysis_stratum_hash"):
        replace(current_snapshot, analysis_stratum_hash="a" * 64)
    with pytest.raises(ProjectExportRuleViolation, match="result_hash"):
        AdminProjectExportInput(
            ProjectExportScope(PROJECT_ID, CAMPAIGN_ID),
            replace(
                data,
                metric_snapshots=(replace(current_snapshot, result_hash="a" * 64),),
            ),
        )


def test_f027_recalc_01_recomputes_snapshot_from_export_bytes() -> None:
    current_snapshot = _current_snapshot(_data())
    result = recalculate_project_export(_bundle().as_mapping())
    assert result.manifest_hash == _bundle().manifest.canonical_hash
    assert result.metrics == (
        result.metrics[0].__class__(
            metric_snapshot_id=str(SNAPSHOT_ID),
            analysis_stratum_hash=_analysis_hash(current_snapshot.source_stratum_hash),
            query_cluster_key="mower-recommendation",
            eligible_sample_count=2,
            recommendation_share=Decimal("0.500000"),
            mention_share=Decimal("1.000000"),
            verified_citation_rate=Decimal("0.500000"),
            method_version=METRIC_METHOD_VERSION,
        ),
    )


def test_f027_recalc_01_does_not_mix_query_clusters_in_same_source_stratum() -> None:
    data = _data()
    other_query_id = UUID("20000000-0000-0000-0000-000000000001")
    other_query_row = replace(
        data.queries[0],
        id=UUID("20000000-0000-0000-0000-000000000002"),
        monitoring_query_id=other_query_id,
        ordinal=1,
        query_text="A different cluster",
        query_cluster_key="different-cluster",
    )
    other_observation = replace(
        data.observations[0],
        id=UUID("20000000-0000-0000-0000-000000000003"),
        monitoring_query_id=other_query_id,
        query_cluster_key="different-cluster",
        recommendation_present=False,
        primary_product_mentioned=False,
        payload_hash="9" * 64,
    )
    source = AdminProjectExportInput(
        ProjectExportScope(PROJECT_ID, CAMPAIGN_ID),
        replace(
            data,
            queries=data.queries + (other_query_row,),
            observations=data.observations + (other_observation,),
        ),
    )
    result = recalculate_project_export(
        build_project_export(source, generated_at=GENERATED_AT).as_mapping()
    )
    assert result.metrics[0].eligible_sample_count == 2
    assert result.metrics[0].recommendation_share == Decimal("0.500000")


def test_f027_recalc_01_preserves_legacy_nulls_without_fabricating_v2() -> None:
    data = _data()
    legacy_protocol = replace(
        data.protocols[0],
        minimum_valid_repeats=None,
        statistics_method_version=None,
        statistics_contract_version=LEGACY_STATISTICS_CONTRACT_VERSION,
    )
    legacy_snapshot = _legacy_snapshot(_current_snapshot(data))
    mapped = ProjectExportData.from_mappings(metric_snapshots=(asdict(legacy_snapshot),))
    assert isinstance(mapped.metric_snapshots[0], LegacyMetricSnapshotExportRecord)
    legacy_data = replace(
        data,
        protocols=(legacy_protocol,),
        metric_snapshots=(legacy_snapshot,),
        metric_observation_memberships=(),
        approved_reports=(),
    )
    source = AdminProjectExportInput(ProjectExportScope(PROJECT_ID, CAMPAIGN_ID), legacy_data)
    bundle = build_project_export(source, generated_at=GENERATED_AT)
    exported = json.loads(bundle.file("project-export.json"))["metric_snapshots"][0]
    assert exported["query_cluster_key"] is None
    assert exported["minimum_valid_repeats"] is None
    assert exported["query_results_snapshot"] is None
    result = recalculate_project_export(bundle.as_mapping())
    assert result.metrics == ()
    assert result.unrecalculable[0].reason.startswith("legacy_statistics_contract")
    with pytest.raises(ProjectExportRuleViolation, match="cannot include legacy"):
        CustomerApprovedProjectExportInput(ProjectExportScope(PROJECT_ID, CAMPAIGN_ID), legacy_data)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["metric_snapshots"][0].__setitem__("recommendation_share", 0.75),
            "recommendation_share",
        ),
        (
            lambda value: value["metric_snapshots"][0].__setitem__("method_version", "old-v1"),
            "method version",
        ),
        (
            lambda value: value["observations"][0].__setitem__("worker_secret", "leak"),
            "public field whitelist",
        ),
    ],
)
def test_f027_recalc_01_rejects_rehashed_semantic_tampering(mutation: object, message: str) -> None:
    files = _bundle().as_mapping()
    data = json.loads(files["project-export.json"])
    mutation(data)  # type: ignore[operator]
    _replace_and_rehash(files, "project-export.json", canonical_json_bytes(data))
    with pytest.raises(ProjectExportVerificationError, match=message):
        recalculate_project_export(files)


def test_f027_recalc_01_rejects_hash_mismatch_extra_files_and_non_finite_json() -> None:
    files = _bundle().as_mapping()
    files["observations.csv"] += b"tampered"
    with pytest.raises(ProjectExportVerificationError, match="byte count|SHA-256"):
        recalculate_project_export(files)

    files = _bundle().as_mapping()
    files["unmanifested.txt"] = b"no"
    with pytest.raises(ProjectExportVerificationError, match="unmanifested"):
        recalculate_project_export(files)

    files = _bundle().as_mapping()
    data = files["project-export.json"].replace(
        b'"recommendation_share":0.5', b'"recommendation_share":NaN'
    )
    _replace_and_rehash(files, "project-export.json", data)
    with pytest.raises(ProjectExportVerificationError, match="non-finite"):
        recalculate_project_export(files)


def _bundle():
    return build_project_export(
        AdminProjectExportInput(
            ProjectExportScope(PROJECT_ID, CAMPAIGN_ID),
            _data(),
        ),
        generated_at=GENERATED_AT,
    )


def _stratum_value() -> dict[str, object]:
    return {
        "capture_method": "manual_ui",
        "platform": "chatgpt",
        "surface": "chatgpt_web",
        "surface_kind": "consumer_ui",
        "engine": "chatgpt-search",
        "configured_model": {"state": "not_disclosed", "value": None},
        "reported_model": {"state": "not_disclosed", "value": None},
        "locale": "en-US",
        "region": "US",
        "language": "en",
        "device": "desktop",
        "client_kind": "browser",
        "search_enabled": True,
        "search_mode": "grounded",
        "platform_detail": None,
        "surface_detail": None,
    }


def _data() -> ProjectExportData:
    stratum_value = _stratum_value()
    stratum_hash = _canonical_hash(stratum_value)
    inventory_hash = _canonical_hash([stratum_value])
    protocol = ProtocolExportRecord(
        id=PROTOCOL_ID,
        project_id=PROJECT_ID,
        campaign_id=CAMPAIGN_ID,
        name="Summer audit protocol",
        platform="chatgpt",
        locale="en-US",
        device="desktop",
        sample_size=3,
        window_days=28,
        status="frozen",
        protocol_hash="1" * 64,
        source_strata_hash=inventory_hash,
        minimum_valid_repeats=3,
        statistics_method_version=METRIC_METHOD_VERSION,
        statistics_contract_version=METRIC_METHOD_VERSION,
        approved_at=NOW,
        frozen_at=NOW,
    )
    source_stratum = ProtocolSourceStratumExportRecord(
        project_id=PROJECT_ID,
        campaign_id=CAMPAIGN_ID,
        protocol_id=PROTOCOL_ID,
        source_stratum_hash=stratum_hash,
        source_contract_version="geo-observation-source-v3",
        capture_method="manual_ui",
        platform="chatgpt",
        platform_detail=None,
        surface="chatgpt_web",
        surface_detail=None,
        surface_kind="consumer_ui",
        engine="chatgpt-search",
        configured_model_state="not_disclosed",
        configured_model=None,
        reported_model_state="not_disclosed",
        reported_model=None,
        locale="en-US",
        region="US",
        language="en",
        device="desktop",
        client_kind="browser",
        search_enabled=True,
        search_mode="grounded",
    )
    query = QueryExportRecord(
        id=QUERY_ROW_ID,
        project_id=PROJECT_ID,
        campaign_id=CAMPAIGN_ID,
        protocol_id=PROTOCOL_ID,
        monitoring_query_id=QUERY_ID,
        query_text="Which mower is recommended?",
        query_kind="recommendation",
        locale="en-US",
        ordinal=0,
        query_cluster_key="mower-recommendation",
    )
    observations = tuple(
        ObservationExportRecord(
            id=observation_id,
            project_id=PROJECT_ID,
            campaign_id=CAMPAIGN_ID,
            protocol_id=PROTOCOL_ID,
            monitoring_query_id=QUERY_ID,
            query_cluster_key="mower-recommendation",
            measurement_window="t28",
            source_stratum_hash=stratum_hash,
            sample_index=index,
            result_status="failed" if index == 3 else "succeeded",
            eligible=True,
            url_verification_status="passed",
            recommendation_present=index == 1,
            primary_product_mentioned=index < 3,
            competitor_mentioned=False,
            ineligible_reasons=(),
            confounding_factors=(),
            capture_method="manual_ui",
            platform="chatgpt",
            surface="chatgpt_web",
            engine="chatgpt-search",
            answer_text='A "quoted", multi-line\nanswer' if index == 1 else "Plain answer",
            payload_hash=str(index) * 64,
            observed_at=NOW,
        )
        for index, observation_id in enumerate(OBSERVATION_IDS, start=1)
    )
    memberships = tuple(
        MetricObservationMembershipExportRecord(
            snapshot_id=SNAPSHOT_ID,
            project_id=PROJECT_ID,
            campaign_id=CAMPAIGN_ID,
            protocol_id=PROTOCOL_ID,
            observation_id=observation.id,
            ordinal=ordinal,
            payload_hash=observation.payload_hash,
        )
        for ordinal, observation in enumerate(observations, start=1)
    )
    citations = (
        CitationExportRecord(
            observation_id=OBSERVATION_IDS[0],
            citation_index=0,
            project_id=PROJECT_ID,
            campaign_id=CAMPAIGN_ID,
            protocol_id=PROTOCOL_ID,
            url="https://example.test/verified",
            title='Quoted, "title"',
            verification_status="passed",
            verified_placement=True,
            destination_id=DESTINATION_ID,
            submission_id=SUBMISSION_ID,
            verified_at=NOW,
        ),
        CitationExportRecord(
            observation_id=OBSERVATION_IDS[1],
            citation_index=0,
            project_id=PROJECT_ID,
            campaign_id=CAMPAIGN_ID,
            protocol_id=PROTOCOL_ID,
            url="https://example.test/unselected",
            title=None,
            verification_status="passed",
            verified_placement=True,
            destination_id=UUID("00000000-0000-0000-0000-000000000099"),
            submission_id=SUBMISSION_ID,
            verified_at=NOW,
        ),
    )
    invalid_reason = InvalidReasonCountExportRecord("result_failed", 1)
    recommendation = _estimate(1, 2)
    product_mention = _estimate(2, 2)
    placement_citation = _estimate(1, 2)
    competitor = _estimate(0, 2)
    query_result = QueryMetricResultExportRecord(
        monitoring_query_id=QUERY_ID,
        query_text_snapshot=query.query_text,
        query_cluster_key="mower-recommendation",
        expected_sample_count=3,
        sampled_sample_count=3,
        valid_sample_count=2,
        invalid_sample_count=1,
        missing_sample_count=0,
        meets_threshold=False,
        invalid_reason_counts=(invalid_reason,),
        confounding_factors=(),
        recommendation=recommendation,
        product_mention=product_mention,
        placement_citation=placement_citation,
        competitor=competitor,
        competitive_delta=Decimal("1.000000"),
    )
    snapshot = MetricSnapshotExportRecord(
        id=SNAPSHOT_ID,
        project_id=PROJECT_ID,
        campaign_id=CAMPAIGN_ID,
        protocol_id=PROTOCOL_ID,
        measurement_window="t28",
        source_stratum_hash=stratum_hash,
        statistics_contract_version=METRIC_METHOD_VERSION,
        query_cluster_key="mower-recommendation",
        analysis_stratum_hash=_analysis_hash(stratum_hash),
        observation_membership_version=OBSERVATION_MEMBERSHIP_VERSION,
        observation_membership_count=len(memberships),
        observation_membership_hash=observation_membership_hash(memberships),
        minimum_valid_repeats=3,
        expected_sample_count=3,
        sampled_sample_count=3,
        eligible_sample_count=2,
        invalid_sample_count=1,
        missing_sample_count=0,
        sampling_completion_ratio=Decimal("1.000000"),
        valid_completion_ratio=Decimal("0.666667"),
        query_count=1,
        sufficient_query_count=0,
        recommendation_share=Decimal("0.500000"),
        product_mention_share=Decimal("1.000000"),
        placement_citation_share=Decimal("0.500000"),
        qualified_destination_coverage=Decimal("0.500000"),
        verified_placement_coverage=Decimal("1.000000"),
        competitive_delta=Decimal("1.000000"),
        recommendation_ci_low=recommendation.ci_low,
        recommendation_ci_high=recommendation.ci_high,
        product_mention_ci_low=product_mention.ci_low,
        product_mention_ci_high=product_mention.ci_high,
        placement_citation_ci_low=placement_citation.ci_low,
        placement_citation_ci_high=placement_citation.ci_high,
        recommendation_query_min=Decimal("0.500000"),
        recommendation_query_max=Decimal("0.500000"),
        product_mention_query_min=Decimal("1.000000"),
        product_mention_query_max=Decimal("1.000000"),
        placement_citation_query_min=Decimal("0.500000"),
        placement_citation_query_max=Decimal("0.500000"),
        worst_query_id=QUERY_ID,
        invalid_reason_counts=(invalid_reason,),
        declared_confounding_factors=(),
        query_results_snapshot=(query_result,),
        selected_destination_ids=(OTHER_DESTINATION_ID, DESTINATION_ID),
        qualified_destination_ids=(DESTINATION_ID,),
        verified_destination_ids=(DESTINATION_ID,),
        status="insufficient_evidence",
        confounded_reasons=("failed_samples",),
        input_hash="4" * 64,
        result_hash="6" * 64,
        method_version=METRIC_METHOD_VERSION,
        computed_at=NOW,
    )
    snapshot = replace(snapshot, result_hash=metric_result_hash(snapshot, stratum_value))
    report = ApprovedReportExportRecord(
        id=REPORT_ID,
        project_id=PROJECT_ID,
        campaign_id=CAMPAIGN_ID,
        protocol_id=PROTOCOL_ID,
        metric_snapshot_id=SNAPSHOT_ID,
        title="Approved summer report",
        body="Approved, read-only result.",
        methodology_statement="Observational, non-causal.",
        report_hash="5" * 64,
        generated_at=NOW,
        approved_at=NOW,
    )
    verified_url = VerifiedUrlExportRecord(
        project_id=PROJECT_ID,
        campaign_id=CAMPAIGN_ID,
        protocol_ids=(PROTOCOL_ID,),
        url="https://example.test/verified",
        title="Verified page",
        destination_id=DESTINATION_ID,
        first_verified_at=NOW,
        observation_count=1,
    )
    return ProjectExportData(
        protocols=(protocol,),
        protocol_source_strata=(source_stratum,),
        queries=(query,),
        observations=observations,
        citations=citations,
        metric_snapshots=(snapshot,),
        metric_observation_memberships=memberships,
        approved_reports=(report,),
        verified_urls=(verified_url,),
    )


def _csv(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8"), newline="")))


def _legacy_snapshot(
    snapshot: MetricSnapshotExportRecord,
) -> LegacyMetricSnapshotExportRecord:
    payload = asdict(snapshot)
    payload["statistics_contract_version"] = LEGACY_STATISTICS_CONTRACT_VERSION
    payload["method_version"] = "geo-observational-source-separated-v1"
    for name in (
        "query_cluster_key",
        "analysis_stratum_hash",
        "observation_membership_version",
        "observation_membership_count",
        "observation_membership_hash",
        "minimum_valid_repeats",
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
    ):
        payload[name] = None
    return LegacyMetricSnapshotExportRecord(**payload)


def _current_snapshot(data: ProjectExportData) -> MetricSnapshotExportRecord:
    snapshot = data.metric_snapshots[0]
    assert isinstance(snapshot, MetricSnapshotExportRecord)
    return snapshot


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _analysis_hash(source_stratum_hash: str) -> str:
    return _canonical_hash(
        {
            "query_cluster_key": "mower-recommendation",
            "source_stratum_hash": source_stratum_hash,
        }
    )


def _estimate(numerator: int, denominator: int) -> MetricEstimateExportRecord:
    low, high = wilson_interval(numerator, denominator)
    share = (
        Decimal("0.000000")
        if denominator == 0
        else (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.000001"))
    )
    return MetricEstimateExportRecord(
        numerator=numerator,
        denominator=denominator,
        share=share,
        ci_low=low,
        ci_high=high,
    )


def _replace_and_rehash(files: dict[str, bytes], path: str, content: bytes) -> None:
    files[path] = content
    manifest = json.loads(files["manifest.json"])
    for descriptor in manifest["files"]:
        if descriptor["path"] == path:
            descriptor["byte_count"] = len(content)
            descriptor["sha256"] = hashlib.sha256(content).hexdigest()
    manifest.pop("manifest_hash")
    manifest["manifest_hash"] = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    files["manifest.json"] = canonical_json_bytes(manifest)
