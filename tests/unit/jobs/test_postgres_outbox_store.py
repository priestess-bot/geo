from __future__ import annotations

from uuid import uuid4

from geo_core.jobs.outbox import PostgresOutboxStore


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows

    def fetchone(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_values: object) -> None:
        return None

    def execute(self, _statement: str, _parameters: tuple[object, ...]) -> _Cursor:
        return _Cursor(self._rows)


def test_outbox_store_accepts_psycopg_mapping_rows() -> None:
    project_id = uuid4()
    job_id = uuid4()
    store = PostgresOutboxStore(
        lambda: _Connection(
            [
                {
                    "id": uuid4(),
                    "project_id": project_id,
                    "job_id": job_id,
                    "topic": "sampling.provider_execute",
                    "payload": {"job_id": str(job_id)},
                }
            ]
        )
    )

    message = store.claim(worker_id="relay", batch_size=1, lease_seconds=30)[0]

    assert message.project_id == project_id
    assert message.job_id == job_id
    assert message.topic == "sampling.provider_execute"


def test_recoverable_jobs_accept_psycopg_mapping_rows() -> None:
    project_id = uuid4()
    job_id = uuid4()
    store = PostgresOutboxStore(
        lambda: _Connection(
            [{"project_id": project_id, "job_id": job_id, "kind": "sampling.provider_execute"}]
        )
    )

    recovered = store.recoverable(batch_size=1)

    assert recovered[0].project_id == project_id
    assert recovered[0].job_id == job_id
    assert recovered[0].kind == "sampling.provider_execute"


def test_outbox_acknowledge_and_fail_accept_psycopg_mapping_rows() -> None:
    project_id = uuid4()
    job_id = uuid4()
    message_store = PostgresOutboxStore(
        lambda: _Connection(
            [
                {
                    "id": uuid4(),
                    "project_id": project_id,
                    "job_id": job_id,
                    "topic": "durable.queued",
                    "payload": {},
                }
            ]
        )
    )
    message = message_store.claim(worker_id="relay", batch_size=1, lease_seconds=30)[0]

    assert PostgresOutboxStore(
        lambda: _Connection([{"acknowledged": True}])
    ).acknowledge(message, worker_id="relay")
    assert PostgresOutboxStore(lambda: _Connection([{"failed": True}])).fail(
        message,
        worker_id="relay",
        error="dispatch_failed",
    )
