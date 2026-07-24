"""Admin runtime selection is project-scoped and discloses no secret lineage."""

from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from geo_api.app_factory import create_api_app
from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.model_gateway.contracts import ModelCaptureMethod
from geo_core.model_gateway.runtime_catalog import (
    ApprovedRuntimeOption,
    ApprovedRuntimeOptions,
)


PROJECT_ID = UUID("10000000-0000-0000-0000-000000000001")
MANIFEST_ID = UUID("20000000-0000-0000-0000-000000000002")
SELECTION_ID = UUID("30000000-0000-0000-0000-000000000003")


class _Services:
    def __init__(self, role: str = "admin") -> None:
        self.role = role

    def require_project_role(
        self,
        authentication: object,
        *,
        project_id: UUID,
        allowed_roles: frozenset[str],
    ) -> AccessPrincipal:
        del authentication
        if self.role not in allowed_roles:
            from geo_core.access.models import AccessForbidden

            raise AccessForbidden("manager role is required")
        identity_id = UUID("40000000-0000-0000-0000-000000000004")
        tenant_id = UUID("50000000-0000-0000-0000-000000000005")
        return AccessPrincipal(
            identity_id=identity_id,
            actor_id=str(identity_id),
            tenant_id=tenant_id,
            memberships=(
                MembershipRecord(
                    project_id=project_id,
                    tenant_id=tenant_id,
                    role=self.role,
                ),
            ),
            auth_method="test",
        )


class _RuntimeApi:
    persistence = "durable"

    def list_options(self, *, project_id: UUID) -> ApprovedRuntimeOptions:
        assert project_id == PROJECT_ID
        return ApprovedRuntimeOptions(
            project_id=project_id,
            current_manifest_id=MANIFEST_ID,
            items=(
                ApprovedRuntimeOption(
                    selection_id=SELECTION_ID,
                    manifest_id=MANIFEST_ID,
                    provider="openai",
                    adapter_release_id="openai-responses-v1",
                    model_release_id="gpt-fixture-v1",
                    configured_model="gpt-fixture",
                    capture_method=ModelCaptureMethod.PROVIDER_API,
                    allowed_purposes=("prompt_release_test", "recommendation"),
                    allowed_search_modes=(None, "web"),
                ),
            ),
        )


def test_admin_lists_only_sanitized_opaque_runtime_options() -> None:
    app = create_api_app(
        surface="internal",
        services=_Services(),  # type: ignore[arg-type]
        model_gateway_runtime_api=_RuntimeApi(),
    )
    with TestClient(app) as client:
        response = client.get(f"/v1/projects/{PROJECT_ID}/model-gateway/options")

    assert response.status_code == 200
    assert response.json() == {
        "current_manifest_id": str(MANIFEST_ID),
        "items": [
            {
                "selection_id": str(SELECTION_ID),
                "manifest_id": str(MANIFEST_ID),
                "provider": "openai",
                "adapter_release_id": "openai-responses-v1",
                "model_release_id": "gpt-fixture-v1",
                "configured_model": "gpt-fixture",
                "capture_method": "provider_api",
                "allowed_purposes": ["prompt_release_test", "recommendation"],
                "allowed_search_modes": [None, "web"],
            }
        ],
    }
    rendered = response.text.lower()
    for forbidden in ("secret", "endpoint", "hash", "credential"):
        assert forbidden not in rendered


def test_customer_surface_never_mounts_runtime_catalog() -> None:
    app = create_api_app(
        surface="customer",
        services=_Services(),  # type: ignore[arg-type]
        model_gateway_runtime_api=_RuntimeApi(),
    )
    with TestClient(app) as client:
        response = client.get(f"/v1/projects/{PROJECT_ID}/model-gateway/options")
    assert response.status_code == 404
