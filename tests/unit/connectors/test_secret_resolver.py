from __future__ import annotations

from uuid import uuid4

import pytest

from geo_core.connectors.secret_resolver import (
    AuditedConnectorSecretResolver,
    ConnectorSecretError,
)
from geo_core.secrets.models import SecretValue


class _Application:
    def __init__(self, value: str) -> None:
        self.value = value
        self.commands = []

    def resolve(self, command):
        self.commands.append(command)
        return SecretValue(self.value)


def test_resolver_returns_only_json_object_for_connector_purpose() -> None:
    application = _Application('{"credentials":{"client_id":"private"}}')
    resolver = AuditedConnectorSecretResolver(
        application, service_identity_id=uuid4()  # type: ignore[arg-type]
    )
    project_id = uuid4()
    value = resolver.resolve(
        project_id=project_id,
        reference_id=uuid4(),
        purpose="connector.gsc",
        version=3,
    )
    assert value == {"credentials": {"client_id": "private"}}
    assert application.commands[0].principal.project_id == project_id
    assert "private" not in repr(resolver)


def test_resolver_rejects_wrong_purpose_and_non_object_secret() -> None:
    resolver = AuditedConnectorSecretResolver(
        _Application("[]"), service_identity_id=uuid4()  # type: ignore[arg-type]
    )
    with pytest.raises(ConnectorSecretError, match="only Connector"):
        resolver.resolve(
            project_id=uuid4(),
            reference_id=uuid4(),
            purpose="provider.openai",
            version=1,
        )
    with pytest.raises(ConnectorSecretError, match="JSON object"):
        resolver.resolve(
            project_id=uuid4(),
            reference_id=uuid4(),
            purpose="connector.ga4",
            version=1,
        )
