"""PostgreSQL two-person approval workflow for encrypted manual sample imports."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
from typing import Any, Callable, Mapping
from uuid import UUID, uuid5

import psycopg

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
    SyntheticLabPersistenceError,
)
from geo_core.synthetic_lab.postgres_import_repository import (
    PostgresSyntheticImportRepository,
)
from geo_core.synthetic_lab.postgres_manual_import_models import StoredManualImportPreview
from geo_core.synthetic_lab.postgres_manual_import_tail import _PostgresManualImportServiceTail
from geo_core.synthetic_lab.raw_artifact_governance import govern_raw_artifact
from geo_core.synthetic_lab.sample_import import (
    ManualSampleImportManifest,
    SampleDedupStatus,
    SampleSourceRights,
    build_manual_import_manifest,
)


_PREVIEW_TTL = timedelta(hours=24)
MINIMUM_PROFILE_SHORT_EXAMPLES = 24


class PostgresManualImportService(_PostgresManualImportServiceTail):
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

    def load_profile_examples(
        self,
        *,
        project_id: UUID,
        sample_ids: tuple[UUID, ...],
        maximum_examples: int = 24,
    ) -> tuple[tuple[UUID, str], ...]:
        """Load a bounded set of approved anonymized short examples for Profile build."""

        if not sample_ids or len(sample_ids) != len(set(sample_ids)):
            raise SyntheticLabContractError(
                "Style Profile example IDs must be non-empty and unique"
            )
        if maximum_examples < MINIMUM_PROFILE_SHORT_EXAMPLES or maximum_examples > 50:
            raise SyntheticLabContractError(
                "Style Profile example limit must be between 24 and 50"
            )
        connection = self._open(project_id)
        try:
            rows = connection.execute(
                """SELECT sample.id, sample.normalized_text_hash,
                          artifact.object_uri, artifact.object_hash,
                          artifact.plaintext_hash, artifact.key_version,
                          artifact.algorithm, artifact.byte_size
                   FROM synthetic_lab_imported_samples AS sample
                   JOIN synthetic_lab_imported_sample_artifacts AS artifact
                     ON artifact.project_id = sample.project_id
                    AND artifact.sample_id = sample.id
                   WHERE sample.project_id = %s AND sample.id = ANY(%s)
                     AND sample.short_example_eligible
                   ORDER BY sample.normalized_text_hash, sample.id
                   LIMIT %s""",
                (project_id, list(sample_ids), maximum_examples),
            ).fetchall()
        finally:
            connection.rollback()
            connection.close()
        if len(rows) < MINIMUM_PROFILE_SHORT_EXAMPLES:
            missing = MINIMUM_PROFILE_SHORT_EXAMPLES - len(rows)
            sample_label = "sample" if missing == 1 else "samples"
            raise SyntheticLabPersistenceError(
                "Style Profile build found "
                f"{len(rows)} approved, unique, short-example-eligible samples; "
                f"requires {MINIMUM_PROFILE_SHORT_EXAMPLES}. Import, anonymize, and approve "
                f"{missing} more eligible {sample_label} before retrying."
            )
        examples: list[tuple[UUID, str]] = []
        for row in rows:
            reference = ManualImportArtifactRef(
                project_id=project_id,
                artifact_id=row["id"],
                kind=ManualImportArtifactKind.ANONYMIZED_SAMPLE,
                uri=row["object_uri"],
                object_hash=row["object_hash"],
                plaintext_hash=row["plaintext_hash"],
                key_version=row["key_version"],
                algorithm=row["algorithm"],
                byte_size=row["byte_size"],
            )
            payload = self._artifacts.load(reference)
            try:
                text = bytes(payload).decode("utf-8")
            except UnicodeDecodeError as error:
                raise SyntheticLabPersistenceError(
                    "approved Style Profile example is not UTF-8"
                ) from error
            finally:
                _wipe(payload)
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != row["normalized_text_hash"]:
                raise SyntheticLabPersistenceError("approved Style Profile example content changed")
            examples.append((row["id"], text))
        return tuple(examples)

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
                """SELECT count(*) AS total FROM synthetic_lab_manual_import_previews
                   WHERE project_id = %s""",
                (principal.project_id,),
            ).fetchone()["total"]
            rows = connection.execute(
                _PREVIEW_SELECT
                + " ORDER BY preview.submitted_at DESC, preview.id LIMIT %s OFFSET %s",
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


def _contains_hash(connection: Any, project_id: UUID, value: str) -> bool:
    return (
        connection.execute(
            """SELECT 1 FROM synthetic_lab_imported_samples
           WHERE project_id = %s AND normalized_text_hash = %s""",
            (project_id, value),
        ).fetchone()
        is not None
    )


__all__ = ["PostgresManualImportService", "StoredManualImportPreview"]
