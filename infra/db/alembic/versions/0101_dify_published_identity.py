"""Freeze trusted published Dify graph identity in every new GEO release.

Revision ID: 0101_dify_published_identity
Revises: 0100_recommendation_type_gate
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0101_dify_published_identity"
down_revision = "0100_recommendation_type_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0101_dify_published_identity.sql"))


def downgrade() -> None:
    op.execute(_sql("0101_dify_published_identity.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
