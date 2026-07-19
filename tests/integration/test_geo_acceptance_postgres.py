from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from scripts.geo_acceptance import AcceptanceConfig, run_acceptance


APP_URL = os.getenv("GEO_ACCEPTANCE_TEST_APP_DATABASE_URL", "").strip()
WORKER_URL = os.getenv("GEO_ACCEPTANCE_TEST_WORKER_DATABASE_URL", "").strip()
ADMIN_URL = os.getenv("GEO_ACCEPTANCE_TEST_ADMIN_DATABASE_URL", "").strip()
ISOLATION_MARKER = os.getenv("GEO_ACCEPTANCE_TEST_ISOLATION_MARKER", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not APP_URL or not WORKER_URL or not ADMIN_URL or not ISOLATION_MARKER,
        reason=(
            "GEO_ACCEPTANCE_TEST_APP_DATABASE_URL, "
            "GEO_ACCEPTANCE_TEST_WORKER_DATABASE_URL and "
            "GEO_ACCEPTANCE_TEST_ADMIN_DATABASE_URL and "
            "GEO_ACCEPTANCE_TEST_ISOLATION_MARKER are required"
        ),
    ),
]


def test_inline_acceptance_refuses_unproven_marker_before_business_writes(
    tmp_path: Path,
) -> None:
    with psycopg.connect(ADMIN_URL) as connection:
        tenant_count = _scalar(connection.execute("SELECT count(*) FROM tenants"))
    wrong_marker = (
        "different-isolation-marker"
        if ISOLATION_MARKER != "different-isolation-marker"
        else "another-isolation-marker"
    )

    with pytest.raises(RuntimeError, match="do not inherit the expected isolation marker"):
        run_acceptance(
            AcceptanceConfig(
                app_database_url=APP_URL,
                worker_database_url=WORKER_URL,
                admin_database_url=ADMIN_URL,
                isolation_marker=wrong_marker,
                run_id=f"invalid-isolation-{uuid4().hex}",
                output_path=tmp_path / "must-not-exist.json",
            )
        )

    with psycopg.connect(ADMIN_URL) as connection:
        assert _scalar(connection.execute("SELECT count(*) FROM tenants")) == tenant_count
    assert not (tmp_path / "must-not-exist.json").exists()


def test_stable_geo_acceptance_closes_the_controlled_full_flow(tmp_path: Path) -> None:
    config = AcceptanceConfig(
        app_database_url=APP_URL,
        worker_database_url=WORKER_URL,
        admin_database_url=ADMIN_URL,
        isolation_marker=ISOLATION_MARKER,
        run_id=f"integration-{uuid4().hex}",
        output_path=tmp_path / "geo-acceptance.json",
    )
    result = run_acceptance(config)
    project = cast(dict[str, object], result["project"])
    project_id = UUID(str(project["project_id"]))
    tenant_id = UUID(str(project["tenant_id"]))
    try:
        assertions = cast(dict[str, object], result["assertions"])
        assert assertions["selected_channel_count"] == 9
        assert assertions["persistent_task_count"] == 9
        assert assertions["blocked_task_count"] == 8
        assert assertions["completed_task_count"] == 1
        assert assertions["export_created_publication"] is False
        assert assertions["claim_inventory_complete"] is True
        assert assertions["review_submitter_differs_from_reviewer"] is True
        assert assertions["isolated_scope_verified"] is True
        assert assertions["terminal_artifact_replay_count"] == 11
        assert assertions["duplicate_artifacts_created_by_terminal_replay"] == 0

        assert result["execution_mode"] == "inline_isolated"
        adapters = {
            str(item["purpose"]): item
            for item in cast(list[dict[str, object]], result["adapters"])
        }
        assert adapters["job_execution"]["adapter"] == "inline_postgres_dispatcher"
        assert adapters["worker_relay_topology"]["adapter"] == "not_exercised"
        fingerprint = cast(dict[str, object], result["environment_fingerprint"])
        assert len(str(fingerprint["sha256"])) == 64
        assert fingerprint["isolation_marker"] == ISOLATION_MARKER
        assert APP_URL not in str(fingerprint)
        assert WORKER_URL not in str(fingerprint)
        assert ADMIN_URL not in str(fingerprint)

        placement = cast(dict[str, object], result["placement"])
        generation_job_id = UUID(str(placement["generation_job_id"]))
        assert placement["prompt_binding_count"] == 9
        assert placement["scheduled_measurement_offsets"] == [28, 56, 84]
        assert placement["measurement_collection_task_status"] == "completed"
        assert [
            item["window"] for item in cast(list[dict[str, object]], placement["measurement_collection_tasks"])
        ] == ["t28", "t56", "t84"]
        assert all(
            item["status"] == "completed"
            for item in cast(list[dict[str, object]], placement["measurement_collection_tasks"])
        )
        assert len(str(placement["prompt_bundle_hash"])) == 64
        assert len(str(placement["package_content_hash"])) == 64

        projection = cast(dict[str, object], result["customer_projection"])
        assert projection["metric_count"] == 3
        assert projection["verified_url_count"] == 1
        assert projection["approved_report_count"] == 3
        assert cast(dict[str, object], result["boundaries"]) == {
            "external_publication_performed": False,
            "public_url_verification_mode": "controlled",
            "monitoring_data_mode": "controlled_acceptance",
            "controlled_simulation": True,
            "causal_claim": False,
            "production_worker_relay_topology_validated": False,
        }
        assert (tmp_path / "geo-acceptance.json").is_file()

        with psycopg.connect(ADMIN_URL) as connection:
            assert _scalar(connection.execute(
                "SELECT count(*) FROM placement_opportunities WHERE project_id = %s",
                (project_id,),
            )) == 9
            assert _scalar(connection.execute(
                "SELECT count(*) FROM publication_requests WHERE project_id = %s",
                (project_id,),
            )) == 1
            assert _scalar(connection.execute(
                "SELECT count(*) FROM placement_export_receipts WHERE project_id = %s",
                (project_id,),
            )) == 1
            assert _scalar(connection.execute(
                """SELECT array_agg(log.status ORDER BY log.call_number, log.created_at)
                   FROM model_call_logs AS log
                   JOIN generation_job_specs AS spec
                     ON spec.project_id = log.project_id AND spec.job_id = log.job_id
                   WHERE log.project_id = %s AND log.job_id = %s""",
                (project_id, generation_job_id),
            )) == ["reserved", "succeeded"]
            artifact_rows = connection.execute(
                """SELECT status, attempt_count
                   FROM artifact_finalize_outbox
                   WHERE project_id = %s""",
                (project_id,),
            ).fetchall()
            assert len(artifact_rows) == 11
            assert set(artifact_rows) == {("finalized", 1)}

            tenant_count = _scalar(connection.execute("SELECT count(*) FROM tenants"))
        with pytest.raises(RuntimeError, match="already has a persisted tenant scope"):
            run_acceptance(config)
        with psycopg.connect(ADMIN_URL) as connection:
            assert _scalar(connection.execute("SELECT count(*) FROM tenants")) == tenant_count
    finally:
        _cleanup(project_id=project_id, tenant_id=tenant_id)


def test_parallel_inline_runs_keep_tenant_project_and_artifacts_isolated(
    tmp_path: Path,
) -> None:
    configs = tuple(
        AcceptanceConfig(
            app_database_url=APP_URL,
            worker_database_url=WORKER_URL,
            admin_database_url=ADMIN_URL,
            isolation_marker=ISOLATION_MARKER,
            run_id=f"parallel-{uuid4().hex}",
            output_path=tmp_path / f"parallel-{index}.json",
        )
        for index in range(2)
    )
    results: list[dict[str, object]] = []
    scopes: list[tuple[UUID, UUID]] = []
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results.extend(executor.map(run_acceptance, configs))
        for result in results:
            project = cast(dict[str, object], result["project"])
            scopes.append(
                (UUID(str(project["project_id"])), UUID(str(project["tenant_id"])))
            )
            assert result["execution_mode"] == "inline_isolated"
        project_ids = [project_id for project_id, _ in scopes]
        assert len(set(project_ids)) == 2
        assert len({tenant_id for _, tenant_id in scopes}) == 2

        with psycopg.connect(ADMIN_URL) as connection:
            artifact_rows = connection.execute(
                """SELECT project_id, count(*)
                   FROM artifact_finalize_outbox
                   WHERE project_id = ANY(%s)
                   GROUP BY project_id""",
                (project_ids,),
            ).fetchall()
            artifact_counts = {
                UUID(str(project_id)): int(str(count))
                for project_id, count in artifact_rows
            }
        assert artifact_counts == {project_id: 11 for project_id in project_ids}
    finally:
        for project_id, tenant_id in scopes:
            _cleanup(project_id=project_id, tenant_id=tenant_id)


def _cleanup(*, project_id: UUID, tenant_id: UUID) -> None:
    with psycopg.connect(ADMIN_URL) as connection:
        identity_ids = [
            row[0]
            for row in connection.execute(
                "SELECT identity_id FROM project_memberships WHERE project_id = %s",
                (project_id,),
            ).fetchall()
        ]
        connection.execute("SET LOCAL session_replication_role = 'replica'")
        if identity_ids:
            connection.execute(
                "DELETE FROM customer_sessions WHERE identity_id = ANY(%s)",
                (identity_ids,),
            )
        project_tables = connection.execute(
            """SELECT DISTINCT columns.table_name
               FROM information_schema.columns AS columns
               JOIN information_schema.tables AS tables
                 ON tables.table_schema = columns.table_schema
                AND tables.table_name = columns.table_name
               WHERE columns.table_schema = 'public'
                 AND columns.column_name = 'project_id'
                 AND tables.table_type = 'BASE TABLE'"""
        ).fetchall()
        for (table_name,) in project_tables:
            connection.execute(
                sql.SQL("DELETE FROM {} WHERE project_id = %s").format(
                    sql.Identifier(table_name)
                ),
                (project_id,),
            )
        connection.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        if identity_ids:
            connection.execute("DELETE FROM identities WHERE id = ANY(%s)", (identity_ids,))
        connection.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        connection.execute("SET LOCAL session_replication_role = 'origin'")


def _scalar(cursor: Any) -> object:
    row = cursor.fetchone()
    assert row is not None
    return row[0]
