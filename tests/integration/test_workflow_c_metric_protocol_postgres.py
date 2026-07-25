from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest
from urllib.parse import urlsplit, urlunsplit

from geo_core.project_scope import set_project_scope
from geo_core.workflow_c_analysis_admission import (
    MetricProtocolStatus,
    new_metric_protocol,
)
from geo_core.workflow_c_analysis_protocols import (
    PostgresWorkflowCMetricProtocolError,
    PostgresWorkflowCMetricProtocolRepository,
    WorkflowCMetricProtocolNotFound,
)
from tests.integration.placement_worker_support import login_url, seed_project
from tests.workflow_c_analysis_test_support import metric_protocol_definition_fixture


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_metric_protocol_is_idempotent_maker_checked_and_project_scoped() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_metric_protocol_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_metric_protocol_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            created_role = True
            first = seed_project(admin, suffix=f"metric-protocol-{suffix}-first")
            second = seed_project(admin, suffix=f"metric-protocol-{suffix}-second")

        app_url = login_url(database_url, user=app_login, password=app_password)
        now = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
        repository = PostgresWorkflowCMetricProtocolRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row),
            clock=lambda: now,
        )
        protocol = new_metric_protocol(
            project_id=first["project"],
            definition=metric_protocol_definition_fixture(),
            actor_id="metric-maker",
            idempotency_key="metric-protocol-v1",
            occurred_at=now,
        )

        created = repository.create(protocol, idempotency_key="metric-protocol-v1")
        replayed = repository.create(protocol, idempotency_key="metric-protocol-v1")
        assert created == replayed
        assert repository.get(project_id=first["project"], protocol_id=protocol.id) == created
        assert repository.list(project_id=first["project"]) == (created,)

        submitted = repository.transition(
            project_id=first["project"],
            protocol_id=protocol.id,
            expected_aggregate_version=1,
            target_status=MetricProtocolStatus.IN_REVIEW,
            actor_id="metric-maker",
            idempotency_key="metric-protocol-v1:submit",
            occurred_at=now + timedelta(minutes=1),
        )
        with pytest.raises(PostgresWorkflowCMetricProtocolError):
            repository.transition(
                project_id=first["project"],
                protocol_id=protocol.id,
                expected_aggregate_version=2,
                target_status=MetricProtocolStatus.APPROVED,
                actor_id="metric-maker",
                reason="self approval is forbidden",
                idempotency_key="metric-protocol-v1:self-approve",
                occurred_at=now + timedelta(minutes=2),
            )
        approved = repository.transition(
            project_id=first["project"],
            protocol_id=protocol.id,
            expected_aggregate_version=submitted.aggregate_version,
            target_status=MetricProtocolStatus.APPROVED,
            actor_id="metric-checker",
            reason="fixed contract and regression evidence checked",
            idempotency_key="metric-protocol-v1:approve",
            occurred_at=now + timedelta(minutes=2),
        )
        replayed_approval = repository.transition(
            project_id=first["project"],
            protocol_id=protocol.id,
            expected_aggregate_version=submitted.aggregate_version,
            target_status=MetricProtocolStatus.APPROVED,
            actor_id="metric-checker",
            reason="fixed contract and regression evidence checked",
            idempotency_key="metric-protocol-v1:approve",
            occurred_at=now + timedelta(minutes=2),
        )
        assert approved == replayed_approval
        assert approved.status is MetricProtocolStatus.APPROVED

        with pytest.raises(WorkflowCMetricProtocolNotFound):
            repository.get(project_id=second["project"], protocol_id=protocol.id)
        _assert_direct_write_is_denied(
            app_url, project_id=first["project"], protocol_id=protocol.id
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


def _assert_direct_write_is_denied(
    database_url: str, *, project_id: UUID, protocol_id: UUID
) -> None:
    with psycopg.connect(database_url) as connection:
        set_project_scope(connection, project_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """UPDATE workflow_c_metric_protocol_versions
                   SET status = 'retired' WHERE project_id = %s AND id = %s""",
                (project_id, protocol_id),
            )


def _database_url(admin_url: str, database_name: str) -> str:
    parts = urlsplit(admin_url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database_name}", parts.query, ""))
