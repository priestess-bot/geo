"""Add immutable external-data snapshots and independent approval lifecycle.

Revision ID: 0103_external_data_approval
Revises: 0102_connector_core
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0103_external_data_approval"
down_revision = "0102_connector_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0103_external_data_approval.sql"))


def downgrade() -> None:
    op.execute(_sql("0103_external_data_approval.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
