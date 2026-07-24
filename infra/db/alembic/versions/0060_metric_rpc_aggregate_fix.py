"""Disambiguate Workflow C metric RPC aggregate version updates."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0060_metric_rpc_aggregate_fix"
down_revision = "0059_analysis_project_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0060_metric_rpc_aggregate_fix.sql"))


def downgrade() -> None:
    op.execute(_sql("0060_metric_rpc_aggregate_fix.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
