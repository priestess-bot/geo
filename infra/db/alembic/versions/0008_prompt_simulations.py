"""Add isolated, non-publishable prompt simulations.

Revision ID: 0008_prompt_simulations
Revises: 0007_placement_operations
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0008_prompt_simulations"
down_revision = "0007_placement_operations"
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
    _execute_file("0008_prompt_simulations.sql")


def downgrade() -> None:
    _execute_file("0008_prompt_simulations.down.sql")
