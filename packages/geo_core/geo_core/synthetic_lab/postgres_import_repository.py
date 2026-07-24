"""PostgreSQL persistence for governed Synthetic Lab manual imports."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg

from geo_core.synthetic_lab.ports import (
    SyntheticLabPersistenceError,
    SyntheticLabVersionConflict,
)
from geo_core.synthetic_lab.raw_artifact_governance import ArtifactGovernanceDecision
from geo_core.synthetic_lab.sample_import import ManualSampleImportManifest


class PostgresSyntheticImportRepository:
    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection, self._project_id = connection, project_id

    def contains_sample_hash(self, *, project_id: UUID, sample_hash: str) -> bool:
        _require_scope(self._project_id, project_id)
        return (
            self._connection.execute(
                """SELECT 1 FROM synthetic_lab_imported_samples
                   WHERE project_id = %s AND normalized_text_hash = %s""",
                (project_id, sample_hash),
            ).fetchone()
            is not None
        )

    def stage(
        self,
        *,
        manifest: ManualSampleImportManifest,
        decisions: tuple[ArtifactGovernanceDecision, ...],
    ) -> None:
        _require_scope(self._project_id, manifest.project_id)
        try:
            self._insert_manifest(manifest)
            for decision in decisions:
                _require_scope(self._project_id, decision.project_id)
                self._insert_decision(decision)
            for error in manifest.row_errors:
                self._connection.execute(
                    """INSERT INTO synthetic_lab_manual_import_row_errors(
                           project_id, manifest_id, row_number, code, message, evidence_hash
                       ) VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        manifest.project_id,
                        manifest.id,
                        error.row_number,
                        error.code,
                        error.message,
                        error.evidence_hash,
                    ),
                )
            for sample in manifest.accepted_samples:
                self._connection.execute(
                    """INSERT INTO synthetic_lab_imported_samples(
                           id, project_id, manifest_id, request_id, row_number,
                           channel, locale, style_source_revision_id,
                           source_revision_number, collection_run_id,
                           normalized_text_hash, source_locator_hash, source_artifact_hash,
                           source_rights, rights_evidence_hash, language_reviewer_id,
                           language_reviewed_at, short_example_eligible,
                           short_example_exclusion_codes
                       ) VALUES (
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, %s, %s
                       )""",
                    (
                        sample.id,
                        sample.project_id,
                        manifest.id,
                        sample.request_id,
                        sample.row_number,
                        sample.channel,
                        sample.locale,
                        sample.style_source_revision_id,
                        sample.source_revision_number,
                        sample.collection_run_id,
                        sample.normalized_text_hash,
                        sample.source_locator_hash,
                        sample.source_artifact_hash,
                        sample.source_rights.value,
                        sample.rights_evidence_hash,
                        sample.language_reviewer_id,
                        sample.language_reviewed_at,
                        sample.short_example_eligible,
                        list(sample.short_example_exclusion_codes),
                    ),
                )
        except psycopg.Error as error:
            raise _database_error(error) from None

    def _insert_manifest(self, manifest: ManualSampleImportManifest) -> None:
        self._connection.execute(
            """INSERT INTO synthetic_lab_manual_import_manifests(
                   id, project_id, preview_id, request_id, channel, locale, imported_by,
                   imported_at, schema_release, row_count, accepted_count,
                   rejected_count, duplicate_row_count, input_hash, manifest_hash
               ) VALUES (
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
               )""",
            (
                manifest.id,
                manifest.project_id,
                manifest.preview_id,
                manifest.request_id,
                manifest.channel,
                manifest.locale,
                manifest.imported_by,
                manifest.imported_at,
                manifest.schema_release,
                manifest.row_count,
                manifest.accepted_count,
                manifest.rejected_count,
                manifest.duplicate_row_count,
                manifest.input_hash,
                manifest.manifest_hash,
            ),
        )

    def _insert_decision(self, decision: ArtifactGovernanceDecision) -> None:
        self._connection.execute(
            """INSERT INTO synthetic_lab_artifact_governance_decisions(
                   artifact_id, project_id, captured_at, classification,
                   persisted_content_hash, persistence_allowed, storage_tier,
                   independent_dek_required, allowed_audiences, ttl_days,
                   expires_at, destroy_temporary_payload
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                decision.artifact_id,
                decision.project_id,
                decision.captured_at,
                decision.classification.value,
                decision.persisted_content_hash,
                decision.persistence_allowed,
                decision.storage_tier.value,
                decision.independent_dek_required,
                [item.value for item in decision.allowed_audiences],
                decision.ttl_days,
                decision.expires_at,
                decision.destroy_temporary_payload,
            ),
        )


def _require_scope(expected: UUID, actual: UUID) -> None:
    if expected != actual:
        raise SyntheticLabPersistenceError("Synthetic Lab UoW Project scope mismatch")


def _database_error(error: psycopg.Error) -> SyntheticLabPersistenceError:
    if error.sqlstate in {"23505", "40001"}:
        return SyntheticLabVersionConflict("Synthetic Lab persistence CAS failed")
    return SyntheticLabPersistenceError("PostgreSQL rejected Synthetic Lab persistence")


__all__ = ["PostgresSyntheticImportRepository"]
