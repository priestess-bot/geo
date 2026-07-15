from geo_api.app_factory import create_api_app
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.placements.domain import Campaign, Opportunity


def test_placement_routes_are_stable_and_internal_only() -> None:
    internal = create_api_app(surface="internal").openapi()["paths"]
    customer = create_api_app(surface="customer").openapi()["paths"]
    expected = {
        "/v1/projects/{project_id}/geo/campaigns",
        "/v1/projects/{project_id}/geo/campaigns/{campaign_id}/monitoring-queries",
        "/v1/projects/{project_id}/geo/destinations",
        "/v1/projects/{project_id}/geo/campaigns/{campaign_id}/opportunities",
        "/v1/projects/{project_id}/geo/opportunities/{opportunity_id}/brief-versions",
        "/v1/projects/{project_id}/geo/brief-versions/{brief_version_id}/evidence-pack-attempts",
        "/v1/projects/{project_id}/geo/prompt-skills/{skill_id}/releases",
        "/v1/projects/{project_id}/geo/brief-versions/{brief_version_id}/prompt-bundles",
        "/v1/projects/{project_id}/geo/prompt-bundles/{prompt_bundle_id}/generation-jobs",
        "/v1/projects/{project_id}/geo/opportunities/{opportunity_id}/package-versions",
        "/v1/projects/{project_id}/geo/package-versions/{version_id}/claims",
        "/v1/projects/{project_id}/geo/package-versions/{version_id}/reviews",
        "/v1/projects/{project_id}/geo/package-versions/{version_id}/publication-requests",
        "/v1/projects/{project_id}/geo/publication-requests/{publication_request_id}/submissions",
        "/v1/projects/{project_id}/geo/submissions/{submission_id}/verification-jobs",
        "/v1/projects/{project_id}/geo/submissions/{submission_id}/measurements",
    }
    assert expected <= set(internal)
    assert not any("/geo/" in path for path in customer)
    assert not any(
        term in path for path in internal for term in ("runtime", "p0a", "p0b", "fixture")
    )


def test_generation_and_publication_require_idempotency_header() -> None:
    document = create_api_app(surface="internal").openapi()
    paths = (
        "/v1/projects/{project_id}/geo/prompt-bundles/{prompt_bundle_id}/generation-jobs",
        "/v1/projects/{project_id}/geo/package-versions/{version_id}/publication-requests",
        "/v1/projects/{project_id}/geo/submissions/{submission_id}/verification-jobs",
    )
    for path in paths:
        parameters = document["paths"][path]["post"]["parameters"]
        header = next(item for item in parameters if item["name"] == "Idempotency-Key")
        assert header["required"] is True


def test_export_is_not_a_publication_operation() -> None:
    document = create_api_app(surface="internal").openapi()["paths"]
    export_path = "/v1/projects/{project_id}/geo/package-versions/{version_id}/exports"
    publication_path = (
        "/v1/projects/{project_id}/geo/package-versions/{version_id}/publication-requests"
    )
    assert document[export_path]["post"]["operationId"] == "exportPlacementPackageVersion"
    assert document[publication_path]["post"]["operationId"] == "requestPlacementPublication"


def test_placement_slice_has_no_legacy_dependency_and_respects_file_budget() -> None:
    roots = (Path("packages/geo_core/geo_core/placements"), Path("apps/api/geo_api"))
    files = list(roots[0].glob("*.py")) + list(roots[1].glob("placement_*.py"))
    forbidden = (
        "geo_api.main",
        "geo_core.geo_placement",
        "from scripts",
        "import scripts",
        "from workers",
        "import workers",
        "content_drafts",
    )
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= 600, path
        assert not any(term in source for term in forbidden), path


def test_api_worker_image_does_not_copy_legacy_workers_or_scripts() -> None:
    dockerfile = Path("apps/api/Dockerfile").read_text(encoding="utf-8")
    assert "COPY workers" not in dockerfile
    assert "COPY scripts" not in dockerfile
    assert "COPY apps/api ./apps/api" in dockerfile
    assert "COPY packages/geo_core ./packages/geo_core" in dockerfile


class _AccessServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self.principal = principal

    def authenticate(self, authentication):
        del authentication
        return self.principal


class _PlacementServices:
    def __init__(self) -> None:
        self.actor_id = None

    def create_campaign(self, **values):
        self.actor_id = values["actor_id"]
        campaign = Campaign(
            uuid4(),
            values["project_id"],
            values["market_profile_id"],
            values["primary_product_entity_id"],
            values["name"],
            values["objective"],
        )
        opportunity = Opportunity(
            uuid4(),
            values["project_id"],
            campaign.id,
            values["destination_ids"][0],
            "destination:test",
            values["rationale"],
        )
        return campaign, (opportunity,)


def _principal(project_id, role: str) -> AccessPrincipal:
    identity_id, tenant_id = uuid4(), uuid4()
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id="subject",
        tenant_id=tenant_id,
        memberships=(MembershipRecord(project_id, tenant_id, role),),
        auth_method="development",
    )


def test_project_role_dependency_blocks_cross_project_and_viewer_commands() -> None:
    allowed_project, other_project = uuid4(), uuid4()
    payload = {
        "market_profile_id": str(uuid4()),
        "primary_product_entity_id": str(uuid4()),
        "name": "Campaign",
        "destination_ids": [str(uuid4())],
        "opportunity_rationale": "Audience fit",
    }
    for project_id, role in ((other_project, "admin"), (allowed_project, "viewer")):
        placement = _PlacementServices()
        app = create_api_app(
            surface="internal",
            services=_AccessServices(_principal(allowed_project, role)),
            placement_services=placement,
        )
        with TestClient(app) as client:
            response = client.post(f"/v1/projects/{project_id}/geo/campaigns", json=payload)
        assert response.status_code == 403
        assert placement.actor_id is None


def test_command_identity_is_derived_from_principal_and_actor_fields_are_forbidden() -> None:
    project_id = uuid4()
    principal = _principal(project_id, "analyst")
    placement = _PlacementServices()
    app = create_api_app(
        surface="internal", services=_AccessServices(principal), placement_services=placement
    )
    payload = {
        "market_profile_id": str(uuid4()),
        "primary_product_entity_id": str(uuid4()),
        "name": "Campaign",
        "destination_ids": [str(uuid4())],
        "opportunity_rationale": "Audience fit",
    }
    with TestClient(app) as client:
        response = client.post(f"/v1/projects/{project_id}/geo/campaigns", json=payload)
        forged = client.post(
            f"/v1/projects/{project_id}/geo/campaigns",
            json={**payload, "actor_id": str(uuid4())},
        )
    assert response.status_code == 201
    assert placement.actor_id == principal.identity_id
    assert forged.status_code == 422
    schemas = app.openapi()["components"]["schemas"]
    forbidden = {
        "actor_id",
        "requested_by",
        "edited_by",
        "submitted_for_review_by",
        "reviewer_id",
    }
    for name in ("CampaignCreate", "BriefVersionCreate", "PackageEdit", "ReviewCreate"):
        assert forbidden.isdisjoint(schemas[name].get("properties", {}))
