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

from tests.integration.placement_worker_support import login_url


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_app_role_reads_keyring_canaries_only_through_restricted_rpc() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_wfc_keyring_reader_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    login, password = f"geo_wfc_keyring_app_{suffix}", uuid4().hex
    created_database = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(login), sql.Literal(password)
                )
            )
            admin.execute(
                """INSERT INTO workflow_c_artifact_master_key_versions(
                       master_key_version, status, algorithm, canary_nonce,
                       canary_ciphertext, created_at, retired_at
                   ) VALUES (1, 'encrypt_decrypt', 'AES-256-GCM', %s, %s,
                             clock_timestamp(), NULL)""",
                (b"a" * 12, b"b" * 32),
            )
            assert admin.execute(
                """SELECT has_table_privilege(
                       'geo_app', 'workflow_c_artifact_master_key_versions', 'SELECT'
                   )"""
            ).fetchone() == (False,)
            admin.commit()

        with psycopg.connect(login_url(database_url, user=login, password=password)) as app:
            rows = app.execute(
                "SELECT * FROM geo_read_workflow_c_artifact_keyring_canaries()"
            ).fetchall()
            assert rows == [(1, "encrypt_decrypt", "AES-256-GCM", b"a" * 12, b"b" * 32, None)]
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                app.execute("SELECT * FROM workflow_c_artifact_master_key_versions").fetchall()
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
