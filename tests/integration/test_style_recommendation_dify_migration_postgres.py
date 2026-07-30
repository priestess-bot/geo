from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from geo_core.secrets import SecretValue, SecretVersionHandle
from geo_core.workflow_runtime import PostgresWorkflowRuntimeCatalog
from tests.integration.dify_release_migration_support import seed_legacy_dify_release
from tests.integration.model_gateway_postgres_fixtures import (
    active_provider_secret,
    register_openai_runtime,
)
from tests.integration.recommendation_dify_legacy_guard_support import (
    assert_legacy_lineage as _assert_legacy_lineage,
    assert_pre_upgrade_v3_native_only,
    seed_pre_upgrade_v3_parent,
)
from tests.integration.placement_worker_support import login_url, seed_project
from tests.integration.recommendation_postgres_lifecycle_support import (
    seed_frozen_recommendation_prompt as _seed_frozen_recommendation_prompt,
)
from tests.integration.test_recommendation_postgres_lifecycle import _principal


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_legacy_recommendation_model_lineage_survives_0096_roundtrip(
    tmp_path: Path,
) -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_recommendation_dify_migration_{suffix}"
    target_url = _database_url(ADMIN_URL, database_name)
    app_login, password = f"geo_rec_dify_{suffix}", uuid4().hex
    role_created = False
    database_created = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        database_created = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url
        command.upgrade(migration, "0095_synthetic_dify_closed_loop")

        now = datetime.now(UTC).replace(microsecond=0)
        with psycopg.connect(target_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(password)
                )
            )
            role_created = True
            seeded = seed_project(admin, suffix=f"rec-dify-migration-{suffix}")

        app_url = login_url(target_url, user=app_login, password=password)
        secret_api, provider_secret = active_provider_secret(
            app_url=app_url,
            ids=seeded,
            directory=tmp_path,
        )
        workflow_secret_id = uuid4()
        secret_api.create(
            _principal(seeded, seeded["owner"], "admin"),
            project_id=seeded["project"],
            reference_id=workflow_secret_id,
            purpose="workflow_runtime.dify",
            value=SecretValue("dify-workflow-key-v1"),
            expected_version=0,
            idempotency_key=f"workflow-secret-create:{suffix}",
        )
        secret_api.verify(
            _principal(seeded, seeded["owner"], "admin"),
            project_id=seeded["project"],
            reference_id=workflow_secret_id,
            version=1,
            expected_version=1,
            idempotency_key=f"workflow-secret-verify:{suffix}",
        )
        secret_api.activate(
            _principal(seeded, seeded["reviewer"], "admin"),
            project_id=seeded["project"],
            reference_id=workflow_secret_id,
            version=1,
            expected_version=2,
            idempotency_key=f"workflow-secret-activate:{suffix}",
        )
        runtime = register_openai_runtime(
            app_url=app_url,
            ids=seeded,
            provider_secret_handle=provider_secret,
            approved_at=now,
        )
        prompt_binding_id = _seed_frozen_recommendation_prompt(
            app_url=app_url,
            seeded=seeded,
            owner=_principal(seeded, seeded["owner"], "admin"),
            reviewer=_principal(seeded, seeded["reviewer"], "admin"),
        )

        parent_job_id, child_job_id = uuid4(), uuid4()
        with psycopg.connect(target_url, row_factory=dict_row) as admin:
            prompt = admin.execute(
                """SELECT binding.binding_version, binding.frozen_state_id,
                          state.version AS state_version,
                          release.program_id, release.id AS release_id,
                          release.version AS release_version,
                          release.release_hash, release.purpose,
                          release.output_schema_hash,
                          release.application_output_schema_hash
                   FROM prompt_program_bindings AS binding
                   JOIN prompt_program_release_states AS state
                     ON state.id = binding.frozen_state_id
                    AND state.project_id = binding.project_id
                   JOIN prompt_program_releases AS release
                     ON release.id = binding.release_id
                    AND release.project_id = binding.project_id
                   WHERE binding.project_id = %s AND binding.id = %s""",
                (seeded["project"], prompt_binding_id),
            ).fetchone()
            assert prompt is not None
            admin.execute(
                """INSERT INTO durable_jobs(
                       id, project_id, kind, status, input_hash, idempotency_key,
                       max_attempts, created_at, updated_at
                   ) VALUES
                       (%s, %s, 'recommendation.generation', 'queued', %s, %s, 3, %s, %s),
                       (%s, %s, 'recommendation.model_call', 'queued', %s, %s, 3, %s, %s)""",
                (
                    parent_job_id,
                    seeded["project"],
                    "1" * 64,
                    f"legacy-parent:{parent_job_id}",
                    now,
                    now,
                    child_job_id,
                    seeded["project"],
                    "2" * 64,
                    f"legacy-child:{child_job_id}",
                    now,
                    now,
                ),
            )
            selection = runtime.selection
            admin.execute(
                """INSERT INTO recommendation_model_tasks(
                       project_id, parent_job_id, child_job_id, parent_input_hash, role,
                       runtime_selection_id, runtime_manifest_id, runtime_manifest_hash,
                       runtime_option_id, runtime_option_hash,
                       prompt_binding_id, prompt_binding_version,
                       prompt_frozen_state_id, prompt_state_version,
                       prompt_release_id, prompt_release_version, prompt_release_hash,
                       prompt_purpose, provider, adapter_release_id, adapter_release_hash,
                       model_release_id, model_release_hash, configured_model,
                       capture_method, search_mode, prompt_bundle_hash,
                       structured_input_hash, output_schema_hash,
                       application_output_schema_hash, task_artifact_expires_at,
                       task_artifact_status, admitted_by, created_at
                   ) VALUES (
                       %s, %s, %s, %s, 'primary',
                       %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s,
                       'provider_api', NULL, %s, %s, %s, %s,
                       %s, 'uploading', %s, %s
                   )""",
                (
                    seeded["project"],
                    parent_job_id,
                    child_job_id,
                    "1" * 64,
                    selection.runtime_option_id,
                    selection.runtime_manifest_id,
                    selection.runtime_manifest_hash,
                    selection.runtime_option_id,
                    selection.runtime_option_hash,
                    prompt_binding_id,
                    prompt["binding_version"],
                    prompt["frozen_state_id"],
                    prompt["state_version"],
                    prompt["release_id"],
                    prompt["release_version"],
                    prompt["release_hash"],
                    prompt["purpose"],
                    runtime.route.provider,
                    runtime.route.adapter_release_id,
                    runtime.route.adapter_release_hash,
                    runtime.route.model_release_id,
                    runtime.route.model_release_hash,
                    selection.configured_model,
                    "3" * 64,
                    "4" * 64,
                    prompt["output_schema_hash"],
                    prompt["application_output_schema_hash"],
                    now + timedelta(days=7),
                    seeded["owner"],
                    now,
                ),
            )
            admin.execute(
                """UPDATE recommendation_model_tasks
                   SET task_artifact_uri = %s, task_artifact_manifest_hash = %s,
                       task_artifact_payload_uri = %s, task_artifact_content_hash = %s,
                       task_artifact_byte_size = 128, task_payload_hash = %s,
                       task_artifact_status = 'active'
                   WHERE project_id = %s AND child_job_id = %s""",
                (
                    f"s3://legacy-recommendation/{child_job_id}/manifest.json",
                    "5" * 64,
                    f"s3://legacy-recommendation/{child_job_id}/payload.json",
                    "6" * 64,
                    "7" * 64,
                    seeded["project"],
                    child_job_id,
                ),
            )
            admin.execute(
                """INSERT INTO recommendation_model_call_lineage(
                       project_id, parent_job_id, child_job_id, role,
                       task_artifact_status, task_artifact_expires_at,
                       status, created_at, updated_at
                   ) VALUES (%s, %s, %s, 'primary', 'active', %s, 'queued', %s, %s)""",
                (
                    seeded["project"],
                    parent_job_id,
                    child_job_id,
                    now + timedelta(days=7),
                    now,
                    now,
                ),
            )

        command.upgrade(migration, "0096_style_recommendation_dify")
        _assert_legacy_lineage(target_url, seeded["project"], child_job_id)
        with psycopg.connect(target_url) as admin:
            baseline_guard = admin.execute(
                "SELECT pg_get_functiondef('geo_assert_recommendation_model_task_change()'::regprocedure)"
            ).fetchone()
        assert baseline_guard is not None

        command.upgrade(migration, "0097_dify_snapshot_fencing")
        command.downgrade(migration, "0096_style_recommendation_dify")
        with psycopg.connect(target_url, row_factory=dict_row) as admin:
            restored_guard = admin.execute(
                "SELECT pg_get_functiondef('geo_assert_recommendation_model_task_change()'::regprocedure)"
            ).fetchone()
            assert restored_guard is not None
            assert restored_guard["pg_get_functiondef"] == baseline_guard[0]
            restored_child_id = _insert_native_recommendation_task(
                admin,
                seeded=seeded,
                prompt_binding_id=prompt_binding_id,
                prompt=prompt,
                runtime=runtime,
                now=now + timedelta(seconds=2),
            )
            restored = admin.execute(
                """SELECT execution_backend, workflow_release_id
                   FROM recommendation_model_tasks
                   WHERE project_id = %s AND child_job_id = %s""",
                (seeded["project"], restored_child_id),
            ).fetchone()
            assert restored == {
                "execution_backend": "model_gateway",
                "workflow_release_id": None,
            }

        catalog = PostgresWorkflowRuntimeCatalog(app_url)
        workflow_secret = SecretVersionHandle(
            reference_id=workflow_secret_id,
            project_id=seeded["project"],
            purpose="workflow_runtime.dify",
            version=1,
        )
        first_release_id = _register_recommendation_workflow_release(
            target_url,
            seeded=seeded,
            prompt=prompt,
            provider_secret=workflow_secret,
            configured_model=runtime.selection.configured_model,
            model_provider=runtime.route.provider,
            suffix=f"{suffix}-first",
        )
        second_release_id = _register_recommendation_workflow_release(
            target_url,
            seeded=seeded,
            prompt=prompt,
            provider_secret=workflow_secret,
            configured_model=runtime.selection.configured_model,
            model_provider=runtime.route.provider,
            suffix=f"{suffix}-second",
        )
        with psycopg.connect(target_url) as admin:
            _seed_successful_canary(
                admin,
                project_id=seeded["project"],
                release_id=first_release_id,
                purpose="recommendations.recommendation",
                app_id=f"recommendation-app-{suffix}-first",
                workflow_id=f"recommendation-workflow-{suffix}-first",
                configured_model=runtime.selection.configured_model,
                model_provider=runtime.route.provider,
                now=now + timedelta(seconds=3),
            )
            _seed_successful_canary(
                admin,
                project_id=seeded["project"],
                release_id=second_release_id,
                purpose="recommendations.recommendation",
                app_id=f"recommendation-app-{suffix}-second",
                workflow_id=f"recommendation-workflow-{suffix}-second",
                configured_model=runtime.selection.configured_model,
                model_provider=runtime.route.provider,
                now=now + timedelta(seconds=4),
            )
        catalog.activate_release(
            project_id=seeded["project"],
            release_id=first_release_id,
            activated_by=seeded["owner"],
            reason="first Recommendation release",
        )
        with psycopg.connect(target_url) as admin:
            legacy_v3_parent_id = seed_pre_upgrade_v3_parent(
                admin,
                project_id=seeded["project"],
                owner_id=seeded["owner"],
                now=now + timedelta(seconds=5),
            )
        command.upgrade(migration, "0097_dify_snapshot_fencing")
        assert_pre_upgrade_v3_native_only(
            target_url,
            seeded=seeded,
            prompt_binding_id=prompt_binding_id,
            prompt=prompt,
            runtime=runtime,
            legacy_parent_id=legacy_v3_parent_id,
            now=now + timedelta(seconds=6),
        )
        _assert_recommendation_binding_race_is_fenced(
            target_url,
            seeded=seeded,
            prompt_binding_id=prompt_binding_id,
            prompt=prompt,
            runtime=runtime,
            first_release_id=first_release_id,
            second_release_id=second_release_id,
            now=now + timedelta(seconds=8),
        )
        command.downgrade(migration, "0096_style_recommendation_dify")
        with psycopg.connect(target_url) as admin:
            admin.execute("SET LOCAL session_replication_role = replica")
            admin.execute(
                """DELETE FROM recommendation_model_tasks
                   WHERE project_id = %s AND execution_backend = 'dify'""",
                (seeded["project"],),
            )
            admin.execute(
                "DELETE FROM dify_workflow_bindings WHERE project_id = %s AND purpose = 'recommendations.recommendation'",
                (seeded["project"],),
            )
            admin.execute(
                """DELETE FROM dify_workflow_execution_attempts
                   WHERE project_id = %s AND release_id IN (%s, %s)""",
                (seeded["project"], first_release_id, second_release_id),
            )
            admin.execute(
                """DELETE FROM dify_workflow_published_snapshots
                   WHERE project_id = %s AND release_id IN (%s, %s)""",
                (seeded["project"], first_release_id, second_release_id),
            )
            admin.execute(
                """DELETE FROM dify_workflow_releases
                   WHERE project_id = %s AND id IN (%s, %s)""",
                (seeded["project"], first_release_id, second_release_id),
            )

        with psycopg.connect(target_url) as admin:
            admin.execute(
                """UPDATE recommendation_model_call_lineage
                   SET status = 'running', updated_at = updated_at + interval '1 second'
                   WHERE project_id = %s AND child_job_id = %s""",
                (seeded["project"], child_job_id),
            )

        command.downgrade(migration, "0095_synthetic_dify_closed_loop")
        with psycopg.connect(target_url, row_factory=dict_row) as admin:
            legacy = admin.execute(
                """SELECT status FROM recommendation_model_call_lineage
                   WHERE project_id = %s AND child_job_id = %s""",
                (seeded["project"], child_job_id),
            ).fetchone()
        assert legacy == {"status": "running"}

        command.upgrade(migration, "0096_style_recommendation_dify")
        _assert_legacy_lineage(target_url, seeded["project"], child_job_id, status="running")
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


def _insert_native_recommendation_task(
    connection,
    *,
    seeded,
    prompt_binding_id,
    prompt,
    runtime,
    now: datetime,
):
    parent_job_id, child_job_id = _seed_recommendation_jobs(
        connection, project_id=seeded["project"], now=now
    )
    _insert_recommendation_task_row(
        connection,
        seeded=seeded,
        prompt_binding_id=prompt_binding_id,
        prompt=prompt,
        runtime=runtime,
        parent_job_id=parent_job_id,
        child_job_id=child_job_id,
        execution_backend="model_gateway",
        workflow_release_id=None,
        workflow_release_hash=None,
        now=now,
    )
    return child_job_id


def _seed_recommendation_jobs(connection, *, project_id, now: datetime):
    parent_job_id, child_job_id = uuid4(), uuid4()
    connection.execute(
        """INSERT INTO durable_jobs(
               id, project_id, kind, status, input_hash, idempotency_key,
               max_attempts, created_at, updated_at
           ) VALUES
               (%s, %s, 'recommendation.generation', 'queued', %s, %s, 3, %s, %s),
               (%s, %s, 'recommendation.model_call', 'queued', %s, %s, 3, %s, %s)""",
        (
            parent_job_id,
            project_id,
            "8" * 64,
            f"restored-parent:{parent_job_id}",
            now,
            now,
            child_job_id,
            project_id,
            "9" * 64,
            f"restored-child:{child_job_id}",
            now,
            now,
        ),
    )
    return parent_job_id, child_job_id


def _insert_recommendation_task_row(
    connection,
    *,
    seeded,
    prompt_binding_id,
    prompt,
    runtime,
    parent_job_id,
    child_job_id,
    execution_backend: str,
    workflow_release_id,
    workflow_release_hash,
    now: datetime,
):
    selection = runtime.selection
    connection.execute(
        """INSERT INTO recommendation_model_tasks(
               project_id, parent_job_id, child_job_id, parent_input_hash, role,
               execution_backend, workflow_release_id, workflow_release_hash,
               runtime_selection_id, runtime_manifest_id, runtime_manifest_hash,
               runtime_option_id, runtime_option_hash,
               prompt_binding_id, prompt_binding_version,
               prompt_frozen_state_id, prompt_state_version,
               prompt_release_id, prompt_release_version, prompt_release_hash,
               prompt_purpose, provider, adapter_release_id, adapter_release_hash,
               model_release_id, model_release_hash, configured_model,
               capture_method, search_mode, prompt_bundle_hash,
               structured_input_hash, output_schema_hash,
               application_output_schema_hash, task_artifact_expires_at,
               task_artifact_status, admitted_by, created_at
           ) VALUES (
               %s, %s, %s, %s, 'primary',
               %s, %s, %s,
               %s, %s, %s, %s, %s,
               %s, %s, %s, %s, %s, %s, %s,
               %s, %s, %s, %s, %s, %s, %s,
               'provider_api', NULL, %s, %s, %s, %s,
               %s, 'uploading', %s, %s
           )""",
        (
            seeded["project"],
            parent_job_id,
            child_job_id,
            "8" * 64,
            execution_backend,
            workflow_release_id,
            workflow_release_hash,
            selection.runtime_option_id,
            selection.runtime_manifest_id,
            selection.runtime_manifest_hash,
            selection.runtime_option_id,
            selection.runtime_option_hash,
            prompt_binding_id,
            prompt["binding_version"],
            prompt["frozen_state_id"],
            prompt["state_version"],
            prompt["release_id"],
            prompt["release_version"],
            prompt["release_hash"],
            prompt["purpose"],
            runtime.route.provider,
            runtime.route.adapter_release_id,
            runtime.route.adapter_release_hash,
            runtime.route.model_release_id,
            runtime.route.model_release_hash,
            selection.configured_model,
            "a" * 64,
            "b" * 64,
            prompt["output_schema_hash"],
            prompt["application_output_schema_hash"],
            now + timedelta(days=7),
            seeded["owner"],
            now,
        ),
    )


def _register_recommendation_workflow_release(
    database_url,
    *,
    seeded,
    prompt,
    provider_secret,
    configured_model: str,
    model_provider: str,
    suffix: str,
):
    return seed_legacy_dify_release(
        database_url,
        project_id=seeded["project"],
        purpose="recommendations.recommendation",
        prompt_program_id=prompt["program_id"],
        prompt_release_id=prompt["release_id"],
        dify_app_id=f"recommendation-app-{suffix}",
        dify_workflow_id=f"recommendation-workflow-{suffix}",
        dsl_hash="c" * 64,
        configured_model=configured_model,
        model_provider=model_provider,
        api_secret_handle=provider_secret,
        created_by=seeded["owner"],
    )


def _seed_successful_canary(
    connection,
    *,
    project_id,
    release_id,
    purpose: str,
    app_id: str,
    workflow_id: str,
    configured_model: str,
    model_provider: str,
    now: datetime,
):
    snapshot_id, attempt_id = uuid4(), uuid4()
    connection.execute(
        """INSERT INTO dify_workflow_published_snapshots(
               id, project_id, release_id, purpose, dify_app_id,
               dify_workflow_id, workflow_hash, snapshot_hash, prompt_nodes,
               input_variables, graph_nodes, published_at, observed_at
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '[]'::jsonb,
                     '[]'::jsonb, %s, %s)""",
        (
            snapshot_id,
            project_id,
            release_id,
            purpose,
            app_id,
            workflow_id,
            "d" * 64,
            "e" * 64,
            Jsonb(
                [
                    {
                        "model_provider": model_provider,
                        "model_name": configured_model,
                    }
                ]
            ),
            now,
            now,
        ),
    )
    connection.execute(
        """INSERT INTO dify_workflow_execution_attempts(
               id, project_id, release_id, execution_kind, attempt_number,
               status, context_hash, request_hash, dify_run_id,
               reported_workflow_id, output_hash, retryable,
               published_snapshot_id, started_at, finished_at
           ) VALUES (%s, %s, %s, 'canary', 1, 'succeeded', %s, %s, %s, %s,
                     %s, false, %s, %s, %s)""",
        (
            attempt_id,
            project_id,
            release_id,
            "1" * 64,
            "2" * 64,
            f"canary-{workflow_id}",
            workflow_id,
            "3" * 64,
            snapshot_id,
            now,
            now,
        ),
    )


def _assert_recommendation_binding_race_is_fenced(
    database_url: str,
    *,
    seeded,
    prompt_binding_id,
    prompt,
    runtime,
    first_release_id,
    second_release_id,
    now: datetime,
):
    with psycopg.connect(database_url, row_factory=dict_row) as admin:
        releases = {
            row["id"]: row
            for row in admin.execute(
                """SELECT id, release_hash FROM dify_workflow_releases
                   WHERE project_id = %s AND id IN (%s, %s)""",
                (seeded["project"], first_release_id, second_release_id),
            ).fetchall()
        }
        active = admin.execute(
            """SELECT id, binding_version FROM dify_workflow_bindings
               WHERE project_id = %s AND purpose = 'recommendations.recommendation'
               ORDER BY binding_version DESC LIMIT 1""",
            (seeded["project"],),
        ).fetchone()
    assert active is not None

    with psycopg.connect(database_url) as admin:
        native_parent, native_child = _seed_recommendation_jobs(
            admin, project_id=seeded["project"], now=now
        )
    with psycopg.connect(database_url) as admin:
        with pytest.raises(
            psycopg.errors.SerializationFailure,
            match="bound to Dify",
        ):
            _insert_recommendation_task_row(
                admin,
                seeded=seeded,
                prompt_binding_id=prompt_binding_id,
                prompt=prompt,
                runtime=runtime,
                parent_job_id=native_parent,
                child_job_id=native_child,
                execution_backend="model_gateway",
                workflow_release_id=None,
                workflow_release_hash=None,
                now=now,
            )

    with psycopg.connect(database_url) as admin:
        race_parent, race_child = _seed_recommendation_jobs(
            admin, project_id=seeded["project"], now=now + timedelta(seconds=1)
        )
    activation = psycopg.connect(database_url)
    reservation = psycopg.connect(database_url)
    try:
        activation.execute(
            """INSERT INTO dify_workflow_bindings(
                   id, project_id, purpose, release_id, release_hash,
                   binding_version, previous_binding_id, activated_by, reason
               ) VALUES (%s, %s, 'recommendations.recommendation', %s, %s,
                         %s, %s, %s, 'concurrent replacement')""",
            (
                uuid4(),
                seeded["project"],
                second_release_id,
                releases[second_release_id]["release_hash"],
                active["binding_version"] + 1,
                active["id"],
                seeded["owner"],
            ),
        )
        reservation.execute("SET LOCAL statement_timeout = '250ms'")
        with pytest.raises(psycopg.errors.QueryCanceled):
            _insert_recommendation_task_row(
                reservation,
                seeded=seeded,
                prompt_binding_id=prompt_binding_id,
                prompt=prompt,
                runtime=runtime,
                parent_job_id=race_parent,
                child_job_id=race_child,
                execution_backend="dify",
                workflow_release_id=first_release_id,
                workflow_release_hash=releases[first_release_id]["release_hash"],
                now=now + timedelta(seconds=1),
            )
        reservation.rollback()
        activation.commit()
        with pytest.raises(
            psycopg.errors.SerializationFailure,
            match="active pinned Workflow Release",
        ):
            _insert_recommendation_task_row(
                reservation,
                seeded=seeded,
                prompt_binding_id=prompt_binding_id,
                prompt=prompt,
                runtime=runtime,
                parent_job_id=race_parent,
                child_job_id=race_child,
                execution_backend="dify",
                workflow_release_id=first_release_id,
                workflow_release_hash=releases[first_release_id]["release_hash"],
                now=now + timedelta(seconds=1),
            )
    finally:
        activation.close()
        reservation.close()

    with psycopg.connect(database_url) as admin:
        current_parent, current_child = _seed_recommendation_jobs(
            admin, project_id=seeded["project"], now=now + timedelta(seconds=2)
        )
        _insert_recommendation_task_row(
            admin,
            seeded=seeded,
            prompt_binding_id=prompt_binding_id,
            prompt=prompt,
            runtime=runtime,
            parent_job_id=current_parent,
            child_job_id=current_child,
            execution_backend="dify",
            workflow_release_id=second_release_id,
            workflow_release_hash=releases[second_release_id]["release_hash"],
            now=now + timedelta(seconds=2),
        )


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
