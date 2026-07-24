"""Add project-scoped Synthetic Lab persistence.

Revision ID: 0030_synthetic_lab
Revises: 0029_model_gateway
"""

from pathlib import Path

from alembic import op


revision = "0030_synthetic_lab"
down_revision = "0029_model_gateway"
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql"


def _execute(name: str) -> None:
    # Execute without a parameters object. SQLAlchemy's driver SQL path passes an
    # empty parameter mapping to psycopg, which makes valid PL/pgSQL tokens such
    # as ``%ROWTYPE`` enter psycopg's placeholder parser.
    connection = op.get_bind().connection.driver_connection
    with connection.cursor() as cursor:
        cursor.execute((_SQL / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute("0030_synthetic_lab.sql")


def downgrade() -> None:
    _execute("0030_synthetic_lab.down.sql")
