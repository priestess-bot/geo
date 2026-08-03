"""Persist the actual model identity for question generation results.

Revision ID: 0119_question_model_identity
Revises: 0118_rec_draft_materialize
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0119_question_model_identity"
down_revision = "0118_rec_draft_materialize"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0119_question_model_identity.sql"))


def downgrade() -> None:
    op.execute(_sql("0119_question_model_identity.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
