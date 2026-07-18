"""Allow every campaign to create a task for the same destination.

Revision ID: 0010_campaign_destinations
Revises: 0009_knowledge_pipeline
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0010_campaign_destinations"
down_revision = "0009_knowledge_pipeline"
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
    _execute_file("0010_campaign_destinations.sql")


def downgrade() -> None:
    _execute_file("0010_campaign_destinations.down.sql")
