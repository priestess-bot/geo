"""Fence Workflow C Sampling Run reservation and Task materialization."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0041_sampling_run_control"
down_revision = "0040_sampling_suite_control"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )


def upgrade() -> None:
    op.execute(_sql("0041_sampling_run_control.sql"))


def downgrade() -> None:
    op.execute(_sql("0041_sampling_run_control.down.sql"))
