"""Persist durable F027 project export requests and immutable artifacts.

Revision ID: 0020_project_exports
Revises: 0019_knowledge_question_sets
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0020_project_exports"
down_revision = "0019_knowledge_question_sets"
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
    _execute_file("0020_project_exports.sql")


def downgrade() -> None:
    _execute_file("0020_project_exports.down.sql")
