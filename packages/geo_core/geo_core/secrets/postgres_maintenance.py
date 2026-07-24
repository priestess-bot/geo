"""Idempotent audited master-key rewrap operations for Secret Store maintenance."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from .application_contracts import SecretRequestHasher
from .crypto import EnvelopeCipher
from .errors import (
    SecretAuthorizationError,
    SecretIdempotencyConflict,
    SecretLifecycleError,
    SecretNotFound,
    SecretScopeViolation,
)
from .models import (
    SecretAuditAction,
    SecretAuditEvent,
    SecretVersionHandle,
    SecretVersionStatus,
)
from .ports import (
    SecretActorRole,
    SecretCommandOutcome,
    SecretCommandRecord,
    SecretOperation,
    SecretPrincipal,
    SecretSurface,
)
from .postgres_repository import PsycopgSecretRepository
from .postgres_uow import PostgresSecretUnitOfWorkFactory


class PostgresSecretMaintenance:
    __secret_bearing__ = True

    def __init__(
        self,
        *,
        uow_factory: PostgresSecretUnitOfWorkFactory,
        cipher: EnvelopeCipher,
        request_hasher: SecretRequestHasher,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._uow_factory = uow_factory
        self._cipher = cipher
        self._request_hasher = request_hasher
        self._clock = clock
        self._id_factory = id_factory

    def rewrap(
        self,
        principal: SecretPrincipal,
        *,
        handle: SecretVersionHandle,
        idempotency_key: str,
    ) -> SecretCommandOutcome:
        _require_maintenance_principal(principal, handle)
        key_hash = self._request_hasher.idempotency_key_hash(idempotency_key)
        request_hash = self._request_hasher.request_hash(
            operation=SecretOperation.REWRAP,
            metadata={
                "actor_id": str(principal.actor_id),
                "project_id": str(handle.project_id),
                "reference_id": str(handle.reference_id),
                "purpose": handle.purpose,
                "version": handle.version,
                "target_master_key_version": self._cipher.active_master_key_version,
            },
        )
        now = self._clock()
        with self._uow_factory.create_postgres(handle.project_id) as unit_of_work:
            replay = unit_of_work.commands.get(key_hash)
            if replay is not None:
                if (
                    replay.operation is not SecretOperation.REWRAP
                    or replay.request_hash != request_hash
                ):
                    raise SecretIdempotencyConflict(
                        "Secret Store Idempotency-Key request hash does not match"
                    )
                return replace(replay.outcome, replayed=True)
            aggregate = unit_of_work.secrets.get(handle.reference_id)
            if aggregate is None:
                raise SecretNotFound("secret reference was not found")
            stored = aggregate.require_version(handle.version)
            if stored.handle != handle:
                raise SecretScopeViolation(
                    "secret handle does not match stored version scope"
                )
            if stored.status is SecretVersionStatus.REVOKED:
                raise SecretLifecycleError("revoked secret version cannot be rewrapped")
            if (
                stored.envelope.master_key_version
                == self._cipher.active_master_key_version
            ):
                raise SecretLifecycleError(
                    "secret version already uses the active master key"
                )
            rewrapped = self._cipher.rewrap(stored.envelope)
            repository = cast(PsycopgSecretRepository, unit_of_work.secrets)
            repository.rewrap(rewrapped)
            outcome = SecretCommandOutcome(
                handle=handle,
                aggregate_version=aggregate.aggregate_version,
                status=stored.status,
            )
            unit_of_work.audits.append(
                SecretAuditEvent(
                    id=self._id_factory(),
                    reference_id=handle.reference_id,
                    project_id=handle.project_id,
                    purpose=handle.purpose,
                    version=handle.version,
                    action=SecretAuditAction.VERSION_REWRAPPED,
                    actor_id=principal.actor_id,
                    occurred_at=now,
                    master_key_version=rewrapped.master_key_version,
                )
            )
            unit_of_work.commands.add(
                SecretCommandRecord(
                    project_id=handle.project_id,
                    operation=SecretOperation.REWRAP,
                    idempotency_key_hash=key_hash,
                    request_hash=request_hash,
                    outcome=outcome,
                    recorded_at=now,
                )
            )
            unit_of_work.commit()
            return outcome


def _require_maintenance_principal(
    principal: SecretPrincipal, handle: SecretVersionHandle
) -> None:
    if (
        principal.project_id != handle.project_id
        or principal.role not in {SecretActorRole.OWNER, SecretActorRole.ADMIN}
        or principal.surface is not SecretSurface.ADMIN
    ):
        raise SecretAuthorizationError(
            "Secret Store rewrap requires a project owner or admin"
        )


__all__ = ["PostgresSecretMaintenance"]
