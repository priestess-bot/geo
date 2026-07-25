"""Admit Workflow C semantic v2 jobs from immutable manifests."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0074_wfc_semantic_job_v2"
down_revision = "0073_wfc_metric_protocols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0074_wfc_semantic_job_v2.sql"))


def downgrade() -> None:
    op.execute(_sql("0074_wfc_semantic_job_v2.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
