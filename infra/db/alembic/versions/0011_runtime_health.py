"""Persist runtime heartbeats and expose safe worker health findings.

Revision ID: 0011_runtime_health
Revises: 0010_campaign_destinations
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0011_runtime_health"
down_revision = "0010_campaign_destinations"
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
    _execute_file("0011_runtime_health.sql")


def downgrade() -> None:
    _execute_file("0011_runtime_health.down.sql")
