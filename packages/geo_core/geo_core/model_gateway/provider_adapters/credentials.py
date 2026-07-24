"""Bridge frozen Secret Store versions to immediate provider credentials."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from geo_core.secrets import (
    ResolveSecretCommand,
    SecretActorRole,
    SecretConfigurationError,
    SecretLifecycleError,
    SecretNotFound,
    SecretPrincipal,
    SecretScopeViolation,
    SecretSurface,
    SecretUnitOfWorkFactory,
    SecretValue,
    SecretVersionHandle,
    SecretVersionUnavailable,
)
from geo_core.secrets.postgres_api import build_secret_store_postgres_runtime


class SecretResolveApplication(Protocol):
    def resolve(self, command: ResolveSecretCommand) -> SecretValue: ...


class SecretStoreCredentialResolver:
    """Decrypt only the frozen Job handle once per immediate provider call."""

    __secret_bearing__ = True

    def __init__(
        self,
        *,
        application: SecretResolveApplication,
        uow_factory: SecretUnitOfWorkFactory,
        worker_actor_id: UUID,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if worker_actor_id.int == 0:
            raise ValueError("provider credential worker actor ID cannot be zero")
        self._application = application
        self._uow_factory = uow_factory
        self._worker_actor_id = worker_actor_id
        self._id_factory = id_factory

    def __repr__(self) -> str:
        return "SecretStoreCredentialResolver([REDACTED])"

    def resolve(self, handle: SecretVersionHandle) -> SecretValue:
        with self._uow_factory.create(handle.project_id) as unit_of_work:
            aggregate = unit_of_work.secrets.get(handle.reference_id)
        if aggregate is None:
            raise SecretNotFound("provider credential reference was not found")
        if (
            aggregate.reference.project_id != handle.project_id
            or aggregate.reference.purpose != handle.purpose
        ):
            raise SecretScopeViolation("provider credential reference scope does not match")
        stored = aggregate.require_version(handle.version)
        if stored.handle != handle:
            raise SecretScopeViolation("provider credential version scope does not match")
        principal = SecretPrincipal(
            actor_id=self._worker_actor_id,
            project_id=handle.project_id,
            role=SecretActorRole.SERVICE,
            surface=SecretSurface.WORKER,
        )
        try:
            return self._application.resolve(
                ResolveSecretCommand(
                    principal=principal,
                    handle=handle,
                    idempotency_key=f"provider-resolve:{self._id_factory()}",
                )
            )
        except SecretLifecycleError as exc:
            raise SecretVersionUnavailable(
                "provider credential version is not available"
            ) from exc


def build_secret_store_credential_resolver(
    *,
    database_url: str,
    master_keyring_path: str | Path | None = None,
    request_hash_key_path: str | Path | None = None,
    worker_actor_id: UUID,
) -> SecretStoreCredentialResolver:
    runtime = build_secret_store_postgres_runtime(
        database_url=database_url,
        master_keyring_path=master_keyring_path,
        request_hash_key_path=request_hash_key_path,
    )
    if runtime is None:
        raise SecretConfigurationError(
            "provider credential Secret Store runtime is not configured"
        )
    return SecretStoreCredentialResolver(
        application=runtime.application,
        uow_factory=runtime.uow_factory,
        worker_actor_id=worker_actor_id,
    )


__all__ = [
    "build_secret_store_credential_resolver",
    "SecretStoreCredentialResolver",
]
