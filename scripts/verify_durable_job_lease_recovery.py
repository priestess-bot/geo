from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def _stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _compose(project: str, *args: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "docker",
            "compose",
            "-p",
            project,
            "-f",
            "infra/docker-compose.yml",
            "-f",
            "infra/docker-compose.durable-leases.test.yml",
            *args,
        ],
        timeout=timeout,
    )


def _wait_for(
    description: str,
    predicate: Callable[[], Any],
    *,
    timeout_seconds: float,
    interval_seconds: float = 0.25,
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    last_value: Any = None
    while time.monotonic() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(interval_seconds)
    raise TimeoutError(f"timed out waiting for {description}; last value={last_value!r}")


def _record(checks: list[dict[str, Any]], name: str, action: Callable[[], Any]) -> Any:
    started = time.monotonic()
    try:
        details = action()
    except Exception as exc:
        checks.append(
            {
                "name": name,
                "status": "failed",
                "duration_seconds": round(time.monotonic() - started, 3),
                "error": f"{exc.__class__.__name__}: {exc}",
            }
        )
        raise
    checks.append(
        {
            "name": name,
            "status": "passed",
            "duration_seconds": round(time.monotonic() - started, 3),
            "details": details,
        }
    )
    return details


def _schema_check(connection: Any) -> dict[str, Any]:
    tables = (
        "knowledge_import_jobs",
        "crawl_jobs",
        "knowledge_parser_runs",
        "chunk_jobs",
        "embedding_jobs",
        "fact_extraction_jobs",
        "prompt_generation_jobs",
        "content_generation_jobs",
        "collection_jobs",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name, count(*)
            FROM information_schema.columns
            WHERE table_schema = 'public' AND column_name = 'lease_token'
              AND table_name = ANY(%s)
            GROUP BY table_name
            ORDER BY table_name
            """,
            (list(tables),),
        )
        token_tables = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT count(*) FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname LIKE 'idx_%_durable_%'
            """
        )
        durable_index_count = int(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT count(*) FROM pg_constraint
            WHERE conname LIKE '%_active_lease_check'
            """
        )
        active_check_count = int(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conname = 'durable_job_metric_counters_metric_name_check'
            """
        )
        metric_constraint = str((cursor.fetchone() or [""])[0])
    connection.commit()
    if set(token_tables) != set(tables):
        raise AssertionError(f"lease_token coverage mismatch: {token_tables}")
    if durable_index_count != 18:
        raise AssertionError(f"expected 18 durable indexes, found {durable_index_count}")
    if active_check_count != 9:
        raise AssertionError(f"expected 9 active lease checks, found {active_check_count}")
    if "dead_lettered" not in metric_constraint:
        raise AssertionError("durable metric allowlist does not permit dead_lettered transitions")
    return {
        "lease_token_tables": len(token_tables),
        "durable_indexes": durable_index_count,
        "active_lease_checks": active_check_count,
        "dead_letter_metric_allowed": True,
    }


def _seed_scope(connection: Any) -> tuple[object, object]:
    tenant_id = uuid4()
    project_id = uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (id, name, slug) VALUES (%s, 'Durable verifier', %s)",
            (tenant_id, f"durable-verifier-{tenant_id}"),
        )
        cursor.execute(
            """
            INSERT INTO projects (
              id, tenant_id, name, market_code, industry_code,
              target_brand, category, prompt_version, status
            ) VALUES (%s, %s, 'Durable verifier', 'GLOBAL', 'test',
                      'VerifierBrand', 'test', 'v1', 'active')
            """,
            (project_id, tenant_id),
        )
    connection.commit()
    return tenant_id, project_id


def _audit_fingerprints(connection: Any, job_id: object) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT output_refs->>'token_fingerprint'
            FROM audit_events
            WHERE target_type = 'durable_job' AND target_id = %s
              AND event_type IN ('durable_job.claimed', 'durable_job.reclaimed')
            ORDER BY created_at, event_type
            """,
            (str(job_id),),
        )
        fingerprints = [str(row[0]) for row in cursor.fetchall() if row[0]]
    connection.commit()
    return fingerprints


def _knowledge_actor_kill(connection: Any, *, project: str, project_id: object) -> dict[str, Any]:
    job_id = uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO knowledge_import_jobs (
              id, project_id, source_mode, status, requested_by, source_config
            ) VALUES (%s, %s, 'pasted_text', 'queued', 'durable-verifier',
                      '{"text":"durable actor kill source"}'::jsonb)
            """,
            (job_id, project_id),
        )
    connection.commit()

    def first_claim() -> object:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT attempt_count, status, lease_token FROM knowledge_import_jobs WHERE id = %s",
                (job_id,),
            )
            row = cursor.fetchone()
        connection.commit()
        return row if row and row[0] == 1 and row[1] == "running" and row[2] else None

    first = _wait_for("Knowledge first claim", first_claim, timeout_seconds=30)
    first_token = str(first[2])
    _compose(project, "kill", "-s", "KILL", "task-worker-knowledge")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, lease_token FROM knowledge_import_jobs WHERE id = %s", (job_id,)
        )
        after_kill = cursor.fetchone()
    connection.commit()
    if after_kill[0] != "running" or str(after_kill[1]) != first_token:
        raise AssertionError("Knowledge actor kill did not preserve the active PostgreSQL row")
    _compose(project, "up", "-d", "--no-deps", "task-worker-knowledge", timeout=300)

    def reclaimed() -> object:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, attempt_count, lease_reclaimed_count, last_reclaimed_from
                FROM knowledge_import_jobs WHERE id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
        connection.commit()
        return row if row and row[1] >= 2 and row[2] >= 1 else None

    transferred = _wait_for("Knowledge expired lease reclaim", reclaimed, timeout_seconds=30)
    fingerprints = _wait_for(
        "Knowledge token rotation audit",
        lambda: (values if len(values := _audit_fingerprints(connection, job_id)) >= 2 else None),
        timeout_seconds=10,
    )
    if len(set(fingerprints)) < 2:
        raise AssertionError("Knowledge reclaim did not rotate token fingerprint")
    return {
        "job_id": str(job_id),
        "attempt_count": int(transferred[1]),
        "lease_reclaimed_count": int(transferred[2]),
        "previous_worker_recorded": bool(transferred[3]),
        "token_rotated": True,
    }


def _collection_actor_kill(connection: Any, *, project: str, project_id: object) -> dict[str, Any]:
    job_id = uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO collection_jobs (id, project_id, requested_by) VALUES (%s, %s, 'durable-verifier')",
            (job_id, project_id),
        )
    connection.commit()

    def first_claim() -> object:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT attempt_count, status, lease_token FROM collection_jobs WHERE id = %s",
                (job_id,),
            )
            row = cursor.fetchone()
        connection.commit()
        return row if row and row[0] == 1 and row[1] == "running" and row[2] else None

    first = _wait_for("Collection first claim", first_claim, timeout_seconds=30)
    first_token = str(first[2])
    _compose(project, "kill", "-s", "KILL", "task-worker-runtime")
    with connection.cursor() as cursor:
        cursor.execute("SELECT status, lease_token FROM collection_jobs WHERE id = %s", (job_id,))
        after_kill = cursor.fetchone()
    connection.commit()
    if after_kill[0] != "running" or str(after_kill[1]) != first_token:
        raise AssertionError("Collection actor kill did not preserve the active PostgreSQL row")
    _compose(project, "up", "-d", "--no-deps", "task-worker-runtime", timeout=300)

    def reclaimed() -> object:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, attempt_count, lease_reclaimed_count, last_reclaimed_from
                FROM collection_jobs WHERE id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
        connection.commit()
        return row if row and row[1] >= 2 and row[2] >= 1 else None

    transferred = _wait_for("Collection expired lease reclaim", reclaimed, timeout_seconds=30)
    fingerprints = _wait_for(
        "Collection token rotation audit",
        lambda: (values if len(values := _audit_fingerprints(connection, job_id)) >= 2 else None),
        timeout_seconds=10,
    )
    if len(set(fingerprints)) < 2:
        raise AssertionError("Collection reclaim did not rotate token fingerprint")
    def terminal() -> object:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM collection_jobs WHERE id = %s",
                (job_id,),
            )
            row = cursor.fetchone()
        connection.commit()
        return row if row and row[0] in {"succeeded", "partial_succeeded", "failed", "dead_letter"} else None

    terminal_row = _wait_for(
        "Collection reclaimed handler terminal state", terminal, timeout_seconds=25
    )
    return {
        "job_id": str(job_id),
        "terminal_status": str(terminal_row[0]),
        "attempt_count": int(transferred[1]),
        "lease_reclaimed_count": int(transferred[2]),
        "previous_worker_recorded": bool(transferred[3]),
        "token_rotated": True,
    }


def _collection_child_kill(connection: Any, *, project: str, project_id: object) -> dict[str, Any]:
    _compose(project, "stop", "task-recovery-dispatcher")
    _compose(project, "stop", "task-worker-runtime")
    job_id = uuid4()
    actor_container = ""
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO collection_jobs (
                  id, project_id, requested_by, status, attempt_count, next_attempt_at
                ) VALUES (%s, %s, 'durable-verifier', 'retry_wait', 1, now())
                """,
                (job_id, project_id),
            )
        connection.commit()
        actor_container = _compose(
            project,
            "run",
            "-d",
            "--no-deps",
            "task-worker-runtime",
            "python",
            "-c",
            "from workers.task_queue.tasks import process_collection_queue; process_collection_queue.fn()",
        ).stdout.strip().splitlines()[-1]

        def child_pid() -> str | None:
            try:
                completed = _run(
                    [
                        "docker",
                        "exec",
                        actor_container,
                        "python",
                        "-c",
                        (
                            "from pathlib import Path; "
                            "matches=[]; "
                            "[(matches.append(path.parent.name) if len(parts := path.read_bytes().split(b'\\0')) > 2 "
                            "and parts[1] == b'-c' and parts[2].startswith(b'import json,time; time.sleep') else None) "
                            "for path in Path('/proc').glob('[0-9]*/cmdline')]; "
                            "print(matches[0] if matches else '')"
                        ),
                    ],
                    timeout=15,
                )
            except subprocess.CalledProcessError:
                return None
            return completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else None

        pid = _wait_for("Collection test child process", child_pid, timeout_seconds=15)
        _run(
            ["docker", "exec", actor_container, "sh", "-c", f"kill -9 {int(pid)}"],
            timeout=15,
        )

        def retry_state() -> object:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status, attempt_count, last_error_code FROM collection_jobs WHERE id = %s",
                    (job_id,),
                )
                row = cursor.fetchone()
            connection.commit()
            return row if row and row[0] in {"retry_wait", "dead_letter"} else None

        row = _wait_for("Collection child failure persistence", retry_state, timeout_seconds=15)
        return {
            "job_id": str(job_id),
            "status": str(row[0]),
            "attempt_count": int(row[1]),
            "error_code": str(row[2]),
            "actor_survived": True,
        }
    finally:
        if actor_container:
            subprocess.run(
                ["docker", "rm", "-f", actor_container],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        _compose(
            project,
            "up",
            "-d",
            "--no-deps",
            "task-worker-runtime",
            "task-recovery-dispatcher",
            timeout=180,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify durable Knowledge/Collection fencing leases.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--compose-project", default="geo-durable-leases")
    parser.add_argument(
        "--artifact-path", default="tmp/durable-job-lease-recovery/latest.json"
    )
    parser.add_argument("--run-actor-kill-tests", action="store_true")
    args = parser.parse_args()

    import psycopg

    started_at = datetime.now(UTC)
    commit = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    worktree_dirty = bool(_run(["git", "status", "--porcelain"]).stdout.strip())
    inputs = {
        "git_commit": commit,
        "compose_project": args.compose_project,
        "actor_kill_tests": args.run_actor_kill_tests,
    }
    checks: list[dict[str, Any]] = []
    connection: Any | None = None
    tenant_id: object | None = None
    failure: BaseException | None = None
    try:
        connection = psycopg.connect(args.database_url)
        _record(checks, "schema_and_index_contract", lambda: _schema_check(connection))
        if args.run_actor_kill_tests:
            tenant_id, project_id = _seed_scope(connection)
            _record(
                checks,
                "knowledge_actor_kill_reclaim",
                lambda: _knowledge_actor_kill(
                    connection, project=args.compose_project, project_id=project_id
                ),
            )
            _record(
                checks,
                "collection_actor_kill_reclaim",
                lambda: _collection_actor_kill(
                    connection, project=args.compose_project, project_id=project_id
                ),
            )
            _record(
                checks,
                "collection_child_kill_is_retry",
                lambda: _collection_child_kill(
                    connection, project=args.compose_project, project_id=project_id
                ),
            )
    except BaseException as exc:
        failure = exc
    finally:
        cleanup_connection = connection
        if cleanup_connection is not None:
            try:
                cleanup_connection.rollback()
            except Exception:
                try:
                    cleanup_connection.close()
                except Exception:
                    pass
                cleanup_connection = None
        if tenant_id is not None:
            try:
                if cleanup_connection is None:
                    cleanup_connection = psycopg.connect(args.database_url)
                with cleanup_connection.cursor() as cursor:
                    cursor.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
                cleanup_connection.commit()
            except BaseException as cleanup_exc:
                try:
                    if cleanup_connection is not None:
                        cleanup_connection.rollback()
                except Exception:
                    pass
                checks.append(
                    {
                        "name": "seed_cleanup",
                        "status": "failed",
                        "error": f"{cleanup_exc.__class__.__name__}: {cleanup_exc}",
                    }
                )
                if failure is None:
                    failure = cleanup_exc
        if cleanup_connection is not None:
            try:
                cleanup_connection.close()
            except Exception:
                pass

    finished_at = datetime.now(UTC)
    evidence_level = (
        "production_evidence" if args.run_actor_kill_tests and failure is None else "configuration_only"
    )
    artifact: dict[str, Any] = {
        "run_id": str(uuid4()),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "git_commit": commit,
        "worktree_dirty": worktree_dirty,
        "environment": {
            "compose_project": args.compose_project,
            "actor_kill_tests": args.run_actor_kill_tests,
        },
        "input_hash": _stable_hash(inputs),
        "status": "failed" if failure else "passed" if args.run_actor_kill_tests else "configuration_only",
        "evidence_level": evidence_level,
        "required_live_checks": {
            "actor_kill_tests": bool(args.run_actor_kill_tests),
            "check_names": [
                "knowledge_actor_kill_reclaim",
                "collection_actor_kill_reclaim",
                "collection_child_kill_is_retry",
            ],
            "satisfied": bool(args.run_actor_kill_tests and failure is None),
        },
        "checks": checks,
    }
    artifact["output_hash"] = _stable_hash(artifact)
    artifact_path = ROOT / args.artifact_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True))
    if failure:
        raise failure
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
