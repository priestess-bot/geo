"""Persist exact Provider Attempt lineage for Sampling Run cancellation replay."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0056_sampling_cancel_lineage"
down_revision = "0055_provider_bulk_enqueue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0056_sampling_cancel_lineage.sql"))


def downgrade() -> None:
    op.execute(_sql("0056_sampling_cancel_lineage.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
