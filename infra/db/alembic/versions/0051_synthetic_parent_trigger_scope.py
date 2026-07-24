"""Avoid applying Synthetic scope guards to unrelated Durable Jobs."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0051_synthetic_parent_scope"
down_revision = "0050_wfc_retention_lock"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")


def upgrade() -> None:
    op.execute(_sql("0051_synthetic_parent_scope.sql"))


def downgrade() -> None:
    op.execute(_sql("0051_synthetic_parent_scope.down.sql"))
