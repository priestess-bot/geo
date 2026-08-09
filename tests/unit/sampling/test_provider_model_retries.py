from __future__ import annotations

from dataclasses import replace

import pytest

from geo_core.model_gateway import (
    ModelCallAttemptKind,
    ModelGatewayError,
    ModelGatewayErrorCode,
    RetryableModelGatewayError,
)
from geo_core.sampling.provider_model_retries import (
    execute_provider_model_attempt_chain,
)

from tests.unit.model_gateway.model_call_application_test_support import (
    application_fixture,
)


def test_durable_retry_creates_one_linked_model_attempt_then_replays_success() -> None:
    fixture = application_fixture(maximum_paid_calls=3)
    fixture.gateway.actions[:] = [
        RetryableModelGatewayError(
            "temporary Provider failure",
            code=ModelGatewayErrorCode.RATE_LIMIT,
            provider="openai",
        ),
        fixture.result,
    ]
    prefix = "workflow-c-provider:attempt-fixture"
    initial = replace(
        fixture.command,
        attempt_idempotency_key=f"{prefix}:initial",
    )

    with pytest.raises(RetryableModelGatewayError):
        execute_provider_model_attempt_chain(
            application=fixture.application,
            initial_command=initial,
            policy=fixture.policy,
            durable_attempt_count=1,
            idempotency_prefix=prefix,
        )

    succeeded = execute_provider_model_attempt_chain(
        application=fixture.application,
        initial_command=initial,
        policy=fixture.policy,
        durable_attempt_count=2,
        idempotency_prefix=prefix,
    )
    replayed = execute_provider_model_attempt_chain(
        application=fixture.application,
        initial_command=initial,
        policy=fixture.policy,
        durable_attempt_count=3,
        idempotency_prefix=prefix,
    )

    attempts = fixture.store.attempts(
        project_id=initial.project_id,
        job_id=initial.job_id,
    )
    assert fixture.gateway.calls == 2
    assert len(attempts) == 2
    assert attempts[0].spec.kind is ModelCallAttemptKind.INITIAL
    assert attempts[1].spec.kind is ModelCallAttemptKind.RETRY
    assert attempts[1].spec.parent_attempt_id == attempts[0].spec.id
    assert succeeded.attempt.spec.id == attempts[1].spec.id
    assert replayed.attempt.spec.id == attempts[1].spec.id
    assert replayed.replayed is True


def test_replayed_non_retryable_failure_never_creates_a_retry() -> None:
    fixture = application_fixture(maximum_paid_calls=3)
    failure = ModelGatewayError(
        "invalid Provider request",
        code=ModelGatewayErrorCode.NON_RETRYABLE_VALIDATION,
        provider="openai",
    )
    fixture.gateway.actions[:] = [failure]
    prefix = "workflow-c-provider:non-retryable"
    initial = replace(
        fixture.command,
        attempt_idempotency_key=f"{prefix}:initial",
    )

    with pytest.raises(ModelGatewayError):
        execute_provider_model_attempt_chain(
            application=fixture.application,
            initial_command=initial,
            policy=fixture.policy,
            durable_attempt_count=1,
            idempotency_prefix=prefix,
        )
    with pytest.raises(ModelGatewayError, match="recorded failure"):
        execute_provider_model_attempt_chain(
            application=fixture.application,
            initial_command=initial,
            policy=fixture.policy,
            durable_attempt_count=2,
            idempotency_prefix=prefix,
        )

    attempts = fixture.store.attempts(
        project_id=initial.project_id,
        job_id=initial.job_id,
    )
    assert fixture.gateway.calls == 1
    assert len(attempts) == 1
