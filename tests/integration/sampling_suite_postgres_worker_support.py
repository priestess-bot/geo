"""Worker-state helpers kept separate from the Sampling Suite setup scenario."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.project_scope import set_project_scope
from geo_core.sampling import (
    PostgresSamplingCancellationRepository,
    ProviderSamplingAttemptAdmission,
)
from geo_core.sampling.postgres_worker_repository import PostgresWorkflowCSamplingRepository


def assert_claim_and_retry_project_sampling_state(
    *,
    app_url: str,
    worker_url: str,
    project_id: UUID,
    durable_job_id: UUID,
    task_id: UUID,
    attempt_id: UUID,
    admission: ProviderSamplingAttemptAdmission,
    first_task_version: int,
    first_attempt_version: int,
    now: datetime,
) -> None:
    def connect_worker():
        return psycopg.connect(worker_url, row_factory=dict_row)

    store = PostgresDurableJobStore(connect_worker)
    repository = PostgresWorkflowCSamplingRepository(connect_worker)
    claimed = store.claim(
        job_id=durable_job_id,
        project_id=project_id,
        expected_kind="sampling.provider_execute",
        worker_id="sampling-suite-integration-worker",
        lease_for=timedelta(minutes=2),
    )
    assert claimed.disposition == "claimed" and claimed.lease is not None
    assert sampling_attempt_state(
        worker_url=worker_url,
        project_id=project_id,
        task_id=task_id,
        attempt_id=attempt_id,
    ) == ("running", first_task_version + 1, "running", first_attempt_version + 1)
    state = repository.provider_state(project_id=project_id, spec=admission.spec)
    assert state.task_version == first_task_version + 1
    assert state.attempt_version == first_attempt_version + 1
    with store.fenced_transaction(claimed.lease) as connection:
        repository.record_failure(
            connection=connection,
            lease=claimed.lease,
            spec_hash=admission.spec_hash,
            state=state,
            task_version=state.task_version,
            attempt_version=state.attempt_version,
            error_code="provider_rate_limited",
            retryable=True,
            occurred_at=now,
        )
        assert store.fail_with_retry_in_transaction(
            connection,
            claimed.lease,
            error_code="provider_rate_limited",
            details={"sampling_status": "retry_ready"},
            retry_delay=timedelta(0),
        ) == "retry_wait"
    assert sampling_attempt_state(
        worker_url=worker_url,
        project_id=project_id,
        task_id=task_id,
        attempt_id=attempt_id,
    ) == ("retry_ready", first_task_version + 2, "queued", first_attempt_version + 2)
    reclaimed = store.claim(
        job_id=durable_job_id,
        project_id=project_id,
        expected_kind="sampling.provider_execute",
        worker_id="sampling-suite-integration-worker",
        lease_for=timedelta(minutes=2),
    )
    assert reclaimed.disposition == "claimed" and reclaimed.lease is not None
    assert reclaimed.lease.fencing_generation == claimed.lease.fencing_generation + 1
    assert sampling_attempt_state(
        worker_url=worker_url,
        project_id=project_id,
        task_id=task_id,
        attempt_id=attempt_id,
    ) == ("running", first_task_version + 3, "running", first_attempt_version + 3)
    cancellation = PostgresSamplingCancellationRepository(
        connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
    )
    cancelled = cancellation.cancel_run(
        project_id=project_id,
        run_id=admission.run_id,
        idempotency_key="sampling-run:cancel:first",
        cancelled_at=now,
    )
    replayed_cancel = cancellation.cancel_run(
        project_id=project_id,
        run_id=admission.run_id,
        idempotency_key="sampling-run:cancel:first",
        cancelled_at=now,
    )
    assert cancelled.run_id == admission.run_id
    assert cancelled.run_status == "cancel_requested"
    assert cancelled.released_task_count == 9
    assert cancelled.cancellation_requested_count == 1
    assert cancelled.attempt_ids == (attempt_id,)
    assert cancelled.replayed is False
    assert replayed_cancel.attempt_ids == (attempt_id,)
    assert replayed_cancel.replayed is True
    assert sampling_attempt_state(
        worker_url=worker_url,
        project_id=project_id,
        task_id=task_id,
        attempt_id=attempt_id,
    ) == ("cancel_requested", first_task_version + 4, "running", first_attempt_version + 3)
    assert sampling_run_state(
        worker_url=worker_url, project_id=project_id, run_id=admission.run_id
    ) == ("cancel_requested", 9)
    store.cancel(reclaimed.lease)
    assert sampling_attempt_state(
        worker_url=worker_url,
        project_id=project_id,
        task_id=task_id,
        attempt_id=attempt_id,
    ) == ("cancelled", first_task_version + 5, "cancelled", first_attempt_version + 4)
    assert sampling_run_state(
        worker_url=worker_url, project_id=project_id, run_id=admission.run_id
    ) == ("cancelled", 9)
    terminal_replay = cancellation.cancel_run(
        project_id=project_id,
        run_id=admission.run_id,
        idempotency_key="sampling-run:cancel:first",
        cancelled_at=now,
    )
    assert terminal_replay.replayed is True
    assert terminal_replay.attempt_ids == (attempt_id,)


def sampling_attempt_state(
    *, worker_url: str, project_id: UUID, task_id: UUID, attempt_id: UUID
) -> tuple[str, int, str, int]:
    with psycopg.connect(worker_url, row_factory=dict_row) as connection:
        set_project_scope(connection, project_id)
        row = connection.execute(
            """SELECT task.status AS task_status, task.version AS task_version,
                      attempt.status AS attempt_status, attempt.version AS attempt_version
                 FROM workflow_c_sampling_tasks AS task
                 JOIN workflow_c_sampling_attempts AS attempt
                   ON attempt.project_id = task.project_id AND attempt.task_id = task.id
                WHERE task.project_id = %s AND task.id = %s AND attempt.id = %s""",
            (project_id, task_id, attempt_id),
        ).fetchone()
    assert row is not None
    return (
        str(row["task_status"]),
        int(row["task_version"]),
        str(row["attempt_status"]),
        int(row["attempt_version"]),
    )


def sampling_run_state(
    *, worker_url: str, project_id: UUID, run_id: UUID
) -> tuple[str, int]:
    with psycopg.connect(worker_url, row_factory=dict_row) as connection:
        set_project_scope(connection, project_id)
        row = connection.execute(
            """SELECT status, released_task_count
                 FROM workflow_c_sampling_runs
                WHERE project_id = %s AND id = %s""",
            (project_id, run_id),
        ).fetchone()
    assert row is not None
    return str(row["status"]), int(row["released_task_count"])


def provider_attempt_spec(
    *,
    run_id: UUID,
    task_id: UUID,
    attempt_id: UUID,
    task_version: int,
    question_hash: str,
    admitted_at: datetime,
) -> dict[str, object]:
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    return {
        "schema_version": 1,
        "kind": "sampling.provider_execute",
        "run_id": str(run_id),
        "task_id": str(task_id),
        "attempt_id": str(attempt_id),
        "task_version": task_version,
        "attempt_version": 1,
        "question": {"text": "Which provider should I choose?", "sha256": question_hash},
        "runtime_selection_id": "d28c0a8d-4c30-4a7b-b9a9-2ed2b6849b91",
        "admitted_by": "1e1b93b6-5a10-476d-9a3a-b0ab8d2d79b3",
        "admitted_at": admitted_at.isoformat(),
        "prompt": {
            "binding_id": "306b1ddc-5a45-4b27-a039-65e97dced3b0",
            "state_id": "b2a7430d-a5a9-4a34-b8ca-290dae9afae6",
            "state_version": 1,
            "release_id": "ef17c4e0-7f6b-4af6-9b62-a6da73484f34",
            "release_hash": _hash("prompt-release"),
            "purpose": "geo_measurement",
            "bundle_hash": _hash("prompt-bundle"),
            "system_message": "Return a JSON answer.",
            "answer_field": "answer",
            "output_schema": schema,
            "application_output_schema": schema,
            "temperature": 0.2,
            "max_output_tokens": 256,
            "seed": 7,
            "tool_mode": None,
        },
        "search_mode": "enabled",
        "deadline_at": None,
    }


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
