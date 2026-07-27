from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from fastapi.testclient import TestClient

from geo_api.app_factory import create_api_app
from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.prompts import (
    InMemoryPromptProgramRepository,
    ProgramKind,
    PromptProgramApplication,
    default_prompt_bootstrap_spec,
    default_prompt_bootstrap_specs,
    prompt_bootstrap_catalog_hash,
)
from geo_core.prompts.bootstrap_contracts import EvalScenario, thaw_mapping
from geo_core.prompts.ports import PromptProgramPersistenceError


class PrincipalServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self.principal = principal

    def authenticate(self, authentication: object) -> AccessPrincipal:
        del authentication
        return self.principal


class FailOneKindOnce:
    def __init__(
        self,
        application: PromptProgramApplication,
        kind: ProgramKind,
    ) -> None:
        self.application = application
        self.kind = kind
        self.failed = False

    def create_program(self, principal: AccessPrincipal, **values: object):
        if values["program_kind"] is self.kind and not self.failed:
            self.failed = True
            raise PromptProgramPersistenceError("temporary bootstrap item failure")
        return self.application.create_program(principal, **values)


def test_prompt_bootstrap_openapi_is_internal_only_and_explicitly_non_atomic() -> None:
    internal = create_api_app(surface="internal").openapi()
    customer = create_api_app(surface="customer").openapi()
    prefix = "/v1/projects/{project_id}/prompt-bootstrap"
    expected = {prefix, f"{prefix}/evaluate", f"{prefix}/drafts"}

    assert expected <= set(internal["paths"])
    assert expected.isdisjoint(customer["paths"])
    assert internal["paths"][prefix]["get"]["operationId"] == (
        "previewPromptBootstrapCatalog"
    )
    assert internal["paths"][f"{prefix}/evaluate"]["post"]["operationId"] == (
        "evaluatePromptBootstrapOutputs"
    )
    assert internal["paths"][f"{prefix}/drafts"]["post"]["operationId"] == (
        "createPromptBootstrapDrafts"
    )
    response_schema = internal["components"]["schemas"]["BootstrapCreateDraftsResponse"]
    assert response_schema["properties"]["atomic"]["const"] is False
    assert response_schema["properties"]["safe_to_retry"]["const"] is True


def test_admin_can_preview_all_frozen_specs_without_persistence_or_model_calls() -> None:
    app, principal, _ = _app(role="admin", prompt_api=None)
    with TestClient(app) as client:
        response = client.get(_path(principal))

    assert response.status_code == 200
    body = response.json()
    assert body["catalog_hash"] == prompt_bootstrap_catalog_hash()
    assert body["external_model_calls"] == 0
    assert body["automatic_transitions"] is False
    assert body["batch_atomicity"] == "per_item"
    assert body["action_boundary"] == "draft_only_manual_test"
    assert len(body["items"]) == 14
    assert [item["program_kind"] for item in body["items"]] == [
        spec.program_kind.value for spec in default_prompt_bootstrap_specs()
    ]
    for item in body["items"]:
        assert len(item["fixtures"]) == 5
        assert sum(criterion["weight"] for criterion in item["rubric"]) == 100
        assert "expected_output" not in item
        assert "system_template" not in item
        assert "user_template" not in item


def test_offline_evaluation_is_deterministic_and_requires_frozen_hashes() -> None:
    app, principal, _ = _app(role="owner", prompt_api=None)
    spec = default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION)
    payload = _evaluation_payload(spec)
    with TestClient(app) as client:
        first = client.post(f"{_path(principal)}/evaluate", json=payload)
        second = client.post(f"{_path(principal)}/evaluate", json=payload)
        stale = client.post(
            f"{_path(principal)}/evaluate",
            json={**payload, "catalog_hash": "0" * 64},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    body = first.json()
    assert body == second.json()
    assert body["passed"] is True
    assert body["score"] == 100
    assert body["external_model_calls"] == 0
    assert body["automatic_transitions"] is False
    assert body["catalog_hash"] == prompt_bootstrap_catalog_hash()
    assert body["test_set_hash"] == spec.test_set_hash
    assert len(body["case_results"]) == 5
    assert all(item["passed"] for item in body["case_results"])
    assert stale.status_code == 409


def test_offline_evaluation_returns_rubric_failure_without_calling_a_model() -> None:
    app, principal, _ = _app(role="admin", prompt_api=None)
    spec = default_prompt_bootstrap_spec(ProgramKind.GENERATION)
    payload = _evaluation_payload(spec)
    subject_case = next(
        fixture for fixture in spec.fixtures if fixture.scenario is EvalScenario.SUBJECT_MIXUP
    )
    bad_output = deepcopy(payload["outputs"][subject_case.fixture_id])
    bad_output["subject_id"] = "subject-placeholder-other"
    payload["outputs"][subject_case.fixture_id] = bad_output

    with TestClient(app) as client:
        response = client.post(f"{_path(principal)}/evaluate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["passed"] is False
    failed = next(
        item for item in body["case_results"] if item["fixture_id"] == subject_case.fixture_id
    )
    assert failed["error_code"] == "subject_mismatch"
    assert failed["failed_criteria"] == ["identity.subject_exact"]
    assert failed["blocking_failure"] is True


def test_create_ten_drafts_is_item_idempotent_and_never_transitions_them() -> None:
    repository = InMemoryPromptProgramRepository()
    application = PromptProgramApplication(repository)
    app, principal, _ = _app(role="admin", prompt_api=application)
    path = f"{_path(principal)}/drafts"
    payload = {"catalog_hash": prompt_bootstrap_catalog_hash()}
    headers = {"Idempotency-Key": "bootstrap-ten-drafts-one"}
    with TestClient(app) as client:
        missing_key = client.post(path, json=payload)
        first = client.post(path, headers=headers, json=payload)
        second = client.post(path, headers=headers, json=payload)

    assert missing_key.status_code == 422
    assert first.status_code == 200
    assert second.status_code == 200
    created = first.json()
    replayed = second.json()
    assert created["completion_status"] == "completed"
    assert created["created_count"] == 14
    assert created["replayed_count"] == created["failed_count"] == 0
    assert replayed["completion_status"] == "completed"
    assert replayed["replayed_count"] == 14
    assert replayed["created_count"] == replayed["failed_count"] == 0
    assert created["atomic"] is False and created["safe_to_retry"] is True
    assert created["action_boundary"] == "draft_only_no_approval_freeze_binding"
    assert len({item["idempotency_key_hash"] for item in created["items"]}) == 14
    assert [item["idempotency_key_hash"] for item in created["items"]] == [
        item["idempotency_key_hash"] for item in replayed["items"]
    ]
    for item in [*created["items"], *replayed["items"]]:
        assert item["release"]["state"]["status"] == "draft"
        assert item["release"]["state"]["evidence_ref"] is None
        assert item["failure"] is None
        assert "system_template" not in item["release"]
    stored = repository.list_programs(
        project_id=principal.project_ids[0], limit=200, offset=0
    )
    assert stored.total == 14


def test_partial_batch_reports_per_item_failure_and_retries_without_duplicates() -> None:
    repository = InMemoryPromptProgramRepository()
    application = PromptProgramApplication(repository)
    fail_once = FailOneKindOnce(application, ProgramKind.CONFLICT_CHECK)
    app, principal, _ = _app(role="admin", prompt_api=fail_once)
    path = f"{_path(principal)}/drafts"
    payload = {"catalog_hash": prompt_bootstrap_catalog_hash()}
    headers = {"Idempotency-Key": "bootstrap-partial-retry-one"}
    with TestClient(app) as client:
        first = client.post(path, headers=headers, json=payload)
        second = client.post(path, headers=headers, json=payload)

    assert first.status_code == second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["completion_status"] == "partial_failure"
    assert first_body["created_count"] == 13 and first_body["failed_count"] == 1
    failure = next(item for item in first_body["items"] if item["status"] == "failed")
    assert failure["program_kind"] == "conflict_check"
    assert failure["failure"] == {
        "code": "persistence_unavailable",
        "detail": "temporary bootstrap item failure",
        "retryable": True,
    }
    assert second_body["completion_status"] == "completed"
    assert second_body["created_count"] == 1
    assert second_body["replayed_count"] == 13
    assert second_body["failed_count"] == 0
    assert repository.list_programs(
        project_id=principal.project_ids[0], limit=200, offset=0
    ).total == 14


def test_draft_creation_fails_closed_when_prompt_persistence_is_unavailable() -> None:
    app, principal, _ = _app(role="admin", prompt_api=None)
    app.state.prompt_program_application = None
    with TestClient(app) as client:
        response = client.post(
            f"{_path(principal)}/drafts",
            headers={"Idempotency-Key": "bootstrap-no-persistence"},
            json={"catalog_hash": prompt_bootstrap_catalog_hash()},
        )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert response.json()["type"] == "urn:geo:problem:service-unavailable"


def test_every_bootstrap_operation_requires_project_owner_or_admin() -> None:
    repository = InMemoryPromptProgramRepository()
    application = PromptProgramApplication(repository)
    app, principal, _ = _app(role="analyst", prompt_api=application)
    spec = default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION)
    with TestClient(app) as client:
        preview = client.get(_path(principal))
        evaluated = client.post(
            f"{_path(principal)}/evaluate", json=_evaluation_payload(spec)
        )
        created = client.post(
            f"{_path(principal)}/drafts",
            headers={"Idempotency-Key": "analyst-bootstrap-denied"},
            json={"catalog_hash": prompt_bootstrap_catalog_hash()},
        )

    assert preview.status_code == evaluated.status_code == created.status_code == 403
    assert repository.list_programs(
        project_id=principal.project_ids[0], limit=200, offset=0
    ).total == 0


def test_stale_catalog_blocks_batch_before_any_item_is_created() -> None:
    repository = InMemoryPromptProgramRepository()
    application = PromptProgramApplication(repository)
    app, principal, _ = _app(role="admin", prompt_api=application)
    with TestClient(app) as client:
        response = client.post(
            f"{_path(principal)}/drafts",
            headers={"Idempotency-Key": "stale-bootstrap-catalog"},
            json={"catalog_hash": "f" * 64},
        )

    assert response.status_code == 409
    assert repository.list_programs(
        project_id=principal.project_ids[0], limit=200, offset=0
    ).total == 0


def _app(*, role: str, prompt_api: object | None):
    tenant_id, identity_id, project_id = uuid4(), uuid4(), uuid4()
    principal = AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=tenant_id,
        memberships=(MembershipRecord(project_id, tenant_id, role),),
        auth_method="test",
    )
    app = create_api_app(
        surface="internal",
        services=PrincipalServices(principal),  # type: ignore[arg-type]
        prompt_program_application=prompt_api,
    )
    return app, principal, project_id


def _path(principal: AccessPrincipal) -> str:
    return f"/v1/projects/{principal.project_ids[0]}/prompt-bootstrap"


def _evaluation_payload(spec) -> dict[str, object]:
    positive = next(
        fixture for fixture in spec.fixtures if fixture.scenario is EvalScenario.POSITIVE
    )
    outputs: dict[str, dict[str, object]] = {}
    for fixture in spec.fixtures:
        source = fixture if fixture.scenario is EvalScenario.PROMPT_INJECTION else positive
        outputs[fixture.fixture_id] = thaw_mapping(source.expected_output)
    return {
        "program_kind": spec.program_kind.value,
        "catalog_hash": prompt_bootstrap_catalog_hash(),
        "spec_hash": spec.spec_hash,
        "test_set_hash": spec.test_set_hash,
        "outputs": outputs,
    }
