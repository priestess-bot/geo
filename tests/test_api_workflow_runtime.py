"""Dify workflow status is project-scoped and never exposes Secret handles."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from geo_api.app_factory import create_api_app
from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.workflow_runtime import WorkflowRuntimeCard


PROJECT_ID = UUID("10000000-0000-0000-0000-000000000001")
RELEASE_ID = UUID("20000000-0000-0000-0000-000000000002")


class _Services:
    def require_project_role(
        self,
        authentication: object,
        *,
        project_id: UUID,
        allowed_roles: frozenset[str],
    ) -> AccessPrincipal:
        del authentication
        assert "analyst" in allowed_roles
        identity_id = UUID("30000000-0000-0000-0000-000000000003")
        tenant_id = UUID("40000000-0000-0000-0000-000000000004")
        return AccessPrincipal(
            identity_id=identity_id,
            actor_id=str(identity_id),
            tenant_id=tenant_id,
            memberships=(MembershipRecord(project_id, tenant_id, "analyst"),),
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
        )


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
