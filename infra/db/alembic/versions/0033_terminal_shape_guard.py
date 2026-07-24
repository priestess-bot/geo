"""Prioritize deterministic Model Gateway terminal shape guards.

Revision ID: 0033_terminal_shape_guard
Revises: 0032_recommendation_workflows
"""

from pathlib import Path

from alembic import op


revision = "0033_terminal_shape_guard"
down_revision = "0032_recommendation_workflows"
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql"


def _execute(name: str) -> None:
    connection = op.get_bind().connection.driver_connection
    with connection.cursor() as cursor:
        cursor.execute((_SQL / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute("0033_terminal_shape_guard.sql")


def downgrade() -> None:
    _execute("0033_terminal_shape_guard.down.sql")
