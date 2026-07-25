"""Immutable Style Source, Collection, Sample and Profile domain contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Literal, Mapping, Protocol, TypeVar
from urllib.parse import urlsplit
from uuid import UUID


STANDARD_STYLE_CHANNELS = frozenset(
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
AU_ENGLISH_LOCALE = "en-AU"
MIN_PROFILE_SAMPLE_COUNT = 200
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EnumT = TypeVar("_EnumT", bound=StrEnum)


class SyntheticLabContractError(ValueError):
    """A synthetic-lab value violates an immutable domain contract."""


class SyntheticLabScopeError(SyntheticLabContractError):
    """Related resources do not share the same Project or frozen lineage."""


class SyntheticLabTransitionError(SyntheticLabContractError):
    """A command is not allowed from the current lifecycle state."""


class ProjectScoped(Protocol):
    @property
    def project_id(self) -> UUID: ...


@dataclass(frozen=True, kw_only=True)
class SyntheticOnly:
    """Non-overridable visibility flags inherited by every lab resource."""

    synthetic: Literal[True] = field(default=True, init=False)
    test_only: Literal[True] = field(default=True, init=False)
    publication_eligible: Literal[False] = field(default=False, init=False)


class StyleAccessMode(StrEnum):
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    MANUAL_IMPORT = "manual_import"


class StyleSourceStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class CollectionRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StyleSampleReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class StyleProfileStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    FROZEN = "frozen"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


STYLE_SOURCE_TRANSITIONS: Mapping[StyleSourceStatus, Mapping[str, StyleSourceStatus]] = {
    StyleSourceStatus.DRAFT: MappingProxyType(
        {"activate": StyleSourceStatus.ACTIVE, "retire": StyleSourceStatus.RETIRED}
    ),
    StyleSourceStatus.ACTIVE: MappingProxyType(
        {"suspend": StyleSourceStatus.SUSPENDED, "retire": StyleSourceStatus.RETIRED}
    ),
    StyleSourceStatus.SUSPENDED: MappingProxyType(
        {"activate": StyleSourceStatus.ACTIVE, "retire": StyleSourceStatus.RETIRED}
    ),
    StyleSourceStatus.RETIRED: MappingProxyType({}),
}

COLLECTION_RUN_TRANSITIONS: Mapping[CollectionRunStatus, Mapping[str, CollectionRunStatus]] = {
    CollectionRunStatus.QUEUED: MappingProxyType(
        {"start": CollectionRunStatus.RUNNING, "cancel": CollectionRunStatus.CANCELLED}
    ),
    CollectionRunStatus.RUNNING: MappingProxyType(
        {
            "complete": CollectionRunStatus.COMPLETED,
            "fail": CollectionRunStatus.FAILED,
            "cancel": CollectionRunStatus.CANCELLED,
        }
    ),
    CollectionRunStatus.COMPLETED: MappingProxyType({}),
    CollectionRunStatus.FAILED: MappingProxyType({}),
    CollectionRunStatus.CANCELLED: MappingProxyType({}),
}

STYLE_PROFILE_TRANSITIONS: Mapping[StyleProfileStatus, Mapping[str, StyleProfileStatus]] = {
    StyleProfileStatus.DRAFT: MappingProxyType({"submit": StyleProfileStatus.IN_REVIEW}),
    StyleProfileStatus.IN_REVIEW: MappingProxyType(
        {"approve": StyleProfileStatus.APPROVED, "reject": StyleProfileStatus.REJECTED}
    ),
    StyleProfileStatus.APPROVED: MappingProxyType({"freeze": StyleProfileStatus.FROZEN}),
    StyleProfileStatus.FROZEN: MappingProxyType({"supersede": StyleProfileStatus.SUPERSEDED}),
    StyleProfileStatus.REJECTED: MappingProxyType({}),
    StyleProfileStatus.SUPERSEDED: MappingProxyType({}),
}


def _require_uuid(value: UUID, label: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise SyntheticLabContractError(f"{label} must be a non-zero UUID")


def _require_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SyntheticLabContractError(f"{label} must not be empty")


def _require_hash(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise SyntheticLabContractError(f"{label} must be lowercase SHA-256")


def _require_aware_datetime(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SyntheticLabContractError(f"{label} must include a timezone")


def _require_channel(channel: str) -> None:
    if channel not in STANDARD_STYLE_CHANNELS:
        raise SyntheticLabContractError(f"unsupported style channel: {channel!r}")


def _require_locale(locale: str) -> None:
    if locale != AU_ENGLISH_LOCALE:
        raise SyntheticLabContractError("synthetic style resources must use locale 'en-AU'")


def _as_enum(value: object, enum_type: type[_EnumT], label: str) -> _EnumT:
    try:
        return enum_type(str(value))
    except (TypeError, ValueError) as exc:
        raise SyntheticLabContractError(f"unsupported {label}: {value!r}") from exc


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, kw_only=True)
class StyleSource(SyntheticOnly):
    id: UUID
    project_id: UUID
    source_id: UUID
    revision_number: int
    channel: str
    access_mode: StyleAccessMode
    locale: str
    source_locator_hash: str
    status: StyleSourceStatus = StyleSourceStatus.DRAFT
    source_url: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "Style Source revision ID"),
            (self.project_id, "Style Source Project ID"),
            (self.source_id, "Style Source identity"),
        ):
            _require_uuid(value, label)
        if self.revision_number < 1:
            raise SyntheticLabContractError("Style Source revision number must be positive")
        _require_channel(self.channel)
        _require_locale(self.locale)
        _require_hash(self.source_locator_hash, "Style Source locator hash")
        if self.source_url is not None:
            parsed = urlsplit(self.source_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or hashlib.sha256(self.source_url.encode()).hexdigest() != self.source_locator_hash
            ):
                raise SyntheticLabContractError(
                    "Style Source URL must be credential-free HTTPS matching its locator hash"
                )
        object.__setattr__(
            self,
            "access_mode",
            _as_enum(self.access_mode, StyleAccessMode, "Style Source access mode"),
        )
        object.__setattr__(
            self,
            "status",
            _as_enum(self.status, StyleSourceStatus, "Style Source status"),
        )


@dataclass(frozen=True, kw_only=True)
class CollectionRun(SyntheticOnly):
    id: UUID
    project_id: UUID
    style_source_revision_id: UUID
    source_revision_number: int
    source_locator_hash: str
    adapter_release: str
    checkpoint_hash: str | None = None
    status: CollectionRunStatus = CollectionRunStatus.QUEUED
    raw_manifest_hash: str | None = None
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "Collection Run ID"),
            (self.project_id, "Collection Run Project ID"),
            (self.style_source_revision_id, "Collection Run Style Source revision ID"),
        ):
            _require_uuid(value, label)
        if self.source_revision_number < 1:
            raise SyntheticLabContractError("Collection Run source revision must be positive")
        _require_hash(self.source_locator_hash, "Collection Run source locator hash")
        _require_text(self.adapter_release, "Collection Run adapter release")
        if self.checkpoint_hash is not None:
            _require_hash(self.checkpoint_hash, "Collection Run checkpoint hash")
        if self.raw_manifest_hash is not None:
            _require_hash(self.raw_manifest_hash, "Collection Run raw manifest hash")
        status = _as_enum(self.status, CollectionRunStatus, "Collection Run status")
        object.__setattr__(self, "status", status)
        if status == CollectionRunStatus.COMPLETED:
            if self.raw_manifest_hash is None:
                raise SyntheticLabContractError(
                    "completed Collection Run requires a raw manifest hash"
                )
            if self.terminal_reason is not None:
                raise SyntheticLabContractError(
                    "completed Collection Run cannot carry a terminal reason"
                )
        elif status in {CollectionRunStatus.FAILED, CollectionRunStatus.CANCELLED}:
            _require_text(self.terminal_reason or "", "Collection Run terminal reason")
        elif self.terminal_reason is not None:
            raise SyntheticLabContractError(
                "non-terminal Collection Run cannot carry a terminal reason"
            )


@dataclass(frozen=True, kw_only=True)
class StyleSample(SyntheticOnly):
    id: UUID
    project_id: UUID
    collection_run_id: UUID
    style_source_revision_id: UUID
    source_revision_number: int
    channel: str
    locale: str
    content_hash: str
    is_anonymized: bool
    is_au_english: bool
    review_status: StyleSampleReviewStatus = StyleSampleReviewStatus.PENDING_REVIEW
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "Style Sample ID"),
            (self.project_id, "Style Sample Project ID"),
            (self.collection_run_id, "Style Sample Collection Run ID"),
            (self.style_source_revision_id, "Style Sample source revision ID"),
        ):
            _require_uuid(value, label)
        if self.source_revision_number < 1:
            raise SyntheticLabContractError("Style Sample source revision must be positive")
        _require_channel(self.channel)
        _require_locale(self.locale)
        _require_hash(self.content_hash, "Style Sample content hash")
        status = _as_enum(
            self.review_status,
            StyleSampleReviewStatus,
            "Style Sample review status",
        )
        object.__setattr__(self, "review_status", status)
        if status == StyleSampleReviewStatus.PENDING_REVIEW:
            if self.reviewed_by is not None or self.reviewed_at is not None:
                raise SyntheticLabContractError(
                    "pending Style Sample cannot carry review attribution"
                )
            return
        if self.reviewed_by is None or self.reviewed_at is None:
            raise SyntheticLabContractError(
                "reviewed Style Sample requires reviewer and review time"
            )
        _require_uuid(self.reviewed_by, "Style Sample reviewer")
        _require_aware_datetime(self.reviewed_at, "Style Sample review time")
        if status == StyleSampleReviewStatus.APPROVED and not (
            self.is_anonymized and self.is_au_english
        ):
            raise SyntheticLabContractError(
                "approved Style Sample must be anonymized Australian English"
            )


@dataclass(frozen=True, kw_only=True)
class StyleProfileVersion(SyntheticOnly):
    id: UUID
    project_id: UUID
    profile_id: UUID
    version_number: int
    channel: str
    locale: str
    corpus_hash: str
    profile_hash: str
    prompt_release_id: UUID
    prompt_release_hash: str
    approved_sample_count: int
    status: StyleProfileStatus = StyleProfileStatus.DRAFT
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "Style Profile version ID"),
            (self.project_id, "Style Profile Project ID"),
            (self.profile_id, "Style Profile identity"),
            (self.prompt_release_id, "Style Profile Prompt Release ID"),
        ):
            _require_uuid(value, label)
        if self.version_number < 1:
            raise SyntheticLabContractError("Style Profile version number must be positive")
        if self.approved_sample_count < 0:
            raise SyntheticLabContractError("Style Profile sample count cannot be negative")
        _require_channel(self.channel)
        _require_locale(self.locale)
        _require_hash(self.corpus_hash, "Style Profile corpus hash")
        _require_hash(self.profile_hash, "Style Profile content hash")
        _require_hash(self.prompt_release_hash, "Style Profile Prompt Release hash")
        status = _as_enum(self.status, StyleProfileStatus, "Style Profile status")
        object.__setattr__(self, "status", status)
        reviewed_states = {
            StyleProfileStatus.APPROVED,
            StyleProfileStatus.FROZEN,
            StyleProfileStatus.REJECTED,
            StyleProfileStatus.SUPERSEDED,
        }
        if status in reviewed_states:
            if self.reviewed_by is None or self.reviewed_at is None:
                raise SyntheticLabContractError(
                    "reviewed Style Profile requires reviewer and review time"
                )
            _require_uuid(self.reviewed_by, "Style Profile reviewer")
            _require_aware_datetime(self.reviewed_at, "Style Profile review time")
        elif self.reviewed_by is not None or self.reviewed_at is not None:
            raise SyntheticLabContractError(
                "unreviewed Style Profile cannot carry review attribution"
            )
        if status in {StyleProfileStatus.FROZEN, StyleProfileStatus.SUPERSEDED}:
            if self.approved_sample_count < MIN_PROFILE_SAMPLE_COUNT:
                raise SyntheticLabContractError(
                    "frozen Style Profile requires at least 200 approved samples"
                )


@dataclass(frozen=True, kw_only=True)
class StyleProfileSampleManifest(SyntheticOnly):
    project_id: UUID
    profile_version_id: UUID
    corpus_hash: str
    sample_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "Style Profile sample manifest Project")
        _require_uuid(self.profile_version_id, "Style Profile sample manifest Profile")
        _require_hash(self.corpus_hash, "Style Profile sample manifest corpus")
        if len(self.sample_ids) < 200 or len(self.sample_ids) > 10_000:
            raise SyntheticLabContractError(
                "Style Profile sample manifest requires 200 to 10000 samples"
            )
        if len(self.sample_ids) != len(set(self.sample_ids)):
            raise SyntheticLabContractError(
                "Style Profile sample manifest cannot contain duplicate samples"
            )
        for sample_id in self.sample_ids:
            _require_uuid(sample_id, "Style Profile sample manifest sample")


def assert_same_project(*resources: ProjectScoped) -> UUID:
    if not resources:
        raise SyntheticLabScopeError("Project scope check requires at least one resource")
    project_id = resources[0].project_id
    _require_uuid(project_id, "Project scope")
    if any(resource.project_id != project_id for resource in resources[1:]):
        raise SyntheticLabScopeError("synthetic-lab resources belong to different Projects")
    return project_id


def assert_synthetic_boundary(*resources: SyntheticOnly) -> None:
    if not resources:
        raise SyntheticLabContractError("synthetic boundary check requires a resource")
    for resource in resources:
        if not resource.synthetic or not resource.test_only or resource.publication_eligible:
            raise SyntheticLabContractError(
                "synthetic-lab resources must remain test-only and publication-ineligible"
            )


def assert_next_style_source_revision(previous: StyleSource, current: StyleSource) -> None:
    assert_same_project(previous, current)
    if current.source_id != previous.source_id or current.id == previous.id:
        raise SyntheticLabScopeError("Style Source revisions do not share immutable identity")
    if current.revision_number != previous.revision_number + 1:
        raise SyntheticLabContractError("Style Source revision history must be contiguous")


def assert_collection_run_lineage(source: StyleSource, run: CollectionRun) -> None:
    assert_same_project(source, run)
    if (
        run.style_source_revision_id != source.id
        or run.source_revision_number != source.revision_number
        or run.source_locator_hash != source.source_locator_hash
    ):
        raise SyntheticLabScopeError("Collection Run does not bind the frozen Style Source")


def assert_style_sample_lineage(
    source: StyleSource,
    run: CollectionRun,
    sample: StyleSample,
) -> None:
    assert_collection_run_lineage(source, run)
    assert_same_project(source, run, sample)
    if (
        sample.collection_run_id != run.id
        or sample.style_source_revision_id != source.id
        or sample.source_revision_number != source.revision_number
        or sample.channel != source.channel
        or sample.locale != source.locale
    ):
        raise SyntheticLabScopeError("Style Sample does not match its frozen collection lineage")


def style_sample_manifest_hash(samples: tuple[StyleSample, ...]) -> str:
    ordered = sorted(samples, key=lambda sample: (sample.content_hash, str(sample.id)))
    return _canonical_hash(
        [
            {
                "id": str(sample.id),
                "content_hash": sample.content_hash,
                "channel": sample.channel,
                "locale": sample.locale,
            }
            for sample in ordered
        ]
    )


def assert_profile_sample_set(
    profile: StyleProfileVersion,
    samples: tuple[StyleSample, ...],
) -> None:
    if not samples:
        raise SyntheticLabContractError("Style Profile requires approved samples")
    assert_same_project(profile, *samples)
    if len({sample.id for sample in samples}) != len(samples):
        raise SyntheticLabContractError("Style Profile sample IDs must be unique")
    if len({sample.content_hash for sample in samples}) != len(samples):
        raise SyntheticLabContractError("Style Profile cannot weight duplicate sample content")
    if any(
        sample.channel != profile.channel
        or sample.locale != profile.locale
        or sample.review_status != StyleSampleReviewStatus.APPROVED
        for sample in samples
    ):
        raise SyntheticLabScopeError(
            "Style Profile samples must be approved and match its channel and locale"
        )
    if len(samples) != profile.approved_sample_count:
        raise SyntheticLabContractError("Style Profile approved sample count does not match")
    if style_sample_manifest_hash(samples) != profile.corpus_hash:
        raise SyntheticLabContractError("Style Profile corpus does not match its frozen hash")


def assert_next_profile_version(
    previous: StyleProfileVersion,
    current: StyleProfileVersion,
) -> None:
    assert_same_project(previous, current)
    if current.profile_id != previous.profile_id or current.id == previous.id:
        raise SyntheticLabScopeError("Style Profile versions do not share immutable identity")
    if current.channel != previous.channel or current.locale != previous.locale:
        raise SyntheticLabScopeError("Style Profile identity cannot change channel or locale")
    if current.version_number != previous.version_number + 1:
        raise SyntheticLabContractError("Style Profile version history must be contiguous")


def _target_status(
    *,
    current: _EnumT,
    command: str,
    transitions: Mapping[_EnumT, Mapping[str, _EnumT]],
    label: str,
) -> _EnumT:
    from geo_core.synthetic_lab.domain_lifecycle import _target_status as implementation

    return implementation(
        current=current,
        command=command,
        transitions=transitions,
        label=label,
    )


def transition_style_source(source: StyleSource, *, command: str) -> StyleSource:
    from geo_core.synthetic_lab.domain_lifecycle import transition_style_source as implementation

    return implementation(source, command=command)


def transition_collection_run(
    run: CollectionRun,
    *,
    command: str,
    raw_manifest_hash: str | None = None,
    reason: str | None = None,
) -> CollectionRun:
    from geo_core.synthetic_lab.domain_lifecycle import (
        transition_collection_run as implementation,
    )

    return implementation(
        run,
        command=command,
        raw_manifest_hash=raw_manifest_hash,
        reason=reason,
    )


def transition_style_sample_review(
    sample: StyleSample,
    *,
    command: str,
    reviewer_id: UUID,
    reviewed_at: datetime,
) -> StyleSample:
    from geo_core.synthetic_lab.domain_lifecycle import (
        transition_style_sample_review as implementation,
    )

    return implementation(
        sample,
        command=command,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
    )
