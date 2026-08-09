"""Deterministic Model Gateway retry chaining for Provider sampling."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from geo_core.model_gateway import (
    ExecuteModelCall,
    ModelCallAttemptKind,
    ModelCallTerminalStatus,
    ModelGatewayError,
    ModelGatewayErrorCode,
    RetryableModelGatewayError,
)
from geo_core.model_gateway.application_support import ModelCallExecution
from geo_core.model_gateway.contracts import ModelPolicy


class ModelCallExecutor(Protocol):
    def execute(
        self, command: ExecuteModelCall, *, policy: ModelPolicy
    ) -> ModelCallExecution: ...


def execute_provider_model_attempt_chain(
    *,
    application: ModelCallExecutor,
    initial_command: ExecuteModelCall,
    policy: ModelPolicy,
    durable_attempt_count: int,
    idempotency_prefix: str,
) -> ModelCallExecution:
    """Replay prior calls and create at most the current Durable retry attempt."""

    if durable_attempt_count < 1:
        raise ValueError("Durable attempt count must be positive")
    if not idempotency_prefix.strip():
        raise ValueError("Provider Model Call idempotency prefix is required")

    command = initial_command
    for logical_attempt in range(1, durable_attempt_count + 1):
        execution = application.execute(command, policy=policy)
        event = execution.terminal_event
        if event.status is ModelCallTerminalStatus.SUCCEEDED:
            return execution
        if event.error_retryable is not True or logical_attempt == durable_attempt_count:
            _raise_replayed_failure(execution)

        retry_number = logical_attempt + 1
        retry_key = f"{idempotency_prefix}:retry:{retry_number}"
        provider_key = (
            retry_key if initial_command.request.idempotency_key is not None else None
        )
        command = replace(
            initial_command,
            request=replace(initial_command.request, idempotency_key=provider_key),
            attempt_kind=ModelCallAttemptKind.RETRY,
            attempt_idempotency_key=retry_key,
            parent_attempt_id=execution.attempt.spec.id,
        )

    raise AssertionError("Provider Model Call retry chain did not terminate")


def _raise_replayed_failure(execution: ModelCallExecution) -> None:
    event = execution.terminal_event
    error_type = (
        RetryableModelGatewayError
        if event.error_retryable is True
        else ModelGatewayError
    )
    raise error_type(
        "replayed Provider Model Call ended in a recorded failure",
        code=event.error_code or ModelGatewayErrorCode.CONFIGURATION,
        provider=execution.attempt.spec.route.provider,
    )


__all__ = ["ModelCallExecutor", "execute_provider_model_attempt_chain"]
