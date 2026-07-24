"""Add the atomic Workflow C immutable Job producer entry point.

Revision ID: 0034_workflow_c_job_enqueue
Revises: 0033_terminal_shape_guard
"""

from pathlib import Path

from alembic import op


revision = "0034_workflow_c_job_enqueue"
down_revision = "0033_terminal_shape_guard"
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql"


def _execute(name: str) -> None:
    connection = op.get_bind().connection.driver_connection
    with connection.cursor() as cursor:
        cursor.execute((_SQL / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute("0034_workflow_c_job_enqueue.sql")


def downgrade() -> None:
    _execute("0034_workflow_c_job_enqueue.down.sql")
