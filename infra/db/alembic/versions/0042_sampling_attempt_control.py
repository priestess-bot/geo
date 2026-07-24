"""Fence first Provider Sampling Attempt admission and enqueue."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0042_sampling_attempt_control"
down_revision = "0041_sampling_run_control"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )


def upgrade() -> None:
    op.execute(_sql("0042_sampling_attempt_control.sql"))


def downgrade() -> None:
    op.execute(_sql("0042_sampling_attempt_control.down.sql"))
