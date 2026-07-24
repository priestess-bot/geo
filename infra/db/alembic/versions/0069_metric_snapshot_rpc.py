"""Persist Workflow C semantic metric projections through a fenced Worker RPC."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0069_metric_snapshot_rpc"
down_revision = "0068_metric_parent_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0069_metric_snapshot_rpc.sql"))


def downgrade() -> None:
    op.execute(_sql("0069_metric_snapshot_rpc.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
