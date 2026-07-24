from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import UUID, uuid4

import pytest

from geo_core.synthetic_lab.domain import SyntheticLabContractError
from geo_core.synthetic_lab.artifact_keyring import SyntheticArtifactKeyring
from geo_core.synthetic_lab.manual_import_artifacts import (
    EncryptedManualImportArtifactStore,
    ManualImportArtifactKind,
    ManualImportArtifactRef,
)
from geo_core.synthetic_lab.manual_import_preview import (
    MAX_IMPORT_BYTES,
    ManualImportApproval,
    ManualImportFormat,
    ManualImportUpload,
    PreviewRowDisposition,
    build_approved_manual_import,
    preview_manual_import,
    stable_preview_id,
)
from geo_core.synthetic_lab.sample_import import SampleSourceRights


NOW = datetime(2026, 7, 23, 8, tzinfo=UTC)


def _upload(
    content: bytes,
    *,
    import_format: ManualImportFormat = ManualImportFormat.TEXT,
    submitted_by: UUID | None = None,
) -> ManualImportUpload:
    return ManualImportUpload(
        preview_id=uuid4(),
        project_id=uuid4(),
        style_source_revision_id=uuid4(),
        source_revision_number=1,
        channel="reddit",
        locale="en-AU",
        filename={
            ManualImportFormat.TEXT: "samples.txt",
            ManualImportFormat.CSV: "samples.csv",
            ManualImportFormat.JSONL: "samples.jsonl",
        }[import_format],
        import_format=import_format,
        content=content,
        default_source_rights=SampleSourceRights.AUTHORIZED_MANUAL_CAPTURE,
        rights_evidence_reference="Internal rights approval GEO-123",
        submitted_by=submitted_by or uuid4(),
        submitted_at=NOW,
        expires_at=NOW + timedelta(hours=24),
    )


def test_text_preview_redacts_pii_and_blocks_duplicates() -> None:
    upload = _upload(
        b"Great Aussie delivery. Email alex@example.com or call 0412 345 678.\n"
        b"Great Aussie delivery. Email alex@example.com or call 0412 345 678.\n"
    )

    preview = preview_manual_import(upload)

    assert preview.selectable_count == 1
    assert preview.blocked_count == 1
    assert preview.rows[0].redacted_text == (
        "Great Aussie delivery. Email [redacted-email] or call [redacted-phone]."
    )
    assert preview.rows[0].detected_codes == ("email_redacted", "phone_redacted")
    assert preview.rows[0].disposition is PreviewRowDisposition.READY_FOR_REVIEW
    assert preview.rows[1].disposition is PreviewRowDisposition.DUPLICATE
    assert preview.rows[1].blocking_codes == ("duplicate_exact_in_upload",)
    assert "alex@example.com" not in json.dumps(preview.manifest_value())


def test_csv_uses_strict_allowlist_and_per_row_rights() -> None:
    upload = _upload(
        b'text,source_locator,source_rights,rights_evidence\n'
        b'"Works well in regional NSW",ticket-44,owned,asset register 44\n',
        import_format=ManualImportFormat.CSV,
    )

    preview = preview_manual_import(upload)

    assert preview.rows[0].source_rights is SampleSourceRights.OWNED
    assert preview.rows[0].selectable


@pytest.mark.parametrize(
    "content",
    [
        b"text,password\nhello,do-not-accept\n",
        b"text,text\nhello,there\n",
        b"unknown\nhello\n",
    ],
)
def test_csv_rejects_unknown_or_duplicate_headers(content: bytes) -> None:
    with pytest.raises(SyntheticLabContractError):
        preview_manual_import(_upload(content, import_format=ManualImportFormat.CSV))


def test_jsonl_requires_string_values_and_known_fields() -> None:
    valid = _upload(
        b'{"text":"Fair dinkum, setup was straightforward.","source_rights":"licensed"}\n',
        import_format=ManualImportFormat.JSONL,
    )
    assert preview_manual_import(valid).selectable_count == 1

    invalid = _upload(
        b'{"text":"hello","rating":5}\n',
        import_format=ManualImportFormat.JSONL,
    )
    with pytest.raises(SyntheticLabContractError):
        preview_manual_import(invalid)


@pytest.mark.parametrize(
    "value",
    [
        "password=really-secret-value",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        "api_key: abcdefghijklmnop",
    ],
)
def test_credential_material_is_blocked_not_returned_as_selectable(value: str) -> None:
    preview = preview_manual_import(_upload(value.encode()))

    assert preview.selectable_count == 0
    assert preview.rows[0].blocking_codes == ("credential_material",)


def test_approval_reparses_exact_upload_and_generates_server_lineage() -> None:
    upload = _upload(b"Useful local warranty support.\nEasy pickup in Melbourne.\n")
    preview = preview_manual_import(upload)
    approver = uuid4()
    approval = ManualImportApproval(
        selected_row_numbers=(1, 2),
        approved_by=approver,
        approved_at=NOW + timedelta(hours=1),
        au_english_verified=True,
        anonymization_verified=True,
    )

    request, inspections, payloads = build_approved_manual_import(upload, preview, approval)

    assert request.imported_by == approver
    assert request.rows[0].sample_id != request.rows[1].sample_id
    assert all(row.language_reviewer_id == approver for row in request.rows)
    assert all(row.anonymization_verified for row in request.rows)
    assert {inspection.artifact_id for inspection in inspections} == set(payloads)
    assert [payload.decode() for payload in payloads.values()] == [
        "Useful local warranty support.",
        "Easy pickup in Melbourne.",
    ]


def test_approval_requires_independent_reviewer_and_only_selectable_rows() -> None:
    submitter = uuid4()
    upload = _upload(b"clean\npassword=blocked\n", submitted_by=submitter)
    preview = preview_manual_import(upload)
    same_actor = ManualImportApproval(
        selected_row_numbers=(1,),
        approved_by=submitter,
        approved_at=NOW + timedelta(hours=1),
        au_english_verified=True,
        anonymization_verified=True,
    )
    with pytest.raises(SyntheticLabContractError, match="different actors"):
        build_approved_manual_import(upload, preview, same_actor)

    blocked = ManualImportApproval(
        selected_row_numbers=(2,),
        approved_by=uuid4(),
        approved_at=NOW + timedelta(hours=1),
        au_english_verified=True,
        anonymization_verified=True,
    )
    with pytest.raises(SyntheticLabContractError, match="blocked row"):
        build_approved_manual_import(upload, preview, blocked)


def test_replay_changes_are_detected_before_approval() -> None:
    upload = _upload(b"first text\n")
    preview = preview_manual_import(upload)
    changed = ManualImportUpload(
        **{
            **upload.__dict__,
            "content": b"changed text\n",
        }
    )
    approval = ManualImportApproval(
        selected_row_numbers=(1,),
        approved_by=uuid4(),
        approved_at=NOW + timedelta(hours=1),
        au_english_verified=True,
        anonymization_verified=True,
    )

    with pytest.raises(SyntheticLabContractError, match="changed"):
        build_approved_manual_import(changed, preview, approval)


def test_upload_limits_and_stable_preview_identity() -> None:
    project_id = uuid4()
    assert stable_preview_id(project_id, "preview-1") == stable_preview_id(
        project_id, "preview-1"
    )
    with pytest.raises(SyntheticLabContractError, match="5 MiB"):
        _upload(b"x" * (MAX_IMPORT_BYTES + 1))


class _MemoryObjects:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def put_object(self, *, key: str, content: bytes, content_type: str, expected_hash: str):
        del content_type
        assert hashlib.sha256(content).hexdigest() == expected_hash
        self.values[key] = content
        return type("Stored", (), {"uri": f"s3://manual/{key}"})()

    def get_s3_uri(self, *, uri: str, expected_hash: str):
        key = uri.removeprefix("s3://manual/")
        content = self.values[key]
        assert hashlib.sha256(content).hexdigest() == expected_hash
        return type("Retrieved", (), {"content": content})()

    def delete_s3_uri(self, *, uri: str) -> bool:
        self.values.pop(uri.removeprefix("s3://manual/"), None)
        return True


def test_manual_import_artifacts_are_encrypted_bound_and_deletable() -> None:
    objects = _MemoryObjects()
    store = EncryptedManualImportArtifactStore(
        object_store=objects,
        keyring=SyntheticArtifactKeyring(active_version="1", keys={"1": b"k" * 32}),
    )
    project_id, artifact_id = uuid4(), uuid4()
    plaintext = b"private upload with alex@example.com"

    reference = store.put(
        project_id=project_id,
        artifact_id=artifact_id,
        kind=ManualImportArtifactKind.TEMPORARY_UPLOAD,
        payload=bytearray(plaintext),
    )

    stored_payload = next(iter(objects.values.values()))
    assert plaintext not in stored_payload
    loaded = store.load(reference)
    assert bytes(loaded) == plaintext
    loaded[:] = b"\x00" * len(loaded)

    wrong_project = ManualImportArtifactRef(
        **{**reference.__dict__, "project_id": uuid4()}
    )
    with pytest.raises(SyntheticLabContractError, match="authentication failed"):
        store.load(wrong_project)

    store.delete(reference)
    assert objects.values == {}


def test_manual_import_artifact_retry_is_content_deterministic() -> None:
    objects = _MemoryObjects()
    store = EncryptedManualImportArtifactStore(
        object_store=objects,
        keyring=SyntheticArtifactKeyring(active_version="1", keys={"1": b"z" * 32}),
    )
    project_id, artifact_id = uuid4(), uuid4()
    first = store.put(
        project_id=project_id,
        artifact_id=artifact_id,
        kind=ManualImportArtifactKind.ANONYMIZED_SAMPLE,
        payload=bytearray(b"approved sample"),
    )
    replay = store.put(
        project_id=project_id,
        artifact_id=artifact_id,
        kind=ManualImportArtifactKind.ANONYMIZED_SAMPLE,
        payload=bytearray(b"approved sample"),
    )

    assert replay == first
