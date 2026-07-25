from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
import json
import multiprocessing
from multiprocessing.connection import Connection
import os
import socket
import subprocess
import time
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
import pytest
from redis import Redis

from geo_core.jobs.outbox import PostgresOutboxStore
from geo_core.jobs.postgres import LostJobLease, PostgresDurableJobStore, WorkerLease
from geo_worker import relay


DATABASE_URL = os.getenv("GEO_MIGRATION_REHEARSAL_DATABASE_URL", "").strip()
VALKEY_IMAGE = "valkey/valkey:8.0.2-alpine"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="GEO_MIGRATION_REHEARSAL_DATABASE_URL is required",
    ),
]


def test_terminated_worker_is_fenced_and_expired_lease_is_reclaimed() -> None:
    tenant_id, project_id, job_id = _seed_job(label="worker-termination")
    parent, child = multiprocessing.get_context("spawn").Pipe(duplex=False)
    process = multiprocessing.get_context("spawn").Process(
        target=_claim_until_terminated,
        args=(DATABASE_URL, project_id, job_id, child),
        name="geo-fault-worker-termination",
    )
    try:
        process.start()
        child.close()
        assert parent.poll(10), "child Worker did not claim the Durable Job"
        first_lease = parent.recv()
        assert isinstance(first_lease, WorkerLease)

        process.terminate()
        process.join(timeout=10)
        assert not process.is_alive()
        assert process.exitcode not in {None, 0}
        _wait_until(
            lambda: _assert_lease_expired(project_id=project_id, job_id=job_id),
            description="terminated Worker lease expiry",
        )

        store = _job_store()
        recovered = store.claim(
            job_id=job_id,
            project_id=project_id,
            expected_kind="fault.worker_termination",
            worker_id="replacement-worker",
            lease_for=timedelta(seconds=5),
        )
        assert recovered.disposition == "claimed" and recovered.lease is not None
        assert recovered.lease.fencing_generation == first_lease.fencing_generation + 1

        with pytest.raises(LostJobLease):
            with store.fenced_transaction(first_lease):
                pass
        with store.fenced_transaction(recovered.lease) as connection:
            store.complete_in_transaction(
                connection,
                recovered.lease,
                result_ref="artifact://fault-recovery/worker-termination",
                details={"outcome": "reclaimed_after_process_termination"},
            )
        with psycopg.connect(DATABASE_URL) as connection:
            job = connection.execute(
                "SELECT status, fencing_generation, attempt_count FROM durable_jobs WHERE id = %s",
                (job_id,),
            ).fetchone()
            events = connection.execute(
                "SELECT event_type FROM durable_job_events WHERE job_id = %s ORDER BY created_at",
                (job_id,),
            ).fetchall()
        assert job == ("succeeded", 2, 2)
        assert [row[0] for row in events] == ["lease_claimed", "lease_reclaimed", "job_succeeded"]
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)
        _delete_tenant(tenant_id)


def test_real_valkey_outage_keeps_outbox_replayable_and_recovery_delivers_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, project_id, job_id = _seed_job(label="broker-outage")
    outbox_id = uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO broker_outbox(
                id, project_id, job_id, topic, payload, idempotency_key
            ) VALUES (%s, %s, %s, 'fault.broker.queued', %s::jsonb, %s)
            """,
            (
                outbox_id,
                project_id,
                job_id,
                json.dumps({"job_id": str(job_id), "project_id": str(project_id)}),
                f"fault-broker-{job_id}",
            ),
        )
    try:
        with _isolated_valkey() as runtime:
            client = Redis.from_url(
                runtime.url,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
                retry_on_timeout=False,
                decode_responses=True,
            )

            def publish(**values: object) -> None:
                client.rpush("geo:fault:wakeups", json.dumps(values, default=str, sort_keys=True))

            monkeypatch.setattr(relay, "_send_job", publish)
            _docker("stop", "--time", "1", runtime.container_name)
            store = PostgresOutboxStore(lambda: psycopg.connect(DATABASE_URL))
            assert relay.relay_once(store, worker_id="fault-relay", batch_size=1) == 0
            failed = _outbox_state(outbox_id)
            assert failed[0] is None
            assert failed[1:4] == (None, "dispatch_failed", 1)

            _docker("start", runtime.container_name)
            _wait_until(lambda: _assert_valkey_ready(client), description="Valkey restart")
            _wait_until(
                lambda: _assert_outbox_available(outbox_id),
                description="failed outbox retry delay",
                timeout_seconds=10,
            )
            assert relay.relay_once(store, worker_id="fault-relay", batch_size=1) == 1
            delivered = _outbox_state(outbox_id)
            assert delivered[0] is not None
            assert delivered[1:] == (None, None, 2)
            messages = cast(list[str], client.lrange("geo:fault:wakeups", 0, -1))
            assert len(messages) == 1
            assert str(job_id) in messages[0]
            assert str(project_id) in messages[0]
            client.close()
    finally:
        _delete_tenant(tenant_id)


def _claim_until_terminated(
    database_url: str,
    project_id: UUID,
    job_id: UUID,
    sender: Connection,
) -> None:
    store = PostgresDurableJobStore(
        lambda: psycopg.connect(database_url, row_factory=dict_row)
    )
    result = store.claim(
        job_id=job_id,
        project_id=project_id,
        expected_kind="fault.worker_termination",
        worker_id="worker-that-will-be-terminated",
        lease_for=timedelta(milliseconds=500),
    )
    if result.disposition != "claimed" or result.lease is None:
        raise RuntimeError(f"fault Worker failed to claim job: {result.disposition}")
    sender.send(result.lease)
    sender.close()
    while True:
        time.sleep(60)


def _job_store() -> PostgresDurableJobStore:
    return PostgresDurableJobStore(
        lambda: psycopg.connect(DATABASE_URL, row_factory=dict_row)
    )


def _seed_job(*, label: str) -> tuple[UUID, UUID, UUID]:
    tenant_id, project_id, job_id = uuid4(), uuid4(), uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            "INSERT INTO tenants(id, name) VALUES (%s, %s)",
            (tenant_id, f"Fault runtime {label} {tenant_id}"),
        )
        connection.execute(
            "INSERT INTO projects(id, tenant_id, name) VALUES (%s, %s, %s)",
            (project_id, tenant_id, f"Fault runtime {label} {project_id}"),
        )
        connection.execute(
            """
            INSERT INTO durable_jobs(
                id, project_id, kind, input_hash, idempotency_key, max_attempts
            ) VALUES (%s, %s, %s, %s, %s, 3)
            """,
            (
                job_id,
                project_id,
                f"fault.{label.replace('-', '_')}",
                "d" * 64,
                f"fault-{label}-{job_id}",
            ),
        )
    return tenant_id, project_id, job_id


def _delete_tenant(tenant_id: UUID) -> None:
    if not DATABASE_URL:
        return
    with psycopg.connect(DATABASE_URL) as connection:
        project_rows = connection.execute(
            "SELECT id FROM projects WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchall()
        project_ids = [row[0] for row in project_rows]
        connection.execute("SET LOCAL session_replication_role = replica")
        for project_id in project_ids:
            connection.execute(
                "DELETE FROM durable_job_events WHERE project_id = %s",
                (project_id,),
            )
            connection.execute(
                "DELETE FROM broker_outbox WHERE project_id = %s",
                (project_id,),
            )
            connection.execute(
                "DELETE FROM durable_jobs WHERE project_id = %s",
                (project_id,),
            )
            connection.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        connection.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))


def _assert_lease_expired(*, project_id: UUID, job_id: UUID) -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            """
            SELECT status, lease_expires_at <= clock_timestamp()
            FROM durable_jobs WHERE id = %s AND project_id = %s
            """,
            (job_id, project_id),
        ).fetchone()
    assert row == ("running", True)


def _outbox_state(outbox_id: UUID) -> tuple[Any, ...]:
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            """
            SELECT published_at, claimed_by, last_error, attempt_count
            FROM broker_outbox WHERE id = %s
            """,
            (outbox_id,),
        ).fetchone()
    assert row is not None
    return tuple(row)


def _assert_outbox_available(outbox_id: UUID) -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            "SELECT available_at <= clock_timestamp() FROM broker_outbox WHERE id = %s",
            (outbox_id,),
        ).fetchone()
    assert row == (True,)


def _assert_valkey_ready(client: Redis) -> None:
    assert client.ping() is True


@contextmanager
def _isolated_valkey() -> Iterator[_ValkeyRuntime]:
    run_id = uuid4().hex[:12]
    name = f"geo-fault-valkey-{run_id}"
    port = _unused_local_port()
    _docker(
        "run",
        "--detach",
        "--name",
        name,
        "--label",
        "geo.test=non-b-fault-runtime",
        "--publish",
        f"127.0.0.1:{port}:6379",
        VALKEY_IMAGE,
    )
    runtime = _ValkeyRuntime(container_name=name, url=f"redis://127.0.0.1:{port}/0")
    probe = Redis.from_url(runtime.url, socket_connect_timeout=0.5, socket_timeout=0.5)
    try:
        _wait_until(lambda: _assert_valkey_ready(probe), description="isolated Valkey")
        yield runtime
    finally:
        probe.close()
        _docker("rm", "--force", name, check=False)


class _ValkeyRuntime:
    def __init__(self, *, container_name: str, url: str) -> None:
        self.container_name = container_name
        self.url = url


def _docker(*arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ("docker", *arguments),
        check=check,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return completed.stdout.strip()


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_until(
    check: Callable[[], object],
    *,
    description: str,
    timeout_seconds: float = 5,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            check()
            return
        except BaseException as exc:
            last_error = exc
            time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {description}") from last_error
