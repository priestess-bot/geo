"""Duck-typed Internal API facade for the PostgreSQL Secret Store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.project_scope import set_project_scope

from .application import SecretApplicationService
from .application_contracts import (
    ActivateSecretVersionCommand,
    CreateSecretCommand,
    RevokeSecretVersionCommand,
    SecretRequestHasher,
    StageSecretRotationCommand,
    VerifySecretCommand,
)
from .crypto import EnvelopeCipher
from .errors import SecretAuthorizationError, SecretNotFound
from .models import SecretValue, SecretVersionHandle
from .ports import (
    SecretActorRole,
    SecretAggregate,
    SecretCommandOutcome,
    SecretPrincipal,
    SecretSurface,
)
from .postgres_config import load_postgres_crypto_config
from .postgres_fingerprint import envelope_fingerprint
from .postgres_keyring import synchronize_master_key_canaries
from .postgres_repository import PsycopgSecretReadRepository
from .postgres_uow import PostgresSecretUnitOfWorkFactory


@dataclass(frozen=True, kw_only=True)
class SecretVersionView:
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
class SecretReferenceView:
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
class SecretReferencePageView:
    items: tuple[SecretReferenceView, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, kw_only=True)
class SecretAuditView:
    reference_id: UUID
    version: int
    action: str
    master_key_version: int
    fingerprint: str
    occurred_at: datetime


@dataclass(frozen=True, kw_only=True)
class SecretAuditPageView:
    items: tuple[SecretAuditView, ...]
    total: int
    limit: int
    offset: int


class PsycopgSecretStoreApi:
    """Internal metadata/lifecycle facade; plaintext resolve is intentionally absent."""

    def __init__(
        self,
        *,
        application: SecretApplicationService,
        uow_factory: PostgresSecretUnitOfWorkFactory,
    ) -> None:
        self._application = application
        self._uow_factory = uow_factory

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
    ) -> SecretVersionView:
        outcome = self._application.create(
            CreateSecretCommand(
                principal=_domain_principal(principal, project_id),
                reference_id=reference_id,
                purpose=purpose,
                value=value,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return self._version_view(project_id, outcome)

    def list_references(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> SecretReferencePageView:
        _domain_principal(principal, project_id)
        connection = self._uow_factory.connect()
        try:
            set_project_scope(connection, project_id)
            aggregates, total = PsycopgSecretReadRepository(
                connection, project_id
            ).list_aggregates(limit=limit, offset=offset)
            return SecretReferencePageView(
                items=tuple(_reference_view(item) for item in aggregates),
                total=total,
                limit=limit,
                offset=offset,
            )
        finally:
            connection.rollback()
            connection.close()

    def get_reference(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
    ) -> SecretReferenceView:
        domain_principal = _domain_principal(principal, project_id)
        self._application.reference_metadata(
            principal=domain_principal, reference_id=reference_id
        )
        return _reference_view(self._aggregate(project_id, reference_id))

    def verify(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        version: int,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionView:
        outcome = self._application.verify(
            VerifySecretCommand(
                principal=_domain_principal(principal, project_id),
                handle=self._handle(project_id, reference_id, version),
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return self._version_view(project_id, outcome)

    def stage_rotation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        value: SecretValue,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionView:
        aggregate = self._aggregate(project_id, reference_id)
        outcome = self._application.stage_rotation(
            StageSecretRotationCommand(
                principal=_domain_principal(principal, project_id),
                reference_id=reference_id,
                purpose=aggregate.reference.purpose,
                value=value,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return self._version_view(project_id, outcome)

    def activate(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        version: int,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionView:
        outcome = self._application.activate(
            ActivateSecretVersionCommand(
                principal=_domain_principal(principal, project_id),
                handle=self._handle(project_id, reference_id, version),
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return self._version_view(project_id, outcome)

    def revoke(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        reference_id: UUID,
        version: int,
        expected_version: int,
        idempotency_key: str,
    ) -> SecretVersionView:
        outcome = self._application.revoke(
            RevokeSecretVersionCommand(
                principal=_domain_principal(principal, project_id),
                handle=self._handle(project_id, reference_id, version),
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return self._version_view(project_id, outcome)

    def list_audits(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> SecretAuditPageView:
        _domain_principal(principal, project_id)
        connection = self._uow_factory.connect()
        try:
            set_project_scope(connection, project_id)
            pairs, total = PsycopgSecretReadRepository(
                connection, project_id
            ).list_audits(limit=limit, offset=offset)
            return SecretAuditPageView(
                items=tuple(
                    SecretAuditView(
                        reference_id=event.reference_id,
                        version=event.version,
                        action=event.action.value,
                        master_key_version=event.master_key_version,
                        fingerprint=fingerprint,
                        occurred_at=event.occurred_at,
                    )
                    for event, fingerprint in pairs
                ),
                total=total,
                limit=limit,
                offset=offset,
            )
        finally:
            connection.rollback()
            connection.close()

    def _version_view(
        self, project_id: UUID, outcome: SecretCommandOutcome
    ) -> SecretVersionView:
        stored = self._aggregate(project_id, outcome.handle.reference_id).require_version(
            outcome.handle.version
        )
        return SecretVersionView(
            reference_id=outcome.handle.reference_id,
            version=outcome.handle.version,
            status=outcome.status.value,
            aggregate_version=outcome.aggregate_version,
            master_key_version=stored.envelope.master_key_version,
            fingerprint=envelope_fingerprint(stored.envelope),
            created_at=stored.envelope.created_at,
            verified_at=stored.verified_at,
            activated_at=stored.activated_at,
            revoked_at=stored.revoked_at,
            replayed=outcome.replayed,
        )

    def _handle(
        self, project_id: UUID, reference_id: UUID, version: int
    ) -> SecretVersionHandle:
        return self._aggregate(project_id, reference_id).require_version(version).handle

    def _aggregate(self, project_id: UUID, reference_id: UUID) -> SecretAggregate:
        with self._uow_factory.create(project_id) as unit_of_work:
            aggregate = unit_of_work.secrets.get(reference_id)
        if aggregate is None:
            raise SecretNotFound("secret reference was not found")
        return aggregate


@dataclass(frozen=True, repr=False)
class SecretStorePostgresRuntime:
    application: SecretApplicationService
    uow_factory: PostgresSecretUnitOfWorkFactory

    def __repr__(self) -> str:
        return "SecretStorePostgresRuntime([REDACTED])"


def build_secret_store_postgres_runtime(
    *,
    database_url: str,
    master_keyring_path: str | Path | None = None,
    request_hash_key_path: str | Path | None = None,
) -> SecretStorePostgresRuntime | None:
    config = load_postgres_crypto_config(
        master_keyring_path=master_keyring_path,
        request_hash_key_path=request_hash_key_path,
    )
    if config is None:
        return None
    factory = PostgresSecretUnitOfWorkFactory(database_url)
    cipher = EnvelopeCipher(config.keyring)
    connection = factory.connect()
    try:
        synchronize_master_key_canaries(connection, cipher)
        connection.commit()
    finally:
        connection.close()
    return SecretStorePostgresRuntime(
        application=SecretApplicationService(
            uow_factory=factory,
            cipher=cipher,
            request_hasher=SecretRequestHasher(config.request_hash_key),
        ),
        uow_factory=factory,
    )


def build_secret_store_api(
    *,
    database_url: str,
    master_keyring_path: str | Path | None = None,
    request_hash_key_path: str | Path | None = None,
) -> PsycopgSecretStoreApi | None:
    runtime = build_secret_store_postgres_runtime(
        database_url=database_url,
        master_keyring_path=master_keyring_path,
        request_hash_key_path=request_hash_key_path,
    )
    if runtime is None:
        return None
    return PsycopgSecretStoreApi(
        application=runtime.application,
        uow_factory=runtime.uow_factory,
    )


def _domain_principal(
    principal: AccessPrincipal, project_id: UUID
) -> SecretPrincipal:
    membership = next(
        (
            item
            for item in principal.memberships
            if item.project_id == project_id
            and item.tenant_id == principal.tenant_id
            and item.role in {"owner", "admin"}
        ),
        None,
    )
    if membership is None:
        raise SecretAuthorizationError(
            "Secret Store command requires project owner or admin"
        )
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


def _reference_view(aggregate: SecretAggregate) -> SecretReferenceView:
    latest = aggregate.versions[-1]
    statuses = {item.status.value for item in aggregate.versions}
    status = (
        "active"
        if aggregate.current_version is not None
        else "pending"
        if "pending" in statuses
        else "revoked"
        if statuses == {"revoked"}
        else "inactive"
    )
    return SecretReferenceView(
        reference_id=aggregate.reference.id,
        purpose=aggregate.reference.purpose,
        status=status,
        aggregate_version=aggregate.aggregate_version,
        current_version=aggregate.current_version,
        latest_version=latest.handle.version,
        master_key_version=latest.envelope.master_key_version,
        fingerprint=envelope_fingerprint(latest.envelope),
        created_at=aggregate.reference.created_at,
        updated_at=aggregate.updated_at,
    )


__all__ = [
    "PsycopgSecretStoreApi",
    "SecretStorePostgresRuntime",
    "build_secret_store_api",
    "build_secret_store_postgres_runtime",
]
