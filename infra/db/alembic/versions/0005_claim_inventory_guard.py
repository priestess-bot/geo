"""Require a persisted claim inventory before package approval.

Revision ID: 0005_claim_inventory_guard
Revises: 0004_monitoring_observations
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0005_claim_inventory_guard"
down_revision = "0004_monitoring_observations"
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
    _execute_file("0005_claim_inventory_guard.sql")


def downgrade() -> None:
    _execute_file("0005_claim_inventory_guard.down.sql")
