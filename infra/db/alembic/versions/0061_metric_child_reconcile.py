"""Reconcile Metric child aggregates from Durable Job terminal state."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0061_metric_child_reconcile"
down_revision = "0060_metric_rpc_aggregate_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0061_metric_child_reconcile.sql"))


def downgrade() -> None:
    op.execute(_sql("0061_metric_child_reconcile.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
