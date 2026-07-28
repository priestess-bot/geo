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

from geo_core.project_scope import set_project_scope
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_rule_type_signals_round_trip_through_real_postgres_producers() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_recommendation_type_{suffix}"
    target_url = _database_url(ADMIN_URL, database_name)
    app_login, password = f"geo_rec_type_{suffix}", uuid4().hex
    database_created = False
    role_created = False
    migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    migration.attributes["geo_database_url_override"] = target_url
    now = datetime.now(UTC).replace(microsecond=0)
    rule_id, alert_id = uuid4(), uuid4()
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        database_created = True
        command.upgrade(migration, "0099_style_profile_build_binding")

        with psycopg.connect(target_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(password)
                )
            )
            role_created = True
            seeded = seed_project(admin, suffix=f"recommendation-type-{suffix}")
            _seed_open_critical_rule(
                admin,
                project_id=seeded["project"],
                rule_id=rule_id,
                alert_id=alert_id,
                now=now,
            )

        command.upgrade(migration, "0100_recommendation_type_gate")
        app_url = login_url(target_url, user=app_login, password=password)
        _assert_rule_projection(
            app_url,
            project_id=seeded["project"],
            rule_id=rule_id,
            enriched=True,
        )

        command.downgrade(migration, "0099_style_profile_build_binding")
        _assert_rule_projection(
            app_url,
            project_id=seeded["project"],
            rule_id=rule_id,
            enriched=False,
        )

        command.upgrade(migration, "0100_recommendation_type_gate")
        _assert_rule_projection(
            app_url,
            project_id=seeded["project"],
            rule_id=rule_id,
            enriched=True,
        )
    finally:
        if database_created:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
                if role_created:
                    server.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login))
                    )


def _seed_open_critical_rule(
    connection,
    *,
    project_id,
    rule_id,
    alert_id,
    now: datetime,
) -> None:
    connection.execute(
        """INSERT INTO workflow_c_alert_rule_versions(
               id, project_id, rule_key, version, status, rule_hash, payload,
               created_by, created_at, aggregate_version
           ) VALUES (%s, %s, 'recommendation.critical_gap', 1, 'draft', %s,
                     %s::jsonb, 'rule-maker', %s, 1)""",
        (
            rule_id,
            project_id,
            "a" * 64,
            Jsonb(
                {
                    "kind": "threshold",
                    "severity": "critical",
                    "parameters": {
                        "schema_version": "alert-rule-threshold-v1",
                        "metric_key": "mention_rate",
                        "operator": "lt",
                        "threshold": "0.5",
                    },
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
            "Recommendation type gate integration fixture reviewed",
            project_id,
            rule_id,
        ),
    )
    connection.execute(
        """INSERT INTO workflow_c_alerts(
               id, project_id, rule_version_id, trigger_snapshot_hash, dedupe_key,
               severity, status, version, payload, opened_at, updated_at
           ) VALUES (%s, %s, %s, %s, %s, 'critical', 'open', 1,
                     '{}'::jsonb, %s, %s)""",
        (
            alert_id,
            project_id,
            rule_id,
            "b" * 64,
            "alert:" + "c" * 64,
            now,
            now,
        ),
    )


def _assert_rule_projection(
    database_url: str,
    *,
    project_id,
    rule_id,
    enriched: bool,
) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as app:
        set_project_scope(app, project_id)
        row = app.execute(
            "SELECT geo_resolve_recommendation_evidence(%s, 'rule', %s) AS value",
            (project_id, str(rule_id)),
        ).fetchone()
        privilege = app.execute(
            """SELECT has_function_privilege(
                   current_user,
                   'geo_resolve_recommendation_evidence(uuid,text,text)',
                   'EXECUTE'
               ) AS allowed"""
        ).fetchone()
    assert row is not None and privilege == {"allowed": True}
    value = row["value"]
    assert value["resource_id"] == str(rule_id)
    assert value["valid"] is True and value["active"] is True
    if enriched:
        assert value["rule_kind"] == "threshold"
        assert value["severity"] == "critical"
        assert value["trigger_status"] == "open"
    else:
        assert "rule_kind" not in value
        assert "severity" not in value
        assert "trigger_status" not in value


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
