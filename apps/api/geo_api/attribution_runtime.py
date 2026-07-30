"""Composition root for local attribution."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from geo_core.attribution import AttributionService


def build_attribution_service() -> AttributionService | None:
    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    return AttributionService(
        connect=lambda: psycopg.connect(database_url, row_factory=dict_row)
    )


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise RuntimeError(f"{name} and {name}_FILE cannot both be configured")
    return Path(file_name).read_text(encoding="utf-8").strip() if file_name else direct


__all__ = ["build_attribution_service"]
