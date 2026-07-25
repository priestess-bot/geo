"""Persist text-free consumer-surface parser summaries."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0081_surface_parser_results"
down_revision = "0080_synthetic_corpus_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0081_surface_parser_results.sql"))


def downgrade() -> None:
    op.execute(_sql("0081_surface_parser_results.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
