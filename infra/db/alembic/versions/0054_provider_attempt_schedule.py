"""Preserve requested-not-before at the Provider Sampling RPC boundary."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0054_provider_attempt_schedule"
down_revision = "0053_provider_exec_enforce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0054_provider_attempt_schedule.sql"))


def downgrade() -> None:
    op.execute(_sql("0054_provider_attempt_schedule.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
