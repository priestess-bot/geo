from __future__ import annotations

from contextlib import nullcontext
from uuid import UUID

import pytest

from geo_worker import service_identity


_IDENTITY = "9e790000-0000-0000-0000-000000000001"


class _Connection:
    def __init__(self, active: bool) -> None:
        self._active = active
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, values: tuple[object, ...]):
        self.calls.append((query, values))
        return self

    def fetchone(self) -> tuple[bool]:
        return (self._active,)


def test_model_gateway_worker_identity_requires_the_configured_active_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(active=True)
    monkeypatch.setenv(
        service_identity.MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ENV, _IDENTITY
    )
    monkeypatch.setattr(
        service_identity.psycopg,
        "connect",
        lambda _url: nullcontext(connection),
    )

    resolved = service_identity.require_model_gateway_worker_identity(
        database_url="postgresql://worker.example/geo"
    )

    assert resolved == UUID(_IDENTITY)
    assert connection.calls == [
        (
            "SELECT geo_require_active_service_identity(%s, %s)",
            (resolved, "model_gateway_worker"),
        )
    ]


@pytest.mark.parametrize("configured", ("", "not-a-uuid", "00000000-0000-0000-0000-000000000000"))
def test_model_gateway_worker_identity_rejects_invalid_deployment_values(
    monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    monkeypatch.setenv(
        service_identity.MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ENV, configured
    )

    with pytest.raises(RuntimeError, match="SERVICE_IDENTITY_ID"):
        service_identity.require_model_gateway_worker_identity(
            database_url="postgresql://worker.example/geo"
        )


def test_model_gateway_worker_identity_rejects_unknown_or_disabled_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        service_identity.MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ENV, _IDENTITY
    )
    monkeypatch.setattr(
        service_identity.psycopg,
        "connect",
        lambda _url: nullcontext(_Connection(active=False)),
    )

    with pytest.raises(RuntimeError, match="not active"):
        service_identity.require_model_gateway_worker_identity(
            database_url="postgresql://worker.example/geo"
        )
