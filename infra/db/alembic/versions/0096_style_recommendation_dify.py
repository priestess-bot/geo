"""Pin Style Profile and Recommendation Dify execution lineage.

Revision ID: 0096_style_recommendation_dify
Revises: 0095_synthetic_dify_closed_loop
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0096_style_recommendation_dify"
down_revision = "0095_synthetic_dify_closed_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0096_style_recommendation_dify.sql"))


def downgrade() -> None:
    op.execute(_sql("0096_style_recommendation_dify.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
