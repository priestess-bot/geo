"""Freeze the exact observation membership of each new metric snapshot.

Revision ID: 0018_metric_membership
Revises: 0017_knowledge_rag_graph
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0018_metric_membership"
down_revision = "0017_knowledge_rag_graph"
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
    _execute_file("0018_metric_membership.sql")


def downgrade() -> None:
    _execute_file("0018_metric_membership.down.sql")
