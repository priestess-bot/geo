"""Strict parsing and safe previews for governed manual style-sample imports."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import hashlib
import io
import json
import re
import unicodedata
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.domain import (
    AU_ENGLISH_LOCALE,
    STANDARD_STYLE_CHANNELS,
    SyntheticLabContractError,
    SyntheticOnly,
    _require_aware_datetime,
    _require_hash,
    _require_text,
    _require_uuid,
)
from geo_core.synthetic_lab.raw_artifact_governance import (
    ArtifactAccessClass,
    ArtifactForm,
    RawArtifactInspection,
)
from geo_core.synthetic_lab.sample_import import (
    ManualSampleImportRequest,
    ManualSampleRow,
    SampleDedupStatus,
    SampleSourceRights,
)


MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 2_000
MAX_ROW_CHARACTERS = 100_000
PREVIEW_SCHEMA_RELEASE = "synthetic-manual-import-preview.v1"
PARSER_RELEASE = "synthetic-manual-import-parser.v1"
SCANNER_RELEASE = "synthetic-manual-import-scanner.v1"
ANONYMIZER_RELEASE = "synthetic-manual-import-anonymizer.v1"

_ALLOWED_FIELDS = frozenset({"text", "source_locator", "source_rights", "rights_evidence"})
_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?:authorization\s*[:=]|bearer\s+[a-z0-9._~+/=-]{12,}|"
    r"(?:api[_ -]?key|password|passwd|session[_ -]?(?:id|token)|"
    r"access[_ -]?token|refresh[_ -]?token|cookie)\s*[:=])"
)
_EMAIL_PATTERN = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?61[\s().-]*[2-478]|0[2-478])(?:[\s().-]*\d){8}(?!\d)"
)
_ACCOUNT_URL_PATTERN = re.compile(
    r"https?://[^\s/]+/(?:u(?:ser)?|profile|account|people|member)s?/[^\s?#]+",
    re.IGNORECASE,
)
_HANDLE_PATTERN = re.compile(r"(?<![\w@])@[A-Za-z0-9_][A-Za-z0-9_.-]{2,30}")
_SPACE_PATTERN = re.compile(r"[ \t\f\v]+")
_MULTI_NEWLINE_PATTERN = re.compile(r"\n{3,}")


class ManualImportFormat(StrEnum):
    TEXT = "text"
    CSV = "csv"
    JSONL = "jsonl"


class PreviewRowDisposition(StrEnum):
    READY_FOR_REVIEW = "ready_for_review"
    BLOCKED = "blocked"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, kw_only=True)
class ManualImportUpload(SyntheticOnly):
    preview_id: UUID
    project_id: UUID
    style_source_revision_id: UUID
    source_revision_number: int
    channel: str
    locale: str
    filename: str
    import_format: ManualImportFormat
    content: bytes = field(repr=False)
    default_source_rights: SampleSourceRights
    rights_evidence_reference: str
    submitted_by: UUID
    submitted_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for value, label in (
            (self.preview_id, "manual import preview"),
            (self.project_id, "manual import Project"),
            (self.style_source_revision_id, "manual import Style Source"),
            (self.submitted_by, "manual import submitter"),
        ):
            _require_uuid(value, label)
        if self.channel not in STANDARD_STYLE_CHANNELS or self.locale != AU_ENGLISH_LOCALE:
            raise SyntheticLabContractError("manual import channel/locale is unsupported")
        if self.source_revision_number < 1:
            raise SyntheticLabContractError("manual import source revision must be positive")
        filename = self.filename.strip()
        if not filename or len(filename) > 255 or filename in {".", ".."}:
            raise SyntheticLabContractError("manual import filename is invalid")
        if "/" in filename or "\\" in filename or "\x00" in filename:
            raise SyntheticLabContractError("manual import filename must not contain a path")
        object.__setattr__(self, "filename", filename)
        try:
            import_format = ManualImportFormat(self.import_format)
            rights = SampleSourceRights(self.default_source_rights)
        except ValueError as error:
            raise SyntheticLabContractError("manual import format or source rights is invalid") from error
        if rights in {SampleSourceRights.RESTRICTED, SampleSourceRights.UNKNOWN}:
            raise SyntheticLabContractError("manual import source rights are not eligible")
        object.__setattr__(self, "import_format", import_format)
        object.__setattr__(self, "default_source_rights", rights)
        _require_text(self.rights_evidence_reference, "manual import rights evidence")
        if len(self.rights_evidence_reference) > 2_000:
            raise SyntheticLabContractError("manual import rights evidence is too long")
        _require_aware_datetime(self.submitted_at, "manual import submission time")
        _require_aware_datetime(self.expires_at, "manual import expiry")
        if self.expires_at <= self.submitted_at:
            raise SyntheticLabContractError("manual import preview must expire after submission")
        if not self.content or len(self.content) > MAX_IMPORT_BYTES:
            raise SyntheticLabContractError("manual import file must be between 1 byte and 5 MiB")


@dataclass(frozen=True, kw_only=True)
class ManualImportPreviewRow(SyntheticOnly):
    row_number: int
    redacted_text: str
    normalized_text_hash: str
    source_locator_hash: str
    source_rights: SampleSourceRights
    rights_evidence_hash: str
    detected_codes: tuple[str, ...]
    blocking_codes: tuple[str, ...]
    disposition: PreviewRowDisposition

    def __post_init__(self) -> None:
        if self.row_number < 1 or not self.redacted_text:
            raise SyntheticLabContractError("manual import preview row is invalid")
        if len(self.redacted_text) > MAX_ROW_CHARACTERS:
            raise SyntheticLabContractError("manual import preview row is too long")
        for value, label in (
            (self.normalized_text_hash, "preview text"),
            (self.source_locator_hash, "preview source locator"),
            (self.rights_evidence_hash, "preview rights evidence"),
        ):
            _require_hash(value, label)
        detected, blocking = tuple(self.detected_codes), tuple(self.blocking_codes)
        if len(set(detected)) != len(detected) or len(set(blocking)) != len(blocking):
            raise SyntheticLabContractError("manual import preview codes must be unique")
        object.__setattr__(self, "detected_codes", detected)
        object.__setattr__(self, "blocking_codes", blocking)
        disposition = PreviewRowDisposition(self.disposition)
        object.__setattr__(self, "disposition", disposition)
        if (disposition is PreviewRowDisposition.READY_FOR_REVIEW) == bool(blocking):
            raise SyntheticLabContractError("manual import preview disposition is inconsistent")

    @property
    def selectable(self) -> bool:
        return self.disposition is PreviewRowDisposition.READY_FOR_REVIEW


@dataclass(frozen=True, kw_only=True)
class ManualImportPreview(SyntheticOnly):
    preview_id: UUID
    project_id: UUID
    style_source_revision_id: UUID
    channel: str
    filename: str
    import_format: ManualImportFormat
    submitted_by: UUID
    submitted_at: datetime
    expires_at: datetime
    upload_plaintext_hash: str
    rows: tuple[ManualImportPreviewRow, ...]
    schema_release: str = PREVIEW_SCHEMA_RELEASE
    parser_release: str = PARSER_RELEASE
    scanner_release: str = SCANNER_RELEASE
    anonymizer_release: str = ANONYMIZER_RELEASE
    preview_manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.preview_id, "manual import preview"),
            (self.project_id, "manual import preview Project"),
            (self.style_source_revision_id, "manual import preview source"),
            (self.submitted_by, "manual import preview submitter"),
        ):
            _require_uuid(value, label)
        _require_hash(self.upload_plaintext_hash, "manual import upload")
        rows = tuple(self.rows)
        if not rows or len(rows) > MAX_IMPORT_ROWS:
            raise SyntheticLabContractError("manual import preview row count is invalid")
        if tuple(row.row_number for row in rows) != tuple(range(1, len(rows) + 1)):
            raise SyntheticLabContractError("manual import preview rows are not contiguous")
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "preview_manifest_hash", canonical_hash(self.manifest_value()))

    @property
    def selectable_count(self) -> int:
        return sum(row.selectable for row in self.rows)

    @property
    def blocked_count(self) -> int:
        return len(self.rows) - self.selectable_count

    def manifest_value(self) -> dict[str, object]:
        return {
            "schema_release": self.schema_release,
            "preview_id": str(self.preview_id),
            "project_id": str(self.project_id),
            "style_source_revision_id": str(self.style_source_revision_id),
            "channel": self.channel,
            "filename": self.filename,
            "import_format": self.import_format.value,
            "submitted_by": str(self.submitted_by),
            "submitted_at": self.submitted_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "upload_plaintext_hash": self.upload_plaintext_hash,
            "parser_release": self.parser_release,
            "scanner_release": self.scanner_release,
            "anonymizer_release": self.anonymizer_release,
            "rows": [_row_manifest(row) for row in self.rows],
        }


@dataclass(frozen=True, kw_only=True)
class ManualImportApproval(SyntheticOnly):
    selected_row_numbers: tuple[int, ...]
    approved_by: UUID
    approved_at: datetime
    au_english_verified: bool
    anonymization_verified: bool

    def __post_init__(self) -> None:
        selected = tuple(sorted(self.selected_row_numbers))
        if not selected or selected[0] < 1 or len(selected) != len(set(selected)):
            raise SyntheticLabContractError("manual import approval rows are invalid")
        object.__setattr__(self, "selected_row_numbers", selected)
        _require_uuid(self.approved_by, "manual import approver")
        _require_aware_datetime(self.approved_at, "manual import approval time")
        if not self.au_english_verified or not self.anonymization_verified:
            raise SyntheticLabContractError("manual import approval requires both review declarations")


def preview_manual_import(upload: ManualImportUpload) -> ManualImportPreview:
    rows = _parse_rows(upload)
    seen: set[str] = set()
    preview_rows: list[ManualImportPreviewRow] = []
    for row_number, raw in enumerate(rows, start=1):
        preview_row = _preview_row(upload, row_number, raw, seen)
        preview_rows.append(preview_row)
        seen.add(preview_row.normalized_text_hash)
    return ManualImportPreview(
        preview_id=upload.preview_id,
        project_id=upload.project_id,
        style_source_revision_id=upload.style_source_revision_id,
        channel=upload.channel,
        filename=upload.filename,
        import_format=upload.import_format,
        submitted_by=upload.submitted_by,
        submitted_at=upload.submitted_at,
        expires_at=upload.expires_at,
        upload_plaintext_hash=hashlib.sha256(upload.content).hexdigest(),
        rows=tuple(preview_rows),
    )


def build_approved_manual_import(
    upload: ManualImportUpload,
    preview: ManualImportPreview,
    approval: ManualImportApproval,
) -> tuple[ManualSampleImportRequest, tuple[RawArtifactInspection, ...], dict[UUID, bytes]]:
    if preview_manual_import(upload).preview_manifest_hash != preview.preview_manifest_hash:
        raise SyntheticLabContractError("manual import preview changed before approval")
    if approval.approved_by == upload.submitted_by:
        raise SyntheticLabContractError("manual import maker and approver must be different actors")
    if approval.approved_at >= upload.expires_at:
        raise SyntheticLabContractError("manual import preview expired before approval")
    selected = set(approval.selected_row_numbers)
    by_number = {row.row_number: row for row in preview.rows}
    if selected - set(by_number) or any(not by_number[number].selectable for number in selected):
        raise SyntheticLabContractError("manual import approval selected a blocked row")
    request_id = uuid5(preview.preview_id, "approved-request")
    collection_run_id = uuid5(preview.preview_id, "approved-collection-run")
    rows: list[ManualSampleRow] = []
    inspections: list[RawArtifactInspection] = []
    payloads: dict[UUID, bytes] = {}
    for number in sorted(selected):
        item = by_number[number]
        sample_id = uuid5(preview.preview_id, f"approved-sample:{number}")
        artifact_id = sample_id
        payload = item.redacted_text.encode("utf-8")
        rows.append(
            ManualSampleRow(
                row_number=number,
                sample_id=sample_id,
                source_locator_hash=item.source_locator_hash,
                source_artifact_hash=item.normalized_text_hash,
                normalized_text_hash=item.normalized_text_hash,
                text_length=len(item.redacted_text),
                au_english_declared=True,
                language_reviewer_id=approval.approved_by,
                language_reviewed_at=approval.approved_at,
                anonymization_verified=True,
                unresolved_pii_codes=(),
                dedup_status=SampleDedupStatus.UNIQUE,
                nearest_sample_hash=None,
                source_rights=item.source_rights,
                rights_evidence_hash=item.rights_evidence_hash,
                source_overlap_ratio=0.0,
                reproduction_risk=False,
            )
        )
        inspections.append(
            RawArtifactInspection(
                artifact_id=artifact_id,
                project_id=upload.project_id,
                captured_at=approval.approved_at,
                access_class=ArtifactAccessClass.RESTRICTED,
                form=ArtifactForm.DERIVED,
                payload_hash=item.normalized_text_hash,
                detected_findings=(),
                unresolved_findings=(),
                redaction_applied=False,
                redaction_verified=True,
                redacted_payload_hash=None,
                anonymization_verified=True,
                policy_max_ttl_days=None,
            )
        )
        payloads[artifact_id] = payload
    request = ManualSampleImportRequest(
        id=request_id,
        project_id=upload.project_id,
        channel=upload.channel,
        locale=upload.locale,
        style_source_revision_id=upload.style_source_revision_id,
        source_revision_number=upload.source_revision_number,
        collection_run_id=collection_run_id,
        imported_by=approval.approved_by,
        imported_at=approval.approved_at,
        schema_release=PREVIEW_SCHEMA_RELEASE,
        submitted_field_names=("text", "source_locator", "source_rights", "rights_evidence"),
        rows=tuple(rows),
    )
    return request, tuple(inspections), payloads


def _parse_rows(upload: ManualImportUpload) -> list[dict[str, str]]:
    try:
        text = upload.content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise SyntheticLabContractError("manual import file must be valid UTF-8") from error
    if "\x00" in text:
        raise SyntheticLabContractError("manual import file contains a NUL byte")
    if upload.import_format is ManualImportFormat.TEXT:
        values = [line.strip() for line in text.splitlines() if line.strip()]
        rows = [{"text": value} for value in values]
    elif upload.import_format is ManualImportFormat.CSV:
        rows = _parse_csv(text)
    else:
        rows = _parse_jsonl(text)
    if not rows or len(rows) > MAX_IMPORT_ROWS:
        raise SyntheticLabContractError("manual import must contain 1 to 2,000 rows")
    return rows


def _parse_csv(text: str) -> list[dict[str, str]]:
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = reader.fieldnames
        if headers is None or len(headers) != len(set(headers)) or "text" not in headers:
            raise SyntheticLabContractError("CSV requires unique headers including text")
        if set(headers) - _ALLOWED_FIELDS:
            raise SyntheticLabContractError("CSV contains unsupported fields")
        rows = []
        for row in reader:
            if None in row:
                raise SyntheticLabContractError("CSV row has more values than headers")
            rows.append({key: value or "" for key, value in row.items()})
        return rows
    except csv.Error as error:
        raise SyntheticLabContractError("manual import CSV is invalid") from error


def _parse_jsonl(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise SyntheticLabContractError(f"JSONL line {line_number} is invalid") from error
        if not isinstance(value, dict) or "text" not in value or set(value) - _ALLOWED_FIELDS:
            raise SyntheticLabContractError(f"JSONL line {line_number} has unsupported fields")
        if any(not isinstance(item, str) for item in value.values()):
            raise SyntheticLabContractError(f"JSONL line {line_number} values must be strings")
        rows.append(dict(value))
    return rows


def _preview_row(
    upload: ManualImportUpload,
    row_number: int,
    raw: dict[str, str],
    seen: set[str],
) -> ManualImportPreviewRow:
    original = _normalize_text(raw.get("text", ""))
    if not original:
        raise SyntheticLabContractError(f"manual import row {row_number} has no text")
    if len(original) > MAX_ROW_CHARACTERS:
        raise SyntheticLabContractError(f"manual import row {row_number} is too long")
    blocking: list[str] = []
    detected: list[str] = []
    if _CREDENTIAL_PATTERN.search(original):
        blocking.append("credential_material")
    redacted = original
    for pattern, replacement, code in (
        (_EMAIL_PATTERN, "[redacted-email]", "email_redacted"),
        (_PHONE_PATTERN, "[redacted-phone]", "phone_redacted"),
        (_ACCOUNT_URL_PATTERN, "[redacted-account-url]", "account_url_redacted"),
        (_HANDLE_PATTERN, "[redacted-handle]", "handle_redacted"),
    ):
        redacted, count = pattern.subn(replacement, redacted)
        if count:
            detected.append(code)
    redacted = _normalize_text(redacted)
    text_hash = hashlib.sha256(redacted.encode()).hexdigest()
    if text_hash in seen:
        blocking.append("duplicate_exact_in_upload")
    rights = _row_rights(raw.get("source_rights", ""), upload.default_source_rights, row_number)
    evidence = (raw.get("rights_evidence", "").strip() or upload.rights_evidence_reference)
    if len(evidence) > 2_000:
        raise SyntheticLabContractError(f"manual import row {row_number} rights evidence is too long")
    locator = raw.get("source_locator", "").strip() or f"{upload.filename}#row-{row_number}"
    if len(locator) > 2_000 or _CREDENTIAL_PATTERN.search(locator):
        raise SyntheticLabContractError(f"manual import row {row_number} source locator is unsafe")
    disposition = (
        PreviewRowDisposition.DUPLICATE
        if "duplicate_exact_in_upload" in blocking
        else PreviewRowDisposition.BLOCKED
        if blocking
        else PreviewRowDisposition.READY_FOR_REVIEW
    )
    return ManualImportPreviewRow(
        row_number=row_number,
        redacted_text=redacted,
        normalized_text_hash=text_hash,
        source_locator_hash=hashlib.sha256(locator.encode()).hexdigest(),
        source_rights=rights,
        rights_evidence_hash=hashlib.sha256(evidence.encode()).hexdigest(),
        detected_codes=tuple(sorted(set(detected))),
        blocking_codes=tuple(sorted(set(blocking))),
        disposition=disposition,
    )


def _row_rights(value: str, default: SampleSourceRights, row_number: int) -> SampleSourceRights:
    if not value.strip():
        return default
    try:
        rights = SampleSourceRights(value.strip())
    except ValueError as error:
        raise SyntheticLabContractError(f"manual import row {row_number} rights are invalid") from error
    if rights in {SampleSourceRights.RESTRICTED, SampleSourceRights.UNKNOWN}:
        raise SyntheticLabContractError(f"manual import row {row_number} rights are ineligible")
    return rights


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(_SPACE_PATTERN.sub(" ", line).strip() for line in normalized.split("\n"))
    return _MULTI_NEWLINE_PATTERN.sub("\n\n", normalized).strip()


def _row_manifest(row: ManualImportPreviewRow) -> dict[str, object]:
    return {
        "row_number": row.row_number,
        "normalized_text_hash": row.normalized_text_hash,
        "source_locator_hash": row.source_locator_hash,
        "source_rights": row.source_rights.value,
        "rights_evidence_hash": row.rights_evidence_hash,
        "detected_codes": list(row.detected_codes),
        "blocking_codes": list(row.blocking_codes),
        "disposition": row.disposition.value,
    }


def stable_preview_id(project_id: UUID, idempotency_key: str) -> UUID:
    _require_uuid(project_id, "manual import preview Project")
    _require_text(idempotency_key, "manual import preview Idempotency-Key")
    return uuid5(NAMESPACE_URL, f"geo:synthetic-manual-preview:{project_id}:{idempotency_key}")


__all__ = [
    "ANONYMIZER_RELEASE",
    "MAX_IMPORT_BYTES",
    "MAX_IMPORT_ROWS",
    "ManualImportApproval",
    "ManualImportFormat",
    "ManualImportPreview",
    "ManualImportPreviewRow",
    "ManualImportUpload",
    "PARSER_RELEASE",
    "PREVIEW_SCHEMA_RELEASE",
    "PreviewRowDisposition",
    "SCANNER_RELEASE",
    "build_approved_manual_import",
    "preview_manual_import",
    "stable_preview_id",
]
