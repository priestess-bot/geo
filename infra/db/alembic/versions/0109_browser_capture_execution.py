"""Fence Browser Capture execution, retries, and Observation completion.

Revision ID: 0109_browser_capture_execution
Revises: 0108_browser_capture_jobs
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0109_browser_capture_execution"
down_revision = "0108_browser_capture_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0109_browser_capture_execution.sql"))


def downgrade() -> None:
    op.execute(_sql("0109_browser_capture_execution.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
