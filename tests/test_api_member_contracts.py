from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from geo_api.app_factory import create_api_app


def test_membership_routes_are_internal_only_and_actor_is_not_a_request_field() -> None:
    internal = create_api_app(surface="internal")
    customer = create_api_app(surface="customer")
    path = "/v1/projects/{project_id}/members"

    assert path in internal.openapi()["paths"]
    assert path not in customer.openapi()["paths"]
    assert f"{path}/{{membership_id}}/revoke" not in customer.openapi()["paths"]

    with TestClient(internal) as client:
        response = client.post(
            f"/v1/projects/{uuid4()}/members",
            headers={"Idempotency-Key": "member-contract-0001"},
            json={
                "issuer": "https://identity.example.com/",
                "subject": "managed-user",
                "email": "managed@example.com",
                "display_name": "Managed User",
                "role": "analyst",
                "actor": str(uuid4()),
            },
        )

    assert response.status_code == 422
    assert response.json()["type"] == "urn:geo:problem:validation-error"


def test_membership_contract_rejects_customer_roles_and_non_https_issuers() -> None:
    app = create_api_app(surface="internal")
    project_id = uuid4()
    base = {
        "issuer": "https://identity.example.com/",
        "subject": "managed-user",
        "email": "managed@example.com",
        "display_name": "Managed User",
        "role": "analyst",
    }

    with TestClient(app) as client:
        customer_role = client.post(
            f"/v1/projects/{project_id}/members",
            headers={"Idempotency-Key": "member-contract-role"},
            json={**base, "role": "customer"},
        )
        insecure_issuer = client.post(
            f"/v1/projects/{project_id}/members",
            headers={"Idempotency-Key": "member-contract-http"},
            json={**base, "issuer": "http://identity.example.com/"},
        )
        userinfo_issuer = client.post(
            f"/v1/projects/{project_id}/members",
            headers={"Idempotency-Key": "member-contract-userinfo"},
            json={**base, "issuer": "https://user:password@identity.example.com/"},
        )

    assert customer_role.status_code == 422
    assert insecure_issuer.status_code == 422
    assert userinfo_issuer.status_code == 422
