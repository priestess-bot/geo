"""Allow the governed Worker to verify Secret Store keyring canaries.

Revision ID: 0088_worker_keyring_sync
Revises: 0087_wfc_report_receipts
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0088_worker_keyring_sync"
down_revision = "0087_wfc_report_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0088_worker_keyring_sync.sql"))


def downgrade() -> None:
    op.execute(_sql("0088_worker_keyring_sync.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
