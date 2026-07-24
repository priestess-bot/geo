"""Complete a Metric Judge batch when all evaluators agree."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0062_metric_judge_agreement"
down_revision = "0061_metric_child_reconcile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0062_metric_judge_agreement.sql"))


def downgrade() -> None:
    op.execute(_sql("0062_metric_judge_agreement.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
