from __future__ import annotations

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

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not APP_URL or not WORKER_URL or not ADMIN_URL,
        reason=(
            "GEO_ACCEPTANCE_TEST_APP_DATABASE_URL, "
            "GEO_ACCEPTANCE_TEST_WORKER_DATABASE_URL and "
            "GEO_ACCEPTANCE_TEST_ADMIN_DATABASE_URL are required"
        ),
    ),
]


def test_stable_geo_acceptance_closes_the_controlled_full_flow(tmp_path: Path) -> None:
    result = run_acceptance(
        AcceptanceConfig(
            app_database_url=APP_URL,
            worker_database_url=WORKER_URL,
            run_id=f"integration-{uuid4().hex}",
            output_path=tmp_path / "geo-acceptance.json",
        )
    )
    project = cast(dict[str, object], result["project"])
    project_id = UUID(str(project["project_id"]))
    tenant_id = UUID(str(project["tenant_id"]))
    try:
        assertions = cast(dict[str, object], result["assertions"])
        assert assertions["selected_channel_count"] == 9
        assert assertions["persistent_task_count"] == 9
        assert assertions["blocked_task_count"] == 8
        assert assertions["approved_task_count"] == 1
        assert assertions["export_created_publication"] is False
        assert assertions["claim_inventory_complete"] is True
        assert assertions["review_submitter_differs_from_reviewer"] is True

        placement = cast(dict[str, object], result["placement"])
        assert placement["prompt_binding_count"] == 9
        assert placement["scheduled_measurement_offsets"] == [28, 56, 84]
        assert len(str(placement["prompt_bundle_hash"])) == 64
        assert len(str(placement["package_content_hash"])) == 64

        projection = cast(dict[str, object], result["customer_projection"])
        assert projection["metric_count"] == 2
        assert projection["verified_url_count"] == 1
        assert projection["approved_report_count"] == 1
        assert cast(dict[str, object], result["boundaries"]) == {
            "external_publication_performed": False,
            "public_url_verification_mode": "controlled",
            "monitoring_data_mode": "controlled_acceptance",
            "causal_claim": False,
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
                """SELECT count(*) FROM model_call_logs
                   WHERE project_id = %s AND status = 'succeeded'""",
                (project_id,),
            )) == 1
    finally:
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
            """SELECT table_name FROM information_schema.columns
               WHERE table_schema = 'public' AND column_name = 'project_id'"""
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
