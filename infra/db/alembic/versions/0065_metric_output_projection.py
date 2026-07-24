"""Persist validated Workflow C metric-child result projections."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0065_metric_output_projection"
down_revision = "0064_wfc_artifact_hold_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0065_metric_output_projection.sql"))


def downgrade() -> None:
    op.execute(_sql("0065_metric_output_projection.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
