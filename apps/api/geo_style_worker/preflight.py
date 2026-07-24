"""Fail-closed runtime validation for the isolated Style Collection worker."""

from __future__ import annotations

import hashlib
import importlib
from importlib.metadata import version
import os
from pathlib import Path
import re
import stat
from uuid import UUID

from geo_core.synthetic_lab.artifact_keyring import load_synthetic_artifact_keyring
from geo_core.synthetic_lab.raw_artifact_governance import ArtifactStorageTier
from geo_core.synthetic_lab.style_browser import (
    StyleAdapterAdmission,
    load_style_adapter_registry,
)
from geo_worker.config import secret_setting


EXPECTED_PLAYWRIGHT_VERSION = "1.60.0"
STYLE_QUEUE = "style-collection"
_DIGEST_IMAGE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")


def validate_style_browser_runtime() -> None:
    image = os.getenv("GEO_STYLE_BROWSER_IMAGE_REFERENCE", "").strip()
    if _DIGEST_IMAGE.fullmatch(image) is None:
        raise RuntimeError("GEO_STYLE_BROWSER_IMAGE_REFERENCE must be digest pinned")
    if os.getenv("GEO_STYLE_COLLECTION_QUEUE", "").strip() != STYLE_QUEUE:
        raise RuntimeError("Style Collection worker must use its dedicated queue")
    _require_service_identity()
    if version("playwright") != EXPECTED_PLAYWRIGHT_VERSION:
        raise RuntimeError("Style Collection Playwright release is not frozen")
    if os.getenv("GEO_STYLE_BROWSER_WS_ENDPOINT", "").strip() != (
        "ws://style-browser-runtime:9222/"
    ):
        raise RuntimeError("Style browser must use the isolated remote runtime")
    chromium = Path(os.getenv("GEO_STYLE_CHROMIUM_EXECUTABLE", "").strip())
    if not chromium.is_file() or not os.access(chromium, os.X_OK):
        raise RuntimeError("frozen Chromium executable is unavailable")
    tmpfs = Path(os.getenv("GEO_STYLE_CAPTURE_TMPFS", "").strip())
    if not tmpfs.is_dir() or not _is_tmpfs(tmpfs):
        raise RuntimeError("Style Collection capture mount must be tmpfs")
    if os.getenv("GEO_STYLE_TMPFS_ENCRYPTION_REQUIRED", "") != "1":
        raise RuntimeError("Style Collection encrypted spool policy is required")
    artifact_keyring_path = os.getenv("GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE", "").strip()
    if not artifact_keyring_path:
        raise RuntimeError("GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE is required")
    artifact_path = Path(artifact_keyring_path)
    master_path = Path(os.getenv("GEO_SECRET_STORE_MASTER_KEYRING_FILE", "").strip())
    _validate_artifact_keyring(artifact_path, master_path)
    registry_path = Path(os.getenv("GEO_STYLE_ADAPTER_REGISTRY_FILE", "").strip())
    expected_registry_hash = os.getenv("GEO_STYLE_ADAPTER_REGISTRY_SHA256", "").strip()
    if (
        registry_path.is_symlink()
        or not registry_path.is_file()
        or not stat.S_ISREG(registry_path.stat().st_mode)
        or os.access(registry_path, os.W_OK)
        or re.fullmatch(r"[0-9a-f]{64}", expected_registry_hash) is None
    ):
        raise RuntimeError("Style adapter registry path and SHA-256 are required")
    actual_registry_hash = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    if actual_registry_hash != expected_registry_hash:
        raise RuntimeError("Style adapter registry digest changed")
    registry = load_style_adapter_registry(registry_path)
    if not any(
        adapter.admission_state is StyleAdapterAdmission.LIVE_CANARY_APPROVED
        for adapter in registry.adapters.values()
    ):
        raise RuntimeError("Style adapter registry has no approved live canary")
    allowed_hosts = tuple(
        host.strip().lower()
        for host in os.getenv("GEO_STYLE_ALLOWED_EGRESS_HOSTS", "").split(",")
        if host.strip()
    )
    if not allowed_hosts:
        raise RuntimeError("GEO_STYLE_ALLOWED_EGRESS_HOSTS is required")
    static_hosts = {
        host for adapter in registry.adapters.values() for host in adapter.allowed_resource_hosts
    }
    if not static_hosts.issubset(allowed_hosts):
        raise RuntimeError("Style adapter registry exceeds the worker egress allowlist")
    for setting in (
        "GEO_DATABASE_URL",
        "GEO_SECRET_STORE_MASTER_KEYRING",
        "GEO_SECRET_STORE_REQUEST_HASH_KEY",
        "GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE_ACCESS_KEY",
        "GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE_SECRET_KEY",
        "GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE_ACCESS_KEY",
        "GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE_SECRET_KEY",
    ):
        secret_setting(setting)
    raw_bucket = os.getenv("GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE_BUCKET", "").strip()
    derived_bucket = os.getenv(
        "GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE_BUCKET", ""
    ).strip()
    if not raw_bucket or not derived_bucket or raw_bucket == derived_bucket:
        raise RuntimeError("Synthetic Style raw and derived artifact buckets must be distinct")
    load_composition_factory()


def _validate_artifact_keyring(artifact_path: Path, master_path: Path) -> None:
    artifact_keyring = load_synthetic_artifact_keyring(artifact_path)
    artifact_keyring.resolve(
        project_id=UUID("00000000-0000-4000-8000-000000000001"),
        storage_tier=ArtifactStorageTier.ENCRYPTED_RAW,
    )
    if master_path.is_file() and (
        artifact_path.samefile(master_path)
        or hashlib.sha256(artifact_path.read_bytes()).digest()
        == hashlib.sha256(master_path.read_bytes()).digest()
    ):
        raise RuntimeError("Synthetic artifact keyring must be independent")


def _require_service_identity() -> UUID:
    raw_identity = os.getenv("GEO_STYLE_COLLECTION_SERVICE_IDENTITY_ID", "").strip()
    try:
        identity_id = UUID(raw_identity)
    except (TypeError, ValueError):
        raise RuntimeError("GEO_STYLE_COLLECTION_SERVICE_IDENTITY_ID must be a UUID") from None
    if identity_id.int == 0:
        raise RuntimeError("GEO_STYLE_COLLECTION_SERVICE_IDENTITY_ID cannot be the nil UUID")
    return identity_id


def load_composition_factory():
    value = os.getenv("GEO_STYLE_COLLECTION_COMPOSITION_FACTORY", "").strip()
    if ":" not in value:
        raise RuntimeError("GEO_STYLE_COLLECTION_COMPOSITION_FACTORY is required")
    module_name, function_name = value.split(":", 1)
    factory = getattr(importlib.import_module(module_name), function_name, None)
    if not callable(factory):
        raise RuntimeError("Style Collection composition factory is not callable")
    return factory


def _is_tmpfs(path: Path) -> bool:
    resolved = path.resolve()
    matches: list[tuple[int, str]] = []
    for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        mount = Path(parts[1].replace("\\040", " ")).resolve()
        try:
            resolved.relative_to(mount)
        except ValueError:
            continue
        matches.append((len(str(mount)), parts[2]))
    return bool(matches) and max(matches)[1] == "tmpfs"


if __name__ == "__main__":
    validate_style_browser_runtime()
