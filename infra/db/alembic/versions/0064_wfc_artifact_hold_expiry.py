"""Add expiring, re-approved legal holds for Workflow C artifacts."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0064_wfc_artifact_hold_expiry"
down_revision = "0063_wfc_artifact_write_grant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0064_wfc_artifact_hold_expiry.sql"))


def downgrade() -> None:
    op.execute(_sql("0064_wfc_artifact_hold_expiry.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
