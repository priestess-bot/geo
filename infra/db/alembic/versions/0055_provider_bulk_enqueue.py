"""Make durable Provider Sampling bulk enqueue atomic and replayable."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0055_provider_bulk_enqueue"
down_revision = "0054_provider_attempt_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0055_provider_bulk_enqueue.sql"))


def downgrade() -> None:
    op.execute(_sql("0055_provider_bulk_enqueue.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
