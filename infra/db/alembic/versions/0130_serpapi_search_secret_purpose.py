"""Allow the optional SerpAPI search runtime to use its search Secret purpose.

The six model-provider purpose contract remains unchanged.  Only the formal
SerpAPI runtime option maps to ``search.serpapi``.
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0130_serpapi_secret_purpose"
down_revision = "0129_question_repair"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "sql" / name).read_text(
        encoding="utf-8"
    )


def upgrade() -> None:
    op.execute(_sql("0130_serpapi_secret_purpose.sql"))


def downgrade() -> None:
    op.execute(_sql("0130_serpapi_secret_purpose.down.sql"))
