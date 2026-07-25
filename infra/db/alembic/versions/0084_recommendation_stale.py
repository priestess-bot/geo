"""Make Recommendation staleness follow Fact lifecycle state."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0084_recommendation_stale"
down_revision = "0083_prompt_release_retirement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0084_recommendation_stale.sql"))


def downgrade() -> None:
    op.execute(_sql("0084_recommendation_stale.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
