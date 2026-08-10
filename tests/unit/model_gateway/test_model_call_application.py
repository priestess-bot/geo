from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from geo_core.model_gateway import (
    ModelCallBudgetExceeded,
    ModelCallConcurrencyExceeded,
    ModelGatewayErrorCode,
    ModelPolicy,
    ModelRouteError,
    ProviderPolicyViolation,
    RetryableModelGatewayError,
    StructuredOutputValidationError,
)
from geo_core.model_gateway.application import (
    ExecuteModelCall,
    ModelCallAdmissionError,
    ModelCallUnknownOutcome,
    ReconcileModelCall,
)
from geo_core.model_gateway.application_support import maximum_paid_calls_per_attempt
from geo_core.model_gateway.ports import (
    ModelCallAttemptKind,
    ModelCallFailureClass,
    ModelCallIdempotencyConflict,
    ModelCallPersistenceError,
    ModelCallTerminalStatus,
    ModelCallVersionConflict,
    canonical_json_hash,
    hash_secret_identifier,
)

from .model_call_application_test_support import (
    PROMPT_TEST_CASE_HASH,
    PROMPT_TEST_CASE_ID,
    PROMPT_TEST_SET_HASH,
    SECRET_MARKER,
    application_fixture,
    empty_lineage_for,
)


def test_attempt_paid_call_ceiling_is_one_for_supported_providers() -> None:
    assert maximum_paid_calls_per_attempt("deepseek") == 1
    assert maximum_paid_calls_per_attempt("openai") == 1
    assert maximum_paid_calls_per_attempt("gemini") == 1


def test_prompt_release_test_freezes_current_draft_set_and_case_on_attempt() -> None:
    fixture = application_fixture(prompt_test=True)

    receipt = fixture.application.execute(fixture.command, policy=fixture.policy)

    spec = receipt.attempt.spec
    assert spec.prompt_binding_id is None
    assert spec.prompt_test_set_hash == PROMPT_TEST_SET_HASH
    assert spec.prompt_test_case_id == PROMPT_TEST_CASE_ID
    assert spec.prompt_test_case_hash == PROMPT_TEST_CASE_HASH


def test_prompt_release_test_rejects_stale_draft_or_changed_test_set_before_io() -> None:
    stale = application_fixture(prompt_test=True, prompt_frozen=False)
    with pytest.raises(ModelCallAdmissionError, match="exact frozen"):
        stale.application.execute(stale.command, policy=stale.policy)
    assert stale.gateway.calls == 0

    changed = application_fixture(prompt_test=True)
    with pytest.raises(ModelCallAdmissionError):
        changed.application.execute(
            replace(changed.command, prompt_test_set_hash="f" * 64),
            policy=changed.policy,
        )
    assert changed.gateway.calls == 0


def test_runtime_prompt_command_rejects_draft_test_lineage_at_construction() -> None:
    fixture = application_fixture()
    with pytest.raises(ValueError, match="runtime model calls"):
        replace(fixture.command, prompt_state_id=fixture.command.prompt_release_id)


def test_success_reserves_before_io_and_persists_only_hashed_content() -> None:
    fixture = application_fixture()
    observed: list[bool] = []

    def assert_reserved_before_call() -> None:
        attempts = fixture.store.attempts(
            project_id=fixture.command.project_id,
            job_id=fixture.command.job_id,
        )
        assert len(attempts) == 1
        assert (
            fixture.store.terminal_event(
                project_id=fixture.command.project_id,
                attempt_id=attempts[0].spec.id,
            )
            is None
        )
        job = fixture.store.job(
            project_id=fixture.command.project_id,
            job_id=fixture.command.job_id,
        )
        assert job is not None
        assert (job.paid_calls, job.reserved_calls) == (0, 1)
        observed.append(True)

    fixture.gateway.before_call = assert_reserved_before_call
    receipt = fixture.application.execute(fixture.command, policy=fixture.policy)

    assert observed == [True]
    assert fixture.gateway.routes == [fixture.route]
    assert receipt.replayed is False
    assert receipt.result == fixture.result
    event = receipt.terminal_event
    assert event.status is ModelCallTerminalStatus.SUCCEEDED
    assert event.provider_request_id == "provider-request-fixture"
    assert event.provider_reported_model == "fixture-openai-model-reported"
    assert (event.prompt_tokens, event.completion_tokens) == (37, 11)
    assert str(event.cost_usd) == "0.0042"
    assert event.finish_reason == "completed"
    assert event.output_hash == canonical_json_hash(fixture.result.output)
    assert event.response_hash == fixture.result.response_hash
    assert event.lineage.citation_count == 1
    assert event.lineage.search_event_count == 1
    assert event.lineage.citation_lineage_hash == canonical_json_hash(fixture.result.citations)
    assert event.lineage.search_lineage_hash == canonical_json_hash(fixture.result.tool_events)
    job = fixture.store.job(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )
    assert job is not None
    assert (job.paid_calls, job.reserved_calls) == (1, 0)
    persisted = repr((receipt.attempt, receipt.terminal_event, job))
    assert SECRET_MARKER not in persisted
    assert fixture.command.attempt_idempotency_key not in persisted
    assert "messages" not in receipt.attempt.spec.__dict__
    assert "secret" not in receipt.attempt.spec.__dict__
    assert "output" not in receipt.terminal_event.__dict__
    assert "citations" not in receipt.terminal_event.__dict__
    assert "tool_events" not in receipt.terminal_event.__dict__


def test_completed_idempotency_replay_never_calls_or_charges_again() -> None:
    fixture = application_fixture()
    first = fixture.application.execute(fixture.command, policy=fixture.policy)

    replay = fixture.application.execute(fixture.command, policy=fixture.policy)

    assert replay.replayed is True
    assert replay.result is None
    assert replay.attempt == first.attempt
    assert replay.terminal_event == first.terminal_event
    assert fixture.gateway.calls == 1
    job = fixture.store.job(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )
    assert job is not None and job.paid_calls == 1


def test_idempotency_key_cannot_be_reused_for_changed_messages() -> None:
    fixture = application_fixture()
    fixture.application.execute(fixture.command, policy=fixture.policy)
    changed = replace(
        fixture.command,
        request=replace(
            fixture.command.request,
            messages=({"role": "user", "content": "A different immutable input"},),
        ),
    )

    with pytest.raises(ModelCallIdempotencyConflict):
        fixture.application.execute(changed, policy=fixture.policy)

    assert fixture.gateway.calls == 1


@pytest.mark.parametrize(
    "changed_command",
    (
        lambda command: replace(command, lease_token=command.prompt_binding_id),
        lambda command: replace(command, prompt_release_hash="c" * 64),
        lambda command: replace(
            command,
            request=replace(command.request, purpose="metric_judge"),
        ),
        lambda command: replace(
            command,
                request=replace(
                    command.request,
                    output_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["other"],
                        "properties": {"other": {"type": "string"}},
                    },
                    application_output_schema={
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["other"],
                        "properties": {"other": {"type": "string"}},
                    },
                ),
        ),
    ),
)
def test_exact_job_prompt_purpose_and_schema_admission_fail_before_reservation(
    changed_command: Callable[[ExecuteModelCall], ExecuteModelCall],
) -> None:
    fixture = application_fixture()

    with pytest.raises(ModelCallAdmissionError):
        fixture.application.execute(changed_command(fixture.command), policy=fixture.policy)

    assert fixture.gateway.calls == 0
    assert (
        fixture.store.attempts(
            project_id=fixture.command.project_id,
            job_id=fixture.command.job_id,
        )
        == ()
    )


def test_unfrozen_prompt_release_is_never_admitted() -> None:
    fixture = application_fixture(prompt_frozen=False)

    with pytest.raises(ModelCallAdmissionError, match="exact frozen"):
        fixture.application.execute(fixture.command, policy=fixture.policy)

    assert fixture.gateway.calls == 0
    assert (
        fixture.store.attempts(
            project_id=fixture.command.project_id,
            job_id=fixture.command.job_id,
        )
        == ()
    )


def test_model_call_requires_the_exact_versioned_project_policy() -> None:
    fixture = application_fixture()

    with pytest.raises(ModelCallAdmissionError, match="project policy version"):
        fixture.application.execute(fixture.command, policy=ModelPolicy())

    wrong_policy = ModelPolicy(
        allowed_providers=fixture.policy.allowed_providers,
        allowed_adapter_release_ids=fixture.policy.allowed_adapter_release_ids,
        policy_version_id=fixture.command.prompt_binding_id,
        maximum_paid_calls=fixture.policy.maximum_paid_calls,
        maximum_concurrent_calls=fixture.policy.maximum_concurrent_calls,
    )
    with pytest.raises(ModelCallAdmissionError, match="exact frozen"):
        fixture.application.execute(fixture.command, policy=wrong_policy)

    assert fixture.gateway.calls == 0
    assert fixture.store.attempts(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    ) == ()


def test_unregistered_release_hash_is_rejected_before_reservation() -> None:
    fixture = application_fixture()
    changed = replace(
        fixture.command,
        route=replace(fixture.command.route, adapter_release_hash="0" * 64),
    )

    with pytest.raises(ModelRouteError, match="release hash"):
        fixture.application.execute(changed, policy=fixture.policy)

    assert fixture.gateway.calls == 0
    assert (
        fixture.store.attempts(
            project_id=fixture.command.project_id,
            job_id=fixture.command.job_id,
        )
        == ()
    )


def test_unknown_paid_outcome_blocks_replay_until_manual_reconciliation() -> None:
    timeout = RetryableModelGatewayError(
        "socket outcome unavailable",
        code=ModelGatewayErrorCode.TIMEOUT,
        provider="openai",
    )
    fixture = application_fixture(actions=[timeout])

    with pytest.raises(ModelCallUnknownOutcome) as captured:
        fixture.application.execute(fixture.command, policy=fixture.policy)

    attempt = fixture.store.attempts(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )[0]
    assert captured.value.attempt_id == attempt.spec.id
    assert (
        fixture.store.terminal_event(
            project_id=fixture.command.project_id,
            attempt_id=attempt.spec.id,
        )
        is None
    )
    with pytest.raises(ModelCallUnknownOutcome):
        fixture.application.execute(fixture.command, policy=fixture.policy)
    assert fixture.gateway.calls == 1

    reconciled = fixture.application.reconcile(
        ReconcileModelCall(
            project_id=fixture.command.project_id,
            attempt_id=attempt.spec.id,
            expected_budget_version=1,
            idempotency_key="reconcile-timeout-fixture",
            status=ModelCallTerminalStatus.FAILED,
            paid_call_consumed=True,
            reconciled_by=fixture.command.prompt_binding_id,
            evidence_ref="operator:provider-console:request-not-completed",
            lineage=empty_lineage_for(fixture.command),
            error_code=ModelGatewayErrorCode.TIMEOUT,
            error_retryable=False,
        )
    )
    assert reconciled.terminal_event.reconciliation_evidence_ref is not None
    assert reconciled.terminal_event.paid_call_count == 1
    replay = fixture.application.execute(fixture.command, policy=fixture.policy)
    assert replay.replayed is True
    assert fixture.gateway.calls == 1


def test_unresolved_call_consumes_concurrency_until_reconciled() -> None:
    timeout = RetryableModelGatewayError(
        "socket outcome unavailable",
        code=ModelGatewayErrorCode.TIMEOUT,
        provider="openai",
    )
    fixture = application_fixture(
        actions=[timeout],
        maximum_paid_calls=2,
        maximum_concurrent_calls=1,
    )

    with pytest.raises(ModelCallUnknownOutcome):
        fixture.application.execute(fixture.command, policy=fixture.policy)
    another = replace(
        fixture.command,
        attempt_idempotency_key="another-concurrent-model-call",
    )
    with pytest.raises(ModelCallConcurrencyExceeded):
        fixture.application.execute(another, policy=fixture.policy)

    assert fixture.gateway.calls == 1


def test_successful_manual_reconciliation_is_paired_and_paid() -> None:
    timeout = RetryableModelGatewayError(
        "socket outcome unavailable",
        code=ModelGatewayErrorCode.TIMEOUT,
        provider="openai",
    )
    fixture = application_fixture(actions=[timeout])
    with pytest.raises(ModelCallUnknownOutcome):
        fixture.application.execute(fixture.command, policy=fixture.policy)
    attempt = fixture.store.attempts(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )[0]
    command = ReconcileModelCall(
        project_id=fixture.command.project_id,
        attempt_id=attempt.spec.id,
        expected_budget_version=1,
        idempotency_key="reconcile-success-fixture",
        status=ModelCallTerminalStatus.SUCCEEDED,
        paid_call_consumed=True,
        reconciled_by=fixture.command.prompt_binding_id,
        evidence_ref="operator:provider-console:completed",
        lineage=empty_lineage_for(fixture.command),
        output_hash="8" * 64,
        response_hash="9" * 64,
    )

    reconciled = fixture.application.reconcile(command)

    assert reconciled.terminal_event.status is ModelCallTerminalStatus.SUCCEEDED
    assert reconciled.terminal_event.error_classification is (
        ModelCallFailureClass.MANUAL_RECONCILIATION
    )
    assert reconciled.terminal_event.error_code is None
    assert reconciled.terminal_event.paid_call_count == 1
    replay = fixture.application.reconcile(command)
    assert replay.replayed is True
    assert replay.terminal_event == reconciled.terminal_event
    with pytest.raises(ModelCallIdempotencyConflict):
        fixture.application.reconcile(
            replace(command, evidence_ref="operator:provider-console:different")
        )
    invalid_fixture = application_fixture(actions=[timeout])
    with pytest.raises(ModelCallUnknownOutcome):
        invalid_fixture.application.execute(
            invalid_fixture.command,
            policy=invalid_fixture.policy,
        )
    invalid_attempt = invalid_fixture.store.attempts(
        project_id=invalid_fixture.command.project_id,
        job_id=invalid_fixture.command.job_id,
    )[0]
    with pytest.raises(ValueError, match="one paid call"):
        invalid_fixture.application.reconcile(
            replace(
                command,
                attempt_id=invalid_attempt.spec.id,
                paid_call_consumed=False,
            )
        )


def test_manual_reconciliation_rejects_stale_budget_version() -> None:
    timeout = RetryableModelGatewayError(
        "socket outcome unavailable",
        code=ModelGatewayErrorCode.TIMEOUT,
        provider="openai",
    )
    fixture = application_fixture(actions=[timeout])
    with pytest.raises(ModelCallUnknownOutcome):
        fixture.application.execute(fixture.command, policy=fixture.policy)
    attempt = fixture.store.attempts(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )[0]

    with pytest.raises(ModelCallVersionConflict, match="budget version"):
        fixture.application.reconcile(
            ReconcileModelCall(
                project_id=fixture.command.project_id,
                attempt_id=attempt.spec.id,
                expected_budget_version=0,
                idempotency_key="reconcile-stale-budget-fixture",
                status=ModelCallTerminalStatus.FAILED,
                paid_call_consumed=False,
                reconciled_by=fixture.command.prompt_release_id,
                evidence_ref="operator:provider-console:not-completed",
                lineage=empty_lineage_for(fixture.command),
                error_code=ModelGatewayErrorCode.TIMEOUT,
                error_retryable=False,
            )
        )
def test_raw_artifact_reference_is_hashed_under_the_exact_adapter_policy() -> None:
    base = application_fixture()
    raw_reference = "minio:provider-artifact/opaque-object-42"
    fixture = application_fixture(
        actions=[replace(base.result, raw_artifact_reference=raw_reference)]
    )

    receipt = fixture.application.execute(fixture.command, policy=fixture.policy)

    lineage = receipt.terminal_event.lineage
    assert lineage.raw_artifact_reference_hash == hash_secret_identifier(raw_reference)
    assert lineage.raw_artifact_policy_hash == fixture.result.raw_artifact_policy_hash
    assert lineage.raw_artifact_storage_decision == "allowed"
    assert lineage.raw_artifact_retention_days == 30
    assert raw_reference not in repr((receipt.attempt, receipt.terminal_event))


def test_reservation_commit_failure_prevents_provider_call() -> None:
    fixture = application_fixture()
    fixture.store.fail_next_commit()

    with pytest.raises(ModelCallPersistenceError, match="simulated"):
        fixture.application.execute(fixture.command, policy=fixture.policy)

    assert fixture.gateway.calls == 0
    assert (
        fixture.store.attempts(
            project_id=fixture.command.project_id,
            job_id=fixture.command.job_id,
        )
        == ()
    )


def test_terminal_commit_failure_becomes_unknown_without_automatic_recall() -> None:
    fixture = application_fixture()
    fixture.gateway.before_call = fixture.store.fail_next_commit

    with pytest.raises(ModelCallUnknownOutcome):
        fixture.application.execute(fixture.command, policy=fixture.policy)

    attempt = fixture.store.attempts(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )[0]
    assert (
        fixture.store.terminal_event(
            project_id=fixture.command.project_id,
            attempt_id=attempt.spec.id,
        )
        is None
    )
    with pytest.raises(ModelCallUnknownOutcome):
        fixture.application.execute(fixture.command, policy=fixture.policy)
    assert fixture.gateway.calls == 1


def test_known_unpaid_policy_failure_releases_budget_reservation() -> None:
    failure = ProviderPolicyViolation("fixture local policy denial", provider="openai")
    fixture = application_fixture(actions=[failure], consume_paid_call=False)

    with pytest.raises(ProviderPolicyViolation):
        fixture.application.execute(fixture.command, policy=fixture.policy)

    attempt = fixture.store.attempts(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )[0]
    event = fixture.store.terminal_event(
        project_id=fixture.command.project_id,
        attempt_id=attempt.spec.id,
    )
    assert event is not None and event.paid_call_count == 0
    job = fixture.store.job(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )
    assert job is not None
    assert (job.paid_calls, job.reserved_calls) == (0, 0)


def test_retry_uses_new_attempt_and_job_wide_paid_budget() -> None:
    unavailable = RetryableModelGatewayError(
        "known provider HTTP response",
        code=ModelGatewayErrorCode.PROVIDER_UNAVAILABLE,
        provider="openai",
        status_code=503,
    )
    fixture = application_fixture(
        actions=[unavailable, application_fixture().result],
        maximum_paid_calls=2,
    )
    with pytest.raises(RetryableModelGatewayError):
        fixture.application.execute(fixture.command, policy=fixture.policy)
    parent = fixture.store.attempts(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )[0]
    retry = replace(
        fixture.command,
        attempt_kind=ModelCallAttemptKind.RETRY,
        parent_attempt_id=parent.spec.id,
        attempt_idempotency_key="attempt-retry-fixture",
    )
    changed_retry = replace(
        retry,
        request=replace(
            retry.request,
            messages=({"role": "user", "content": "changed retry input"},),
        ),
        attempt_idempotency_key="attempt-changed-retry-fixture",
    )

    with pytest.raises(ModelCallAdmissionError, match="input hash"):
        fixture.application.execute(changed_retry, policy=fixture.policy)

    receipt = fixture.application.execute(retry, policy=fixture.policy)

    assert receipt.terminal_event.status is ModelCallTerminalStatus.SUCCEEDED
    attempts = fixture.store.attempts(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )
    assert [item.attempt_number for item in attempts] == [1, 2]
    job = fixture.store.job(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )
    assert job is not None and job.paid_calls == 2
    exhausted = replace(retry, attempt_idempotency_key="attempt-budget-exhausted")
    with pytest.raises(ModelCallBudgetExceeded):
        fixture.application.execute(exhausted, policy=fixture.policy)
    assert fixture.gateway.calls == 2


def test_application_structured_validation_is_logged_and_repair_is_budgeted() -> None:
    good = application_fixture().result
    invalid = replace(good, output={"answer": "missing required field"})
    fixture = application_fixture(actions=[invalid, good], maximum_paid_calls=2)

    with pytest.raises(StructuredOutputValidationError):
        fixture.application.execute(fixture.command, policy=fixture.policy)

    parent = fixture.store.attempts(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )[0]
    failed = fixture.store.terminal_event(
        project_id=fixture.command.project_id,
        attempt_id=parent.spec.id,
    )
    assert failed is not None
    assert failed.error_classification is ModelCallFailureClass.APPLICATION_STRUCTURED_OUTPUT
    assert failed.error_code is ModelGatewayErrorCode.SCHEMA_INVALID
    repair = replace(
        fixture.command,
        attempt_kind=ModelCallAttemptKind.REPAIR,
        parent_attempt_id=parent.spec.id,
        attempt_idempotency_key="attempt-repair-fixture",
    )

    receipt = fixture.application.execute(repair, policy=fixture.policy)

    assert receipt.terminal_event.status is ModelCallTerminalStatus.SUCCEEDED
    job = fixture.store.job(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )
    assert job is not None and job.paid_calls == 2


def test_portable_schema_pass_full_application_schema_fail_is_recorded() -> None:
    application_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer", "recommended"],
        "properties": {
            "answer": {
                "type": "string",
                "minLength": 1,
                "pattern": "^APPROVED:",
            },
            "recommended": {"type": "boolean"},
        },
    }
    fixture = application_fixture(application_output_schema=application_schema)

    with pytest.raises(StructuredOutputValidationError, match="pattern"):
        fixture.application.execute(fixture.command, policy=fixture.policy)

    attempt = fixture.store.attempts(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )[0]
    event = fixture.store.terminal_event(
        project_id=fixture.command.project_id,
        attempt_id=attempt.spec.id,
    )
    assert event is not None
    assert event.error_classification is ModelCallFailureClass.APPLICATION_STRUCTURED_OUTPUT
    assert attempt.spec.output_schema_hash != attempt.spec.application_output_schema_hash
    assert fixture.gateway.calls == 1
