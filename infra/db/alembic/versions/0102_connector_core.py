"""Add the project-scoped Connector Core truth model.

Revision ID: 0102_connector_core
Revises: 0101_dify_published_identity
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0102_connector_core"
down_revision = "0101_dify_published_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0102_connector_core.sql"))


def downgrade() -> None:
    op.execute(_sql("0102_connector_core.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
