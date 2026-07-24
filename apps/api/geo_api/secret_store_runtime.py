"""Internal Secret Store API port, memory adapter, and fail-closed composition."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
import hashlib
import importlib
import os
from pathlib import Path
from threading import RLock
from typing import Protocol, cast
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.secrets import (
    ActivateSecretVersionCommand,
    CreateSecretCommand,
    EncryptedSecretVersion,
    MemorySecretDatabase,
    RevokeSecretVersionCommand,
    SecretActorRole,
    SecretAggregate,
    SecretApplicationService,
    SecretAuthorizationError,
    SecretCommandOutcome,
    SecretNotFound,
    SecretPrincipal,
    SecretSurface,
    SecretValue,
    SecretVersionHandle,
    StageSecretRotationCommand,
    VerifySecretCommand,
)


@dataclass(frozen=True, kw_only=True)
class SecretVersionRead:
    reference_id: UUID
    version: int
    status: str
    aggregate_version: int
    master_key_version: int
    fingerprint: str
    created_at: datetime
    verified_at: datetime | None
    activated_at: datetime | None
    revoked_at: datetime | None
    replayed: bool


@dataclass(frozen=True, kw_only=True)
class SecretReferenceRead:
    reference_id: UUID
    purpose: str
    status: str
    aggregate_version: int
    current_version: int | None
    latest_version: int
    master_key_version: int
    fingerprint: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class SecretReferencePageRead:
    items: tuple[SecretReferenceRead, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, kw_only=True)
class SecretAuditRead:
    reference_id: UUID
    version: int
    action: str
    master_key_version: int
    fingerprint: str
    occurred_at: datetime


@dataclass(frozen=True, kw_only=True)
class SecretAuditPageRead:
    items: tuple[SecretAuditRead, ...]
    total: int
    limit: int
    offset: int


class SecretStoreApi(Protocol):
    def create(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        purpose: str,
        value: SecretValue,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionRead: ...

    def list_references(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> SecretReferencePageRead: ...

    def get_reference(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
    ) -> SecretReferenceRead: ...

    def verify(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        version: int,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionRead: ...

    def stage_rotation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        value: SecretValue,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionRead: ...

    def activate(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        version: int,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionRead: ...

    def revoke(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        version: int,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionRead: ...

    def list_audits(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> SecretAuditPageRead: ...


class MemorySecretStoreApi:
    """Internal test adapter around the application service and memory repository."""

    def __init__(
        self,
        *,
        application: SecretApplicationService,
        database: MemorySecretDatabase,
        reference_ids: Iterable[tuple[UUID, UUID]] = (),
    ) -> None:
        self._application = application
        self._database = database
        self._lock = RLock()
        self._reference_ids: dict[UUID, set[UUID]] = {}
        for project_id, reference_id in reference_ids:
            self._reference_ids.setdefault(project_id, set()).add(reference_id)

    def create(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        purpose: str,
        value: SecretValue,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionRead:
        domain_principal = _domain_principal(principal, project_id)
        outcome = self._application.create(
            CreateSecretCommand(
                principal=domain_principal,
                reference_id=reference_id,
                purpose=purpose,
                value=value,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
        )
        with self._lock:
            self._reference_ids.setdefault(project_id, set()).add(reference_id)
        return self._version_read(project_id, outcome)

    def list_references(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> SecretReferencePageRead:
        domain_principal = _domain_principal(principal, project_id)
        with self._lock:
            identifiers = tuple(sorted(self._reference_ids.get(project_id, ()), key=str))
        selected = identifiers[offset : offset + limit]
        return SecretReferencePageRead(
            items=tuple(
                self._reference_read(domain_principal, reference_id)
                for reference_id in selected
            ),
            total=len(identifiers),
            limit=limit,
            offset=offset,
        )

    def get_reference(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
    ) -> SecretReferenceRead:
        return self._reference_read(_domain_principal(principal, project_id), reference_id)

    def verify(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        version: int,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionRead:
        domain_principal = _domain_principal(principal, project_id)
        outcome = self._application.verify(
            VerifySecretCommand(
                principal=domain_principal,
                handle=self._handle(project_id, reference_id, version),
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return self._version_read(project_id, outcome)

    def stage_rotation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        value: SecretValue,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionRead:
        domain_principal = _domain_principal(principal, project_id)
        aggregate = self._aggregate(project_id, reference_id)
        outcome = self._application.stage_rotation(
            StageSecretRotationCommand(
                principal=domain_principal,
                reference_id=reference_id,
                purpose=aggregate.reference.purpose,
                value=value,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return self._version_read(project_id, outcome)

    def activate(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        version: int,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionRead:
        domain_principal = _domain_principal(principal, project_id)
        outcome = self._application.activate(
            ActivateSecretVersionCommand(
                principal=domain_principal,
                handle=self._handle(project_id, reference_id, version),
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return self._version_read(project_id, outcome)

    def revoke(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        version: int,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionRead:
        domain_principal = _domain_principal(principal, project_id)
        outcome = self._application.revoke(
            RevokeSecretVersionCommand(
                principal=domain_principal,
                handle=self._handle(project_id, reference_id, version),
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return self._version_read(project_id, outcome)

    def list_audits(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> SecretAuditPageRead:
        _domain_principal(principal, project_id)
        events = self._database.audit_events(project_id)
        selected = events[offset : offset + limit]
        items: list[SecretAuditRead] = []
        for event in selected:
            stored = self._aggregate(project_id, event.reference_id).require_version(event.version)
            items.append(
                SecretAuditRead(
                    reference_id=event.reference_id,
                    version=event.version,
                    action=event.action.value,
                    master_key_version=event.master_key_version,
                    fingerprint=_fingerprint(stored.envelope),
                    occurred_at=event.occurred_at,
                )
            )
        return SecretAuditPageRead(
            items=tuple(items),
            total=len(events),
            limit=limit,
            offset=offset,
        )

    def _reference_read(
        self,
        principal: SecretPrincipal,
        reference_id: UUID,
    ) -> SecretReferenceRead:
        metadata = self._application.reference_metadata(
            principal=principal,
            reference_id=reference_id,
        )
        latest = self._aggregate(principal.project_id, reference_id).require_version(
            metadata.latest_version
        )
        return SecretReferenceRead(
            reference_id=metadata.reference_id,
            purpose=metadata.purpose,
            status=metadata.status,
            aggregate_version=metadata.aggregate_version,
            current_version=metadata.current_version,
            latest_version=metadata.latest_version,
            master_key_version=latest.envelope.master_key_version,
            fingerprint=_fingerprint(latest.envelope),
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
        )

    def _version_read(
        self,
        project_id: UUID,
        outcome: SecretCommandOutcome,
    ) -> SecretVersionRead:
        stored = self._aggregate(project_id, outcome.handle.reference_id).require_version(
            outcome.handle.version
        )
        return SecretVersionRead(
            reference_id=outcome.handle.reference_id,
            version=outcome.handle.version,
            status=outcome.status.value,
            aggregate_version=outcome.aggregate_version,
            master_key_version=stored.envelope.master_key_version,
            fingerprint=_fingerprint(stored.envelope),
            created_at=stored.envelope.created_at,
            verified_at=stored.verified_at,
            activated_at=stored.activated_at,
            revoked_at=stored.revoked_at,
            replayed=outcome.replayed,
        )

    def _handle(
        self,
        project_id: UUID,
        reference_id: UUID,
        version: int,
    ) -> SecretVersionHandle:
        return self._aggregate(project_id, reference_id).require_version(version).handle

    def _aggregate(self, project_id: UUID, reference_id: UUID) -> SecretAggregate:
        aggregate = self._database.reference(project_id, reference_id)
        if aggregate is None:
            raise SecretNotFound("secret reference was not found")
        return aggregate


def build_secret_store_application() -> SecretStoreApi | None:
    """Load PostgreSQL composition only when its migration-backed adapter exists."""

    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    module_name = "geo_core.secrets.postgres"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        return None
    builder = getattr(module, "build_secret_store_api", None)
    if not callable(builder):
        return None
    return cast(SecretStoreApi, builder(database_url=database_url))


def _domain_principal(principal: AccessPrincipal, project_id: UUID) -> SecretPrincipal:
    for membership in principal.memberships:
        if membership.project_id == project_id and membership.role in {"owner", "admin"}:
            return SecretPrincipal(
                actor_id=principal.identity_id,
                project_id=project_id,
                role=(
                    SecretActorRole.OWNER
                    if membership.role == "owner"
                    else SecretActorRole.ADMIN
                ),
                surface=SecretSurface.ADMIN,
            )
    raise SecretAuthorizationError("Secret Store command requires project owner or admin")


def _fingerprint(envelope: EncryptedSecretVersion) -> str:
    digest = hashlib.sha256()
    digest.update(str(envelope.handle.reference_id).encode("ascii"))
    digest.update(envelope.handle.version.to_bytes(8, "big"))
    digest.update(envelope.master_key_version.to_bytes(8, "big"))
    digest.update(envelope.data_nonce)
    digest.update(envelope.ciphertext)
    digest.update(envelope.wrap_nonce)
    digest.update(envelope.wrapped_data_key)
    return digest.hexdigest()


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return direct
