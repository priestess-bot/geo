"""Project external operations into versioned Workflow C alert inputs.

Revision ID: 0115_external_operational_alerts
Revises: 0114_browser_surface_drift
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0115_external_operational_alerts"
down_revision = "0114_browser_surface_drift"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0115_external_operational_alerts.sql"))


def downgrade() -> None:
    op.execute(_sql("0115_external_operational_alerts.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
