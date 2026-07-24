"""Fence Provider Sampling cancellation and unused reservation release."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0044_sampling_cancel"
down_revision = "0043_sampling_attempt_claim"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )


def upgrade() -> None:
    op.execute(_sql("0044_sampling_cancel.sql"))


def downgrade() -> None:
    op.execute(_sql("0044_sampling_cancel.down.sql"))
