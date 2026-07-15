"""Provision schema through Alembic's configured environment or secret file."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


ROOT = Path(__file__).resolve().parents[1]


def provision() -> None:
    configuration = Config(ROOT / "alembic.ini")
    command.upgrade(configuration, "head")


def main() -> None:
    provision()


if __name__ == "__main__":
    main()
