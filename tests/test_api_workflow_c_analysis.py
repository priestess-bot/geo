from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import pytest
from uuid import UUID

from fastapi.testclient import TestClient

from geo_api.workflow_c_analysis_contracts import (
    AnalyzeComparisonFamilyRequest,
    ComputeDriftRequest,
    ComputeSemanticMetricsRequest,
)
from geo_api.workflow_c_analysis_runtime import WorkflowCAnalysisUnavailable
from geo_api.workflow_c_presenters import semantic_snapshot_response
from geo_core.semantic_metrics import (
    DeterministicRuleVersions,
    FrozenMetricSuite,
    JudgeVersion,
    MetricInputSet,
    MetricObservation,
    PlannedMetricSlot,
    SemanticStratum,
    SubjectInventory,
    compute_semantic_metric_snapshot,
    first_metric_suite,
)
from geo_core.workflow_c_analysis_reads import StoredSemanticMetricSnapshot
from geo_core.statistical_methods import (
    ComparisonInput,
    DriftObservation,
    FrozenComparisonProtocol,
    PairedObservation,
    StatisticalStratum,
)

from tests.workflow_c_api_test_support import PROJECT_ID, digest, internal_app


RUN_ID = UUID("71000000-0000-4000-8000-000000000001")
METRIC_PROTOCOL_ID = UUID("71000000-0000-4000-8000-000000000002")
FACT_SNAPSHOT_ID = UUID("71000000-0000-4000-8000-000000000003")
PROMPT_RELEASE_ID = UUID("71000000-0000-4000-8000-000000000004")
CORPUS_VERSION_ID = UUID("71000000-0000-4000-8000-000000000005")
COMPARISON_PLAN_ID = UUID("71000000-0000-4000-8000-000000000006")
DRIFT_PROTOCOL_ID = UUID("71000000-0000-4000-8000-000000000007")


def test_semantic_compute_accepts_only_server_resolved_immutable_selectors() -> None:
    app, api, _, _ = internal_app()
    selector, input_set, metric_suite = _semantic_fixture()
    api.analysis.install_semantic_inputs(
        project_id=PROJECT_ID,
        selector=selector,
        input_set=input_set,
        metric_suite=metric_suite,
    )
    path = f"/v1/projects/{PROJECT_ID}/analysis/semantic-metrics/compute"

    with TestClient(app) as client:
        response = client.post(path, json=_json(selector))
        inventory = client.get(f"/v1/projects/{PROJECT_ID}/analysis/semantic-metrics")
        forged = client.post(
            path,
            json={
                **_json(selector),
                "observations": [{"answer_text": "fabricated"}],
                "planned_slots": [{"slot_id": "forged"}],
                "minimum_valid_completion": "0.01",
            },
        )

    assert response.status_code == 200, response.text
    assert inventory.status_code == 200, inventory.text
    assert inventory.json()["total"] == 1
    assert inventory.json()["items"][0]["snapshot_hash"] == response.json()["snapshot_hash"]
    body = response.json()
    assert forged.status_code == 422
    assert len(body["results"]) == 18
    assert len(body["snapshot_hash"]) == 64
    assert body["input_set_hash"] == input_set.input_set_hash
    assert {item["denominator"] for item in body["results"]} <= {0, 1}
    for item in body["results"]:
        assert (
            item["valid_input_count"] + item["invalid_input_count"] + item["missing_input_count"]
            == item["denominator"]
        )
        assert item["status"] == "insufficient_evidence"

    request_schema = app.openapi()["components"]["schemas"]["ComputeSemanticMetricsRequest"][
        "properties"
    ]
    forbidden = {
        "observations",
        "observation_artifacts",
        "planned_slots",
        "approved_facts",
        "verified_urls",
        "subjects",
        "judge_version",
        "rule_versions",
        "computed_at",
    }
    assert not forbidden.intersection(request_schema)


def test_semantic_answer_stays_in_server_artifact_resolution() -> None:
    app, api, _, _ = internal_app()
    answer = "Advinsys is recommended for the Australian accounting workflow."
    observation = MetricObservation(
        id=UUID("72000000-0000-4000-8000-000000000001"),
        slot_id="slot-1",
        payload_hash=digest("metric-observation-content"),
        question_id="q-1",
        question_cluster="purchase",
        answer_text=answer,
    )
    selector, input_set, metric_suite = _semantic_fixture(observation=observation)
    api.analysis.install_semantic_inputs(
        project_id=PROJECT_ID,
        selector=selector,
        input_set=input_set,
        metric_suite=metric_suite,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{PROJECT_ID}/analysis/semantic-metrics/compute",
            json=_json(selector),
        )

    assert response.status_code == 200, response.text
    assert answer not in response.text
    assert "answer_text" not in str(_json(selector))


def test_stored_semantic_projection_rechecks_hash_and_lineage_before_rendering() -> None:
    _, input_set, metric_suite = _semantic_fixture()
    snapshot = compute_semantic_metric_snapshot(
        input_set=input_set,
        suite=metric_suite,
        computed_at=datetime.fromisoformat("2026-07-24T00:00:00+00:00"),
    )
    stored = StoredSemanticMetricSnapshot(
        project_id=PROJECT_ID,
        snapshot_hash=snapshot.snapshot_hash,
        input_set_hash=snapshot.input_set_hash,
        suite_hash=snapshot.suite_hash,
        source_stratum_hash="f" * 64,
        payload=snapshot.canonical_value(),
    )

    response = semantic_snapshot_response(PROJECT_ID, stored)

    assert response.snapshot_hash == snapshot.snapshot_hash
    assert len(response.results) == len(snapshot.results)
    assert {item.result_hash for item in response.results} == {
        item.result_hash for item in snapshot.results
    }
    with pytest.raises(WorkflowCAnalysisUnavailable, match="hash is inconsistent"):
        semantic_snapshot_response(
            PROJECT_ID,
            StoredSemanticMetricSnapshot(
                project_id=PROJECT_ID,
                snapshot_hash="0" * 64,
                input_set_hash=snapshot.input_set_hash,
                suite_hash=snapshot.suite_hash,
                source_stratum_hash="f" * 64,
                payload=snapshot.canonical_value(),
            ),
        )


def test_comparison_endpoint_resolves_pairs_and_holm_protocol_server_side() -> None:
    app, api, _, _ = internal_app()
    stratum = _stratum("model-v1")
    selector = _comparison_selector()
    api.analysis.install_comparison_inputs(
        project_id=PROJECT_ID,
        selector=selector,
        comparisons=(_comparison_input(stratum),),
    )
    path = f"/v1/projects/{PROJECT_ID}/analysis/comparisons/analyze"

    with TestClient(app) as client:
        first = client.post(path, json=_json(selector))
        second = client.post(path, json=_json(selector))
        inventory = client.get(f"/v1/projects/{PROJECT_ID}/analysis/comparisons")
        forged = client.post(
            path,
            json={
                **_json(selector),
                "comparisons": [{"pairs": [{"baseline": 0, "candidate": 100}]}],
                "adjusted_p_value": "0",
            },
        )

    assert first.status_code == second.status_code == 200, first.text
    assert inventory.status_code == 200, inventory.text
    assert inventory.json()["items"][0]["family_hash"] == first.json()["family_hash"]
    assert forged.status_code == 422
    body = first.json()
    assert body == second.json()
    assert body["correction_method"] == "holm-v1"
    assert body["results"][0]["conclusion"] == "win"
    assert body["results"][0]["valid_pair_count"] == 4
    assert body["results"][0]["planned_pair_count"] == 4
    assert body["results"][0]["completion_ratio"] == "1"

    properties = app.openapi()["components"]["schemas"]["AnalyzeComparisonFamilyRequest"][
        "properties"
    ]
    assert not {
        "comparisons",
        "pairs",
        "achieved_power",
        "p_value",
        "effect",
    }.intersection(properties)


def test_drift_endpoint_resolves_effects_from_snapshot_selectors() -> None:
    app, api, _, _ = internal_app()
    baseline = _stratum("model-v1")
    current = _stratum("model-v2")
    selector = _drift_selector()
    api.analysis.install_drift_inputs(
        project_id=PROJECT_ID,
        selector=selector,
        baseline=(DriftObservation("baseline-1", baseline, Decimal("0.20")),),
        current=(DriftObservation("current-1", current, Decimal("0.10")),),
    )
    path = f"/v1/projects/{PROJECT_ID}/analysis/drift/compute"

    with TestClient(app) as client:
        response = client.post(path, json=_json(selector))
        inventory = client.get(f"/v1/projects/{PROJECT_ID}/analysis/drift")
        forged = client.post(
            path,
            json={
                **_json(selector),
                "baseline": [{"observation_id": "fake", "effect": "999"}],
                "current": [],
            },
        )

    assert response.status_code == 200, response.text
    assert inventory.status_code == 200, inventory.text
    assert inventory.json()["items"][0]["report_hash"] == response.json()["report_hash"]
    assert forged.status_code == 422
    body = response.json()
    assert len(body["model_drift"]) == 1
    assert body["model_drift"][0]["baseline_models"] == ["model-v1"]
    assert body["model_drift"][0]["current_models"] == ["model-v2"]
    assert body["source_drift"] == []
    assert body["effect_drift"] == []
    properties = app.openapi()["components"]["schemas"]["ComputeDriftRequest"]["properties"]
    assert not {"baseline", "current", "effects", "observations"}.intersection(properties)


def test_unknown_or_hash_mismatched_selector_fails_without_projection() -> None:
    app, api, _, _ = internal_app()
    selector, input_set, metric_suite = _semantic_fixture()
    api.analysis.install_semantic_inputs(
        project_id=PROJECT_ID,
        selector=selector,
        input_set=input_set,
        metric_suite=metric_suite,
    )
    forged = {**_json(selector), "fact_snapshot_hash": digest("different-facts")}

    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{PROJECT_ID}/analysis/semantic-metrics/compute",
            json=forged,
        )

    assert response.status_code == 404


def _semantic_fixture(
    *, observation: MetricObservation | None = None
) -> tuple[ComputeSemanticMetricsRequest, MetricInputSet, FrozenMetricSuite]:
    judge = JudgeVersion(
        key="metric-judge",
        version="metric-judge-v1",
        prompt_release_id=PROMPT_RELEASE_ID,
        prompt_release_hash=digest("metric-prompt"),
        model_identity="review-provider/model-v1",
        schema_version="metric-judge-output-v2",
    )
    metric_suite = first_metric_suite(
        judge_version=judge,
        rule_versions=DeterministicRuleVersions(
            subject="subject-rule-v1",
            url="url-rule-v1",
            citation_order="citation-order-v1",
            denominator="planned-denominator-v1",
            mention="mention-rule-v1",
        ),
        minimum_valid_completion=Decimal("0.80"),
    )
    input_set = MetricInputSet(
        stratum=SemanticStratum(
            (("capture_method", "provider_api"), ("locale", "en-AU"), ("region", "AU"))
        ),
        planned_slots=(PlannedMetricSlot("slot-1", "q-1", "purchase"),),
        observations=((observation,) if observation is not None else ()),
        subjects=SubjectInventory(
            primary_subject_key="advinsys",
            brand_aliases=("Advinsys",),
            product_aliases=("RoboClean X",),
            competitors=(("rivalco", ("RivalBot",)),),
        ),
        approved_facts=(),
        verified_urls=(),
        approved_corpus_version="corpus-v1",
        approved_corpus_hash=digest("corpus-v1"),
    )
    selector = ComputeSemanticMetricsRequest(
        sampling_run_id=RUN_ID,
        sampling_run_version=1,
        suite_hash=digest("sampling-suite-v1"),
        metric_protocol_id=METRIC_PROTOCOL_ID,
        metric_protocol_hash=metric_suite.suite_hash,
        fact_snapshot_id=FACT_SNAPSHOT_ID,
        fact_snapshot_hash=digest("approved-facts-v1"),
        prompt_release_id=PROMPT_RELEASE_ID,
        prompt_release_hash=judge.prompt_release_hash,
        corpus_version_id=CORPUS_VERSION_ID,
        corpus_version_hash=input_set.approved_corpus_hash,
    )
    return selector, input_set, metric_suite


def _stratum(model: str) -> StatisticalStratum:
    return StatisticalStratum(
        provider="openai",
        reported_model=model,
        capture_method="provider_api",
        locale="en-AU",
        region="AU",
        source_composition_hash=digest("source-composition"),
        sampling_source_stratum_hash=digest("sampling-source-stratum"),
        question_cluster="purchase",
    )


def _comparison_selector() -> AnalyzeComparisonFamilyRequest:
    return AnalyzeComparisonFamilyRequest(
        comparison_plan_id=COMPARISON_PLAN_ID,
        comparison_plan_hash=digest("comparison-plan"),
        baseline_metric_snapshot_hash=digest("baseline-metrics"),
        candidate_metric_snapshot_hash=digest("candidate-metrics"),
    )


def _comparison_input(stratum: StatisticalStratum) -> ComparisonInput:
    protocol = FrozenComparisonProtocol(
        protocol_hash=digest("comparison-protocol"),
        question_set_hash=digest("comparison-question-set"),
        baseline_version="baseline-v1",
        candidate_version="candidate-v2",
        metric_key="recommendation",
        metric_method_version="semantic-metrics-v1",
        comparison_id="recommendation-primary",
        family="primary-metrics",
        stratum=stratum,
        alpha=Decimal("0.05"),
        delta=Decimal("0.10"),
        target_power=Decimal("0.80"),
        precision=Decimal("1.00"),
        min_pairs=3,
        power_plan_hash=digest("a-priori-power-plan"),
        a_priori_design_power=Decimal("0.80"),
        minimum_completion_ratio=Decimal("0.80"),
        bootstrap_iterations=100,
    )
    pairs = tuple(
        PairedObservation(
            pair_id=f"pair-{index}",
            question_id=f"q-{index}",
            question_cluster="purchase",
            stratum_hash=stratum.stratum_hash,
            sampling_source_stratum_hash=stratum.sampling_source_stratum_hash,
            capture_method="provider_api",
            baseline=Decimal("0.10") * index,
            candidate=Decimal("0.10") * index + Decimal("1.00"),
        )
        for index in range(1, 5)
    )
    return ComparisonInput(protocol, stratum.sampling_source_stratum_hash, 4, pairs)


def _drift_selector() -> ComputeDriftRequest:
    return ComputeDriftRequest(
        drift_protocol_id=DRIFT_PROTOCOL_ID,
        drift_protocol_hash=digest("drift-protocol"),
        baseline_metric_snapshot_hash=digest("baseline-metrics"),
        current_metric_snapshot_hash=digest("current-metrics"),
    )


def _json(value) -> dict[str, object]:
    return value.model_dump(mode="json")
