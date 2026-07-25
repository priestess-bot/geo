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

from geo_core.alerts import (
    AlertConflict,
    AlertEvidenceReference,
    AlertRuleKind,
    AlertRuleVersion,
    AlertScope,
    AlertSeverity,
    AlertTriggerSnapshot,
    open_alert,
)
from geo_core.alerts.postgres_lifecycle import PostgresWorkflowCAlertRepository
from geo_core.alerts.postgres_operation_values import rule_value
from geo_core.project_scope import set_project_scope
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_alert_dispositions_are_fenced_idempotent_and_durable() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_alert_control_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_alert_control_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    now = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        alembic_command.upgrade(migration, "head")
        alembic_command.downgrade(migration, "0038_sampling_admission_control")
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            created_role = True
            first = seed_project(admin, suffix=f"alert-control-{suffix}-first")
            second = seed_project(admin, suffix=f"alert-control-{suffix}-second")
            alert_id = _seed_alert(
                admin,
                project_id=first["project"],
                marker="first",
                now=now,
            )

        app_url = login_url(database_url, user=app_login, password=app_password)
        repository = PostgresWorkflowCAlertRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row),
            clock=lambda: now,
        )

        acknowledged = repository.transition(
            project_id=first["project"],
            alert_id=alert_id,
            expected_version=1,
            operation="acknowledge",
            actor_id="operator-1",
            reason="investigating",
            command_key="alert:acknowledge:first",
        )
        assert acknowledged.replayed is False
        assert acknowledged.alert.status.value == "acknowledged"
        assert acknowledged.alert.version == 2
        assert len(acknowledged.notification_commands) == 3
        assert {item.channel.value for item in acknowledged.notification_commands} == {
            "admin_inbox",
            "local_smtp",
            "internal_webhook",
        }

        replayed = repository.transition(
            project_id=first["project"],
            alert_id=alert_id,
            expected_version=1,
            operation="acknowledge",
            actor_id="operator-1",
            reason="investigating",
            command_key="alert:acknowledge:first",
        )
        assert replayed.replayed is True
        assert replayed.alert == acknowledged.alert
        assert replayed.notification_commands == ()

        suppressed = repository.transition(
            project_id=first["project"],
            alert_id=alert_id,
            expected_version=2,
            operation="suppress",
            actor_id="operator-1",
            reason="planned maintenance",
            command_key="alert:suppress:first",
            occurred_at=now + timedelta(minutes=1),
            suppressed_until=now + timedelta(hours=1),
        )
        assert suppressed.alert.status.value == "suppressed"
        assert suppressed.alert.version == 3
        assert suppressed.alert.suppressed_until == now + timedelta(hours=1)
        assert len(repository.notifications(project_id=first["project"], alert_id=alert_id)) == 6

        with pytest.raises(AlertConflict):
            repository.transition(
                project_id=first["project"],
                alert_id=alert_id,
                expected_version=3,
                operation="suppress",
                actor_id="other-operator",
                reason="different input",
                command_key="alert:suppress:first",
                occurred_at=now + timedelta(minutes=1),
                suppressed_until=now + timedelta(hours=1),
            )

        with psycopg.connect(database_url, row_factory=dict_row) as admin:
            assert _count(
                admin,
                "workflow_c_alert_dispositions",
                first["project"],
            ) == 2
            assert _count(admin, "workflow_c_alert_notifications", first["project"]) == 6
            assert _count_kind(
                admin,
                first["project"],
                "workflow_c.alert.notify",
            ) == 6
            assert _count_topic(
                admin,
                first["project"],
                "workflow_c.alert.notify",
            ) == 6

        _assert_app_cannot_bypass_alert_commands(
            app_url,
            project_id=first["project"],
            alert_id=alert_id,
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


def _seed_alert(connection, *, project_id: UUID, marker: str, now: datetime) -> UUID:
    set_project_scope(connection, project_id)
    rule = AlertRuleVersion(
        id=uuid4(),
        project_id=project_id,
        rule_key=f"recommendation-share-{marker}",
        version=1,
        kind=AlertRuleKind.THRESHOLD,
        severity=AlertSeverity.WARNING,
        parameters={
            "schema_version": "alert-rule-threshold-v1",
            "metric_key": "recommendation_share",
            "operator": "lt",
            "threshold": "0.5",
        },
        frozen_by="rule-maker",
        frozen_at=now - timedelta(minutes=2),
    )
    scope = AlertScope(
        project_id=project_id,
        resource_kind="monitoring_report",
        resource_key=f"report:{marker}",
        dimensions=(("surface", "perplexity"),),
    )
    trigger = AlertTriggerSnapshot(
        values={"observed_value": "0.3", "metric_key": "recommendation_share"},
        captured_at=now - timedelta(minutes=1),
    )
    alert = open_alert(
        alert_id=uuid4(),
        rule_version=rule,
        scope=scope,
        trigger_snapshot=trigger,
        evidence=(
            AlertEvidenceReference(
                kind="metric_snapshot",
                resource_id=f"snapshot:{marker}",
                version="semantic-metrics-v1",
                sha256="a" * 64,
                locator="results[0]",
            ),
        ),
        opened_at=now,
    )
    connection.execute(
        """INSERT INTO workflow_c_alert_rule_versions(
               id, project_id, rule_key, version, status, rule_hash, payload,
               created_by, created_at, aggregate_version
           ) VALUES (%s, %s, %s, %s, 'draft', %s, %s::jsonb,
                     'rule-maker', %s, 1)""",
        (
            rule.id,
            project_id,
            rule.rule_key,
            rule.version,
            rule.rule_hash,
            Jsonb(
                {
                    "kind": rule.kind.value,
                    "severity": rule.severity.value,
                    "parameters": dict(rule.parameters),
                }
            ),
            now - timedelta(minutes=2),
        ),
    )
    connection.execute(
        """UPDATE workflow_c_alert_rule_versions
              SET status = 'approved', approved_by = 'rule-checker',
                  approved_at = %s, decision_reason = %s, aggregate_version = 2
            WHERE project_id = %s AND id = %s""",
        (
            now - timedelta(minutes=1),
            "fixed alert-control fixture reviewed",
            project_id,
            rule.id,
        ),
    )
    payload = {
        "schema_version": "workflow-c-alert-v1",
        "rule": rule_value(rule),
        "scope": scope.canonical_value() | {"dimensions": dict(scope.dimensions)},
        "trigger_snapshot": {
            "values": dict(trigger.values),
            "captured_at": trigger.captured_at.isoformat(),
            "snapshot_hash": trigger.snapshot_hash,
        },
        "evidence": [item.canonical_value() for item in alert.evidence],
    }
    connection.execute(
        """INSERT INTO workflow_c_alerts(
               id, project_id, rule_version_id, trigger_snapshot_hash, dedupe_key,
               severity, status, version, payload, opened_at, updated_at
           ) VALUES (%s, %s, %s, %s, %s, %s, 'open', 1, %s::jsonb, %s, %s)""",
        (
            alert.id,
            project_id,
            rule.id,
            trigger.snapshot_hash,
            alert.dedupe_key,
            alert.severity.value,
            Jsonb(payload),
            now,
            now,
        ),
    )
    connection.commit()
    return alert.id


def _assert_app_cannot_bypass_alert_commands(
    database_url: str, *, project_id: UUID, alert_id: UUID
) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        set_project_scope(connection, project_id)
        assert _boolean(
            connection,
            "SELECT has_table_privilege(current_user, 'workflow_c_alerts', 'UPDATE')",
        ) is False
        assert _boolean(
            connection,
            "SELECT has_table_privilege(current_user, 'workflow_c_alert_dispositions', 'INSERT')",
        ) is False
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """UPDATE workflow_c_alerts
                   SET status = 'resolved' WHERE project_id = %s AND id = %s""",
                (project_id, alert_id),
            )
        connection.rollback()


def _assert_scope_rejects_foreign_project(
    database_url: str, *, scoped_project_id: UUID, foreign_project_id: UUID
) -> None:
    with psycopg.connect(database_url) as connection:
        set_project_scope(connection, scoped_project_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """SELECT * FROM geo_transition_workflow_c_alert(
                       %s, %s, 1, 'alert:foreign', %s, %s::jsonb,
                       'acknowledge', 'operator', 'reason', clock_timestamp(), NULL, %s::jsonb
                   )""",
                (
                    foreign_project_id,
                    uuid4(),
                    "a" * 64,
                    Jsonb(
                        {
                            "actor_id": "operator",
                            "disposition": "acknowledged",
                            "reason": "reason",
                            "suppressed_until": None,
                        }
                    ),
                    Jsonb([]),
                ),
            )
        connection.rollback()


def _count(connection, table: str, project_id: UUID) -> int:
    row = connection.execute(
        sql.SQL("SELECT count(*) FROM {} WHERE project_id = %s").format(sql.Identifier(table)),
        (project_id,),
    ).fetchone()
    return _scalar_count(row)


def _count_kind(connection, project_id: UUID, kind: str) -> int:
    row = connection.execute(
        "SELECT count(*) FROM durable_jobs WHERE project_id = %s AND kind = %s",
        (project_id, kind),
    ).fetchone()
    return _scalar_count(row)


def _count_topic(connection, project_id: UUID, topic: str) -> int:
    row = connection.execute(
        "SELECT count(*) FROM broker_outbox WHERE project_id = %s AND topic = %s",
        (project_id, topic),
    ).fetchone()
    return _scalar_count(row)


def _scalar_count(row: object) -> int:
    if isinstance(row, dict):
        return int(next(iter(row.values())))
    if isinstance(row, tuple):
        return int(row[0])
    raise AssertionError("expected a count row")


def _boolean(connection, query: str) -> bool:
    row = connection.execute(query).fetchone()
    value = row[0] if not isinstance(row, dict) else next(iter(row.values()))
    if not isinstance(value, bool):
        raise AssertionError("expected a boolean")
    return value


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
