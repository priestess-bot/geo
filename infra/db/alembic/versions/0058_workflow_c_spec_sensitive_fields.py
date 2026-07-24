"""Reject expanded credential-like keys from Workflow C immutable Job specs."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0058_wfc_spec_sensitive"
down_revision = "0057_provider_exec_retirement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0058_wfc_spec_sensitive.sql"))


def downgrade() -> None:
    op.execute(_sql("0058_wfc_spec_sensitive.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
