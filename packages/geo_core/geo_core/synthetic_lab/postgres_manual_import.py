"""PostgreSQL two-person approval workflow for encrypted manual sample imports."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import hashlib
from typing import Any, Callable, Mapping
from uuid import UUID, uuid5

import psycopg

from geo_core.project_scope import set_project_scope
from geo_core.synthetic_lab.application_support import canonical_hash, require_roles
from geo_core.synthetic_lab.domain import StyleAccessMode, StyleSource, SyntheticLabContractError
from geo_core.synthetic_lab.manual_import_artifacts import (
    EncryptedManualImportArtifactStore,
    ManualImportArtifactKind,
    ManualImportArtifactRef,
)
from geo_core.synthetic_lab.manual_import_preview import (
    ManualImportApproval,
    ManualImportFormat,
    ManualImportPreview,
    ManualImportUpload,
    build_approved_manual_import,
    preview_manual_import,
    stable_preview_id,
)
from geo_core.synthetic_lab.manual_import_upload_codec import (
    decode_manual_import_upload,
    encode_manual_import_upload,
)
from geo_core.synthetic_lab.postgres_manual_import_support import (
    MANUAL_IMPORT_ENCRYPTED_MEDIA_TYPE,
    PREVIEW_SELECT as _PREVIEW_SELECT,
    artifact_ref as _artifact_ref,
    assert_upload_row as _assert_upload_row,
    database_error as _database_error,
    decode_base64 as _decode_base64,
    preview_summary as _summary,
    wipe as _wipe,
)
from geo_core.synthetic_lab.ports import (
    LabPrincipal,
    LabRole,
    SyntheticLabIdempotencyConflict,
    SyntheticLabNotFound,
    SyntheticLabPersistenceError,
)
from geo_core.synthetic_lab.postgres_import_repository import (
    PostgresSyntheticImportRepository,
)
from geo_core.synthetic_lab.raw_artifact_governance import govern_raw_artifact
from geo_core.synthetic_lab.sample_import import (
    ManualSampleImportManifest,
    SampleDedupStatus,
    SampleSourceRights,
    build_manual_import_manifest,
)


_PREVIEW_TTL = timedelta(hours=24)
@dataclass(frozen=True, kw_only=True)
class StoredManualImportPreview:
    preview: ManualImportPreview
    artifact: ManualImportArtifactRef
    status: str
    version: int
    row_count: int
    selectable_count: int
    blocked_count: int
    replayed: bool = False


class PostgresManualImportService:
    def __init__(
        self,
        *,
        connection_factory: Callable[[], Any],
        artifacts: EncryptedManualImportArtifactStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connect = connection_factory
        self._artifacts = artifacts
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_preview(
        self,
        *,
        principal: LabPrincipal,
        source: StyleSource,
        values: Mapping[str, object],
        idempotency_key: str,
    ) -> StoredManualImportPreview:
        require_roles(principal, source.project_id, LabRole.OPERATOR, LabRole.REVIEWER)
        if source.access_mode is not StyleAccessMode.MANUAL_IMPORT:
            raise SyntheticLabContractError("manual import requires a manual Style Source")
        content = _decode_base64(values["content_base64"])
        preview_id = stable_preview_id(source.project_id, idempotency_key)
        replay = self._matching_replay(
            principal=principal,
            source=source,
            preview_id=preview_id,
            values=values,
            content=content,
        )
        if replay is not None:
            return replay
        now = self._clock()
        upload = ManualImportUpload(
            preview_id=preview_id,
            project_id=source.project_id,
            style_source_revision_id=source.id,
            source_revision_number=source.revision_number,
            channel=source.channel,
            locale=source.locale,
            filename=str(values["filename"]),
            import_format=ManualImportFormat(str(values["import_format"])),
            content=content,
            default_source_rights=SampleSourceRights(str(values["default_source_rights"])),
            rights_evidence_reference=str(values["rights_evidence_reference"]),
            submitted_by=principal.actor_id,
            submitted_at=now,
            expires_at=now + _PREVIEW_TTL,
        )
        preview = preview_manual_import(upload)
        if any("credential_material" in row.blocking_codes for row in preview.rows):
            raise SyntheticLabContractError("manual import contains credential material")
        encrypted_payload = bytearray(encode_manual_import_upload(upload))
        artifact = self._artifacts.put(
            project_id=source.project_id,
            artifact_id=uuid5(preview_id, "temporary-upload"),
            kind=ManualImportArtifactKind.TEMPORARY_UPLOAD,
            payload=encrypted_payload,
        )
        connection = self._open(source.project_id)
        try:
            row = connection.execute(
                """SELECT * FROM geo_create_synthetic_manual_import_preview(
                       %(project_id)s, %(preview_id)s, %(source_id)s, %(source_revision)s,
                       %(channel)s, %(locale)s, %(filename)s, %(import_format)s,
                       %(rights)s, %(rights_hash)s, %(submitted_by)s, %(submitted_at)s,
                       %(expires_at)s, %(artifact_id)s, %(uri)s, %(object_hash)s,
                       %(plaintext_hash)s, %(key_version)s, %(algorithm)s, %(media_type)s,
                       %(byte_size)s, %(schema_release)s, %(parser_release)s,
                       %(scanner_release)s, %(anonymizer_release)s, %(row_count)s,
                       %(selectable_count)s, %(blocked_count)s, %(manifest_hash)s
                   )""",
                {
                    "project_id": source.project_id,
                    "preview_id": preview_id,
                    "source_id": source.id,
                    "source_revision": source.revision_number,
                    "channel": source.channel,
                    "locale": source.locale,
                    "filename": upload.filename,
                    "import_format": upload.import_format.value,
                    "rights": upload.default_source_rights.value,
                    "rights_hash": hashlib.sha256(
                        upload.rights_evidence_reference.encode()
                    ).hexdigest(),
                    "submitted_by": upload.submitted_by,
                    "submitted_at": upload.submitted_at,
                    "expires_at": upload.expires_at,
                    "artifact_id": artifact.artifact_id,
                    "uri": artifact.uri,
                    "object_hash": artifact.object_hash,
                    "plaintext_hash": artifact.plaintext_hash,
                    "key_version": artifact.key_version,
                    "algorithm": artifact.algorithm,
                    "media_type": MANUAL_IMPORT_ENCRYPTED_MEDIA_TYPE,
                    "byte_size": artifact.byte_size,
                    "schema_release": preview.schema_release,
                    "parser_release": preview.parser_release,
                    "scanner_release": preview.scanner_release,
                    "anonymizer_release": preview.anonymizer_release,
                    "row_count": len(preview.rows),
                    "selectable_count": preview.selectable_count,
                    "blocked_count": preview.blocked_count,
                    "manifest_hash": preview.preview_manifest_hash,
                },
            ).fetchone()
            connection.commit()
            return StoredManualImportPreview(
                preview=preview,
                artifact=artifact,
                status=str(row["status"]),
                version=int(row["version"]),
                row_count=len(preview.rows),
                selectable_count=preview.selectable_count,
                blocked_count=preview.blocked_count,
                replayed=bool(row["replayed"]),
            )
        except psycopg.Error as error:
            connection.rollback()
            replay = self._matching_replay(
                principal=principal,
                source=source,
                preview_id=preview_id,
                values=values,
                content=content,
            )
            if replay is not None:
                if replay.artifact.uri != artifact.uri:
                    self._artifacts.delete(artifact)
                return replay
            raise _database_error(error) from None
        finally:
            connection.close()

    def list_previews(
        self, *, principal: LabPrincipal, limit: int, offset: int
    ) -> tuple[tuple[dict[str, object], ...], int]:
        require_roles(principal, principal.project_id, LabRole.OPERATOR, LabRole.REVIEWER)
        connection = self._open(principal.project_id)
        try:
            total = connection.execute(
                "SELECT count(*) FROM synthetic_lab_manual_import_previews WHERE project_id = %s",
                (principal.project_id,),
            ).fetchone()[0]
            rows = connection.execute(
                _PREVIEW_SELECT + " ORDER BY preview.submitted_at DESC, preview.id LIMIT %s OFFSET %s",
                (principal.project_id, limit, offset),
            ).fetchall()
            return tuple(_summary(dict(row)) for row in rows), int(total)
        finally:
            connection.rollback()
            connection.close()

    def get_preview(
        self, *, principal: LabPrincipal, preview_id: UUID
    ) -> StoredManualImportPreview:
        require_roles(principal, principal.project_id, LabRole.OPERATOR, LabRole.REVIEWER)
        row = self._stored_row(principal.project_id, preview_id)
        artifact = _artifact_ref(row)
        payload = self._artifacts.load(artifact)
        try:
            upload = decode_manual_import_upload(bytes(payload))
        finally:
            _wipe(payload)
        _assert_upload_row(upload, row)
        preview = preview_manual_import(upload)
        if preview.preview_manifest_hash != row["preview_manifest_hash"]:
            raise SyntheticLabPersistenceError("manual import preview manifest changed")
        return StoredManualImportPreview(
            preview=preview,
            artifact=artifact,
            status=str(row["status"]),
            version=int(str(row["version"])),
            row_count=int(str(row["row_count"])),
            selectable_count=int(str(row["selectable_count"])),
            blocked_count=int(str(row["blocked_count"])),
        )

    def approve_preview(
        self,
        *,
        principal: LabPrincipal,
        preview_id: UUID,
        expected_version: int,
        selected_rows: tuple[int, ...],
        idempotency_key: str,
    ) -> ManualSampleImportManifest | dict[str, object]:
        require_roles(principal, principal.project_id, LabRole.APPROVER, LabRole.REVIEWER)
        detail = self.get_preview(principal=principal, preview_id=preview_id)
        request_hash = canonical_hash(
            {
                "preview_id": str(preview_id),
                "expected_version": expected_version,
                "selected_rows": sorted(selected_rows),
                "au_english_verified": True,
                "anonymization_verified": True,
            }
        )
        replay = self._terminal_replay(
            principal.project_id,
            preview_id,
            decision="approved",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        approval = ManualImportApproval(
            selected_row_numbers=selected_rows,
            approved_by=principal.actor_id,
            approved_at=self._clock(),
            au_english_verified=True,
            anonymization_verified=True,
        )
        upload = self._load_upload(detail)
        request, inspections, payloads = build_approved_manual_import(
            upload, detail.preview, approval
        )
        connection = self._open(principal.project_id)
        try:
            request = replace(
                request,
                rows=tuple(
                    replace(
                        row,
                        dedup_status=SampleDedupStatus.CROSS_RUN_DUPLICATE,
                        nearest_sample_hash=row.normalized_text_hash,
                    )
                    if _contains_hash(connection, principal.project_id, row.normalized_text_hash)
                    else row
                    for row in request.rows
                ),
            )
            manifest = build_manual_import_manifest(
                request,
                manifest_id=uuid5(preview_id, "approved-manifest"),
                preview_id=preview_id,
            )
            references = self._store_accepted_payloads(
                manifest=manifest,
                payloads=payloads,
            )
            connection.execute(
                """SELECT version FROM synthetic_lab_manual_import_preview_states
                   WHERE project_id = %s AND preview_id = %s
                   ORDER BY version DESC LIMIT 1 FOR UPDATE""",
                (principal.project_id, preview_id),
            )
            decisions = tuple(govern_raw_artifact(inspection) for inspection in inspections)
            PostgresSyntheticImportRepository(connection, principal.project_id).stage(
                manifest=manifest,
                decisions=decisions,
            )
            self._insert_sample_artifacts(connection, manifest, references, approval.approved_at)
            self._finalize(
                connection,
                principal=principal,
                preview_id=preview_id,
                expected_version=expected_version,
                decision="approved",
                occurred_at=approval.approved_at,
                selected_rows=selected_rows,
                final_manifest_id=manifest.id,
                reason_hash=None,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            connection.commit()
            return manifest
        except psycopg.Error as error:
            connection.rollback()
            raise _database_error(error) from None
        except SyntheticLabPersistenceError:
            connection.rollback()
            raise
        finally:
            connection.close()

    def reject_preview(
        self,
        *,
        principal: LabPrincipal,
        preview_id: UUID,
        expected_version: int,
        reason: str,
        idempotency_key: str,
    ) -> StoredManualImportPreview:
        require_roles(principal, principal.project_id, LabRole.APPROVER, LabRole.REVIEWER)
        request_hash = canonical_hash(
            {"preview_id": str(preview_id), "expected_version": expected_version, "reason": reason}
        )
        connection = self._open(principal.project_id)
        try:
            self._finalize(
                connection,
                principal=principal,
                preview_id=preview_id,
                expected_version=expected_version,
                decision="rejected",
                occurred_at=self._clock(),
                selected_rows=(),
                final_manifest_id=None,
                reason_hash=hashlib.sha256(reason.encode()).hexdigest(),
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            connection.commit()
        except psycopg.Error as error:
            connection.rollback()
            raise _database_error(error) from None
        finally:
            connection.close()
        return self.get_preview(principal=principal, preview_id=preview_id)

    def _load_upload(self, detail: StoredManualImportPreview) -> ManualImportUpload:
        payload = self._artifacts.load(detail.artifact)
        try:
            return decode_manual_import_upload(bytes(payload))
        finally:
            _wipe(payload)

    def _stored_row(self, project_id: UUID, preview_id: UUID) -> dict[str, object]:
        connection = self._open(project_id)
        try:
            row = connection.execute(_PREVIEW_SELECT + " AND preview.id = %s", (project_id, preview_id)).fetchone()
            if row is None:
                raise SyntheticLabNotFound("manual import preview was not found")
            return dict(row)
        finally:
            connection.rollback()
            connection.close()

    def _store_accepted_payloads(
        self,
        *,
        manifest: ManualSampleImportManifest,
        payloads: Mapping[UUID, bytes],
    ) -> dict[UUID, ManualImportArtifactRef]:
        return {
            sample.id: self._artifacts.put(
                project_id=manifest.project_id,
                artifact_id=sample.id,
                kind=ManualImportArtifactKind.ANONYMIZED_SAMPLE,
                payload=bytearray(payloads[sample.id]),
            )
            for sample in manifest.accepted_samples
        }

    @staticmethod
    def _insert_sample_artifacts(
        connection: Any,
        manifest: ManualSampleImportManifest,
        references: Mapping[UUID, ManualImportArtifactRef],
        created_at: datetime,
    ) -> None:
        for sample in manifest.accepted_samples:
            reference = references[sample.id]
            connection.execute(
                """INSERT INTO synthetic_lab_imported_sample_artifacts(
                       project_id, sample_id, object_uri, object_hash, plaintext_hash,
                       key_version, algorithm, media_type, byte_size, created_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    manifest.project_id,
                    sample.id,
                    reference.uri,
                    reference.object_hash,
                    reference.plaintext_hash,
                    reference.key_version,
                    reference.algorithm,
                    MANUAL_IMPORT_ENCRYPTED_MEDIA_TYPE,
                    reference.byte_size,
                    created_at,
                ),
            )

    @staticmethod
    def _finalize(
        connection: Any,
        *,
        principal: LabPrincipal,
        preview_id: UUID,
        expected_version: int,
        decision: str,
        occurred_at: datetime,
        selected_rows: tuple[int, ...],
        final_manifest_id: UUID | None,
        reason_hash: str | None,
        idempotency_key: str,
        request_hash: str,
    ) -> None:
        connection.execute(
            """SELECT * FROM geo_finalize_synthetic_manual_import_preview(
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
               )""",
            (
                principal.project_id,
                preview_id,
                expected_version,
                principal.actor_id,
                decision,
                occurred_at,
                list(selected_rows),
                decision == "approved",
                decision == "approved",
                final_manifest_id,
                reason_hash,
                hashlib.sha256(idempotency_key.encode()).hexdigest(),
                request_hash,
            ),
        ).fetchone()

    def _terminal_replay(
        self,
        project_id: UUID,
        preview_id: UUID,
        *,
        decision: str,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, object] | None:
        row = self._stored_row(project_id, preview_id)
        if row["status"] == "pending":
            return None
        if (
            row["status"] != decision
            or row["idempotency_key_hash"] != hashlib.sha256(idempotency_key.encode()).hexdigest()
            or row["request_hash"] != request_hash
            or row["final_manifest_id"] is None
        ):
            raise SyntheticLabIdempotencyConflict("manual import approval is already terminal")
        return self._manifest_row(project_id, row["final_manifest_id"])

    def _manifest_row(self, project_id: UUID, manifest_id: object) -> dict[str, object]:
        connection = self._open(project_id)
        try:
            row = connection.execute(
                """SELECT * FROM synthetic_lab_manual_import_manifests
                   WHERE project_id = %s AND id = %s""",
                (project_id, manifest_id),
            ).fetchone()
            if row is None:
                raise SyntheticLabPersistenceError("approved import manifest is unavailable")
            errors = connection.execute(
                """SELECT row_number, code, message, evidence_hash
                   FROM synthetic_lab_manual_import_row_errors
                   WHERE project_id = %s AND manifest_id = %s ORDER BY row_number, code""",
                (project_id, manifest_id),
            ).fetchall()
            return {**dict(row), "row_errors": tuple(dict(error) for error in errors), "replayed": True}
        finally:
            connection.rollback()
            connection.close()

    def _open(self, project_id: UUID) -> Any:
        connection = self._connect()
        set_project_scope(connection, project_id)
        return connection

    def _matching_replay(
        self,
        *,
        principal: LabPrincipal,
        source: StyleSource,
        preview_id: UUID,
        values: Mapping[str, object],
        content: bytes,
    ) -> StoredManualImportPreview | None:
        try:
            detail = self.get_preview(principal=principal, preview_id=preview_id)
        except SyntheticLabNotFound:
            return None
        upload = self._load_upload(detail)
        expected = (
            source.project_id,
            source.id,
            source.revision_number,
            source.channel,
            source.locale,
            str(values["filename"]),
            ManualImportFormat(str(values["import_format"])),
            content,
            SampleSourceRights(str(values["default_source_rights"])),
            str(values["rights_evidence_reference"]),
            principal.actor_id,
        )
        actual = (
            upload.project_id,
            upload.style_source_revision_id,
            upload.source_revision_number,
            upload.channel,
            upload.locale,
            upload.filename,
            upload.import_format,
            upload.content,
            upload.default_source_rights,
            upload.rights_evidence_reference,
            upload.submitted_by,
        )
        if actual != expected:
            raise SyntheticLabIdempotencyConflict(
                "manual import preview idempotency key was reused"
            )
        return replace(detail, replayed=True)


def _contains_hash(connection: Any, project_id: UUID, value: str) -> bool:
    return connection.execute(
        """SELECT 1 FROM synthetic_lab_imported_samples
           WHERE project_id = %s AND normalized_text_hash = %s""",
        (project_id, value),
    ).fetchone() is not None


__all__ = ["PostgresManualImportService", "StoredManualImportPreview"]
