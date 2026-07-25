"""Scope Provider Attempt validation to Provider capture methods."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0075_wfc_manual_attempt_scope"
down_revision = "0074_wfc_semantic_job_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0075_wfc_manual_attempt_scope.sql"))


def downgrade() -> None:
    op.execute(_sql("0075_wfc_manual_attempt_scope.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
