"""Add audited Model Gateway releases, policy, and call persistence.

Revision ID: 0029_model_gateway
Revises: 0028_secret_store
"""

from pathlib import Path

from alembic import op


revision = "0029_model_gateway"
down_revision = "0028_secret_store"
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql"


def _execute(name: str) -> None:
    # Keep PL/pgSQL tokens such as ``%ROWTYPE`` out of psycopg's placeholder parser.
    connection = op.get_bind().connection.driver_connection
    with connection.cursor() as cursor:
        cursor.execute((_SQL / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute("0029_model_gateway.sql")


def downgrade() -> None:
    _execute("0029_model_gateway.down.sql")
