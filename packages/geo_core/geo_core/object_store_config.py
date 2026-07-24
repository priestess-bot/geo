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
    return build_object_store_from_prefix("OBJECT_STORE", environment=environment)


def build_object_store_from_prefix(
    prefix: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> S3CompatibleObjectStore:
    """Build an S3 client from an explicit configuration namespace.

    Sensitive artifact domains must not inherit the general application object
    store credentials merely because they use the same S3-compatible API.
    Callers therefore provide a fixed, reviewed prefix such as
    ``GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE``.
    """

    normalized = prefix.strip().upper()
    if not normalized or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for character in normalized):
        raise RuntimeError("object-store configuration prefix is invalid")
    values = os.environ if environment is None else environment
    auto_create = values.get(f"{normalized}_AUTO_CREATE_BUCKET", "0").strip().casefold()
    if auto_create not in {"0", "1", "false", "true", "no", "yes", "off", "on"}:
        raise RuntimeError(f"{normalized}_AUTO_CREATE_BUCKET must be a boolean")
    return S3CompatibleObjectStore(
        endpoint=values.get(f"{normalized}_ENDPOINT", "").strip(),
        bucket=values.get(f"{normalized}_BUCKET", "").strip(),
        access_key=_secret(values, f"{normalized}_ACCESS_KEY"),
        secret_key=_secret(values, f"{normalized}_SECRET_KEY"),
        region=values.get(f"{normalized}_REGION", "us-east-1").strip(),
        auto_create_bucket=auto_create in {"1", "true", "yes", "on"},
    )


__all__ = ["build_object_store", "build_object_store_from_prefix"]
