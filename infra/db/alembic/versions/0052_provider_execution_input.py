"""Persist server-resolved Provider Sampling execution inputs."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0052_provider_execution_input"
down_revision = "0051_synthetic_parent_scope"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")


def upgrade() -> None:
    op.execute(_sql("0052_provider_execution_input.sql"))


def downgrade() -> None:
    op.execute(_sql("0052_provider_execution_input.down.sql"))
