"""Add explicit lineage for replayed Knowledge RAG Job specs.

Revision ID: 0117_knowledge_rag_replay_link
Revises: 0116_knowledge_rag_replay
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0117_knowledge_rag_replay_link"
down_revision = "0116_knowledge_rag_replay"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0117_knowledge_rag_replay_link.sql"))


def downgrade() -> None:
    op.execute(_sql("0117_knowledge_rag_replay_link.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
