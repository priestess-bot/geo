"""Retire SerpAPI and add LokiProxy provider-managed pool state."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0131_lokiproxy_pool"
down_revision = "0130_serpapi_secret_purpose"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )


def upgrade() -> None:
    op.execute(_sql("0131_lokiproxy_pool.sql"))


def downgrade() -> None:
    op.execute(_sql("0131_lokiproxy_pool.down.sql"))
