"""Add an audited retirement lifecycle for Provider execution inputs."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0057_provider_exec_retirement"
down_revision = "0056_sampling_cancel_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0057_provider_exec_retirement.sql"))


def downgrade() -> None:
    op.execute(_sql("0057_provider_exec_retirement.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(encoding="utf-8")
