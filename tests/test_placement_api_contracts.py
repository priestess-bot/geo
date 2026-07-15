from geo_api.app_factory import create_api_app
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.placements.domain import (
    Campaign,
    Opportunity,
    PlacementConflict,
    PlacementNotFound,
    PromptReleaseView,
    Submission,
)


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
        "/v1/projects/{project_id}/geo/prompt-catalog/defaults",
        "/v1/projects/{project_id}/geo/brief-versions/{brief_version_id}/prompt-bundles",
        "/v1/projects/{project_id}/geo/prompt-bundles/{prompt_bundle_id}/generation-jobs",
        "/v1/projects/{project_id}/geo/opportunities/{opportunity_id}/package-versions",
        "/v1/projects/{project_id}/geo/package-versions/{version_id}/claims",
        "/v1/projects/{project_id}/geo/package-versions/{version_id}/reviews",
        "/v1/projects/{project_id}/geo/package-versions/{version_id}/publication-requests",
        "/v1/projects/{project_id}/geo/publication-requests/{publication_request_id}/submissions",
        "/v1/projects/{project_id}/geo/submissions/{submission_id}/verification-jobs",
        "/v1/projects/{project_id}/geo/submissions/{submission_id}/measurements",
        "/v1/projects/{project_id}/geo/measurement-collection-tasks",
        "/v1/projects/{project_id}/geo/measurement-collection-tasks/{task_id}/complete",
        "/v1/projects/{project_id}/geo/measurement-collection-tasks/{task_id}/cancel",
    }
    assert expected <= set(internal)
    assert expected.isdisjoint(customer)
    assert {
        "/v1/projects/{project_id}/geo/summary",
        "/v1/projects/{project_id}/geo/verified-urls",
        "/v1/projects/{project_id}/geo/metrics",
        "/v1/projects/{project_id}/geo/measurement-windows",
        "/v1/projects/{project_id}/geo/reports",
    } <= set(customer)
    assert not any(
        term in path for path in internal for term in ("runtime", "p0a", "p0b", "fixture")
    )


def test_generation_and_publication_require_idempotency_header() -> None:
    document = create_api_app(surface="internal").openapi()
    paths = (
        "/v1/projects/{project_id}/geo/prompt-bundles/{prompt_bundle_id}/generation-jobs",
        "/v1/projects/{project_id}/geo/package-versions/{version_id}/publication-requests",
        "/v1/projects/{project_id}/geo/submissions/{submission_id}/verification-jobs",
        "/v1/projects/{project_id}/geo/publication-requests/{publication_request_id}/submissions",
    )
    for path in paths:
        parameters = document["paths"][path]["post"]["parameters"]
        header = next(item for item in parameters if item["name"] == "Idempotency-Key")
        assert header["required"] is True


def test_prompt_release_contract_exposes_the_complete_executable_snapshot() -> None:
    schemas = create_api_app(surface="internal").openapi()["components"]["schemas"]
    create = schemas["PromptReleaseCreate"]
    view = schemas["PromptReleaseView"]
    assert {"source", "system_template", "user_template", "output_schema"} <= set(
        create["required"]
    )
    assert {
        "source_text",
        "system_template",
        "user_template",
        "variable_schema",
        "output_schema",
        "compiler_version",
        "release_hash",
    } <= set(view["required"])
    generation = schemas["GenerationCreate"]["properties"]
    assert generation["configured_model"]["default"] == "deepseek-v4-flash"
    assert generation["model_call_budget"]["default"] == 2
    assert generation["model_call_budget"]["maximum"] == 5


def test_export_is_not_a_publication_operation() -> None:
    document = create_api_app(surface="internal").openapi()["paths"]
    export_path = "/v1/projects/{project_id}/geo/package-versions/{version_id}/exports"
    publication_path = (
        "/v1/projects/{project_id}/geo/package-versions/{version_id}/publication-requests"
    )
    assert document[export_path]["post"]["operationId"] == "exportPlacementPackageVersion"
    assert document[publication_path]["post"]["operationId"] == "requestPlacementPublication"


def test_manual_package_edit_requires_a_non_empty_claim_inventory() -> None:
    document = create_api_app(surface="internal").openapi()
    package_edit = document["components"]["schemas"]["PackageEdit"]
    assert "claims" in package_edit["required"]
    assert package_edit["properties"]["claims"]["minItems"] == 1


def test_placement_state_and_missing_resource_use_public_problem_contracts() -> None:
    app = create_api_app(surface="internal")

    @app.get("/_test/placement-conflict")
    def conflict() -> None:
        raise PlacementConflict("invalid transition")

    @app.get("/_test/placement-missing")
    def missing() -> None:
        raise PlacementNotFound("missing package")

    with TestClient(app) as client:
        conflict_response = client.get("/_test/placement-conflict")
        missing_response = client.get("/_test/placement-missing")
    assert conflict_response.status_code == 409
    assert conflict_response.json()["type"] == "urn:geo:problem:placement-state-conflict"
    assert missing_response.status_code == 404
    assert missing_response.json()["type"] == "urn:geo:problem:placement-not-found"


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
    assert "COPY scripts ./scripts" not in dockerfile
    assert "scripts/provision_dev_database.py scripts/provision_initial_owner.py" in dockerfile
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
        self.submission_values = None

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

    def create_submission(self, **values):
        self.submission_values = values
        return Submission(
            id=uuid4(),
            project_id=values["project_id"],
            publication_request_id=values["publication_request_id"],
            status="awaiting_url",
            idempotency_key=values["idempotency_key"],
            submitted_by=values["submitted_by"],
        )


class _PromptPlacementServices:
    def __init__(self) -> None:
        self.values = None

    def publish_skill_version(self, **values):
        self.values = values
        return PromptReleaseView(
            uuid4(), values["project_id"], uuid4(), 1, "a" * 64,
            values["source"], values["system_template"], values["user_template"],
            {"required": ["brief", "evidence", "destination_policy"]},
            values["output_schema"], "geo-prompt-compiler-v1",
        )


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


def test_submission_requires_idempotency_and_uses_authenticated_actor() -> None:
    project_id = uuid4()
    principal = _principal(project_id, "admin")
    placement = _PlacementServices()
    app = create_api_app(
        surface="internal", services=_AccessServices(principal), placement_services=placement
    )
    path = f"/v1/projects/{project_id}/geo/publication-requests/{uuid4()}/submissions"
    with TestClient(app) as client:
        missing = client.post(path, json={})
        created = client.post(
            path, json={}, headers={"Idempotency-Key": "submission-contract-0001"}
        )
    assert missing.status_code == 422
    assert created.status_code == 201
    assert placement.submission_values["submitted_by"] == principal.identity_id
    assert placement.submission_values["idempotency_key"] == "submission-contract-0001"


def test_prompt_release_endpoint_publishes_the_submitted_system_and_user_templates() -> None:
    project_id, skill_id = uuid4(), uuid4()
    placement = _PromptPlacementServices()
    principal = _principal(project_id, "admin")
    app = create_api_app(
        surface="internal",
        services=_AccessServices(principal),
        placement_services=placement,
    )
    payload = {
        "source": "Auditable source",
        "system_template": "Published system instruction",
        "user_template": "{{brief}} {{evidence}} {{destination_policy}}",
        "output_schema": {"type": "object"},
        "client_variable_names": [],
    }
    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{project_id}/geo/prompt-skills/{skill_id}/releases",
            json=payload,
        )

    assert response.status_code == 201, response.text
    assert response.json()["source_text"] == payload["source"]
    assert response.json()["system_template"] == payload["system_template"]
    assert response.json()["user_template"] == payload["user_template"]
    assert placement.values["actor_id"] == principal.identity_id
