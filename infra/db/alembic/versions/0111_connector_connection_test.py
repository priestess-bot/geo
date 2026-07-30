"""Add durable, secret-free Connector connection tests.

Revision ID: 0111_connector_connection_test
Revises: 0110_attribution_external_report
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0111_connector_connection_test"
down_revision = "0110_attribution_external_report"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0111_connector_connection_test.sql"))


def downgrade() -> None:
    op.execute(_sql("0111_connector_connection_test.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
