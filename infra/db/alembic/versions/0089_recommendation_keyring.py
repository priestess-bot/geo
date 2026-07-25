"""Let the governed Worker register Recommendation artifact key canaries.

Revision ID: 0089_recommendation_keyring
Revises: 0088_worker_keyring_sync
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0089_recommendation_keyring"
down_revision = "0088_worker_keyring_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0089_recommendation_keyring.sql"))


def downgrade() -> None:
    op.execute(_sql("0089_recommendation_keyring.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
