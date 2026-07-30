"""Audited, purpose-scoped Connector credential resolution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from uuid import UUID, uuid4

import psycopg

from geo_core.secrets.application import SecretApplicationService
from geo_core.secrets.application_contracts import ResolveSecretCommand, SecretRequestHasher
from geo_core.secrets.crypto import EnvelopeCipher
from geo_core.secrets.models import SecretVersionHandle
from geo_core.secrets.ports import SecretActorRole, SecretPrincipal, SecretSurface
from geo_core.secrets.postgres_config import load_postgres_crypto_config
from geo_core.secrets.postgres_keyring import synchronize_master_key_canaries
from geo_core.secrets.postgres_uow import PostgresSecretUnitOfWorkFactory


CONNECTOR_WORKER_SERVICE_NAME = "connector_worker"


class ConnectorSecretError(RuntimeError):
    """Connector credential is unavailable or violates its frozen contract."""


class AuditedConnectorSecretResolver:
    __secret_bearing__ = True

    def __init__(
        self,
        application: SecretApplicationService,
        *,
        service_identity_id: UUID,
    ) -> None:
        if service_identity_id.int == 0:
            raise ValueError("Connector worker service identity cannot be nil")
        self._application = application
        self._actor_id = service_identity_id

    def __repr__(self) -> str:
        return "AuditedConnectorSecretResolver([REDACTED])"

    def resolve(
        self,
        *,
        project_id: UUID,
        reference_id: UUID,
        purpose: str,
        version: int,
    ) -> Mapping[str, object]:
        if not purpose.startswith("connector."):
            raise ConnectorSecretError("Connector worker may resolve only Connector secrets")
        handle = SecretVersionHandle(
            project_id=project_id,
            reference_id=reference_id,
            purpose=purpose,
            version=version,
        )
        secret = self._application.resolve(
            ResolveSecretCommand(
                principal=SecretPrincipal(
                    actor_id=self._actor_id,
                    project_id=project_id,
                    role=SecretActorRole.SERVICE,
                    surface=SecretSurface.WORKER,
                ),
                handle=handle,
                idempotency_key=f"connector-resolve:{uuid4()}",
            )
        )
        try:
            value = json.loads(secret.reveal_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ConnectorSecretError("Connector credential must be a JSON object") from error
        if not isinstance(value, dict) or not value or any(
            not isinstance(key, str) for key in value
        ):
            raise ConnectorSecretError("Connector credential must be a non-empty JSON object")
        return value


def build_audited_connector_secret_resolver(
    *, database_url: str, service_identity_id: UUID
) -> AuditedConnectorSecretResolver:
    config = load_postgres_crypto_config()
    if config is None:
        raise ConnectorSecretError("Connector Secret Store keyring is unavailable")
    factory = PostgresSecretUnitOfWorkFactory(database_url)
    cipher = EnvelopeCipher(config.keyring)
    connection = factory.connect()
    try:
        row = connection.execute(
            "SELECT geo_require_active_service_identity(%s, %s)",
            (service_identity_id, CONNECTOR_WORKER_SERVICE_NAME),
        ).fetchone()
        if row is None or row[0] is not True:
            raise ConnectorSecretError("Connector worker service identity is not active")
        synchronize_master_key_canaries(connection, cipher)
        connection.commit()
    except (psycopg.Error, RuntimeError):
        connection.rollback()
        raise
    finally:
        connection.close()
    return AuditedConnectorSecretResolver(
        SecretApplicationService(
            uow_factory=factory,
            cipher=cipher,
            request_hasher=SecretRequestHasher(config.request_hash_key),
        ),
        service_identity_id=service_identity_id,
    )


__all__ = [
    "AuditedConnectorSecretResolver",
    "CONNECTOR_WORKER_SERVICE_NAME",
    "ConnectorSecretError",
    "build_audited_connector_secret_resolver",
]
