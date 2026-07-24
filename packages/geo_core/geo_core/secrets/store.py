"""Thread-safe lifecycle core for encrypted, project-scoped secret versions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import RLock
from typing import Never
from uuid import UUID, uuid4

from .crypto import EnvelopeCipher
from .errors import (
    SecretNotFound,
    SecretScopeViolation,
    SecretSerializationRejected,
    SecretStateConflict,
    SecretVersionUnavailable,
)
from .models import (
    EncryptedSecretVersion,
    SecretAuditAction,
    SecretAuditEvent,
    SecretReference,
    SecretValue,
    SecretVerificationResult,
    SecretVersionHandle,
    SecretVersionStatus,
    require_aware_datetime,
    require_uuid,
)


@dataclass(frozen=True, kw_only=True)
class _StoredVersion:
    envelope: EncryptedSecretVersion
    status: SecretVersionStatus
    verified_at: datetime | None = None


class InMemorySecretStore:
    """Persistence-neutral lifecycle implementation used by adapters and tests.

    It stores encrypted envelopes only. A PostgreSQL repository can persist the
    immutable snapshots and audit events without changing these transitions.
    """

    def __init__(
        self,
        cipher: EnvelopeCipher,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._cipher = cipher
        self._clock = clock
        self._id_factory = id_factory
        self._references: dict[UUID, SecretReference] = {}
        self._versions: dict[tuple[UUID, int], _StoredVersion] = {}
        self._current_versions: dict[UUID, int] = {}
        self._audit: list[SecretAuditEvent] = []
        self._lock = RLock()

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("Secret Store process state cannot be serialized")

    def create(
        self,
        *,
        reference_id: UUID,
        project_id: UUID,
        purpose: str,
        value: SecretValue,
        actor_id: UUID,
    ) -> SecretVersionHandle:
        now = self._now()
        reference = SecretReference(
            id=reference_id,
            project_id=project_id,
            purpose=purpose,
            created_at=now,
        )
        require_uuid(actor_id, "secret actor ID")
        with self._lock:
            if reference_id in self._references:
                raise SecretStateConflict("secret reference already exists")
            envelope = self._cipher.encrypt(
                reference=reference,
                version=1,
                value=value,
                created_at=now,
            )
            self._cipher.decrypt(envelope)
            self._references[reference_id] = reference
            self._versions[(reference_id, 1)] = _StoredVersion(
                envelope=envelope,
                status=SecretVersionStatus.ACTIVE,
                verified_at=now,
            )
            self._current_versions[reference_id] = 1
            for action in (
                SecretAuditAction.REFERENCE_CREATED,
                SecretAuditAction.VERSION_STAGED,
                SecretAuditAction.VERSION_VERIFIED,
                SecretAuditAction.VERSION_ACTIVATED,
            ):
                self._record(envelope=envelope, action=action, actor_id=actor_id, now=now)
            return envelope.handle

    def stage_version(
        self,
        *,
        reference_id: UUID,
        project_id: UUID,
        purpose: str,
        value: SecretValue,
        actor_id: UUID,
    ) -> SecretVersionHandle:
        now = self._now()
        require_uuid(actor_id, "secret actor ID")
        with self._lock:
            reference = self._scoped_reference(reference_id, project_id, purpose)
            existing = [version for candidate, version in self._versions if candidate == reference_id]
            version = max(existing, default=0) + 1
            envelope = self._cipher.encrypt(
                reference=reference,
                version=version,
                value=value,
                created_at=now,
            )
            self._versions[(reference_id, version)] = _StoredVersion(
                envelope=envelope,
                status=SecretVersionStatus.PENDING,
            )
            self._record(
                envelope=envelope,
                action=SecretAuditAction.VERSION_STAGED,
                actor_id=actor_id,
                now=now,
            )
            return envelope.handle

    def verify_version(
        self,
        handle: SecretVersionHandle,
        *,
        project_id: UUID,
        purpose: str,
        actor_id: UUID,
    ) -> SecretVerificationResult:
        now = self._now()
        require_uuid(actor_id, "secret actor ID")
        with self._lock:
            stored = self._scoped_version(handle, project_id, purpose)
            if stored.status is SecretVersionStatus.REVOKED:
                raise SecretVersionUnavailable("revoked secret version cannot be verified")
            self._cipher.decrypt(stored.envelope)
            self._versions[(handle.reference_id, handle.version)] = replace(
                stored,
                verified_at=now,
            )
            self._record(
                envelope=stored.envelope,
                action=SecretAuditAction.VERSION_VERIFIED,
                actor_id=actor_id,
                now=now,
            )
            return SecretVerificationResult(
                handle=handle,
                verified_at=now,
                master_key_version=stored.envelope.master_key_version,
            )

    def activate_version(
        self,
        handle: SecretVersionHandle,
        *,
        project_id: UUID,
        purpose: str,
        actor_id: UUID,
    ) -> None:
        now = self._now()
        require_uuid(actor_id, "secret actor ID")
        with self._lock:
            stored = self._scoped_version(handle, project_id, purpose)
            if stored.status is not SecretVersionStatus.PENDING or stored.verified_at is None:
                raise SecretStateConflict("only a verified pending secret version can be activated")
            previous_version = self._current_versions.get(handle.reference_id)
            if previous_version is not None and handle.version <= previous_version:
                raise SecretStateConflict("secret activation cannot roll back to an older version")
            if previous_version is not None:
                previous_key = (handle.reference_id, previous_version)
                previous = self._versions[previous_key]
                self._versions[previous_key] = replace(
                    previous,
                    status=SecretVersionStatus.SUPERSEDED,
                )
            self._versions[(handle.reference_id, handle.version)] = replace(
                stored,
                status=SecretVersionStatus.ACTIVE,
            )
            self._current_versions[handle.reference_id] = handle.version
            self._record(
                envelope=stored.envelope,
                action=SecretAuditAction.VERSION_ACTIVATED,
                actor_id=actor_id,
                now=now,
            )

    def rotate(
        self,
        *,
        reference_id: UUID,
        project_id: UUID,
        purpose: str,
        value: SecretValue,
        actor_id: UUID,
    ) -> SecretVersionHandle:
        """Verify and atomically switch a new version while holding the lifecycle lock."""

        with self._lock:
            handle = self.stage_version(
                reference_id=reference_id,
                project_id=project_id,
                purpose=purpose,
                value=value,
                actor_id=actor_id,
            )
            self.verify_version(
                handle,
                project_id=project_id,
                purpose=purpose,
                actor_id=actor_id,
            )
            self.activate_version(
                handle,
                project_id=project_id,
                purpose=purpose,
                actor_id=actor_id,
            )
            return handle

    def revoke_version(
        self,
        handle: SecretVersionHandle,
        *,
        project_id: UUID,
        purpose: str,
        actor_id: UUID,
    ) -> None:
        now = self._now()
        require_uuid(actor_id, "secret actor ID")
        with self._lock:
            stored = self._scoped_version(handle, project_id, purpose)
            if stored.status is SecretVersionStatus.REVOKED:
                return
            self._versions[(handle.reference_id, handle.version)] = replace(
                stored,
                status=SecretVersionStatus.REVOKED,
            )
            if self._current_versions.get(handle.reference_id) == handle.version:
                del self._current_versions[handle.reference_id]
            self._record(
                envelope=stored.envelope,
                action=SecretAuditAction.VERSION_REVOKED,
                actor_id=actor_id,
                now=now,
            )

    def resolve(
        self,
        handle: SecretVersionHandle,
        *,
        project_id: UUID,
        purpose: str,
        actor_id: UUID,
    ) -> SecretValue:
        now = self._now()
        require_uuid(actor_id, "secret actor ID")
        with self._lock:
            stored = self._scoped_version(handle, project_id, purpose)
            if stored.status not in {SecretVersionStatus.ACTIVE, SecretVersionStatus.SUPERSEDED}:
                raise SecretVersionUnavailable("secret version is not available to consumers")
            value = self._cipher.decrypt(stored.envelope)
            self._record(
                envelope=stored.envelope,
                action=SecretAuditAction.VERSION_RESOLVED,
                actor_id=actor_id,
                now=now,
            )
            return value

    def current_handle(
        self,
        *,
        reference_id: UUID,
        project_id: UUID,
        purpose: str,
    ) -> SecretVersionHandle:
        with self._lock:
            self._scoped_reference(reference_id, project_id, purpose)
            try:
                version = self._current_versions[reference_id]
            except KeyError:
                raise SecretVersionUnavailable("secret reference has no active version") from None
            return self._versions[(reference_id, version)].envelope.handle

    def rewrap_version(
        self,
        handle: SecretVersionHandle,
        *,
        project_id: UUID,
        purpose: str,
        actor_id: UUID,
    ) -> EncryptedSecretVersion:
        now = self._now()
        require_uuid(actor_id, "secret actor ID")
        with self._lock:
            stored = self._scoped_version(handle, project_id, purpose)
            if stored.status is SecretVersionStatus.REVOKED:
                raise SecretVersionUnavailable("revoked secret version cannot be rewrapped")
            envelope = self._cipher.rewrap(stored.envelope)
            self._versions[(handle.reference_id, handle.version)] = replace(
                stored,
                envelope=envelope,
            )
            self._record(
                envelope=envelope,
                action=SecretAuditAction.VERSION_REWRAPPED,
                actor_id=actor_id,
                now=now,
            )
            return envelope

    def encrypted_version(
        self,
        handle: SecretVersionHandle,
        *,
        project_id: UUID,
        purpose: str,
    ) -> EncryptedSecretVersion:
        with self._lock:
            return self._scoped_version(handle, project_id, purpose).envelope

    @property
    def audit_events(self) -> tuple[SecretAuditEvent, ...]:
        with self._lock:
            return tuple(self._audit)

    def status_of(
        self,
        handle: SecretVersionHandle,
        *,
        project_id: UUID,
        purpose: str,
    ) -> SecretVersionStatus:
        with self._lock:
            return self._scoped_version(handle, project_id, purpose).status

    def _scoped_reference(
        self,
        reference_id: UUID,
        project_id: UUID,
        purpose: str,
    ) -> SecretReference:
        try:
            reference = self._references[reference_id]
        except KeyError:
            raise SecretNotFound("secret reference was not found") from None
        if reference.project_id != project_id or reference.purpose != purpose:
            raise SecretScopeViolation("secret reference does not match project and purpose scope")
        return reference

    def _scoped_version(
        self,
        handle: SecretVersionHandle,
        project_id: UUID,
        purpose: str,
    ) -> _StoredVersion:
        if handle.project_id != project_id or handle.purpose != purpose:
            raise SecretScopeViolation("secret handle does not match project and purpose scope")
        reference = self._scoped_reference(handle.reference_id, project_id, purpose)
        if handle.project_id != reference.project_id or handle.purpose != reference.purpose:
            raise SecretScopeViolation("secret version does not match its reference scope")
        try:
            stored = self._versions[(handle.reference_id, handle.version)]
        except KeyError:
            raise SecretNotFound("secret version was not found") from None
        if stored.envelope.handle != handle:
            raise SecretScopeViolation("secret version identity does not match its envelope")
        return stored

    def _record(
        self,
        *,
        envelope: EncryptedSecretVersion,
        action: SecretAuditAction,
        actor_id: UUID,
        now: datetime,
    ) -> None:
        handle = envelope.handle
        self._audit.append(
            SecretAuditEvent(
                id=self._id_factory(),
                reference_id=handle.reference_id,
                project_id=handle.project_id,
                purpose=handle.purpose,
                version=handle.version,
                action=action,
                actor_id=actor_id,
                occurred_at=now,
                master_key_version=envelope.master_key_version,
            )
        )

    def _now(self) -> datetime:
        value = self._clock()
        require_aware_datetime(value, "Secret Store clock")
        return value
