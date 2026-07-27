"""Add editable Prompt workspace drafts and single-operator publish support.

Revision ID: 0090_prompt_workspace
Revises: 0089_recommendation_keyring
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0090_prompt_workspace"
down_revision = "0089_recommendation_keyring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0090_prompt_workspace.sql"))


def downgrade() -> None:
    op.execute(_sql("0090_prompt_workspace.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
