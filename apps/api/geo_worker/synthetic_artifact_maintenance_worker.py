"""Dedicated least-privilege consumer for Synthetic raw-artifact retention."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
import os
import socket
import threading
from uuid import UUID

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Middleware
import psycopg
from psycopg.rows import dict_row

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.object_store_config import build_object_store_from_prefix
from geo_core.placements.worker_composition import PlacementWorkerDispatcher
from geo_core.runtime_health import PeriodicHeartbeat, RuntimeHealthRepository, RuntimeHeartbeat
from geo_core.synthetic_lab.artifact_maintenance import SyntheticArtifactMaintenanceService
from geo_core.synthetic_lab.artifact_maintenance_contracts import (
    SYNTHETIC_ARTIFACT_MAINTENANCE_ACTOR,
    SYNTHETIC_ARTIFACT_MAINTENANCE_JOB_KIND,
    SYNTHETIC_ARTIFACT_MAINTENANCE_QUEUE,
)
from geo_core.synthetic_lab.postgres_artifact_maintenance import (
    PostgresSyntheticArtifactMaintenanceRepository,
)
from geo_core.synthetic_lab.raw_artifact_storage import RawArtifactStores
from geo_worker.config import (
    bounded_int_setting,
    runtime_heartbeat_identity,
    runtime_heartbeat_interval_seconds,
    secret_setting,
)
from geo_worker.synthetic_artifact_maintenance import SyntheticArtifactMaintenanceOperation


_BROKER_URL = os.getenv("GEO_TASK_QUEUE_BROKER_URL", "redis://valkey:6379/0").strip()
_RAW_BUCKET = "geo-synthetic-style-raw"
_DERIVED_BUCKET = "geo-synthetic-style-derived"
if not _BROKER_URL:
    raise RuntimeError("GEO_TASK_QUEUE_BROKER_URL is required")


class _HeartbeatMiddleware(Middleware):
    def __init__(self) -> None:
        self._periodic: PeriodicHeartbeat | None = None
        self._lock = threading.Lock()

    def after_process_boot(self, broker) -> None:
        del broker
        # Validate deletion-only credentials before any consumer advertises ready.
        maintenance_dispatcher()
        self._heartbeat().mark_starting()

    def after_consumer_thread_boot(self, broker, thread) -> None:
        del broker, thread
        self._heartbeat().start()

    def before_consumer_thread_shutdown(self, broker, thread) -> None:
        del broker, thread
        with self._lock:
            periodic = self._periodic
        if periodic is not None:
            periodic.stop()

    def _heartbeat(self) -> PeriodicHeartbeat:
        with self._lock:
            if self._periodic is None:
                interval = runtime_heartbeat_interval_seconds()
                repository = RuntimeHealthRepository(
                    lambda: psycopg.connect(secret_setting("GEO_DATABASE_URL"))
                )
                heartbeat = RuntimeHeartbeat(
                    repository,
                    runtime_heartbeat_identity(
                        "synthetic_artifact_maintenance_worker", process_id=os.getpid()
                    ),
                    interval_seconds=interval,
                )
                self._periodic = PeriodicHeartbeat(
                    heartbeat, interval_seconds=float(interval)
                )
            return self._periodic


broker = RedisBroker(url=_BROKER_URL)
broker.add_middleware(_HeartbeatMiddleware())
dramatiq.set_broker(broker)


@dataclass(frozen=True)
class _Handler:
    operation: SyntheticArtifactMaintenanceOperation

    def handle(self, lease: WorkerLease):
        return self.operation.execute(lease)


@lru_cache(maxsize=1)
def maintenance_dispatcher() -> PlacementWorkerDispatcher:
    database_url = secret_setting("GEO_DATABASE_URL")

    def connect():
        return psycopg.connect(database_url, row_factory=dict_row)

    raw_store = build_object_store_from_prefix(
        "GEO_SYNTHETIC_ARTIFACT_DELETER_RAW_OBJECT_STORE"
    )
    derived_store = build_object_store_from_prefix(
        "GEO_SYNTHETIC_ARTIFACT_DELETER_DERIVED_OBJECT_STORE"
    )
    if raw_store.bucket != _RAW_BUCKET or derived_store.bucket != _DERIVED_BUCKET:
        raise RuntimeError("Synthetic artifact deleter buckets are not isolated")
    worker_id = os.getenv(
        "GEO_WORKER_ID", f"synthetic-artifact-maintenance:{socket.gethostname()}"
    ).strip()
    if not worker_id:
        raise RuntimeError("GEO_WORKER_ID cannot be empty")
    lease_for = timedelta(
        seconds=bounded_int_setting(
            "GEO_SYNTHETIC_ARTIFACT_MAINTENANCE_JOB_LEASE_SECONDS",
            300,
            minimum=30,
            maximum=3_600,
        )
    )
    service = SyntheticArtifactMaintenanceService(
        repository=PostgresSyntheticArtifactMaintenanceRepository(connect),
        stores=RawArtifactStores(
            encrypted_raw=raw_store,
            restricted_independent_dek=raw_store,
            derived_project=derived_store,
        ),
        worker_id=worker_id,
        expiry_batch_size=bounded_int_setting(
            "GEO_SYNTHETIC_ARTIFACT_EXPIRY_BATCH_SIZE",
            100,
            minimum=1,
            maximum=1_000,
        ),
        deletion_lease_seconds=bounded_int_setting(
            "GEO_SYNTHETIC_ARTIFACT_DELETION_LEASE_SECONDS",
            120,
            minimum=5,
            maximum=3_600,
        ),
        max_deletions=bounded_int_setting(
            "GEO_SYNTHETIC_ARTIFACT_MAX_DELETIONS_PER_JOB",
            100,
            minimum=1,
            maximum=100,
        ),
    )
    store = PostgresDurableJobStore(connect)
    operation = SyntheticArtifactMaintenanceOperation(
        store=store,
        service=service,
        lease_for=lease_for,
    )
    return PlacementWorkerDispatcher(
        store=store,
        handlers={SYNTHETIC_ARTIFACT_MAINTENANCE_JOB_KIND: _Handler(operation)},
        worker_id=worker_id,
        lease_for=lease_for,
    )


@dramatiq.actor(
    actor_name=SYNTHETIC_ARTIFACT_MAINTENANCE_ACTOR,
    queue_name=SYNTHETIC_ARTIFACT_MAINTENANCE_QUEUE,
    max_retries=0,
    time_limit=900_000,
)
def process_synthetic_artifact_maintenance_job(
    job_id: str, project_id: str
) -> dict[str, object]:
    return dict(
        maintenance_dispatcher().process(job_id=UUID(job_id), project_id=UUID(project_id))
    )


__all__ = [
    "SYNTHETIC_ARTIFACT_MAINTENANCE_ACTOR",
    "SYNTHETIC_ARTIFACT_MAINTENANCE_QUEUE",
    "maintenance_dispatcher",
    "process_synthetic_artifact_maintenance_job",
]
