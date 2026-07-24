from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
from geo_core.workflow_c_metric_judge_worker import PostgresWorkflowCMetricJudgeRepository
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_metric_child_completion_is_project_scoped_and_fenced() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_metric_child_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    worker_login, password = f"geo_metric_child_{suffix}", uuid4().hex
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
        command.downgrade(migration, "0059_analysis_project_scope")
        command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(password)
                )
            )
            created_role = True
            first = seed_project(admin, suffix=f"metric-child-{suffix}-first")
            second = seed_project(admin, suffix=f"metric-child-{suffix}-second")
            seeded = _seed_running_metric_child(admin, project_id=first["project"], now=now)
            hash_mismatch = _seed_running_metric_child(
                admin,
                project_id=first["project"],
                now=now,
                sampling_lineage=(
                    UUID(str(seeded["run_id"])),
                    UUID(str(seeded["observation_id"])),
                ),
            )
            legacy = _seed_running_metric_child(
                admin,
                project_id=first["project"],
                now=now,
                sampling_lineage=(
                    UUID(str(seeded["run_id"])),
                    UUID(str(seeded["observation_id"])),
                ),
            )

        worker_url = login_url(database_url, user=worker_login, password=password)
        projection = _judge_projection()
        output_hash = _projection_hash(projection)
        with psycopg.connect(worker_url) as worker:
            set_project_scope(worker, first["project"])
            row = worker.execute(
                """SELECT * FROM geo_complete_workflow_c_metric_child(
                       %s, %s, %s, 1, %s, 'metric_judge', %s, %s, NULL, NULL, %s::jsonb
                   )""",
                (
                    first["project"],
                    seeded["child_job"],
                    seeded["lease_token"],
                    seeded["parent_input_hash"],
                    uuid4(),
                    output_hash,
                    Jsonb(projection),
                ),
            ).fetchone()
            assert row is not None and row[0] == "succeeded" and row[1] == "running"
            persisted = worker.execute(
                """SELECT output_hash, output_projection
                       FROM workflow_c_metric_child_output_projections
                      WHERE project_id = %s AND child_job_id = %s""",
                (first["project"], seeded["child_job"]),
            ).fetchone()
            assert persisted == (output_hash, projection)
            worker.commit()
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                worker.execute(
                    "UPDATE workflow_c_metric_model_children SET status = 'failed'"
                )
            worker.rollback()

        with psycopg.connect(worker_url) as worker:
            set_project_scope(worker, first["project"])
            with pytest.raises(psycopg.errors.SerializationFailure, match="completion was fenced"):
                worker.execute(
                    """SELECT * FROM geo_complete_workflow_c_metric_child(
                           %s, %s, %s, 1, %s, 'metric_judge', %s, %s, NULL, NULL, %s::jsonb
                       )""",
                    (
                        first["project"],
                        seeded["child_job"],
                        seeded["lease_token"],
                        seeded["parent_input_hash"],
                        uuid4(),
                        output_hash,
                        Jsonb(projection),
                    ),
                )
            worker.rollback()
            with pytest.raises(psycopg.errors.InvalidParameterValue, match="completion input is invalid"):
                worker.execute(
                    """SELECT * FROM geo_complete_workflow_c_metric_child(
                           %s, %s, %s, 1, %s, 'metric_judge', %s, %s, NULL, NULL, %s::jsonb
                       )""",
                    (
                        second["project"],
                        seeded["child_job"],
                        seeded["lease_token"],
                        seeded["parent_input_hash"],
                        uuid4(),
                        output_hash,
                        Jsonb(projection),
                    ),
                )
            worker.rollback()

            with pytest.raises(psycopg.errors.InvalidParameterValue, match="projection does not match"):
                worker.execute(
                    """SELECT * FROM geo_complete_workflow_c_metric_child(
                           %s, %s, %s, 1, %s, 'metric_judge', %s, %s, NULL, NULL, %s::jsonb
                       )""",
                    (
                        first["project"],
                        hash_mismatch["child_job"],
                        hash_mismatch["lease_token"],
                        hash_mismatch["parent_input_hash"],
                        uuid4(),
                        _hash("different-projection"),
                        Jsonb(projection),
                    ),
                )
            worker.rollback()
            set_project_scope(worker, first["project"])
            assert worker.execute(
                """SELECT status FROM workflow_c_metric_model_children
                      WHERE project_id = %s AND child_job_id = %s""",
                (first["project"], hash_mismatch["child_job"]),
            ).fetchone() == ("running",)

            legacy_row = worker.execute(
                """SELECT * FROM geo_complete_workflow_c_metric_child(
                       %s, %s, %s, 1, %s, 'metric_judge', %s, %s, NULL, NULL
                   )""",
                (
                    first["project"],
                    legacy["child_job"],
                    legacy["lease_token"],
                    legacy["parent_input_hash"],
                    uuid4(),
                    output_hash,
                ),
            ).fetchone()
            assert legacy_row is not None and legacy_row[0] == "succeeded"
            assert worker.execute(
                """SELECT count(*) FROM workflow_c_metric_child_output_projections
                      WHERE project_id = %s AND child_job_id = %s""",
                (first["project"], legacy["child_job"]),
            ).fetchone() == (0,)
            worker.commit()
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
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login)))


def test_matching_metric_judges_complete_the_batch_without_an_arbiter() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_metric_agreement_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    worker_login, password = f"geo_metric_agreement_{suffix}", uuid4().hex
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
        command.downgrade(migration, "0061_metric_child_reconcile")
        command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(password)
                )
            )
            created_role = True
            project_id = seed_project(admin, suffix=f"metric-agreement-{suffix}")["project"]
            first = _seed_running_metric_child(admin, project_id=project_id, now=now)
            second = _seed_running_metric_judge_sibling(
                admin,
                project_id=project_id,
                batch_id=first["batch_id"],
                parent_job_id=first["parent_job_id"],
                parent_input_hash=first["parent_input_hash"],
                now=now,
            )

        worker_url = login_url(database_url, user=worker_login, password=password)
        projection = _judge_projection()
        agreed_output = _projection_hash(projection)
        with psycopg.connect(worker_url) as worker:
            set_project_scope(worker, project_id)
            first_row = worker.execute(
                """SELECT * FROM geo_complete_workflow_c_metric_child(
                       %s, %s, %s, 1, %s, 'metric_judge', %s, %s, NULL, NULL, %s::jsonb
                   )""",
                (
                    project_id,
                    first["child_job"],
                    first["lease_token"],
                    first["parent_input_hash"],
                    uuid4(),
                    agreed_output,
                    Jsonb(projection),
                ),
            ).fetchone()
            assert first_row is not None and first_row[1] == "running"
            second_row = worker.execute(
                """SELECT * FROM geo_complete_workflow_c_metric_child(
                       %s, %s, %s, 1, %s, 'metric_judge', %s, %s, NULL, NULL, %s::jsonb
                   )""",
                (
                    project_id,
                    second["child_job"],
                    second["lease_token"],
                    first["parent_input_hash"],
                    uuid4(),
                    agreed_output,
                    Jsonb(projection),
                ),
            ).fetchone()
            assert second_row is not None and second_row[1] == "completed"
            batch = worker.execute(
                """SELECT status, selected_candidate_id, selected_output_hash, completed_at
                       FROM workflow_c_metric_judge_batches
                      WHERE project_id = %s AND id = %s""",
                (project_id, first["batch_id"]),
            ).fetchone()
            assert batch is not None
            assert batch[0] == "completed"
            assert batch[1] == first["candidate_id"]
            assert batch[2] == agreed_output
            assert batch[3] is not None
            arbiter_count = worker.execute(
                """SELECT count(*) FROM workflow_c_metric_model_children
                      WHERE project_id = %s AND batch_id = %s AND role = 'arbiter'""",
                (project_id, first["batch_id"]),
            ).fetchone()
            assert arbiter_count == (0,)
            projections = worker.execute(
                """SELECT output_projection
                       FROM workflow_c_metric_child_output_projections AS projection
                       JOIN workflow_c_metric_model_children AS child
                         ON child.project_id = projection.project_id
                        AND child.child_job_id = projection.child_job_id
                      WHERE projection.project_id = %s AND child.batch_id = %s
                      ORDER BY child.ordinal""",
                (project_id, first["batch_id"]),
            ).fetchall()
            assert projections == [(projection,), (projection,)]
            worker.commit()
            repository = PostgresWorkflowCMetricJudgeRepository(
                lambda: psycopg.connect(worker_url, row_factory=dict_row)
            )
            selected = repository.selected_judge_candidate(
                project_id=project_id, batch_id=first["batch_id"]
            )
            assert selected.candidate_id == str(first["candidate_id"])
            assert selected.output.overall_status == "pass"
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
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login)))


def _seed_running_metric_child(
    connection: psycopg.Connection,
    *,
    project_id: UUID,
    now: datetime,
    sampling_lineage: tuple[UUID, UUID] | None = None,
) -> dict[str, UUID | str]:
    parent_job, child_job, batch_id = uuid4(), uuid4(), uuid4()
    lease_token, candidate_id = uuid4(), uuid4()
    runtime_option_id = uuid4()
    parent_input_hash, task_hash = _hash("metric-parent"), _hash("metric-task")
    if sampling_lineage is None:
        run_id, observation_id = _seed_metric_sampling_lineage(
            connection, project_id=project_id, now=now
        )
    else:
        run_id, observation_id = sampling_lineage
    connection.execute(
        """INSERT INTO durable_jobs(
               id, project_id, kind, status, input_hash, idempotency_key, next_run_at
           ) VALUES (%s, %s, 'workflow_c.analysis.semantic_metrics', 'queued', %s, %s, %s)""",
        (parent_job, project_id, parent_input_hash, f"metric-parent:{parent_job}", now),
    )
    connection.execute(
        """INSERT INTO durable_jobs(
               id, project_id, kind, status, input_hash, idempotency_key, next_run_at,
               lease_owner, lease_token, lease_expires_at, heartbeat_at, fencing_generation
           ) VALUES (%s, %s, 'workflow_c.metric_judge', 'running', %s, %s, %s,
                     'metric-worker', %s, %s, %s, 1)""",
        (
            child_job,
            project_id,
            task_hash,
            f"metric-child:{child_job}",
            now,
            lease_token,
            now + timedelta(hours=1),
            now,
        ),
    )
    connection.execute("SET LOCAL session_replication_role = replica")
    connection.execute(
        """INSERT INTO workflow_c_metric_judge_batches(
               id, project_id, parent_job_id, run_id, observation_id, ordinal,
               planned_batch_count, plans_hash, parent_input_hash, input_set_hash,
               metric_suite_hash, status, aggregate_version, created_at
           ) VALUES (%s, %s, %s, %s, %s, 1, 1, %s, %s, %s, %s, 'queued', 1, %s)""",
        (
            batch_id, project_id, parent_job, run_id, observation_id, _hash("plans"),
            parent_input_hash, _hash("input-set"), _hash("metric-suite"), now,
        ),
    )
    connection.execute(
        """INSERT INTO workflow_c_metric_model_children(
               project_id, parent_job_id, child_job_id, batch_id, role, ordinal,
               evaluator_id, candidate_id, parent_input_hash, runtime_selection_id,
               runtime_manifest_id, runtime_manifest_hash, runtime_option_id,
               runtime_option_hash, prompt_binding_id, prompt_binding_version,
               prompt_frozen_state_id, prompt_state_version, prompt_release_id,
               prompt_release_version, prompt_release_hash, prompt_purpose,
               prompt_bundle_hash, portable_output_schema_hash,
               application_output_schema_hash, task_ciphertext, task_data_nonce,
               task_wrapped_data_key, task_wrap_nonce, task_master_key_version,
               task_algorithm, task_hash, status, created_at
           ) VALUES (%s, %s, %s, %s, 'metric_judge', 1, 'fixture-judge', %s, %s,
                     %s, %s, %s, %s, %s, %s, 1, %s, 1, %s, 1, %s, 'metric_judge',
                     %s, %s, %s, %s, %s, %s, %s, 1, 'AES-256-GCM', %s, 'running', %s)""",
        (
            project_id, parent_job, child_job, batch_id, candidate_id, parent_input_hash,
            runtime_option_id, uuid4(), _hash("runtime-manifest"), runtime_option_id,
            _hash("runtime-option"),
            uuid4(), uuid4(), uuid4(), _hash("prompt-release"),
            _hash("prompt-bundle"), _hash("portable-schema"), _hash("application-schema"),
            b"fixture-ciphertext", b"a" * 12, b"fixture-wrapped-key", b"b" * 12,
            task_hash, now,
        ),
    )
    return {
        "child_job": child_job,
        "lease_token": lease_token,
        "parent_input_hash": parent_input_hash,
        "parent_job_id": parent_job,
        "batch_id": batch_id,
        "candidate_id": candidate_id,
        "run_id": run_id,
        "observation_id": observation_id,
    }


def _seed_metric_sampling_lineage(
    connection: psycopg.Connection, *, project_id: UUID, now: datetime
) -> tuple[UUID, UUID]:
    """Create the persisted Observation identity required by a metric batch."""
    policy_id, suite_id, run_id = uuid4(), uuid4(), uuid4()
    task_id, attempt_id, attempt_job_id, observation_id = uuid4(), uuid4(), uuid4(), uuid4()
    policy_hash = _hash(f"metric-policy:{policy_id}")
    suite_hash = _hash(f"metric-suite:{suite_id}")
    task_key = _hash(f"metric-task:{task_id}")
    source_stratum_hash = _hash(f"metric-source:{project_id}")
    location_evidence_hash = _hash(f"metric-location:{attempt_id}")

    # This fixture creates immutable historical lineage.  The actual test
    # transition is still executed through the worker-only completion RPC.
    connection.execute("SET LOCAL session_replication_role = replica")
    connection.execute(
        """INSERT INTO workflow_c_sampling_admission_policies(
               id, project_id, revision, status, effective_authorization_state,
               platform, capture_method, adapter_release, location_control,
               location_evidence_hash, authorization_reference, created_by,
               authorized_purposes, definition_hash, policy_version, valid_until,
               quota_remaining, daily_task_limit, minimum_request_interval_seconds,
               max_concurrency, aggregate_version, payload, created_at, updated_at
           ) VALUES (%s, %s, 1, 'draft', 'not_assessed',
                     'fixture', 'manual_ui', 'fixture-v1', 'not_controlled', %s,
                     'fixture:metric-lineage', 'fixture-owner', '[\"geo_measurement\"]'::jsonb,
                     %s, 'fixture-v1', %s, 1, 1, 0, 1, 1, '{}'::jsonb, %s, %s)""",
        (
            policy_id,
            project_id,
            location_evidence_hash,
            policy_hash,
            now + timedelta(days=1),
            now,
            now,
        ),
    )
    connection.execute(
        """INSERT INTO workflow_c_sampling_suites(
               id, project_id, suite_hash, admission_policy_id, admission_policy_hash,
               source_stratum_hash, capture_method, planned_task_count,
               minimum_valid_repeats, payload, frozen_at
           ) VALUES (%s, %s, %s, %s, %s, %s, 'manual_ui', 1, 3, '{}'::jsonb, %s)""",
        (suite_id, project_id, suite_hash, policy_id, policy_hash, source_stratum_hash, now),
    )
    connection.execute(
        """INSERT INTO workflow_c_sampling_runs(
               id, project_id, suite_id, suite_hash, admission_policy_id,
               admission_policy_hash, admission_grant_hash, purpose, status,
               reserved_task_count, admitted_not_before, authorization_valid_until,
               version, payload, created_at
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'geo_measurement', 'completed',
                     1, %s, %s, 1, '{}'::jsonb, %s)""",
        (
            run_id,
            project_id,
            suite_id,
            suite_hash,
            policy_id,
            policy_hash,
            _hash(f"metric-grant:{run_id}"),
            now - timedelta(minutes=1),
            now + timedelta(days=1),
            now,
        ),
    )
    connection.execute(
        """INSERT INTO workflow_c_sampling_tasks(
               id, project_id, run_id, suite_id, task_key, source_stratum_hash,
               capture_method, question_id, question_version, repetition, status,
               version, payload, created_at, updated_at
           ) VALUES (%s, %s, %s, %s, %s, %s, 'manual_ui', 'fixture-question', 'v1',
                     1, 'succeeded', 1, '{}'::jsonb, %s, %s)""",
        (task_id, project_id, run_id, suite_id, task_key, source_stratum_hash, now, now),
    )
    connection.execute(
        """INSERT INTO durable_jobs(
               id, project_id, kind, status, input_hash, idempotency_key,
               next_run_at, completed_at
           ) VALUES (%s, %s, 'sampling.manual_import', 'succeeded', %s, %s, %s, %s)""",
        (
            attempt_job_id,
            project_id,
            _hash(f"metric-attempt-job:{attempt_job_id}"),
            f"metric-attempt-job:{attempt_job_id}",
            now,
            now,
        ),
    )
    connection.execute(
        """INSERT INTO workflow_c_sampling_attempts(
               id, project_id, run_id, task_id, task_key, durable_job_id, ordinal,
               status, authorization_checked_at, version, payload, created_at, updated_at
           ) VALUES (%s, %s, %s, %s, %s, %s, 1, 'succeeded', %s, 1,
                     '{}'::jsonb, %s, %s)""",
        (attempt_id, project_id, run_id, task_id, task_key, attempt_job_id, now, now, now),
    )
    connection.execute(
        """INSERT INTO workflow_c_sampling_observations(
               id, project_id, run_id, task_id, attempt_id, task_key, source_stratum_hash,
               status, observation_hash, actual_location_json, evidence_json, payload, observed_at
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'complete', %s,
                     jsonb_build_object('location_control', 'not_controlled',
                                        'location_evidence_hash', %s::text),
                     '{}'::jsonb, '{}'::jsonb, %s)""",
        (
            observation_id,
            project_id,
            run_id,
            task_id,
            attempt_id,
            task_key,
            source_stratum_hash,
            _hash(f"metric-observation:{observation_id}"),
            location_evidence_hash,
            now,
        ),
    )
    return run_id, observation_id


def _seed_running_metric_judge_sibling(
    connection: psycopg.Connection,
    *,
    project_id: UUID,
    batch_id: UUID,
    parent_job_id: UUID,
    parent_input_hash: str,
    now: datetime,
) -> dict[str, UUID]:
    child_job, lease_token, candidate_id, runtime_option_id = uuid4(), uuid4(), uuid4(), uuid4()
    task_hash = _hash(f"metric-sibling-task:{child_job}")
    connection.execute(
        """INSERT INTO durable_jobs(
               id, project_id, kind, status, input_hash, idempotency_key, next_run_at,
               lease_owner, lease_token, lease_expires_at, heartbeat_at, fencing_generation
           ) VALUES (%s, %s, 'workflow_c.metric_judge', 'running', %s, %s, %s,
                     'metric-worker', %s, %s, %s, 1)""",
        (
            child_job,
            project_id,
            task_hash,
            f"metric-child:{child_job}",
            now,
            lease_token,
            now + timedelta(hours=1),
            now,
        ),
    )
    connection.execute(
        """INSERT INTO workflow_c_metric_model_children(
               project_id, parent_job_id, child_job_id, batch_id, role, ordinal,
               evaluator_id, candidate_id, parent_input_hash, runtime_selection_id,
               runtime_manifest_id, runtime_manifest_hash, runtime_option_id,
               runtime_option_hash, prompt_binding_id, prompt_binding_version,
               prompt_frozen_state_id, prompt_state_version, prompt_release_id,
               prompt_release_version, prompt_release_hash, prompt_purpose,
               prompt_bundle_hash, portable_output_schema_hash,
               application_output_schema_hash, task_ciphertext, task_data_nonce,
               task_wrapped_data_key, task_wrap_nonce, task_master_key_version,
               task_algorithm, task_hash, status, created_at
           ) VALUES (%s, %s, %s, %s, 'metric_judge', 2, 'fixture-judge-b', %s, %s,
                     %s, %s, %s, %s, %s, %s, 1, %s, 1, %s, 1, %s, 'metric_judge',
                     %s, %s, %s, %s, %s, %s, %s, 1, 'AES-256-GCM', %s, 'running', %s)""",
        (
            project_id,
            parent_job_id,
            child_job,
            batch_id,
            candidate_id,
            parent_input_hash,
            runtime_option_id,
            uuid4(),
            _hash("runtime-manifest-sibling"),
            runtime_option_id,
            _hash("runtime-option-sibling"),
            uuid4(),
            uuid4(),
            uuid4(),
            _hash("prompt-release-sibling"),
            _hash("prompt-bundle-sibling"),
            _hash("portable-schema-sibling"),
            _hash("application-schema-sibling"),
            b"fixture-ciphertext-sibling",
            b"c" * 12,
            b"fixture-wrapped-key-sibling",
            b"d" * 12,
            task_hash,
            now,
        ),
    )
    return {"child_job": child_job, "lease_token": lease_token, "candidate_id": candidate_id}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _judge_projection() -> dict[str, object]:
    return {
        "results": [
            {
                "kind": "recommendation",
                "label": "yes",
                "score": "1",
                "reason_codes": [],
                "locators": [
                    {
                        "kind": "answer_span",
                        "reference_id": "fixture-answer",
                        "version": "fixture-v1",
                        "content_hash": "a" * 64,
                        "start": 0,
                        "end": 1,
                        "redacted_quote_hash": None,
                    }
                ],
                "schema_version": "metric-judge-output-v1",
                "metric_id": "recommendation",
            }
        ],
        "overall_status": "pass",
        "output_locale": "en-AU",
    }


def _projection_hash(value: dict[str, object]) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
