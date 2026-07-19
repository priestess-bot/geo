from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from geo_api.app_factory import create_api_app
from geo_api.foundation_services import (
    ConnectedFoundationServices,
    UnavailableFoundationServices,
    resolve_services_from_environment,
    services_from_environment,
)
from geo_core.access.models import (
    AccessPrincipal,
    AuthenticationRequired,
    JobRecord,
    MembershipRecord,
    Page,
    ProjectRecord,
)


class StubAccessApplication:
    def __init__(self) -> None:
        self.identity_id = uuid4()
        self.tenant_id = uuid4()
        self.project_ids = (uuid4(), uuid4())
        self.session_id = uuid4()
        self.principal = AccessPrincipal(
            identity_id=self.identity_id,
            actor_id="subject-1",
            tenant_id=self.tenant_id,
            memberships=(
                MembershipRecord(
                    project_id=self.project_ids[0], tenant_id=self.tenant_id, role="customer"
                ),
                MembershipRecord(
                    project_id=self.project_ids[1], tenant_id=self.tenant_id, role="viewer"
                ),
            ),
            auth_method="session",
            session_id=self.session_id,
        )
        self.projects = (
            ProjectRecord(
                id=self.project_ids[0],
                name="Public Project A",
                status="active",
                role="customer",
                market_code="AU",
            ),
            ProjectRecord(
                id=self.project_ids[1],
                name="Public Project B",
                status="paused",
                role="viewer",
                market_code="NZ",
            ),
        )
        now = datetime.now(UTC)
        self.job = JobRecord(
            id=uuid4(),
            kind="collection",
            status="queued",
            created_at=now,
            updated_at=now,
            result_ref=None,
            error_code=None,
        )
        self.revoked = False

    def authenticate_customer_session(self, *, raw_token: str) -> AccessPrincipal:
        if raw_token != "valid-customer-session":
            raise AuthenticationRequired("A customer session is required.")
        return self.principal

    def authenticate_development(self, *, identity_id: UUID, tenant_id: UUID) -> AccessPrincipal:
        if (identity_id, tenant_id) != (self.identity_id, self.tenant_id):
            raise AuthenticationRequired("Development authentication headers are required.")
        return self.principal

    def authenticate_external(self, external: object) -> AccessPrincipal:
        del external
        return self.principal

    def list_projects(self, principal: AccessPrincipal, *, limit: int, offset: int) -> Page:
        assert principal == self.principal
        return Page(
            items=self.projects[offset : offset + limit],
            total=len(self.projects),
            limit=limit,
            offset=offset,
        )

    def list_jobs(self, principal: AccessPrincipal, *, limit: int, offset: int) -> Page:
        assert principal == self.principal
        return Page(items=(self.job,), total=1, limit=limit, offset=offset)

    def get_job(self, principal: AccessPrincipal, *, job_id: UUID) -> JobRecord | None:
        assert principal == self.principal
        return self.job if job_id == self.job.id else None

    def logout(self, principal: AccessPrincipal) -> None:
        assert principal == self.principal
        self.revoked = True

    def logout_customer_session(self, *, raw_token: str, csrf_token: str) -> None:
        assert raw_token == "valid-customer-session"
        assert csrf_token == "valid-csrf"
        self.revoked = True


def _customer_app(access: StubAccessApplication) -> object:
    services = ConnectedFoundationServices(
        access,  # type: ignore[arg-type]
        surface="customer",
        auth_mode="session",
    )
    return create_api_app(surface="customer", services=services)


def _internal_app(access: StubAccessApplication) -> object:
    services = ConnectedFoundationServices(
        access,  # type: ignore[arg-type]
        surface="internal",
        auth_mode="development",
    )
    return create_api_app(surface="internal", services=services)


def test_customer_session_returns_all_projects_using_customer_dto() -> None:
    access = StubAccessApplication()
    with TestClient(_customer_app(access)) as client:
        client.cookies.set("GEO_CUSTOMER_SESSION", "valid-customer-session")
        response = client.get("/v1/projects")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "project_id": str(access.project_ids[0]),
                "display_name": "Public Project A",
                "market_code": "AU",
                "role": "customer",
                "status": "active",
            },
            {
                "project_id": str(access.project_ids[1]),
                "display_name": "Public Project B",
                "market_code": "NZ",
                "role": "viewer",
                "status": "paused",
            },
        ],
        "total": 2,
        "limit": 50,
        "offset": 0,
    }
    assert [item["role"] for item in response.json()["items"]] == ["customer", "viewer"]


def test_customer_surface_rejects_development_headers_without_session() -> None:
    access = StubAccessApplication()
    with TestClient(_customer_app(access)) as client:
        response = client.get(
            "/v1/projects",
            headers={
                "X-GEO-Actor-ID": str(access.identity_id),
                "X-GEO-Tenant-ID": str(access.tenant_id),
            },
        )

    assert response.status_code == 401
    assert response.json()["type"] == "urn:geo:problem:authentication-required"


def test_internal_development_mode_requires_both_explicit_headers() -> None:
    access = StubAccessApplication()
    with TestClient(_internal_app(access)) as client:
        missing = client.get("/v1/projects")
        allowed = client.get(
            "/v1/projects",
            headers={
                "X-GEO-Actor-ID": str(access.identity_id),
                "X-GEO-Tenant-ID": str(access.tenant_id),
            },
        )

    assert missing.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["items"][0]["role"] == "customer"
    assert "display_name" not in allowed.text


def test_internal_jobs_use_full_scope_and_customer_does_not_expose_jobs() -> None:
    access = StubAccessApplication()
    with TestClient(_internal_app(access)) as internal:
        headers = {
            "X-GEO-Actor-ID": str(access.identity_id),
            "X-GEO-Tenant-ID": str(access.tenant_id),
        }
        identity = internal.get("/v1/auth/me", headers=headers)
        jobs = internal.get("/v1/jobs", headers=headers)
        job = internal.get(f"/v1/jobs/{access.job.id}", headers=headers)

    assert identity.status_code == jobs.status_code == job.status_code == 200
    assert identity.json()["project_ids"] == [str(value) for value in access.project_ids]
    assert jobs.json()["items"][0]["id"] == str(access.job.id)

    with TestClient(_customer_app(access)) as customer:
        customer.cookies.set("GEO_CUSTOMER_SESSION", "valid-customer-session")
        assert customer.get("/v1/jobs").status_code == 404
        assert customer.get(f"/v1/jobs/{access.job.id}").status_code == 404


def test_customer_logout_revokes_session_and_expires_cookie() -> None:
    access = StubAccessApplication()
    with TestClient(_customer_app(access)) as client:
        client.cookies.set("GEO_CUSTOMER_SESSION", "valid-customer-session")
        client.cookies.set("GEO_CSRF_TOKEN", "valid-csrf")
        response = client.post("/v1/auth/logout", headers={"X-GEO-CSRF-Token": "valid-csrf"})

    assert response.status_code == 200
    assert access.revoked
    assert "GEO_CUSTOMER_SESSION=" in response.headers["set-cookie"]


def test_customer_and_internal_openapi_use_distinct_project_contracts() -> None:
    access = StubAccessApplication()
    customer_schema = _customer_app(access).openapi()  # type: ignore[attr-defined]
    internal_schema = _internal_app(access).openapi()  # type: ignore[attr-defined]

    customer_ref = customer_schema["paths"]["/v1/projects"]["get"]["responses"]["200"]
    internal_ref = internal_schema["paths"]["/v1/projects"]["get"]["responses"]["200"]
    assert "CustomerProjectSummary" in str(customer_ref)
    assert "ProjectSummary" in str(internal_ref)
    assert "CustomerProjectSummary" not in str(internal_ref)
    customer_contract = customer_schema["components"]["schemas"]["CustomerProjectSummary"]
    assert "role" in customer_contract["required"]


def test_header_development_auth_is_explicit_and_forbidden_in_production(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEO_DATABASE_URL", "postgresql://geo:secret@database.invalid/geo")
    monkeypatch.setenv("GEO_AUTH_TOKEN_SECRET", "access-signing-secret-at-least-32-bytes")
    monkeypatch.setenv("GEO_AUTH_MODE", "development")
    monkeypatch.setenv("GEO_DEPLOYMENT_ENVIRONMENT", "development")
    development = services_from_environment(surface="internal")

    monkeypatch.setenv("GEO_DEPLOYMENT_ENVIRONMENT", "production")
    production = services_from_environment(surface="internal")

    assert isinstance(development, ConnectedFoundationServices)
    assert isinstance(production, UnavailableFoundationServices)


def test_access_resolution_keeps_read_only_service_but_fails_readiness_for_short_secret() -> None:
    resolution = resolve_services_from_environment(
        surface="customer",
        environment={
            "GEO_DATABASE_URL": "postgresql://geo:secret@database.invalid/geo",
            "GEO_AUTH_TOKEN_SECRET": "too-short",
        },
    )

    assert isinstance(resolution.services, ConnectedFoundationServices)
    assert resolution.access_configured is False
