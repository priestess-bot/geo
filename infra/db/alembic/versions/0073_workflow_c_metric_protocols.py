"""Add governed Workflow C metric protocols and immutable input manifests."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0073_wfc_metric_protocols"
down_revision = "0072_wfc_artifact_keyring_reader"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0073_wfc_metric_protocols.sql"))


def downgrade() -> None:
    op.execute(_sql("0073_wfc_metric_protocols.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
