"""Reliable PostgreSQL Outbox relay plus expired-lease recovery dispatch."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import os
import socket
import time

import psycopg

from geo_core.jobs.outbox import PostgresOutboxStore
from geo_core.runtime_health import RuntimeHealthRepository, RuntimeHeartbeat
from geo_worker.config import (
    bounded_int_setting,
    runtime_heartbeat_identity,
    runtime_heartbeat_interval_seconds,
    secret_setting,
)
from geo_worker.recommendation_artifact_maintenance_routing import (
    RECOMMENDATION_ARTIFACT_MAINTENANCE_JOB_KIND,
    RECOMMENDATION_ARTIFACT_MAINTENANCE_OUTBOX_TOPICS,
)
from geo_core.synthetic_lab.artifact_maintenance_contracts import (
    SYNTHETIC_ARTIFACT_MAINTENANCE_OUTBOX_TOPICS,
)
from geo_worker.tasks import send_durable_job
from geo_worker.workflow_c_maintenance_routing import (
    WORKFLOW_C_ARTIFACT_MAINTENANCE_JOB_KIND,
    WORKFLOW_C_MAINTENANCE_OUTBOX_TOPICS,
)


_STYLE_COLLECTION_TOPICS = frozenset(
    {"synthetic.style.collect.queued", "synthetic.style_collection.queued"}
)


def _send_job(
    *,
    job_id,
    project_id,
    style_collection: bool,
    workflow_c_maintenance: bool,
    recommendation_artifact_maintenance: bool,
    synthetic_artifact_maintenance: bool,
) -> None:
    send_durable_job(
        job_id=job_id,
        project_id=project_id,
        style_collection=style_collection,
        workflow_c_maintenance=workflow_c_maintenance,
        recommendation_artifact_maintenance=recommendation_artifact_maintenance,
        synthetic_artifact_maintenance=synthetic_artifact_maintenance,
    )


def enqueue_synthetic_artifact_maintenance(
    database_url: str, *, now: datetime | None = None
) -> int:
    """Create only idempotent Durable Jobs/outbox rows through the worker RPC."""
    scheduled_at = datetime.now(UTC) if now is None else now
    if scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
        raise ValueError("synthetic artifact maintenance time must be timezone-aware")
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            "SELECT * FROM geo_enqueue_synthetic_artifact_maintenance(%s)",
            (scheduled_at,),
        ).fetchall()
    return len(rows)


def relay_once(store: PostgresOutboxStore, *, worker_id: str, batch_size: int) -> int:
    delivered = 0
    for message in store.claim(worker_id=worker_id, batch_size=batch_size, lease_seconds=30):
        try:
            _send_job(
                job_id=message.job_id,
                project_id=message.project_id,
                style_collection=message.topic in _STYLE_COLLECTION_TOPICS,
                workflow_c_maintenance=(
                    message.topic in WORKFLOW_C_MAINTENANCE_OUTBOX_TOPICS
                ),
                recommendation_artifact_maintenance=(
                    message.topic in RECOMMENDATION_ARTIFACT_MAINTENANCE_OUTBOX_TOPICS
                ),
                synthetic_artifact_maintenance=(
                    message.topic in SYNTHETIC_ARTIFACT_MAINTENANCE_OUTBOX_TOPICS
                ),
            )
        except Exception:
            store.fail(message, worker_id=worker_id, error="dispatch_failed")
        else:
            if store.acknowledge(message, worker_id=worker_id):
                delivered += 1
    return delivered


def recover_once(store: PostgresOutboxStore, *, batch_size: int) -> int:
    jobs = store.recoverable(batch_size=batch_size)
    dispatched = 0
    for job in jobs:
        try:
            _send_job(
                job_id=job.job_id,
                project_id=job.project_id,
                style_collection=job.kind in {"style.collect", "style_collection"},
                workflow_c_maintenance=(
                    job.kind == WORKFLOW_C_ARTIFACT_MAINTENANCE_JOB_KIND
                ),
                recommendation_artifact_maintenance=(
                    job.kind == RECOMMENDATION_ARTIFACT_MAINTENANCE_JOB_KIND
                ),
                synthetic_artifact_maintenance=(
                    job.kind in SYNTHETIC_ARTIFACT_MAINTENANCE_OUTBOX_TOPICS
                ),
            )
        except Exception:
            continue
        dispatched += 1
    return dispatched


def main() -> int:
    parser = argparse.ArgumentParser(description="Relay GEO durable job wakeups")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--recovery-seconds", type=float, default=15.0)
    parser.add_argument("--synthetic-maintenance-seconds", type=int)
    args = parser.parse_args()
    database_url = secret_setting("GEO_DATABASE_URL")
    store = PostgresOutboxStore(lambda: psycopg.connect(database_url))
    worker_id = os.getenv("GEO_OUTBOX_WORKER_ID", f"outbox:{socket.gethostname()}")
    heartbeat = RuntimeHeartbeat(
        RuntimeHealthRepository(lambda: psycopg.connect(database_url)),
        runtime_heartbeat_identity("outbox_relay", process_id=os.getpid()),
        interval_seconds=runtime_heartbeat_interval_seconds(),
    )
    synthetic_maintenance_seconds = args.synthetic_maintenance_seconds
    if synthetic_maintenance_seconds is None:
        synthetic_maintenance_seconds = bounded_int_setting(
            "GEO_SYNTHETIC_ARTIFACT_MAINTENANCE_POLL_SECONDS",
            60,
            minimum=10,
            maximum=3600,
        )
    elif not 10 <= synthetic_maintenance_seconds <= 3600:
        raise RuntimeError("--synthetic-maintenance-seconds must be between 10 and 3600")
    heartbeat.pulse(status="starting", force=True)
    if args.once:
        try:
            enqueue_synthetic_artifact_maintenance(database_url)
        except psycopg.Error:
            heartbeat.pulse(status="failed", force=True)
            return 1
        heartbeat.pulse(status="ready", force=True)
        relay_once(store, worker_id=worker_id, batch_size=args.batch_size)
        recover_once(store, batch_size=args.batch_size)
        heartbeat.pulse(status="stopping", force=True)
        return 0
    last_recovery = 0.0
    last_synthetic_maintenance = float("-inf")
    try:
        while True:
            now = time.monotonic()
            if now - last_synthetic_maintenance >= synthetic_maintenance_seconds:
                try:
                    enqueue_synthetic_artifact_maintenance(database_url)
                except psycopg.Error:
                    # Do not invent a broker-only maintenance task when the worker
                    # transaction could not atomically create its durable intent.
                    heartbeat.pulse(status="failed", force=True)
                    last_synthetic_maintenance = now
                    time.sleep(max(args.poll_seconds, 0.1))
                    continue
                last_synthetic_maintenance = now
            heartbeat.pulse(status="ready")
            relay_once(store, worker_id=worker_id, batch_size=args.batch_size)
            if now - last_recovery >= max(args.recovery_seconds, 5.0):
                recover_once(store, batch_size=args.batch_size)
                last_recovery = now
            heartbeat.pulse(status="ready")
            time.sleep(max(args.poll_seconds, 0.1))
    finally:
        heartbeat.pulse(status="stopping", force=True)


if __name__ == "__main__":
    raise SystemExit(main())
