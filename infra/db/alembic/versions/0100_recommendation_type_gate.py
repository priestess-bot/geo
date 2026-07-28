"""Project producer conclusions and alert state into Recommendation evidence.

Revision ID: 0100_recommendation_type_gate
Revises: 0099_style_profile_build_binding
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0100_recommendation_type_gate"
down_revision = "0099_style_profile_build_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0100_recommendation_type_gate.sql"))


def downgrade() -> None:
    op.execute(_sql("0100_recommendation_type_gate.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
