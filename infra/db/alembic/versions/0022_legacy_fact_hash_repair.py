"""Repair legacy Fact hashes produced from lower-cased statements.

Revision ID: 0022_legacy_fact_hash_repair
Revises: 0021_observation_source_details
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0022_legacy_fact_hash_repair"
down_revision = "0021_observation_source_details"
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _execute_file(name: str) -> None:
    sql = (_SQL_DIR / name).read_text(encoding="utf-8")
    bind = op.get_bind()
    if hasattr(bind, "exec_driver_sql"):
        bind.exec_driver_sql(sql)
    else:
        op.execute(sql)


def upgrade() -> None:
    _execute_file("0022_legacy_fact_hash_repair.sql")


def downgrade() -> None:
    _execute_file("0022_legacy_fact_hash_repair.down.sql")
