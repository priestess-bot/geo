"""Atomically admit the encrypted Arbiter after Metric Judge disagreement."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0067_metric_arbiter_admission"
down_revision = "0066_metric_parent_admission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0067_metric_arbiter_admission.sql"))


def downgrade() -> None:
    op.execute(_sql("0067_metric_arbiter_admission.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
