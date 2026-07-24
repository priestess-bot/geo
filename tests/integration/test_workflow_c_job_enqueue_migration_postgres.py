from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
import pytest


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
FUNCTION_SIGNATURE = (
    "geo_enqueue_workflow_c_job_spec(uuid,text,text,jsonb,text,integer)"
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_workflow_c_job_enqueue_migration_downgrades_and_replays_its_permissions() -> None:
    database_name = f"geo_workflow_c_enqueue_migration_{uuid4().hex[:10]}"
    target_url = _database_url(ADMIN_URL, database_name)
    created_database = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url

        command.upgrade(migration, "head")
        _assert_0034_permissions(target_url, present=True)

        command.downgrade(migration, "0033_terminal_shape_guard")
        _assert_0034_permissions(target_url, present=False)

        command.upgrade(migration, "head")
        _assert_0034_permissions(target_url, present=True)
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )


def _assert_0034_permissions(database_url: str, *, present: bool) -> None:
    with psycopg.connect(database_url) as connection:
        exists = _boolean(
            connection,
            "SELECT to_regprocedure(%s) IS NOT NULL",
            (FUNCTION_SIGNATURE,),
        )
        can_insert = _boolean(
            connection,
            "SELECT has_table_privilege('geo_app', 'workflow_c_job_specs', 'INSERT')",
        )
        if present:
            can_execute = _boolean(
                connection,
                "SELECT has_function_privilege('geo_app', %s, 'EXECUTE')",
                (FUNCTION_SIGNATURE,),
            )
            assert exists is True
            assert can_execute is True
            assert can_insert is False
        else:
            assert exists is False
            assert can_insert is True


def _boolean(connection: Any, query: str, params: tuple[object, ...] = ()) -> bool:
    row = connection.execute(query, params).fetchone()
    if row is None or not isinstance(row[0], bool):
        raise AssertionError("expected a boolean PostgreSQL result")
    return row[0]


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
