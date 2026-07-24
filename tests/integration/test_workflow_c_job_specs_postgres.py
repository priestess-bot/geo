from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from geo_core.project_scope import set_project_scope
from geo_core.workflow_c_job_specs import (
    PostgresWorkflowCJobSpecWriter,
    WORKFLOW_C_JOB_KINDS,
    WorkflowCJobSpecError,
)
from tests.integration.placement_worker_support import cleanup_projects, login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_workflow_c_producer_commits_all_supported_job_specs_under_app_rls() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_workflow_c_specs_{suffix}"
    target_url = _database_url(ADMIN_URL, database_name)
    app_login, password = f"geo_workflow_c_specs_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    first: dict[str, UUID] | None = None
    second: dict[str, UUID] | None = None
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url
        command.upgrade(migration, "head")
        with psycopg.connect(target_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(password)
                )
            )
            created_role = True
            first = seed_project(admin, suffix=f"workflow-c-specs-{suffix}-a")
            second = seed_project(admin, suffix=f"workflow-c-specs-{suffix}-b")
        app_url = login_url(target_url, user=app_login, password=password)
        writer = PostgresWorkflowCJobSpecWriter(
            lambda: psycopg.connect(app_url, row_factory=dict_row)
        )

        payloads = {
            kind: _payload(kind, index=index)
            for index, kind in enumerate(sorted(WORKFLOW_C_JOB_KINDS), start=1)
        }
        idempotency_keys = {
            kind: f"workflow-c-spec:{index}"
            for index, kind in enumerate(sorted(WORKFLOW_C_JOB_KINDS), start=1)
        }
        jobs = {
            kind: writer.enqueue(
                project_id=first["project"],
                kind=kind,
                payload=payloads[kind],
                idempotency_key=idempotency_keys[kind],
            )
            for kind in sorted(WORKFLOW_C_JOB_KINDS)
        }
        replay = writer.enqueue(
            project_id=first["project"],
            kind="workflow_c.alert.notify",
            payload=payloads["workflow_c.alert.notify"],
            idempotency_key=idempotency_keys["workflow_c.alert.notify"],
        )
        assert replay.replayed is True
        assert replay.job_id == jobs["workflow_c.alert.notify"].job_id

        with psycopg.connect(target_url, row_factory=dict_row) as admin:
            rows = admin.execute(
                """SELECT job.kind, job.input_hash, spec.spec_hash,
                          spec.spec_payload, outbox.topic, outbox.payload
                   FROM durable_jobs AS job
                   JOIN workflow_c_job_specs AS spec
                     ON spec.project_id = job.project_id AND spec.job_id = job.id
                   JOIN broker_outbox AS outbox
                     ON outbox.project_id = job.project_id AND outbox.job_id = job.id
                  WHERE job.project_id = %s
                  ORDER BY job.kind""",
                (first["project"],),
            ).fetchall()
            event_count = admin.execute(
                """SELECT count(*) AS count FROM durable_job_events
                   WHERE project_id = %s AND event_type = 'job_enqueued'
                     AND worker_id = 'workflow-c-producer'""",
                (first["project"],),
            ).fetchone()["count"]
        assert len(rows) == len(WORKFLOW_C_JOB_KINDS)
        assert event_count == len(WORKFLOW_C_JOB_KINDS)
        for row in rows:
            assert row["input_hash"] == row["spec_hash"]
            assert row["spec_payload"]["kind"] == row["kind"]
            assert row["spec_payload"]["schema_version"] == 1
            assert row["payload"] == {
                "job_id": str(jobs[row["kind"]].job_id),
                "project_id": str(first["project"]),
            }
            assert row["topic"] == row["kind"]

        with pytest.raises(WorkflowCJobSpecError, match="secret or credential"):
            writer.enqueue(
                project_id=first["project"],
                kind="workflow_c.alert.notify",
                payload={
                    "schema_version": 1,
                    "kind": "workflow_c.alert.notify",
                    "token": "must-not-reach-postgres",
                },
                idempotency_key="workflow-c-spec:sensitive",
            )
        unsafe_payload = {
            **_payload("workflow_c.alert.notify", index=99),
            "nested": {"api-key": "must-not-reach-postgres"},
        }
        with psycopg.connect(app_url) as app_connection:
            set_project_scope(app_connection, first["project"])
            with pytest.raises(psycopg.errors.InvalidParameterValue, match="enqueue input is invalid"):
                app_connection.execute(
                    """SELECT * FROM geo_enqueue_workflow_c_job_spec(
                           %s, %s, %s, %s::jsonb, %s, %s
                       )""",
                    (
                        first["project"],
                        "workflow_c.alert.notify",
                        _payload_hash(unsafe_payload),
                        Jsonb(unsafe_payload),
                        "workflow-c-spec:direct-unsafe",
                        3,
                    ),
                )
            app_connection.rollback()
        with psycopg.connect(app_url) as app_connection:
            set_project_scope(app_connection, second["project"])
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                app_connection.execute("SELECT count(*) FROM workflow_c_job_specs")
            app_connection.rollback()
            set_project_scope(app_connection, first["project"])
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                app_connection.execute(
                    """INSERT INTO workflow_c_job_specs(
                           project_id, job_id, kind, spec_hash, spec_payload, created_at
                       ) VALUES (%s, %s, %s, %s, %s::jsonb, clock_timestamp())""",
                    (
                        first["project"],
                        jobs["workflow_c.alert.notify"].job_id,
                        "workflow_c.alert.notify",
                        jobs["workflow_c.alert.notify"].spec_hash,
                        json.dumps(payloads["workflow_c.alert.notify"]),
                    ),
                )
            app_connection.rollback()
    finally:
        if first is not None and second is not None:
            with psycopg.connect(target_url) as admin:
                cleanup_projects(
                    admin,
                    projects=[first, second],
                    tenant_ids=[first["tenant"], second["tenant"]],
                    app_login=app_login,
                )
            created_role = False
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        if created_role:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))


def _payload(kind: str, *, index: int) -> dict[str, object]:
    if kind == "sampling.provider_execute":
        question = f"Which Australian plan is best? {index}"
        return {
            "schema_version": 1,
            "kind": kind,
            "run_id": str(uuid4()),
            "task_id": str(uuid4()),
            "attempt_id": str(uuid4()),
            "task_version": 1,
            "attempt_version": 1,
            "question": {"text": question, "sha256": _hash(question)},
            "runtime_selection_id": str(uuid4()),
            "admitted_by": str(uuid4()),
            "admitted_at": datetime.now(UTC).isoformat(),
            "prompt": {
                "binding_id": str(uuid4()),
                "state_id": str(uuid4()),
                "state_version": 1,
                "release_id": str(uuid4()),
                "release_hash": "a" * 64,
                "purpose": "workflow_c.sampling",
                "bundle_hash": "b" * 64,
                "system_message": "Return structured output.",
                "answer_field": "answer",
                "output_schema": {"type": "object"},
                "application_output_schema": {"type": "object"},
                "temperature": 0.0,
                "max_output_tokens": 100,
                "seed": None,
                "tool_mode": None,
            },
            "search_mode": None,
            "deadline_at": None,
        }
    if kind == "sampling.manual_import":
        return {
            "schema_version": 1,
            "kind": kind,
            "manual_import_id": str(uuid4()),
            "run_id": str(uuid4()),
            "task_id": str(uuid4()),
            "attempt_id": str(uuid4()),
            "artifact_manifest_id": str(uuid4()),
            "artifact_manifest_hash": "c" * 64,
            "artifact_content_hash": "d" * 64,
            "governance_policy_hash": "e" * 64,
            "capture_session_id": str(uuid4()),
            "task_version": 1,
            "attempt_version": 1,
        }
    return {
        "schema_version": 1,
        "kind": kind,
        "producer_marker": f"Australian caf\u00e9 fixture-{index}",
    }


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _payload_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
