"""Validate comparison and drift commands at the generic admission boundary."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0071_analysis_job_admission"
down_revision = "0070_analysis_projection_rpc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0071_analysis_job_admission.sql"))


def downgrade() -> None:
    op.execute(_sql("0071_analysis_job_admission.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
