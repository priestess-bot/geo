"""Add the consent-based local attribution ledger.

Revision ID: 0104_local_attribution
Revises: 0103_external_data_approval
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0104_local_attribution"
down_revision = "0103_external_data_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0104_local_attribution.sql"))


def downgrade() -> None:
    op.execute(_sql("0104_local_attribution.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
