from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.rate_limits import ConcurrentRateLimiter
from dramatiq.rate_limits.backends import RedisBackend

from geno_core.collection_jobs import CollectionJobStore
from geno_core.runtime import build_object_store_from_env, build_repository_from_env, close_repository_connection
from workers.knowledge_worker.run_knowledge_pipeline import run_once as run_knowledge_once
from workers.report_export_worker.run_report_export_jobs import process_next_report_export_job


BROKER_URL = os.getenv("GENO_TASK_QUEUE_BROKER_URL", "redis://valkey:6379/0").strip()
if not BROKER_URL:
    raise RuntimeError("GENO_TASK_QUEUE_BROKER_URL is required")

broker = RedisBroker(url=BROKER_URL)
dramatiq.set_broker(broker)
rate_limit_backend = RedisBackend(url=BROKER_URL)
collection_rate_limiter = ConcurrentRateLimiter(
    rate_limit_backend,
    "geo-production-collection-provider",
    limit=max(1, int(os.getenv("GENO_COLLECTION_PROVIDER_CONCURRENCY", "1"))),
    ttl=3_900_000,
)


def _parse_collection_output(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise RuntimeError("collection worker returned no JSON output")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("collection worker returned invalid JSON output") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("collection worker output must be an object")
    return payload


@dramatiq.actor(
    actor_name="process_collection_queue",
    queue_name="collection",
    max_retries=4,
    min_backoff=10_000,
    max_backoff=300_000,
    time_limit=3_900_000,
)
def process_collection_queue() -> dict[str, Any]:
    repository = build_repository_from_env()
    store = CollectionJobStore(repository)
    worker_id = os.getenv("GENO_COLLECTION_WORKER_ID", "dramatiq-collection-worker")
    job = None
    try:
        job = store.claim_next(
            worker_id=worker_id,
            lease_seconds=int(os.getenv("GENO_COLLECTION_JOB_LEASE_SECONDS", "3600")),
        )
        if job is None:
            return {"status": "idle", "processed": False}
        command = [
            sys.executable,
            "workers/collector_worker/run_collection_slice.py",
            "--mode",
            "api",
            "--project-id",
            str(job["project_id"]),
            "--prompt-limit",
            str(job["prompt_limit"]),
            "--sample-size",
            str(job["sample_size"]),
            "--cities",
            ",".join(str(city) for city in (job.get("cities") or ["Global"])),
            "--persist",
            "--persist-analysis",
            "--require-ready-collectors",
            "--require-no-collection-failures",
            "--score-formula-version",
            "visibility_v1.0",
        ]
        with collection_rate_limiter.acquire(raise_on_failure=False) as acquired:
            if not acquired:
                raise RuntimeError("collection provider concurrency limit is busy")
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=int(os.getenv("GENO_COLLECTION_JOB_TIMEOUT_SECONDS", "3600")),
            )
        result = _parse_collection_output(completed.stdout)
        updated = store.complete(job=job, result=result)
        return {"status": str(updated["status"]), "processed": True, "job": updated, "result": result}
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        if job is None:
            raise
        error_message = str(exc)
        if isinstance(exc, subprocess.CalledProcessError):
            error_message = (exc.stderr or exc.stdout or str(exc)).strip()
        updated = store.fail(
            job=job,
            error_code=exc.__class__.__name__,
            error_message=error_message,
            retry_seconds=int(os.getenv("GENO_COLLECTION_RETRY_BACKOFF_SECONDS", "120")),
        )
        return {
            "status": str(updated["status"]),
            "processed": True,
            "job": updated,
            "error": error_message,
        }
    finally:
        close_repository_connection(repository)


@dramatiq.actor(
    actor_name="process_knowledge_queue",
    queue_name="knowledge",
    max_retries=4,
    min_backoff=5_000,
    max_backoff=300_000,
    time_limit=3_600_000,
)
def process_knowledge_queue() -> dict[str, Any]:
    from geno_core.knowledge_pipeline import close_knowledge_repository, connect_knowledge_pipeline_repository

    repository = connect_knowledge_pipeline_repository()
    worker_id = os.getenv("GENO_KNOWLEDGE_WORKER_ID", "dramatiq-knowledge-worker")
    repository.set_maintenance_scope(worker_id=worker_id)
    processed: list[dict[str, Any]] = []
    try:
        for _ in range(max(1, int(os.getenv("GENO_KNOWLEDGE_DRAMATIQ_DRAIN_CYCLES", "20")))):
            result = run_knowledge_once(
                repository,
                worker_id=worker_id,
                lease_seconds=int(os.getenv("GENO_KNOWLEDGE_WORKER_LEASE_SECONDS", "600")),
                max_jobs=int(os.getenv("GENO_KNOWLEDGE_WORKER_MAX_JOBS", "25")),
            )
            current = list(result.get("processed") or [])
            processed.extend(current)
            if not current:
                break
    finally:
        close_knowledge_repository(repository)
    return {"status": "processed", "processed_count": len(processed), "records": processed}


@dramatiq.actor(
    actor_name="process_report_export_queue",
    queue_name="report",
    max_retries=4,
    min_backoff=5_000,
    max_backoff=300_000,
    time_limit=600_000,
)
def process_report_export_queue() -> dict[str, Any]:
    repository = build_repository_from_env()
    object_store = build_object_store_from_env()
    results: list[dict[str, Any]] = []
    try:
        for _ in range(max(1, int(os.getenv("GENO_REPORT_DRAMATIQ_DRAIN_JOBS", "25")))):
            result = process_next_report_export_job(
                repository=repository,
                object_store=object_store,
                updated_by=os.getenv("GENO_REPORT_EXPORT_WORKER_ID", "dramatiq-report-worker"),
                require_object_store=True,
                max_attempts=int(os.getenv("GENO_REPORT_EXPORT_WORKER_MAX_ATTEMPTS", "3")),
                retry_backoff_seconds=int(os.getenv("GENO_REPORT_EXPORT_WORKER_RETRY_BACKOFF_SECONDS", "300")),
                lease_seconds=int(os.getenv("GENO_REPORT_EXPORT_WORKER_LEASE_SECONDS", "900")),
            )
            results.append(result)
            if result.get("status") == "idle":
                break
    finally:
        close_repository_connection(repository)
    return {
        "status": "processed",
        "processed_count": sum(1 for result in results if result.get("processed")),
        "records": results,
    }
