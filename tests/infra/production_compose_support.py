"""Shared Compose fixtures for focused production infrastructure tests."""

from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "infra" / "compose.prod.yml"
STYLE_COMPOSE_PATH = ROOT / "infra" / "compose.style-collection.yml"


def load_compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def load_style_compose() -> dict[str, Any]:
    return yaml.safe_load(STYLE_COMPOSE_PATH.read_text(encoding="utf-8"))


def load_runtime_services() -> dict[str, Any]:
    return {
        **load_compose()["services"],
        **load_style_compose()["services"],
    }


__all__ = [
    "COMPOSE_PATH",
    "ROOT",
    "STYLE_COMPOSE_PATH",
    "load_compose",
    "load_runtime_services",
    "load_style_compose",
]
