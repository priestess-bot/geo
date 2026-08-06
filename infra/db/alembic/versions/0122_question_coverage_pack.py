"""Add complete question coverage packs and resumable batch evidence.

Revision ID: 0122_question_coverage_pack
Revises: 0121_synth_direct_task
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0122_question_coverage_pack"
down_revision = "0121_synth_direct_task"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0122_question_coverage_pack.sql"))


def downgrade() -> None:
    op.execute(_sql("0122_question_coverage_pack.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
