"""Reconcile unhandled Provider Sampling Durable Job terminal states."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0045_sampling_terminal_reconcile"
down_revision = "0044_sampling_cancel"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )


def upgrade() -> None:
    op.execute(_sql("0045_sampling_terminal_reconcile.sql"))


def downgrade() -> None:
    op.execute(_sql("0045_sampling_terminal_reconcile.down.sql"))
