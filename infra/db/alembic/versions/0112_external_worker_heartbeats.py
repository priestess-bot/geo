"""Admit Connector and Browser Capture workers to runtime health.

Revision ID: 0112_external_worker_heartbeats
Revises: 0111_connector_connection_test
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0112_external_worker_heartbeats"
down_revision = "0111_connector_connection_test"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0112_external_worker_heartbeats.sql"))


def downgrade() -> None:
    op.execute(_sql("0112_external_worker_heartbeats.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
