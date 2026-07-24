"""Require frozen Provider execution input at Suite and Attempt admission."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0053_provider_exec_enforce"
down_revision = "0052_provider_execution_input"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0053_provider_exec_enforce.sql"))


def downgrade() -> None:
    op.execute(_sql("0053_provider_exec_enforce.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
