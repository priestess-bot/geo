"""Real PostgreSQL scenarios for the migration-frozen Recommendation V3 exception."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geo_core.workflow_runtime.contracts import canonical_json_hash


def assert_legacy_lineage(
    database_url: str,
    project_id,
    child_job_id,
    *,
    status: str = "queued",
) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        row = connection.execute(
            """SELECT task.execution_backend AS task_backend,
                      task.workflow_release_id, task.workflow_release_hash,
                      lineage.execution_backend AS lineage_backend,
                      lineage.dify_attempt_id, lineage.status
               FROM recommendation_model_tasks AS task
               JOIN recommendation_model_call_lineage AS lineage
                 ON lineage.project_id = task.project_id
                AND lineage.child_job_id = task.child_job_id
               WHERE task.project_id = %s AND task.child_job_id = %s""",
            (project_id, child_job_id),
        ).fetchone()
    assert row == {
        "task_backend": "model_gateway",
        "workflow_release_id": None,
        "workflow_release_hash": None,
        "lineage_backend": "model_gateway",
        "dify_attempt_id": None,
        "status": status,
    }


def seed_pre_upgrade_v3_parent(
    connection,
    *,
    project_id: UUID,
    owner_id: UUID,
    now: datetime,
) -> UUID:
    parent_job_id = uuid4()
    payload = {
        "contract_version": "recommendation-generation-spec-v3",
        "project_id": str(project_id),
        "legacy_request": "frozen-before-0097",
        "valid_until": (now + timedelta(days=7)).isoformat(),
        "created_by": str(owner_id),
    }
    connection.execute(
        """INSERT INTO durable_jobs(
               id, project_id, kind, status, input_hash, idempotency_key,
               max_attempts, created_at, updated_at
           ) VALUES (%s, %s, 'recommendation.generate', 'queued', %s, %s, 3, %s, %s)""",
        (
            parent_job_id,
            project_id,
            "a" * 64,
            f"legacy-v3-parent:{parent_job_id}",
            now,
            now,
        ),
    )
    connection.execute(
        """INSERT INTO recommendation_generation_specs(
               project_id, job_id, api_version, spec_payload, spec_payload_hash,
               input_hash, idempotency_key_hash, valid_until, created_by, created_at
           ) VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s, %s)""",
        (
            project_id,
            parent_job_id,
            Jsonb(payload),
            canonical_json_hash(payload),
            "a" * 64,
            canonical_json_hash({"legacy-v3-parent": str(parent_job_id)}),
            now + timedelta(days=7),
            owner_id,
            now,
        ),
    )
    return parent_job_id


def assert_pre_upgrade_v3_native_only(
    database_url: str,
    *,
    seeded,
    prompt_binding_id,
    prompt,
    runtime,
    legacy_parent_id: UUID,
    now: datetime,
) -> None:
    # Import after the migration test module has initialized to avoid a test-support cycle.
    from tests.integration.test_style_recommendation_dify_migration_postgres import (
        _insert_recommendation_task_row,
    )

    with psycopg.connect(database_url, row_factory=dict_row) as admin:
        marker = admin.execute(
            """SELECT captured_contract_version
               FROM dify_legacy_recommendation_native_parents
               WHERE project_id = %s AND parent_job_id = %s""",
            (seeded["project"], legacy_parent_id),
        ).fetchone()
        assert marker == {"captured_contract_version": "recommendation-generation-spec-v3"}
        legacy_child_id = _seed_child(
            admin,
            project_id=seeded["project"],
            parent_job_id=legacy_parent_id,
            now=now,
        )
        _insert_recommendation_task_row(
            admin,
            seeded=seeded,
            prompt_binding_id=prompt_binding_id,
            prompt=prompt,
            runtime=runtime,
            parent_job_id=legacy_parent_id,
            child_job_id=legacy_child_id,
            execution_backend="model_gateway",
            workflow_release_id=None,
            workflow_release_hash=None,
            now=now,
        )

    with psycopg.connect(database_url, row_factory=dict_row) as admin:
        forged_parent_id = seed_pre_upgrade_v3_parent(
            admin,
            project_id=seeded["project"],
            owner_id=seeded["owner"],
            now=now + timedelta(seconds=1),
        )
        forged_child_id = _seed_child(
            admin,
            project_id=seeded["project"],
            parent_job_id=forged_parent_id,
            now=now + timedelta(seconds=1),
        )
        assert (
            admin.execute(
                """SELECT 1 FROM dify_legacy_recommendation_native_parents
               WHERE project_id = %s AND parent_job_id = %s""",
                (seeded["project"], forged_parent_id),
            ).fetchone()
            is None
        )
        try:
            _insert_recommendation_task_row(
                admin,
                seeded=seeded,
                prompt_binding_id=prompt_binding_id,
                prompt=prompt,
                runtime=runtime,
                parent_job_id=forged_parent_id,
                child_job_id=forged_child_id,
                execution_backend="model_gateway",
                workflow_release_id=None,
                workflow_release_hash=None,
                now=now + timedelta(seconds=1),
            )
        except psycopg.errors.SerializationFailure as error:
            assert "bound to Dify" in str(error)
            admin.rollback()
        else:
            raise AssertionError("post-upgrade forged V3 parent bypassed the active Dify binding")


def _seed_child(
    connection,
    *,
    project_id: UUID,
    parent_job_id: UUID,
    now: datetime,
) -> UUID:
    child_job_id = uuid4()
    connection.execute(
        """INSERT INTO durable_jobs(
               id, project_id, kind, status, input_hash, idempotency_key,
               parent_job_id, max_attempts, created_at, updated_at
           ) VALUES (%s, %s, 'recommendation.model_call', 'queued', %s, %s,
                     %s, 3, %s, %s)""",
        (
            child_job_id,
            project_id,
            "b" * 64,
            f"legacy-v3-child:{child_job_id}",
            parent_job_id,
            now,
            now,
        ),
    )
    return child_job_id
