"""Periodic Durable Job seeding for idle Workflow C artifact retention."""

from __future__ import annotations

import argparse
import logging
import os
import time

import psycopg
from psycopg.rows import dict_row

from geo_core.runtime_health import RuntimeHealthRepository, RuntimeHeartbeat
from geo_core.workflow_c_artifacts.postgres_scheduler import (
    PostgresWorkflowCArtifactMaintenanceSchedulerRepository,
)
from geo_core.workflow_c_artifacts.scheduler import WorkflowCArtifactMaintenanceScheduler
from geo_worker.config import (
    bounded_int_setting,
    runtime_heartbeat_identity,
    runtime_heartbeat_interval_seconds,
    secret_setting,
)


LOGGER = logging.getLogger(__name__)


def maintenance_scheduler() -> WorkflowCArtifactMaintenanceScheduler:
    database_url = secret_setting("GEO_DATABASE_URL")
    return WorkflowCArtifactMaintenanceScheduler(
        repository=PostgresWorkflowCArtifactMaintenanceSchedulerRepository(
            connect=lambda: psycopg.connect(database_url, row_factory=dict_row)
        ),
        staged_grace_seconds=bounded_int_setting(
            "GEO_WORKFLOW_C_ARTIFACT_STAGED_GRACE_SECONDS",
            900,
            minimum=60,
            maximum=86_400,
        ),
        max_projects=bounded_int_setting(
            "GEO_WORKFLOW_C_ARTIFACT_MAINTENANCE_SEED_BATCH_SIZE",
            100,
            minimum=1,
            maximum=1000,
        ),
    )


def _poll_seconds() -> float:
    return float(
        bounded_int_setting(
            "GEO_WORKFLOW_C_ARTIFACT_MAINTENANCE_SCHEDULE_SECONDS",
            60,
            minimum=5,
            maximum=3600,
        )
    )


def _heartbeat() -> RuntimeHeartbeat:
    database_url = secret_setting("GEO_DATABASE_URL")
    return RuntimeHeartbeat(
        RuntimeHealthRepository(lambda: psycopg.connect(database_url)),
        runtime_heartbeat_identity(
            "workflow_c_maintenance_scheduler", process_id=os.getpid()
        ),
        interval_seconds=runtime_heartbeat_interval_seconds(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed project-scoped Workflow C artifact maintenance Jobs"
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    scheduler = maintenance_scheduler()
    heartbeat = _heartbeat()
    heartbeat.pulse(status="starting", force=True)
    try:
        while True:
            result = scheduler.run_once()
            LOGGER.info(
                "workflow_c_artifact_maintenance_seed completed projects=%s inserted=%s coalesced=%s",
                result.scheduled_project_count,
                result.inserted_job_count,
                result.coalesced_job_count,
            )
            heartbeat.pulse(status="ready", force=True)
            if args.once:
                return 0
            time.sleep(_poll_seconds())
    except Exception:
        heartbeat.pulse(status="failed", force=True)
        raise
    finally:
        heartbeat.pulse(status="stopping", force=True)


if __name__ == "__main__":
    raise SystemExit(main())
