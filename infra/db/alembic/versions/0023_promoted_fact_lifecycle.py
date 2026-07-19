"""Allow lifecycle-only retirement of promoted Knowledge Facts.

Revision ID: 0023_promoted_fact_lifecycle
Revises: 0022_legacy_fact_hash_repair
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0023_promoted_fact_lifecycle"
down_revision = "0022_legacy_fact_hash_repair"
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _execute_file(name: str) -> None:
    sql = (_SQL_DIR / name).read_text(encoding="utf-8")
    bind = op.get_bind()
    if hasattr(bind, "exec_driver_sql"):
        bind.exec_driver_sql(sql)
    else:
        op.execute(sql)


def upgrade() -> None:
    _execute_file("0023_promoted_fact_lifecycle.sql")


def downgrade() -> None:
    _execute_file("0023_promoted_fact_lifecycle.down.sql")
