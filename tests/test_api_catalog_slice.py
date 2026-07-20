from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from geo_api.app_factory import ApiSettings, create_api_app
from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.catalog.application import CatalogApplication
from geo_core.catalog.domain import (
    BootstrapResult,
    EvidenceItem,
    MarketProfile,
    ProductEntity,
    Project,
)


NOW = datetime(2026, 7, 16, tzinfo=UTC)


class PrincipalServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self.principal = principal

    def authenticate(self, authentication: object) -> AccessPrincipal:
        del authentication
        return self.principal


class Repository:
    def __init__(self) -> None:
        self.projects: dict[UUID, Project] = {}
        self.entities: dict[UUID, ProductEntity] = {}
        self.markets: list[MarketProfile] = []
        self.evidence: list[EvidenceItem] = []

    def create_project(self, *, project_id: UUID, principal: AccessPrincipal, name: str):
        project = Project(project_id, principal.tenant_id, name, "active", NOW, NOW)
        self.projects[project_id] = project
        return project

    def get_project(self, *, project_id: UUID, tenant_id: UUID):
        project = self.projects.get(project_id)
        return project if project and project.tenant_id == tenant_id else None

    def update_project(self, **values: object):
        project = self.projects.get(values["project_id"])
        if project is None:
            return None
        changed = Project(
            project.id,
            project.tenant_id,
            str(values["name"] or project.name),
            str(values["status"] or project.status),
            project.created_at,
            NOW,
        )
        self.projects[project.id] = changed
        return changed

    def create_entity(self, **values: object):
        from geo_core.catalog.domain import EntityType

        entity = ProductEntity(
            uuid4(),
            values["project_id"],
            EntityType(values["entity_type"]),
            str(values["canonical_name"]),
            values["canonical_url"],
            values["attributes"],
            "active",
            NOW,
        )
        self.entities[entity.id] = entity
        return entity

    def list_entities(self, **values: object):
        return tuple(
            item for item in self.entities.values() if item.project_id == values["project_id"]
        )

    def get_entity(self, *, project_id: UUID, entity_id: UUID):
        item = self.entities.get(entity_id)
        return item if item and item.project_id == project_id else None

    def create_evidence(self, *, project_id: UUID, draft: object):
        item = EvidenceItem(uuid4(), project_id, draft, NOW)
        self.evidence.append(item)
        return item

    def list_evidence(self, **values: object):
        return tuple(
            item for item in self.evidence if item.project_id == values["project_id"]
        )

    def list_market_profiles(self, **values: object):
        return tuple(
            item for item in self.markets if item.project_id == values["project_id"]
        )

    def create_market_profile(self, **values: object):
        profile = MarketProfile(
            uuid4(),
            values["project_id"],
            str(values["market_code"]),
            str(values["locale"]),
            str(values["timezone"]),
            values["rules"],
            "active",
            NOW,
        )
        self.markets.append(profile)
        return profile

    def bootstrap_development(self, **values: object):
        project = Project(
            values["project_id"],
            values["tenant_id"],
            str(values["project_name"]),
            "active",
            NOW,
            NOW,
        )
        self.projects[project.id] = project
        return BootstrapResult(values["tenant_id"], values["identity_id"], project)


class UnitOfWork:
    def __init__(self, repository: Repository) -> None:
        self.catalog = repository

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def include_project(self, project_id: UUID) -> None:
        del project_id

    def set_bootstrap_scope(self, **values: object) -> None:
        del values

    def commit(self) -> None:
        return None


def _app(role: str = "owner", *, settings: ApiSettings | None = None):
    tenant_id, identity_id, project_id = uuid4(), uuid4(), uuid4()
    principal = AccessPrincipal(
        identity_id=identity_id,
        actor_id="authenticated-subject",
        tenant_id=tenant_id,
        memberships=(MembershipRecord(project_id, tenant_id, role),),
        auth_method="development",
    )
    repository = Repository()
    repository.projects[project_id] = Project(
        project_id, tenant_id, "Existing", "active", NOW, NOW
    )
    bootstrap_allowed = bool(
        settings
        and settings.dev_tools_enabled
        and settings.deployment_environment != "production"
    )
    application = CatalogApplication(  # type: ignore[arg-type]
        lambda principal=None: UnitOfWork(repository),
        development_bootstrap_allowed=bootstrap_allowed,
    )
    app = create_api_app(
        surface="internal",
        services=PrincipalServices(principal),  # type: ignore[arg-type]
        catalog_application=application,
        settings=settings,
    )
    return app, principal, repository


def test_internal_catalog_uses_principal_and_rejects_payload_actor() -> None:
    app, principal, _ = _app()
    with TestClient(app) as client:
        injected = client.post(
            "/v1/projects", json={"name": "Injected", "actor_id": str(uuid4())}
        )
        created = client.post("/v1/projects", json={"name": "Authenticated project"})

    assert injected.status_code == 422
    assert created.status_code == 201
    assert created.json()["tenant_id"] == str(principal.tenant_id)


def test_evidence_api_returns_fail_closed_eligibility_and_validates_hash() -> None:
    app, principal, _ = _app("analyst")
    project_id = principal.project_ids[0]
    with TestClient(app) as client:
        entity = client.post(
            f"/v1/projects/{project_id}/entities",
            json={"entity_type": "product", "canonical_name": "Product One"},
        ).json()
        text = "Observed product specification"
        payload = {
            "item_type": "citation",
            "source_id": str(uuid4()),
            "subject_entity_id": entity["id"],
            "subject_role": "product",
            "locator": {"page": 1},
            "snapshot": {
                "kind": "text",
                "text": text,
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
            },
            "source_revision": {"kind": "content_hash", "value": "v1"},
            "usage_rights": "unknown",
            "confidentiality": "internal",
        }
        created = client.post(f"/v1/projects/{project_id}/evidence-items", json=payload)
        payload["snapshot"]["sha256"] = "0" * 64
        invalid = client.post(f"/v1/projects/{project_id}/evidence-items", json=payload)

    assert created.status_code == 201
    assert created.json()["eligible_for_generation"] is False
    assert created.json()["eligible_for_publication"] is False
    assert invalid.status_code == 422


def test_generic_evidence_api_rejects_approved_fact_creation() -> None:
    app, principal, _ = _app("analyst")
    project_id = principal.project_ids[0]
    text = "Approved facts require Knowledge lineage"
    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{project_id}/evidence-items",
            json={
                "item_type": "approved_fact",
                "source_id": str(uuid4()),
                "subject_entity_id": None,
                "subject_role": "neutral",
                "locator": {},
                "snapshot": {
                    "kind": "text",
                    "text": text,
                    "sha256": hashlib.sha256(text.encode()).hexdigest(),
                },
                "source_revision": {"kind": "content_hash", "value": "v1"},
                "usage_rights": "owned",
                "confidentiality": "internal",
            },
        )

    assert response.status_code == 422


def test_market_profile_create_and_list_are_project_scoped() -> None:
    app, principal, _ = _app("analyst")
    project_id = principal.project_ids[0]
    with TestClient(app) as client:
        created = client.post(
            f"/v1/projects/{project_id}/market-profiles",
            json={
                "market_code": "au",
                "locale": "en-AU",
                "timezone": "Australia/Sydney",
                "rules": {"language": "English"},
            },
        )
        listed = client.get(f"/v1/projects/{project_id}/market-profiles")

    assert created.status_code == 201
    assert created.json()["market_code"] == "AU"
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [created.json()["id"]]


def test_project_update_requires_owner_or_admin() -> None:
    app, principal, _ = _app("analyst")
    with TestClient(app) as client:
        response = client.patch(
            f"/v1/projects/{principal.project_ids[0]}", json={"name": "No"}
        )

    assert response.status_code == 403


def test_customer_openapi_has_no_catalog_mutations_or_evidence_routes() -> None:
    customer = create_api_app(surface="customer")
    paths = customer.openapi()["paths"]

    assert "post" not in paths["/v1/projects"]
    assert "/v1/projects/{project_id}" not in paths
    assert not any(path.endswith("/entities") for path in paths)
    assert not any(path.endswith("/evidence-items") for path in paths)


def test_dev_bootstrap_route_is_absent_in_production_even_when_flag_is_true() -> None:
    production, _, _ = _app(
        settings=ApiSettings(dev_tools_enabled=True, deployment_environment="production")
    )
    development, _, _ = _app(
        settings=ApiSettings(dev_tools_enabled=True, deployment_environment="development")
    )

    assert "/v1/dev-tools/catalog-bootstrap" not in production.openapi()["paths"]
    assert "/v1/dev-tools/catalog-bootstrap" in development.openapi()["paths"]
    with TestClient(development) as client:
        response = client.post(
            "/v1/dev-tools/catalog-bootstrap",
            json={
                "tenant_name": "Development tenant",
                "identity_subject": "developer@example.com",
                "identity_email": "developer@example.com",
                "project_name": "First project",
            },
        )
    assert response.status_code == 201
    assert response.json()["project"]["name"] == "First project"
