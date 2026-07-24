"""Style Browser image, registry, selector, and egress preflight checks."""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit
from uuid import UUID

from scripts.production_preflight_common import (
    has_symlink_component,
    strict_json_object,
    valid_https_url,
)
from scripts.production_preflight_contracts import PreflightIssue


_STYLE_FACTORY = "geo_style_worker.composition:build_style_collection_dispatcher"
_DNS_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STYLE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_STYLE_CHANNELS = frozenset(
    {
        "owned_site",
        "amazon",
        "youtube",
        "tiktok",
        "instagram",
        "productreview",
        "reddit",
        "ozbargain",
        "quora",
    }
)
_STYLE_ADAPTER_KEYS = frozenset(
    {
        "channel",
        "adapter_release",
        "admission_state",
        "allowed_resource_hosts",
        "content_selectors",
        "navigation_timeout_ms",
        "settle_timeout_ms",
        "login_flow",
    }
)
_STYLE_LOGIN_KEYS = frozenset(
    {
        "login_url",
        "username_selector",
        "password_selector",
        "submit_selector",
        "success_selector",
    }
)
_MAX_STYLE_REGISTRY_BYTES = 256 * 1024


def read_style_registry_file(
    value: str,
    issues: list[PreflightIssue],
    *,
    current_euid: int,
) -> bytes | None:
    field = "GEO_STYLE_ADAPTER_REGISTRY_FILE"
    path = Path(value)
    if not path.is_absolute():
        issues.append(PreflightIssue("STYLE_REGISTRY_PATH_NOT_ABSOLUTE", field))
        return None
    if has_symlink_component(path):
        issues.append(PreflightIssue("STYLE_REGISTRY_FILE_NOT_REGULAR", field))
        return None
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        issues.append(PreflightIssue("STYLE_REGISTRY_FILE_NOT_FOUND", field))
        return None
    except OSError:
        issues.append(PreflightIssue("STYLE_REGISTRY_FILE_UNREADABLE", field))
        return None
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        issues.append(PreflightIssue("STYLE_REGISTRY_FILE_NOT_REGULAR", field))
        return None
    if metadata.st_uid not in {0, current_euid}:
        issues.append(PreflightIssue("STYLE_REGISTRY_FILE_OWNER", field))
    if stat.S_IMODE(metadata.st_mode) != 0o444:
        issues.append(PreflightIssue("STYLE_REGISTRY_FILE_PERMISSIONS", field))
    if not 2 <= metadata.st_size <= _MAX_STYLE_REGISTRY_BYTES:
        issues.append(PreflightIssue("STYLE_REGISTRY_FILE_SIZE", field))
        return None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            opened = os.fstat(descriptor)
            if (
                opened.st_dev != metadata.st_dev
                or opened.st_ino != metadata.st_ino
                or opened.st_size != metadata.st_size
                or opened.st_uid != metadata.st_uid
                or opened.st_gid != metadata.st_gid
                or opened.st_mode != metadata.st_mode
            ):
                issues.append(PreflightIssue("STYLE_REGISTRY_FILE_CHANGED", field))
                return None
            content = os.read(descriptor, _MAX_STYLE_REGISTRY_BYTES + 1)
            after = os.fstat(descriptor)
            if (
                len(content) != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
                or after.st_ctime_ns != opened.st_ctime_ns
            ):
                issues.append(PreflightIssue("STYLE_REGISTRY_FILE_CHANGED", field))
                return None
        finally:
            os.close(descriptor)
    except OSError:
        issues.append(PreflightIssue("STYLE_REGISTRY_FILE_UNREADABLE", field))
        return None
    return content


def validate_style_registry(
    values: dict[str, str],
    content: bytes | None,
    issues: list[PreflightIssue],
) -> None:
    if content is None:
        return
    digest_field = "GEO_STYLE_ADAPTER_REGISTRY_SHA256"
    expected_digest = values.get(digest_field, "").strip()
    if _SHA256.fullmatch(expected_digest) is None:
        issues.append(PreflightIssue("STYLE_REGISTRY_DIGEST_INVALID", digest_field))
    elif not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected_digest):
        issues.append(PreflightIssue("STYLE_REGISTRY_DIGEST_MISMATCH", digest_field))
    try:
        payload = strict_json_object(content)
        resource_hosts = _require_style_registry_payload(payload)
        global_hosts = {
            item.strip()
            for item in values.get("GEO_STYLE_ALLOWED_EGRESS_HOSTS", "").split(",")
            if item.strip()
        }
        if not resource_hosts <= global_hosts:
            issues.append(
                PreflightIssue(
                    "STYLE_REGISTRY_EGRESS_NOT_ALLOWED",
                    "GEO_STYLE_ALLOWED_EGRESS_HOSTS",
                )
            )
    except ValueError:
        issues.append(
            PreflightIssue(
                "STYLE_REGISTRY_CONTENT_INVALID",
                "GEO_STYLE_ADAPTER_REGISTRY_FILE",
            )
        )


def validate_style_runtime(values: dict[str, str], issues: list[PreflightIssue]) -> None:
    service_identity = values.get("GEO_STYLE_COLLECTION_SERVICE_IDENTITY_ID", "").strip()
    try:
        if UUID(service_identity).int == 0:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        issues.append(
            PreflightIssue(
                "STYLE_SERVICE_IDENTITY_INVALID",
                "GEO_STYLE_COLLECTION_SERVICE_IDENTITY_ID",
            )
        )

    factory = values.get("GEO_STYLE_COLLECTION_COMPOSITION_FACTORY", "").strip()
    if factory and factory != _STYLE_FACTORY:
        issues.append(
            PreflightIssue(
                "STYLE_FACTORY_INVALID",
                "GEO_STYLE_COLLECTION_COMPOSITION_FACTORY",
            )
        )

    chromium = values.get("GEO_STYLE_CHROMIUM_EXECUTABLE", "").strip()
    if chromium:
        chromium_path = Path(chromium)
        if (
            not chromium_path.is_absolute()
            or ".." in chromium_path.parts
            or not chromium.startswith("/ms-playwright/")
        ):
            issues.append(
                PreflightIssue(
                    "STYLE_CHROMIUM_PATH_INVALID",
                    "GEO_STYLE_CHROMIUM_EXECUTABLE",
                )
            )

    allowlist = values.get("GEO_STYLE_ALLOWED_EGRESS_HOSTS", "").strip()
    if allowlist:
        hosts = [item.strip() for item in allowlist.split(",")]
        if (
            len(set(hosts)) != len(hosts)
            or any(
                not host
                or host != host.casefold()
                or _DNS_HOST.fullmatch(host) is None
                or host in {"localhost", "localhost.localdomain"}
                or host.endswith(".local")
                for host in hosts
            )
        ):
            issues.append(
                PreflightIssue(
                    "STYLE_EGRESS_ALLOWLIST_INVALID",
                    "GEO_STYLE_ALLOWED_EGRESS_HOSTS",
                )
            )


def _require_style_registry_payload(payload: dict[str, object]) -> frozenset[str]:
    if set(payload) != {"schema_version", "release_id", "adapters"}:
        raise ValueError
    release_id = payload["release_id"]
    adapters = payload["adapters"]
    if (
        payload["schema_version"] != 1
        or not isinstance(release_id, str)
        or _STYLE_TOKEN.fullmatch(release_id) is None
        or not isinstance(adapters, list)
        or not adapters
    ):
        raise ValueError
    channels: set[str] = set()
    identities: set[tuple[str, str]] = set()
    resource_hosts: set[str] = set()
    for raw_adapter in adapters:
        if not isinstance(raw_adapter, dict) or set(raw_adapter) != _STYLE_ADAPTER_KEYS:
            raise ValueError
        channel = raw_adapter["channel"]
        release = raw_adapter["adapter_release"]
        admission_state = raw_adapter["admission_state"]
        if (
            not isinstance(channel, str)
            or channel not in _STYLE_CHANNELS
            or not isinstance(release, str)
            or _STYLE_TOKEN.fullmatch(release) is None
            or admission_state not in {"reviewed_fixture", "live_canary_approved"}
        ):
            raise ValueError
        identity = (channel, release)
        if identity in identities:
            raise ValueError
        identities.add(identity)
        channels.add(channel)
        adapter_hosts = _require_style_resource_hosts(
            raw_adapter["allowed_resource_hosts"]
        )
        resource_hosts.update(adapter_hosts)
        _require_style_selectors(raw_adapter["content_selectors"])
        _require_bounded_int(raw_adapter["navigation_timeout_ms"], 1_000, 60_000)
        _require_bounded_int(raw_adapter["settle_timeout_ms"], 0, 10_000)
        _require_style_login_flow(raw_adapter["login_flow"], adapter_hosts)
    if channels != _STYLE_CHANNELS:
        raise ValueError
    return frozenset(resource_hosts)


def _require_style_resource_hosts(value: object) -> frozenset[str]:
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError
    hosts: list[str] = []
    for host in value:
        if (
            not isinstance(host, str)
            or host != host.casefold()
            or _DNS_HOST.fullmatch(host) is None
            or host in {"localhost", "localhost.localdomain"}
            or host.endswith(".local")
        ):
            raise ValueError
        hosts.append(host)
    if len(set(hosts)) != len(hosts):
        raise ValueError
    return frozenset(hosts)


def _require_style_selectors(value: object) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValueError
    for selector in value:
        if (
            not isinstance(selector, str)
            or not selector.strip()
            or len(selector.encode("utf-8")) > 500
            or any(character in selector for character in ("\x00", "\n", "\r"))
        ):
            raise ValueError


def _require_bounded_int(value: object, minimum: int, maximum: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not minimum <= value <= maximum
    ):
        raise ValueError


def _require_style_login_flow(
    value: object, resource_hosts: frozenset[str]
) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != _STYLE_LOGIN_KEYS:
        raise ValueError
    login_url = value["login_url"]
    if not isinstance(login_url, str) or not valid_https_url(login_url):
        raise ValueError
    parsed = urlsplit(login_url)
    if parsed.query or parsed.fragment or parsed.hostname not in resource_hosts:
        raise ValueError
    _require_style_selectors(
        [
            value["username_selector"],
            value["password_selector"],
            value["submit_selector"],
            value["success_selector"],
        ]
    )


__all__ = ["read_style_registry_file", "validate_style_registry", "validate_style_runtime"]
