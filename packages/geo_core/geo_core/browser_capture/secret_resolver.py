"""Audited, purpose-scoped proxy credential resolution for Browser Capture."""

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


BROWSER_CAPTURE_WORKER_SERVICE_NAME = "browser_capture_worker"


class BrowserProxySecretError(RuntimeError):
    """A proxy credential is unavailable or violates its frozen purpose."""


class AuditedBrowserProxySecretResolver:
    __secret_bearing__ = True

    def __init__(self, application: SecretApplicationService, *, service_identity_id: UUID) -> None:
        if service_identity_id.int == 0:
            raise ValueError("Browser Capture worker service identity cannot be nil")
        self._application = application
        self._actor_id = service_identity_id

    def __repr__(self) -> str:
        return "AuditedBrowserProxySecretResolver([REDACTED])"

    def resolve(
        self,
        *,
        project_id: UUID,
        reference_id: UUID,
        purpose: str,
        version: int,
    ) -> Mapping[str, object]:
        if not purpose.startswith("browser_egress."):
            raise BrowserProxySecretError(
                "Browser Capture worker may resolve only browser_egress secrets"
            )
        return self._resolve_json(
            project_id=project_id,
            reference_id=reference_id,
            purpose=purpose,
            version=version,
            idempotency_prefix="browser-proxy-resolve",
            label="Browser proxy",
        )

    def resolve_storage_state(
        self,
        *,
        project_id: UUID,
        reference_id: UUID,
        purpose: str,
        version: int,
    ) -> Mapping[str, object]:
        if purpose != "browser_session.storage_state":
            raise BrowserProxySecretError(
                "Browser Capture worker may resolve only browser_session.storage_state"
            )
        return self._resolve_json(
            project_id=project_id,
            reference_id=reference_id,
            purpose=purpose,
            version=version,
            idempotency_prefix="browser-session-resolve",
            label="Browser session storage state",
        )

    def _resolve_json(
        self,
        *,
        project_id: UUID,
        reference_id: UUID,
        purpose: str,
        version: int,
        idempotency_prefix: str,
        label: str,
    ) -> Mapping[str, object]:
        secret = self._application.resolve(
            ResolveSecretCommand(
                principal=SecretPrincipal(
                    actor_id=self._actor_id,
                    project_id=project_id,
                    role=SecretActorRole.SERVICE,
                    surface=SecretSurface.WORKER,
                ),
                handle=SecretVersionHandle(
                    project_id=project_id,
                    reference_id=reference_id,
                    purpose=purpose,
                    version=version,
                ),
                idempotency_key=f"{idempotency_prefix}:{uuid4()}",
            )
        )
        try:
            value = json.loads(secret.reveal_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise BrowserProxySecretError(f"{label} Secret must be a JSON object") from error
        if not isinstance(value, dict) or not value or any(
            not isinstance(key, str) for key in value
        ):
            raise BrowserProxySecretError(f"{label} Secret must be a non-empty JSON object")
        return value


def build_audited_browser_proxy_secret_resolver(
    *, database_url: str, service_identity_id: UUID
) -> AuditedBrowserProxySecretResolver:
    config = load_postgres_crypto_config()
    if config is None:
        raise BrowserProxySecretError("Browser Capture Secret Store keyring is unavailable")
    factory = PostgresSecretUnitOfWorkFactory(database_url)
    cipher = EnvelopeCipher(config.keyring)
    connection = factory.connect()
    try:
        row = connection.execute(
            "SELECT geo_require_active_service_identity(%s, %s)",
            (service_identity_id, BROWSER_CAPTURE_WORKER_SERVICE_NAME),
        ).fetchone()
        if row is None or row[0] is not True:
            raise BrowserProxySecretError(
                "Browser Capture worker service identity is not active"
            )
        synchronize_master_key_canaries(connection, cipher)
        connection.commit()
    except (psycopg.Error, RuntimeError):
        connection.rollback()
        raise
    finally:
        connection.close()
    return AuditedBrowserProxySecretResolver(
        SecretApplicationService(
            uow_factory=factory,
            cipher=cipher,
            request_hasher=SecretRequestHasher(config.request_hash_key),
        ),
        service_identity_id=service_identity_id,
    )


__all__ = [
    "AuditedBrowserProxySecretResolver",
    "BROWSER_CAPTURE_WORKER_SERVICE_NAME",
    "BrowserProxySecretError",
    "build_audited_browser_proxy_secret_resolver",
]
