"""Persist an explicit ten-question Sampling Suite pilot selection.

Revision ID: 0126_sampling_question_selection
Revises: 0125_browser_bulk_enqueue
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0126_sampling_question_selection"
down_revision = "0125_browser_bulk_enqueue"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )


def upgrade() -> None:
    op.execute(_sql("0126_sampling_question_selection.sql"))


def downgrade() -> None:
    op.execute(_sql("0126_sampling_question_selection.down.sql"))
