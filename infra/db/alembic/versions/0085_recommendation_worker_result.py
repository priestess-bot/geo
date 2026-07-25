"""Allow the restricted Recommendation worker to finalize result projections."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0085_recommendation_worker_res"
down_revision = "0084_recommendation_stale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0085_recommendation_worker_res.sql"))


def downgrade() -> None:
    op.execute(_sql("0085_recommendation_worker_res.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
