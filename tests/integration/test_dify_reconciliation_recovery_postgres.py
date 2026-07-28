from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
from geo_core.workflow_runtime import PostgresWorkflowRuntimeCatalog
from geo_core.workflow_runtime.contracts import canonical_json_hash
from geo_core.workflow_runtime.reconciliation import (
    DifyRecoveryBindingError,
    DifyRecoveryRequiredError,
    bind_dify_resubmission,
)
from tests.integration.test_style_profile_dify_result_binding_postgres import (
    _seed_exact_dify_style_child,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_unknown_outcome_recovery_uses_one_new_parent_and_never_replays_old_parent() -> None:
    database_name = f"geo_dify_recovery_{uuid4().hex[:10]}"
    target_url = _database_url(ADMIN_URL, database_name)
    created_database = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url
        command.upgrade(migration, "0099_style_profile_build_binding")

        fixture = _seed_exact_dify_style_child(target_url)
        now = datetime.now(UTC).replace(microsecond=0)
        _make_unknown_outcome_with_active_lease(target_url, fixture, now=now)
        project_id = _uuid(fixture["project_id"])
        owner_id = _uuid(fixture["owner_id"])
        attempt_id = _uuid(fixture["business_attempt_id"])
        catalog = PostgresWorkflowRuntimeCatalog(target_url)

        unresolved = catalog.list_unresolved_attempts(project_id=project_id)
        assert len(unresolved) == 1
        assert unresolved[0].lease_state == "active"
        assert unresolved[0].required_action == "wait_for_lease_expiry"
        with pytest.raises(psycopg.errors.SerializationFailure, match="lease is active"):
            _issue_token(catalog, project_id, attempt_id, owner_id)

        _expire_child_lease(target_url, fixture, now=now)
        token = _issue_token(catalog, project_id, attempt_id, owner_id)
        assert len(token) == 64

        with psycopg.connect(target_url, row_factory=dict_row) as connection:
            different_parent = _clone_parent(
                connection, fixture, fingerprint_value="different", now=now
            )
            set_project_scope(connection, project_id)
            assert (
                bind_dify_resubmission(
                    connection,
                    project_id=project_id,
                    new_parent_job_id=different_parent,
                    actor_id=owner_id,
                    recovery_of_attempt_id=None,
                    token=None,
                )
                is None
            )

        omitted = psycopg.connect(target_url, row_factory=dict_row)
        try:
            same_without_token = _clone_parent(omitted, fixture, fingerprint_value="same", now=now)
            set_project_scope(omitted, project_id)
            with pytest.raises(DifyRecoveryRequiredError, match="requires recovery_of_attempt_id"):
                bind_dify_resubmission(
                    omitted,
                    project_id=project_id,
                    new_parent_job_id=same_without_token,
                    actor_id=owner_id,
                    recovery_of_attempt_id=None,
                    token=None,
                )
            omitted.rollback()
        finally:
            omitted.close()

        with psycopg.connect(target_url, row_factory=dict_row) as connection:
            recovered_parent = _clone_parent(connection, fixture, fingerprint_value="same", now=now)
            set_project_scope(connection, project_id)
            assert (
                bind_dify_resubmission(
                    connection,
                    project_id=project_id,
                    new_parent_job_id=recovered_parent,
                    actor_id=owner_id,
                    recovery_of_attempt_id=attempt_id,
                    token=token,
                )
                == attempt_id
            )

        with psycopg.connect(target_url, row_factory=dict_row) as connection:
            set_project_scope(connection, project_id)
            assert (
                bind_dify_resubmission(
                    connection,
                    project_id=project_id,
                    new_parent_job_id=recovered_parent,
                    actor_id=owner_id,
                    recovery_of_attempt_id=attempt_id,
                    token=token,
                )
                == attempt_id
            )

        reused = psycopg.connect(target_url, row_factory=dict_row)
        try:
            another_same_parent = _clone_parent(reused, fixture, fingerprint_value="same", now=now)
            set_project_scope(reused, project_id)
            with pytest.raises(DifyRecoveryBindingError, match="already consumed"):
                bind_dify_resubmission(
                    reused,
                    project_id=project_id,
                    new_parent_job_id=another_same_parent,
                    actor_id=owner_id,
                    recovery_of_attempt_id=attempt_id,
                    token=token,
                )
            reused.rollback()
        finally:
            reused.close()

        with pytest.raises(psycopg.errors.CheckViolation, match="already consumed"):
            _issue_token(catalog, project_id, attempt_id, owner_id)
        _assert_single_recovery_without_old_replay(
            target_url,
            fixture,
            recovered_parent_id=recovered_parent,
        )
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )


def _issue_token(
    catalog: PostgresWorkflowRuntimeCatalog,
    project_id: UUID,
    attempt_id: UUID,
    owner_id: UUID,
) -> str:
    return catalog.authorize_new_parent_after_unknown_outcome(
        project_id=project_id,
        attempt_id=attempt_id,
        authorized_by=owner_id,
        provider_outcome="not_found",
        provider_run_id=None,
        evidence_reference="dify-history://verified-not-found",
        reason="The provider history proves no completed output exists.",
    )


def _make_unknown_outcome_with_active_lease(
    database_url: str,
    fixture: dict[str, object],
    *,
    now: datetime,
) -> None:
    parent_id = _uuid(fixture["parent_job_id"])
    child_id = _uuid(fixture["child_job_id"])
    attempt_id = _uuid(fixture["business_attempt_id"])
    project_id = _uuid(fixture["project_id"])
    owner_id = _uuid(fixture["owner_id"])
    payload = _style_task_payload(parent_id, owner_id, "same")
    with psycopg.connect(database_url) as connection:
        connection.execute("SET LOCAL session_replication_role = replica")
        connection.execute(
            "DELETE FROM dify_workflow_execution_results WHERE attempt_id = %s",
            (attempt_id,),
        )
        connection.execute(
            """UPDATE dify_workflow_execution_attempts
               SET status = 'failed', dify_task_id = NULL, dify_run_id = NULL,
                   reported_workflow_id = NULL, output_hash = NULL,
                   error_classification = 'unknown_outcome',
                   error_code = 'dify_unknown_outcome',
                   error_message = 'response outcome is unknown', retryable = false,
                   finished_at = %s
               WHERE id = %s AND project_id = %s""",
            (now, attempt_id, project_id),
        )
        connection.execute(
            """UPDATE durable_jobs
               SET status = 'running', attempt_count = 1, lease_owner = 'recovery-test',
                   lease_token = %s, lease_expires_at = %s, fencing_generation = 1,
                   result_ref = NULL, completed_at = NULL, updated_at = %s
               WHERE id = %s AND project_id = %s""",
            (uuid4(), now + timedelta(minutes=10), now, child_id, project_id),
        )
        connection.execute(
            """UPDATE synthetic_lab_execution_tasks
               SET task_payload = %s, task_payload_hash = %s
               WHERE project_id = %s AND job_id = %s""",
            (Jsonb(payload), canonical_json_hash(payload), project_id, parent_id),
        )
        connection.execute("SET LOCAL session_replication_role = origin")


def _expire_child_lease(
    database_url: str,
    fixture: dict[str, object],
    *,
    now: datetime,
) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute("SET LOCAL session_replication_role = replica")
        connection.execute(
            """UPDATE durable_jobs SET lease_expires_at = %s, updated_at = %s
               WHERE id = %s AND project_id = %s""",
            (
                now - timedelta(seconds=1),
                now,
                _uuid(fixture["child_job_id"]),
                _uuid(fixture["project_id"]),
            ),
        )
        connection.execute("SET LOCAL session_replication_role = origin")


def _clone_parent(
    connection,
    fixture: dict[str, object],
    *,
    fingerprint_value: str,
    now: datetime,
) -> UUID:
    parent_id = uuid4()
    project_id = _uuid(fixture["project_id"])
    owner_id = _uuid(fixture["owner_id"])
    old_parent_id = _uuid(fixture["parent_job_id"])
    payload = _style_task_payload(parent_id, owner_id, fingerprint_value)
    metadata_payload = {"recovery_parent_id": str(parent_id)}
    connection.execute(
        """INSERT INTO durable_jobs(
               id, project_id, kind, status, input_hash, idempotency_key,
               max_attempts, attempt_count, next_run_at, fencing_generation,
               replay_nonce, created_at, updated_at
           ) VALUES (%s, %s, 'style.profile.build', 'queued', %s, %s,
                     3, 0, %s, 0, 0, %s, %s)""",
        (
            parent_id,
            project_id,
            canonical_json_hash(payload),
            f"style-recovery-parent:{parent_id}",
            now,
            now,
            now,
        ),
    )
    connection.execute(
        """INSERT INTO synthetic_lab_job_metadata(
               job_id, project_id, metadata_version, domain_job_kind,
               payload, payload_hash, fact_snapshot_id, fact_snapshot_hash,
               profile_version_id, profile_hash, prompt_release_id,
               prompt_release_hash, facts_current_approved, profile_frozen,
               prompt_frozen, created_at, updated_at
           )
           SELECT %s, project_id, metadata_version, domain_job_kind,
                  %s, %s, fact_snapshot_id, fact_snapshot_hash,
                  profile_version_id, profile_hash, prompt_release_id,
                  prompt_release_hash, facts_current_approved, profile_frozen,
                  prompt_frozen, %s, %s
           FROM synthetic_lab_job_metadata
           WHERE project_id = %s AND job_id = %s""",
        (
            parent_id,
            Jsonb(metadata_payload),
            canonical_json_hash(metadata_payload),
            now,
            now,
            project_id,
            old_parent_id,
        ),
    )
    connection.execute(
        """INSERT INTO synthetic_lab_execution_tasks(
               project_id, job_id, requested_by, execution_kind,
               expected_job_input_hash, task_input_hash, task_type,
               task_payload, task_payload_hash, staged_at
           ) VALUES (%s, %s, %s, 'style.profile.build', %s, %s,
                     'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildTask',
                     %s, %s, %s)""",
        (
            project_id,
            parent_id,
            owner_id,
            canonical_json_hash(payload),
            canonical_json_hash(payload),
            Jsonb(payload),
            canonical_json_hash(payload),
            now,
        ),
    )
    return parent_id


def _style_task_payload(parent_id: UUID, owner_id: UUID, value: str) -> dict[str, object]:
    return {
        "$type": "geo_core.synthetic_lab.execution_contracts.StyleProfileBuildTask",
        "fields": {
            "profile_key": value,
            "job_id": str(parent_id),
            "requested_by": str(owner_id),
        },
    }


def _assert_single_recovery_without_old_replay(
    database_url: str,
    fixture: dict[str, object],
    *,
    recovered_parent_id: UUID,
) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        row = connection.execute(
            """SELECT
                   (SELECT count(*) FROM dify_workflow_reconciliation_consumptions
                    WHERE project_id = %s AND attempt_id = %s) AS consumption_count,
                   (SELECT new_parent_job_id
                    FROM dify_workflow_reconciliation_consumptions
                    WHERE project_id = %s AND attempt_id = %s) AS recovered_parent_id,
                   (SELECT count(*) FROM dify_workflow_execution_attempts
                    WHERE project_id = %s AND job_id = %s
                      AND execution_kind = 'business') AS old_provider_attempts,
                   (SELECT attempt_count FROM durable_jobs
                    WHERE project_id = %s AND id = %s) AS old_parent_attempt_count,
                   (SELECT status FROM durable_jobs
                    WHERE project_id = %s AND id = %s) AS recovered_parent_status""",
            (
                _uuid(fixture["project_id"]),
                _uuid(fixture["business_attempt_id"]),
                _uuid(fixture["project_id"]),
                _uuid(fixture["business_attempt_id"]),
                _uuid(fixture["project_id"]),
                _uuid(fixture["child_job_id"]),
                _uuid(fixture["project_id"]),
                _uuid(fixture["parent_job_id"]),
                _uuid(fixture["project_id"]),
                recovered_parent_id,
            ),
        ).fetchone()
    assert row == {
        "consumption_count": 1,
        "recovered_parent_id": recovered_parent_id,
        "old_provider_attempts": 1,
        "old_parent_attempt_count": 1,
        "recovered_parent_status": "queued",
    }


def _uuid(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
