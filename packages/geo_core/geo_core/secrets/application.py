"""Project-scoped Secret Store commands, authorization, and recovery preflight."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
import hmac
from uuid import UUID, uuid4

from .application_contracts import (
    ActivateSecretVersionCommand,
    CreateSecretCommand,
    ResolveSecretCommand,
    RevokeSecretVersionCommand,
    SecretRequestHasher,
    StageSecretRotationCommand,
    VerifySecretCommand,
)
from .crypto import EnvelopeCipher
from .errors import (
    SecretAuthorizationError,
    SecretConcurrencyConflict,
    SecretIdempotencyConflict,
    SecretLifecycleError,
    SecretNotFound,
    SecretScopeViolation,
)
from .models import (
    SecretAuditAction,
    SecretAuditEvent,
    SecretReference,
    SecretValue,
    SecretVersionHandle,
    SecretVersionStatus,
    require_aware_datetime,
)
from .ports import (
    SecretActorRole,
    SecretAggregate,
    SecretCommandOutcome,
    SecretCommandRecord,
    SecretOperation,
    SecretPrincipal,
    SecretReferenceMetadata,
    SecretSurface,
    SecretUnitOfWork,
    SecretUnitOfWorkFactory,
    StoredSecretVersion,
)
from .recovery_application import SecretRecoveryApplication, SecretRecoveryReadiness


class SecretApplicationService:
    __secret_bearing__ = True

    def __init__(
        self,
        *,
        uow_factory: SecretUnitOfWorkFactory,
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

    def create(self, command: CreateSecretCommand) -> SecretCommandOutcome:
        _require_admin(command.principal)
        if (
            not isinstance(command.expected_version, int)
            or isinstance(command.expected_version, bool)
            or command.expected_version != 0
        ):
            raise SecretConcurrencyConflict("new secret expected_version must be zero")
        now = self._now()
        key_hash, request_hash = self._hash_command(
            operation=SecretOperation.CREATE,
            principal=command.principal,
            idempotency_key=command.idempotency_key,
            metadata={
                "project_id": str(command.principal.project_id),
                "reference_id": str(command.reference_id),
                "purpose": command.purpose,
                "expected_version": command.expected_version,
            },
            value=command.value,
        )
        with self._uow(command.principal.project_id) as uow:
            replay = _replay(uow, key_hash, request_hash)
            if replay is not None:
                return replay
            if uow.secrets.get(command.reference_id) is not None:
                raise SecretLifecycleError("secret reference already exists")
            reference = SecretReference(
                id=command.reference_id,
                project_id=command.principal.project_id,
                purpose=command.purpose,
                created_at=now,
            )
            envelope = self._cipher.encrypt(
                reference=reference,
                version=1,
                value=command.value,
                created_at=now,
            )
            stored = StoredSecretVersion(
                envelope=envelope,
                status=SecretVersionStatus.PENDING,
                created_by=command.principal.actor_id,
            )
            aggregate = SecretAggregate(
                reference=reference,
                aggregate_version=1,
                current_version=None,
                created_by=command.principal.actor_id,
                updated_at=now,
                versions=(stored,),
            )
            outcome = SecretCommandOutcome(
                handle=envelope.handle,
                aggregate_version=1,
                status=SecretVersionStatus.PENDING,
            )
            uow.secrets.add(aggregate)
            self._audit(uow, outcome, SecretAuditAction.REFERENCE_CREATED, command.principal, now)
            self._audit(uow, outcome, SecretAuditAction.VERSION_STAGED, command.principal, now)
            _record_command(
                uow, SecretOperation.CREATE, key_hash, request_hash, outcome, now
            )
            uow.commit()
            return outcome

    def verify(self, command: VerifySecretCommand) -> SecretCommandOutcome:
        _require_admin(command.principal)
        self._require_handle_scope(command.principal, command.handle)
        return self._change_version(
            operation=SecretOperation.VERIFY,
            principal=command.principal,
            handle=command.handle,
            idempotency_key=command.idempotency_key,
            expected_version=command.expected_version,
            transition=self._verify_transition,
            audit_action=SecretAuditAction.VERSION_VERIFIED,
        )

    def stage_rotation(self, command: StageSecretRotationCommand) -> SecretCommandOutcome:
        _require_admin(command.principal)
        now = self._now()
        key_hash, request_hash = self._hash_command(
            operation=SecretOperation.ROTATE_STAGE,
            principal=command.principal,
            idempotency_key=command.idempotency_key,
            metadata={
                "project_id": str(command.principal.project_id),
                "reference_id": str(command.reference_id),
                "purpose": command.purpose,
                "expected_version": command.expected_version,
            },
            value=command.value,
        )
        with self._uow(command.principal.project_id) as uow:
            replay = _replay(uow, key_hash, request_hash)
            if replay is not None:
                return replay
            aggregate = _require_aggregate(uow, command.reference_id)
            _require_reference_scope(aggregate, command.principal.project_id, command.purpose)
            _require_expected_version(aggregate, command.expected_version)
            if aggregate.current_version is None:
                raise SecretLifecycleError("secret rotation requires an active version")
            if any(item.status is SecretVersionStatus.PENDING for item in aggregate.versions):
                raise SecretLifecycleError("secret reference already has a pending version")
            version = max(item.handle.version for item in aggregate.versions) + 1
            envelope = self._cipher.encrypt(
                reference=aggregate.reference,
                version=version,
                value=command.value,
                created_at=now,
            )
            stored = StoredSecretVersion(
                envelope=envelope,
                status=SecretVersionStatus.PENDING,
                created_by=command.principal.actor_id,
            )
            updated = replace(
                aggregate,
                aggregate_version=aggregate.aggregate_version + 1,
                updated_at=now,
                versions=aggregate.versions + (stored,),
            )
            outcome = SecretCommandOutcome(
                handle=envelope.handle,
                aggregate_version=updated.aggregate_version,
                status=stored.status,
            )
            uow.secrets.save(updated, expected_version=command.expected_version)
            self._audit(uow, outcome, SecretAuditAction.VERSION_STAGED, command.principal, now)
            _record_command(
                uow, SecretOperation.ROTATE_STAGE, key_hash, request_hash, outcome, now
            )
            uow.commit()
            return outcome

    def activate(self, command: ActivateSecretVersionCommand) -> SecretCommandOutcome:
        _require_admin(command.principal)
        self._require_handle_scope(command.principal, command.handle)
        return self._change_version(
            operation=SecretOperation.ACTIVATE,
            principal=command.principal,
            handle=command.handle,
            idempotency_key=command.idempotency_key,
            expected_version=command.expected_version,
            transition=self._activate_transition,
            audit_action=SecretAuditAction.VERSION_ACTIVATED,
        )

    def revoke(self, command: RevokeSecretVersionCommand) -> SecretCommandOutcome:
        _require_admin(command.principal)
        self._require_handle_scope(command.principal, command.handle)
        return self._change_version(
            operation=SecretOperation.REVOKE,
            principal=command.principal,
            handle=command.handle,
            idempotency_key=command.idempotency_key,
            expected_version=command.expected_version,
            transition=self._revoke_transition,
            audit_action=SecretAuditAction.VERSION_REVOKED,
        )

    def resolve(self, command: ResolveSecretCommand) -> SecretValue:
        _require_internal(command.principal)
        self._require_handle_scope(command.principal, command.handle)
        now = self._now()
        key_hash, request_hash = self._hash_command(
            operation=SecretOperation.RESOLVE,
            principal=command.principal,
            idempotency_key=command.idempotency_key,
            metadata=_handle_metadata(command.handle),
        )
        with self._uow(command.principal.project_id) as uow:
            replay = _replay(uow, key_hash, request_hash)
            aggregate = _require_aggregate(uow, command.handle.reference_id)
            stored = aggregate.require_version(command.handle.version)
            if stored.handle != command.handle:
                raise SecretScopeViolation("secret handle does not match stored version scope")
            if stored.status not in {SecretVersionStatus.ACTIVE, SecretVersionStatus.SUPERSEDED}:
                raise SecretLifecycleError("secret version is unavailable to internal consumers")
            value = self._cipher.decrypt(stored.envelope)
            if replay is None:
                outcome = SecretCommandOutcome(
                    handle=command.handle,
                    aggregate_version=aggregate.aggregate_version,
                    status=stored.status,
                )
                self._audit(
                    uow,
                    outcome,
                    SecretAuditAction.VERSION_RESOLVED,
                    command.principal,
                    now,
                )
                _record_command(
                    uow, SecretOperation.RESOLVE, key_hash, request_hash, outcome, now
                )
            uow.commit()
            return value

    def reference_metadata(
        self,
        *,
        principal: SecretPrincipal,
        reference_id: UUID,
    ) -> SecretReferenceMetadata:
        _require_admin(principal)
        with self._uow(principal.project_id) as uow:
            aggregate = _require_aggregate(uow, reference_id)
            statuses = {item.status for item in aggregate.versions}
            if aggregate.current_version is not None:
                status = "active"
            elif SecretVersionStatus.PENDING in statuses:
                status = "pending"
            elif statuses == {SecretVersionStatus.REVOKED}:
                status = "revoked"
            else:
                status = "inactive"
            return SecretReferenceMetadata(
                reference_id=aggregate.reference.id,
                project_id=aggregate.project_id,
                purpose=aggregate.reference.purpose,
                aggregate_version=aggregate.aggregate_version,
                current_version=aggregate.current_version,
                latest_version=max(item.handle.version for item in aggregate.versions),
                status=status,
                created_at=aggregate.reference.created_at,
                updated_at=aggregate.updated_at,
            )

    def _change_version(
        self,
        *,
        operation: SecretOperation,
        principal: SecretPrincipal,
        handle: SecretVersionHandle,
        idempotency_key: str,
        expected_version: int,
        transition: Callable[
            [SecretAggregate, StoredSecretVersion, SecretPrincipal, datetime],
            SecretAggregate,
        ],
        audit_action: SecretAuditAction,
    ) -> SecretCommandOutcome:
        now = self._now()
        key_hash, request_hash = self._hash_command(
            operation=operation,
            principal=principal,
            idempotency_key=idempotency_key,
            metadata={**_handle_metadata(handle), "expected_version": expected_version},
        )
        with self._uow(principal.project_id) as uow:
            replay = _replay(uow, key_hash, request_hash)
            if replay is not None:
                return replay
            aggregate = _require_aggregate(uow, handle.reference_id)
            _require_expected_version(aggregate, expected_version)
            stored = aggregate.require_version(handle.version)
            if stored.handle != handle:
                raise SecretScopeViolation("secret handle does not match stored version scope")
            updated = transition(aggregate, stored, principal, now)
            updated_stored = updated.require_version(handle.version)
            outcome = SecretCommandOutcome(
                handle=handle,
                aggregate_version=updated.aggregate_version,
                status=updated_stored.status,
            )
            uow.secrets.save(updated, expected_version=expected_version)
            self._audit(uow, outcome, audit_action, principal, now)
            _record_command(uow, operation, key_hash, request_hash, outcome, now)
            uow.commit()
            return outcome

    def _verify_transition(
        self,
        aggregate: SecretAggregate,
        stored: StoredSecretVersion,
        principal: SecretPrincipal,
        now: datetime,
    ) -> SecretAggregate:
        if stored.status is not SecretVersionStatus.PENDING or stored.verified_at is not None:
            raise SecretLifecycleError("only an unverified pending secret version can be verified")
        self._cipher.decrypt(stored.envelope)
        verified = replace(stored, verified_by=principal.actor_id, verified_at=now)
        return _update_aggregate(aggregate, verified, now)

    def _activate_transition(
        self,
        aggregate: SecretAggregate,
        stored: StoredSecretVersion,
        principal: SecretPrincipal,
        now: datetime,
    ) -> SecretAggregate:
        if stored.status is not SecretVersionStatus.PENDING or stored.verified_at is None:
            raise SecretLifecycleError("only a verified pending secret version can be activated")
        if (
            stored.created_by == principal.actor_id
            and not stored.handle.purpose.startswith(("browser_egress.", "browser_session."))
        ):
            raise SecretAuthorizationError("secret version creator cannot activate that version")
        if stored.handle.version != max(item.handle.version for item in aggregate.versions):
            raise SecretLifecycleError("only the latest pending secret version can be activated")
        versions: list[StoredSecretVersion] = []
        for item in aggregate.versions:
            if item.handle.version == stored.handle.version:
                versions.append(
                    replace(
                        item,
                        status=SecretVersionStatus.ACTIVE,
                        activated_by=principal.actor_id,
                        activated_at=now,
                    )
                )
            elif item.status is SecretVersionStatus.ACTIVE:
                versions.append(replace(item, status=SecretVersionStatus.SUPERSEDED))
            else:
                versions.append(item)
        return replace(
            aggregate,
            aggregate_version=aggregate.aggregate_version + 1,
            current_version=stored.handle.version,
            updated_at=now,
            versions=tuple(versions),
        )

    def _revoke_transition(
        self,
        aggregate: SecretAggregate,
        stored: StoredSecretVersion,
        principal: SecretPrincipal,
        now: datetime,
    ) -> SecretAggregate:
        if stored.status is SecretVersionStatus.REVOKED:
            raise SecretLifecycleError("secret version is already revoked")
        revoked = replace(
            stored,
            status=SecretVersionStatus.REVOKED,
            revoked_by=principal.actor_id,
            revoked_at=now,
        )
        versions = tuple(
            revoked if item.handle.version == revoked.handle.version else item
            for item in aggregate.versions
        )
        return replace(
            aggregate,
            aggregate_version=aggregate.aggregate_version + 1,
            current_version=(
                None
                if aggregate.current_version == stored.handle.version
                else aggregate.current_version
            ),
            updated_at=now,
            versions=versions,
        )

    def _audit(
        self,
        uow: SecretUnitOfWork,
        outcome: SecretCommandOutcome,
        action: SecretAuditAction,
        principal: SecretPrincipal,
        now: datetime,
    ) -> None:
        envelope = _require_aggregate(uow, outcome.handle.reference_id).require_version(
            outcome.handle.version
        ).envelope
        uow.audits.append(
            SecretAuditEvent(
                id=self._id_factory(),
                reference_id=outcome.handle.reference_id,
                project_id=outcome.handle.project_id,
                purpose=outcome.handle.purpose,
                version=outcome.handle.version,
                action=action,
                actor_id=principal.actor_id,
                occurred_at=now,
                master_key_version=envelope.master_key_version,
            )
        )

    def _hash_command(
        self,
        *,
        operation: SecretOperation,
        principal: SecretPrincipal,
        idempotency_key: str,
        metadata: Mapping[str, object],
        value: SecretValue | None = None,
    ) -> tuple[str, str]:
        return (
            self._request_hasher.idempotency_key_hash(idempotency_key),
            self._request_hasher.request_hash(
                operation=operation,
                metadata={**metadata, "actor_id": str(principal.actor_id)},
                value=value,
            ),
        )

    def _uow(self, project_id: UUID) -> SecretUnitOfWork:
        uow = self._uow_factory.create(project_id)
        if uow.project_id != project_id:
            raise SecretScopeViolation("Secret Store Unit of Work belongs to another project")
        return uow

    def _require_handle_scope(
        self,
        principal: SecretPrincipal,
        handle: SecretVersionHandle,
    ) -> None:
        if handle.project_id != principal.project_id:
            raise SecretScopeViolation("secret handle belongs to another project")

    def _now(self) -> datetime:
        value = self._clock()
        require_aware_datetime(value, "Secret Store application clock")
        return value


def _require_admin(principal: SecretPrincipal) -> None:
    if principal.surface is not SecretSurface.ADMIN or principal.role not in {
        SecretActorRole.OWNER,
        SecretActorRole.ADMIN,
    }:
        raise SecretAuthorizationError("Secret Store command requires an owner or admin")


def _require_internal(principal: SecretPrincipal) -> None:
    if principal.surface not in {SecretSurface.INTERNAL_API, SecretSurface.WORKER} or principal.role not in {
        SecretActorRole.OWNER,
        SecretActorRole.ADMIN,
        SecretActorRole.SERVICE,
    }:
        raise SecretAuthorizationError("secret plaintext is restricted to internal consumers")


def _require_aggregate(uow: SecretUnitOfWork, reference_id: UUID) -> SecretAggregate:
    aggregate = uow.secrets.get(reference_id)
    if aggregate is None:
        raise SecretNotFound("secret reference was not found")
    if aggregate.project_id != uow.project_id:
        raise SecretScopeViolation("secret reference belongs to another project")
    return aggregate


def _require_reference_scope(
    aggregate: SecretAggregate,
    project_id: UUID,
    purpose: str,
) -> None:
    if aggregate.project_id != project_id or aggregate.reference.purpose != purpose:
        raise SecretScopeViolation("secret reference does not match project and purpose scope")


def _require_expected_version(aggregate: SecretAggregate, expected_version: int) -> None:
    if (
        not isinstance(expected_version, int)
        or isinstance(expected_version, bool)
        or aggregate.aggregate_version != expected_version
    ):
        raise SecretConcurrencyConflict("secret aggregate expected_version is stale")


def _update_aggregate(
    aggregate: SecretAggregate,
    updated_version: StoredSecretVersion,
    now: datetime,
) -> SecretAggregate:
    versions = tuple(
        updated_version if item.handle.version == updated_version.handle.version else item
        for item in aggregate.versions
    )
    return replace(
        aggregate,
        aggregate_version=aggregate.aggregate_version + 1,
        updated_at=now,
        versions=versions,
    )


def _replay(
    uow: SecretUnitOfWork,
    idempotency_key_hash: str,
    request_hash: str,
) -> SecretCommandOutcome | None:
    existing = uow.commands.get(idempotency_key_hash)
    if existing is None:
        return None
    if not hmac.compare_digest(existing.request_hash, request_hash):
        raise SecretIdempotencyConflict("Idempotency-Key request hash does not match")
    return replace(existing.outcome, replayed=True)


def _record_command(
    uow: SecretUnitOfWork,
    operation: SecretOperation,
    idempotency_key_hash: str,
    request_hash: str,
    outcome: SecretCommandOutcome,
    now: datetime,
) -> None:
    uow.commands.add(
        SecretCommandRecord(
            project_id=uow.project_id,
            operation=operation,
            idempotency_key_hash=idempotency_key_hash,
            request_hash=request_hash,
            outcome=outcome,
            recorded_at=now,
        )
    )


def _handle_metadata(handle: SecretVersionHandle) -> dict[str, object]:
    return {
        "project_id": str(handle.project_id),
        "reference_id": str(handle.reference_id),
        "purpose": handle.purpose,
        "version": handle.version,
    }


__all__ = [
    "ActivateSecretVersionCommand", "CreateSecretCommand", "ResolveSecretCommand",
    "RevokeSecretVersionCommand", "SecretApplicationService", "SecretRecoveryApplication",
    "SecretRecoveryReadiness", "SecretRequestHasher", "StageSecretRotationCommand",
    "VerifySecretCommand",
]
