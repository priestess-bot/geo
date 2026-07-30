"""Bridge approved Browser resources into Sampling admission.

Revision ID: 0107_browser_sampling_bridge
Revises: 0106_connector_reconcile
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0107_browser_sampling_bridge"
down_revision = "0106_connector_reconcile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0107_browser_sampling_bridge.sql"))


def downgrade() -> None:
    op.execute(_sql("0107_browser_sampling_bridge.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
