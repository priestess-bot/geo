"""Shared command, authorization and Durable Job guards for Synthetic Lab apps."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import json
from typing import Iterable, Mapping, TypeVar, cast
from uuid import UUID

from geo_core.jobs.lifecycle import (
    DomainJobSpec,
    DurableJob,
    InvalidTransition,
    JobStatus,
    LeaseConflict,
    claim,
    complete,
)
from geo_core.synthetic_lab.authorization import AuthorizationBinding
from geo_core.synthetic_lab.corpus import FinalizationGuard
from geo_core.synthetic_lab.ports import (
    CommandReceipt,
    LabPrincipal,
    LabRole,
    RuntimeInputPort,
    RuntimeInputSnapshot,
    SyntheticCommandIdentity,
    SyntheticCommandOperation,
    SyntheticCommandRecord,
    SyntheticLabIdempotencyConflict,
    SyntheticLabJobOwnershipLost,
    SyntheticLabPermissionDenied,
    SyntheticLabStaleInput,
    SyntheticLabUnitOfWork,
    SyntheticOutboxMessage,
    SyntheticJob,
)


_ResultT = TypeVar("_ResultT")


@dataclass(frozen=True, kw_only=True)
class JobWriteOwnership:
    lease_id: UUID
    fencing_token: int

    def __post_init__(self) -> None:
        if self.fencing_token < 1:
            raise ValueError("held fencing token must be positive")


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def command_identity(
    *,
    project_id: UUID,
    idempotency_key: str,
    operation: SyntheticCommandOperation,
    request: object,
) -> SyntheticCommandIdentity:
    key = idempotency_key.strip()
    if not key:
        raise ValueError("Idempotency-Key is required")
    return SyntheticCommandIdentity(
        project_id=project_id,
        idempotency_key_hash=hashlib.sha256(key.encode("utf-8")).hexdigest(),
        operation=operation,
        request_hash=canonical_hash(request),
    )


def recover_command(
    uow: SyntheticLabUnitOfWork,
    identity: SyntheticCommandIdentity,
    result_type: type[_ResultT],
) -> CommandReceipt | None:
    existing = uow.commands.get(
        project_id=identity.project_id,
        idempotency_key_hash=identity.idempotency_key_hash,
    )
    if existing is None:
        return None
    if existing.identity != identity:
        raise SyntheticLabIdempotencyConflict(
            "Idempotency-Key was reused with another operation or request hash"
        )
    if not isinstance(existing.result, result_type):
        raise SyntheticLabIdempotencyConflict("Synthetic Lab command result type changed")
    return CommandReceipt(existing.result, replayed=True)


def stage_command(
    uow: SyntheticLabUnitOfWork,
    identity: SyntheticCommandIdentity,
    result: object,
) -> CommandReceipt:
    uow.commands.stage(SyntheticCommandRecord(identity, result))
    uow.commit()
    return CommandReceipt(result, replayed=False)


def require_roles(principal: LabPrincipal, project_id: UUID, *roles: LabRole) -> None:
    if principal.project_id != project_id:
        raise SyntheticLabPermissionDenied("Synthetic Lab actor belongs to another Project")
    allowed = frozenset(roles)
    if not principal.roles.intersection(allowed):
        raise SyntheticLabPermissionDenied(
            "Synthetic Lab command requires one of: "
            + ", ".join(sorted(role.value for role in allowed))
        )


def reject_self_approval(principal: LabPrincipal, submitted_by: UUID) -> None:
    if principal.actor_id == submitted_by:
        raise SyntheticLabPermissionDenied(
            "Synthetic Lab submitter cannot approve or freeze their own resource"
        )


def assert_runtime_ready(snapshot: RuntimeInputSnapshot) -> None:
    if not snapshot.facts_current_approved:
        raise SyntheticLabStaleInput("approved Fact snapshot is stale or inactive")
    if not snapshot.profile_frozen:
        raise SyntheticLabStaleInput("Style Profile is not frozen or is stale")
    if not snapshot.prompt_frozen:
        raise SyntheticLabStaleInput("Prompt Release is not frozen or is stale")


def assert_runtime_current(
    frozen: RuntimeInputSnapshot,
    port: RuntimeInputPort,
) -> RuntimeInputSnapshot:
    current = port.current(frozen)
    frozen_identity = (
        frozen.project_id,
        frozen.fact_snapshot_id,
        frozen.fact_snapshot_hash,
        frozen.profile_version_id,
        frozen.profile_hash,
        frozen.prompt_release_id,
        frozen.prompt_release_hash,
    )
    current_identity = (
        current.project_id,
        current.fact_snapshot_id,
        current.fact_snapshot_hash,
        current.profile_version_id,
        current.profile_hash,
        current.prompt_release_id,
        current.prompt_release_hash,
    )
    if frozen_identity != current_identity:
        raise SyntheticLabStaleInput("frozen Fact/Profile/Prompt identity or hash changed")
    assert_runtime_ready(current)
    return current


def assert_terminal_write(
    job: SyntheticJob,
    *,
    ownership: JobWriteOwnership,
    runtime_port: RuntimeInputPort | None,
    at: datetime,
) -> RuntimeInputSnapshot | None:
    if job.status not in {JobStatus.RUNNING, JobStatus.FINALIZING}:
        raise SyntheticLabJobOwnershipLost("only a running Job can write a terminal result")
    if job.cancel_requested:
        raise SyntheticLabJobOwnershipLost("cancelled Job cannot write a terminal result")
    if job.lease_id != ownership.lease_id or job.fencing_token != ownership.fencing_token:
        raise SyntheticLabJobOwnershipLost("Job lease or fencing token is stale")
    if job.durable.lease_expires_at is None or job.durable.lease_expires_at <= at:
        raise SyntheticLabJobOwnershipLost("Job lease expired before the terminal write")
    if job.runtime_inputs is None:
        return None
    if runtime_port is None:
        raise SyntheticLabStaleInput("terminal write requires a runtime input recheck port")
    return assert_runtime_current(job.runtime_inputs, runtime_port)


def finalization_guard(
    job: SyntheticJob,
    *,
    resource_id: UUID,
    ownership: JobWriteOwnership,
    current: RuntimeInputSnapshot,
) -> FinalizationGuard:
    return FinalizationGuard(
        project_id=job.project_id,
        resource_id=resource_id,
        expected_lease_id=job.lease_id,  # type: ignore[arg-type]
        held_lease_id=ownership.lease_id,
        expected_fencing_token=job.fencing_token,
        held_fencing_token=ownership.fencing_token,
        fact_snapshot_id=current.fact_snapshot_id,
        fact_snapshot_hash=current.fact_snapshot_hash,
        facts_current_approved=current.facts_current_approved,
        cancelled=job.cancel_requested,
    )


def new_outbox_message(
    *,
    message_id: UUID,
    job: SyntheticJob,
    event_type: str,
) -> SyntheticOutboxMessage:
    return SyntheticOutboxMessage(
        id=message_id,
        project_id=job.project_id,
        job_id=job.id,
        event_type=event_type,
        payload_hash=canonical_hash(
            {
                "project_id": job.project_id,
                "job_id": job.id,
                "kind": job.kind,
                "input_hash": job.input_hash,
            }
        ),
    )


def new_synthetic_job(
    *,
    job_id: UUID,
    project_id: UUID,
    kind: str,
    input_hash: str,
    idempotency_key_hash: str,
    payload: Mapping[str, object],
    runtime_inputs: RuntimeInputSnapshot | None,
    authorization_binding: AuthorizationBinding | None = None,
) -> SyntheticJob:
    return SyntheticJob(
        durable=DurableJob(
            id=job_id,
            project_id=project_id,
            spec=DomainJobSpec(kind=kind, payload=payload),
            input_hash=input_hash,
            idempotency_key=idempotency_key_hash,
        ),
        runtime_inputs=runtime_inputs,
        authorization_binding=authorization_binding,
    )


def claim_synthetic_job(
    job: SyntheticJob,
    *,
    worker_id: str,
    at: datetime,
    lease_for: timedelta,
) -> SyntheticJob:
    try:
        durable = claim(job.durable, worker_id=worker_id, now=at, lease_for=lease_for)
    except InvalidTransition as error:
        raise SyntheticLabJobOwnershipLost(str(error)) from error
    return SyntheticJob(
        durable=durable,
        runtime_inputs=job.runtime_inputs,
        authorization_binding=job.authorization_binding,
        version=job.version + 1,
    )


def complete_synthetic_job(
    job: SyntheticJob,
    *,
    ownership: JobWriteOwnership,
    at: datetime,
    result_ref: str,
) -> SyntheticJob:
    if job.cancel_requested:
        raise SyntheticLabJobOwnershipLost("cancelled Job cannot write a terminal result")
    try:
        durable = complete(
            job.durable,
            token=ownership.lease_id,
            generation=ownership.fencing_token,
            now=at,
            result_ref=result_ref,
        )
    except (LeaseConflict, InvalidTransition) as error:
        raise SyntheticLabJobOwnershipLost(str(error)) from error
    return SyntheticJob(
        durable=durable,
        runtime_inputs=job.runtime_inputs,
        authorization_binding=job.authorization_binding,
        version=job.version + 1,
    )


def _canonical_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _canonical_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        converted = [_canonical_value(item) for item in cast(Iterable[object], value)]
        if isinstance(value, (set, frozenset)):
            return sorted(converted, key=lambda item: json.dumps(item, sort_keys=True))
        return converted
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"value of type {type(value).__name__} is not canonically serializable")


__all__ = [
    "JobWriteOwnership",
    "assert_runtime_current",
    "assert_runtime_ready",
    "assert_terminal_write",
    "canonical_hash",
    "claim_synthetic_job",
    "command_identity",
    "complete_synthetic_job",
    "finalization_guard",
    "new_outbox_message",
    "new_synthetic_job",
    "recover_command",
    "reject_self_approval",
    "require_roles",
    "stage_command",
]
