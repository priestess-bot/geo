"""Allow frozen legacy Prompt Simulation jobs to finish artifact finalization.

Revision ID: 0026_legacy_simulation
Revises: 0025_monitoring_source_guard
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0026_legacy_simulation"
down_revision = "0025_monitoring_source_guard"
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
    _execute_file("0026_legacy_simulation.sql")


def downgrade() -> None:
    _execute_file("0026_legacy_simulation.down.sql")
