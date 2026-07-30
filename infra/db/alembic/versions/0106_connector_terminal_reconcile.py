"""Reconcile Connector Runs from Durable Job retry and terminal state.

Revision ID: 0106_connector_reconcile
Revises: 0105_browser_capture_core
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0106_connector_reconcile"
down_revision = "0105_browser_capture_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0106_connector_reconcile.sql"))


def downgrade() -> None:
    op.execute(_sql("0106_connector_reconcile.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
