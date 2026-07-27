from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from geo_core.jobs.postgres import WorkerLease
from geo_core.secrets import SecretValue, SecretVersionHandle
from geo_core.workflow_runtime import (
    DifyWorkflowExecutor,
    RetryableWorkflowExecutionError,
    WorkflowAuthenticationError,
    WorkflowContractError,
    WorkflowExecutionRequest,
    WorkflowRuntimeRelease,
    PublishedWorkflowSnapshot,
)
from geo_core.workflow_runtime.contracts import CONTEXT_CONTRACT_VERSION, canonical_json_hash


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class FakeCredentials:
    def __init__(self, value: str = "app-secret") -> None:
        self.value = value
        self.handles = []

    def resolve(self, handle):
        self.handles.append(handle)
        return SecretValue(self.value)


class FakeRepository:
    def __init__(self, release) -> None:
        self.release = release
        self.started = []
        self.finished = []
        self.attempt_id = uuid4()

    def resolve_active(self, *, project_id, purpose):
        assert project_id == self.release.project_id
        assert purpose == self.release.purpose
        return self.release

    def get_release(self, *, project_id, release_id):
        assert (project_id, release_id) == (self.release.project_id, self.release.id)
        return self.release

    def begin_business_attempt(self, lease, **values):
        self.started.append((lease, values))
        return self.attempt_id

    def finish_business_attempt(self, lease, *, attempt_id, values):
        self.finished.append((lease, attempt_id, values))

    def begin_canary_attempt(self, **values):
        self.started.append((None, values))
        return self.attempt_id

    def finish_canary_attempt(self, **values):
        self.finished.append((None, values["attempt_id"], values["values"]))

    def record_published_snapshot(self, *, release, snapshot):
        assert release == self.release
        self.snapshot = snapshot
        return uuid4()


class FakePublishedReader:
    def __init__(self, release) -> None:
        self.release = release

    def read(self, *, purpose, app_id):
        assert (purpose, app_id) == (self.release.purpose, self.release.dify_app_id)
        return PublishedWorkflowSnapshot(
            purpose=purpose,
            app_id=app_id,
            workflow_id="published-workflow",
            workflow_hash="e" * 64,
            snapshot_hash="f" * 64,
            prompt_nodes=({"node_id": "llm", "messages": []},),
            input_variables=({"name": "geo_context_json"},),
            graph_nodes=({"node_id": "llm", "type": "llm", "title": "LLM"},),
            published_at=datetime(2026, 7, 27, tzinfo=UTC),
            observed_at=datetime(2026, 7, 27, tzinfo=UTC),
        )


def release_and_request():
    project_id = uuid4()
    output_schema = {
        "type": "object",
        "properties": {"questions": {"type": "array"}},
        "required": ["questions"],
    }
    input_schema = {
        "type": "object",
        "properties": {"dimensions": {"type": "array"}},
        "required": ["dimensions"],
    }
    release = WorkflowRuntimeRelease(
        id=uuid4(),
        project_id=project_id,
        purpose="knowledge.question_generation",
        version=1,
        prompt_program_id=uuid4(),
        prompt_release_id=uuid4(),
        prompt_release_hash="a" * 64,
        prompt_system_template="Frozen program system policy.",
        prompt_user_template="Process this request:\n{{request_json}}",
        dify_app_id="app-one",
        dify_workflow_id="workflow-one",
        dsl_hash="b" * 64,
        context_contract_version=CONTEXT_CONTRACT_VERSION,
        input_schema=input_schema,
        input_schema_hash=canonical_json_hash(input_schema),
        output_schema=output_schema,
        output_schema_hash=canonical_json_hash(output_schema),
        configured_model="deepseek-chat",
        model_provider="deepseek",
        api_secret_handle=SecretVersionHandle(
            reference_id=uuid4(),
            project_id=project_id,
            purpose="workflow_runtime.dify",
            version=1,
        ),
        release_hash="c" * 64,
        binding_version=1,
    )
    request = WorkflowExecutionRequest(
        project_id=project_id,
        purpose=release.purpose,
        context={"dimensions": [{"dimension_key": "value"}]},
        input_hash="d" * 64,
        output_schema=output_schema,
    )
    lease = WorkerLease(
        uuid4(), project_id, "knowledge.question.generate", "worker", uuid4(), 2, 1, 3
    )
    return release, request, lease


def test_executes_blocking_workflow_and_records_exact_lineage() -> None:
    release, request, lease = release_and_request()

    def handler(message: httpx.Request) -> httpx.Response:
        assert message.headers["authorization"] == "Bearer app-secret"
        payload = json.loads(message.content)
        assert payload["response_mode"] == "blocking"
        assert json.loads(payload["inputs"]["geo_context_json"]) == request.context
        assert payload["inputs"]["geo_prompt_system"].startswith("Frozen program system policy.")
        assert "dimensions" in payload["inputs"]["geo_prompt_user"]
        return httpx.Response(
            200,
            json={
                "task_id": "task-1",
                "workflow_run_id": "run-1",
                "data": {
                    "workflow_id": "workflow-one",
                    "status": "succeeded",
                    "outputs": {"result": json.dumps({"questions": []})},
                    "total_steps": 3,
                    "elapsed_time": 1.25,
                },
            },
        )

    repository = FakeRepository(release)
    result = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).execute_optional(lease, request)

    assert result is not None
    assert result.output == {"questions": []}
    assert result.dify_run_id == "run-1"
    assert result.as_model_gateway_result().provider == "dify"
    assert repository.started[0][1]["context_hash"] == request.context_hash
    assert repository.finished[0][2]["status"] == "succeeded"
    assert repository.finished[0][2]["dify_run_id"] == "run-1"


def test_managed_workflow_uses_dify_prompt_and_records_published_snapshot() -> None:
    release, request, lease = release_and_request()

    def handler(message: httpx.Request) -> httpx.Response:
        payload = json.loads(message.content)
        assert "geo_prompt_system" not in payload["inputs"]
        assert "geo_prompt_user" not in payload["inputs"]
        return httpx.Response(
            200,
            json={
                "workflow_run_id": "managed-run",
                "data": {
                    "workflow_id": "published-workflow",
                    "status": "succeeded",
                    "outputs": {"result": json.dumps({"questions": []})},
                },
            },
        )

    repository = FakeRepository(release)
    result = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        published_reader=FakePublishedReader(release),  # type: ignore[arg-type]
        require_active=True,
    ).execute_optional(lease, request)

    assert result is not None
    assert repository.started[0][1]["published_snapshot_id"] is not None
    assert repository.finished[0][2]["reported_workflow_id"] == "published-workflow"


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retryable_http_failure_is_recorded_and_never_falls_back(status: int) -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(status, json={"message": "busy"})
            )
        ),
    )

    with pytest.raises(RetryableWorkflowExecutionError):
        executor.execute_optional(lease, request)

    assert repository.finished[0][2]["status"] == "failed"
    assert repository.finished[0][2]["retryable"] is True


def test_authentication_failure_is_terminal_and_actionable() -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(401, json={"message": "invalid token"})
            )
        ),
    )

    with pytest.raises(WorkflowAuthenticationError, match="rejected"):
        executor.execute_optional(lease, request)
    assert repository.finished[0][2]["error_code"] == "dify_auth_rejected"


def test_no_active_binding_is_the_only_native_fallback_signal() -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    repository.resolve_active = lambda **_: None
    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("called"))),
    )
    assert executor.execute_optional(lease, request) is None
    assert repository.started == []


def test_required_active_binding_fails_instead_of_using_native_runtime() -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    repository.resolve_active = lambda **_: None
    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        require_active=True,
    )
    with pytest.raises(Exception, match="no active workflow"):
        executor.execute_optional(lease, request)


def test_canary_business_validator_runs_before_success_is_recorded() -> None:
    release, request, _lease = release_and_request()
    repository = FakeRepository(release)

    def success_response(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "workflow_run_id": "canary-run",
                "data": {
                    "workflow_id": release.dify_workflow_id,
                    "status": "succeeded",
                    "outputs": {"result": json.dumps({"questions": []})},
                },
            },
        )

    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(transport=httpx.MockTransport(success_response)),
    )

    def reject_output(_output) -> None:
        raise WorkflowContractError(
            "question canary returned no usable cases",
            code="question_canary_invalid",
        )

    with pytest.raises(WorkflowContractError, match="no usable cases"):
        executor.execute_canary(
            project_id=release.project_id,
            release_id=release.id,
            request=request,
            validate_output=reject_output,
        )

    assert repository.finished[0][2]["status"] == "failed"
    assert repository.finished[0][2]["error_code"] == "question_canary_invalid"
    assert repository.finished[0][2]["dify_run_id"] == "canary-run"
    assert repository.finished[0][2]["reported_workflow_id"] == "workflow-one"
    assert repository.finished[0][2]["http_status"] == 200


def test_business_schema_failure_is_recorded_before_attempt_success() -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "workflow_run_id": "bad-schema-run",
                        "data": {
                            "workflow_id": release.dify_workflow_id,
                            "status": "succeeded",
                            "outputs": {"result": json.dumps({"wrong": []})},
                        },
                    },
                )
            )
        ),
    )

    with pytest.raises(WorkflowContractError, match="business schema"):
        executor.execute_optional(lease, request)

    assert repository.finished[0][2]["status"] == "failed"
    assert repository.finished[0][2]["error_code"] == "dify_business_schema_invalid"
    assert repository.finished[0][2]["dify_run_id"] == "bad-schema-run"
    assert repository.finished[0][2]["http_status"] == 200


def test_malformed_model_json_is_retryable_and_preserves_response_lineage() -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "task_id": "malformed-task",
                        "workflow_run_id": "malformed-run",
                        "data": {
                            "workflow_id": release.dify_workflow_id,
                            "status": "succeeded",
                            "outputs": {"result": '{"questions": []}}'},
                        },
                    },
                )
            )
        ),
    )

    with pytest.raises(RetryableWorkflowExecutionError, match="malformed JSON"):
        executor.execute_optional(lease, request)

    failure = repository.finished[0][2]
    assert failure["status"] == "failed"
    assert failure["retryable"] is True
    assert failure["error_code"] == "dify_output_not_json"
    assert failure["dify_task_id"] == "malformed-task"
    assert failure["dify_run_id"] == "malformed-run"
    assert failure["reported_workflow_id"] == release.dify_workflow_id
    assert failure["http_status"] == 200


def test_request_hash_rejects_non_hex_text() -> None:
    _release, request, _lease = release_and_request()

    with pytest.raises(WorkflowContractError, match="must be SHA-256"):
        WorkflowExecutionRequest(
            project_id=request.project_id,
            purpose=request.purpose,
            context=request.context,
            input_hash="z" * 64,
            output_schema=request.output_schema,
        )
