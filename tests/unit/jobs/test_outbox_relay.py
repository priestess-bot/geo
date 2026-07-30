from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from geo_core.jobs.outbox import OutboxMessage, RecoverableJob
from geo_worker import relay


def test_relay_imports_only_the_lightweight_browser_routing_contract() -> None:
    source = (Path(__file__).resolve().parents[3] / "apps/api/geo_worker/relay.py").read_text(
        encoding="utf-8"
    )
    assert "geo_core.browser_capture.routing" in source
    assert "geo_core.browser_capture.worker" not in source
    assert "geo_core.browser_capture.egress_test" not in source


class _Store:
    def __init__(self) -> None:
        self.message = OutboxMessage(uuid4(), uuid4(), uuid4(), "durable.queued", {})
        self.failures: list[str] = []

    def claim(self, *, worker_id: str, batch_size: int, lease_seconds: int):
        del worker_id, batch_size, lease_seconds
        return (self.message,)

    def acknowledge(self, message: OutboxMessage, *, worker_id: str) -> bool:
        del message, worker_id
        raise AssertionError("failed dispatch must not acknowledge")

    def fail(self, message: OutboxMessage, *, worker_id: str, error: str) -> bool:
        del message, worker_id
        self.failures.append(error)
        return True


class _RecoveryStore:
    def __init__(self) -> None:
        self.jobs = (
            RecoverableJob(uuid4(), uuid4(), "standard"),
            RecoverableJob(uuid4(), uuid4(), "style_collection"),
            RecoverableJob(uuid4(), uuid4(), "workflow_c.artifact_maintenance"),
            RecoverableJob(
                uuid4(), uuid4(), "recommendation.artifact_maintenance"
            ),
            RecoverableJob(uuid4(), uuid4(), "synthetic_lab.artifact_maintenance"),
            RecoverableJob(uuid4(), uuid4(), "connector.sync"),
            RecoverableJob(uuid4(), uuid4(), "connector.connection_test"),
            RecoverableJob(uuid4(), uuid4(), "browser.capture"),
            RecoverableJob(uuid4(), uuid4(), "browser.egress_test"),
        )

    def recoverable(self, *, batch_size: int):
        del batch_size
        return self.jobs


def test_dispatch_failure_persists_only_a_stable_non_sensitive_code(monkeypatch) -> None:
    store = _Store()
    marker = "credential-must-not-reach-outbox"

    def fail(**_values: object) -> None:
        raise RuntimeError(marker)

    monkeypatch.setattr(relay, "_send_job", fail)

    assert relay.relay_once(store, worker_id="relay-1", batch_size=1) == 0
    assert store.failures == ["dispatch_failed"]
    assert marker not in repr(store.failures)


def test_recovery_continues_after_one_dispatch_failure(monkeypatch) -> None:
    store = _RecoveryStore()
    dispatched: list[object] = []

    def send(**values: object) -> None:
        dispatched.append(values)
        if len(dispatched) == 1:
            raise RuntimeError("broker endpoint with credentials")

    monkeypatch.setattr(relay, "_send_job", send)

    assert relay.recover_once(store, batch_size=10) == 8
    assert len(dispatched) == 9
    assert dispatched[2]["workflow_c_maintenance"] is True
    assert dispatched[3]["recommendation_artifact_maintenance"] is True
    assert dispatched[4]["synthetic_artifact_maintenance"] is True
    assert dispatched[5]["connector_sync"] is True
    assert dispatched[6]["connector_sync"] is True
    assert dispatched[7]["browser_capture"] is True
    assert dispatched[8]["browser_capture"] is True


def test_synthetic_maintenance_producer_uses_the_atomic_worker_rpc(monkeypatch) -> None:
    executed: list[tuple[str, tuple[object, ...]]] = []

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, statement: str, parameters: tuple[object, ...]):
            executed.append((statement, parameters))
            return self

        def fetchall(self) -> list[object]:
            return [object(), object()]

    monkeypatch.setattr(relay.psycopg, "connect", lambda _url: _Connection())
    now = datetime(2026, 7, 23, 0, 0, tzinfo=UTC)

    assert relay.enqueue_synthetic_artifact_maintenance("postgresql://worker", now=now) == 2
    assert executed == [
        (
            "SELECT * FROM geo_enqueue_synthetic_artifact_maintenance(%s)",
            (now,),
        )
    ]


def test_synthetic_maintenance_producer_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        relay.enqueue_synthetic_artifact_maintenance(
            "postgresql://worker", now=datetime(2026, 7, 23)
        )
