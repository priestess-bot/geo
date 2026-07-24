"""Allow a fenced synthetic-retention lease to be reclaimed after expiry."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0048_synthetic_retention_reclaim"
down_revision = "0047_sampling_manual_import"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")


def upgrade() -> None:
    op.execute(_sql("0048_synthetic_retention_reclaim.sql"))


def downgrade() -> None:
    op.execute(_sql("0048_synthetic_retention_reclaim.down.sql"))
