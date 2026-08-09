"""Allow revised rejected duplicates to re-enter QuestionSet review.

Revision ID: 0129_question_repair
Revises: 0128_connector_test_scopes
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0129_question_repair"
down_revision = "0128_connector_test_scopes"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )


def upgrade() -> None:
    op.execute(_sql("0129_question_repair.sql"))


def downgrade() -> None:
    op.execute(_sql("0129_question_repair.down.sql"))
