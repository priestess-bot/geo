"""PostgreSQL two-person approval workflow for encrypted manual sample imports."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
from typing import TYPE_CHECKING, Any, Callable, Mapping
from uuid import UUID


from geo_core.project_scope import set_project_scope
from geo_core.synthetic_lab.domain import StyleSource
from geo_core.synthetic_lab.manual_import_artifacts import (
    EncryptedManualImportArtifactStore,
    ManualImportArtifactKind,
    ManualImportArtifactRef,
)
from geo_core.synthetic_lab.manual_import_preview import (
    ManualImportFormat,
    ManualImportUpload,
)
from geo_core.synthetic_lab.manual_import_upload_codec import (
    decode_manual_import_upload,
)
from geo_core.synthetic_lab.postgres_manual_import_models import StoredManualImportPreview
from geo_core.synthetic_lab.postgres_manual_import_support import (
    MANUAL_IMPORT_ENCRYPTED_MEDIA_TYPE,
    PREVIEW_SELECT as _PREVIEW_SELECT,
    wipe as _wipe,
)
from geo_core.synthetic_lab.ports import (
    LabPrincipal,
    SyntheticLabIdempotencyConflict,
    SyntheticLabNotFound,
    SyntheticLabPersistenceError,
)
from geo_core.synthetic_lab.sample_import import (
    ManualSampleImportManifest,
    SampleSourceRights,
)


_PREVIEW_TTL = timedelta(hours=24)


class _PostgresManualImportServiceTail:
    _connect: Callable[[], Any]
    _artifacts: EncryptedManualImportArtifactStore
    _clock: Callable[[], datetime]

    if TYPE_CHECKING:

        def get_preview(
            self, *, principal: LabPrincipal, preview_id: UUID
        ) -> StoredManualImportPreview: ...

    def _load_upload(self, detail: StoredManualImportPreview) -> ManualImportUpload:
        payload = self._artifacts.load(detail.artifact)
        try:
            return decode_manual_import_upload(bytes(payload))
        finally:
            _wipe(payload)

    def _stored_row(self, project_id: UUID, preview_id: UUID) -> dict[str, object]:
        connection = self._open(project_id)
        try:
            row = connection.execute(
                _PREVIEW_SELECT + " AND preview.id = %s", (project_id, preview_id)
            ).fetchone()
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
            return {
                **dict(row),
                "row_errors": tuple(dict(error) for error in errors),
                "replayed": True,
            }
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
