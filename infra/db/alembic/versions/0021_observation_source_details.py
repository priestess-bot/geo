"""Make OTHER platform and surface details part of exact source strata.

Revision ID: 0021_observation_source_details
Revises: 0020_project_exports
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0021_observation_source_details"
down_revision = "0020_project_exports"
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
    _execute_file("0021_observation_source_details.sql")


def downgrade() -> None:
    _execute_file("0021_observation_source_details.down.sql")
