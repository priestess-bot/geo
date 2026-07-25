"""Add bounded producer-owned summaries for Recommendation generation."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0086_recommendation_summaries"
down_revision = "0085_recommendation_worker_res"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0086_recommendation_summaries.sql"))


def downgrade() -> None:
    op.execute(_sql("0086_recommendation_summaries.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
