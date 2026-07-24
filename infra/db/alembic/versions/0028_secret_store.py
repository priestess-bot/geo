"""Add the project-scoped encrypted Secret Store.

Revision ID: 0028_secret_store
Revises: 0027_prompt_programs
"""

from pathlib import Path

from alembic import op

revision = "0028_secret_store"
down_revision = "0027_prompt_programs"
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql"


def _execute(name: str) -> None:
    op.get_bind().exec_driver_sql((_SQL / name).read_text(encoding="utf-8"))


def upgrade() -> None:
    _execute("0028_secret_store.sql")


def downgrade() -> None:
    _execute("0028_secret_store.down.sql")
