"""Make Recommendation append-only lifecycle compatible with App privileges.

Revision ID: 0036_recommendation_locks
Revises: 0035_workflow_c_report_locks
"""

from pathlib import Path

from alembic import op


revision = "0036_recommendation_locks"
down_revision = "0035_workflow_c_report_locks"
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql"


def _execute(name: str) -> None:
    connection = op.get_bind().connection.driver_connection
    with connection.cursor() as cursor:
        cursor.execute((_SQL / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute("0036_recommendation_locks.sql")


def downgrade() -> None:
    _execute("0036_recommendation_locks.down.sql")
