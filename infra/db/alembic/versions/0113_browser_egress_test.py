"""Add durable Australian egress endpoint self-tests.

Revision ID: 0113_browser_egress_test
Revises: 0112_external_worker_heartbeats
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0113_browser_egress_test"
down_revision = "0112_external_worker_heartbeats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0113_browser_egress_test.sql"))


def downgrade() -> None:
    op.execute(_sql("0113_browser_egress_test.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
