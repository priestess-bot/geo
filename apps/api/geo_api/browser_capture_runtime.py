"""Browser Capture Admin composition root."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from geo_core.browser_capture.admin import BrowserCaptureAdminService
from geo_core.browser_capture.admission import BrowserCaptureAttemptAdmissionService


def build_browser_capture_admin_service() -> BrowserCaptureAdminService | None:
    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    return BrowserCaptureAdminService(
        connect=lambda: psycopg.connect(database_url, row_factory=dict_row)
    )


def build_browser_capture_attempt_service() -> BrowserCaptureAttemptAdmissionService | None:
    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    return BrowserCaptureAttemptAdmissionService(
        connect=lambda: psycopg.connect(database_url, row_factory=dict_row)
    )


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise RuntimeError(f"{name} and {name}_FILE cannot both be configured")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return direct


__all__ = ["build_browser_capture_admin_service", "build_browser_capture_attempt_service"]
