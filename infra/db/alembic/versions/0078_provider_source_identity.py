"""Add canonical Kimi source identity and five-provider source routing."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0078_provider_source_identity"
down_revision = "0077_wfc_alert_report_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0078_provider_source_identity.sql"))


def downgrade() -> None:
    op.execute(_sql("0078_provider_source_identity.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
