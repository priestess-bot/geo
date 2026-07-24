"""Scope Workflow C analytical projections by Project before deduplication."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0059_analysis_project_scope"
down_revision = "0058_wfc_spec_sensitive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0059_analysis_project_scope.sql"))


def downgrade() -> None:
    op.execute(_sql("0059_analysis_project_scope.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
