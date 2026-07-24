"""Production contracts for authorized public and normal-login Style Collection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import hashlib
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.secrets.models import SecretValue, SecretVersionHandle
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.authorization import AuthorizationBinding
from geo_core.synthetic_lab.domain import (
    AU_ENGLISH_LOCALE,
    STANDARD_STYLE_CHANNELS,
    StyleAccessMode,
    SyntheticLabContractError,
    SyntheticOnly,
    _as_enum,
    _require_aware_datetime,
    _require_hash,
    _require_text,
    _require_uuid,
)
from geo_core.synthetic_lab.raw_artifact_governance import RawArtifactInspection


class StyleCollectionExecutionError(RuntimeError):
    """A collection failed without carrying page or credential content."""


class CollectionBlockReason(StrEnum):
    CAPTCHA = "captcha"
    ACCESS_DENIED = "access_denied"
    RATE_LIMITED = "rate_limited"
    LOGIN_FAILED = "login_failed"
    ROBOTS_DENIED = "robots_denied"
    REDIRECT_DENIED = "redirect_denied"
    AUTHORIZATION_STALE = "authorization_stale"


class CollectionOutcome(StrEnum):
    CAPTURED = "captured"
    ACCESS_BLOCKED = "access_blocked"


@dataclass(frozen=True, kw_only=True)
class TmpfsCapturePolicy:
    mount_path: str
    maximum_bytes: int
    encrypted: bool = True
    cleanup_on_exit: bool = True
    filesystem: str = "tmpfs"

    def __post_init__(self) -> None:
        if not self.mount_path.startswith(("/dev/shm/", "/run/", "/tmp/")):
            raise SyntheticLabContractError("Style Collection requires an isolated tmpfs mount")
        if self.maximum_bytes < 1:
            raise SyntheticLabContractError("Style Collection tmpfs limit must be positive")
        if self.filesystem != "tmpfs" or not self.encrypted or not self.cleanup_on_exit:
            raise SyntheticLabContractError(
                "Style Collection temporary storage must be encrypted tmpfs with cleanup"
            )


@dataclass(frozen=True, kw_only=True)
class StyleCollectionTask:
    project_id: UUID
    job_id: UUID
    collection_run_id: UUID
    style_source_revision_id: UUID
    source_revision_number: int
    channel: str
    locale: str
    access_mode: StyleAccessMode
    source_url: str = field(repr=False)
    source_locator_hash: str
    adapter_release: str
    authorization: AuthorizationBinding
    login_secret: SecretVersionHandle | None
    allowed_redirect_hosts: tuple[str, ...]
    robots_user_agent: str
    raw_artifact_id: UUID
    derived_artifact_id: UUID
    tmpfs: TmpfsCapturePolicy
    maximum_redirects: int = 5
    allow_proxy_rotation: bool = field(default=False, init=False)
    allow_stealth: bool = field(default=False, init=False)
    allow_captcha_solver: bool = field(default=False, init=False)
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.project_id, "collection Project"),
            (self.job_id, "collection Job"),
            (self.collection_run_id, "Collection Run"),
            (self.style_source_revision_id, "Style Source revision"),
            (self.raw_artifact_id, "raw collection artifact"),
            (self.derived_artifact_id, "derived collection artifact"),
        ):
            _require_uuid(value, label)
        if self.source_revision_number < 1 or self.maximum_redirects < 0:
            raise SyntheticLabContractError("collection source version/redirect limit is invalid")
        if self.channel not in STANDARD_STYLE_CHANNELS or self.locale != AU_ENGLISH_LOCALE:
            raise SyntheticLabContractError("collection channel/locale is unsupported")
        mode = _as_enum(self.access_mode, StyleAccessMode, "collection access mode")
        object.__setattr__(self, "access_mode", mode)
        if mode is StyleAccessMode.MANUAL_IMPORT:
            raise SyntheticLabContractError("manual imports cannot enter the live collector")
        _validate_safe_source_url(self.source_url)
        _require_hash(self.source_locator_hash, "collection source locator")
        _require_text(self.adapter_release, "collection adapter release")
        _require_text(self.robots_user_agent, "collection robots user agent")
        if (
            self.authorization.project_id != self.project_id
            or self.authorization.channel != self.channel
            or self.authorization.adapter_release != self.adapter_release
        ):
            raise SyntheticLabContractError("collection authorization does not match task scope")
        if self.login_secret is not None and self.login_secret.project_id != self.project_id:
            raise SyntheticLabContractError("collection login Secret crosses Project scope")
        if mode is StyleAccessMode.AUTHENTICATED and self.login_secret is None:
            raise SyntheticLabContractError("normal-login collection requires a Secret handle")
        if self.login_secret is not None and self.login_secret.purpose != (
            f"style_collection_login.{self.channel}"
        ):
            raise SyntheticLabContractError(
                "collection login Secret purpose does not match the exact channel"
            )
        if mode is StyleAccessMode.PUBLIC and self.login_secret is not None:
            raise SyntheticLabContractError("public collection cannot resolve a login Secret")
        hosts = tuple(sorted(set(host.lower().strip() for host in self.allowed_redirect_hosts)))
        object.__setattr__(self, "allowed_redirect_hosts", hosts)
        source_host = (urlsplit(self.source_url).hostname or "").lower()
        if not hosts or source_host not in hosts or any(not host for host in hosts):
            raise SyntheticLabContractError("collection redirect allowlist must include source host")
        object.__setattr__(self, "input_hash", canonical_hash(self.value()))

    def value(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "job_id": self.job_id,
            "collection_run_id": self.collection_run_id,
            "style_source_revision_id": self.style_source_revision_id,
            "source_revision_number": self.source_revision_number,
            "channel": self.channel,
            "locale": self.locale,
            "access_mode": self.access_mode,
            "source_url_hash": hashlib.sha256(self.source_url.encode()).hexdigest(),
            "source_locator_hash": self.source_locator_hash,
            "adapter_release": self.adapter_release,
            "authorization": self.authorization,
            "login_secret": self.login_secret.as_job_payload() if self.login_secret else None,
            "allowed_redirect_hosts": self.allowed_redirect_hosts,
            "robots_user_agent": self.robots_user_agent,
            "raw_artifact_id": self.raw_artifact_id,
            "derived_artifact_id": self.derived_artifact_id,
            "tmpfs": self.tmpfs,
            "maximum_redirects": self.maximum_redirects,
            "allow_proxy_rotation": False,
            "allow_stealth": False,
            "allow_captcha_solver": False,
        }


@dataclass(frozen=True, kw_only=True)
class RobotsAccessDecision:
    allowed: bool
    checked_at: datetime
    policy_hash: str

    def __post_init__(self) -> None:
        _require_aware_datetime(self.checked_at, "robots decision time")
        _require_hash(self.policy_hash, "robots policy")


@dataclass(frozen=True, kw_only=True)
class StylePageCapture:
    final_url: str
    navigation_chain: tuple[str, ...]
    raw_bundle: bytearray | None = field(repr=False)
    raw_media_type: str
    captured_at: datetime
    capture_release: str
    block_reason: CollectionBlockReason | None = None

    def __post_init__(self) -> None:
        _validate_safe_source_url(self.final_url)
        chain = tuple(self.navigation_chain)
        object.__setattr__(self, "navigation_chain", chain)
        if not chain or chain[-1] != self.final_url:
            raise SyntheticLabContractError("collection navigation chain must end at final URL")
        _require_text(self.raw_media_type, "collection raw media type")
        _require_aware_datetime(self.captured_at, "collection capture time")
        _require_text(self.capture_release, "collection capture release")
        if self.block_reason is None and not self.raw_bundle:
            raise SyntheticLabContractError("successful collection requires a raw bundle")


@dataclass(frozen=True, kw_only=True)
class ExtractedStyleText:
    payload: bytearray = field(repr=False)
    record_count: int
    parser_release: str

    def __post_init__(self) -> None:
        if not self.payload or self.record_count < 1:
            raise SyntheticLabContractError("style text extraction produced no records")
        _require_text(self.parser_release, "style text parser release")


@dataclass(frozen=True, kw_only=True)
class InspectedArtifact:
    inspection: RawArtifactInspection
    payload: bytearray = field(repr=False)

    def __post_init__(self) -> None:
        content_hash = hashlib.sha256(self.payload).hexdigest()
        expected = self.inspection.redacted_payload_hash or self.inspection.payload_hash
        if content_hash != expected:
            raise SyntheticLabContractError("inspected artifact payload does not match inspection")


@dataclass(frozen=True, kw_only=True)
class StyleCollectionOutput(SyntheticOnly):
    project_id: UUID
    collection_run_id: UUID
    outcome: CollectionOutcome
    final_url_hash: str
    navigation_chain_hash: str
    raw_manifest_hash: str | None
    derived_manifest_hash: str | None
    derived_content_hash: str | None
    extracted_record_count: int
    block_reason: CollectionBlockReason | None
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "collection output Project")
        _require_uuid(self.collection_run_id, "collection output Run")
        outcome = _as_enum(self.outcome, CollectionOutcome, "collection outcome")
        object.__setattr__(self, "outcome", outcome)
        _require_hash(self.final_url_hash, "collection final URL")
        _require_hash(self.navigation_chain_hash, "collection navigation chain")
        for value, label in (
            (self.raw_manifest_hash, "collection raw manifest"),
            (self.derived_manifest_hash, "collection derived manifest"),
            (self.derived_content_hash, "collection derived content"),
        ):
            if value is not None:
                _require_hash(value, label)
        if outcome is CollectionOutcome.CAPTURED:
            if (
                self.derived_manifest_hash is None
                or self.derived_content_hash is None
                or self.extracted_record_count < 1
                or self.block_reason is not None
            ):
                raise SyntheticLabContractError("captured collection output is incomplete")
        elif self.block_reason is None or any(
            value is not None
            for value in (
                self.raw_manifest_hash,
                self.derived_manifest_hash,
                self.derived_content_hash,
            )
        ):
            raise SyntheticLabContractError("blocked collection cannot carry persisted content")
        object.__setattr__(self, "result_hash", canonical_hash(self.value()))

    def value(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "collection_run_id": self.collection_run_id,
            "outcome": self.outcome,
            "final_url_hash": self.final_url_hash,
            "navigation_chain_hash": self.navigation_chain_hash,
            "raw_manifest_hash": self.raw_manifest_hash,
            "derived_manifest_hash": self.derived_manifest_hash,
            "derived_content_hash": self.derived_content_hash,
            "extracted_record_count": self.extracted_record_count,
            "block_reason": self.block_reason,
        }


class StyleCollectionSecretResolverPort(Protocol):
    def resolve(self, handle: SecretVersionHandle) -> SecretValue: ...


NavigationGuard = Callable[[str], None]


class StyleCollectorPort(Protocol):
    def check_robots(self, task: StyleCollectionTask, url: str) -> RobotsAccessDecision: ...

    def collect(
        self,
        task: StyleCollectionTask,
        *,
        credential: SecretValue | None,
        before_navigation: NavigationGuard,
    ) -> StylePageCapture: ...


class StyleTextExtractorPort(Protocol):
    def extract(self, task: StyleCollectionTask, capture: StylePageCapture) -> ExtractedStyleText: ...


class StyleArtifactInspectorPort(Protocol):
    def inspect_raw(
        self,
        task: StyleCollectionTask,
        capture: StylePageCapture,
    ) -> InspectedArtifact: ...

    def inspect_derived(
        self,
        task: StyleCollectionTask,
        capture: StylePageCapture,
        extracted: ExtractedStyleText,
    ) -> InspectedArtifact: ...


class StyleCollectionRepositoryPort(Protocol):
    def load(self, lease: WorkerLease) -> StyleCollectionTask: ...

    def finalize(
        self,
        *,
        connection: object,
        lease: WorkerLease,
        task: StyleCollectionTask,
        output: StyleCollectionOutput,
    ) -> None: ...

    def mark_attempt_orphaned(
        self,
        *,
        lease: WorkerLease,
        reason: str,
    ) -> None: ...


class StyleCollectionTaskStagingPort(Protocol):
    def stage(
        self,
        task: StyleCollectionTask,
        *,
        expected_job_input_hash: str,
    ) -> None: ...


def _validate_safe_source_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise SyntheticLabContractError(
            "collection URL must be credential-free HTTPS without query or fragment"
        )


__all__ = [
    "CollectionBlockReason",
    "CollectionOutcome",
    "ExtractedStyleText",
    "InspectedArtifact",
    "NavigationGuard",
    "RobotsAccessDecision",
    "StyleArtifactInspectorPort",
    "StyleCollectionExecutionError",
    "StyleCollectionOutput",
    "StyleCollectionRepositoryPort",
    "StyleCollectionTaskStagingPort",
    "StyleCollectionSecretResolverPort",
    "StyleCollectionTask",
    "StyleCollectorPort",
    "StylePageCapture",
    "StyleTextExtractorPort",
    "TmpfsCapturePolicy",
]
