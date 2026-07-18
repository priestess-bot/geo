"""Composition root for the enterprise knowledge application."""

from __future__ import annotations

import os
from pathlib import Path

from geo_core.knowledge import KnowledgeApplication


def build_knowledge_application() -> KnowledgeApplication | None:
    database_url = _secret("GEO_DATABASE_URL")
    return KnowledgeApplication(database_url) if database_url else None


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return direct
