"""Idempotent, versioned manual reconciliation for unknown model-call outcomes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import re
from uuid import UUID, uuid4

from geo_core.model_gateway.application_support import (
    ModelCallAdmissionError,
    ModelCallExecution,
)
from geo_core.model_gateway.contracts import ModelGatewayErrorCode
from geo_core.model_gateway.ports import (
    ModelCallFailureClass,
    ModelCallAttempt,
    ModelCallIdempotencyConflict,
    ModelCallLineage,
    ModelCallPersistenceError,
    ModelCallReconciliationRecord,
    ModelCallTerminalEvent,
    ModelCallTerminalStatus,
    ModelCallUnitOfWorkFactory,
    ModelCallVersionConflict,
    canonical_json_hash,
    hash_secret_identifier,
)


_EVIDENCE_REFERENCE = re.compile(
    r"^[a-z][a-z0-9_.-]{0,63}:[A-Za-z0-9][A-Za-z0-9._:/-]{0,447}$"
)


@dataclass(frozen=True)
class ReconcileModelCall:
    project_id: UUID
    attempt_id: UUID
    expected_budget_version: int
    idempotency_key: str
    status: ModelCallTerminalStatus
    paid_call_consumed: bool
    reconciled_by: UUID
    evidence_ref: str
    lineage: ModelCallLineage
    provider_request_id: str | None = None
    provider_reported_model: str | None = None
    gateway_call_log_id: UUID | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: Decimal | None = None
    finish_reason: str | None = None
    output_hash: str | None = None
    response_hash: str | None = None
    error_code: ModelGatewayErrorCode | None = None
    error_retryable: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ModelCallTerminalStatus(self.status))
        if not isinstance(self.paid_call_consumed, bool):
            raise ValueError("manual reconciliation paid-call decision must be boolean")
        if min(self.project_id.int, self.attempt_id.int, self.reconciled_by.int) == 0:
            raise ValueError("manual reconciliation UUIDs cannot be zero")
        if self.expected_budget_version < 0:
            raise ValueError("manual reconciliation expected budget version cannot be negative")
        if not self.idempotency_key.strip():
            raise ValueError("manual reconciliation idempotency key cannot be empty")
        if _EVIDENCE_REFERENCE.fullmatch(self.evidence_ref) is None:
            raise ValueError("manual reconciliation requires an opaque evidence reference")


class ModelCallReconciliationService:
    def __init__(
        self,
        *,
        uow_factory: ModelCallUnitOfWorkFactory,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._id_factory = id_factory
        self._clock = clock

    def reconcile(self, command: ReconcileModelCall) -> ModelCallExecution:
        key_hash = hash_secret_identifier(command.idempotency_key)
        request_hash = reconciliation_request_hash(command)
        with self._uow_factory(project_id=command.project_id) as uow:
            replay = uow.calls.get_reconciliation_command(
                project_id=command.project_id,
                idempotency_key_hash=key_hash,
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ModelCallIdempotencyConflict(
                        "manual reconciliation idempotency key was reused"
                    )
                attempt = uow.calls.get_attempt(
                    project_id=command.project_id,
                    attempt_id=replay.attempt_id,
                )
                event = uow.calls.get_terminal_event(
                    project_id=command.project_id,
                    attempt_id=replay.attempt_id,
                )
                if attempt is None or event is None or event.id != replay.terminal_event_id:
                    raise ModelCallPersistenceError(
                        "manual reconciliation replay lineage is incomplete"
                    )
                return ModelCallExecution(attempt, event, None, replayed=True)
            attempt = uow.calls.get_attempt(
                project_id=command.project_id,
                attempt_id=command.attempt_id,
            )
            if attempt is None:
                raise ModelCallAdmissionError("model-call attempt does not exist")
            if uow.calls.get_terminal_event(
                project_id=command.project_id,
                attempt_id=command.attempt_id,
            ) is not None:
                raise ModelCallAdmissionError(
                    "model-call attempt already has an immutable terminal event"
                )
            job = uow.calls.get_job(
                project_id=command.project_id,
                job_id=attempt.spec.job_id,
            )
            if job is None:
                raise ModelCallAdmissionError("model-call Job admission does not exist")
            if job.budget_version != command.expected_budget_version:
                raise ModelCallVersionConflict(
                    "manual reconciliation budget version changed concurrently"
                )
            occurred_at = self._clock()
            event = reconciliation_event(
                event_id=self._id_factory(),
                occurred_at=occurred_at,
                attempt=attempt,
                command=command,
            )
            uow.calls.append_terminal_event(
                event=event,
                expected_budget_version=command.expected_budget_version,
            )
            uow.calls.add_reconciliation_command(
                ModelCallReconciliationRecord(
                    id=self._id_factory(),
                    project_id=command.project_id,
                    attempt_id=attempt.spec.id,
                    terminal_event_id=event.id,
                    reconciled_by=command.reconciled_by,
                    idempotency_key_hash=key_hash,
                    request_hash=request_hash,
                    expected_budget_version=command.expected_budget_version,
                    recorded_at=occurred_at,
                )
            )
            uow.commit()
            return ModelCallExecution(attempt, event, None, replayed=False)


def reconciliation_request_hash(command: ReconcileModelCall) -> str:
    return canonical_json_hash(
        {
            "project_id": command.project_id,
            "attempt_id": command.attempt_id,
            "expected_budget_version": command.expected_budget_version,
            "status": command.status,
            "paid_call_consumed": command.paid_call_consumed,
            "reconciled_by": command.reconciled_by,
            "evidence_ref": command.evidence_ref,
            "lineage": command.lineage.__dict__,
            "provider_request_id": command.provider_request_id,
            "provider_reported_model": command.provider_reported_model,
            "gateway_call_log_id": command.gateway_call_log_id,
            "prompt_tokens": command.prompt_tokens,
            "completion_tokens": command.completion_tokens,
            "cost_usd": command.cost_usd,
            "finish_reason": command.finish_reason,
            "output_hash": command.output_hash,
            "response_hash": command.response_hash,
            "error_code": command.error_code,
            "error_retryable": command.error_retryable,
        }
    )


def reconciliation_event(
    *,
    event_id: UUID,
    occurred_at: datetime,
    attempt: ModelCallAttempt,
    command: ReconcileModelCall,
) -> ModelCallTerminalEvent:
    failed = command.status is ModelCallTerminalStatus.FAILED
    return ModelCallTerminalEvent(
        id=event_id,
        project_id=command.project_id,
        job_id=attempt.spec.job_id,
        attempt_id=attempt.spec.id,
        status=command.status,
        occurred_at=occurred_at,
        paid_call_count=1 if command.paid_call_consumed else 0,
        gateway_call_log_id=command.gateway_call_log_id,
        configured_model=attempt.spec.configured_model,
        provider_reported_model=command.provider_reported_model,
        provider_request_id=command.provider_request_id,
        prompt_tokens=command.prompt_tokens,
        completion_tokens=command.completion_tokens,
        cost_usd=command.cost_usd,
        finish_reason=command.finish_reason,
        input_hash=attempt.spec.input_hash,
        output_hash=command.output_hash,
        response_hash=command.response_hash,
        lineage=command.lineage,
        error_classification=ModelCallFailureClass.MANUAL_RECONCILIATION,
        error_code=(command.error_code or ModelGatewayErrorCode.CONFIGURATION) if failed else None,
        error_retryable=(command.error_retryable or False) if failed else None,
        reconciled_by=command.reconciled_by,
        reconciliation_evidence_ref=command.evidence_ref,
    )


__all__ = [
    "ModelCallReconciliationService",
    "ReconcileModelCall",
    "reconciliation_request_hash",
]
