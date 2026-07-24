"""PostgreSQL-backed Secret Store resolver for Style Collection login."""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg

from geo_core.secrets.application import SecretApplicationService
from geo_core.secrets.application_contracts import ResolveSecretCommand, SecretRequestHasher
from geo_core.secrets.crypto import EnvelopeCipher
from geo_core.secrets.models import SecretValue, SecretVersionHandle
from geo_core.secrets.ports import SecretActorRole, SecretPrincipal, SecretSurface
from geo_core.secrets.postgres_config import load_postgres_crypto_config
from geo_core.secrets.postgres_keyring import synchronize_master_key_canaries
from geo_core.secrets.postgres_uow import PostgresSecretUnitOfWorkFactory


STYLE_COLLECTION_WORKER_SERVICE_NAME = "style_collection_worker"


class AuditedStyleSecretResolver:
    __secret_bearing__ = True

    def __init__(
        self,
        application: SecretApplicationService,
        *,
        service_identity_id: UUID,
    ) -> None:
        if service_identity_id.int == 0:
            raise ValueError("Style worker service identity cannot be the nil UUID")
        self._application = application
        self._actor_id = service_identity_id

    def resolve(self, handle: SecretVersionHandle) -> SecretValue:
        if not handle.purpose.startswith("style_collection_login."):
            raise ValueError("Style worker may resolve only channel-scoped login Secrets")
        return self._application.resolve(
            ResolveSecretCommand(
                principal=SecretPrincipal(
                    actor_id=self._actor_id,
                    project_id=handle.project_id,
                    role=SecretActorRole.SERVICE,
                    surface=SecretSurface.WORKER,
                ),
                handle=handle,
                idempotency_key=f"style-resolve:{uuid4()}",
            )
        )

    def __repr__(self) -> str:
        return "AuditedStyleSecretResolver([REDACTED])"


def build_audited_style_secret_resolver(
    *,
    database_url: str,
    service_identity_id: UUID,
) -> AuditedStyleSecretResolver:
    if service_identity_id.int == 0:
        raise RuntimeError("Style worker service identity cannot be the nil UUID")
    config = load_postgres_crypto_config()
    if config is None:
        raise RuntimeError("Style worker Secret Store keyring is unavailable")
    factory = PostgresSecretUnitOfWorkFactory(database_url)
    cipher = EnvelopeCipher(config.keyring)
    connection = factory.connect()
    try:
        row = connection.execute(
            "SELECT geo_require_active_service_identity(%s, %s)",
            (service_identity_id, STYLE_COLLECTION_WORKER_SERVICE_NAME),
        ).fetchone()
        if row is None or row[0] is not True:
            raise RuntimeError("Style worker service identity is not active")
        synchronize_master_key_canaries(connection, cipher)
        connection.commit()
    except (psycopg.Error, RuntimeError):
        connection.rollback()
        raise
    finally:
        connection.close()
    application = SecretApplicationService(
        uow_factory=factory,
        cipher=cipher,
        request_hasher=SecretRequestHasher(config.request_hash_key),
    )
    return AuditedStyleSecretResolver(
        application,
        service_identity_id=service_identity_id,
    )


__all__ = [
    "AuditedStyleSecretResolver",
    "STYLE_COLLECTION_WORKER_SERVICE_NAME",
    "build_audited_style_secret_resolver",
]
