"""Persist Workflow C Sampling admission policies behind fenced commands.

Revision ID: 0038_sampling_admission_control
Revises: 0037_wfc_artifact_tombstone
"""

from pathlib import Path

from alembic import op


revision = "0038_sampling_admission_control"
down_revision = "0037_wfc_artifact_tombstone"
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql"


def _execute(name: str) -> None:
    connection = op.get_bind().connection.driver_connection
    with connection.cursor() as cursor:
        cursor.execute((_SQL / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute("0038_sampling_admission_control.sql")


def downgrade() -> None:
    _execute("0038_sampling_admission_control.down.sql")
