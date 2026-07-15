"""Composition root for governed monitoring."""

from __future__ import annotations

import os
from pathlib import Path

from geo_core.monitoring.application import MonitoringApplication


def build_monitoring_application() -> MonitoringApplication | None:
    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    from geo_core.monitoring.postgres import PsycopgMonitoringUnitOfWorkFactory

    return MonitoringApplication(PsycopgMonitoringUnitOfWorkFactory(database_url))


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return direct
