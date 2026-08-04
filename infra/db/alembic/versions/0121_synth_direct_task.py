"""Admit direct Synthetic generation into the closed execution contract.

Revision ID: 0121_synth_direct_task
Revises: 0120_synthetic_direct_generation
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0121_synth_direct_task"
down_revision = "0120_synthetic_direct_generation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0121_synth_direct_task.sql"))


def downgrade() -> None:
    op.execute(_sql("0121_synth_direct_task.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
