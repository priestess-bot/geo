"""Freeze Synthetic child execution backend and exact Dify lineage.

Revision ID: 0098_synthetic_dify_lineage
Revises: 0097_dify_snapshot_fencing
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0098_synthetic_dify_lineage"
down_revision = "0097_dify_snapshot_fencing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0098_synthetic_dify_lineage.sql"))


def downgrade() -> None:
    op.execute(_sql("0098_synthetic_dify_lineage.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
