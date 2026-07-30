"""Suspend Browser Surface releases on parser or runtime drift.

Revision ID: 0114_browser_surface_drift
Revises: 0113_browser_egress_test
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0114_browser_surface_drift"
down_revision = "0113_browser_egress_test"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0114_browser_surface_drift.sql"))


def downgrade() -> None:
    op.execute(_sql("0114_browser_surface_drift.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
