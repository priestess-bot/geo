"""Fence Workflow C comparison and drift projection persistence."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0070_analysis_projection_rpc"
down_revision = "0069_metric_snapshot_rpc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0070_analysis_projection_rpc.sql"))


def downgrade() -> None:
    op.execute(_sql("0070_analysis_projection_rpc.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
