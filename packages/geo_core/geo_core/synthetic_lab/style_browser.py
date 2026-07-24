"""Pure frozen registry contracts for Style browser adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
import re
from types import MappingProxyType
from urllib.parse import urlsplit

from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.collection_execution_contracts import (
    StyleCollectionExecutionError,
    StyleCollectionTask,
)
from geo_core.synthetic_lab.domain import STANDARD_STYLE_CHANNELS, StyleAccessMode


_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class StyleAdapterAdmission(StrEnum):
    REVIEWED_FIXTURE = "reviewed_fixture"
    LIVE_CANARY_APPROVED = "live_canary_approved"


@dataclass(frozen=True, kw_only=True)
class StyleLoginFlow:
    login_url: str
    username_selector: str
    password_selector: str
    submit_selector: str
    success_selector: str

    def __post_init__(self) -> None:
        _safe_https_url(self.login_url)
        for value in (
            self.username_selector,
            self.password_selector,
            self.submit_selector,
            self.success_selector,
        ):
            _selector(value)


@dataclass(frozen=True, kw_only=True)
class StyleAdapterRelease:
    channel: str
    adapter_release: str
    content_selectors: tuple[str, ...]
    allowed_resource_hosts: tuple[str, ...]
    navigation_timeout_ms: int
    settle_timeout_ms: int
    login_flow: StyleLoginFlow | None
    admission_state: StyleAdapterAdmission
    release_hash: str = ""

    def __post_init__(self) -> None:
        if self.channel not in STANDARD_STYLE_CHANNELS:
            raise StyleCollectionExecutionError("Style adapter channel is unsupported")
        if _TOKEN.fullmatch(self.adapter_release) is None:
            raise StyleCollectionExecutionError("Style adapter release is invalid")
        selectors = tuple(self.content_selectors)
        if not 1 <= len(selectors) <= 20 or len(set(selectors)) != len(selectors):
            raise StyleCollectionExecutionError("Style adapter selectors are invalid")
        for selector in selectors:
            _selector(selector)
        object.__setattr__(self, "content_selectors", selectors)
        submitted_hosts = tuple(self.allowed_resource_hosts)
        resource_hosts = tuple(sorted(submitted_hosts))
        if (
            len(resource_hosts) > 50
            or len(set(resource_hosts)) != len(resource_hosts)
            or any(not _valid_host(host) for host in resource_hosts)
        ):
            raise StyleCollectionExecutionError("Style adapter resource hosts are invalid")
        object.__setattr__(self, "allowed_resource_hosts", resource_hosts)
        if self.login_flow is not None and (
            urlsplit(self.login_flow.login_url).hostname or ""
        ).lower() not in resource_hosts:
            raise StyleCollectionExecutionError("Style login host is not a frozen resource host")
        try:
            admission = StyleAdapterAdmission(self.admission_state)
        except ValueError as error:
            raise StyleCollectionExecutionError("Style adapter admission state is invalid") from error
        object.__setattr__(self, "admission_state", admission)
        if not 1_000 <= self.navigation_timeout_ms <= 60_000:
            raise StyleCollectionExecutionError("Style adapter navigation timeout is invalid")
        if not 0 <= self.settle_timeout_ms <= 10_000:
            raise StyleCollectionExecutionError("Style adapter settle timeout is invalid")
        expected = canonical_hash(
            {
                "channel": self.channel,
                "adapter_release": self.adapter_release,
                "content_selectors": selectors,
                "allowed_resource_hosts": resource_hosts,
                "navigation_timeout_ms": self.navigation_timeout_ms,
                "settle_timeout_ms": self.settle_timeout_ms,
                "login_flow": self.login_flow,
                "admission_state": admission,
            }
        )
        if self.release_hash and self.release_hash != expected:
            raise StyleCollectionExecutionError("Style adapter release hash changed")
        object.__setattr__(self, "release_hash", expected)


@dataclass(frozen=True, kw_only=True)
class StyleAdapterRegistry:
    release_id: str
    adapters: Mapping[tuple[str, str], StyleAdapterRelease]
    registry_hash: str

    def require(
        self,
        task: StyleCollectionTask,
        *,
        allow_reviewed_fixture: bool = False,
    ) -> StyleAdapterRelease:
        try:
            adapter = self.adapters[(task.channel, task.adapter_release)]
        except KeyError as error:
            raise StyleCollectionExecutionError("Style adapter release is not frozen") from error
        if task.access_mode is StyleAccessMode.AUTHENTICATED and adapter.login_flow is None:
            raise StyleCollectionExecutionError("authenticated Style Source has no login flow")
        if (
            adapter.admission_state is not StyleAdapterAdmission.LIVE_CANARY_APPROVED
            and not allow_reviewed_fixture
        ):
            raise StyleCollectionExecutionError("Style adapter has no approved live canary")
        return adapter


def load_style_adapter_registry(path: str | Path) -> StyleAdapterRegistry:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StyleCollectionExecutionError("Style adapter registry cannot be read") from error
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "release_id",
        "adapters",
    }:
        raise StyleCollectionExecutionError("Style adapter registry schema is invalid")
    if payload["schema_version"] != 1 or not isinstance(payload["release_id"], str):
        raise StyleCollectionExecutionError("Style adapter registry version is invalid")
    if _TOKEN.fullmatch(payload["release_id"]) is None or not isinstance(payload["adapters"], list):
        raise StyleCollectionExecutionError("Style adapter registry identity is invalid")
    adapters: dict[tuple[str, str], StyleAdapterRelease] = {}
    for item in payload["adapters"]:
        adapter = _parse_adapter(item)
        identity = (adapter.channel, adapter.adapter_release)
        if identity in adapters:
            raise StyleCollectionExecutionError("Style adapter identity is duplicated")
        adapters[identity] = adapter
    if {channel for channel, _release in adapters} != set(STANDARD_STYLE_CHANNELS):
        raise StyleCollectionExecutionError("Style adapter registry must cover all nine channels")
    return StyleAdapterRegistry(
        release_id=payload["release_id"],
        adapters=MappingProxyType(adapters),
        registry_hash=canonical_hash(payload),
    )


def _parse_adapter(value: object) -> StyleAdapterRelease:
    required = {
        "channel",
        "adapter_release",
        "content_selectors",
        "allowed_resource_hosts",
        "navigation_timeout_ms",
        "settle_timeout_ms",
        "login_flow",
        "admission_state",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise StyleCollectionExecutionError("Style adapter entry schema is invalid")
    selectors = value["content_selectors"]
    resource_hosts = value["allowed_resource_hosts"]
    if not isinstance(selectors, list) or any(not isinstance(item, str) for item in selectors):
        raise StyleCollectionExecutionError("Style adapter selectors are invalid")
    if not isinstance(resource_hosts, list) or any(
        not isinstance(item, str) for item in resource_hosts
    ):
        raise StyleCollectionExecutionError("Style adapter resource hosts are invalid")
    login = value["login_flow"]
    if login is not None:
        login_keys = {
            "login_url",
            "username_selector",
            "password_selector",
            "submit_selector",
            "success_selector",
        }
        if not isinstance(login, dict) or set(login) != login_keys:
            raise StyleCollectionExecutionError("Style adapter login flow schema is invalid")
        login = StyleLoginFlow(**login)
    try:
        return StyleAdapterRelease(
            channel=value["channel"],
            adapter_release=value["adapter_release"],
            content_selectors=tuple(selectors),
            allowed_resource_hosts=tuple(resource_hosts),
            navigation_timeout_ms=value["navigation_timeout_ms"],
            settle_timeout_ms=value["settle_timeout_ms"],
            login_flow=login,
            admission_state=StyleAdapterAdmission(value["admission_state"]),
        )
    except (TypeError, ValueError) as error:
        raise StyleCollectionExecutionError("Style adapter entry types are invalid") from error


def _selector(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise StyleCollectionExecutionError("Style adapter selector is invalid")


def _safe_https_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise StyleCollectionExecutionError("Style adapter URL must be credential-free HTTPS")


def _valid_host(value: str) -> bool:
    labels = value.split(".")
    return (
        value == value.lower()
        and 1 <= len(value) <= 253
        and all(_HOST_LABEL.fullmatch(label) is not None for label in labels)
    )


__all__ = [
    "StyleAdapterAdmission",
    "StyleAdapterRegistry",
    "StyleAdapterRelease",
    "StyleLoginFlow",
    "load_style_adapter_registry",
]
