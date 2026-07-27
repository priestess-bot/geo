from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from types import MappingProxyType
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from geo_api import prompt_program_runtime
from geo_api.app_factory import create_api_app
from geo_api.prompt_program_presenters import present_render_preview
from geo_api.prompt_program_runtime import (
    PromptProgramPageRead,
    PromptReleasePageRead,
    PromptReleaseRead,
)
from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.prompts.application import (
    BoundPromptProgram,
    CommandReceipt,
    CreatedPromptProgram,
    CreatedPromptRelease,
    PromptProgramForbidden,
    PromptProgramNotFound,
    PromptProgramRuntimeBlocked,
    TransitionedPromptProgram,
)
from geo_core.prompts.ports import (
    PromptBindingPageRead,
    PromptProgramIdempotencyConflict,
    PromptProgramPersistenceError,
    PromptProgramVersionConflict,
)
from geo_core.prompts.program import (
    CompiledProgramPrompt,
    ProgramKind,
    ProgramReleaseState,
    ProgramTestEvidence,
    PromptProgram,
    PromptProgramRelease,
    PromptProgramRuleViolation,
    bind_frozen_release,
    compare_candidate_to_approved,
    create_initial_release_state,
    transition_release_state,
)
from geo_core.prompts.test_execution_contracts import (
    PromptTestJob,
    PromptTestJobReceipt,
    PromptTestRuntimeOption,
)
from geo_core.prompts.workspace import (
    PromptFlowWorkspaceItem,
    PromptRenderPreview,
    PromptWorkingDraft,
    default_prompt_flow_definitions,
    draft_hash,
)
from geo_core.model_gateway.contracts import ModelCaptureMethod


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
RUNTIME_SELECTION_ID = uuid4()


def test_render_preview_response_deeply_thaws_frozen_fixture_values() -> None:
    compiled = CompiledProgramPrompt(
        release_id=uuid4(),
        release_hash="a" * 64,
        variable_input_hash="b" * 64,
        compiled_system="system",
        compiled_system_hash="c" * 64,
        compiled_user="user",
        compiled_user_hash="d" * 64,
        output_schema_version="test-output-v1",
        model_policy_version="test-policy-v1",
        model_policy_hash="e" * 64,
    )
    preview = PromptRenderPreview(
        fixture_id="question-generation.positive.v1",
        fixture_label="nested frozen fixture",
        input_value=MappingProxyType({
            "evidence": (MappingProxyType({"ref": "fact:au-1"}),),
            "dimensions": MappingProxyType({"market": "AU", "language": "en"}),
        }),
        draft=compiled,
        current=None,
        current_release_version=1,
    )

    body = json.loads(json.dumps(present_render_preview(preview).model_dump(mode="json")))

    assert body["input_value"] == {
        "dimensions": {"language": "en", "market": "AU"},
        "evidence": [{"ref": "fact:au-1"}],
    }


class PrincipalServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self.principal = principal

    def authenticate(self, authentication: object) -> AccessPrincipal:
        del authentication
        return self.principal


class PromptApiStub:
    def __init__(self) -> None:
        self.program: PromptProgram | None = None
        self.releases: dict[object, PromptProgramRelease] = {}
        self.states: dict[object, ProgramReleaseState] = {}
        self.test_evidence: dict[object, ProgramTestEvidence] = {}
        self.last_call: dict[str, object] = {}
        self.last_test_call: dict[str, object] = {}
        self.binding = None
        self.draft: PromptWorkingDraft | None = None

    def list_test_runtimes(self, principal: AccessPrincipal, **values: object):
        del principal, values
        return (
            PromptTestRuntimeOption(
                runtime_selection_id=RUNTIME_SELECTION_ID,
                runtime_selection_hash="11" * 32,
                runtime_manifest_id=uuid4(),
                runtime_manifest_hash="22" * 32,
                provider="openai",
                adapter_release_id="openai-adapter-v1",
                adapter_release_hash="33" * 32,
                model_release_id="openai-model-v1",
                model_release_hash="44" * 32,
                configured_model="gpt-fixture",
                capture_method=ModelCaptureMethod.PROVIDER_API,
                policy_version_id=uuid4(),
                policy_version_hash="55" * 32,
            ),
        )

    def create_program(self, principal: AccessPrincipal, **values: object):
        self.last_call = {"principal": principal, **values}
        program = PromptProgram(
            id=uuid4(),
            project_id=values["project_id"],
            program_kind=values["program_kind"],
            purpose=str(values["purpose"]),
            owner_id=principal.identity_id,
        )
        release = PromptProgramRelease.compile(
            id=uuid4(),
            program=program,
            version=1,
            system_template=str(values["system_template"]),
            user_template=str(values["user_template"]),
            schemas=values["schemas"],
            model_policy=values["model_policy"],
            test_set_id=values["test_set_id"],
            test_set_version=int(values["test_set_version"]),
            test_set_hash=str(values["test_set_hash"]),
            compiler_version=str(values["compiler_version"]),
        )
        state = create_initial_release_state(
            id=uuid4(), release=release, actor_id=principal.identity_id, acted_at=NOW
        )
        self.program = program
        self.releases[release.id] = release
        self.states[release.id] = state
        self.draft = PromptWorkingDraft(
            project_id=program.project_id,
            program_id=program.id,
            display_name="候选测评生成",
            system_template=release.system_template,
            user_template=release.user_template,
            revision=1,
            draft_hash=draft_hash(
                display_name="候选测评生成",
                system_template=release.system_template,
                user_template=release.user_template,
            ),
            base_release_id=release.id,
            candidate_release_id=None,
            updated_by=principal.identity_id,
            updated_at=NOW,
        )
        return CommandReceipt(CreatedPromptProgram(program, release, state), replayed=False)

    def list_flow_workspace(self, principal: AccessPrincipal, **values: object):
        del principal, values
        items = []
        latest = max(self.releases.values(), key=lambda item: item.version, default=None)
        for definition in default_prompt_flow_definitions():
            configured = self.program is not None and self.program.purpose == definition.purpose
            items.append(
                PromptFlowWorkspaceItem(
                    definition=definition,
                    program=self.program if configured else None,
                    draft=self.draft if configured else None,
                    latest_release=latest if configured else None,
                    current_release_id=(self.draft.base_release_id if configured and self.draft else None),
                    current_release_version=(latest.version if configured and latest else None),
                    candidate_status=None,
                    latest_test_job_id=None,
                    latest_test_status=None,
                    latest_test_score=None,
                )
            )
        return tuple(items)

    def get_working_draft(self, principal: AccessPrincipal, **values: object):
        del principal, values
        assert self.draft is not None
        return self.draft

    def save_working_draft(self, principal: AccessPrincipal, **values: object):
        assert self.draft is not None
        assert values["expected_revision"] == self.draft.revision
        name = str(values["display_name"])
        system = str(values["system_template"])
        user = str(values["user_template"])
        self.draft = replace(
            self.draft,
            display_name=name,
            system_template=system,
            user_template=user,
            revision=self.draft.revision + 1,
            draft_hash=draft_hash(
                display_name=name,
                system_template=system,
                user_template=user,
            ),
            updated_by=principal.identity_id,
        )
        return self.draft

    def list_programs(self, principal: AccessPrincipal, **values: object):
        del principal, values
        assert self.program is not None
        return PromptProgramPageRead((self.program,), 1)

    def create_release(self, principal: AccessPrincipal, **values: object):
        assert self.program is not None
        release = PromptProgramRelease.compile(
            id=uuid4(),
            program=self.program,
            version=int(values["expected_version"]) + 1,
            system_template=str(values["system_template"]),
            user_template=str(values["user_template"]),
            schemas=values["schemas"],
            model_policy=values["model_policy"],
            test_set_id=values["test_set_id"],
            test_set_version=int(values["test_set_version"]),
            test_set_hash=str(values["test_set_hash"]),
            compiler_version=str(values["compiler_version"]),
        )
        state = create_initial_release_state(
            id=uuid4(), release=release, actor_id=principal.identity_id, acted_at=NOW
        )
        self.releases[release.id] = release
        self.states[release.id] = state
        return CommandReceipt(CreatedPromptRelease(release, state), replayed=False)

    def get_program(self, principal: AccessPrincipal, **values: object):
        del principal, values
        assert self.program is not None
        return self.program

    def list_releases(self, principal: AccessPrincipal, **values: object):
        del principal, values
        items = tuple(
            PromptReleaseRead(release, self.states[release.id])
            for release in sorted(
                self.releases.values(), key=lambda item: item.version, reverse=True
            )
        )
        return PromptReleasePageRead(items, len(items))

    def get_release(self, principal: AccessPrincipal, **values: object):
        del principal
        release = self.releases[values["release_id"]]
        return PromptReleaseRead(release, self.states[release.id])

    def enqueue_test(self, principal: AccessPrincipal, **values: object):
        self.last_test_call = {"principal": principal, **values}
        release = self.releases[values["release_id"]]
        current = self.states[release.id]
        state_id = uuid4()
        evidence = ProgramTestEvidence(
            id=uuid4(),
            project_id=values["project_id"],
            release_id=release.id,
            release_hash=release.release_hash,
            tested_state_id=state_id,
            test_set_id=release.test_set_id,
            test_set_version=release.test_set_version,
            output_artifact_ref="s3://prompt-tests/server-evaluated/run.json",
            output_hash="a" * 64,
            tested_by=principal.identity_id,
            tested_at=NOW,
        )
        state = transition_release_state(
            id=state_id,
            release=release,
            current=current,
            command="record_test",
            actor_id=principal.identity_id,
            acted_at=NOW,
            evidence_ref=evidence.state_evidence_ref,
        )
        self.states[release.id] = state
        self.test_evidence[release.id] = evidence
        return PromptTestJobReceipt(
            PromptTestJob(
                id=uuid4(),
                project_id=release.project_id,
                release_id=release.id,
                release_hash=release.release_hash,
                test_set_id=release.test_set_id,
                test_set_version=release.test_set_version,
                test_set_hash=release.test_set_hash,
                input_hash="cd" * 32,
            ),
            replayed=False,
        )

    def approve_release(self, principal: AccessPrincipal, **values: object):
        release = self.releases[values["release_id"]]
        current = self.states[release.id]
        evidence = self.test_evidence[release.id]
        state = transition_release_state(
            id=uuid4(),
            release=release,
            current=current,
            command="approve",
            actor_id=principal.identity_id,
            acted_at=NOW,
            evidence_ref=f"approval:{evidence.evidence_hash}",
        )
        self.states[release.id] = state
        result = TransitionedPromptProgram(release, state, evidence)
        return CommandReceipt(result, False)

    def freeze_release(self, principal: AccessPrincipal, **values: object):
        release = self.releases[values["release_id"]]
        current = self.states[release.id]
        state = transition_release_state(
            id=uuid4(),
            release=release,
            current=current,
            command="freeze",
            actor_id=principal.identity_id,
            acted_at=NOW,
            evidence_ref=f"freeze:{current.id}",
        )
        self.states[release.id] = state
        return CommandReceipt(TransitionedPromptProgram(release, state), False)

    def retire_release(self, principal: AccessPrincipal, **values: object):
        release = self.releases[values["release_id"]]
        current = self.states[release.id]
        state = transition_release_state(
            id=uuid4(),
            release=release,
            current=current,
            command="retire",
            actor_id=principal.identity_id,
            acted_at=NOW,
            evidence_ref=f"retire:{current.id}:{current.release_hash}",
        )
        self.states[release.id] = state
        return CommandReceipt(TransitionedPromptProgram(release, state), False)

    def diff_release(self, principal: AccessPrincipal, **values: object):
        del principal
        baseline = self.releases[values["baseline_release_id"]]
        candidate = self.releases[values["candidate_release_id"]]
        result = compare_candidate_to_approved(
            approved_release=baseline,
            approved_state=self.states[baseline.id],
            candidate_release=candidate,
            candidate_state=self.states[candidate.id],
            fixed_variables=values["fixed_variables"],
        )
        return CommandReceipt(result, False)

    def bind_release(self, principal: AccessPrincipal, **values: object):
        release = self.releases[values["release_id"]]
        state = self.states[release.id]
        binding = bind_frozen_release(
            id=uuid4(),
            project_id=values["project_id"],
            purpose=str(values["purpose"]),
            release=release,
            state=state,
            binding_version=int(values["expected_version"]) + 1,
            previous_binding_id=None,
            actor_id=principal.identity_id,
            bound_at=NOW,
        )
        self.binding = binding
        return CommandReceipt(BoundPromptProgram(release, state, binding), False)

    def list_bindings(self, principal: AccessPrincipal, **values: object):
        del principal, values
        items = (self.binding,) if self.binding is not None else ()
        return PromptBindingPageRead(items, len(items))


class RaisingPromptApi:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def create_program(self, principal: AccessPrincipal, **values: object):
        del principal, values
        raise self.error


def test_prompt_program_openapi_is_internal_stable_and_redacted() -> None:
    internal = create_api_app(surface="internal").openapi()
    customer = create_api_app(surface="customer").openapi()
    prefix = "/v1/projects/{project_id}/prompt-programs"
    expected = {
        prefix,
        f"{prefix}/{{program_id}}",
        f"{prefix}/{{program_id}}/releases",
        f"{prefix}/{{program_id}}/releases/{{release_id}}",
        f"{prefix}/{{program_id}}/releases/{{release_id}}/tests",
        f"{prefix}/{{program_id}}/releases/{{release_id}}/approve",
        f"{prefix}/{{program_id}}/releases/{{release_id}}/freeze",
        f"{prefix}/{{program_id}}/releases/{{release_id}}/retire",
        f"{prefix}/{{program_id}}/releases/{{release_id}}/diff",
        "/v1/projects/{project_id}/prompt-program-test-options",
        "/v1/projects/{project_id}/prompt-program-bindings",
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
        "createPromptProgram",
        "listPromptPrograms",
        "getPromptProgram",
        "listPromptProgramReleases",
        "createPromptProgramRelease",
        "getPromptProgramRelease",
        "testPromptProgramRelease",
        "approvePromptProgramRelease",
        "freezePromptProgramRelease",
        "retirePromptProgramRelease",
        "diffPromptProgramRelease",
        "bindPromptProgramRelease",
        "listPromptProgramBindings",
        "listPromptProgramTestRuntimes",
    }
    schemas = internal["components"]["schemas"]
    release_fields = schemas["PromptProgramReleaseResponse"]["properties"]
    test_request_fields = schemas["TestPromptProgramReleaseRequest"]["properties"]
    test_job_fields = schemas["PromptTestJobResponse"]["properties"]
    assert "system_template" not in release_fields
    assert "user_template" not in release_fields
    assert "output_artifact_ref" not in test_request_fields
    assert "output_hash" not in test_request_fields
    assert "passed" not in test_request_fields
    assert set(test_request_fields) == {
        "test_set_id",
        "test_set_version",
        "test_set_hash",
        "runtime_selection_id",
        "expected_version",
    }
    assert "output_artifact_ref" not in test_job_fields


def test_unavailable_runtime_fails_closed_and_commands_require_idempotency() -> None:
    app, principal = _app(None)
    path = f"/v1/projects/{principal.project_ids[0]}/prompt-programs"
    payload = _create_payload()
    with TestClient(app) as client:
        missing_key = client.post(path, json=payload)
        unavailable = client.post(
            path, headers={"Idempotency-Key": "create:one"}, json=payload
        )

    assert missing_key.status_code == 422
    assert unavailable.status_code == 503
    assert unavailable.headers["Retry-After"] == "30"


def test_runtime_fails_closed_when_postgres_api_builder_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEO_DATABASE_URL", "postgresql://prompt.invalid/geo")
    monkeypatch.delenv("GEO_DATABASE_URL_FILE", raising=False)
    monkeypatch.setattr(prompt_program_runtime.importlib, "import_module", lambda name: object())

    assert prompt_program_runtime.build_prompt_program_application() is None


def test_create_and_test_responses_expose_hash_lineage_without_raw_content() -> None:
    stub = PromptApiStub()
    app, principal = _app(stub)
    project_id = principal.project_ids[0]
    create_payload = _create_payload()
    with TestClient(app) as client:
        created = client.post(
            f"/v1/projects/{project_id}/prompt-programs",
            headers={"Idempotency-Key": "create:one"},
            json=create_payload,
        )
        body = created.json()
        program_id = body["program"]["id"]
        release_id = body["release"]["id"]
        listed_programs = client.get(
            f"/v1/projects/{project_id}/prompt-programs"
        )
        runtimes = client.get(
            f"/v1/projects/{project_id}/prompt-program-test-options"
        )
        tested = client.post(
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/releases/{release_id}/tests",
            headers={"Idempotency-Key": "test:one"},
            json={
                "test_set_id": body["release"]["test_set_id"],
                "test_set_version": body["release"]["test_set_version"],
                "test_set_hash": body["release"]["test_set_hash"],
                "runtime_selection_id": str(RUNTIME_SELECTION_ID),
                "expected_version": 1,
            },
        )
        fetched_program = client.get(
            f"/v1/projects/{project_id}/prompt-programs/{program_id}"
        )
        listed = client.get(
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/releases"
        )
        fetched_release = client.get(
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/releases/{release_id}"
        )
        approved = client.post(
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/releases/{release_id}/approve",
            headers={"Idempotency-Key": "approve:one"},
            json={"expected_version": 2},
        )
        created_v2 = client.post(
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/releases",
            headers={"Idempotency-Key": "release:two"},
            json=_release_payload(create_payload),
        )
        release_v2_id = created_v2.json()["release"]["id"]
        listed_after_v2 = client.get(
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/releases"
        )
        diffed = client.post(
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/releases/{release_v2_id}/diff",
            headers={"Idempotency-Key": "diff:one"},
            json={
                "baseline_release_id": release_id,
                "fixed_variables": {"scenario": "sensitive fixed input"},
                "expected_version": 1,
            },
        )
        frozen = client.post(
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/releases/{release_id}/freeze",
            headers={"Idempotency-Key": "freeze:one"},
            json={"expected_version": 3},
        )
        bound = client.post(
            f"/v1/projects/{project_id}/prompt-program-bindings",
            headers={"Idempotency-Key": "bind:one"},
            json={
                "program_id": program_id,
                "release_id": release_id,
                "purpose": "synthetic_lab.generation",
                "expected_version": 0,
            },
        )
        bindings = client.get(
            f"/v1/projects/{project_id}/prompt-program-bindings",
            params={"program_kind": "generation"},
        )
        retired = client.post(
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/releases/{release_id}/retire",
            headers={"Idempotency-Key": "retire:one"},
            json={"expected_version": 4},
        )

    assert created.status_code == 201
    assert stub.last_call["principal"] is principal
    assert stub.last_call["expected_version"] == 0
    assert "system_template" not in body["release"]
    assert "user_template" not in body["release"]
    assert "policy" not in body["release"]
    assert tested.status_code == 202
    assert tested.json()["status"] == "queued"
    assert tested.json()["test_set_hash"] == body["release"]["test_set_hash"]
    assert "output_artifact_ref" not in tested.json()
    assert "passed" not in tested.json()
    assert retired.status_code == 200
    assert retired.json()["release"]["state"]["status"] == "retired"
    assert fetched_program.status_code == 200
    assert listed_programs.status_code == 200
    assert listed_programs.json()["items"] == [body["program"]]
    assert runtimes.status_code == 200
    assert runtimes.json()["items"][0]["runtime_selection_id"] == str(
        RUNTIME_SELECTION_ID
    )
    route = stub.last_test_call["route"]
    assert getattr(route, "runtime_selection_id") == RUNTIME_SELECTION_ID
    assert listed.status_code == 200 and listed.json()["total"] == 1
    assert fetched_release.json()["system_template"] == create_payload["system_template"]
    assert fetched_release.json()["user_template"] == create_payload["user_template"]
    assert approved.status_code == 200
    assert created_v2.status_code == 201
    assert created_v2.json()["release"]["version"] == 2
    assert listed_after_v2.status_code == 200
    assert listed_after_v2.json()["total"] == 2
    assert [item["version"] for item in listed_after_v2.json()["items"]] == [2, 1]
    assert frozen.status_code == 200
    assert diffed.status_code == 200
    assert diffed.json()["base_release_id"] == release_id
    assert diffed.json()["candidate_release_id"] == release_v2_id
    assert diffed.json()["changed_fields"] == ["user_template"]
    assert "sensitive fixed input" not in diffed.text
    assert bound.status_code == 200
    assert bindings.status_code == 200
    assert bindings.json()["items"][0]["id"] == bound.json()["id"]


def test_prompt_workspace_exposes_editable_content_without_leaking_it_in_lists() -> None:
    stub = PromptApiStub()
    app, principal = _app(stub)
    project_id = principal.project_ids[0]
    payload = _create_payload()
    with TestClient(app) as client:
        created = client.post(
            f"/v1/projects/{project_id}/prompt-programs",
            headers={"Idempotency-Key": "workspace:create"},
            json=payload,
        )
        program_id = created.json()["program"]["id"]
        flows = client.get(f"/v1/projects/{project_id}/prompt-flows")
        draft = client.get(
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/draft"
        )
        saved = client.put(
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/draft",
            json={
                "display_name": "澳洲测评候选生成",
                "system_template": "Use approved evidence for {{channel}}.",
                "user_template": "Write the {{scenario}} candidates.",
                "expected_revision": 1,
            },
        )
        listed = client.get(
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/releases"
        )

    assert created.status_code == 201
    assert flows.status_code == 200
    configured = next(
        item for item in flows.json()["items"] if item["program"] is not None
    )
    assert configured["display_name"] == "候选测评生成"
    assert configured["draft"]["system_template"] == payload["system_template"]
    assert draft.status_code == 200
    assert draft.json()["user_template"] == payload["user_template"]
    assert saved.status_code == 200
    assert saved.json()["revision"] == 2
    assert saved.json()["display_name"] == "澳洲测评候选生成"
    assert listed.status_code == 200
    assert "system_template" not in listed.json()["items"][0]


def test_prompt_workspace_slots_insert_only_template_variables() -> None:
    slots = {
        slot.key: slot
        for definition in default_prompt_flow_definitions()
        for slot in definition.context_slots
    }

    assert slots["request_json"].insertion == "{{request_json}}"
    assert all(
        slot.insertion == f"{{{{{slot.key}}}}}"
        for slot in slots.values()
    )


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (PromptProgramRuleViolation("invalid"), 422),
        (PromptProgramForbidden("denied"), 403),
        (PromptProgramNotFound("missing"), 404),
        (PromptProgramIdempotencyConflict("key conflict"), 409),
        (PromptProgramVersionConflict("version conflict"), 409),
        (PromptProgramRuntimeBlocked("not frozen"), 409),
        (PromptProgramPersistenceError("database unavailable"), 503),
    ],
)
def test_prompt_program_errors_map_to_stable_problem_statuses(
    error: Exception, expected_status: int
) -> None:
    app, principal = _app(RaisingPromptApi(error))
    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{principal.project_ids[0]}/prompt-programs",
            headers={"Idempotency-Key": "create:error"},
            json=_create_payload(),
        )

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/problem+json")


def _app(prompt_api: object | None):
    tenant_id, identity_id, project_id = uuid4(), uuid4(), uuid4()
    principal = AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=tenant_id,
        memberships=(MembershipRecord(project_id, tenant_id, "admin"),),
        auth_method="test",
    )
    app = create_api_app(
        surface="internal",
        services=PrincipalServices(principal),  # type: ignore[arg-type]
        prompt_program_application=prompt_api,
    )
    return app, principal


def _create_payload() -> dict[str, object]:
    variables = {
        "type": "object",
        "properties": {"scenario": {"type": "string"}},
        "required": ["scenario"],
        "additionalProperties": False,
    }
    return {
        "program_kind": ProgramKind.GENERATION.value,
        "purpose": "synthetic_lab.generation",
        "system_template": "Return JSON for {{scenario}}.",
        "user_template": "Generate {{scenario}}.",
        "schemas": {
            "variable_schema_version": "variables-v1",
            "variable_schema": variables,
            "input_schema_version": "input-v1",
            "input_schema": variables,
            "output_schema_version": "candidate-v1",
            "output_schema": {
                "type": "object",
                "properties": {"candidate": {"type": "string"}},
                "required": ["candidate"],
            },
            "application_output_schema_version": "candidate-application-v1",
            "application_output_schema": {
                "type": "object",
                "properties": {"candidate": {"type": "string"}},
                "required": ["candidate"],
            },
        },
        "model_policy": {
            "version": "generation-v1",
            "policy": {"configured_model": "approved-model", "fallback": False},
        },
        "test_set_id": str(uuid4()),
        "test_set_version": 1,
        "test_set_hash": "ab" * 32,
        "compiler_version": "geo-prompt-compiler-v2",
        "expected_version": 0,
    }


def _release_payload(create_payload: dict[str, object]) -> dict[str, object]:
    return {
        "system_template": create_payload["system_template"],
        "user_template": "Generate a detailed {{scenario}}.",
        "schemas": create_payload["schemas"],
        "model_policy": create_payload["model_policy"],
        "test_set_id": create_payload["test_set_id"],
        "test_set_version": create_payload["test_set_version"],
        "test_set_hash": create_payload["test_set_hash"],
        "compiler_version": create_payload["compiler_version"],
        "expected_version": 1,
    }
