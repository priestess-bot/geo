"""Materialize generated Recommendation results as reviewable drafts.

Revision ID: 0118_rec_draft_materialize
Revises: 0117_knowledge_rag_replay_link
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0118_rec_draft_materialize"
down_revision = "0117_knowledge_rag_replay_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0118_rec_draft_materialize.sql"))


def downgrade() -> None:
    op.execute(_sql("0118_rec_draft_materialize.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
