from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest
from sqlalchemy.exc import ProgrammingError

from geo_core.project_scope import set_project_scope
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_analytical_projections_allow_equal_hashes_without_cross_project_reads() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_analysis_scope_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    app_login, password = f"geo_analysis_scope_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    migration.attributes["geo_database_url_override"] = database_url
    now = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(password)
                )
            )
            created_role = True
            first = seed_project(admin, suffix=f"analysis-scope-{suffix}-first")
            second = seed_project(admin, suffix=f"analysis-scope-{suffix}-second")
            _insert_equal_hash_projections(
                admin,
                project_ids=(first["project"], second["project"]),
                now=now,
            )

        app_url = login_url(database_url, user=app_login, password=password)
        _assert_project_projection_view(
            app_url,
            project_id=first["project"],
            expected_project_id=first["project"],
        )
        _assert_project_projection_view(
            app_url,
            project_id=second["project"],
            expected_project_id=second["project"],
        )

        with pytest.raises(ProgrammingError, match="Project-scoped analytical hash identities exist"):
            command.downgrade(migration, "0058_wfc_spec_sensitive")
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


def _insert_equal_hash_projections(
    connection: psycopg.Connection,
    *,
    project_ids: tuple[UUID, UUID],
    now: datetime,
) -> None:
    snapshot_hash = _hash("same-semantic-snapshot")
    family_hash = _hash("same-comparison-family")
    report_hash = _hash("same-drift-report")
    source_hash, target_hash = _hash("drift-source"), _hash("drift-target")
    connection.execute("SET LOCAL session_replication_role = replica")
    for project_id in project_ids:
        connection.execute(
            """INSERT INTO workflow_c_semantic_metric_snapshots(
                   snapshot_hash, project_id, run_id, input_set_hash, metric_suite_hash,
                   source_stratum_hash, capture_method, evidence_status, warning_ratio,
                   test_only, synthetic, payload, computed_at
               ) VALUES (%s, %s, %s, %s, %s, %s, 'provider_api', 'complete', 0,
                         false, false, '{}'::jsonb, %s)""",
            (
                snapshot_hash,
                project_id,
                uuid4(),
                _hash("same-input-set"),
                _hash("same-metric-suite"),
                _hash("same-source-stratum"),
                now,
            ),
        )
        connection.execute(
            """INSERT INTO workflow_c_semantic_metric_results(
                   project_id, snapshot_hash, metric_key, metric_version, status, estimate,
                   interval_json, denominator, valid_count, invalid_count, missing_count,
                   judge_version_hash, rule_versions_hash, evidence_locators_json, payload
               ) VALUES (%s, %s, 'mention_rate', 'v1', 'complete', 0.5, '{}'::jsonb,
                         1, 1, 0, 0, NULL, %s, '[]'::jsonb, '{}'::jsonb)""",
            (project_id, snapshot_hash, _hash("same-rule-versions")),
        )
        connection.execute(
            """INSERT INTO workflow_c_comparison_families(
                   family_hash, project_id, protocol_hash, power_plan_hash,
                   bootstrap_method, bootstrap_iterations, correction_method,
                   simultaneous_interval_method, status, payload, computed_at
               ) VALUES (%s, %s, %s, %s, 'paired_bootstrap', 100,
                         'holm', 'newcombe', 'complete', '{}'::jsonb, %s)""",
            (
                family_hash,
                project_id,
                _hash("same-protocol"),
                _hash("same-power-plan"),
                now,
            ),
        )
        connection.execute(
            """INSERT INTO workflow_c_comparison_results(
                   project_id, family_hash, comparison_id, stratum_hash,
                   sampling_source_stratum_hash, conclusion, adjusted_p_value,
                   interval_json, payload
               ) VALUES (%s, %s, 'baseline-vs-candidate', %s, %s, 'equivalent',
                         0.5, '{}'::jsonb, '{}'::jsonb)""",
            (
                project_id,
                family_hash,
                _hash("same-comparison-stratum"),
                _hash("same-sampling-stratum"),
            ),
        )
        connection.execute(
            """INSERT INTO workflow_c_drift_reports(
                   report_hash, project_id, source_snapshot_hash, target_snapshot_hash,
                   status, payload, computed_at
               ) VALUES (%s, %s, %s, %s, 'complete', '{}'::jsonb, %s)""",
            (report_hash, project_id, source_hash, target_hash, now),
        )


def _assert_project_projection_view(
    app_url: str,
    *,
    project_id: UUID,
    expected_project_id: UUID,
) -> None:
    snapshot_hash = _hash("same-semantic-snapshot")
    family_hash = _hash("same-comparison-family")
    report_hash = _hash("same-drift-report")
    with psycopg.connect(app_url, row_factory=dict_row) as app:
        set_project_scope(app, project_id)
        assert _project_ids(
            app, "workflow_c_semantic_metric_snapshots", "snapshot_hash", snapshot_hash
        ) == {expected_project_id}
        assert _project_ids(
            app, "workflow_c_semantic_metric_results", "snapshot_hash", snapshot_hash
        ) == {expected_project_id}
        assert _project_ids(
            app, "workflow_c_comparison_families", "family_hash", family_hash
        ) == {expected_project_id}
        assert _project_ids(
            app, "workflow_c_comparison_results", "family_hash", family_hash
        ) == {expected_project_id}
        assert _project_ids(
            app, "workflow_c_drift_reports", "report_hash", report_hash
        ) == {expected_project_id}
        row = app.execute(
            "SELECT geo_resolve_recommendation_evidence(%s, 'metric_comparison', %s) AS value",
            (project_id, f"{family_hash}:baseline-vs-candidate"),
        ).fetchone()
        assert row is not None
        value = row["value"]
        assert isinstance(value, dict)
        assert value["project_id"] == str(expected_project_id)


def _project_ids(
    connection: psycopg.Connection,
    table: str,
    hash_column: str,
    hash_value: str,
) -> set[UUID]:
    rows = connection.execute(
        sql.SQL("SELECT project_id FROM {} WHERE {} = %s").format(
            sql.Identifier(table), sql.Identifier(hash_column)
        ),
        (hash_value,),
    ).fetchall()
    return {row["project_id"] for row in rows}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
