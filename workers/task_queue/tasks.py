from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager, nullcontext
from typing import Any

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import MiddlewareError

from geo_core.collection_jobs import CollectionJobStore
from geo_core.durable_jobs import (
    LeaseClaim,
    LeaseGuard,
    LostLeaseError,
    internal_lease_environment,
)
from geo_core.runtime import (
    build_object_store_from_env,
    build_repository_from_env,
    close_repository_connection,
    validate_runtime_schema_compatibility,
)
from workers.knowledge_worker.run_knowledge_pipeline import run_once as run_knowledge_once
from workers.report_export_worker.run_report_export_jobs import process_next_report_export_job


BROKER_URL = os.getenv("GEO_TASK_QUEUE_BROKER_URL", "redis://valkey:6379/0").strip()
if not BROKER_URL:
    raise RuntimeError("GEO_TASK_QUEUE_BROKER_URL is required")

broker = RedisBroker(url=BROKER_URL)


class SchemaCompatibilityMiddleware(dramatiq.Middleware):
    def before_worker_boot(self, broker: object, worker: object) -> None:
        del broker, worker
        try:
            validate_runtime_schema_compatibility()
        except Exception:
            raise MiddlewareError("Schema v2 compatibility check failed") from None


broker.add_middleware(SchemaCompatibilityMiddleware())
dramatiq.set_broker(broker)

_COLLECTION_ADVISORY_LOCK_NAMESPACE = 1_196_572_994


class CollectionFinalizingDescriptorError(RuntimeError):
    pass


@contextmanager
def _collection_rate_limit_context():
    bypass = os.getenv("GEO_COLLECTION_TEST_BYPASS_RATE_LIMIT", "").strip().lower()
    if bypass in {"1", "true", "yes"}:
        if os.getenv("GEO_DEPLOYMENT_ENVIRONMENT", "").strip().lower() != "test":
            raise RuntimeError("collection rate-limit bypass is restricted to the test environment")
        with nullcontext(True) as acquired:
            yield acquired
        return

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for Collection provider concurrency")
    import psycopg

    connection = psycopg.connect(database_url, autocommit=True)
    acquired_slot: int | None = None
    try:
        with connection.cursor() as cursor:
            for slot in range(max(1, int(os.getenv("GEO_COLLECTION_PROVIDER_CONCURRENCY", "1")))):
                cursor.execute(
                    "SELECT pg_try_advisory_lock(%s, %s)",
                    (_COLLECTION_ADVISORY_LOCK_NAMESPACE, slot),
                )
                if bool(cursor.fetchone()[0]):
                    acquired_slot = slot
                    break
        yield acquired_slot is not None
    finally:
        if acquired_slot is not None:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_unlock(%s, %s)",
                        (_COLLECTION_ADVISORY_LOCK_NAMESPACE, acquired_slot),
                    )
            except Exception:
                pass
        connection.close()


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


def _terminate_collection_child(process: subprocess.Popen[str], *, grace_seconds: float) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.1, grace_seconds))
            except subprocess.TimeoutExpired:
                pass
        # The leader may exit on TERM while a browser/driver descendant
        # ignores it. Always KILL the remaining isolated process group.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            process.wait(timeout=max(1.0, grace_seconds))
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=max(0.1, grace_seconds))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=max(1.0, grace_seconds))


def _run_collection_subprocess(
    command: list[str],
    *,
    guard: LeaseGuard,
    timeout_seconds: int,
    terminate_grace_seconds: float,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    started = time.monotonic()
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_file, tempfile.TemporaryFile(
        mode="w+t", encoding="utf-8"
    ) as stderr_file:
        process = subprocess.Popen(
            command,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            env=environment,
            start_new_session=os.name == "posix",
        )
        try:
            while process.poll() is None:
                guard.raise_if_stopped()
                if time.monotonic() - started >= max(1, timeout_seconds):
                    raise subprocess.TimeoutExpired(command, timeout_seconds)
                time.sleep(0.2)
        except BaseException:
            _terminate_collection_child(process, grace_seconds=terminate_grace_seconds)
            raise
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read()
        stderr = stderr_file.read()
        if process.returncode:
            raise subprocess.CalledProcessError(
                process.returncode,
                command,
                output=stdout,
                stderr=stderr,
            )
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _collection_test_after_claim_failpoint(claim: LeaseClaim) -> None:
    failpoint = os.getenv("GEO_DURABLE_JOB_AFTER_CLAIM_FAILPOINT", "").strip()
    if failpoint not in {"all", "collection_jobs"}:
        return
    if os.getenv("GEO_DEPLOYMENT_ENVIRONMENT", "").strip().lower() != "test":
        raise RuntimeError("durable job failpoints are restricted to the test environment")
    target_attempt = max(
        1, int(os.getenv("GEO_DURABLE_JOB_AFTER_CLAIM_FAILPOINT_ATTEMPT", "1"))
    )
    if claim.attempt_count != target_attempt:
        return
    pause_seconds = max(
        0.0, float(os.getenv("GEO_DURABLE_JOB_AFTER_CLAIM_PAUSE_SECONDS", "0"))
    )
    if pause_seconds:
        time.sleep(pause_seconds)
    else:
        raise RuntimeError("test failpoint after durable collection claim")


def _collection_test_command(command: list[str]) -> list[str]:
    raw_seconds = os.getenv("GEO_COLLECTION_TEST_CHILD_SECONDS", "").strip()
    if not raw_seconds:
        return command
    if os.getenv("GEO_DEPLOYMENT_ENVIRONMENT", "").strip().lower() != "test":
        raise RuntimeError("collection test child is restricted to the test environment")
    seconds = max(0.1, float(raw_seconds))
    code = (
        "import json,time; "
        f"time.sleep({seconds!r}); "
        "print(json.dumps({'success_count': 1, 'failure_count': 0, 'test_child': True}))"
    )
    return [sys.executable, "-c", code]


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
    worker_id = os.getenv("GEO_COLLECTION_WORKER_ID", "dramatiq-collection-worker")
    claim: LeaseClaim | None = None
    guard: LeaseGuard | None = None
    lease_seconds = int(os.getenv("GEO_COLLECTION_JOB_LEASE_SECONDS", "3600"))
    capacity = ExitStack()
    try:
        acquired = capacity.enter_context(_collection_rate_limit_context())
        if not acquired:
            return {"status": "capacity_busy", "processed": False}
        recovery = store.claim_next_outcome(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            mode="recovery",
        )
        store.record_recovery_pass(worker_id=worker_id, slots_used=1)
        if recovery.kind in {"cancelled", "dead_lettered"}:
            return {
                "status": recovery.kind,
                "processed": True,
                "job_id": str(recovery.job_id),
            }
        claim = recovery.claim
        if claim is None:
            claim = store.claim_next(
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                mode="fresh",
            )
        if claim is None:
            return {"status": "idle", "processed": False}
        job = claim.worker_payload()
        guard = store.lease_guard(claim, lease_seconds=lease_seconds).start()
        _collection_test_after_claim_failpoint(claim)
        if claim.claimed_from == "finalizing":
            descriptor = (
                dict(job.get("finalize_descriptor") or {})
                if isinstance(job.get("finalize_descriptor"), dict)
                else {}
            )
            result = (
                dict(descriptor.get("result") or {})
                if isinstance(descriptor.get("result"), dict)
                else {}
            )
            terminal_status = str(descriptor.get("terminal_status") or "")
            if not result or terminal_status not in claim.spec.success_statuses:
                raise CollectionFinalizingDescriptorError(
                    "reclaimed finalizing Collection Job has no valid persisted descriptor"
                )
            guard.raise_if_stopped()
            guard.stop()
            updated = store.complete(claim=claim, result=result)
            return {
                "status": str(updated["status"]),
                "processed": True,
                "job": updated,
                "result": result,
                "descriptor_only_recovery": True,
            }
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
        command = _collection_test_command(command)
        completed = _run_collection_subprocess(
            command,
            guard=guard,
            timeout_seconds=int(os.getenv("GEO_COLLECTION_JOB_TIMEOUT_SECONDS", "3600")),
            terminate_grace_seconds=float(
                os.getenv("GEO_COLLECTION_CHILD_TERMINATE_GRACE_SECONDS", "10")
            ),
            environment={
                **os.environ,
                **internal_lease_environment(claim, lease_seconds=lease_seconds),
            },
        )
        result = _parse_collection_output(completed.stdout)
        guard.raise_if_stopped()
        store.begin_finalizing(claim=claim, result=result)
        guard.raise_if_stopped()
        guard.stop()
        updated = store.complete(claim=claim, result=result)
        return {"status": str(updated["status"]), "processed": True, "job": updated, "result": result}
    except LostLeaseError as exc:
        if guard is not None:
            guard.stop()
        repository.connection.rollback()
        status = "lease_lost"
        if claim is not None and (exc.cancel_requested or (guard is not None and guard.cancel_requested)):
            try:
                updated = store.acknowledge_cancel(claim)
                status = "cancelled"
            except LostLeaseError:
                repository.connection.rollback()
            else:
                return {"status": status, "processed": True, "job": updated}
        return {
            "status": status,
            "processed": claim is not None,
            "job_id": str(claim.job_id) if claim is not None else None,
        }
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        if claim is None:
            raise
        if guard is not None:
            try:
                guard.raise_if_stopped()
            except LostLeaseError as lease_error:
                guard.stop()
                repository.connection.rollback()
                if lease_error.cancel_requested or guard.cancel_requested:
                    try:
                        updated = store.acknowledge_cancel(claim)
                        return {"status": "cancelled", "processed": True, "job": updated}
                    except LostLeaseError:
                        repository.connection.rollback()
                return {"status": "lease_lost", "processed": True, "job_id": str(claim.job_id)}
            guard.stop()
        error_message = str(exc)
        if isinstance(exc, subprocess.CalledProcessError):
            error_message = (exc.stderr or exc.stdout or str(exc)).strip()
        try:
            updated = store.fail(
                claim=claim,
                error_code=exc.__class__.__name__,
                error_message=error_message,
                retry_seconds=int(os.getenv("GEO_COLLECTION_RETRY_BACKOFF_SECONDS", "120")),
                retryable=not isinstance(
                    exc,
                    (FileNotFoundError, PermissionError, CollectionFinalizingDescriptorError),
                ),
            )
        except LostLeaseError:
            repository.connection.rollback()
            return {"status": "lease_lost", "processed": True, "job_id": str(claim.job_id)}
        return {
            "status": str(updated["status"]),
            "processed": True,
            "job": updated,
            "error": error_message,
        }
    finally:
        if guard is not None:
            guard.stop()
        capacity.close()
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
    from geo_core.knowledge_pipeline import close_knowledge_repository, connect_knowledge_pipeline_repository

    repository = connect_knowledge_pipeline_repository()
    worker_id = os.getenv("GEO_KNOWLEDGE_WORKER_ID", "dramatiq-knowledge-worker")
    repository.set_maintenance_scope(worker_id=worker_id)
    processed: list[dict[str, Any]] = []
    try:
        for _ in range(max(1, int(os.getenv("GEO_KNOWLEDGE_DRAMATIQ_DRAIN_CYCLES", "20")))):
            result = run_knowledge_once(
                repository,
                worker_id=worker_id,
                lease_seconds=int(os.getenv("GEO_KNOWLEDGE_WORKER_LEASE_SECONDS", "600")),
                max_jobs=int(os.getenv("GEO_KNOWLEDGE_WORKER_MAX_JOBS", "25")),
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
        for _ in range(max(1, int(os.getenv("GEO_REPORT_DRAMATIQ_DRAIN_JOBS", "25")))):
            result = process_next_report_export_job(
                repository=repository,
                object_store=object_store,
                updated_by=os.getenv("GEO_REPORT_EXPORT_WORKER_ID", "dramatiq-report-worker"),
                require_object_store=True,
                max_attempts=int(os.getenv("GEO_REPORT_EXPORT_WORKER_MAX_ATTEMPTS", "3")),
                retry_backoff_seconds=int(os.getenv("GEO_REPORT_EXPORT_WORKER_RETRY_BACKOFF_SECONDS", "300")),
                lease_seconds=int(os.getenv("GEO_REPORT_EXPORT_WORKER_LEASE_SECONDS", "900")),
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
