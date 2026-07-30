"""Publish attribution snapshots through the external report lifecycle.

Revision ID: 0110_attribution_external_report
Revises: 0109_browser_capture_execution
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0110_attribution_external_report"
down_revision = "0109_browser_capture_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0110_attribution_external_report.sql"))


def downgrade() -> None:
    op.execute(_sql("0110_attribution_external_report.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
