"""Canonical encrypted payload codec for reconstructing manual import uploads."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
import json
from uuid import UUID

from geo_core.synthetic_lab.domain import SyntheticLabContractError
from geo_core.synthetic_lab.manual_import_preview import ManualImportFormat, ManualImportUpload
from geo_core.synthetic_lab.sample_import import SampleSourceRights


_FIELDS = frozenset(
    {
        "schema_version",
        "preview_id",
        "project_id",
        "style_source_revision_id",
        "source_revision_number",
        "channel",
        "locale",
        "filename",
        "import_format",
        "content_base64",
        "default_source_rights",
        "rights_evidence_reference",
        "submitted_by",
        "submitted_at",
        "expires_at",
    }
)


def encode_manual_import_upload(upload: ManualImportUpload) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "preview_id": str(upload.preview_id),
            "project_id": str(upload.project_id),
            "style_source_revision_id": str(upload.style_source_revision_id),
            "source_revision_number": upload.source_revision_number,
            "channel": upload.channel,
            "locale": upload.locale,
            "filename": upload.filename,
            "import_format": upload.import_format.value,
            "content_base64": base64.b64encode(upload.content).decode("ascii"),
            "default_source_rights": upload.default_source_rights.value,
            "rights_evidence_reference": upload.rights_evidence_reference,
            "submitted_by": str(upload.submitted_by),
            "submitted_at": upload.submitted_at.isoformat(),
            "expires_at": upload.expires_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def decode_manual_import_upload(payload: bytes) -> ManualImportUpload:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SyntheticLabContractError("manual import upload artifact JSON is invalid") from error
    if not isinstance(value, dict) or set(value) != _FIELDS or value["schema_version"] != 1:
        raise SyntheticLabContractError("manual import upload artifact schema changed")
    string_fields = _FIELDS - {"schema_version", "source_revision_number"}
    if any(not isinstance(value[name], str) for name in string_fields) or not isinstance(
        value["source_revision_number"], int
    ):
        raise SyntheticLabContractError("manual import upload artifact value type changed")
    try:
        content = base64.b64decode(value["content_base64"], validate=True)
        return ManualImportUpload(
            preview_id=UUID(value["preview_id"]),
            project_id=UUID(value["project_id"]),
            style_source_revision_id=UUID(value["style_source_revision_id"]),
            source_revision_number=value["source_revision_number"],
            channel=value["channel"],
            locale=value["locale"],
            filename=value["filename"],
            import_format=ManualImportFormat(value["import_format"]),
            content=content,
            default_source_rights=SampleSourceRights(value["default_source_rights"]),
            rights_evidence_reference=value["rights_evidence_reference"],
            submitted_by=UUID(value["submitted_by"]),
            submitted_at=datetime.fromisoformat(value["submitted_at"]),
            expires_at=datetime.fromisoformat(value["expires_at"]),
        )
    except (ValueError, binascii.Error) as error:
        raise SyntheticLabContractError("manual import upload artifact value is invalid") from error


__all__ = ["decode_manual_import_upload", "encode_manual_import_upload"]
