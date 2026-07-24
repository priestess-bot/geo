"""Dedicated least-privilege consumer for Workflow C artifact maintenance."""

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
from geo_core.placements.worker_composition import PlacementWorkerDispatcher
from geo_core.runtime_health import PeriodicHeartbeat, RuntimeHealthRepository, RuntimeHeartbeat
from geo_core.workflow_c_artifacts.composition import (
    build_workflow_c_artifact_maintenance_composition,
)
from geo_core.workflow_c_artifacts.lifecycle import (
    WORKFLOW_C_ARTIFACT_MAINTENANCE_JOB_KIND,
)
from geo_worker.config import (
    bounded_int_setting,
    runtime_heartbeat_identity,
    runtime_heartbeat_interval_seconds,
    secret_setting,
)
from geo_worker.workflow_c_artifact_maintenance import (
    WorkflowCArtifactMaintenanceOperation,
)
from geo_worker.workflow_c_maintenance_routing import (
    WORKFLOW_C_MAINTENANCE_ACTOR,
    WORKFLOW_C_MAINTENANCE_QUEUE,
)


_BROKER_URL = os.getenv("GEO_TASK_QUEUE_BROKER_URL", "redis://valkey:6379/0").strip()
if not _BROKER_URL:
    raise RuntimeError("GEO_TASK_QUEUE_BROKER_URL is required")


class _HeartbeatMiddleware(Middleware):
    def __init__(self) -> None:
        self._periodic: PeriodicHeartbeat | None = None
        self._lock = threading.Lock()

    def after_process_boot(self, broker) -> None:
        del broker
        # Refuse a ready heartbeat until the restricted deleter composition is usable.
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
                        "workflow_c_maintenance_worker", process_id=os.getpid()
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
    operation: WorkflowCArtifactMaintenanceOperation

    def handle(self, lease: WorkerLease):
        return self.operation.execute(lease)


@lru_cache(maxsize=1)
def maintenance_dispatcher() -> PlacementWorkerDispatcher:
    database_url = secret_setting("GEO_DATABASE_URL")

    def connect():
        return psycopg.connect(database_url, row_factory=dict_row)

    store = PostgresDurableJobStore(connect)
    worker_id = os.getenv(
        "GEO_WORKER_ID", f"workflow-c-maintenance:{socket.gethostname()}"
    ).strip()
    if not worker_id:
        raise RuntimeError("GEO_WORKER_ID cannot be empty")
    lease_for = timedelta(
        seconds=bounded_int_setting(
            "GEO_WORKFLOW_C_ARTIFACT_MAINTENANCE_JOB_LEASE_SECONDS",
            300,
            minimum=30,
            maximum=3600,
        )
    )
    composition = build_workflow_c_artifact_maintenance_composition(
        connection_factory=connect,
        worker_id=worker_id,
        deletion_lease_seconds=bounded_int_setting(
            "GEO_WORKFLOW_C_ARTIFACT_DELETION_LEASE_SECONDS",
            120,
            minimum=30,
            maximum=3600,
        ),
        max_deletions=bounded_int_setting(
            "GEO_WORKFLOW_C_ARTIFACT_MAX_DELETIONS_PER_JOB",
            100,
            minimum=1,
            maximum=1000,
        ),
    )
    operation = WorkflowCArtifactMaintenanceOperation(
        store=store,
        service=composition.service,
        lease_for=lease_for,
    )
    return PlacementWorkerDispatcher(
        store=store,
        handlers={WORKFLOW_C_ARTIFACT_MAINTENANCE_JOB_KIND: _Handler(operation)},
        worker_id=worker_id,
        lease_for=lease_for,
    )


@dramatiq.actor(
    actor_name=WORKFLOW_C_MAINTENANCE_ACTOR,
    queue_name=WORKFLOW_C_MAINTENANCE_QUEUE,
    max_retries=0,
    time_limit=900_000,
)
def process_workflow_c_maintenance_job(
    job_id: str, project_id: str
) -> dict[str, object]:
    return dict(
        maintenance_dispatcher().process(
            job_id=UUID(job_id), project_id=UUID(project_id)
        )
    )


__all__ = [
    "WORKFLOW_C_MAINTENANCE_ACTOR",
    "WORKFLOW_C_MAINTENANCE_QUEUE",
    "maintenance_dispatcher",
    "process_workflow_c_maintenance_job",
]
