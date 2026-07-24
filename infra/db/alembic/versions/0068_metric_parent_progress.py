"""Expose fenced Metric-parent progress through restricted Worker RPCs."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0068_metric_parent_progress"
down_revision = "0067_metric_arbiter_admission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0068_metric_parent_progress.sql"))


def downgrade() -> None:
    op.execute(_sql("0068_metric_parent_progress.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
