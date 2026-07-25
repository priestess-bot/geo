"""Add one-way, auditable Prompt Release retirement."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0083_prompt_release_retirement"
down_revision = "0082_recommendation_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0083_prompt_release_retirement.sql"))


def downgrade() -> None:
    op.execute(_sql("0083_prompt_release_retirement.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
