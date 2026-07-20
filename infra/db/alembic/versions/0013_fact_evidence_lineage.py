"""Add relational Fact-to-Evidence lineage and fail-closed promotion guards.

Revision ID: 0013_fact_evidence_lineage
Revises: 0012_campaign_prompt_context
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0013_fact_evidence_lineage"
down_revision = "0012_campaign_prompt_context"
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
    _execute_file("0013_fact_evidence_lineage.sql")


def downgrade() -> None:
    _execute_file("0013_fact_evidence_lineage.down.sql")
