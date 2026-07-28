from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
import pytest


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_0095_downgrade_restores_the_exact_0094_schema_contract() -> None:
    database_name = f"geo_synthetic_dify_migration_{uuid4().hex[:10]}"
    target_url = _database_url(ADMIN_URL, database_name)
    created_database = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url

        command.upgrade(migration, "0094_dify_published_snapshot")
        before = _schema_contract(target_url)

        command.upgrade(migration, "0095_synthetic_dify_closed_loop")
        command.downgrade(migration, "0094_dify_published_snapshot")

        assert _schema_contract(target_url) == before
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )


def _schema_contract(database_url: str) -> tuple[str, str | None, tuple[tuple[str, str], ...]]:
    with psycopg.connect(database_url) as connection:
        function_definition = connection.execute(
            """SELECT pg_get_functiondef(
                   'geo_assert_synthetic_model_call_child_job_change()'::regprocedure
               )"""
        ).fetchone()
        view_comment = connection.execute(
            """SELECT obj_description(
                   'synthetic_lab_model_call_child_status'::regclass, 'pg_class'
               )"""
        ).fetchone()
        constraints = connection.execute(
            """SELECT constraint_name, pg_get_constraintdef(oid, true)
               FROM (
                   SELECT constraint_value.conname AS constraint_name,
                          constraint_value.oid
                   FROM pg_constraint AS constraint_value
                   WHERE constraint_value.conname IN (
                       'dify_published_snapshots_project_key',
                       'dify_published_snapshots_identity_key',
                       'dify_workflow_attempts_snapshot_fkey'
                   )
               ) AS selected
               ORDER BY constraint_name"""
        ).fetchall()
    assert function_definition is not None
    assert view_comment is not None
    assert len(constraints) == 3
    return (
        str(function_definition[0]),
        str(view_comment[0]) if view_comment[0] is not None else None,
        tuple((str(name), str(definition)) for name, definition in constraints),
    )


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
