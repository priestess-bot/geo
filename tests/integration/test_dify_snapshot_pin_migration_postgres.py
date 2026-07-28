from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from geo_core.secrets import SecretVersionHandle
from geo_core.workflow_runtime import PostgresWorkflowRuntimeCatalog
from geo_core.workflow_runtime.contracts import canonical_json_hash
from tests.integration.dify_release_migration_support import seed_legacy_dify_release
from tests.integration.placement_worker_support import login_url, seed_project
from tests.integration.test_dify_workflow_runtime_postgres import (
    _seed_frozen_prompt_and_secret,
)
from tests.integration.test_style_recommendation_dify_migration_postgres import _database_url


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_legacy_ambiguous_release_backfills_latest_pin_without_rewriting_results() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_dify_pin_migration_{suffix}"
    target_url = _database_url(ADMIN_URL, database_name)
    app_login, password = f"geo_dify_pin_{suffix}", uuid4().hex
    role_created = False
    database_created = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        database_created = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url
        command.upgrade(migration, "0096_style_recommendation_dify")

        now = datetime.now(UTC).replace(microsecond=0)
        with psycopg.connect(target_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(password)
                )
            )
            role_created = True
            seeded = seed_project(admin, suffix=f"dify-pin-migration-{suffix}")
            prompt, secret_id = _seed_frozen_prompt_and_secret(admin, seeded)
            admin.commit()

        app_url = login_url(target_url, user=app_login, password=password)
        catalog = PostgresWorkflowRuntimeCatalog(app_url)
        release_id = seed_legacy_dify_release(
            target_url,
            project_id=seeded["project"],
            purpose="knowledge.question_generation",
            prompt_program_id=prompt["program"],
            prompt_release_id=prompt["release"],
            dify_app_id="legacy-app",
            dify_workflow_id="legacy-workflow",
            dsl_hash="a" * 64,
            configured_model="deepseek-chat",
            model_provider="langgenius/deepseek/deepseek",
            api_secret_handle=SecretVersionHandle(
                reference_id=secret_id,
                project_id=seeded["project"],
                purpose="workflow_runtime.dify",
                version=1,
            ),
            created_by=seeded["owner"],
        )
        first_snapshot_id, second_snapshot_id = uuid4(), uuid4()
        first_canary_id, second_canary_id = uuid4(), uuid4()
        business_job_id, business_attempt_id = uuid4(), uuid4()
        old_output = {"questions": [{"text": "Which legacy result was preserved?"}]}
        old_output_hash = canonical_json_hash(old_output)
        prompt_nodes = Jsonb(
            [
                {
                    "model_provider": "langgenius/deepseek/deepseek",
                    "model_name": "deepseek-chat",
                }
            ]
        )
        with psycopg.connect(target_url) as admin:
            admin.execute(
                """INSERT INTO dify_workflow_published_snapshots(
                       id, project_id, release_id, purpose, dify_app_id,
                       dify_workflow_id, workflow_hash, snapshot_hash,
                       prompt_nodes, input_variables, graph_nodes,
                       published_at, observed_at
                   ) VALUES
                       (%s, %s, %s, 'knowledge.question_generation', 'legacy-app',
                        'legacy-workflow-v1', %s, %s, %s, '[]'::jsonb, '[]'::jsonb,
                        %s, %s),
                       (%s, %s, %s, 'knowledge.question_generation', 'legacy-app',
                        'legacy-workflow-v2', %s, %s, %s, '[]'::jsonb, '[]'::jsonb,
                        %s, %s)""",
                (
                    first_snapshot_id,
                    seeded["project"],
                    release_id,
                    "b" * 64,
                    "c" * 64,
                    prompt_nodes,
                    now,
                    now,
                    second_snapshot_id,
                    seeded["project"],
                    release_id,
                    "d" * 64,
                    "e" * 64,
                    prompt_nodes,
                    now + timedelta(seconds=1),
                    now + timedelta(seconds=1),
                ),
            )
            admin.execute(
                """INSERT INTO dify_workflow_execution_attempts(
                       id, project_id, release_id, execution_kind, attempt_number,
                       status, context_hash, request_hash, dify_run_id,
                       reported_workflow_id, output_hash, retryable,
                       published_snapshot_id, started_at, finished_at
                   ) VALUES
                       (%s, %s, %s, 'canary', 1, 'succeeded', %s, %s,
                        'legacy-canary-v1', 'legacy-workflow-v1', %s, false,
                        %s, %s, %s),
                       (%s, %s, %s, 'canary', 2, 'succeeded', %s, %s,
                        'legacy-canary-v2', 'legacy-workflow-v2', %s, false,
                        %s, %s, %s)""",
                (
                    first_canary_id,
                    seeded["project"],
                    release_id,
                    "1" * 64,
                    "2" * 64,
                    "3" * 64,
                    first_snapshot_id,
                    now,
                    now,
                    second_canary_id,
                    seeded["project"],
                    release_id,
                    "4" * 64,
                    "5" * 64,
                    "6" * 64,
                    second_snapshot_id,
                    now + timedelta(seconds=1),
                    now + timedelta(seconds=1),
                ),
            )
            admin.execute(
                """INSERT INTO durable_jobs(
                       id, project_id, kind, status, input_hash, idempotency_key,
                       created_at, updated_at, completed_at
                   ) VALUES (%s, %s, 'legacy.dify.completed', 'succeeded', %s, %s,
                             %s, %s, %s)""",
                (
                    business_job_id,
                    seeded["project"],
                    "7" * 64,
                    f"legacy-dify-business:{business_job_id}",
                    now,
                    now,
                    now,
                ),
            )
            admin.execute(
                """INSERT INTO dify_workflow_execution_attempts(
                       id, project_id, release_id, job_id, execution_kind,
                       attempt_number, fencing_generation, status, context_hash,
                       request_hash, published_snapshot_id, started_at
                   ) VALUES (%s, %s, %s, %s, 'business', 1, 1, 'running',
                             %s, %s, %s, %s)""",
                (
                    business_attempt_id,
                    seeded["project"],
                    release_id,
                    business_job_id,
                    "8" * 64,
                    "9" * 64,
                    first_snapshot_id,
                    now,
                ),
            )
            admin.execute(
                """INSERT INTO dify_workflow_execution_results(
                       attempt_id, project_id, job_id, output, response_hash,
                       configured_model
                   ) VALUES (%s, %s, %s, %s, %s, 'deepseek-chat')""",
                (
                    business_attempt_id,
                    seeded["project"],
                    business_job_id,
                    Jsonb(old_output),
                    old_output_hash,
                ),
            )
            admin.execute(
                """UPDATE dify_workflow_execution_attempts
                   SET status = 'succeeded', dify_run_id = 'legacy-business-v1',
                       reported_workflow_id = 'legacy-workflow-v1',
                       output_hash = %s, retryable = false, finished_at = %s
                   WHERE id = %s""",
                (old_output_hash, now, business_attempt_id),
            )

        binding_id = catalog.activate_release(
            project_id=seeded["project"],
            release_id=release_id,
            activated_by=seeded["owner"],
            reason="legacy release before immutable snapshot pins",
        )

        command.upgrade(migration, "0097_dify_snapshot_fencing")
        _assert_legacy_pin_state(
            target_url,
            project_id=seeded["project"],
            release_id=release_id,
            binding_id=binding_id,
            expected_snapshot_id=second_snapshot_id,
            expected_canary_id=second_canary_id,
            business_attempt_id=business_attempt_id,
            expected_old_snapshot_id=first_snapshot_id,
            expected_output=old_output,
        )

        command.downgrade(migration, "0096_style_recommendation_dify")
        with psycopg.connect(target_url) as admin:
            assert admin.execute(
                "SELECT to_regclass('dify_workflow_release_snapshot_pins')"
            ).fetchone() == (None,)
        command.upgrade(migration, "0097_dify_snapshot_fencing")
        _assert_legacy_pin_state(
            target_url,
            project_id=seeded["project"],
            release_id=release_id,
            binding_id=binding_id,
            expected_snapshot_id=second_snapshot_id,
            expected_canary_id=second_canary_id,
            business_attempt_id=business_attempt_id,
            expected_old_snapshot_id=first_snapshot_id,
            expected_output=old_output,
        )
    finally:
        if database_created:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                if role_created:
                    server.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(app_login)))
                    server.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login))
                    )
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )


def _assert_legacy_pin_state(
    database_url: str,
    *,
    project_id,
    release_id,
    binding_id,
    expected_snapshot_id,
    expected_canary_id,
    business_attempt_id,
    expected_old_snapshot_id,
    expected_output: dict[str, object],
) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        row = connection.execute(
            """SELECT pin.published_snapshot_id, pin.canary_attempt_id, pin.pin_source,
                      binding.id AS binding_id, business.published_snapshot_id AS old_snapshot_id,
                      result.output AS old_output
               FROM dify_workflow_release_snapshot_pins AS pin
               JOIN dify_workflow_bindings AS binding
                 ON binding.project_id = pin.project_id
                AND binding.release_id = pin.release_id
               JOIN dify_workflow_execution_attempts AS business
                 ON business.id = %s AND business.project_id = pin.project_id
               JOIN dify_workflow_execution_results AS result
                 ON result.attempt_id = business.id AND result.project_id = business.project_id
               WHERE pin.project_id = %s AND pin.release_id = %s""",
            (business_attempt_id, project_id, release_id),
        ).fetchone()
    assert row == {
        "published_snapshot_id": expected_snapshot_id,
        "canary_attempt_id": expected_canary_id,
        "pin_source": "migration_backfill",
        "binding_id": binding_id,
        "old_snapshot_id": expected_old_snapshot_id,
        "old_output": expected_output,
    }
