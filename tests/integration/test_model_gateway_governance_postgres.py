from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
import pytest

from geo_core.model_gateway.contracts import ModelPolicy
from geo_core.model_gateway.postgres import build_model_gateway_persistence
from geo_core.project_scope import set_project_scope
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_model_gateway_governance_round_trip_rls_and_direct_write_guards() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_model_governance_{suffix}"
    test_admin_url = _database_url(ADMIN_URL, database_name)
    app_login, password = f"geo_model_governance_{suffix}", uuid4().hex
    role_created = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = test_admin_url
        alembic_command.upgrade(migration, "head")
        alembic_command.downgrade(migration, "0028_secret_store")
        alembic_command.upgrade(migration, "head")

        with psycopg.connect(test_admin_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(password)
                )
            )
            role_created = True
            first = seed_project(admin, suffix=f"model-governance-{suffix}-a")
            second = seed_project(admin, suffix=f"model-governance-{suffix}-b")

        app_url = login_url(test_admin_url, user=app_login, password=password)
        persistence = build_model_gateway_persistence(app_url)
        assert persistence is not None
        policy = ModelPolicy(
            allowed_providers=frozenset({"openai"}),
            allowed_adapter_release_ids=frozenset({"openai-governance-v1"}),
            policy_version_id=uuid4(),
            maximum_paid_calls=2,
            maximum_concurrent_calls=1,
        )
        now = datetime.now(UTC)
        persistence.register_project_policy(
            project_id=first["project"],
            policy=policy,
            version=1,
            previous_version_id=None,
            created_by=first["reviewer"],
            created_at=now,
        )
        assert policy.policy_version_id is not None
        assert policy.policy_version_hash is not None

        with psycopg.connect(app_url) as connection:
            set_project_scope(connection, second["project"])
            assert connection.execute(
                "SELECT count(*) FROM model_gateway_project_policy_versions"
            ).fetchone()[0] == 0

        with psycopg.connect(app_url) as connection:
            set_project_scope(connection, first["project"])
            with pytest.raises(psycopg.Error):
                connection.execute("INSERT INTO model_gateway_runtime_manifests DEFAULT VALUES")
            connection.rollback()
            set_project_scope(connection, first["project"])
            with pytest.raises(psycopg.Error):
                connection.execute(
                    """UPDATE model_gateway_job_admissions
                       SET lease_token = gen_random_uuid() WHERE false"""
                )
            connection.rollback()

            set_project_scope(connection, first["project"])
            with pytest.raises(psycopg.Error, match="invalid Model Gateway runtime manifest"):
                connection.execute(
                    """SELECT geo_register_model_gateway_runtime_manifest(
                           %s, %s, %s, 2, %s, %s, %s, 1,
                           %s, %s, %s, %s, %s, %s
                       )""",
                    (
                        uuid4(),
                        first["project"],
                        "a" * 64,
                        policy.policy_version_id,
                        policy.policy_version_hash,
                        "a" * 64,
                        first["owner"],
                        now,
                        first["owner"],
                        now,
                        "s3://geo-evidence/runtime-manifest.json",
                        "b" * 64,
                    ),
                )
            connection.rollback()

            set_project_scope(connection, first["project"])
            with pytest.raises(psycopg.Error):
                connection.execute(
                    """SELECT geo_register_model_gateway_runtime_manifest(
                           %s, %s, %s, 2, %s, %s, %s, 1,
                           %s, %s, %s, %s, %s, %s
                       )""",
                    (
                        uuid4(),
                        first["project"],
                        "c" * 64,
                        policy.policy_version_id,
                        policy.policy_version_hash,
                        "c" * 64,
                        first["owner"],
                        now,
                        first["reviewer"],
                        now,
                        "postgresql://user:password@db/evidence",
                        "d" * 64,
                    ),
                )
            connection.rollback()

        with psycopg.connect(test_admin_url) as admin:
            assert admin.execute(
                """SELECT has_table_privilege(
                           'geo_worker',
                           'model_gateway_job_admissions',
                           'INSERT'
                       )"""
            ).fetchone()[0] is True
            assert admin.execute(
                """SELECT has_table_privilege(
                           'geo_readonly',
                           'model_gateway_terminal_events',
                           'SELECT'
                       )"""
            ).fetchone()[0] is False
            assert admin.execute(
                """SELECT has_column_privilege(
                           'geo_app', 'model_gateway_job_admissions',
                           'lease_token', 'UPDATE'
                       )"""
            ).fetchone()[0] is False
    finally:
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


def _database_url(database_url: str, database_name: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(parsed._replace(path=f"/{database_name}"))
