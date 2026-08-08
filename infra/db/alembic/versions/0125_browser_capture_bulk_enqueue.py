"""Add atomic bulk enqueue for automated consumer-surface capture.

Revision ID: 0125_browser_bulk_enqueue
Revises: 0124_browser_owner_enable
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0125_browser_bulk_enqueue"
down_revision = "0124_browser_owner_enable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0125_browser_bulk_enqueue.sql"))


def downgrade() -> None:
    op.execute(_sql("0125_browser_bulk_enqueue.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
