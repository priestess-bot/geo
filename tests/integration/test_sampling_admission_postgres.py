from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyDecisionRequest,
    AdmissionPolicySubmitRequest,
    CreateAdmissionPolicyRequest,
)
from geo_api.workflow_c_sampling_postgres_policy import (
    PostgresWorkflowCSamplingPolicyControl,
)
from geo_core.project_scope import set_project_scope
from geo_core.sampling import SamplingConflict
from geo_core.sampling.postgres_admission import PostgresSamplingAdmissionRepository
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_sampling_admission_is_fenced_idempotent_and_project_scoped() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_sampling_admission_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_sampling_admission_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        alembic_command.upgrade(migration, "head")
        alembic_command.downgrade(migration, "0037_wfc_artifact_tombstone")
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            created_role = True
            first = seed_project(admin, suffix=f"sampling-admission-{suffix}-first")
            second = seed_project(admin, suffix=f"sampling-admission-{suffix}-second")
            _seed_runtime_option(admin, project_id=first["project"], marker="first")
            _seed_runtime_option(admin, project_id=second["project"], marker="second")

        app_url = login_url(database_url, user=app_login, password=app_password)
        now = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)
        repository = PostgresSamplingAdmissionRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row),
            clock=lambda: now,
        )
        control = PostgresWorkflowCSamplingPolicyControl(
            repository=repository,
            clock=lambda: now,
        )
        request = CreateAdmissionPolicyRequest(
            runtime_authorization_option_key="provider-au-v1",
            purpose="geo_measurement",
            valid_until=now + timedelta(days=7),
            quota_remaining=100,
            daily_task_limit=20,
            minimum_request_interval_seconds=1,
            max_concurrency=2,
        )

        created = control.create(
            project_id=first["project"],
            actor_id="maker-1",
            idempotency_key="admission:first",
            payload=request,
        )
        replayed_create = control.create(
            project_id=first["project"],
            actor_id="maker-1",
            idempotency_key="admission:first",
            payload=request,
        )
        assert created.record.status.value == "draft"
        assert created.record.aggregate_version == 1
        assert replayed_create.record == created.record

        with pytest.raises(SamplingConflict):
            control.create(
                project_id=first["project"],
                actor_id="other-maker",
                idempotency_key="admission:first",
                payload=request,
            )

        submitted = control.submit(
            project_id=first["project"],
            policy_id=created.record.id,
            actor_id="maker-1",
            idempotency_key="admission:first:submit",
            payload=AdmissionPolicySubmitRequest(expected_version=1),
        )
        replayed_submit = control.submit(
            project_id=first["project"],
            policy_id=created.record.id,
            actor_id="maker-1",
            idempotency_key="admission:first:submit",
            payload=AdmissionPolicySubmitRequest(expected_version=1),
        )
        assert submitted.record.status.value == "pending_review"
        assert submitted.record.aggregate_version == 2
        assert replayed_submit.record == submitted.record

        with pytest.raises(SamplingConflict):
            control.decide(
                project_id=first["project"],
                policy_id=created.record.id,
                actor_id="maker-1",
                idempotency_key="admission:first:invalid-approval",
                payload=AdmissionPolicyDecisionRequest(
                    expected_version=2, reason="maker cannot check"
                ),
                approved=True,
            )

        approved = control.decide(
            project_id=first["project"],
            policy_id=created.record.id,
            actor_id="checker-1",
            idempotency_key="admission:first:approve",
            payload=AdmissionPolicyDecisionRequest(
                expected_version=2, reason="authorization checked"
            ),
            approved=True,
        )
        assert approved.record.status.value == "approved"
        assert approved.effective_authorization_state.value == "approved"
        assert approved.record.aggregate_version == 3

        revoked = control.revoke(
            project_id=first["project"],
            policy_id=created.record.id,
            actor_id="checker-2",
            idempotency_key="admission:first:revoke",
            payload=AdmissionPolicyDecisionRequest(
                expected_version=3, reason="authorization withdrawn"
            ),
        )
        replayed_revoke = control.revoke(
            project_id=first["project"],
            policy_id=created.record.id,
            actor_id="checker-2",
            idempotency_key="admission:first:revoke",
            payload=AdmissionPolicyDecisionRequest(
                expected_version=3, reason="authorization withdrawn"
            ),
        )
        assert revoked.record.status.value == "revoked"
        assert replayed_revoke.record == revoked.record

        _assert_app_cannot_bypass_policy_commands(
            app_url,
            project_id=first["project"],
            policy_id=created.record.id,
        )
        _assert_scope_rejects_foreign_project(
            app_url,
            scoped_project_id=first["project"],
            foreign_project_id=second["project"],
        )
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
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))


def _seed_runtime_option(connection, *, project_id: UUID, marker: str) -> None:
    connection.execute(
        """INSERT INTO workflow_c_sampling_runtime_options(
               project_id, option_key, option_hash, display_name, platform,
               capture_method, adapter_release, location_control,
               location_evidence_hash, authorization_reference, allowed_purposes,
               status, frozen_at
           ) VALUES (
               %s, 'provider-au-v1', %s, %s, 'provider', 'provider_api',
               'provider-au-release-v1', 'country', %s, %s,
               %s::jsonb, 'approved', clock_timestamp()
           )""",
        (
            project_id,
            _hash(f"option:{marker}"),
            f"Provider AU {marker}",
            _hash(f"location:{marker}"),
            f"authorization:{marker}",
            Jsonb(["geo_measurement"]),
        ),
    )


def _assert_app_cannot_bypass_policy_commands(
    database_url: str, *, project_id: UUID, policy_id: UUID
) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        set_project_scope(connection, project_id)
        assert (
            _boolean(
                connection,
                "SELECT has_table_privilege(current_user, 'workflow_c_sampling_admission_policies', 'INSERT')",
            )
            is False
        )
        assert (
            _boolean(
                connection,
                "SELECT has_table_privilege(current_user, 'workflow_c_command_ledger', 'INSERT')",
            )
            is False
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """UPDATE workflow_c_sampling_admission_policies
                   SET status = 'approved' WHERE project_id = %s AND id = %s""",
                (project_id, policy_id),
            )
        connection.rollback()


def _assert_scope_rejects_foreign_project(
    database_url: str, *, scoped_project_id: UUID, foreign_project_id: UUID
) -> None:
    with psycopg.connect(database_url) as connection:
        set_project_scope(connection, scoped_project_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """SELECT * FROM geo_transition_workflow_c_sampling_admission_policy(
                       %s, %s, 1, %s, %s, 'submit', 'actor', NULL, clock_timestamp()
                   )""",
                (
                    foreign_project_id,
                    uuid4(),
                    _hash("foreign-idempotency"),
                    _hash("foreign-input"),
                ),
            )
        connection.rollback()


def _boolean(connection, query: str) -> bool:
    row = connection.execute(query).fetchone()
    if row is None:
        raise AssertionError("expected a row")
    value = row[0] if not isinstance(row, dict) else next(iter(row.values()))
    if not isinstance(value, bool):
        raise AssertionError("expected a boolean")
    return value


def _hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
