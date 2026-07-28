from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
import pytest
from sqlalchemy.exc import DBAPIError

from tests.integration.placement_worker_support import seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_0098_real_postgres_roundtrip_restores_0097_contract() -> None:
    database_name = f"geo_synthetic_lineage_{uuid4().hex[:10]}"
    target_url = _database_url(ADMIN_URL, database_name)
    created_database = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url

        command.upgrade(migration, "0097_dify_snapshot_fencing")
        before = _schema_contract(target_url)
        legacy = _seed_legacy_dify_children(target_url)

        command.upgrade(migration, "0098_synthetic_dify_lineage")
        with psycopg.connect(target_url) as connection:
            columns = {
                str(row[0]): (str(row[1]), str(row[2]))
                for row in connection.execute(
                    """SELECT column_name, data_type, is_nullable
                       FROM information_schema.columns
                       WHERE table_schema = 'public'
                         AND table_name = 'synthetic_lab_model_call_children'
                         AND column_name IN (
                           'execution_backend', 'workflow_release_id',
                           'workflow_release_hash', 'backend_lineage_source'
                         )"""
                ).fetchall()
            }
            overloads = connection.execute(
                """SELECT pronargs
                   FROM pg_proc
                   WHERE pronamespace = 'public'::regnamespace
                     AND proname = 'geo_enqueue_synthetic_model_call_child'
                   ORDER BY pronargs"""
            ).fetchall()
            view_columns = {
                str(row[0])
                for row in connection.execute(
                    """SELECT column_name FROM information_schema.columns
                       WHERE table_schema = 'public'
                         AND table_name = 'synthetic_lab_model_call_child_status'"""
                ).fetchall()
            }
        assert columns == {
            "backend_lineage_source": ("text", "NO"),
            "execution_backend": ("text", "NO"),
            "workflow_release_id": ("uuid", "YES"),
            "workflow_release_hash": ("text", "YES"),
        }
        assert overloads == [(46,), (49,)]
        assert {
            "backend_lineage_source",
            "model_attempt_id",
            "gateway_call_log_id",
            "workflow_attempt_id",
            "published_snapshot_id",
            "published_snapshot_hash",
        } <= view_columns
        _assert_legacy_backfill(target_url, legacy)

        command.downgrade(migration, "0097_dify_snapshot_fencing")
        assert _schema_contract(target_url) == before
        _assert_legacy_0097_projection(target_url, legacy)
        command.upgrade(migration, "0098_synthetic_dify_lineage")
        _assert_legacy_backfill(target_url, legacy)

        # A real post-0098 Dify admission cannot be projected back into the
        # weaker 0097 contract. Replica mode simulates that already-governed row
        # without constructing an unrelated live parent execution.
        with psycopg.connect(target_url) as connection:
            connection.execute("SET LOCAL session_replication_role = replica")
            connection.execute(
                """UPDATE synthetic_lab_model_call_children
                   SET backend_lineage_source = 'runtime_admission'
                   WHERE project_id = %s AND child_job_id = %s""",
                (legacy["project_id"], legacy["verified_child_id"]),
            )
            connection.execute("SET LOCAL session_replication_role = origin")
        with pytest.raises(
            DBAPIError,
            match="cannot downgrade while post-0098 Synthetic child Dify lineage exists",
        ):
            command.downgrade(migration, "0097_dify_snapshot_fencing")
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )


def test_0098_rejects_nonterminal_legacy_attempt_outside_the_release_pin() -> None:
    database_name = f"geo_synthetic_lineage_active_{uuid4().hex[:10]}"
    target_url = _database_url(ADMIN_URL, database_name)
    created_database = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url
        command.upgrade(migration, "0097_dify_snapshot_fencing")
        legacy = _seed_legacy_dify_children(target_url)
        _make_child_nonterminal_with_mismatched_pin(target_url, legacy)

        with pytest.raises(
            DBAPIError,
            match=(
                "cannot migrate: a non-terminal Synthetic child lacks its exact "
                "pinned execution backend"
            ),
        ):
            command.upgrade(migration, "0098_synthetic_dify_lineage")
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )


def _schema_contract(database_url: str) -> tuple[object, ...]:
    with psycopg.connect(database_url) as connection:
        child_columns = tuple(
            connection.execute(
                """SELECT column_name, data_type, is_nullable, column_default
                   FROM information_schema.columns
                   WHERE table_schema = 'public'
                     AND table_name = 'synthetic_lab_model_call_children'
                   ORDER BY ordinal_position"""
            ).fetchall()
        )
        function_rows = tuple(
            connection.execute(
                """SELECT pg_get_function_identity_arguments(oid), pg_get_functiondef(oid)
                   FROM pg_proc
                   WHERE pronamespace = 'public'::regnamespace
                     AND proname = 'geo_enqueue_synthetic_model_call_child'
                   ORDER BY pronargs"""
            ).fetchall()
        )
        guard = connection.execute(
            """SELECT pg_get_functiondef(
                 'geo_assert_synthetic_model_call_child_job_change()'::regprocedure
               )"""
        ).fetchone()
        child_guard = connection.execute(
            """SELECT pg_get_functiondef(
                 'geo_assert_synthetic_model_call_child()'::regprocedure
               )"""
        ).fetchone()
        view = connection.execute(
            """SELECT pg_get_viewdef(
                 'synthetic_lab_model_call_child_status'::regclass, true
               )"""
        ).fetchone()
        comment = connection.execute(
            """SELECT obj_description(
                 'synthetic_lab_model_call_child_status'::regclass, 'pg_class'
               )"""
        ).fetchone()
    return child_columns, function_rows, guard, child_guard, view, comment


def _seed_legacy_dify_children(database_url: str) -> dict[str, object]:
    now = datetime.now(UTC).replace(microsecond=0)
    release_id, prompt_release_id, prompt_program_id = uuid4(), uuid4(), uuid4()
    secret_id, project_id = uuid4(), uuid4()
    verified_child_id, mismatch_child_id = uuid4(), uuid4()
    verified_attempt_id, mismatch_attempt_id = uuid4(), uuid4()
    with psycopg.connect(database_url) as connection:
        seeded = seed_project(connection, suffix=f"synthetic-lineage-{uuid4().hex[:8]}")
        project_id = seeded["project"]
        connection.execute("SET LOCAL session_replication_role = replica")
        connection.execute(
            """INSERT INTO dify_workflow_releases(
                   id, project_id, purpose, version, prompt_program_id,
                   prompt_release_id, prompt_release_hash, dify_app_id,
                   dify_workflow_id, dsl_hash, context_contract_version,
                   input_schema, input_schema_hash, output_schema,
                   output_schema_hash, configured_model, model_provider,
                   api_secret_reference_id, api_secret_purpose,
                   api_secret_version, release_hash, created_by, created_at
               ) VALUES (
                   %s, %s, 'synthetic_lab.generation', 1, %s, %s, %s,
                   'legacy-synthetic-app', 'legacy-synthetic-workflow', %s,
                   'geo-dify-context-v1', '{}'::jsonb, %s, '{}'::jsonb, %s,
                   'deepseek-chat', 'langgenius/deepseek/deepseek', %s,
                   'workflow_runtime.dify', 1, %s, %s, %s
               )""",
            (
                release_id,
                project_id,
                prompt_program_id,
                prompt_release_id,
                "1" * 64,
                "2" * 64,
                "3" * 64,
                "4" * 64,
                secret_id,
                "5" * 64,
                seeded["owner"],
                now,
            ),
        )
        for index, (child_id, attempt_id, configured_model) in enumerate(
            (
                (verified_child_id, verified_attempt_id, "deepseek-chat"),
                (mismatch_child_id, mismatch_attempt_id, "deepseek-v4-flash"),
            ),
            start=1,
        ):
            connection.execute(
                """INSERT INTO durable_jobs(
                       id, project_id, kind, status, input_hash, idempotency_key,
                       result_ref, created_at, updated_at, completed_at
                   ) VALUES (
                       %s, %s, 'synthetic.model.call', 'succeeded', %s, %s,
                       %s, %s, %s, %s
                   )""",
                (
                    child_id,
                    project_id,
                    str(index) * 64,
                    f"legacy-synthetic-child:{child_id}",
                    f"dify-workflow://attempt/{attempt_id}",
                    now,
                    now,
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO synthetic_lab_model_call_children(
                       project_id, child_job_id, parent_job_id, parent_job_kind,
                       parent_task_input_hash, parent_lease_token,
                       parent_fencing_generation, step_key, step_key_hash,
                       model_job_version, fact_snapshot_id, fact_snapshot_hash,
                       profile_version_id, profile_hash,
                       runtime_prompt_release_id, runtime_prompt_release_hash,
                       prompt_binding_id, prompt_binding_version,
                       prompt_frozen_state_id, prompt_state_version,
                       prompt_release_id, prompt_release_version,
                       prompt_release_hash, prompt_program_kind, prompt_purpose,
                       admitted_by, prompt_model_policy_hash, provider,
                       adapter_release_id, adapter_release_hash, model_release_id,
                       model_release_hash, configured_model, runtime_manifest_id,
                       runtime_manifest_hash, runtime_option_id,
                       runtime_option_hash, search_mode, prompt_bundle_hash,
                       structured_input_hash, portable_output_schema_hash,
                       application_output_schema_hash, task_artifact_uri,
                       task_artifact_hash, deterministic_seed, max_output_tokens,
                       child_input_hash, outbox_id, created_at
                   ) VALUES (
                       %s, %s, %s, 'review.case.run', %s, %s, 1,
                       %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, 1,
                       %s, 1, %s, 1, %s, 'generation',
                       'synthetic_lab.generation', %s, %s, 'deepseek',
                       'deepseek-adapter-v1', %s, 'deepseek-release-v1', %s,
                       %s, %s, %s, %s, %s, NULL, %s, %s, %s, %s,
                       's3://geo-test/legacy-task.json', %s, %s, 4096, %s, %s, %s
                   )""",
                (
                    project_id,
                    child_id,
                    uuid4(),
                    "6" * 64,
                    uuid4(),
                    f"generation-{index}",
                    "7" * 64,
                    uuid4(),
                    "8" * 64,
                    uuid4(),
                    "9" * 64,
                    prompt_release_id,
                    "1" * 64,
                    uuid4(),
                    uuid4(),
                    prompt_release_id,
                    "1" * 64,
                    seeded["owner"],
                    "a" * 64,
                    "b" * 64,
                    "c" * 64,
                    configured_model,
                    uuid4(),
                    "d" * 64,
                    uuid4(),
                    "e" * 64,
                    "f" * 64,
                    "1" * 64,
                    "2" * 64,
                    "3" * 64,
                    "4" * 64,
                    index,
                    "5" * 64,
                    uuid4(),
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO dify_workflow_execution_attempts(
                       id, project_id, release_id, job_id, execution_kind,
                       attempt_number, fencing_generation, status, context_hash,
                       request_hash, dify_run_id, reported_workflow_id,
                       output_hash, retryable, started_at, finished_at
                   ) VALUES (
                       %s, %s, %s, %s, 'business', 1, 1, 'succeeded',
                       %s, %s, %s, 'legacy-synthetic-workflow', %s, false, %s, %s
                   )""",
                (
                    attempt_id,
                    project_id,
                    release_id,
                    child_id,
                    "6" * 64,
                    "7" * 64,
                    f"legacy-run-{index}",
                    "8" * 64,
                    now,
                    now,
                ),
            )
        connection.execute("SET LOCAL session_replication_role = origin")
    return {
        "project_id": project_id,
        "owner_id": seeded["owner"],
        "release_id": release_id,
        "release_hash": "5" * 64,
        "verified_child_id": verified_child_id,
        "verified_attempt_id": verified_attempt_id,
        "mismatch_child_id": mismatch_child_id,
        "mismatch_attempt_id": mismatch_attempt_id,
    }


def _assert_legacy_backfill(
    database_url: str, legacy: dict[str, object]
) -> None:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """SELECT child.child_job_id, child.execution_backend,
                      child.backend_lineage_source, child.workflow_release_id,
                      status.workflow_attempt_id, status.dify_release_id
               FROM synthetic_lab_model_call_children child
               JOIN synthetic_lab_model_call_child_status status
                 ON status.project_id = child.project_id
                AND status.child_job_id = child.child_job_id
               WHERE child.project_id = %s
                 AND child.child_job_id IN (%s, %s)
               ORDER BY child.child_job_id""",
            (
                legacy["project_id"],
                legacy["verified_child_id"],
                legacy["mismatch_child_id"],
            ),
        ).fetchall()
        with pytest.raises(psycopg.Error, match="immutable"):
            connection.execute(
                """UPDATE synthetic_lab_model_call_children
                   SET backend_lineage_source = 'runtime_admission'
                   WHERE project_id = %s AND child_job_id = %s""",
                (legacy["project_id"], legacy["mismatch_child_id"]),
            )
        connection.rollback()
    actual = {
        row[0]: (row[1], row[2], row[3], row[4], row[5]) for row in rows
    }
    assert actual[legacy["verified_child_id"]] == (
        "dify",
        "migration_backfill_verified",
        legacy["release_id"],
        legacy["verified_attempt_id"],
        legacy["release_id"],
    )
    assert actual[legacy["mismatch_child_id"]] == (
        "dify",
        "migration_backfill_historical_mismatch",
        legacy["release_id"],
        legacy["mismatch_attempt_id"],
        legacy["release_id"],
    )


def _assert_legacy_0097_projection(
    database_url: str, legacy: dict[str, object]
) -> None:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """SELECT child_job_id, execution_backend, model_attempt_id,
                      dify_release_id
               FROM synthetic_lab_model_call_child_status
               WHERE project_id = %s AND child_job_id IN (%s, %s)""",
            (
                legacy["project_id"],
                legacy["verified_child_id"],
                legacy["mismatch_child_id"],
            ),
        ).fetchall()
    actual = {row[0]: (row[1], row[2], row[3]) for row in rows}
    assert actual[legacy["verified_child_id"]] == (
        "dify",
        legacy["verified_attempt_id"],
        legacy["release_id"],
    )
    assert actual[legacy["mismatch_child_id"]] == (
        "dify",
        legacy["mismatch_attempt_id"],
        legacy["release_id"],
    )


def _make_child_nonterminal_with_mismatched_pin(
    database_url: str, legacy: dict[str, object]
) -> None:
    pinned_snapshot_id, attempt_snapshot_id = uuid4(), uuid4()
    canary_attempt_id = uuid4()
    now = datetime.now(UTC).replace(microsecond=0)
    with psycopg.connect(database_url) as connection:
        connection.execute("SET LOCAL session_replication_role = replica")
        connection.execute(
            """INSERT INTO dify_workflow_published_snapshots(
                   id, project_id, release_id, purpose, dify_app_id,
                   dify_workflow_id, workflow_hash, snapshot_hash,
                   prompt_nodes, input_variables, graph_nodes,
                   published_at, observed_at
               ) VALUES
                   (%s, %s, %s, 'synthetic_lab.generation',
                    'legacy-synthetic-app', 'legacy-synthetic-workflow-pinned',
                    %s, %s, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, %s, %s),
                   (%s, %s, %s, 'synthetic_lab.generation',
                    'legacy-synthetic-app', 'legacy-synthetic-workflow-later',
                    %s, %s, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, %s, %s)""",
            (
                pinned_snapshot_id,
                legacy["project_id"],
                legacy["release_id"],
                "9" * 64,
                "a" * 64,
                now,
                now,
                attempt_snapshot_id,
                legacy["project_id"],
                legacy["release_id"],
                "b" * 64,
                "c" * 64,
                now,
                now,
            ),
        )
        connection.execute(
            """INSERT INTO dify_workflow_execution_attempts(
                   id, project_id, release_id, execution_kind,
                   attempt_number, status, context_hash, request_hash,
                   dify_run_id, reported_workflow_id, output_hash, retryable,
                   published_snapshot_id, started_at, finished_at
               ) VALUES (
                   %s, %s, %s, 'canary', 1, 'succeeded', %s, %s,
                   'legacy-canary-run', 'legacy-synthetic-workflow-pinned',
                   %s, false, %s, %s, %s
               )""",
            (
                canary_attempt_id,
                legacy["project_id"],
                legacy["release_id"],
                "d" * 64,
                "e" * 64,
                "f" * 64,
                pinned_snapshot_id,
                now,
                now,
            ),
        )
        connection.execute(
            """INSERT INTO dify_workflow_release_snapshot_pins(
                   project_id, release_id, published_snapshot_id,
                   dify_workflow_id, workflow_hash, snapshot_hash,
                   canary_attempt_id, pin_source, pinned_at
               ) VALUES (
                   %s, %s, %s, 'legacy-synthetic-workflow-pinned',
                   %s, %s, %s, 'migration_backfill', %s
               )""",
            (
                legacy["project_id"],
                legacy["release_id"],
                pinned_snapshot_id,
                "9" * 64,
                "a" * 64,
                canary_attempt_id,
                now,
            ),
        )
        connection.execute(
            """INSERT INTO dify_workflow_bindings(
                   id, project_id, purpose, release_id, release_hash,
                   binding_version, activated_by, activated_at, reason
               ) VALUES (
                   %s, %s, 'synthetic_lab.generation', %s, %s, 1,
                   %s, %s, 'legacy active release'
               )""",
            (
                uuid4(),
                legacy["project_id"],
                legacy["release_id"],
                legacy["release_hash"],
                legacy["owner_id"],
                now,
            ),
        )
        connection.execute(
            """UPDATE durable_jobs
               SET status = 'queued', result_ref = NULL, completed_at = NULL
               WHERE project_id = %s AND id = %s""",
            (legacy["project_id"], legacy["verified_child_id"]),
        )
        connection.execute(
            """UPDATE dify_workflow_execution_attempts
               SET status = 'running', dify_run_id = NULL,
                   reported_workflow_id = NULL, output_hash = NULL,
                   retryable = NULL, finished_at = NULL,
                   published_snapshot_id = %s
               WHERE project_id = %s AND id = %s""",
            (
                attempt_snapshot_id,
                legacy["project_id"],
                legacy["verified_attempt_id"],
            ),
        )
        connection.execute("SET LOCAL session_replication_role = origin")


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
