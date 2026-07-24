"""Add Workflow C sampling, statistical analysis, alerts, and artifact governance.

Revision ID: 0031_workflow_c_stats_alerts
Revises: 0030_synthetic_lab
"""

from pathlib import Path

from alembic import op


revision = "0031_workflow_c_stats_alerts"
down_revision = "0030_synthetic_lab"
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql"


def _execute(name: str) -> None:
    connection = op.get_bind().connection.driver_connection
    with connection.cursor() as cursor:
        cursor.execute((_SQL / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute("0031_workflow_c_stats_alerts.sql")


def downgrade() -> None:
    _execute("0031_workflow_c_stats_alerts.down.sql")
