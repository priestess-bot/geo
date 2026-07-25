"""Admit lease-owned Synthetic Corpus finalization tasks and results."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0080_synthetic_corpus_execution"
down_revision = "0079_synth_profile_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0080_synthetic_corpus_execution.sql"))


def downgrade() -> None:
    op.execute(_sql("0080_synthetic_corpus_execution.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
