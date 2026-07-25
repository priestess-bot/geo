"""Persist scoped idempotency receipts for Workflow C report commands."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0087_wfc_report_receipts"
down_revision = "0086_recommendation_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0087_wfc_report_receipts.sql"))


def downgrade() -> None:
    op.execute(_sql("0087_wfc_report_receipts.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
