"""Add the governed consumer-surface Browser Capture truth model.

Revision ID: 0105_browser_capture_core
Revises: 0104_local_attribution
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0105_browser_capture_core"
down_revision = "0104_local_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0105_browser_capture_core.sql"))


def downgrade() -> None:
    op.execute(_sql("0105_browser_capture_core.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
