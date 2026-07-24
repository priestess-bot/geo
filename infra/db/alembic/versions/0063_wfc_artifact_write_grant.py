"""Allow the restricted Workflow C writer to enqueue failed-stage cleanup."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0063_wfc_artifact_write_grant"
down_revision = "0062_metric_judge_agreement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0063_wfc_artifact_write_grant.sql"))


def downgrade() -> None:
    op.execute(_sql("0063_wfc_artifact_write_grant.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
