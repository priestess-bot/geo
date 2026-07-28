"""Bind Style Profile review to one exact completed build result.

Revision ID: 0099_style_profile_build_binding
Revises: 0098_synthetic_dify_lineage
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0099_style_profile_build_binding"
down_revision = "0098_synthetic_dify_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0099_style_profile_build_binding.sql"))


def downgrade() -> None:
    op.execute(_sql("0099_style_profile_build_binding.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
