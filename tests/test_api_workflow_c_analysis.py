from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import pytest
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from geo_api.workflow_c_analysis_contracts import (
    AnalyzeComparisonFamilyRequest,
    ComputeDriftRequest,
    ComputeSemanticMetricsRequest,
)
from geo_api.workflow_c_analysis_runtime import (
    SemanticAnalysisJobReceipt,
    StatisticalAnalysisJobReceipt,
    WorkflowCAnalysisUnavailable,
)
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
from geo_core.workflow_c_statistical_protocols import ComparisonPlanDefinition

from tests.workflow_c_analysis_test_support import metric_protocol_definition_fixture
from tests.workflow_c_api_test_support import (
    PROJECT_ID,
    digest,
    internal_app,
    principal,
)


RUN_ID = UUID("71000000-0000-4000-8000-000000000001")
METRIC_PROTOCOL_ID = UUID("71000000-0000-4000-8000-000000000002")
FACT_SNAPSHOT_ID = UUID("71000000-0000-4000-8000-000000000003")
PROMPT_RELEASE_ID = UUID("71000000-0000-4000-8000-000000000004")
CORPUS_VERSION_ID = UUID("71000000-0000-4000-8000-000000000005")
COMPARISON_PLAN_ID = UUID("71000000-0000-4000-8000-000000000006")
DRIFT_PROTOCOL_ID = UUID("71000000-0000-4000-8000-000000000007")


def test_metric_protocol_api_enforces_maker_checker_lifecycle() -> None:
    app, _, _, services = internal_app()
    path = f"/v1/projects/{PROJECT_ID}/analysis/metric-protocols"

    with TestClient(app) as client:
        created = client.post(
            path,
            headers={"Idempotency-Key": "metric-protocol:create"},
            json={
                "definition": metric_protocol_definition_fixture().canonical_value(),
                "supersedes_protocol_id": None,
            },
        )
        protocol_id = created.json()["id"]
        submitted = client.post(
            f"{path}/{protocol_id}/submit",
            headers={"Idempotency-Key": "metric-protocol:submit"},
            json={"expected_aggregate_version": 1},
        )
        self_approval = client.post(
            f"{path}/{protocol_id}/approve",
            headers={"Idempotency-Key": "metric-protocol:self-approve"},
            json={
                "expected_aggregate_version": 2,
                "reason": "fixed regression suite passed",
            },
        )
        services.principal = principal("owner")
        approved = client.post(
            f"{path}/{protocol_id}/approve",
            headers={"Idempotency-Key": "metric-protocol:approve"},
            json={
                "expected_aggregate_version": 2,
                "reason": "fixed regression suite passed",
            },
        )
        listed = client.get(path)

    assert created.status_code == 201
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "in_review"
    assert self_approval.status_code == 422
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by"] == "workflow-c-owner"
    assert listed.status_code == 200
    assert listed.json()["items"] == [approved.json()]


def test_semantic_job_enqueue_returns_pollable_immutable_receipt(monkeypatch) -> None:
    app, api, _, _ = internal_app()
    job_id, manifest_id = uuid4(), uuid4()

    def enqueue(**kwargs) -> SemanticAnalysisJobReceipt:
        assert kwargs == {
            "project_id": PROJECT_ID,
            "payload": kwargs["payload"],
            "actor_id": "workflow-c-admin",
            "idempotency_key": "semantic-metrics:one",
        }
        assert kwargs["payload"].sampling_run_id == RUN_ID
        assert kwargs["payload"].metric_protocol_id == METRIC_PROTOCOL_ID
        return SemanticAnalysisJobReceipt(
            job_id=job_id,
            manifest_id=manifest_id,
            manifest_hash=digest("semantic-manifest"),
            replayed=False,
        )

    monkeypatch.setattr(api.analysis, "enqueue_semantic_metrics", enqueue)
    path = f"/v1/projects/{PROJECT_ID}/analysis/semantic-metrics/jobs"
    with TestClient(app) as client:
        response = client.post(
            path,
            headers={"Idempotency-Key": "semantic-metrics:one"},
            json={
                "sampling_run_id": str(RUN_ID),
                "metric_protocol_id": str(METRIC_PROTOCOL_ID),
                "max_attempts": 3,
            },
        )
        forged = client.post(
            path,
            headers={"Idempotency-Key": "semantic-metrics:forged"},
            json={
                "sampling_run_id": str(RUN_ID),
                "metric_protocol_id": str(METRIC_PROTOCOL_ID),
                "answer_text": "client supplied truth",
            },
        )

    assert response.status_code == 202
    assert response.headers["Location"] == f"/v1/jobs/{job_id}"
    assert response.json() == {
        "job_id": str(job_id),
        "status": "queued",
        "status_url": f"/v1/jobs/{job_id}",
        "manifest_id": str(manifest_id),
        "manifest_hash": digest("semantic-manifest"),
        "replayed": False,
    }
    assert forged.status_code == 422


def test_statistical_protocol_api_enforces_kind_and_maker_checker_lifecycle() -> None:
    app, _, _, services = internal_app()
    path = f"/v1/projects/{PROJECT_ID}/analysis/statistical-protocols"
    definition = _comparison_plan_definition()

    with TestClient(app) as client:
        created = client.post(
            path,
            headers={"Idempotency-Key": "comparison-plan:create"},
            json={"definition": definition.canonical_value()},
        )
        protocol_id = created.json()["id"]
        submitted = client.post(
            f"{path}/{protocol_id}/submit",
            headers={"Idempotency-Key": "comparison-plan:submit"},
            json={"expected_aggregate_version": 1},
        )
        self_approval = client.post(
            f"{path}/{protocol_id}/approve",
            headers={"Idempotency-Key": "comparison-plan:self-approve"},
            json={"expected_aggregate_version": 2, "reason": "frozen design reviewed"},
        )
        services.principal = principal("owner")
        approved = client.post(
            f"{path}/{protocol_id}/approve",
            headers={"Idempotency-Key": "comparison-plan:approve"},
            json={"expected_aggregate_version": 2, "reason": "frozen design reviewed"},
        )
        listed = client.get(path)

    assert created.status_code == 201, created.text
    assert created.json()["kind"] == "comparison_plan"
    assert created.json()["definition_hash"] == definition.definition_hash
    assert submitted.status_code == 200
    assert self_approval.status_code == 422
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert listed.json()["items"] == [approved.json()]


def test_statistical_job_routes_accept_only_protocol_and_snapshot_selectors(
    monkeypatch,
) -> None:
    app, api, _, _ = internal_app()
    comparison_job, drift_job = uuid4(), uuid4()

    def enqueue_comparison(**kwargs) -> StatisticalAnalysisJobReceipt:
        assert kwargs["payload"].comparison_plan_id == COMPARISON_PLAN_ID
        assert kwargs["actor_id"] == "workflow-c-admin"
        return StatisticalAnalysisJobReceipt(
            comparison_job, digest("comparison-spec"), False
        )

    def enqueue_drift(**kwargs) -> StatisticalAnalysisJobReceipt:
        assert kwargs["payload"].drift_protocol_id == DRIFT_PROTOCOL_ID
        assert kwargs["actor_id"] == "workflow-c-admin"
        return StatisticalAnalysisJobReceipt(drift_job, digest("drift-spec"), True)

    monkeypatch.setattr(api.analysis, "enqueue_comparison", enqueue_comparison)
    monkeypatch.setattr(api.analysis, "enqueue_drift", enqueue_drift)
    comparison_path = f"/v1/projects/{PROJECT_ID}/analysis/comparisons/jobs"
    drift_path = f"/v1/projects/{PROJECT_ID}/analysis/drift/jobs"
    with TestClient(app) as client:
        comparison = client.post(
            comparison_path,
            headers={"Idempotency-Key": "comparison:one"},
            json={
                "comparison_plan_id": str(COMPARISON_PLAN_ID),
                "baseline_metric_snapshot_hash": digest("baseline"),
                "candidate_metric_snapshot_hash": digest("candidate"),
            },
        )
        drift = client.post(
            drift_path,
            headers={"Idempotency-Key": "drift:one"},
            json={
                "drift_protocol_id": str(DRIFT_PROTOCOL_ID),
                "baseline_metric_snapshot_hash": digest("baseline"),
                "current_metric_snapshot_hash": digest("current"),
            },
        )
        forged = client.post(
            comparison_path,
            headers={"Idempotency-Key": "comparison:forged"},
            json={
                "comparison_plan_id": str(COMPARISON_PLAN_ID),
                "baseline_metric_snapshot_hash": digest("baseline"),
                "candidate_metric_snapshot_hash": digest("candidate"),
                "pairs": [{"baseline": "0", "candidate": "999"}],
            },
        )

    assert comparison.status_code == 202
    assert comparison.headers["Location"] == f"/v1/jobs/{comparison_job}"
    assert comparison.json()["spec_hash"] == digest("comparison-spec")
    assert drift.status_code == 202
    assert drift.headers["Location"] == f"/v1/jobs/{drift_job}"
    assert drift.json()["replayed"] is True
    assert forged.status_code == 422


@pytest.mark.parametrize(
    ("resource", "legacy_action", "runtime_method"),
    (
        ("semantic-metrics", "compute", "compute_semantic_metrics"),
        ("comparisons", "analyze", "analyze_comparisons"),
        ("drift", "compute", "compute_drift"),
    ),
)
def test_synchronous_analysis_compatibility_endpoints_are_stable_gone(
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
    legacy_action: str,
    runtime_method: str,
) -> None:
    app, api, _, _ = internal_app()
    monkeypatch.setattr(
        api.analysis,
        runtime_method,
        lambda **_kwargs: pytest.fail("removed endpoint called its runtime computation method"),
    )
    if resource == "semantic-metrics":
        payload = _json(_semantic_fixture()[0])
    elif resource == "comparisons":
        payload = _json(_comparison_selector())
    else:
        payload = _json(_drift_selector())
    path = f"/v1/projects/{PROJECT_ID}/analysis/{resource}/{legacy_action}"
    successor = f"/v1/projects/{PROJECT_ID}/analysis/{resource}/jobs"

    with TestClient(app) as client:
        response = client.post(path, json=payload)
        inventory = client.get(f"/v1/projects/{PROJECT_ID}/analysis/{resource}")

    assert response.status_code == 410, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["deprecation"] == "true"
    assert response.headers["link"] == f'<{successor}>; rel="successor-version"'
    assert response.json() == {
        "type": "urn:geo:problem:synchronous-analysis-removed",
        "title": "Gone",
        "status": 410,
        "detail": (
            "Synchronous Workflow C analysis has been removed. "
            f"Enqueue the durable job with POST {successor}."
        ),
        "instance": path,
        "request_id": response.headers["x-request-id"],
    }
    assert inventory.status_code == 200, inventory.text
    assert inventory.json() == {"items": [], "total": 0}

    openapi_path = f"/v1/projects/{{project_id}}/analysis/{resource}/{legacy_action}"
    operation = app.openapi()["paths"][openapi_path]["post"]
    assert operation["deprecated"] is True
    assert "200" not in operation["responses"]
    assert "410" in operation["responses"]
    assert "application/problem+json" in operation["responses"]["410"]["content"]


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


def _comparison_selector() -> AnalyzeComparisonFamilyRequest:
    return AnalyzeComparisonFamilyRequest(
        comparison_plan_id=COMPARISON_PLAN_ID,
        comparison_plan_hash=digest("comparison-plan"),
        baseline_metric_snapshot_hash=digest("baseline-metrics"),
        candidate_metric_snapshot_hash=digest("candidate-metrics"),
    )


def _comparison_plan_definition() -> ComparisonPlanDefinition:
    return ComparisonPlanDefinition(
        family="primary-metrics",
        question_clusters=("purchase",),
        alpha=Decimal("0.05"),
        delta=Decimal("0.10"),
        target_power=Decimal("0.80"),
        precision=Decimal("0.20"),
        min_pairs=3,
        power_plan_hash=digest("a-priori-power-plan"),
        a_priori_design_power=Decimal("0.85"),
        bootstrap_iterations=100,
    )


def _drift_selector() -> ComputeDriftRequest:
    return ComputeDriftRequest(
        drift_protocol_id=DRIFT_PROTOCOL_ID,
        drift_protocol_hash=digest("drift-protocol"),
        baseline_metric_snapshot_hash=digest("baseline-metrics"),
        current_metric_snapshot_hash=digest("current-metrics"),
    )


def _json(value) -> dict[str, object]:
    return value.model_dump(mode="json")
