"""Add governed Workflow C comparison and drift protocols."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0076_wfc_stat_protocols"
down_revision = "0075_wfc_manual_attempt_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0076_wfc_stat_protocols.sql"))


def downgrade() -> None:
    op.execute(_sql("0076_wfc_stat_protocols.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
