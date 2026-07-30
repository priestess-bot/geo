"""Admit Browser Capture attempts as dedicated Durable Jobs.

Revision ID: 0108_browser_capture_jobs
Revises: 0107_browser_sampling_bridge
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0108_browser_capture_jobs"
down_revision = "0107_browser_sampling_bridge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0108_browser_capture_jobs.sql"))


def downgrade() -> None:
    op.execute(_sql("0108_browser_capture_jobs.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
