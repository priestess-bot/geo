"""Atomically admit encrypted Metric Judge child batches from one parent lease."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0066_metric_parent_admission"
down_revision = "0065_metric_output_projection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0066_metric_parent_admission.sql"))


def downgrade() -> None:
    op.execute(_sql("0066_metric_parent_admission.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
