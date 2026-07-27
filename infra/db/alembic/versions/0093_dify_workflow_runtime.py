"""Add immutable Dify workflow releases, bindings and execution lineage.

Revision ID: 0093_dify_workflow_runtime
Revises: 0092_prompt_workspace_kinds
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0093_dify_workflow_runtime"
down_revision = "0092_prompt_workspace_kinds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0093_dify_workflow_runtime.sql"))


def downgrade() -> None:
    op.execute(_sql("0093_dify_workflow_runtime.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
