"""Fenced PostgreSQL manifest persistence for governed Synthetic artifacts."""

from __future__ import annotations

from typing import Any

import psycopg

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.synthetic_lab.artifact_keyring_postgres import PostgresArtifactDekVault
from geo_core.synthetic_lab.raw_artifact_governance import (
    ArtifactGovernanceDecision,
    ArtifactTombstone,
    RawArtifactClassification,
)
from geo_core.synthetic_lab.raw_artifact_storage_contracts import (
    ArtifactDeletionIntent,
    PersistedRawArtifact,
    RawArtifactManifestRepositoryPort,
    RawArtifactStorageError,
)


class PostgresRawArtifactManifestRepository(RawArtifactManifestRepositoryPort):
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        dek_vault: PostgresArtifactDekVault,
    ) -> None:
        self._store = store
        self._dek_vault = dek_vault

    def record_rejection(
        self,
        *,
        lease: WorkerLease,
        decision: ArtifactGovernanceDecision,
    ) -> None:
        if decision.persistence_allowed:
            raise RawArtifactStorageError("persisted decision cannot be recorded as a rejection")
        try:
            with self._store.fenced_transaction(lease) as connection:
                _stage_decision(connection, decision)
        except psycopg.Error as error:
            raise RawArtifactStorageError(
                "PostgreSQL rejected the artifact governance decision"
            ) from error

    def commit_persisted(
        self,
        *,
        lease: WorkerLease,
        artifact: PersistedRawArtifact,
    ) -> None:
        manifest = artifact.manifest
        if (
            not artifact.decision.persistence_allowed
            or manifest.project_id != lease.project_id
            or manifest.job_id != lease.job_id
            or manifest.fencing_generation != lease.fencing_generation
        ):
            raise RawArtifactStorageError("artifact commit changed fenced ownership")
        pending = None
        if manifest.artifact_key_ref is not None:
            pending = self._dek_vault.pending_for(
                key_ref=manifest.artifact_key_ref,
                project_id=manifest.project_id,
                artifact_id=manifest.artifact_id,
                fencing_generation=manifest.fencing_generation,
            )
        try:
            with self._store.fenced_transaction(lease) as connection:
                _stage_decision(connection, artifact.decision)
                connection.execute(
                    """INSERT INTO synthetic_lab_raw_artifacts(
                           project_id, artifact_id, job_id, generation_lease_token,
                           fencing_generation, artifact_form, classification, storage_tier,
                           persisted_content_hash, stored_object_hash, manifest_hash,
                           manifest_uri, payload_uri, media_type, byte_size, record_count,
                           source_identity_hash, producer_release, encryption_algorithm,
                           artifact_key_ref, tier_key_version, captured_at, created_at,
                           ttl_days, expires_at, allowed_audiences, lifecycle_state
                       ) VALUES (
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, 'persisted'
                       )""",
                    (
                        manifest.project_id,
                        manifest.artifact_id,
                        manifest.job_id,
                        lease.lease_token,
                        manifest.fencing_generation,
                        (
                            "derived"
                            if manifest.classification
                            is RawArtifactClassification.DERIVED_ANONYMIZED
                            else "raw"
                        ),
                        manifest.classification.value,
                        manifest.storage_tier.value,
                        manifest.persisted_content_hash,
                        manifest.stored_object_hash,
                        manifest.manifest_hash,
                        artifact.manifest_uri,
                        manifest.payload_uri,
                        manifest.media_type,
                        manifest.byte_size,
                        manifest.record_count,
                        manifest.source_identity_hash,
                        manifest.producer_release,
                        manifest.encryption_algorithm,
                        manifest.artifact_key_ref,
                        manifest.tier_key_version,
                        manifest.captured_at,
                        manifest.created_at,
                        manifest.ttl_days,
                        manifest.expires_at,
                        [audience.value for audience in artifact.decision.allowed_audiences],
                    ),
                )
                if pending is not None:
                    connection.execute(
                        """INSERT INTO synthetic_lab_artifact_deks(
                               key_ref, project_id, artifact_id, fencing_generation,
                               wrapped_dek, wrap_nonce, master_key_version, algorithm,
                               status, created_at
                           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)""",
                        (
                            pending.key_ref,
                            pending.project_id,
                            pending.artifact_id,
                            pending.fencing_generation,
                            pending.wrapped_dek,
                            pending.wrap_nonce,
                            pending.master_key_version,
                            pending.algorithm,
                            pending.created_at,
                        ),
                    )
        except psycopg.Error as error:
            raise RawArtifactStorageError(
                "PostgreSQL rejected the fenced artifact manifest"
            ) from error
        if pending is not None:
            self._dek_vault.mark_committed(pending.key_ref)

    def begin_deletion(
        self,
        *,
        lease: WorkerLease,
        artifact: PersistedRawArtifact,
        tombstone: ArtifactTombstone,
    ) -> ArtifactDeletionIntent:
        del lease, artifact, tombstone
        raise RawArtifactStorageError(
            "production artifact deletion requires the dedicated deletion-outbox lease"
        )

    def complete_tombstone(
        self,
        *,
        lease: WorkerLease,
        intent: ArtifactDeletionIntent,
        tombstone: ArtifactTombstone,
    ) -> None:
        del lease, intent, tombstone
        raise RawArtifactStorageError(
            "production tombstones require the dedicated deletion-outbox lease"
        )


def _stage_decision(connection: Any, decision: ArtifactGovernanceDecision) -> None:
    values = (
        decision.artifact_id,
        decision.project_id,
        decision.captured_at,
        decision.classification.value,
        decision.persisted_content_hash,
        decision.persistence_allowed,
        decision.storage_tier.value,
        decision.independent_dek_required,
        [audience.value for audience in decision.allowed_audiences],
        decision.ttl_days,
        decision.expires_at,
        decision.destroy_temporary_payload,
    )
    connection.execute(
        """INSERT INTO synthetic_lab_artifact_governance_decisions(
               artifact_id, project_id, captured_at, classification,
               persisted_content_hash, persistence_allowed, storage_tier,
               independent_dek_required, allowed_audiences, ttl_days, expires_at,
               destroy_temporary_payload
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (artifact_id) DO NOTHING""",
        values,
    )
    row = connection.execute(
        """SELECT artifact_id, project_id, captured_at, classification,
                  persisted_content_hash, persistence_allowed, storage_tier,
                  independent_dek_required, allowed_audiences, ttl_days, expires_at,
                  destroy_temporary_payload
           FROM synthetic_lab_artifact_governance_decisions
           WHERE artifact_id = %s AND project_id = %s""",
        (decision.artifact_id, decision.project_id),
    ).fetchone()
    if row is None or tuple(row) != values:
        raise RawArtifactStorageError("artifact governance identity already changed")


__all__ = ["PostgresRawArtifactManifestRepository"]
