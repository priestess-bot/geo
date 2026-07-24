"""Extraction and conservative privacy inspection for Style capture bundles."""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
import re
import zipfile

from geo_core.synthetic_lab.collection_execution_contracts import (
    ExtractedStyleText,
    InspectedArtifact,
    StyleCollectionExecutionError,
    StyleCollectionTask,
    StylePageCapture,
)
from geo_core.synthetic_lab.domain import StyleAccessMode
from geo_core.synthetic_lab.raw_artifact_governance import (
    ArtifactAccessClass,
    ArtifactForm,
    RawArtifactInspection,
    SensitiveFinding,
)


_EMAIL = re.compile(rb"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_URL = re.compile(rb"(?i)https://[^\s<>\"']+")
_ACCOUNT_URL = re.compile(
    rb"(?i)https://[^\s<>\"']+/(?:account|profile|u|user|users)/[^\s<>\"']*"
)
_PHONE = re.compile(rb"(?<!\d)(?:\+?61|0)[2-478](?:[\s()-]*\d){8}(?!\d)")
_SECRET_VALUE_PATTERNS = {
    SensitiveFinding.AUTHORIZATION: (
        re.compile(rb"(?i)\bauthorization\s*[:=]\s*(?!\[redacted\])[^\s,;]+"),
        re.compile(rb"(?i)\bbearer\s+[a-z0-9._~-]{8,}"),
    ),
    SensitiveFinding.COOKIE: (
        re.compile(rb"(?i)\b(?:cookie|set-cookie)\s*[:=]\s*(?!\[redacted\])[^\s]+"),
    ),
    SensitiveFinding.SESSION_TOKEN: (
        re.compile(rb"(?i)\b(?:session_token|sessionid|sid)\s*[:=]\s*(?!\[redacted\])[^\s&;,]+"),
    ),
    SensitiveFinding.PASSWORD: (
        re.compile(rb"(?i)\b(?:password|passwd)\s*[:=]\s*(?!\[redacted\])[^\s&<;,]+"),
    ),
    SensitiveFinding.STORAGE_STATE: (
        re.compile(rb"(?i)\b(?:storage_state|localstorage)\s*[:=]\s*(?!\[redacted\])[^\s]+"),
    ),
}


class ZipStyleTextExtractor:
    def __init__(self, *, maximum_records: int = 2_000, maximum_text_bytes: int = 4_194_304):
        self._maximum_records = maximum_records
        self._maximum_text_bytes = maximum_text_bytes

    def extract(
        self,
        task: StyleCollectionTask,
        capture: StylePageCapture,
    ) -> ExtractedStyleText:
        del task
        if capture.raw_bundle is None:
            raise StyleCollectionExecutionError("Style capture has no bundle to extract")
        records = _read_records(capture.raw_bundle, self._maximum_text_bytes)
        normalized = tuple(
            dict.fromkeys(" ".join(item.split()) for item in records if " ".join(item.split()))
        )
        if not normalized or len(normalized) > self._maximum_records:
            raise StyleCollectionExecutionError("Style capture record count is invalid")
        payload = bytearray("\n".join(normalized).encode("utf-8"))
        if len(payload) > self._maximum_text_bytes:
            raise StyleCollectionExecutionError("Style extracted text exceeds byte limit")
        return ExtractedStyleText(
            payload=payload,
            record_count=len(normalized),
            parser_release="style-records-zip-v1",
        )


class ConservativeStyleArtifactInspector:
    """Reject unresolved raw identifiers and anonymize derived text before storage."""

    def inspect_raw(
        self,
        task: StyleCollectionTask,
        capture: StylePageCapture,
    ) -> InspectedArtifact:
        if capture.raw_bundle is None:
            raise StyleCollectionExecutionError("Style raw inspection has no bundle")
        payload = bytearray(capture.raw_bundle)
        searchable = _searchable_bundle(payload, task.tmpfs.maximum_bytes)
        detected = set(_detect(searchable))
        if task.access_mode is StyleAccessMode.AUTHENTICATED:
            detected.add(SensitiveFinding.RESTRICTED_CONTENT)
        unresolved = tuple(
            sorted(
                detected - {SensitiveFinding.RESTRICTED_CONTENT},
                key=lambda item: item.value,
            )
        )
        inspection = RawArtifactInspection(
            artifact_id=task.raw_artifact_id,
            project_id=task.project_id,
            captured_at=capture.captured_at,
            access_class=(
                ArtifactAccessClass.AUTHENTICATED
                if task.access_mode is StyleAccessMode.AUTHENTICATED
                else ArtifactAccessClass.PUBLIC
            ),
            form=ArtifactForm.RAW,
            payload_hash=hashlib.sha256(payload).hexdigest(),
            detected_findings=tuple(sorted(detected, key=lambda item: item.value)),
            unresolved_findings=unresolved,
            redaction_applied=False,
            redaction_verified=False,
            redacted_payload_hash=None,
            anonymization_verified=False,
        )
        return InspectedArtifact(inspection=inspection, payload=payload)

    def inspect_derived(
        self,
        task: StyleCollectionTask,
        capture: StylePageCapture,
        extracted: ExtractedStyleText,
    ) -> InspectedArtifact:
        original = bytes(extracted.payload)
        detected = set(_detect(original))
        if _URL.search(original):
            detected.add(SensitiveFinding.ACCOUNT_URL)
        redacted = _redact(original)
        changed = redacted != original
        post_redaction = set(_detect(redacted))
        unresolved = tuple(sorted(post_redaction, key=lambda item: item.value))
        payload = bytearray(redacted)
        inspection = RawArtifactInspection(
            artifact_id=task.derived_artifact_id,
            project_id=task.project_id,
            captured_at=capture.captured_at,
            access_class=ArtifactAccessClass.PUBLIC,
            form=ArtifactForm.DERIVED,
            payload_hash=hashlib.sha256(original).hexdigest(),
            detected_findings=tuple(sorted(detected, key=lambda item: item.value)),
            unresolved_findings=unresolved,
            redaction_applied=changed,
            redaction_verified=changed and not unresolved,
            redacted_payload_hash=hashlib.sha256(redacted).hexdigest() if changed else None,
            anonymization_verified=not unresolved,
        )
        return InspectedArtifact(inspection=inspection, payload=payload)


def _read_records(bundle: bytearray, maximum_bytes: int) -> list[str]:
    try:
        with zipfile.ZipFile(BytesIO(bundle)) as archive:
            _validate_archive(archive, maximum_bytes)
            raw = archive.read("style-records.json")
    except (KeyError, OSError, zipfile.BadZipFile) as error:
        raise StyleCollectionExecutionError("Style capture bundle is invalid") from error
    try:
        values = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StyleCollectionExecutionError("Style capture records are invalid") from error
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise StyleCollectionExecutionError("Style capture records schema is invalid")
    return values


def _searchable_bundle(bundle: bytearray, maximum_bytes: int) -> bytes:
    try:
        with zipfile.ZipFile(BytesIO(bundle)) as archive:
            _validate_archive(archive, maximum_bytes)
            return b"\n".join(
                archive.read(name)
                for name in ("page.html", "network.har.json", "style-records.json")
            )
    except (KeyError, OSError, zipfile.BadZipFile) as error:
        raise StyleCollectionExecutionError("Style capture bundle is invalid") from error


def _validate_archive(archive: zipfile.ZipFile, maximum_bytes: int) -> None:
    expected = {"page.html", "viewport.png", "network.har.json", "style-records.json"}
    names = archive.namelist()
    if set(names) != expected or len(names) != len(expected):
        raise StyleCollectionExecutionError("Style capture bundle members changed")
    if any(
        item.file_size < 0
        or item.file_size > maximum_bytes
        or item.compress_size > maximum_bytes
        or "/" in item.filename
        or "\\" in item.filename
        for item in archive.infolist()
    ):
        raise StyleCollectionExecutionError("Style capture bundle exceeds safety limits")
    if sum(item.file_size for item in archive.infolist()) > maximum_bytes * 4:
        raise StyleCollectionExecutionError("Style capture expanded size exceeds safety limits")


def _detect(value: bytes) -> tuple[SensitiveFinding, ...]:
    findings = {
        finding
        for finding, patterns in _SECRET_VALUE_PATTERNS.items()
        if any(pattern.search(value) for pattern in patterns)
    }
    if _EMAIL.search(value):
        findings.add(SensitiveFinding.EMAIL)
    if _ACCOUNT_URL.search(value):
        findings.add(SensitiveFinding.ACCOUNT_URL)
    if _PHONE.search(value):
        findings.add(SensitiveFinding.DIRECT_IDENTIFIER)
    return tuple(sorted(findings, key=lambda item: item.value))


def _redact(value: bytes) -> bytes:
    redacted = _EMAIL.sub(b"[EMAIL]", value)
    redacted = _URL.sub(b"[URL]", redacted)
    return _PHONE.sub(b"[PHONE]", redacted)


__all__ = ["ConservativeStyleArtifactInspector", "ZipStyleTextExtractor"]
