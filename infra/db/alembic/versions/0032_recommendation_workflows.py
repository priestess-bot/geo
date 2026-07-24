"""Add Recommendation evidence, approvals, generation, and artifact lifecycle.

Revision ID: 0032_recommendation_workflows
Revises: 0031_workflow_c_stats_alerts
"""

from pathlib import Path

from alembic import op


revision = "0032_recommendation_workflows"
down_revision = "0031_workflow_c_stats_alerts"
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql"


def _execute(name: str) -> None:
    # The migration uses PL/pgSQL row-type tokens; psycopg must receive the
    # complete SQL string without SQLAlchemy's placeholder processing.
    connection = op.get_bind().connection.driver_connection
    with connection.cursor() as cursor:
        cursor.execute((_SQL / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute("0032_recommendation_workflows.sql")


def downgrade() -> None:
    _execute("0032_recommendation_workflows.down.sql")
