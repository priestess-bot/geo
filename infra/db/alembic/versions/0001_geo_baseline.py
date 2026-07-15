"""Create the fresh GEO modular-monolith database baseline.

Revision ID: 0001_geo_baseline
Revises: None
"""
from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0001_geo_baseline"
down_revision = None
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
    _execute_file("0001_geo_baseline.sql")


def downgrade() -> None:
    _execute_file("0001_geo_baseline.down.sql")
