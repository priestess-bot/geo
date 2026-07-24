from uuid import uuid4

import pytest

from geo_core.secrets.models import SecretValue, SecretVersionHandle
from geo_core.synthetic_lab.postgres_style_secret_resolver import AuditedStyleSecretResolver


class _Application:
    def __init__(self) -> None:
        self.commands = []

    def resolve(self, command):
        self.commands.append(command)
        return SecretValue("fixture-login")


def test_style_resolver_uses_worker_service_principal_and_unique_audited_request() -> None:
    application = _Application()
    service_identity_id = uuid4()
    resolver = AuditedStyleSecretResolver(
        application,
        service_identity_id=service_identity_id,
    )  # type: ignore[arg-type]
    handle = SecretVersionHandle(
        reference_id=uuid4(),
        project_id=uuid4(),
        purpose="style_collection_login.reddit",
        version=2,
    )

    first = resolver.resolve(handle)
    second = resolver.resolve(handle)

    assert first.matches("fixture-login") and second.matches("fixture-login")
    assert len(application.commands) == 2
    assert application.commands[0].principal.role.value == "service"
    assert application.commands[0].principal.surface.value == "worker"
    assert application.commands[0].principal.actor_id == service_identity_id
    assert application.commands[0].handle == handle
    assert application.commands[0].idempotency_key != application.commands[1].idempotency_key
    assert "fixture-login" not in repr(resolver)


def test_style_resolver_rejects_non_login_secret_before_application() -> None:
    application = _Application()
    resolver = AuditedStyleSecretResolver(
        application,
        service_identity_id=uuid4(),
    )  # type: ignore[arg-type]
    handle = SecretVersionHandle(
        reference_id=uuid4(),
        project_id=uuid4(),
        purpose="model_provider.openai",
        version=1,
    )

    with pytest.raises(ValueError, match="channel-scoped"):
        resolver.resolve(handle)

    assert application.commands == []
