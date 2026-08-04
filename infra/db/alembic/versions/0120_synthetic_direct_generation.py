"""Add direct Synthetic Lab channel-style command identity.

Revision ID: 0120_synthetic_direct_generation
Revises: 0119_question_model_identity
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0120_synthetic_direct_generation"
down_revision = "0119_question_model_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0120_synthetic_direct_generation.sql"))


def downgrade() -> None:
    op.execute(_sql("0120_synthetic_direct_generation.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
