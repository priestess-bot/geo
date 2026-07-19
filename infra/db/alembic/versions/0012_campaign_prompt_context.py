"""Add exact Campaign ancestry and Opportunity-owned Prompt bindings.

Revision ID: 0012_campaign_prompt_context
Revises: 0011_runtime_health
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0012_campaign_prompt_context"
down_revision = "0011_runtime_health"
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
    _execute_file("0012_campaign_prompt_context.sql")


def downgrade() -> None:
    _execute_file("0012_campaign_prompt_context.down.sql")
