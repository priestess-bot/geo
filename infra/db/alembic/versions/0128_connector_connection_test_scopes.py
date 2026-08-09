"""Freeze active Connector Scopes into connection-test Jobs.

Revision ID: 0128_connector_test_scopes
Revises: 0127_question_set_dedup
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0128_connector_test_scopes"
down_revision = "0127_question_set_dedup"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )


def upgrade() -> None:
    op.execute(_sql("0128_connector_test_scopes.sql"))


def downgrade() -> None:
    op.execute(_sql("0128_connector_test_scopes.down.sql"))
