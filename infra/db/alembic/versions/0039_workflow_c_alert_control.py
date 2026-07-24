"""Fence manual Workflow C alert dispositions behind one durable RPC."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0039_workflow_c_alert_control"
down_revision = "0038_sampling_admission_control"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )


def upgrade() -> None:
    op.execute(_sql("0039_workflow_c_alert_control.sql"))


def downgrade() -> None:
    op.execute(_sql("0039_workflow_c_alert_control.down.sql"))
