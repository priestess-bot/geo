"""Composition root for the internal project membership application."""

from __future__ import annotations

import os
from pathlib import Path

from geo_core.access.membership_service import AccessMembershipService


def build_membership_application() -> AccessMembershipService | None:
    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    from geo_core.access.postgres import PsycopgAccessUnitOfWorkFactory

    return AccessMembershipService(PsycopgAccessUnitOfWorkFactory(database_url))


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return direct
