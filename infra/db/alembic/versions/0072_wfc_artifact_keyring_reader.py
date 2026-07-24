"""Expose a minimal keyring-canary reader to the restricted App role."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0072_wfc_artifact_keyring_reader"
down_revision = "0071_analysis_job_admission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0072_wfc_artifact_keyring_reader.sql"))


def downgrade() -> None:
    op.execute(_sql("0072_wfc_artifact_keyring_reader.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
