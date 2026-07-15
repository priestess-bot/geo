from __future__ import annotations

from dataclasses import replace
import os
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from geo_api.app_factory import ApiSettings, create_api_app
from geo_api.foundation_services import ConnectedFoundationServices
from geo_core.access.models import ExternalIdentity
from geo_core.access.postgres import PsycopgAccessUnitOfWorkFactory
from geo_core.access.service import AccessApplicationService
from geo_core.catalog.application import CatalogApplication
from geo_core.catalog.postgres import PsycopgCatalogUnitOfWorkFactory
from scripts import provision_initial_owner as provisioner


APP_URL = os.getenv("GEO_ACCESS_TEST_DATABASE_URL", "").strip()
ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not APP_URL or not ADMIN_URL,
        reason="GEO_ACCESS_TEST_DATABASE_URL and GEO_ACCESS_TEST_ADMIN_DATABASE_URL are required",
    ),
]


class FixedOidcVerifier:
    def __init__(self, external: ExternalIdentity) -> None:
        self.external = external

    def verify(self, token: str) -> ExternalIdentity:
        assert token == "verified-edge-token"
        return self.external


def test_initial_owner_first_replay_conflict_denial_audit_and_project_creation() -> None:
    marker = uuid4().hex[:10]
    config = provisioner.InitialOwnerConfig(
        tenant_id=uuid4(),
        tenant_name=f"Bootstrap Tenant {marker}",
        oidc_issuer="https://identity.example.com/",
        oidc_subject=f"owner-{marker}",
        email=f"owner-{marker}@example.com",
        display_name=f"Owner {marker}",
        project_id=uuid4(),
        project_name=f"Initial Project {marker}",
    )
    identity_id: UUID | None = None
    try:
        first = provisioner.provision_from_url(ADMIN_URL, config)
        identity_id = first.identity_id
        replay = provisioner.provision_from_url(ADMIN_URL, config)

        assert first.replayed is False
        assert replay.replayed is True
        assert replay.tenant_id == first.tenant_id == config.tenant_id
        assert replay.identity_id == first.identity_id
        assert replay.project_id == first.project_id == config.project_id

        with pytest.raises(
            provisioner.InitialOwnerProvisionError,
            match="bootstrap_existing_state_conflict",
        ):
            provisioner.provision_from_url(
                ADMIN_URL, replace(config, project_name="Conflicting Project")
            )
        with pytest.raises(
            provisioner.InitialOwnerProvisionError,
            match="bootstrap_installer_role_required",
        ):
            provisioner.provision_from_url(APP_URL, config)

        with psycopg.connect(ADMIN_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT actor_identity_id, subject_type, subject_id, metadata
                FROM access_audit_events
                WHERE tenant_id = %s AND event_type = 'tenant.bootstrap'
                ORDER BY created_at, id
                """,
                (config.tenant_id,),
            )
            audit = cursor.fetchall()
        assert len(audit) == 2
        assert [row[3]["replayed"] for row in audit] == [False, True]
        assert {row[3]["issuer"] for row in audit} == {config.oidc_issuer}
        assert all(row[0] == first.identity_id for row in audit)
        assert all(row[1] == "project" and row[2] == config.project_id for row in audit)

        access = AccessApplicationService(PsycopgAccessUnitOfWorkFactory(APP_URL))
        services = ConnectedFoundationServices(
            access,
            surface="internal",
            auth_mode="oidc",
            oidc_verifier=FixedOidcVerifier(
                ExternalIdentity(
                    issuer=config.oidc_issuer,
                    subject=config.oidc_subject,
                    tenant_id=config.tenant_id,
                    email=config.email,
                    display_name=config.display_name,
                )
            ),  # type: ignore[arg-type]
        )
        app = create_api_app(
            surface="internal",
            settings=ApiSettings(deployment_environment="production"),
            services=services,
            catalog_application=CatalogApplication(PsycopgCatalogUnitOfWorkFactory(APP_URL)),
        )
        with TestClient(app) as client:
            response = client.post(
                "/v1/projects",
                headers={"Authorization": "Bearer verified-edge-token"},
                json={"name": f"Second Project {marker}"},
            )
        assert response.status_code == 201, response.text
        created_project_id = UUID(response.json()["id"])
        assert UUID(response.json()["tenant_id"]) == config.tenant_id
        with psycopg.connect(ADMIN_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT role, status FROM project_memberships
                WHERE project_id = %s AND identity_id = %s
                """,
                (created_project_id, first.identity_id),
            )
            assert cursor.fetchone() == ("owner", "active")
    finally:
        _cleanup(config.tenant_id, identity_id)


def _cleanup(tenant_id: UUID, identity_id: UUID | None) -> None:
    with psycopg.connect(ADMIN_URL) as connection, connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE access_audit_events DISABLE TRIGGER " "access_audit_events_append_only"
        )
        cursor.execute("DELETE FROM access_audit_events WHERE tenant_id = %s", (tenant_id,))
        cursor.execute(
            "ALTER TABLE access_audit_events ENABLE TRIGGER " "access_audit_events_append_only"
        )
        cursor.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        if identity_id is not None:
            cursor.execute("DELETE FROM identities WHERE id = %s", (identity_id,))
