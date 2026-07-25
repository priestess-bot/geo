"""Resolve Recommendation evidence through current Workflow C lineage."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0082_recommendation_evidence"
down_revision = "0081_surface_parser_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0082_recommendation_evidence.sql"))


def downgrade() -> None:
    op.execute(_sql("0082_recommendation_evidence.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
