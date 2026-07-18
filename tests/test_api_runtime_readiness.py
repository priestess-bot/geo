from __future__ import annotations

from collections.abc import Mapping
from urllib.request import Request

import psycopg
import pytest
from redis import Redis

from geo_api import runtime_readiness


def test_postgres_probe_only_executes_select_one(monkeypatch: pytest.MonkeyPatch) -> None:
    queries: list[str] = []
    connection_options: dict[str, object] = {}

    class Result:
        def fetchone(self) -> tuple[int]:
            return (1,)

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, query: str) -> Result:
            queries.append(query)
            return Result()

    def connect(database_url: str, **kwargs: object) -> Connection:
        assert database_url == "postgresql://private"
        connection_options.update(kwargs)
        return Connection()

    monkeypatch.setattr(psycopg, "connect", connect)
    probe = runtime_readiness._postgres_probe(
        {"GEO_DATABASE_URL": "postgresql://private"}, 2.0
    )

    probe()

    assert queries == ["SELECT 1"]
    assert connection_options == {
        "autocommit": True,
        "connect_timeout": 2,
        "options": "-c statement_timeout=2000",
    }


def test_valkey_probe_only_pings_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    options: dict[str, object] = {}

    class Client:
        def ping(self) -> bool:
            calls.append("ping")
            return True

        def close(self) -> None:
            calls.append("close")

    client = Client()

    def from_url(cls: type[Redis], url: str, **kwargs: object) -> Client:
        del cls
        assert url == "redis://valkey:6379/0"
        options.update(kwargs)
        return client

    monkeypatch.setattr(Redis, "from_url", classmethod(from_url))
    probe = runtime_readiness._valkey_probe(
        {"GEO_TASK_QUEUE_BROKER_URL": "redis://valkey:6379/0"}, 2.0
    )

    probe()

    assert calls == ["ping", "close"]
    assert options == {"socket_connect_timeout": 2.0, "socket_timeout": 2.0}


def test_object_store_probe_uses_signed_bucket_head_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, str, Mapping[str, str], float]] = []

    class Response:
        status = 200
        headers: Mapping[str, str] = {}

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def read(self) -> bytes:
            return b""

    def fake_urlopen(request: Request, *, timeout: float) -> Response:
        requests.append(
            (request.get_method(), request.full_url, dict(request.header_items()), timeout)
        )
        return Response()

    monkeypatch.setattr(runtime_readiness, "urlopen", fake_urlopen)
    probe = runtime_readiness._object_store_probe(
        {
            "OBJECT_STORE_ENDPOINT": "http://minio:9000",
            "OBJECT_STORE_BUCKET": "geo-artifacts",
            "OBJECT_STORE_ACCESS_KEY": "object-access",
            "OBJECT_STORE_SECRET_KEY": "object-secret",
        },
        2.0,
    )

    probe()

    assert len(requests) == 1
    method, url, headers, timeout = requests[0]
    assert method == "HEAD"
    assert url == "http://minio:9000/geo-artifacts"
    assert timeout == 2.0
    authorization = next(value for key, value in headers.items() if key.lower() == "authorization")
    assert authorization.startswith("AWS4-HMAC-SHA256 Credential=object-access/")
    assert "object-secret" not in repr(requests)


def test_surface_probe_contract_rejects_missing_or_external_dependencies() -> None:
    with pytest.raises(ValueError, match="customer readiness dependencies"):
        runtime_readiness.ReadinessChecker(surface="customer", probes=())

    with pytest.raises(ValueError, match="internal readiness dependencies"):
        runtime_readiness.ReadinessChecker(
            surface="internal",
            probes=(
                runtime_readiness.DependencyProbe("postgres", lambda: None),
                runtime_readiness.DependencyProbe("valkey", lambda: None),
            ),
        )
