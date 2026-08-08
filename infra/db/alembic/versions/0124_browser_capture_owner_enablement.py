"""Allow one project owner to enable Browser Capture runtime configuration.

Revision ID: 0124_browser_owner_enable
Revises: 0123_question_semantic_dedup
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0124_browser_owner_enable"
down_revision = "0123_question_semantic_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0124_browser_owner_enable.sql"))


def downgrade() -> None:
    op.execute(_sql("0124_browser_owner_enable.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
