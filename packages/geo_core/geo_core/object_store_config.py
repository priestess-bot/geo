"""Small object-store composition helper independent of legacy runtime wiring."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from geo_core.object_store import S3CompatibleObjectStore


def _secret(environment: Mapping[str, str], name: str) -> str:
    direct = environment.get(name, "").strip()
    file_name = environment.get(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise RuntimeError(f"configure {name} directly or by file, not both")
    if file_name:
        try:
            direct = Path(file_name).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"{name}_FILE cannot be read") from exc
    if not direct:
        raise RuntimeError(f"{name} or {name}_FILE is required")
    return direct


def build_object_store(
    environment: Mapping[str, str] | None = None,
) -> S3CompatibleObjectStore:
    values = os.environ if environment is None else environment
    auto_create = values.get("OBJECT_STORE_AUTO_CREATE_BUCKET", "0").strip().casefold()
    if auto_create not in {"0", "1", "false", "true", "no", "yes", "off", "on"}:
        raise RuntimeError("OBJECT_STORE_AUTO_CREATE_BUCKET must be a boolean")
    return S3CompatibleObjectStore(
        endpoint=values.get("OBJECT_STORE_ENDPOINT", "").strip(),
        bucket=values.get("OBJECT_STORE_BUCKET", "geo-artifacts").strip(),
        access_key=_secret(values, "OBJECT_STORE_ACCESS_KEY"),
        secret_key=_secret(values, "OBJECT_STORE_SECRET_KEY"),
        region=values.get("OBJECT_STORE_REGION", "us-east-1").strip(),
        auto_create_bucket=auto_create in {"1", "true", "yes", "on"},
    )
