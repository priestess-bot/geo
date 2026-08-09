"""Count successful question revisions in frozen QuestionSet inventory.

Revision ID: 0127_question_set_dedup
Revises: 0126_sampling_question_selection
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0127_question_set_dedup"
down_revision = "0126_sampling_question_selection"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )


def upgrade() -> None:
    op.execute(_sql("0127_question_set_dedup.sql"))


def downgrade() -> None:
    op.execute(_sql("0127_question_set_dedup.down.sql"))
