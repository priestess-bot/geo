"""Persistence-neutral Secret Store application ports and immutable records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from .errors import SecretContractError, SecretNotFound
from .models import (
    EncryptedSecretVersion,
    SecretAuditEvent,
    SecretReference,
    SecretVersionHandle,
    SecretVersionStatus,
    require_aware_datetime,
    require_positive_int,
    require_uuid,
)


class SecretActorRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    SERVICE = "service"
    VIEWER = "viewer"
    CUSTOMER = "customer"


class SecretSurface(StrEnum):
    ADMIN = "admin"
    INTERNAL_API = "internal_api"
    WORKER = "worker"
    CUSTOMER = "customer"


class SecretOperation(StrEnum):
    CREATE = "create"
    VERIFY = "verify"
    ROTATE_STAGE = "rotate_stage"
    ACTIVATE = "activate"
    REVOKE = "revoke"
    RESOLVE = "resolve"
    REWRAP = "rewrap"


@dataclass(frozen=True, kw_only=True)
class SecretPrincipal:
    actor_id: UUID
    project_id: UUID
    role: SecretActorRole
    surface: SecretSurface

    def __post_init__(self) -> None:
        require_uuid(self.actor_id, "secret principal actor ID")
        require_uuid(self.project_id, "secret principal project ID")
        try:
            object.__setattr__(self, "role", SecretActorRole(self.role))
            object.__setattr__(self, "surface", SecretSurface(self.surface))
        except (TypeError, ValueError):
            raise SecretContractError("secret principal role or surface is invalid") from None


@dataclass(frozen=True, kw_only=True)
class StoredSecretVersion:
    envelope: EncryptedSecretVersion
    status: SecretVersionStatus
    created_by: UUID
    verified_by: UUID | None = None
    verified_at: datetime | None = None
    activated_by: UUID | None = None
    activated_at: datetime | None = None
    revoked_by: UUID | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        require_uuid(self.created_by, "secret version creator ID")
        try:
            object.__setattr__(self, "status", SecretVersionStatus(self.status))
        except (TypeError, ValueError):
            raise SecretContractError("stored secret version status is invalid") from None
        _paired_actor_time(self.verified_by, self.verified_at, "verification")
        _paired_actor_time(self.activated_by, self.activated_at, "activation")
        _paired_actor_time(self.revoked_by, self.revoked_at, "revocation")
        if self.status in {SecretVersionStatus.ACTIVE, SecretVersionStatus.SUPERSEDED}:
            if self.verified_at is None or self.activated_at is None:
                raise SecretContractError("active secret versions require verification and activation")
        if (
            self.activated_by is not None
            and self.activated_by == self.created_by
            and not self.handle.purpose.startswith(("browser_egress.", "browser_session."))
        ):
            raise SecretContractError("a secret version creator cannot activate that version")
        if self.status is SecretVersionStatus.REVOKED and self.revoked_at is None:
            raise SecretContractError("revoked secret versions require revocation metadata")

    @property
    def handle(self) -> SecretVersionHandle:
        return self.envelope.handle


@dataclass(frozen=True, kw_only=True)
class SecretAggregate:
    reference: SecretReference
    aggregate_version: int
    current_version: int | None
    created_by: UUID
    updated_at: datetime
    versions: tuple[StoredSecretVersion, ...]

    def __post_init__(self) -> None:
        require_positive_int(self.aggregate_version, "secret aggregate version")
        require_uuid(self.created_by, "secret reference creator ID")
        require_aware_datetime(self.updated_at, "secret aggregate update time")
        if not self.versions:
            raise SecretContractError("secret aggregate requires at least one version")
        numbers = tuple(item.handle.version for item in self.versions)
        if numbers != tuple(sorted(set(numbers))):
            raise SecretContractError("secret aggregate versions must be unique and sorted")
        for item in self.versions:
            handle = item.handle
            if (
                handle.reference_id != self.reference.id
                or handle.project_id != self.reference.project_id
                or handle.purpose != self.reference.purpose
            ):
                raise SecretContractError("secret version does not match reference scope")
        active = tuple(
            item.handle.version
            for item in self.versions
            if item.status is SecretVersionStatus.ACTIVE
        )
        if self.current_version is None:
            if active:
                raise SecretContractError("secret aggregate without current version cannot be active")
        elif active != (self.current_version,):
            raise SecretContractError("secret aggregate current version must be the only active version")

    @property
    def project_id(self) -> UUID:
        return self.reference.project_id

    def require_version(self, version: int) -> StoredSecretVersion:
        for item in self.versions:
            if item.handle.version == version:
                return item
        raise SecretNotFound("secret version was not found")


@dataclass(frozen=True, kw_only=True)
class SecretCommandOutcome:
    handle: SecretVersionHandle
    aggregate_version: int
    status: SecretVersionStatus
    replayed: bool = False

    def __post_init__(self) -> None:
        require_positive_int(self.aggregate_version, "secret command aggregate version")
        try:
            object.__setattr__(self, "status", SecretVersionStatus(self.status))
        except (TypeError, ValueError):
            raise SecretContractError("secret command outcome status is invalid") from None


@dataclass(frozen=True, kw_only=True)
class SecretCommandRecord:
    project_id: UUID
    operation: SecretOperation
    idempotency_key_hash: str
    request_hash: str
    outcome: SecretCommandOutcome
    recorded_at: datetime

    def __post_init__(self) -> None:
        require_uuid(self.project_id, "secret command project ID")
        try:
            object.__setattr__(self, "operation", SecretOperation(self.operation))
        except (TypeError, ValueError):
            raise SecretContractError("secret command operation is invalid") from None
        _require_sha256(self.idempotency_key_hash, "idempotency key hash")
        _require_sha256(self.request_hash, "request hash")
        require_aware_datetime(self.recorded_at, "secret command record time")
        if self.outcome.handle.project_id != self.project_id:
            raise SecretContractError("secret command outcome belongs to another project")


@dataclass(frozen=True, kw_only=True)
class SecretReferenceMetadata:
    reference_id: UUID
    project_id: UUID
    purpose: str
    aggregate_version: int
    current_version: int | None
    latest_version: int
    status: str
    created_at: datetime
    updated_at: datetime


class SecretRepository(Protocol):
    def get(self, reference_id: UUID) -> SecretAggregate | None: ...

    def add(self, aggregate: SecretAggregate) -> None: ...

    def save(self, aggregate: SecretAggregate, *, expected_version: int) -> None: ...


class SecretCommandRepository(Protocol):
    def get(self, idempotency_key_hash: str) -> SecretCommandRecord | None: ...

    def add(self, record: SecretCommandRecord) -> None: ...


class SecretAuditRepository(Protocol):
    def append(self, event: SecretAuditEvent) -> None: ...


class SecretUnitOfWork(Protocol):
    project_id: UUID
    secrets: SecretRepository
    commands: SecretCommandRepository
    audits: SecretAuditRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class SecretUnitOfWorkFactory(Protocol):
    def create(self, project_id: UUID) -> SecretUnitOfWork: ...


def _paired_actor_time(actor_id: UUID | None, occurred_at: datetime | None, label: str) -> None:
    if (actor_id is None) != (occurred_at is None):
        raise SecretContractError(f"secret {label} actor and time must be set together")
    if actor_id is not None:
        require_uuid(actor_id, f"secret {label} actor ID")
    if occurred_at is not None:
        require_aware_datetime(occurred_at, f"secret {label} time")


def _require_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise SecretContractError(f"secret {label} must be lowercase SHA-256")
