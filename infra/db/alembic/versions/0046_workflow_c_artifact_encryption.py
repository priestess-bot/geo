"""Align Workflow C artifact encryption metadata with the independent DEK envelope."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0046_wfc_artifact_encryption"
down_revision = "0045_sampling_terminal_reconcile"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")


def upgrade() -> None:
    op.execute(_sql("0046_wfc_artifact_encryption.sql"))


def downgrade() -> None:
    op.execute(_sql("0046_wfc_artifact_encryption.down.sql"))
