from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from geo_api import recommendation_runtime
from geo_api.app_factory import create_api_app
from geo_api.recommendation_runtime import memory_recommendation_api
from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.recommendations import (
    ContentRef,
    AttributionRef,
    FactRef,
    InMemoryRecommendationStore,
    MetricComparisonRef,
    ModelCallRef,
    ObservationEvidenceClass,
    ObservationRef,
    PromptReleaseRef,
    QuestionRef,
    RecommendationApplication,
    RecommendationDecision,
    RecommendationEvidenceGraph,
    RecommendationForbidden,
    RecommendationNotFound,
    RecommendationPersistenceError,
    RecommendationRuleViolation,
    RecommendationScope,
    RecommendationVersionConflict,
    RuleRef,
    SurfaceRef,
)
from geo_core.recommendations.generation_contracts import (
    GenerationExecution,
    RecommendationGenerationJob,
    idempotency_hash,
)
from tests.unit.recommendations.generation_test_support import generation_spec


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("20000000-0000-0000-0000-000000000002")


class PrincipalServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self.principal = principal

    def authenticate(self, authentication: object) -> AccessPrincipal:
        del authentication
        return self.principal


class RaisingRecommendationApi:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def create_recommendation(self, principal: AccessPrincipal, **values: object):
        del principal, values
        raise self.error


class GenerationApiStub:
    def __init__(self) -> None:
        spec = generation_spec()
        self.job = RecommendationGenerationJob(
            id=uuid4(),
            spec=spec,
            input_hash=spec.input_hash,
            idempotency_key_hash=idempotency_hash("generation:api"),
        )
        self.selection = None

    def enqueue_generation_job(
        self, principal: AccessPrincipal, *, selection, idempotency_key: str
    ) -> GenerationExecution:
        del principal, idempotency_key
        self.selection = selection
        return GenerationExecution(self.job, None)


def test_recommendation_openapi_is_internal_strict_and_draft_only() -> None:
    internal = create_api_app(surface="internal", recommendation_api=object()).openapi()
    customer = create_api_app(surface="customer", recommendation_api=object()).openapi()
    prefix = "/v1/projects/{project_id}/recommendations"
    expected = {
        prefix,
        f"{prefix}/{{recommendation_id}}",
        f"{prefix}/{{recommendation_id}}/submit",
        f"{prefix}/{{recommendation_id}}/review",
        f"{prefix}/{{recommendation_id}}/approve",
        f"{prefix}/{{recommendation_id}}/reject",
        f"{prefix}/{{recommendation_id}}/expire",
        f"{prefix}/{{recommendation_id}}/reconcile-stale",
        f"{prefix}/{{recommendation_id}}/drafts/{{draft_id}}/prepare-action",
        f"{prefix}/generation-jobs",
        f"{prefix}/generation-jobs/{{job_id}}",
        f"{prefix}/generation-jobs/{{job_id}}/cancel",
    }

    assert expected <= set(internal["paths"])
    assert expected.isdisjoint(customer["paths"])
    operations = {
        operation["operationId"]
        for path in expected
        for method, operation in internal["paths"][path].items()
        if method in {"get", "post"}
    }
    assert operations == {
        "createRecommendation",
        "listRecommendations",
        "getRecommendation",
        "submitRecommendation",
        "reviewRecommendation",
        "approveRecommendation",
        "rejectRecommendation",
        "expireRecommendation",
        "reconcileStaleRecommendation",
        "prepareRecommendationDraftAction",
        "enqueueRecommendationGenerationJob",
        "getRecommendationGenerationJob",
        "cancelRecommendationGenerationJob",
    }
    assert not any("execute" in operation.lower() for operation in operations)
    assert not any("publish" in operation.lower() for operation in operations)

    schemas = internal["components"]["schemas"]
    assert schemas["EvidenceGraphContract"]["additionalProperties"] is False
    assert schemas["ObservationRefContract"]["additionalProperties"] is False
    assert schemas["CreateRecommendationRequest"]["additionalProperties"] is False
    selector_fields = schemas["EvidenceSelectorContract"]["properties"]
    assert set(selector_fields) == {"kind", "resource_id"}
    for path in expected:
        operation = internal["paths"][path].get("post")
        if operation is None:
            continue
        idempotency = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "Idempotency-Key"
        )
        assert idempotency["required"] is True
        request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
        schema_name = request_schema["$ref"].rsplit("/", 1)[-1]
        if schema_name != "EnqueueRecommendationGenerationRequest":
            assert "expected_version" in schemas[schema_name]["required"]
    assert not any("lease" in operation.lower() for operation in operations)
    generation_request = schemas["EnqueueRecommendationGenerationRequest"]
    assert generation_request["additionalProperties"] is False
    assert "evidence" not in generation_request["properties"]
    assert set(schemas["GenerationModelSelectorContract"]["properties"]) == {
        "runtime_selection_id",
        "search_mode",
    }


def test_unavailable_runtime_fails_closed_and_customer_never_mounts_routes() -> None:
    services = PrincipalServices(_principal("analyst"))
    internal = create_api_app(
        surface="internal",
        services=services,
        recommendation_api=object(),
    )
    internal.state.recommendation_api = None
    customer = create_api_app(
        surface="customer",
        services=services,
        recommendation_api=object(),
    )
    path = f"/v1/projects/{PROJECT_ID}/recommendations"
    payload = _create_payload()

    with TestClient(internal) as client:
        missing_key = client.post(path, json=payload)
        unavailable = client.post(
            path,
            headers={"Idempotency-Key": "recommendation:create:unavailable"},
            json=payload,
        )
    with TestClient(customer) as client:
        hidden = client.post(
            path,
            headers={"Idempotency-Key": "recommendation:create:customer"},
            json=payload,
        )

    assert missing_key.status_code == 422
    assert unavailable.status_code == 503
    assert unavailable.headers["Retry-After"] == "30"
    assert hidden.status_code == 404


def test_generation_enqueue_accepts_only_selectors_and_returns_frozen_lineage() -> None:
    services = PrincipalServices(_principal("analyst"))
    api = GenerationApiStub()
    app = create_api_app(
        surface="internal",
        services=services,
        recommendation_api=api,
    )
    payload = _generation_payload(api.job)

    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{PROJECT_ID}/recommendations/generation-jobs",
            headers={"Idempotency-Key": "generation:api"},
            json=payload,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["id"] == str(api.job.id)
    assert body["prompt"]["release_hash"] == api.job.spec.prompt_binding.release_hash
    assert body["model"]["model_release_hash"] == api.job.spec.route.model_release_hash
    assert api.selection is not None
    assert api.selection.project_id == PROJECT_ID

    forged = deepcopy(payload)
    forged["evidence_selectors"][0]["valid"] = True
    with TestClient(app) as client:
        rejected = client.post(
            f"/v1/projects/{PROJECT_ID}/recommendations/generation-jobs",
            headers={"Idempotency-Key": "generation:forged"},
            json=forged,
        )
    assert rejected.status_code == 422

    raw_model = deepcopy(payload)
    raw_model["model"] = {
        "provider": "openai",
        "adapter_release_id": "operator-picked-adapter",
        "model_release_id": "operator-picked-model",
        "search_mode": "none",
    }
    with TestClient(app) as client:
        raw_model_rejected = client.post(
            f"/v1/projects/{PROJECT_ID}/recommendations/generation-jobs",
            headers={"Idempotency-Key": "generation:raw-model"},
            json=raw_model,
        )
    assert raw_model_rejected.status_code == 422


def test_memory_api_exposes_governed_human_approval_and_unstarted_draft() -> None:
    store = InMemoryRecommendationStore()
    store.install_evidence(*_evidence().all_refs)
    domain_application = RecommendationApplication(
        store.unit_of_work_factory(),
        clock=lambda: NOW,
    )
    api = memory_recommendation_api(domain_application)
    services = PrincipalServices(_principal("analyst"))
    app = create_api_app(
        surface="internal",
        services=services,
        recommendation_api=api,
    )
    collection_path = f"/v1/projects/{PROJECT_ID}/recommendations"

    with TestClient(app) as client:
        created = client.post(
            collection_path,
            headers={"Idempotency-Key": "recommendation:create:one"},
            json=_create_payload(),
        )
        assert created.status_code == 201, created.text
        created_body = created.json()
        recommendation = created_body["recommendation"]
        recommendation_id = recommendation["id"]
        input_versions = recommendation["input_versions"]
        assert recommendation["status"] == "draft"
        assert input_versions

        item_path = f"{collection_path}/{recommendation_id}"
        listed = client.get(collection_path)
        fetched = client.get(item_path)
        assert listed.status_code == fetched.status_code == 200
        assert listed.json()["total"] == 1
        assert fetched.json()["recommendation"]["id"] == recommendation_id

        submitted = client.post(
            f"{item_path}/submit",
            headers={"Idempotency-Key": "recommendation:submit:one"},
            json={"expected_version": 1},
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["recommendation"]["status"] == "in_review"

        services.principal = _principal("owner")
        reviewed = client.post(
            f"{item_path}/review",
            headers={"Idempotency-Key": "recommendation:review:one"},
            json={
                "expected_version": 2,
                "notes": "Reviewed against the exact frozen evidence graph.",
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        assert (
            reviewed.json()["review"]["evidence_graph_hash"]
            == recommendation["evidence_graph_hash"]
        )

        services.principal = _principal("admin")
        approved = client.post(
            f"{item_path}/approve",
            headers={"Idempotency-Key": "recommendation:approve:one"},
            json={"expected_version": 2},
        )
        assert approved.status_code == 200, approved.text
        approved_body = approved.json()
        draft = approved_body["downstream_draft"]
        assert approved_body["recommendation"]["status"] == "approved"
        assert approved_body["action_boundary"] == "draft_only_unstarted"
        assert draft["status"] == "draft"
        assert (
            draft["draft_only"],
            draft["enqueued"],
            draft["executed"],
            draft["published"],
            draft["started_at"],
        ) == (True, False, False, False, None)

        prepared = client.post(
            f"{item_path}/drafts/{draft['id']}/prepare-action",
            headers={"Idempotency-Key": "recommendation:prepare:one"},
            json={
                "expected_version": 3,
                "change_reason": "data_refreshed",
            },
        )
        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["authorized"] is True
        assert prepared.json()["action_boundary"] == "source_checked_draft_only"
        assert prepared.json()["draft"]["started_at"] is None

        execute = client.post(
            f"{item_path}/drafts/{draft['id']}/execute",
            headers={"Idempotency-Key": "recommendation:execute:forbidden-surface"},
            json={"expected_version": 3},
        )
        publish = client.post(
            f"{item_path}/drafts/{draft['id']}/publish",
            headers={"Idempotency-Key": "recommendation:publish:forbidden-surface"},
            json={"expected_version": 3},
        )
        assert execute.status_code == publish.status_code == 404

        services.principal = _principal("viewer", project_id=uuid4())
        outside_scope = client.get(item_path)
        assert outside_scope.status_code == 404


def test_attribution_unavailability_is_frozen_as_internal_insufficient_evidence() -> None:
    evidence = replace(
        _evidence(),
        attributions=(
            AttributionRef(
                **_base_ref("attribution:connector-policy"),
                valid=False,
                available=False,
                reason="connector_attribution_excluded_from_this_phase",
            ),
        ),
    )
    store = InMemoryRecommendationStore()
    store.install_evidence(*evidence.all_refs)
    api = memory_recommendation_api(
        RecommendationApplication(store.unit_of_work_factory(), clock=lambda: NOW)
    )
    app = create_api_app(
        surface="internal",
        services=PrincipalServices(_principal("analyst")),
        recommendation_api=api,
    )
    path = f"/v1/projects/{PROJECT_ID}/recommendations"
    conclusive = _create_payload(evidence)
    insufficient = deepcopy(conclusive)
    insufficient["recommendation_type"] = "insufficient_evidence"
    insufficient["proposed_draft_kind"] = "sampling_plan"

    with TestClient(app) as client:
        rejected = client.post(
            path,
            headers={"Idempotency-Key": "recommendation:attribution:conclusive"},
            json=conclusive,
        )
        created = client.post(
            path,
            headers={"Idempotency-Key": "recommendation:attribution:insufficient"},
            json=insufficient,
        )

    assert rejected.status_code == 422
    assert created.status_code == 201, created.text
    recommendation = created.json()["recommendation"]
    assert recommendation["recommendation_type"] == "insufficient_evidence"
    assert recommendation["evidence"]["attributions"] == [
        {
            "project_id": str(PROJECT_ID),
            "resource_id": "attribution:connector-policy",
            "version": "v1",
            "sha256": _digest("attribution:connector-policy:v1"),
            "locator": {"id": "attribution:connector-policy"},
            "valid": False,
            "available": False,
            "reason": "connector_attribution_excluded_from_this_phase",
        }
    ]
    assert any(
        item["kind"] == "attribution_availability"
        and item["resource_id"] == "attribution:connector-policy"
        for item in recommendation["input_versions"]
    )


def test_evidence_selectors_reject_state_flags_and_client_project_identity() -> None:
    services = PrincipalServices(_principal("analyst"))
    app = create_api_app(
        surface="internal",
        services=services,
        recommendation_api=RaisingRecommendationApi(AssertionError("must not be called")),
    )
    path = f"/v1/projects/{PROJECT_ID}/recommendations"
    headers = {"Idempotency-Key": "recommendation:create:strict"}
    nested_extra = deepcopy(_create_payload())
    nested_extra["evidence_selectors"][0]["approved"] = True  # type: ignore[index]
    cross_project = deepcopy(_create_payload())
    cross_project["scope"]["project_id"] = str(uuid4())  # type: ignore[index]

    with TestClient(app) as client:
        strict = client.post(path, headers=headers, json=nested_extra)
        domain_rule = client.post(
            path,
            headers={"Idempotency-Key": "recommendation:create:cross-project"},
            json=cross_project,
        )

    assert strict.status_code == 422
    assert domain_rule.status_code == 422
    assert strict.headers["content-type"].startswith("application/problem+json")
    assert domain_rule.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize(
    ("error", "expected_status"),
    (
        (RecommendationRuleViolation("invalid evidence"), 422),
        (RecommendationForbidden("not permitted"), 403),
        (RecommendationNotFound("not found"), 404),
        (RecommendationVersionConflict("version changed"), 409),
        (RecommendationPersistenceError("database unavailable"), 503),
    ),
)
def test_recommendation_errors_map_to_stable_problem_statuses(
    error: Exception,
    expected_status: int,
) -> None:
    services = PrincipalServices(_principal("analyst"))
    app = create_api_app(
        surface="internal",
        services=services,
        recommendation_api=RaisingRecommendationApi(error),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{PROJECT_ID}/recommendations",
            headers={"Idempotency-Key": "recommendation:create:error"},
            json=_create_payload(),
        )

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/problem+json")
    if expected_status == 503:
        assert response.headers["Retry-After"] == "30"


def test_runtime_fails_closed_when_postgres_builder_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEO_DATABASE_URL", "postgresql://recommendation.invalid/geo")
    monkeypatch.delenv("GEO_DATABASE_URL_FILE", raising=False)
    monkeypatch.setattr(recommendation_runtime.importlib, "import_module", lambda name: object())

    assert recommendation_runtime.build_recommendation_api() is None


def test_runtime_discovers_the_durable_postgres_recommendation_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEO_DATABASE_URL", "postgresql://geo_app:secret@db/geo")
    monkeypatch.delenv("GEO_DATABASE_URL_FILE", raising=False)

    assert recommendation_runtime.build_recommendation_api() is not None


def _principal(role: str, *, project_id: UUID = PROJECT_ID) -> AccessPrincipal:
    identity_id = uuid4()
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=TENANT_ID,
        memberships=(MembershipRecord(project_id, TENANT_ID, role),),
        auth_method="test",
    )


def _create_payload(
    evidence: RecommendationEvidenceGraph | None = None,
) -> dict[str, object]:
    evidence = _evidence() if evidence is None else evidence
    return {
        "recommendation_type": "hard_blocker",
        "proposed_draft_kind": "content_brief",
        "valid_until": (NOW + timedelta(days=30)).isoformat(),
        "expected_version": 0,
        "scope": {
            "applicable_version": evidence.scope.applicable_version,
            "campaign_id": str(evidence.scope.campaign_id),
            "question_or_cluster_ref": evidence.scope.question_or_cluster_ref,
            "surface_ref": evidence.scope.surface_ref,
            "content_asset_ref": evidence.scope.content_asset_ref,
            "url_ref": evidence.scope.url_ref,
        },
        "decision": {
            "impact_chain": list(evidence.decision.impact_chain),
            "risk": evidence.decision.risk,
            "effort": evidence.decision.effort,
            "business_value": evidence.decision.business_value,
            "confidence": str(evidence.decision.confidence),
            "counterevidence": list(evidence.decision.counterevidence),
            "validation_plan": list(evidence.decision.validation_plan),
            "stale_conditions": list(evidence.decision.stale_conditions),
        },
        "evidence_selectors": [
            {"kind": item.ref_kind, "resource_id": item.resource_id} for item in evidence.all_refs
        ],
    }


def _generation_payload(job: RecommendationGenerationJob) -> dict[str, object]:
    spec = job.spec
    return {
        "scope": {
            key: value
            for key, value in spec.evidence.scope.canonical_value().items()
            if key != "project_id"
        },
        "evidence_selectors": [
            {"kind": item.ref_kind, "resource_id": item.resource_id}
            for item in spec.evidence.all_refs
        ],
        "prompt_binding_id": str(spec.prompt_binding.binding_id),
        "model": {
            "runtime_selection_id": "90000000-0000-0000-0000-000000000009",
            "search_mode": None,
        },
        "valid_until": spec.valid_until.isoformat(),
        "minimum_real_observations": spec.minimum_real_observations,
        "arbiter_prompt_binding_id": None,
        "arbiter_model": None,
    }


def _evidence() -> RecommendationEvidenceGraph:
    question = QuestionRef(**_base_ref("question:1"), active=True)
    surface = SurfaceRef(**_base_ref("surface:google-aio:r1"), active=True)
    observation = ObservationRef(
        **_base_ref("observation:1"),
        capture_method="provider_api",
        evidence_class=ObservationEvidenceClass.REAL_OBSERVATION,
        question_resource_id=question.resource_id,
        surface_resource_id=surface.resource_id,
        eligible=True,
    )
    prompt = PromptReleaseRef(**_base_ref("prompt:recommendation:r1"), approved=True, frozen=True)
    return RecommendationEvidenceGraph(
        scope=RecommendationScope(
            project_id=PROJECT_ID,
            applicable_version="recommendation-contract-v1",
            campaign_id=UUID("30000000-0000-0000-0000-000000000003"),
            question_or_cluster_ref=question.resource_id,
            surface_ref=surface.resource_id,
            content_asset_ref="content:1",
            url_ref="verified-url:1",
        ),
        decision=RecommendationDecision(
            impact_chain=("Observed omission", "Lower qualified consideration"),
            risk="medium",
            effort="small",
            business_value="Protect discovery",
            confidence=Decimal("0.82"),
            counterevidence=("One interval remains wide",),
            validation_plan=("Run a paired frozen experiment",),
            stale_conditions=("Any evidence input version changes",),
        ),
        observations=(observation,),
        metric_comparisons=(
            MetricComparisonRef(
                **_base_ref("comparison:1"),
                observation_resource_ids=(observation.resource_id,),
                method_version="comparison-method-v1",
                method_sha256=_digest("comparison-method-v1"),
                sufficient_evidence=True,
            ),
        ),
        facts=(FactRef(**_base_ref("fact:1"), approved=True, retired=False),),
        rules=(RuleRef(**_base_ref("rule:1"), active=True),),
        prompt_releases=(prompt,),
        model_calls=(
            ModelCallRef(
                **_base_ref("model-call:1"),
                prompt_release_resource_id=prompt.resource_id,
                model_identity="provider/model@2026-07-23",
                succeeded=True,
            ),
        ),
        contents=(ContentRef(**_base_ref("content:1"), current=True),),
        questions=(question,),
        surfaces=(surface,),
    )


def _base_ref(resource_id: str) -> dict[str, object]:
    return {
        "project_id": PROJECT_ID,
        "resource_id": resource_id,
        "version": "v1",
        "sha256": _digest(f"{resource_id}:v1"),
        "locator": {"id": resource_id},
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
