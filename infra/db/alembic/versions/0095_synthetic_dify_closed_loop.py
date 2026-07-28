"""Persist replayable Dify results and admit synthetic Dify children.

Revision ID: 0095_synthetic_dify_closed_loop
Revises: 0094_dify_published_snapshot
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0095_synthetic_dify_closed_loop"
down_revision = "0094_dify_published_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0095_synthetic_dify_closed_loop.sql"))


def downgrade() -> None:
    op.execute(_sql("0095_synthetic_dify_closed_loop.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
