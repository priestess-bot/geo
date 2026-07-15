"""Add GitHub-backed engineering governance projections.

Revision ID: 0002_engineering_governance
Revises: 0001_geo_baseline
"""
from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0002_engineering_governance"
down_revision = "0001_geo_baseline"
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
    _execute_file("0002_engineering_governance.sql")


def downgrade() -> None:
    _execute_file("0002_engineering_governance.down.sql")
