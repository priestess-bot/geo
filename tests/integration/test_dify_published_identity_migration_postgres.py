from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest
from sqlalchemy.exc import OperationalError

from geo_core.secrets import SecretVersionHandle
from geo_core.workflow_runtime import PostgresWorkflowRuntimeCatalog
from tests.integration.dify_release_migration_support import seed_legacy_dify_release
from tests.integration.placement_worker_support import seed_project
from tests.integration.test_dify_workflow_runtime_postgres import (
    _seed_frozen_prompt_and_secret,
)
from tests.integration.test_style_recommendation_dify_migration_postgres import _database_url


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_0101_backfill_truth_and_runtime_enrollment_downgrade_guard() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_dify_identity_{suffix}"
    target_url = _database_url(ADMIN_URL, database_name)
    database_created = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        database_created = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url
        command.upgrade(migration, "0100_recommendation_type_gate")

        with psycopg.connect(target_url) as admin:
            seeded = seed_project(admin, suffix=f"dify-identity-{suffix}")
            prompt, secret_id = _seed_frozen_prompt_and_secret(admin, seeded)
            admin.commit()
        secret = SecretVersionHandle(
            reference_id=secret_id,
            project_id=seeded["project"],
            purpose="workflow_runtime.dify",
            version=1,
        )
        legacy_id = seed_legacy_dify_release(
            target_url,
            project_id=seeded["project"],
            purpose="knowledge.question_generation",
            prompt_program_id=prompt["program"],
            prompt_release_id=prompt["release"],
            dify_app_id="identity-app",
            dify_workflow_id="identity-workflow",
            dsl_hash="1" * 64,
            configured_model="deepseek-chat",
            model_provider="langgenius/deepseek/deepseek",
            api_secret_handle=secret,
            created_by=seeded["owner"],
        )
        with psycopg.connect(target_url) as admin:
            admin.execute(
                """INSERT INTO dify_workflow_published_snapshots (
                       id, project_id, release_id, purpose, dify_app_id,
                       dify_workflow_id, workflow_hash, snapshot_hash,
                       prompt_nodes, input_variables, graph_nodes,
                       published_at, observed_at
                   ) VALUES (%s, %s, %s, 'knowledge.question_generation',
                             'identity-app', 'identity-workflow', %s, %s,
                             '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, %s, %s)""",
                (
                    uuid4(),
                    seeded["project"],
                    legacy_id,
                    "a" * 64,
                    "b" * 64,
                    datetime.now(UTC),
                    datetime.now(UTC),
                ),
            )
            admin.commit()

        command.upgrade(migration, "0101_dify_published_identity")
        with psycopg.connect(target_url, row_factory=dict_row) as admin:
            legacy = admin.execute(
                """SELECT registered_workflow_hash, registered_snapshot_hash,
                          registered_identity_source
                   FROM dify_workflow_releases WHERE id = %s""",
                (legacy_id,),
            ).fetchone()
        assert legacy == {
            "registered_workflow_hash": None,
            "registered_snapshot_hash": None,
            "registered_identity_source": None,
        }

        command.downgrade(migration, "0100_recommendation_type_gate")
        command.upgrade(migration, "0101_dify_published_identity")
        runtime_id = PostgresWorkflowRuntimeCatalog(target_url).register_release(
            project_id=seeded["project"],
            purpose="knowledge.question_generation",
            prompt_program_id=prompt["program"],
            prompt_release_id=prompt["release"],
            dify_app_id="identity-app",
            dify_workflow_id="identity-workflow",
            dsl_hash="1" * 64,
            registered_workflow_hash="c" * 64,
            registered_snapshot_hash="d" * 64,
            configured_model="deepseek-chat",
            model_provider="langgenius/deepseek/deepseek",
            api_secret_handle=secret,
            created_by=seeded["owner"],
        )
        with psycopg.connect(target_url, row_factory=dict_row) as admin:
            runtime = admin.execute(
                """SELECT registered_workflow_hash, registered_snapshot_hash,
                          registered_identity_source
                   FROM dify_workflow_releases WHERE id = %s""",
                (runtime_id,),
            ).fetchone()
        assert runtime == {
            "registered_workflow_hash": "c" * 64,
            "registered_snapshot_hash": "d" * 64,
            "registered_identity_source": "runtime_enrollment",
        }
        with pytest.raises(
            OperationalError,
            match="runtime-enrolled Dify Releases",
        ):
            command.downgrade(migration, "0100_recommendation_type_gate")
        with psycopg.connect(target_url) as admin:
            assert admin.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "0101_dify_published_identity",
            )
    finally:
        if database_created:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
