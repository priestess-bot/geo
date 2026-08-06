"""Align question semantic duplicate evidence with application classification.

Revision ID: 0123_question_semantic_dedup
Revises: 0122_question_coverage_pack
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0123_question_semantic_dedup"
down_revision = "0122_question_coverage_pack"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0123_question_semantic_dedup.sql"))


def downgrade() -> None:
    op.execute(_sql("0123_question_semantic_dedup.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
