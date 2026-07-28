"""Pin published Dify graphs and fence terminal execution writes.

Revision ID: 0097_dify_snapshot_fencing
Revises: 0096_style_recommendation_dify
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0097_dify_snapshot_fencing"
down_revision = "0096_style_recommendation_dify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0097_dify_snapshot_fencing.sql"))


def downgrade() -> None:
    op.execute(_sql("0097_dify_snapshot_fencing.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
