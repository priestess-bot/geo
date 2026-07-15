from __future__ import annotations

import os
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from geo_api.app_factory import ApiSettings, create_api_app
from geo_api.foundation_services import ConnectedFoundationServices
from geo_core.access.postgres import PsycopgAccessUnitOfWorkFactory
from geo_core.access.service import AccessApplicationService


APP_URL = os.getenv("GEO_ACCESS_TEST_DATABASE_URL", "").strip()
ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()
TOKEN_SECRET = "integration-access-token-secret-value-123456789"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not APP_URL or not ADMIN_URL,
        reason="GEO_ACCESS_TEST_DATABASE_URL and GEO_ACCESS_TEST_ADMIN_DATABASE_URL are required",
    ),
]


def test_invitation_lifecycle_preserves_all_memberships_and_session_security() -> None:
    tenant_id = uuid4()
    owner_id = uuid4()
    customer_id = uuid4()
    invited_project = uuid4()
    existing_project = uuid4()
    marker = uuid4().hex[:10]
    customer_email = f"customer-{marker}@example.com"
    _seed(
        tenant_id=tenant_id,
        owner_id=owner_id,
        customer_id=customer_id,
        invited_project=invited_project,
        existing_project=existing_project,
        marker=marker,
        customer_email=customer_email,
    )
    access = AccessApplicationService(
        PsycopgAccessUnitOfWorkFactory(APP_URL), token_secret=TOKEN_SECRET
    )
    internal = create_api_app(
        surface="internal",
        settings=ApiSettings(cookie_secure=False),
        services=ConnectedFoundationServices(access, surface="internal", auth_mode="development"),
    )
    customer = create_api_app(
        surface="customer",
        settings=ApiSettings(cookie_secure=True),
        services=ConnectedFoundationServices(access, surface="customer", auth_mode="session"),
    )
    admin_headers = {
        "X-GEO-Actor-ID": str(owner_id),
        "X-GEO-Tenant-ID": str(tenant_id),
        "Idempotency-Key": f"create-{marker}-0001",
    }
    try:
        with TestClient(internal) as admin_client:
            created = admin_client.post(
                f"/v1/projects/{invited_project}/invitations",
                headers=admin_headers,
                json={
                    "email": customer_email,
                    "role": "analyst",
                    "target_surface": "customer",
                    "expires_in_hours": 24,
                },
            )
            assert created.status_code == 201, created.text
            invitation = created.json()["invitation"]
            invitation_id = invitation["id"]
            invite_token = created.json()["invite_token"]
            assert invite_token not in str(invitation)
            assert created.json()["replayed"] is False

            replayed_creation = admin_client.post(
                f"/v1/projects/{invited_project}/invitations",
                headers=admin_headers,
                json={
                    "email": customer_email,
                    "role": "analyst",
                    "target_surface": "customer",
                    "expires_in_hours": 24,
                },
            )
            assert replayed_creation.status_code == 201
            assert replayed_creation.json()["invite_token"] == invite_token
            assert replayed_creation.json()["replayed"] is True

            listed = admin_client.get(
                f"/v1/projects/{invited_project}/invitations",
                headers={
                    key: value for key, value in admin_headers.items() if key != "Idempotency-Key"
                },
            )
            assert listed.status_code == 200
            assert "invite_token" not in listed.text
            assert listed.json()["items"][0]["status"] == "pending"

            revoked = admin_client.post(
                f"/v1/projects/{invited_project}/invitations",
                headers={**admin_headers, "Idempotency-Key": f"create-{marker}-revoked"},
                json={
                    "email": f"revoked-{marker}@example.com",
                    "role": "viewer",
                    "target_surface": "customer",
                    "expires_in_hours": 24,
                },
            )
            assert revoked.status_code == 201
            revoked_invitation = revoked.json()
            revoked_response = admin_client.post(
                f"/v1/projects/{invited_project}/invitations/"
                f"{revoked_invitation['invitation']['id']}/revoke",
                headers={
                    key: value for key, value in admin_headers.items() if key != "Idempotency-Key"
                },
            )
            assert revoked_response.status_code == 200
            assert revoked_response.json()["status"] == "revoked"

            expiring = admin_client.post(
                f"/v1/projects/{invited_project}/invitations",
                headers={**admin_headers, "Idempotency-Key": f"create-{marker}-expired"},
                json={
                    "email": f"expired-{marker}@example.com",
                    "role": "viewer",
                    "target_surface": "customer",
                    "expires_in_hours": 1,
                },
            )
            assert expiring.status_code == 201
            expired_invitation = expiring.json()
            _expire_invitation(UUID(expired_invitation["invitation"]["id"]))

        credential = {
            "invitation_id": invitation_id,
            "invite_token": invite_token,
            "requested_surface": "admin",
        }
        with TestClient(customer, base_url="https://testserver") as customer_client:
            revoked_preflight = customer_client.post(
                "/v1/auth/invitations/preflight",
                json={
                    "invitation_id": revoked_invitation["invitation"]["id"],
                    "invite_token": revoked_invitation["invite_token"],
                    "requested_surface": "customer",
                },
            )
            assert revoked_preflight.status_code == 200
            assert revoked_preflight.json()["compatibility"] == "invalid"

            expired_preflight = customer_client.post(
                "/v1/auth/invitations/preflight",
                json={
                    "invitation_id": expired_invitation["invitation"]["id"],
                    "invite_token": expired_invitation["invite_token"],
                    "requested_surface": "customer",
                },
            )
            assert expired_preflight.status_code == 200
            assert expired_preflight.json()["compatibility"] == "invalid"

            mismatch = customer_client.post("/v1/auth/invitations/preflight", json=credential)
            assert mismatch.status_code == 200
            assert mismatch.json()["compatibility"] == "surface_mismatch"
            assert mismatch.json()["recommended_surface"] == "customer"

            wrong_redeem = customer_client.post(
                "/v1/auth/invitations/redeem",
                headers={"Idempotency-Key": f"redeem-{marker}-0001"},
                json=credential,
            )
            assert wrong_redeem.status_code == 409
            assert _invitation_status(UUID(invitation_id)) == "pending"

            credential["requested_surface"] = "customer"
            redeemed = customer_client.post(
                "/v1/auth/invitations/redeem",
                headers={"Idempotency-Key": f"redeem-{marker}-0001"},
                json=credential,
            )
            assert redeemed.status_code == 201, redeemed.text
            assert redeemed.json()["recovery_status"] == "created"
            assert set(redeemed.json()["session"]["project_ids"]) == {
                str(invited_project),
                str(existing_project),
            }
            assert set(redeemed.json()["session"]["roles"]) == {"analyst", "viewer"}
            session_token = redeemed.cookies["GEO_CUSTOMER_SESSION"]
            csrf_token = redeemed.cookies["GEO_CSRF_TOKEN"]
            assert "HttpOnly" in redeemed.headers["set-cookie"]
            assert "SameSite=lax" in redeemed.headers["set-cookie"]
            assert "Secure" in redeemed.headers["set-cookie"]

            idempotent_replay = customer_client.post(
                "/v1/auth/invitations/redeem",
                headers={"Idempotency-Key": f"redeem-{marker}-0001"},
                json=credential,
            )
            assert idempotent_replay.status_code == 201
            assert idempotent_replay.json()["recovery_status"] == "replayed"
            assert idempotent_replay.cookies["GEO_CUSTOMER_SESSION"] == session_token

            replay_preflight = customer_client.post(
                "/v1/auth/invitations/preflight", json=credential
            )
            assert replay_preflight.status_code == 200
            assert replay_preflight.json()["compatibility"] == "compatible"

            projects = customer_client.get("/v1/projects")
            assert projects.status_code == 200
            assert {item["project_id"] for item in projects.json()["items"]} == {
                str(invited_project),
                str(existing_project),
            }

            rejected_logout = customer_client.post("/v1/auth/logout")
            assert rejected_logout.status_code == 403
            accepted_logout = customer_client.post(
                "/v1/auth/logout", headers={"X-GEO-CSRF-Token": csrf_token}
            )
            assert accepted_logout.status_code == 200
            customer_client.cookies.set("GEO_CUSTOMER_SESSION", session_token)
            assert customer_client.get("/v1/auth/me").status_code == 401

        assert _invitation_status(UUID(invitation_id)) == "redeemed"
        assert _audit_types(UUID(invitation_id)) >= {
            "invitation.created",
            "invitation.preflight_failed",
            "invitation.redeemed",
            "session.created",
            "session.revoked",
        }
        with TestClient(customer, base_url="https://testserver") as customer_client:
            assert (
                customer_client.get(f"/v1/projects/{invited_project}/invitations").status_code
                == 404
            )
    finally:
        _cleanup(tenant_id, owner_id, customer_id)


def _seed(
    *,
    tenant_id: UUID,
    owner_id: UUID,
    customer_id: UUID,
    invited_project: UUID,
    existing_project: UUID,
    marker: str,
    customer_email: str,
) -> None:
    with psycopg.connect(ADMIN_URL) as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO tenants (id, name) VALUES (%s, %s)", (tenant_id, marker))
        cursor.execute(
            "INSERT INTO identities (id, issuer, subject, email) VALUES (%s, 'oidc', %s, %s)",
            (owner_id, f"owner-{marker}", f"owner-{marker}@example.com"),
        )
        cursor.execute(
            """
            INSERT INTO identities (id, issuer, subject, email)
            VALUES (%s, 'geo:customer', %s, %s)
            """,
            (customer_id, customer_email, customer_email),
        )
        for project_id, name in ((invited_project, "Invited"), (existing_project, "Existing")):
            cursor.execute(
                "INSERT INTO projects (id, tenant_id, name) VALUES (%s, %s, %s)",
                (project_id, tenant_id, f"{name} {marker}"),
            )
        cursor.execute(
            """
            INSERT INTO project_memberships (tenant_id, project_id, identity_id, role)
            VALUES (%s, %s, %s, 'owner'), (%s, %s, %s, 'owner'),
                   (%s, %s, %s, 'viewer')
            """,
            (
                tenant_id,
                invited_project,
                owner_id,
                tenant_id,
                existing_project,
                owner_id,
                tenant_id,
                existing_project,
                customer_id,
            ),
        )


def _invitation_status(invitation_id: UUID) -> str:
    with psycopg.connect(ADMIN_URL) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT status FROM project_invitations WHERE id = %s", (invitation_id,))
        return str(cursor.fetchone()[0])


def _audit_types(invitation_id: UUID) -> set[str]:
    with psycopg.connect(ADMIN_URL) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT event_type FROM access_audit_events
            WHERE subject_id = %s OR event_type LIKE %s
            """,
            (invitation_id, "session.%"),
        )
        return {str(row[0]) for row in cursor.fetchall()}


def _expire_invitation(invitation_id: UUID) -> None:
    with psycopg.connect(ADMIN_URL) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE project_invitations SET expires_at = now() - interval '1 minute' "
            "WHERE id = %s",
            (invitation_id,),
        )


def _cleanup(tenant_id: UUID, owner_id: UUID, customer_id: UUID) -> None:
    with psycopg.connect(ADMIN_URL) as connection, connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE access_audit_events DISABLE TRIGGER access_audit_events_append_only"
        )
        cursor.execute("DELETE FROM access_audit_events WHERE tenant_id = %s", (tenant_id,))
        cursor.execute(
            "ALTER TABLE access_audit_events ENABLE TRIGGER access_audit_events_append_only"
        )
        cursor.execute(
            "DELETE FROM invitation_redemptions WHERE project_id IN "
            "(SELECT id FROM projects WHERE tenant_id = %s)",
            (tenant_id,),
        )
        cursor.execute("DELETE FROM customer_sessions WHERE tenant_id = %s", (tenant_id,))
        cursor.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        cursor.execute("DELETE FROM identities WHERE id IN (%s, %s)", (owner_id, customer_id))
