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
from tests.integration.placement_worker_support import login_url, seed_project
from tests.integration.test_workflow_c_metric_parent_admission_postgres import (
    _child_payload,
    _finalize_payload,
    _seed_parent_lineage,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_metric_arbiter_admission_requires_complete_disagreeing_judge_projections() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_metric_arbiter_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    worker_login, password = f"geo_metric_arbiter_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        command.upgrade(migration, "head")
        command.downgrade(migration, "0066_metric_parent_admission")
        command.upgrade(migration, "head")

        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(password)
                )
            )
            created_role = True
            project = seed_project(admin, suffix=f"metric-arbiter-{suffix}")
            parent = _seed_parent_lineage(admin, project=project, now=now)
            admin.commit()

        worker_url = login_url(database_url, user=worker_login, password=password)
        batch_id = uuid4()
        first_child, second_child = uuid4(), uuid4()
        judge_payload = _finalize_payload(
            [
                {
                    "id": str(batch_id),
                    "run_id": str(parent["run_id"]),
                    "observation_id": str(parent["observation_id"]),
                    "ordinal": 1,
                    "planned_batch_count": 1,
                    "plans_hash": _hash("plans"),
                    "input_set_hash": _hash("input-set"),
                    "metric_suite_hash": _hash("metric-suite"),
                    "children": [
                        _child_payload(
                            child_id=first_child,
                            candidate_id=uuid4(),
                            ordinal=1,
                            evaluator_id="judge-a",
                            parent=parent,
                        ),
                        _child_payload(
                            child_id=second_child,
                            candidate_id=uuid4(),
                            ordinal=2,
                            evaluator_id="judge-b",
                            parent=parent,
                        ),
                    ],
                }
            ]
        )
        with psycopg.connect(worker_url) as worker:
            set_project_scope(worker, project["project"])
            worker.execute(
                """SELECT * FROM geo_admit_workflow_c_metric_judge_batches(
                       %s, %s, %s, 1, %s, %s::jsonb
                   )""",
                (
                    project["project"],
                    parent["job_id"],
                    parent["lease_token"],
                    parent["input_hash"],
                    Jsonb(judge_payload),
                ),
            )
            worker.commit()

        first_projection = {"candidate": "one"}
        second_projection = {"candidate": "two"}
        first_output_hash, second_output_hash = (
            _json_hash(first_projection),
            _json_hash(second_projection),
        )
        with psycopg.connect(database_url) as admin:
            admin.execute("SET session_replication_role = replica")
            try:
                admin.execute(
                    """UPDATE workflow_c_metric_model_children
                           SET status = 'succeeded', model_attempt_id = %s,
                               output_hash = %s, completed_at = %s
                         WHERE project_id = %s AND child_job_id = %s""",
                    (uuid4(), first_output_hash, now, project["project"], first_child),
                )
                admin.execute(
                    """UPDATE workflow_c_metric_model_children
                           SET status = 'succeeded', model_attempt_id = %s,
                               output_hash = %s, completed_at = %s
                         WHERE project_id = %s AND child_job_id = %s""",
                    (uuid4(), second_output_hash, now, project["project"], second_child),
                )
                admin.execute(
                    """UPDATE workflow_c_metric_judge_batches
                           SET status = 'running', aggregate_version = aggregate_version + 1
                         WHERE project_id = %s AND id = %s""",
                    (project["project"], batch_id),
                )
            finally:
                admin.execute("SET session_replication_role = origin")
            admin.execute(
                """INSERT INTO workflow_c_metric_child_output_projections(
                       project_id, child_job_id, output_hash, output_projection, recorded_at
                   ) VALUES (%s, %s, %s, %s::jsonb, %s)""",
                (project["project"], first_child, first_output_hash, Jsonb(first_projection), now),
            )
            admin.commit()

        arbiter_child = uuid4()
        arbiter_payload = _arbiter_payload(
            child_id=arbiter_child,
            candidate_id=uuid4(),
            parent=parent,
            batch_id=batch_id,
        )
        with psycopg.connect(worker_url, row_factory=dict_row) as worker:
            set_project_scope(worker, project["project"])
            with pytest.raises(
                psycopg.errors.SerializationFailure, match="Judge evidence is incomplete"
            ):
                worker.execute(
                    """SELECT geo_admit_workflow_c_metric_arbiter_child(
                           %s, %s, %s, 1, %s, %s, %s::jsonb
                       )""",
                    (
                        project["project"],
                        parent["job_id"],
                        parent["lease_token"],
                        parent["input_hash"],
                        batch_id,
                        Jsonb(arbiter_payload),
                    ),
                )
            worker.rollback()

        with psycopg.connect(database_url) as admin:
            admin.execute(
                """INSERT INTO workflow_c_metric_child_output_projections(
                       project_id, child_job_id, output_hash, output_projection, recorded_at
                   ) VALUES (%s, %s, %s, %s::jsonb, %s)""",
                (
                    project["project"],
                    second_child,
                    second_output_hash,
                    Jsonb(second_projection),
                    now,
                ),
            )
            admin.commit()

        with psycopg.connect(worker_url, row_factory=dict_row) as worker:
            set_project_scope(worker, project["project"])
            row = worker.execute(
                """SELECT geo_admit_workflow_c_metric_arbiter_child(
                       %s, %s, %s, 1, %s, %s, %s::jsonb
                   )""",
                (
                    project["project"],
                    parent["job_id"],
                    parent["lease_token"],
                    parent["input_hash"],
                    batch_id,
                    Jsonb(arbiter_payload),
                ),
            ).fetchone()
            assert row == {"geo_admit_workflow_c_metric_arbiter_child": arbiter_child}
            persisted = worker.execute(
                """SELECT batch.arbiter_child_job_id, child.role, child.task_hash,
                              job.kind, job.input_hash, spec.spec_hash, spec.spec_payload
                       FROM workflow_c_metric_judge_batches AS batch
                       JOIN workflow_c_metric_model_children AS child
                         ON child.project_id = batch.project_id
                        AND child.child_job_id = batch.arbiter_child_job_id
                       JOIN durable_jobs AS job
                         ON job.project_id = child.project_id AND job.id = child.child_job_id
                       JOIN workflow_c_job_specs AS spec
                         ON spec.project_id = child.project_id AND spec.job_id = child.child_job_id
                      WHERE batch.project_id = %s AND batch.id = %s""",
                (project["project"], batch_id),
            ).fetchone()
            assert persisted is not None
            assert persisted["arbiter_child_job_id"] == arbiter_child
            assert persisted["role"] == "arbiter"
            assert persisted["kind"] == "workflow_c.metric_arbiter"
            assert persisted["task_hash"] == persisted["input_hash"] != persisted["spec_hash"]
            public_spec = persisted["spec_payload"]
            assert set(public_spec) == {"schema_version", "kind", "metric_model_child"}
            assert public_spec["metric_model_child"]["role"] == "arbiter"
            assert (
                worker.execute(
                    """SELECT count(*) FROM broker_outbox
                      WHERE project_id = %s AND job_id = %s
                        AND topic = 'workflow_c.metric_arbiter'""",
                    (project["project"], arbiter_child),
                ).fetchone()["count"]
                == 1
            )
            worker.commit()
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                worker.execute("UPDATE workflow_c_metric_model_children SET status = 'failed'")
            worker.rollback()

            set_project_scope(worker, project["project"])
            with pytest.raises(
                psycopg.errors.SerializationFailure, match="batch is not admissible"
            ):
                worker.execute(
                    """SELECT geo_admit_workflow_c_metric_arbiter_child(
                           %s, %s, %s, 1, %s, %s, %s::jsonb
                       )""",
                    (
                        project["project"],
                        parent["job_id"],
                        parent["lease_token"],
                        parent["input_hash"],
                        batch_id,
                        Jsonb(arbiter_payload),
                    ),
                )
            worker.rollback()
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        if created_role:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login))
                )


def _arbiter_payload(
    *, child_id: UUID, candidate_id: UUID, parent: dict[str, UUID | str], batch_id: UUID
) -> dict[str, object]:
    payload = _child_payload(
        child_id=child_id,
        candidate_id=candidate_id,
        ordinal=1,
        evaluator_id="arbiter-a",
        parent=parent,
    )
    task_hash = _hash(f"arbiter-task:{child_id}")
    spec = payload["spec_payload"]
    assert isinstance(spec, dict)
    reference = spec["metric_model_child"]
    assert isinstance(reference, dict)
    spec["kind"] = "workflow_c.metric_arbiter"
    reference["batch_id"] = str(batch_id)
    reference["role"] = "arbiter"
    reference["task_hash"] = task_hash
    payload["task_hash"] = task_hash
    payload["spec_hash"] = _json_hash(spec)
    return payload


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
