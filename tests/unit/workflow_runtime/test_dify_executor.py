from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from geo_core.workflow_runtime import (
    DifyWorkflowExecutor,
    RetryableWorkflowExecutionError,
    WorkflowAuthenticationError,
    WorkflowConfigurationError,
    WorkflowContractError,
    WorkflowExecutionRequest,
    WorkflowExecutionResult,
    PublishedWorkflowSnapshotPin,
)
from geo_core.workflow_runtime.contracts import canonical_json_hash
from geo_core.workflow_runtime.errors import UnknownWorkflowOutcomeError
from tests.unit.workflow_runtime.dify_executor_test_support import (
    FakeCredentials,
    FakePublishedReader,
    FakeRepository,
    release_and_request,
)


def test_executes_blocking_workflow_and_records_exact_lineage() -> None:
    release, request, lease = release_and_request()

    def handler(message: httpx.Request) -> httpx.Response:
        assert message.headers["authorization"] == "Bearer app-secret"
        payload = json.loads(message.content)
        assert payload["response_mode"] == "blocking"
        assert json.loads(payload["inputs"]["geo_context_json"]) == request.context
        assert "geo_prompt_system" not in payload["inputs"]
        assert "geo_prompt_user" not in payload["inputs"]
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
        published_reader=FakePublishedReader(release),  # type: ignore[arg-type]
    ).execute_optional(lease, request)

    assert result is not None
    assert result.output == {"questions": []}
    assert result.dify_run_id == "run-1"
    assert result.as_model_gateway_result().provider == "dify"
    assert repository.started[0][1]["context_hash"] == request.context_hash
    assert repository.finished[0][2]["status"] == "succeeded"
    assert repository.finished[0][2]["dify_run_id"] == "run-1"
    assert repository.finished[0][2]["elapsed_seconds"] == "1.25"


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
                    "workflow_id": release.dify_workflow_id,
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
    assert repository.finished[0][2]["reported_workflow_id"] == release.dify_workflow_id
    assert result.published_snapshot_id == repository.snapshot_id
    assert result.published_snapshot_hash == "f" * 64
    assert result.as_model_gateway_result().usage_details["published_snapshot_id"] == str(
        repository.snapshot_id
    )


def test_first_canary_persists_the_actual_published_identity_for_later_pin() -> None:
    release, request, _lease = release_and_request()
    repository = FakeRepository(release)
    repository.pin = None
    published_workflow_id = "published-workflow-v2"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "workflow_run_id": "first-canary-run",
                "data": {
                    "workflow_id": published_workflow_id,
                    "status": "succeeded",
                    "outputs": {"result": json.dumps({"questions": []})},
                },
            },
        )

    result = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        published_reader=FakePublishedReader(release, workflow_id=published_workflow_id),  # type: ignore[arg-type]
    ).execute_canary(
        project_id=release.project_id,
        release_id=release.id,
        request=request,
        validate_output=lambda _: None,
    )

    assert result.published_snapshot_id == repository.snapshot_id
    assert result.published_workflow_id == published_workflow_id
    assert repository.started[0][1]["published_snapshot_id"] == repository.snapshot_id
    assert repository.finished[0][2]["reported_workflow_id"] == published_workflow_id


@pytest.mark.parametrize("reported_workflow_id", [None, "", "   "])
def test_success_without_exact_workflow_identity_fails_closed(
    reported_workflow_id: str | None,
) -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)

    def handler(_: httpx.Request) -> httpx.Response:
        data = {
            "status": "succeeded",
            "outputs": {"result": json.dumps({"questions": []})},
        }
        if reported_workflow_id is not None:
            data["workflow_id"] = reported_workflow_id
        return httpx.Response(
            200,
            json={"workflow_run_id": "missing-identity-run", "data": data},
        )

    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        published_reader=FakePublishedReader(release),  # type: ignore[arg-type]
    )

    with pytest.raises(WorkflowConfigurationError) as captured:
        executor.execute_optional(lease, request)

    assert captured.value.code == "dify_workflow_identity_missing"
    failure = repository.finished[0][2]
    assert failure["status"] == "failed"
    assert failure["reported_workflow_id"] is None
    assert failure["dify_run_id"] == "missing-identity-run"


def test_mismatched_workflow_identity_records_provider_value_not_expected_value() -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    provider_workflow_id = "unexpected-provider-workflow"
    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "workflow_run_id": "mismatch-run",
                        "data": {
                            "workflow_id": provider_workflow_id,
                            "status": "succeeded",
                            "outputs": {"result": json.dumps({"questions": []})},
                        },
                    },
                )
            )
        ),
        published_reader=FakePublishedReader(release),  # type: ignore[arg-type]
    )

    with pytest.raises(WorkflowConfigurationError) as captured:
        executor.execute_optional(lease, request)

    assert captured.value.code == "dify_workflow_identity_mismatch"
    failure = repository.finished[0][2]
    assert failure["status"] == "failed"
    assert failure["reported_workflow_id"] == provider_workflow_id
    assert failure["reported_workflow_id"] != release.dify_workflow_id


def test_business_execution_requires_a_canary_pin_and_published_reader() -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    repository.pin = None
    without_pin = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
    )
    with pytest.raises(WorkflowConfigurationError) as missing_pin:
        without_pin.execute_optional(lease, request)
    assert missing_pin.value.code == "dify_release_snapshot_not_pinned"

    repository.pin = PublishedWorkflowSnapshotPin(
        project_id=release.project_id,
        release_id=release.id,
        published_snapshot_id=repository.snapshot_id,
        workflow_id=release.dify_workflow_id,
        workflow_hash="e" * 64,
        snapshot_hash="f" * 64,
    )
    without_reader = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
    )
    with pytest.raises(WorkflowConfigurationError) as missing_reader:
        without_reader.execute_optional(lease, request)
    assert missing_reader.value.code == "dify_published_reader_required"


def test_recorded_business_result_replays_without_another_provider_call() -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    output = {"questions": []}
    repository.replay = WorkflowExecutionResult(
        output=output,
        attempt_id=uuid4(),
        runtime_release_id=release.id,
        runtime_release_hash=release.release_hash,
        dify_task_id="recorded-task",
        dify_run_id="recorded-run",
        configured_model=release.configured_model,
        provider_reported_model=release.configured_model,
        prompt_tokens=1,
        completion_tokens=1,
        total_steps=3,
        elapsed_seconds=None,
        response_hash=canonical_json_hash(output),
        published_snapshot_id=repository.snapshot_id,
        published_snapshot_hash="f" * 64,
    )
    reader = FakePublishedReader(release)
    result = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: pytest.fail("provider called during replay"))
        ),
        published_reader=reader,  # type: ignore[arg-type]
    ).execute_optional(lease, request)

    assert result == repository.replay
    assert repository.started == []
    assert repository.finished == []
    assert reader.read_count == 0


@pytest.mark.parametrize("status", [429])
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
        published_reader=FakePublishedReader(release),  # type: ignore[arg-type]
    )

    with pytest.raises(RetryableWorkflowExecutionError):
        executor.execute_optional(lease, request)

    assert repository.finished[0][2]["status"] == "failed"
    assert repository.finished[0][2]["retryable"] is True


@pytest.mark.parametrize("status", [500, 502, 503])
def test_http_5xx_is_terminal_unknown_outcome_for_non_idempotent_post(status: int) -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(status, json={"message": "provider failed"})
            )
        ),
        published_reader=FakePublishedReader(release),  # type: ignore[arg-type]
    )

    with pytest.raises(UnknownWorkflowOutcomeError) as captured:
        executor.execute_optional(lease, request)

    assert captured.value.code == "dify_unknown_outcome"
    failure = repository.finished[0][2]
    assert failure["http_status"] == status
    assert failure["error_classification"] == "unknown_outcome"
    assert failure["retryable"] is False


def test_running_attempt_blocks_a_second_provider_submission_before_graph_read() -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    repository.unresolved_attempt_id = uuid4()
    reader = FakePublishedReader(release)
    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: pytest.fail("provider called twice"))
        ),
        published_reader=reader,  # type: ignore[arg-type]
    )

    with pytest.raises(UnknownWorkflowOutcomeError, match="reconcile GEO attempt"):
        executor.execute_optional(lease, request)

    assert reader.read_count == 0
    assert repository.started == []
    assert repository.finished == []


def test_business_execution_fails_closed_when_published_graph_differs_from_pin() -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: pytest.fail("drifted graph executed"))
        ),
        published_reader=FakePublishedReader(release, snapshot_hash="0" * 64),  # type: ignore[arg-type]
    )

    with pytest.raises(WorkflowConfigurationError) as captured:
        executor.execute_optional(lease, request)

    assert captured.value.code == "dify_registered_published_identity_changed"
    assert repository.started == []


def test_business_execution_fails_closed_when_dify_ui_changes_model() -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: pytest.fail("changed model executed"))
        ),
        published_reader=FakePublishedReader(release, configured_model="deepseek-reasoner"),  # type: ignore[arg-type]
    )

    with pytest.raises(WorkflowConfigurationError) as captured:
        executor.execute_optional(lease, request)

    assert captured.value.code == "dify_published_model_mismatch"
    assert repository.started == []


@pytest.mark.parametrize(
    "error_type",
    [httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout],
)
def test_transport_failure_before_send_is_retryable_and_preserves_attempt_lineage(
    error_type: type[httpx.TransportError],
) -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)

    def fail_before_send(message: httpx.Request) -> httpx.Response:
        raise error_type("connection was not established", request=message)

    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(transport=httpx.MockTransport(fail_before_send)),
        published_reader=FakePublishedReader(release),  # type: ignore[arg-type]
    )

    with pytest.raises(RetryableWorkflowExecutionError) as captured:
        executor.execute_optional(lease, request)

    assert captured.value.code == "dify_transport_unavailable"
    assert captured.value.retryable is True
    assert len(repository.started) == len(repository.finished) == 1
    assert repository.started[0][1]["context_hash"] == request.context_hash
    assert repository.finished[0][1] == repository.attempt_id
    failure = repository.finished[0][2]
    assert failure["error_classification"] == "retryable"
    assert failure["error_code"] == "dify_transport_unavailable"
    assert failure["retryable"] is True
    assert "retry the same GEO Job" in failure["error_message"]


@pytest.mark.parametrize(
    "error_type",
    [httpx.ReadTimeout, httpx.ReadError, httpx.WriteTimeout, httpx.WriteError],
)
def test_transport_failure_after_possible_send_is_terminal_unknown_outcome(
    error_type: type[httpx.TransportError],
) -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)

    def lose_definitive_response(message: httpx.Request) -> httpx.Response:
        raise error_type("response outcome is unknown", request=message)

    executor = DifyWorkflowExecutor(
        repository=repository,
        credential_resolver=FakeCredentials(),
        base_url="http://dify-api:5001",
        client=httpx.Client(transport=httpx.MockTransport(lose_definitive_response)),
        published_reader=FakePublishedReader(release),  # type: ignore[arg-type]
    )

    with pytest.raises(UnknownWorkflowOutcomeError) as captured:
        executor.execute_optional(lease, request)

    assert captured.value.code == "dify_unknown_outcome"
    assert captured.value.retryable is False
    assert len(repository.started) == len(repository.finished) == 1
    assert repository.started[0][1]["context_hash"] == request.context_hash
    assert repository.finished[0][1] == repository.attempt_id
    failure = repository.finished[0][2]
    assert failure["error_classification"] == "unknown_outcome"
    assert failure["error_code"] == "dify_unknown_outcome"
    assert failure["retryable"] is False
    assert "Do not retry automatically" in failure["error_message"]
    assert failure["dify_task_id"] is None
    assert failure["dify_run_id"] is None


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
        published_reader=FakePublishedReader(release),  # type: ignore[arg-type]
    )

    with pytest.raises(WorkflowAuthenticationError, match="rejected"):
        executor.execute_optional(lease, request)
    assert repository.finished[0][2]["error_code"] == "dify_auth_rejected"


def test_no_active_binding_is_the_only_native_fallback_signal() -> None:
    release, request, lease = release_and_request()
    repository = FakeRepository(release)
    repository.pin = None
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
        published_reader=FakePublishedReader(release),  # type: ignore[arg-type]
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
        published_reader=FakePublishedReader(release),  # type: ignore[arg-type]
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
        published_reader=FakePublishedReader(release),  # type: ignore[arg-type]
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
