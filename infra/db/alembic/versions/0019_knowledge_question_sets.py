"""Add governed QuestionSet generation, protocol binding, and GEO simulation lineage.

Revision ID: 0019_knowledge_question_sets
Revises: 0018_metric_membership
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0019_knowledge_question_sets"
down_revision = "0018_metric_membership"
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
    _execute_file("0019_knowledge_question_sets.sql")


def downgrade() -> None:
    _execute_file("0019_knowledge_question_sets.down.sql")
