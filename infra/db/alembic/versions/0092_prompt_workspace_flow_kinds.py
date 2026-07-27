"""Allow the four independent Prompt workspace flow kinds.

Revision ID: 0092_prompt_workspace_kinds
Revises: 0091_mgw_worker_admit
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0092_prompt_workspace_kinds"
down_revision = "0091_mgw_worker_admit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0092_prompt_workspace_kinds.sql"))


def downgrade() -> None:
    op.execute(_sql("0092_prompt_workspace_kinds.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
