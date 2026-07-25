"""Govern alert rules and enforce report maker-checker approval."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0077_wfc_alert_report_api"
down_revision = "0076_wfc_stat_protocols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0077_wfc_alert_report_api.sql"))


def downgrade() -> None:
    op.execute(_sql("0077_wfc_alert_report_api.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
