"""Allow the API role to clone frozen Knowledge RAG specs for Job replay.

Revision ID: 0116_knowledge_rag_replay
Revises: 0115_external_operational_alerts
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0116_knowledge_rag_replay"
down_revision = "0115_external_operational_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0116_knowledge_rag_replay.sql"))


def downgrade() -> None:
    op.execute(_sql("0116_knowledge_rag_replay.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
