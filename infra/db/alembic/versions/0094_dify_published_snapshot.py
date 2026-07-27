"""Persist the exact published Dify workflow used by an execution.

Revision ID: 0094_dify_published_snapshot
Revises: 0093_dify_workflow_runtime
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0094_dify_published_snapshot"
down_revision = "0093_dify_workflow_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0094_dify_published_snapshot.sql"))


def downgrade() -> None:
    op.execute(_sql("0094_dify_published_snapshot.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
