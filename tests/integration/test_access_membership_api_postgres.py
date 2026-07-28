from __future__ import annotations

import os
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from geo_api.app_factory import ApiSettings, create_api_app
from geo_api.foundation_services import ConnectedFoundationServices
from geo_core.access.membership_service import AccessMembershipService
from geo_core.access.models import ExternalIdentity
from geo_core.access.postgres import PsycopgAccessUnitOfWorkFactory
from geo_core.access.service import AccessApplicationService
from geo_core.catalog.application import CatalogApplication
from geo_core.catalog.postgres import PsycopgCatalogUnitOfWorkFactory
from scripts.bootstrap_deepseek_prompt_runtime import (
    _project_operator as deepseek_project_operator,
)
from scripts.enroll_dify_workflows import _project_operator as dify_project_operator


APP_URL = os.getenv("GEO_ACCESS_TEST_DATABASE_URL", "").strip()
ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not APP_URL or not ADMIN_URL,
        reason="GEO_ACCESS_TEST_DATABASE_URL and GEO_ACCESS_TEST_ADMIN_DATABASE_URL are required",
    ),
]


class MappingOidcVerifier:
    def __init__(self, identities: dict[str, ExternalIdentity]) -> None:
        self.identities = identities

    def verify(self, token: str) -> ExternalIdentity:
        return self.identities[token]


def test_oidc_member_management_is_idempotent_governed_and_project_scoped() -> None:
    tenant_id = uuid4()
    foreign_tenant_id = uuid4()
    project_id = uuid4()
    foreign_project_id = uuid4()
    owner_id = uuid4()
    foreign_owner_id = uuid4()
    marker = uuid4().hex[:10]
    issuer = "https://identity.example.com/"
    owner_subject = f"owner-{marker}"
    analyst_subject = f"analyst-{marker}"
    admin_subject = f"admin-{marker}"
    customer_subject = f"customer-{marker}"
    _seed(
        tenant_id=tenant_id,
        foreign_tenant_id=foreign_tenant_id,
        project_id=project_id,
        foreign_project_id=foreign_project_id,
        owner_id=owner_id,
        foreign_owner_id=foreign_owner_id,
        marker=marker,
        issuer=issuer,
        owner_subject=owner_subject,
    )
    factory = PsycopgAccessUnitOfWorkFactory(APP_URL)
    access = AccessApplicationService(factory)
    verifier = MappingOidcVerifier(
        {
            "owner-token": ExternalIdentity(
                issuer=issuer, subject=owner_subject, tenant_id=tenant_id
            ),
            "analyst-token": ExternalIdentity(
                issuer=issuer, subject=analyst_subject, tenant_id=tenant_id
            ),
            "admin-token": ExternalIdentity(
                issuer=issuer, subject=admin_subject, tenant_id=tenant_id
            ),
        }
    )
    app = create_api_app(
        surface="internal",
        settings=ApiSettings(deployment_environment="production"),
        services=ConnectedFoundationServices(
            access,
            surface="internal",
            auth_mode="oidc",
            oidc_verifier=verifier,  # type: ignore[arg-type]
        ),
        membership_application=AccessMembershipService(factory),
        catalog_application=CatalogApplication(PsycopgCatalogUnitOfWorkFactory(APP_URL)),
    )
    owner_headers = {"Authorization": "Bearer owner-token"}
    analyst_headers = {"Authorization": "Bearer analyst-token"}
    admin_headers = {"Authorization": "Bearer admin-token"}
    analyst_payload = {
        "issuer": issuer,
        "subject": analyst_subject,
        "email": f"analyst-{marker}@example.com",
        "display_name": f"Analyst {marker}",
        "role": "analyst",
    }
    admin_payload = {
        "issuer": issuer,
        "subject": admin_subject,
        "email": f"admin-{marker}@example.com",
        "display_name": f"Admin {marker}",
        "role": "admin",
    }
    try:
        with TestClient(app) as client:
            created = client.post(
                f"/v1/projects/{project_id}/members",
                headers={**owner_headers, "Idempotency-Key": f"add-analyst-{marker}"},
                json=analyst_payload,
            )
            assert created.status_code == 201, created.text
            assert created.json()["replayed"] is False
            analyst_member = created.json()["member"]
            assert UUID(analyst_member["identity_id"]) != owner_id

            replay = client.post(
                f"/v1/projects/{project_id}/members",
                headers={**owner_headers, "Idempotency-Key": f"add-analyst-{marker}"},
                json=analyst_payload,
            )
            assert replay.status_code == 201
            assert replay.json()["replayed"] is True
            assert replay.json()["member"]["membership_id"] == analyst_member["membership_id"]

            conflict = client.post(
                f"/v1/projects/{project_id}/members",
                headers={**owner_headers, "Idempotency-Key": f"add-analyst-{marker}"},
                json={**analyst_payload, "email": f"changed-{marker}@example.com"},
            )
            assert conflict.status_code == 409
            assert conflict.json()["type"] == "urn:geo:problem:idempotency-conflict"

            second_manager = client.post(
                f"/v1/projects/{project_id}/members",
                headers={**owner_headers, "Idempotency-Key": f"add-admin-{marker}"},
                json=admin_payload,
            )
            assert second_manager.status_code == 201, second_manager.text
            admin_identity_id = UUID(second_manager.json()["member"]["identity_id"])
            dify_approver = dify_project_operator(
                database_url=APP_URL,
                identity_id=admin_identity_id,
                project_id=project_id,
                tenant_id=tenant_id,
                auth_method="dify-enrollment-approver",
                label="approver",
            )
            deepseek_approver = deepseek_project_operator(
                database_url=APP_URL,
                identity_id=admin_identity_id,
                project_id=project_id,
                tenant_id=tenant_id,
                auth_method="operator-bootstrap-approval",
                label="--approved-by",
            )
            assert dify_approver.roles == ("admin",)
            assert deepseek_approver.roles == ("admin",)
            _seed_customer_membership(
                tenant_id=tenant_id,
                project_id=project_id,
                issuer=issuer,
                subject=customer_subject,
                marker=marker,
            )

            listed = client.get(
                f"/v1/projects/{project_id}/members", headers=owner_headers
            )
            assert listed.status_code == 200, listed.text
            assert listed.json()["total"] == 3
            assert {item["role"] for item in listed.json()["items"]} == {
                "owner",
                "admin",
                "analyst",
            }

            current_analyst = client.get("/v1/auth/me", headers=analyst_headers)
            assert current_analyst.status_code == 200, current_analyst.text
            assert current_analyst.json()["actor_id"] == analyst_subject
            assert current_analyst.json()["project_ids"] == [str(project_id)]

            read_project = client.get(
                f"/v1/projects/{project_id}", headers=analyst_headers
            )
            assert read_project.status_code == 200, read_project.text
            edit_content = client.post(
                f"/v1/projects/{project_id}/entities",
                headers=analyst_headers,
                json={
                    "entity_type": "product",
                    "canonical_name": f"Reviewer Product {marker}",
                    "canonical_url": "https://example.com/product",
                    "attributes": {},
                },
            )
            assert edit_content.status_code == 201, edit_content.text

            analyst_cannot_manage = client.get(
                f"/v1/projects/{project_id}/members", headers=analyst_headers
            )
            assert analyst_cannot_manage.status_code == 403
            cross_tenant = client.get(
                f"/v1/projects/{foreign_project_id}/members", headers=owner_headers
            )
            assert cross_tenant.status_code == 403

            admin_cannot_add_owner = client.post(
                f"/v1/projects/{project_id}/members",
                headers={**admin_headers, "Idempotency-Key": f"admin-owner-{marker}"},
                json={
                    "issuer": issuer,
                    "subject": f"forbidden-owner-{marker}",
                    "email": f"forbidden-owner-{marker}@example.com",
                    "display_name": "Forbidden Owner",
                    "role": "owner",
                },
            )
            assert admin_cannot_add_owner.status_code == 403

            owner_membership_id = next(
                item["membership_id"]
                for item in listed.json()["items"]
                if item["role"] == "owner"
            )
            last_owner = client.post(
                f"/v1/projects/{project_id}/members/{owner_membership_id}/revoke",
                headers={**owner_headers, "Idempotency-Key": f"last-owner-{marker}"},
            )
            assert last_owner.status_code == 409
            assert "last active project owner" in last_owner.json()["detail"].lower()

            admin_cannot_revoke_owner = client.post(
                f"/v1/projects/{project_id}/members/{owner_membership_id}/revoke",
                headers={**admin_headers, "Idempotency-Key": f"admin-revoke-owner-{marker}"},
            )
            assert admin_cannot_revoke_owner.status_code == 403

            admin_cannot_change_owner = client.post(
                f"/v1/projects/{project_id}/members/{owner_membership_id}/role",
                headers={**admin_headers, "Idempotency-Key": f"admin-role-owner-{marker}"},
                json={"role": "admin"},
            )
            assert admin_cannot_change_owner.status_code == 403
            last_owner_role = client.post(
                f"/v1/projects/{project_id}/members/{owner_membership_id}/role",
                headers={**owner_headers, "Idempotency-Key": f"last-owner-role-{marker}"},
                json={"role": "admin"},
            )
            assert last_owner_role.status_code == 409
            assert "last active project owner" in last_owner_role.json()["detail"].lower()

            promoted = client.post(
                f"/v1/projects/{project_id}/members/"
                f"{analyst_member['membership_id']}/role",
                headers={**admin_headers, "Idempotency-Key": f"promote-analyst-{marker}"},
                json={"role": "admin"},
            )
            assert promoted.status_code == 200, promoted.text
            assert promoted.json()["member"]["role"] == "admin"
            restored_role = client.post(
                f"/v1/projects/{project_id}/members/"
                f"{analyst_member['membership_id']}/role",
                headers={**owner_headers, "Idempotency-Key": f"restore-analyst-{marker}"},
                json={"role": "analyst"},
            )
            assert restored_role.status_code == 200, restored_role.text
            assert restored_role.json()["member"]["role"] == "analyst"

            revoked = client.post(
                f"/v1/projects/{project_id}/members/"
                f"{analyst_member['membership_id']}/revoke",
                headers={**owner_headers, "Idempotency-Key": f"revoke-analyst-{marker}"},
            )
            assert revoked.status_code == 200, revoked.text
            assert revoked.json()["member"]["status"] == "revoked"
            assert revoked.json()["replayed"] is False
            revoke_replay = client.post(
                f"/v1/projects/{project_id}/members/"
                f"{analyst_member['membership_id']}/revoke",
                headers={**owner_headers, "Idempotency-Key": f"revoke-analyst-{marker}"},
            )
            assert revoke_replay.status_code == 200
            assert revoke_replay.json()["replayed"] is True

            reactivated = client.post(
                f"/v1/projects/{project_id}/members/"
                f"{analyst_member['membership_id']}/reactivate",
                headers={**owner_headers, "Idempotency-Key": f"reactivate-{marker}"},
            )
            assert reactivated.status_code == 200, reactivated.text
            assert reactivated.json()["member"]["status"] == "active"
            assert reactivated.json()["replayed"] is False

            stable_add_replay = client.post(
                f"/v1/projects/{project_id}/members",
                headers={**owner_headers, "Idempotency-Key": f"add-analyst-{marker}"},
                json=analyst_payload,
            )
            assert stable_add_replay.status_code == 201
            assert stable_add_replay.json()["replayed"] is True
            assert stable_add_replay.json()["member"]["role"] == "analyst"
            assert stable_add_replay.json()["member"]["status"] == "active"

        with psycopg.connect(ADMIN_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_type, actor_identity_id, subject_type
                FROM access_audit_events
                WHERE project_id = %s AND event_type IN (
                    'member.added', 'member.revoked',
                    'member.role_changed', 'member.reactivated'
                )
                ORDER BY created_at, id
                """,
                (project_id,),
            )
            audits = cursor.fetchall()
        assert [row[0] for row in audits] == [
            "member.added",
            "member.added",
            "member.role_changed",
            "member.role_changed",
            "member.revoked",
            "member.reactivated",
        ]
        assert [row[1] for row in audits] == [
            owner_id,
            owner_id,
            admin_identity_id,
            owner_id,
            owner_id,
            owner_id,
        ]
        assert all(row[2] == "membership" for row in audits)
    finally:
        _cleanup(
            tenant_ids=(tenant_id, foreign_tenant_id),
            issuer=issuer,
            subjects=(
                owner_subject,
                analyst_subject,
                admin_subject,
                customer_subject,
                f"foreign-{marker}",
            ),
        )


def _seed_customer_membership(
    *, tenant_id: UUID, project_id: UUID, issuer: str, subject: str, marker: str
) -> None:
    with psycopg.connect(ADMIN_URL) as connection:
        identity_id = uuid4()
        connection.execute(
            """INSERT INTO identities (id, issuer, subject, email, display_name)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                identity_id,
                issuer,
                subject,
                f"customer-{marker}@example.com",
                f"Customer {marker}",
            ),
        )
        connection.execute(
            """INSERT INTO project_memberships
                   (tenant_id, project_id, identity_id, role)
               VALUES (%s, %s, %s, 'customer')""",
            (tenant_id, project_id, identity_id),
        )


def _seed(
    *,
    tenant_id: UUID,
    foreign_tenant_id: UUID,
    project_id: UUID,
    foreign_project_id: UUID,
    owner_id: UUID,
    foreign_owner_id: UUID,
    marker: str,
    issuer: str,
    owner_subject: str,
) -> None:
    with psycopg.connect(ADMIN_URL) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s), (%s, %s)",
            (tenant_id, f"Tenant {marker}", foreign_tenant_id, f"Foreign {marker}"),
        )
        cursor.execute(
            """
            INSERT INTO identities (id, issuer, subject, email, display_name)
            VALUES (%s, %s, %s, %s, %s), (%s, %s, %s, %s, %s)
            """,
            (
                owner_id,
                issuer,
                owner_subject,
                f"owner-{marker}@example.com",
                f"Owner {marker}",
                foreign_owner_id,
                issuer,
                f"foreign-{marker}",
                f"foreign-{marker}@example.com",
                f"Foreign {marker}",
            ),
        )
        cursor.execute(
            """
            INSERT INTO projects (id, tenant_id, name)
            VALUES (%s, %s, %s), (%s, %s, %s)
            """,
            (
                project_id,
                tenant_id,
                f"Managed {marker}",
                foreign_project_id,
                foreign_tenant_id,
                f"Foreign {marker}",
            ),
        )
        cursor.execute(
            """
            INSERT INTO project_memberships (tenant_id, project_id, identity_id, role)
            VALUES (%s, %s, %s, 'owner'), (%s, %s, %s, 'owner')
            """,
            (
                tenant_id,
                project_id,
                owner_id,
                foreign_tenant_id,
                foreign_project_id,
                foreign_owner_id,
            ),
        )


def _cleanup(*, tenant_ids: tuple[UUID, ...], issuer: str, subjects: tuple[str, ...]) -> None:
    with psycopg.connect(ADMIN_URL) as connection, connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE access_audit_events DISABLE TRIGGER access_audit_events_append_only"
        )
        cursor.execute(
            "DELETE FROM access_audit_events WHERE tenant_id = ANY(%s::uuid[])",
            (list(tenant_ids),),
        )
        cursor.execute(
            "ALTER TABLE access_audit_events ENABLE TRIGGER access_audit_events_append_only"
        )
        cursor.execute("DELETE FROM tenants WHERE id = ANY(%s::uuid[])", (list(tenant_ids),))
        cursor.execute(
            "DELETE FROM identities WHERE issuer = %s AND subject = ANY(%s::text[])",
            (issuer, list(subjects)),
        )
