"""Permit guarded Model Gateway admission writes from the Worker.

Revision ID: 0091_mgw_worker_admit
Revises: 0090_prompt_workspace
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0091_mgw_worker_admit"
down_revision = "0090_prompt_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0091_mgw_worker_admit.sql"))


def downgrade() -> None:
    op.execute(_sql("0091_mgw_worker_admit.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
