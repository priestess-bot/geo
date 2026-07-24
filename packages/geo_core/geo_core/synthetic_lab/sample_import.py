"""Manual style-sample import validation and deterministic manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import math
from uuid import UUID

from geo_core.synthetic_lab.domain import (
    AU_ENGLISH_LOCALE,
    STANDARD_STYLE_CHANNELS,
    SyntheticLabContractError,
    SyntheticOnly,
    _as_enum,
    _canonical_hash,
    _require_aware_datetime,
    _require_hash,
    _require_text,
    _require_uuid,
    assert_same_project,
    assert_synthetic_boundary,
)


MAX_SHORT_EXAMPLE_CHARACTERS = 240
MAX_SHORT_EXAMPLE_SOURCE_OVERLAP = 0.35
_FORBIDDEN_CREDENTIAL_FRAGMENTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "storage_state",
    "token",
)


class SampleSourceRights(StrEnum):
    OWNED = "owned"
    LICENSED = "licensed"
    PUBLIC_REFERENCE = "public_reference"
    AUTHORIZED_MANUAL_CAPTURE = "authorized_manual_capture"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class SampleDedupStatus(StrEnum):
    UNIQUE = "unique"
    EXACT_DUPLICATE = "exact_duplicate"
    NEAR_DUPLICATE = "near_duplicate"
    CROSS_RUN_DUPLICATE = "cross_run_duplicate"


_ELIGIBLE_RIGHTS = frozenset(
    {
        SampleSourceRights.OWNED,
        SampleSourceRights.LICENSED,
        SampleSourceRights.PUBLIC_REFERENCE,
        SampleSourceRights.AUTHORIZED_MANUAL_CAPTURE,
    }
)


@dataclass(frozen=True, kw_only=True)
class ManualSampleRow(SyntheticOnly):
    row_number: int
    sample_id: UUID
    source_locator_hash: str
    source_artifact_hash: str
    normalized_text_hash: str
    text_length: int
    au_english_declared: bool
    language_reviewer_id: UUID | None
    language_reviewed_at: datetime | None
    anonymization_verified: bool
    unresolved_pii_codes: tuple[str, ...]
    dedup_status: SampleDedupStatus
    nearest_sample_hash: str | None
    source_rights: SampleSourceRights
    rights_evidence_hash: str | None
    source_overlap_ratio: float
    reproduction_risk: bool

    def __post_init__(self) -> None:
        if self.row_number < 1:
            raise SyntheticLabContractError("manual import row number must be positive")
        _require_uuid(self.sample_id, "manual import Sample ID")
        for hash_value, label in (
            (self.source_locator_hash, "manual import source locator hash"),
            (self.source_artifact_hash, "manual import source artifact hash"),
            (self.normalized_text_hash, "manual import normalized text hash"),
        ):
            _require_hash(hash_value, label)
        if self.text_length < 1:
            raise SyntheticLabContractError("manual import sample text length must be positive")
        if (self.language_reviewer_id is None) != (self.language_reviewed_at is None):
            raise SyntheticLabContractError(
                "language reviewer and review time must be supplied together"
            )
        if self.language_reviewer_id is not None:
            _require_uuid(self.language_reviewer_id, "language reviewer ID")
            _require_aware_datetime(
                self.language_reviewed_at,  # type: ignore[arg-type]
                "language review time",
            )
        pii_codes = tuple(self.unresolved_pii_codes)
        object.__setattr__(self, "unresolved_pii_codes", pii_codes)
        if len(pii_codes) != len(set(pii_codes)) or any(not code.strip() for code in pii_codes):
            raise SyntheticLabContractError("unresolved PII codes must be unique non-empty values")
        dedup = _as_enum(self.dedup_status, SampleDedupStatus, "sample dedup status")
        rights = _as_enum(self.source_rights, SampleSourceRights, "sample source rights")
        object.__setattr__(self, "dedup_status", dedup)
        object.__setattr__(self, "source_rights", rights)
        if dedup == SampleDedupStatus.UNIQUE and self.nearest_sample_hash is not None:
            raise SyntheticLabContractError("unique sample cannot bind a duplicate hash")
        if dedup != SampleDedupStatus.UNIQUE:
            if self.nearest_sample_hash is None:
                raise SyntheticLabContractError("duplicate sample requires nearest sample hash")
            _require_hash(self.nearest_sample_hash, "nearest sample hash")
        if self.rights_evidence_hash is not None:
            _require_hash(self.rights_evidence_hash, "sample rights evidence hash")
        if not math.isfinite(self.source_overlap_ratio) or not 0 <= self.source_overlap_ratio <= 1:
            raise SyntheticLabContractError("sample source overlap ratio must be in [0, 1]")


@dataclass(frozen=True, kw_only=True)
class ManualSampleImportRequest(SyntheticOnly):
    id: UUID
    project_id: UUID
    channel: str
    locale: str
    style_source_revision_id: UUID
    source_revision_number: int
    collection_run_id: UUID
    imported_by: UUID
    imported_at: datetime
    schema_release: str
    submitted_field_names: tuple[str, ...]
    rows: tuple[ManualSampleRow, ...]

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.id, "manual import request ID"),
            (self.project_id, "manual import Project ID"),
            (self.style_source_revision_id, "manual import Style Source revision ID"),
            (self.collection_run_id, "manual import Collection Run ID"),
            (self.imported_by, "manual import actor ID"),
        ):
            _require_uuid(uuid_value, label)
        if self.channel not in STANDARD_STYLE_CHANNELS:
            raise SyntheticLabContractError("manual import channel is unsupported")
        if self.locale != AU_ENGLISH_LOCALE:
            raise SyntheticLabContractError("manual style import requires locale 'en-AU'")
        if self.source_revision_number < 1:
            raise SyntheticLabContractError("manual import source revision must be positive")
        _require_aware_datetime(self.imported_at, "manual import time")
        _require_text(self.schema_release, "manual import schema release")
        fields = tuple(self.submitted_field_names)
        rows = tuple(self.rows)
        object.__setattr__(self, "submitted_field_names", fields)
        object.__setattr__(self, "rows", rows)
        if len(fields) != len(set(fields)) or any(not value.strip() for value in fields):
            raise SyntheticLabContractError(
                "manual import field names must be unique and non-empty"
            )
        forbidden = tuple(field for field in fields if _is_credential_field(field))
        if forbidden:
            raise SyntheticLabContractError("manual import schema cannot contain credential fields")
        if not rows:
            raise SyntheticLabContractError("manual import requires at least one row")
        if len({row.row_number for row in rows}) != len(rows):
            raise SyntheticLabContractError("manual import row numbers must be unique")
        if len({row.sample_id for row in rows}) != len(rows):
            raise SyntheticLabContractError("manual import Sample IDs must be unique")
        assert_synthetic_boundary(self, *rows)


@dataclass(frozen=True, kw_only=True)
class ManualImportRowError(SyntheticOnly):
    row_number: int
    code: str
    message: str
    evidence_hash: str

    def __post_init__(self) -> None:
        if self.row_number < 1:
            raise SyntheticLabContractError("manual import error row must be positive")
        _require_text(self.code, "manual import row error code")
        _require_text(self.message, "manual import row error message")
        _require_hash(self.evidence_hash, "manual import row error evidence hash")


@dataclass(frozen=True, kw_only=True)
class ImportedStyleSample(SyntheticOnly):
    id: UUID
    project_id: UUID
    request_id: UUID
    row_number: int
    channel: str
    locale: str
    style_source_revision_id: UUID
    source_revision_number: int
    collection_run_id: UUID
    normalized_text_hash: str
    source_locator_hash: str
    source_artifact_hash: str
    source_rights: SampleSourceRights
    rights_evidence_hash: str
    language_reviewer_id: UUID
    language_reviewed_at: datetime
    short_example_eligible: bool
    short_example_exclusion_codes: tuple[str, ...]
    anonymized: bool = field(default=True, init=False)
    au_english: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.id, "Imported Style Sample ID"),
            (self.project_id, "Imported Style Sample Project ID"),
            (self.request_id, "Imported Style Sample request ID"),
            (self.style_source_revision_id, "Imported Style Sample source revision ID"),
            (self.collection_run_id, "Imported Style Sample Collection Run ID"),
            (self.language_reviewer_id, "Imported Style Sample language reviewer ID"),
        ):
            _require_uuid(uuid_value, label)
        if self.row_number < 1 or self.source_revision_number < 1:
            raise SyntheticLabContractError("Imported Style Sample row/revision must be positive")
        if self.channel not in STANDARD_STYLE_CHANNELS or self.locale != AU_ENGLISH_LOCALE:
            raise SyntheticLabContractError("Imported Style Sample channel/locale is invalid")
        for hash_value, label in (
            (self.normalized_text_hash, "Imported Style Sample text hash"),
            (self.source_locator_hash, "Imported Style Sample locator hash"),
            (self.source_artifact_hash, "Imported Style Sample artifact hash"),
            (self.rights_evidence_hash, "Imported Style Sample rights hash"),
        ):
            _require_hash(hash_value, label)
        rights = _as_enum(self.source_rights, SampleSourceRights, "Imported Sample rights")
        object.__setattr__(self, "source_rights", rights)
        if rights not in _ELIGIBLE_RIGHTS:
            raise SyntheticLabContractError("Imported Style Sample rights are not eligible")
        _require_aware_datetime(self.language_reviewed_at, "Imported Sample language review time")
        exclusions = tuple(self.short_example_exclusion_codes)
        object.__setattr__(self, "short_example_exclusion_codes", exclusions)
        if self.short_example_eligible == bool(exclusions):
            raise SyntheticLabContractError(
                "short-example eligibility and exclusion markers are inconsistent"
            )


@dataclass(frozen=True, kw_only=True)
class ManualSampleImportManifest(SyntheticOnly):
    id: UUID
    project_id: UUID
    preview_id: UUID
    request_id: UUID
    channel: str
    locale: str
    imported_by: UUID
    imported_at: datetime
    schema_release: str
    row_count: int
    accepted_samples: tuple[ImportedStyleSample, ...]
    row_errors: tuple[ManualImportRowError, ...]
    duplicate_row_count: int
    input_hash: str
    manifest_hash: str

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.id, "manual import manifest ID"),
            (self.project_id, "manual import manifest Project ID"),
            (self.preview_id, "manual import preview ID"),
            (self.request_id, "manual import manifest request ID"),
            (self.imported_by, "manual import manifest actor ID"),
        ):
            _require_uuid(uuid_value, label)
        if self.channel not in STANDARD_STYLE_CHANNELS or self.locale != AU_ENGLISH_LOCALE:
            raise SyntheticLabContractError("manual import manifest channel/locale is invalid")
        _require_aware_datetime(self.imported_at, "manual import manifest time")
        _require_text(self.schema_release, "manual import manifest schema release")
        accepted = tuple(self.accepted_samples)
        errors = tuple(self.row_errors)
        object.__setattr__(self, "accepted_samples", accepted)
        object.__setattr__(self, "row_errors", errors)
        if self.row_count < 1 or self.duplicate_row_count < 0:
            raise SyntheticLabContractError("manual import manifest counts are invalid")
        if len(accepted) + len({item.row_number for item in errors}) != self.row_count:
            raise SyntheticLabContractError(
                "manual import manifest must account for every input row"
            )
        if len({item.id for item in accepted}) != len(accepted):
            raise SyntheticLabContractError("accepted Sample IDs must be unique")
        assert_same_project(self, *accepted)
        assert_synthetic_boundary(self, *accepted, *errors)
        _require_hash(self.input_hash, "manual import input hash")
        _require_hash(self.manifest_hash, "manual import manifest hash")
        if self.manifest_hash != manual_import_manifest_hash(self):
            raise SyntheticLabContractError("manual import manifest does not match its hash")

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_samples)

    @property
    def rejected_count(self) -> int:
        return self.row_count - self.accepted_count


def build_manual_import_manifest(
    request: ManualSampleImportRequest,
    *,
    manifest_id: UUID,
    preview_id: UUID,
) -> ManualSampleImportManifest:
    _require_uuid(manifest_id, "manual import manifest ID")
    _require_uuid(preview_id, "manual import preview ID")
    input_hash = manual_import_input_hash(request)
    accepted: list[ImportedStyleSample] = []
    errors: list[ManualImportRowError] = []
    seen_hashes: set[str] = set()
    duplicate_rows: set[int] = set()
    for row in sorted(request.rows, key=lambda value: value.row_number):
        row_errors = _validate_row(row, seen_hashes)
        if row.normalized_text_hash in seen_hashes:
            row_errors.append("duplicate_exact_in_batch")
        if row.dedup_status != SampleDedupStatus.UNIQUE or any(
            code.startswith("duplicate_") for code in row_errors
        ):
            duplicate_rows.add(row.row_number)
        if row_errors:
            errors.extend(_row_error(row, code) for code in sorted(set(row_errors)))
        else:
            accepted.append(_accepted_sample(request, row))
        seen_hashes.add(row.normalized_text_hash)
    provisional = object.__new__(ManualSampleImportManifest)
    values = {
        "id": manifest_id,
        "project_id": request.project_id,
        "preview_id": preview_id,
        "request_id": request.id,
        "channel": request.channel,
        "locale": request.locale,
        "imported_by": request.imported_by,
        "imported_at": request.imported_at,
        "schema_release": request.schema_release,
        "row_count": len(request.rows),
        "accepted_samples": tuple(accepted),
        "row_errors": tuple(errors),
        "duplicate_row_count": len(duplicate_rows),
        "input_hash": input_hash,
    }
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    manifest_hash = manual_import_manifest_hash(provisional)
    return ManualSampleImportManifest(**values, manifest_hash=manifest_hash)  # type: ignore[arg-type]


def manual_import_input_hash(request: ManualSampleImportRequest) -> str:
    return _canonical_hash(
        {
            "project_id": str(request.project_id),
            "channel": request.channel,
            "locale": request.locale,
            "style_source_revision_id": str(request.style_source_revision_id),
            "source_revision_number": request.source_revision_number,
            "collection_run_id": str(request.collection_run_id),
            "imported_by": str(request.imported_by),
            "imported_at": request.imported_at.isoformat(),
            "schema_release": request.schema_release,
            "submitted_field_names": list(request.submitted_field_names),
            "rows": [
                _row_value(row) for row in sorted(request.rows, key=lambda item: item.row_number)
            ],
        }
    )


def manual_import_manifest_hash(manifest: ManualSampleImportManifest) -> str:
    return _canonical_hash(
        {
            "preview_id": str(manifest.preview_id),
            "request_id": str(manifest.request_id),
            "input_hash": manifest.input_hash,
            "row_count": manifest.row_count,
            "duplicate_row_count": manifest.duplicate_row_count,
            "accepted": [
                {
                    "id": str(item.id),
                    "row_number": item.row_number,
                    "normalized_text_hash": item.normalized_text_hash,
                    "short_example_eligible": item.short_example_eligible,
                    "short_example_exclusion_codes": list(item.short_example_exclusion_codes),
                }
                for item in manifest.accepted_samples
            ],
            "errors": [
                {
                    "row_number": item.row_number,
                    "code": item.code,
                    "evidence_hash": item.evidence_hash,
                }
                for item in manifest.row_errors
            ],
        }
    )


def _validate_row(row: ManualSampleRow, seen_hashes: set[str]) -> list[str]:
    errors: list[str] = []
    if not row.au_english_declared:
        errors.append("au_english_not_declared")
    if row.language_reviewer_id is None:
        errors.append("language_review_missing")
    if not row.anonymization_verified or row.unresolved_pii_codes:
        errors.append("anonymization_failed")
    if row.dedup_status != SampleDedupStatus.UNIQUE:
        errors.append(f"duplicate_{row.dedup_status.value}")
    if row.normalized_text_hash in seen_hashes:
        errors.append("duplicate_exact_in_batch")
    if row.source_rights not in _ELIGIBLE_RIGHTS or row.rights_evidence_hash is None:
        errors.append("source_rights_ineligible")
    return errors


def _accepted_sample(
    request: ManualSampleImportRequest,
    row: ManualSampleRow,
) -> ImportedStyleSample:
    exclusions: list[str] = []
    if row.text_length > MAX_SHORT_EXAMPLE_CHARACTERS:
        exclusions.append("too_long_for_short_example")
    if row.source_overlap_ratio > MAX_SHORT_EXAMPLE_SOURCE_OVERLAP:
        exclusions.append("source_overlap_too_high")
    if row.reproduction_risk:
        exclusions.append("source_reproduction_risk")
    return ImportedStyleSample(
        id=row.sample_id,
        project_id=request.project_id,
        request_id=request.id,
        row_number=row.row_number,
        channel=request.channel,
        locale=request.locale,
        style_source_revision_id=request.style_source_revision_id,
        source_revision_number=request.source_revision_number,
        collection_run_id=request.collection_run_id,
        normalized_text_hash=row.normalized_text_hash,
        source_locator_hash=row.source_locator_hash,
        source_artifact_hash=row.source_artifact_hash,
        source_rights=row.source_rights,
        rights_evidence_hash=row.rights_evidence_hash,  # type: ignore[arg-type]
        language_reviewer_id=row.language_reviewer_id,  # type: ignore[arg-type]
        language_reviewed_at=row.language_reviewed_at,  # type: ignore[arg-type]
        short_example_eligible=not exclusions,
        short_example_exclusion_codes=tuple(exclusions),
    )


def _row_error(row: ManualSampleRow, code: str) -> ManualImportRowError:
    return ManualImportRowError(
        row_number=row.row_number,
        code=code,
        message=_ERROR_MESSAGES[code],
        evidence_hash=_canonical_hash(
            {"row_number": row.row_number, "code": code, "row_hash": row.normalized_text_hash}
        ),
    )


def _row_value(row: ManualSampleRow) -> dict[str, object]:
    return {
        "row_number": row.row_number,
        "sample_id": str(row.sample_id),
        "source_locator_hash": row.source_locator_hash,
        "source_artifact_hash": row.source_artifact_hash,
        "normalized_text_hash": row.normalized_text_hash,
        "text_length": row.text_length,
        "au_english_declared": row.au_english_declared,
        "language_reviewer_id": (
            str(row.language_reviewer_id) if row.language_reviewer_id else None
        ),
        "language_reviewed_at": (
            row.language_reviewed_at.isoformat() if row.language_reviewed_at else None
        ),
        "anonymization_verified": row.anonymization_verified,
        "unresolved_pii_codes": list(row.unresolved_pii_codes),
        "dedup_status": row.dedup_status.value,
        "nearest_sample_hash": row.nearest_sample_hash,
        "source_rights": row.source_rights.value,
        "rights_evidence_hash": row.rights_evidence_hash,
        "source_overlap_ratio": row.source_overlap_ratio,
        "reproduction_risk": row.reproduction_risk,
    }


def _is_credential_field(field_name: str) -> bool:
    normalized = field_name.strip().lower().replace("-", "_")
    return any(fragment in normalized for fragment in _FORBIDDEN_CREDENTIAL_FRAGMENTS)


_ERROR_MESSAGES = {
    "anonymization_failed": "Anonymization or PII verification did not pass.",
    "au_english_not_declared": "Australian English was not declared.",
    "duplicate_cross_run_duplicate": "The sample duplicates a prior run.",
    "duplicate_exact_duplicate": "The sample is an exact duplicate.",
    "duplicate_exact_in_batch": "The sample duplicates another row in this import.",
    "duplicate_near_duplicate": "The sample is a near duplicate.",
    "language_review_missing": "An Australian English reviewer is required.",
    "source_rights_ineligible": "Eligible source rights and evidence are required.",
}


__all__ = [
    "MAX_SHORT_EXAMPLE_CHARACTERS",
    "MAX_SHORT_EXAMPLE_SOURCE_OVERLAP",
    "ImportedStyleSample",
    "ManualImportRowError",
    "ManualSampleImportManifest",
    "ManualSampleImportRequest",
    "ManualSampleRow",
    "SampleDedupStatus",
    "SampleSourceRights",
    "build_manual_import_manifest",
    "manual_import_input_hash",
    "manual_import_manifest_hash",
]
