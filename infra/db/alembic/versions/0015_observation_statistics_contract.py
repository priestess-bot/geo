"""Add versioned observation statistics and minimum repeat thresholds.

Revision ID: 0015_observation_statistics_v2
Revises: 0014_observation_source_contract
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0015_observation_statistics_v2"
down_revision = "0014_observation_source_contract"
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
    _execute_file("0015_observation_statistics_v2.sql")


def downgrade() -> None:
    _execute_file("0015_observation_statistics_v2.down.sql")
