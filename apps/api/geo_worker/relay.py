"""Reliable PostgreSQL Outbox relay plus expired-lease recovery dispatch."""

from __future__ import annotations

import argparse
import os
import socket
import time

import psycopg

from geo_core.jobs.outbox import PostgresOutboxStore
from geo_worker.config import secret_setting
from geo_worker.tasks import process_durable_job


def relay_once(store: PostgresOutboxStore, *, worker_id: str, batch_size: int) -> int:
    delivered = 0
    for message in store.claim(worker_id=worker_id, batch_size=batch_size, lease_seconds=30):
        try:
            process_durable_job.send(str(message.job_id), str(message.project_id))
        except Exception as exc:
            store.fail(message, worker_id=worker_id, error=str(exc))
        else:
            if store.acknowledge(message, worker_id=worker_id):
                delivered += 1
    return delivered


def recover_once(store: PostgresOutboxStore, *, batch_size: int) -> int:
    jobs = store.recoverable(batch_size=batch_size)
    for job in jobs:
        process_durable_job.send(str(job.job_id), str(job.project_id))
    return len(jobs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Relay GEO durable job wakeups")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--recovery-seconds", type=float, default=15.0)
    args = parser.parse_args()
    database_url = secret_setting("GEO_DATABASE_URL")
    store = PostgresOutboxStore(lambda: psycopg.connect(database_url))
    worker_id = os.getenv("GEO_OUTBOX_WORKER_ID", f"outbox:{socket.gethostname()}")
    if args.once:
        relay_once(store, worker_id=worker_id, batch_size=args.batch_size)
        recover_once(store, batch_size=args.batch_size)
        return 0
    last_recovery = 0.0
    while True:
        relay_once(store, worker_id=worker_id, batch_size=args.batch_size)
        now = time.monotonic()
        if now - last_recovery >= max(args.recovery_seconds, 5.0):
            recover_once(store, batch_size=args.batch_size)
            last_recovery = now
        time.sleep(max(args.poll_seconds, 0.1))


if __name__ == "__main__":
    raise SystemExit(main())
