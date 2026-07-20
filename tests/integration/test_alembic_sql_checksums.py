from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest
from sqlalchemy.engine import URL

from infra.db.alembic.checksums import MigrationChecksumError


ROOT = Path(__file__).resolve().parents[2]
ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_URL,
        reason="GEO_ACCESS_TEST_ADMIN_DATABASE_URL is required",
    ),
]


def test_alembic_external_sql_checksum_ledger_fails_closed_and_tracks_down_up() -> None:
    database_name = f"geo_checksum_{uuid4().hex[:12]}"
    admin_parameters = conninfo_to_dict(ADMIN_URL)
    maintenance_parameters = {**admin_parameters, "dbname": "postgres"}
    database_parameters = {**admin_parameters, "dbname": database_name}
    database_url = make_conninfo(**database_parameters)
    sqlalchemy_url = URL.create(
        "postgresql+psycopg",
        username=admin_parameters.get("user"),
        password=admin_parameters.get("password"),
        host=admin_parameters.get("host"),
        port=int(admin_parameters["port"]) if admin_parameters.get("port") else None,
        database=database_name,
    ).render_as_string(hide_password=False)
    with psycopg.connect(make_conninfo(**maintenance_parameters), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        with tempfile.TemporaryDirectory(prefix="geo-alembic-checksum-") as directory:
            script_root = Path(directory) / "alembic"
            shutil.copytree(ROOT / "infra/db/alembic", script_root)
            configuration = Config(ROOT / "alembic.ini")
            configuration.set_main_option("script_location", str(script_root))
            configuration.attributes["geo_database_url_override"] = sqlalchemy_url
            script = ScriptDirectory.from_config(configuration)
            expected_revisions = [
                str(revision.revision) for revision in reversed(list(script.walk_revisions()))
            ]

            command.upgrade(configuration, "head")
            with psycopg.connect(database_url) as connection:
                revisions = connection.execute(
                    "SELECT revision FROM alembic_sql_checksum_ledger ORDER BY revision"
                ).fetchall()
            assert [row[0] for row in revisions] == expected_revisions

            changed = script_root / "sql/0001_geo_baseline.sql"
            original = changed.read_bytes()
            changed.write_bytes(original + b"\n-- prohibited post-apply change\n")
            with pytest.raises(MigrationChecksumError, match="checksum drift"):
                command.upgrade(configuration, "head")
            changed.write_bytes(original)

            command.downgrade(configuration, "0005_claim_inventory_guard")
            with psycopg.connect(database_url) as connection:
                revisions = connection.execute(
                    "SELECT revision FROM alembic_sql_checksum_ledger ORDER BY revision"
                ).fetchall()
            downgrade_revision = "0005_claim_inventory_guard"
            assert [row[0] for row in revisions] == expected_revisions[
                : expected_revisions.index(downgrade_revision) + 1
            ]
            command.upgrade(configuration, "head")
            assert script.get_heads() == [expected_revisions[-1]]
            with psycopg.connect(database_url) as connection:
                assert connection.execute(
                    "SELECT count(*) FROM alembic_sql_checksum_ledger"
                ).fetchone()[0] == len(expected_revisions)
    finally:
        with psycopg.connect(make_conninfo(**maintenance_parameters), autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )
