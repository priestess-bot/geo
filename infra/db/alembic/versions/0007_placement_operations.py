"""Close placement submission and measurement operations.

Revision ID: 0007_placement_operations
Revises: 0006_monitoring_lineage
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0007_placement_operations"
down_revision = "0006_monitoring_lineage"
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
    _execute_file("0007_placement_operations.sql")


def downgrade() -> None:
    _execute_file("0007_placement_operations.down.sql")
