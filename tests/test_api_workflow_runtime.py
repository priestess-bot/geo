"""Dify workflow status is project-scoped and never exposes Secret handles."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from geo_api.app_factory import create_api_app
from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_api.workflow_runtime_api import RefreshingWorkflowRuntimeApi
from geo_core.workflow_runtime import PublishedWorkflowSnapshot, WorkflowRuntimeCard
from geo_core.workflow_runtime import DifyUnresolvedAttempt
from geo_core.workflow_runtime import WorkflowConfigurationError


PROJECT_ID = UUID("10000000-0000-0000-0000-000000000001")
RELEASE_ID = UUID("20000000-0000-0000-0000-000000000002")


class _Services:
    def __init__(self, role: str = "analyst") -> None:
        self.role = role

    def require_project_role(
        self,
        authentication: object,
        *,
        project_id: UUID,
        allowed_roles: frozenset[str],
    ) -> AccessPrincipal:
        del authentication
        assert self.role in allowed_roles
        identity_id = UUID("30000000-0000-0000-0000-000000000003")
        tenant_id = UUID("40000000-0000-0000-0000-000000000004")
        return AccessPrincipal(
            identity_id=identity_id,
            actor_id=str(identity_id),
            tenant_id=tenant_id,
            memberships=(MembershipRecord(project_id, tenant_id, self.role),),
            auth_method="test",
        )


class _Catalog:
    persistence = "durable"

    def list_cards(self, *, project_id: UUID):
        assert project_id == PROJECT_ID
        return (
            WorkflowRuntimeCard(
                purpose="knowledge.question_generation",
                backend="dify",
                activation_status="active",
                release_id=RELEASE_ID,
                release_version=2,
                release_hash="a" * 64,
                prompt_program_id=UUID("50000000-0000-0000-0000-000000000005"),
                prompt_release_id=UUID("60000000-0000-0000-0000-000000000006"),
                prompt_release_hash="b" * 64,
                dify_app_id="app-1",
                dify_workflow_id="workflow-1",
                dsl_hash="c" * 64,
                configured_model="deepseek-chat",
                model_provider="deepseek",
                binding_version=1,
                activated_at=datetime(2026, 7, 26, tzinfo=UTC),
                last_attempt_status="succeeded",
                last_attempt_kind="canary",
                last_attempt_at=datetime(2026, 7, 26, tzinfo=UTC),
            ),
            WorkflowRuntimeCard(
                purpose="synthetic_lab.style_profile",
                backend="native",
                activation_status="not_configured",
            ),
            WorkflowRuntimeCard(
                purpose="recommendations.recommendation",
                backend="native",
                activation_status="not_configured",
            ),
        )


class _ReconciliationCatalog(_Catalog):
    def __init__(self) -> None:
        self.issued: dict[str, object] | None = None

    def list_unresolved_attempts(self, *, project_id: UUID):
        assert project_id == PROJECT_ID
        return (
            DifyUnresolvedAttempt(
                attempt_id=UUID("71000000-0000-0000-0000-000000000071"),
                parent_job_id=UUID("72000000-0000-0000-0000-000000000072"),
                child_job_id=UUID("73000000-0000-0000-0000-000000000073"),
                flow_kind="recommendation",
                purpose="recommendations.recommendation",
                status="failed",
                child_job_status="failed",
                lease_state="terminal",
                required_action="verify_provider_then_issue_new_parent_token",
                provider_run_id="dify-run-1",
                error_code="dify_unknown_outcome",
                error_message="response was not definitive",
                started_at=datetime(2026, 7, 28, tzinfo=UTC),
            ),
            DifyUnresolvedAttempt(
                attempt_id=UUID("74000000-0000-0000-0000-000000000074"),
                parent_job_id=UUID("75000000-0000-0000-0000-000000000075"),
                child_job_id=UUID("76000000-0000-0000-0000-000000000076"),
                flow_kind="style_profile",
                purpose="synthetic_lab.style_profile",
                status="running",
                child_job_status="running",
                lease_state="active",
                required_action="wait_for_lease_expiry",
                provider_run_id=None,
                error_code=None,
                error_message=None,
                started_at=datetime(2026, 7, 28, 0, 1, tzinfo=UTC),
            ),
        )

    def authorize_new_parent_after_unknown_outcome(self, **values: object) -> str:
        if values["attempt_id"] == UUID("74000000-0000-0000-0000-000000000074"):
            raise WorkflowConfigurationError(
                "Dify attempt cannot be reconciled while its Durable Job lease is active"
            )
        self.issued = values
        return "a" * 64


def test_internal_api_returns_actionable_dify_card_without_secret_lineage(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEO_WORKFLOW_RUNTIME_BACKEND", "dify")
    monkeypatch.setenv("GEO_DIFY_CONSOLE_URL", "http://127.0.0.1:15000")
    app = create_api_app(
        surface="internal",
        services=_Services(),  # type: ignore[arg-type]
        workflow_runtime_api=_Catalog(),
    )
    with TestClient(app) as client:
        response = client.get(f"/v1/projects/{PROJECT_ID}/dify-workflows")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_backend"] == "dify"
    assert body["items"][0]["activation_status"] == "active"
    assert body["items"][0]["console_url"].endswith("/app/app-1/workflow")
    assert [item["purpose"] for item in body["items"]] == [
        "knowledge.question_generation",
        "synthetic_lab.style_profile",
        "recommendations.recommendation",
    ]
    rendered = response.text.lower()
    for forbidden in ("secret_reference", "secret_version", "api_key", "credential"):
        assert forbidden not in rendered


def test_customer_api_does_not_mount_dify_catalog() -> None:
    app = create_api_app(
        surface="customer",
        services=_Services(),  # type: ignore[arg-type]
        workflow_runtime_api=_Catalog(),
    )
    with TestClient(app) as client:
        response = client.get(f"/v1/projects/{PROJECT_ID}/dify-workflows")
    assert response.status_code == 404


def test_internal_operator_can_list_and_issue_one_time_recovery_token() -> None:
    catalog = _ReconciliationCatalog()
    app = create_api_app(
        surface="internal",
        services=_Services("owner"),  # type: ignore[arg-type]
        workflow_runtime_api=catalog,
    )
    attempt_id = UUID("71000000-0000-0000-0000-000000000071")
    with TestClient(app) as client:
        listed = client.get(f"/v1/projects/{PROJECT_ID}/dify-workflows/unresolved-attempts")
        issued = client.post(
            f"/v1/projects/{PROJECT_ID}/dify-workflows/unresolved-attempts/"
            f"{attempt_id}/resubmission-token",
            json={
                "provider_outcome": "failed_without_output",
                "provider_run_id": "dify-run-1",
                "evidence_reference": "dify-console://run/dify-run-1",
                "reason": "Provider run failed before producing an output.",
            },
        )
        invalid = client.post(
            f"/v1/projects/{PROJECT_ID}/dify-workflows/unresolved-attempts/"
            f"{attempt_id}/resubmission-token",
            json={
                "provider_outcome": "failed_without_output",
                "evidence_reference": "dify-console://run/missing",
                "reason": "Missing provider run ID must fail.",
            },
        )
        active_lease = client.post(
            f"/v1/projects/{PROJECT_ID}/dify-workflows/unresolved-attempts/"
            "74000000-0000-0000-0000-000000000074/resubmission-token",
            json={
                "provider_outcome": "not_found",
                "provider_run_id": None,
                "evidence_reference": "dify-console://search/no-run",
                "reason": "No provider run was found.",
            },
        )

    assert listed.status_code == 200
    assert listed.json()["items"][0]["flow_kind"] == "recommendation"
    assert listed.json()["items"][0]["lease_state"] == "terminal"
    assert listed.json()["items"][1]["lease_state"] == "active"
    assert listed.json()["items"][1]["required_action"] == "wait_for_lease_expiry"
    assert listed.json()["items"][0]["required_action"] == (
        "verify_provider_then_issue_new_parent_token"
    )
    assert issued.status_code == 201
    assert issued.headers["cache-control"] == "no-store"
    assert issued.json()["dify_reconciliation_token"] == "a" * 64
    assert issued.json()["recovery_of_attempt_id"] == str(attempt_id)
    assert catalog.issued is not None
    assert catalog.issued["attempt_id"] == attempt_id
    assert invalid.status_code == 422
    assert active_lease.status_code == 409
    assert "lease is active" in active_lease.json()["detail"]


class _RefreshCatalog:
    def __init__(self, card: WorkflowRuntimeCard) -> None:
        self.card = card
        self.recorded: list[PublishedWorkflowSnapshot] = []

    def list_cards(self, *, project_id: UUID):
        assert project_id == PROJECT_ID
        return (self.card,)

    def record_published_snapshot(
        self,
        *,
        project_id: UUID,
        release_id: UUID,
        snapshot: PublishedWorkflowSnapshot,
    ) -> UUID:
        assert project_id == PROJECT_ID
        assert release_id == RELEASE_ID
        self.recorded.append(snapshot)
        return UUID("70000000-0000-0000-0000-000000000007")


class _SnapshotReader:
    def __init__(self, snapshot: PublishedWorkflowSnapshot) -> None:
        self.snapshot = snapshot

    def read(self, *, purpose: str, app_id: str) -> PublishedWorkflowSnapshot:
        assert purpose == "knowledge.question_generation"
        assert app_id == "app-1"
        return self.snapshot


def _published_snapshot(*, snapshot_hash: str, prompt_text: str) -> PublishedWorkflowSnapshot:
    now = datetime(2026, 7, 28, tzinfo=UTC)
    return PublishedWorkflowSnapshot(
        purpose="knowledge.question_generation",
        app_id="app-1",
        workflow_id="published-workflow",
        workflow_hash="d" * 64,
        snapshot_hash=snapshot_hash,
        prompt_nodes=(
            {
                "node_id": "llm-1",
                "title": "Prompt",
                "model_provider": "deepseek",
                "model_name": "deepseek-chat",
                "messages": [{"role": "system", "text": prompt_text}],
            },
        ),
        input_variables=({"name": "geo_context_json"},),
        graph_nodes=({"node_id": "llm-1", "type": "llm", "title": "Prompt"},),
        published_at=now,
        observed_at=now,
    )


def test_refresh_marks_graph_drift_and_keeps_the_pinned_snapshot_visible() -> None:
    pinned_nodes = ({"node_id": "llm-1", "title": "Pinned", "messages": []},)
    card = WorkflowRuntimeCard(
        purpose="knowledge.question_generation",
        backend="dify",
        activation_status="active",
        release_id=RELEASE_ID,
        dify_app_id="app-1",
        dify_workflow_id="published-workflow",
        published_workflow_hash="d" * 64,
        published_snapshot_hash="e" * 64,
        published_prompt_nodes=pinned_nodes,
        sync_status="cached",
    )
    catalog = _RefreshCatalog(card)
    changed = _published_snapshot(snapshot_hash="f" * 64, prompt_text="Changed Prompt")

    result = RefreshingWorkflowRuntimeApi(
        catalog=catalog,  # type: ignore[arg-type]
        reader=_SnapshotReader(changed),  # type: ignore[arg-type]
    ).list_cards(project_id=PROJECT_ID)[0]

    assert catalog.recorded == [changed]
    assert result.sync_status == "drifted"
    assert result.published_snapshot_hash == "e" * 64
    assert result.published_prompt_nodes == pinned_nodes
    assert "新的 Workflow Release" in (result.sync_error or "")


def test_refresh_reports_current_only_when_live_graph_matches_the_pin() -> None:
    snapshot = _published_snapshot(snapshot_hash="e" * 64, prompt_text="Pinned Prompt")
    card = WorkflowRuntimeCard(
        purpose="knowledge.question_generation",
        backend="dify",
        activation_status="active",
        release_id=RELEASE_ID,
        dify_app_id="app-1",
        dify_workflow_id="published-workflow",
        published_workflow_hash=snapshot.workflow_hash,
        published_snapshot_hash=snapshot.snapshot_hash,
        published_prompt_nodes=snapshot.prompt_nodes,
        sync_status="cached",
    )

    result = RefreshingWorkflowRuntimeApi(
        catalog=_RefreshCatalog(card),  # type: ignore[arg-type]
        reader=_SnapshotReader(snapshot),  # type: ignore[arg-type]
    ).list_cards(project_id=PROJECT_ID)[0]

    assert result.sync_status == "current"
    assert result.published_snapshot_hash == snapshot.snapshot_hash
