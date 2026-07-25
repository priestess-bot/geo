"""Allow draft Profile runtime only for governed Style Profile build Jobs."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0079_synth_profile_runtime"
down_revision = "0078_provider_source_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(_sql("0079_synth_profile_runtime.sql"))


def downgrade() -> None:
    op.execute(_sql("0079_synth_profile_runtime.down.sql"))


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )
