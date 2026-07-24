"""Project-scoped read projections used by the Synthetic Lab Internal API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from geo_core.project_scope import set_project_scope
from geo_core.secrets.models import SecretVersionHandle
from geo_core.synthetic_lab.authorization import AuthorizationRecord
from geo_core.synthetic_lab.collection_execution_contracts import StyleCollectionTask
from geo_core.synthetic_lab.domain import (
    StyleProfileStatus,
    StyleProfileVersion,
    StyleSample,
    StyleSampleReviewStatus,
    StyleSource,
)
from geo_core.synthetic_lab.ports import SyntheticJob, SyntheticLabNotFound, VersionedAggregate
from geo_core.synthetic_lab.postgres_rows import (
    aggregate_from_row,
    authorization_from_row,
    job_from_row,
)
from geo_core.synthetic_lab.postgres_codec import decode_object, payload_hash


@dataclass(frozen=True)
class SyntheticApiPage:
    items: tuple[object, ...]
    total: int
    limit: int
    offset: int


class PostgresSyntheticApiReads:
    def __init__(self, connection_factory) -> None:
        self._connection_factory = connection_factory

    def authorizations(self, project_id: UUID, *, limit: int, offset: int) -> SyntheticApiPage:
        connection = self._open(project_id)
        try:
            total = connection.execute(
                """SELECT count(*) FROM (
                       SELECT DISTINCT channel, adapter_release
                       FROM synthetic_lab_authorization_versions
                       WHERE project_id = %s
                   ) AS current""",
                (project_id,),
            ).fetchone()[0]
            rows = connection.execute(
                """SELECT DISTINCT ON (channel, adapter_release) *
                   FROM synthetic_lab_authorization_versions
                   WHERE project_id = %s
                   ORDER BY channel, adapter_release, version_number DESC
                   LIMIT %s OFFSET %s""",
                (project_id, limit, offset),
            ).fetchall()
            return SyntheticApiPage(
                tuple(authorization_from_row(dict(row)).record for row in rows),
                int(total),
                limit,
                offset,
            )
        finally:
            connection.rollback()
            connection.close()

    def imported_sample_options(
        self, project_id: UUID, *, limit: int, offset: int
    ) -> SyntheticApiPage:
        connection = self._open(project_id)
        try:
            total = connection.execute(
                "SELECT count(*) FROM synthetic_lab_imported_samples WHERE project_id = %s",
                (project_id,),
            ).fetchone()[0]
            rows = connection.execute(
                """SELECT id, channel, source_rights, short_example_eligible, created_at,
                          row_number
                   FROM synthetic_lab_imported_samples
                   WHERE project_id = %s
                   ORDER BY created_at DESC, id
                   LIMIT %s OFFSET %s""",
                (project_id, limit, offset),
            ).fetchall()
            return SyntheticApiPage(
                tuple(
                    {
                        **dict(row),
                        "display_label": (
                            f"{row['channel']} sample {row['row_number']} · "
                            f"{str(row['id'])[:8]}"
                        ),
                    }
                    for row in rows
                ),
                int(total),
                limit,
                offset,
            )
        finally:
            connection.rollback()
            connection.close()

    def resource_inventory(self, project_id: UUID) -> dict[str, tuple[dict[str, object], ...]]:
        connection = self._open(project_id)
        try:
            samples = connection.execute(
                """SELECT id, channel, source_rights, short_example_eligible, row_number
                   FROM synthetic_lab_imported_samples
                   WHERE project_id = %s ORDER BY channel, created_at DESC, id LIMIT 10000""",
                (project_id,),
            ).fetchall()
            bindings = connection.execute(
                """SELECT DISTINCT ON (purpose) id, purpose, binding_version
                   FROM prompt_program_bindings
                   WHERE project_id = %s AND purpose LIKE 'synthetic_lab.%%'
                   ORDER BY purpose, binding_version DESC""",
                (project_id,),
            ).fetchall()
            questions = connection.execute(
                """SELECT id, name, version_number FROM knowledge_question_sets
                   WHERE project_id = %s AND status = 'frozen' AND content_hash IS NOT NULL
                   ORDER BY created_at DESC, id LIMIT 1000""",
                (project_id,),
            ).fetchall()
            facts = connection.execute(
                """SELECT id, brief_version_id, attempt_number FROM evidence_pack_attempts
                   WHERE project_id = %s AND status = 'ready' AND pack_hash IS NOT NULL
                   ORDER BY created_at DESC, id LIMIT 1000""",
                (project_id,),
            ).fetchall()
            profile_rows = connection.execute(
                """SELECT DISTINCT ON (resource_id) *
                   FROM synthetic_lab_aggregate_versions
                   WHERE project_id = %s AND kind = 'style_profile'
                   ORDER BY resource_id, version DESC""",
                (project_id,),
            ).fetchall()
            profiles = tuple(
                aggregate_from_row(dict(row)).payload for row in profile_rows
            )
            return {
                "samples": tuple(
                    {
                        "id": row["id"],
                        "label": f"{row['channel']} sample {row['row_number']} · {str(row['id'])[:8]}",
                        "kind": "sample",
                        "status": (
                            "short_example_eligible"
                            if row["short_example_eligible"]
                            else "profile_only"
                        ),
                        "channel": row["channel"],
                    }
                    for row in samples
                ),
                "prompt_bindings": tuple(
                    {
                        "id": row["id"],
                        "label": f"{row['purpose']} · binding v{row['binding_version']}",
                        "kind": "prompt_binding",
                        "status": "frozen",
                        "channel": None,
                    }
                    for row in bindings
                ),
                "question_sets": tuple(
                    {
                        "id": row["id"],
                        "label": f"{row['name']} · v{row['version_number']}",
                        "kind": "question_set",
                        "status": "frozen",
                        "channel": None,
                    }
                    for row in questions
                ),
                "fact_snapshots": tuple(
                    {
                        "id": row["id"],
                        "label": (
                            f"Evidence pack {str(row['brief_version_id'])[:8]} · "
                            f"attempt {row['attempt_number']}"
                        ),
                        "kind": "fact_snapshot",
                        "status": "ready",
                        "channel": None,
                    }
                    for row in facts
                ),
                "profiles": tuple(
                    {
                        "id": profile.id,
                        "label": f"{profile.channel} profile v{profile.version_number}",
                        "kind": "profile",
                        "status": profile.status.value,
                        "channel": profile.channel,
                    }
                    for profile in profiles
                    if isinstance(profile, StyleProfileVersion)
                    and profile.status is StyleProfileStatus.FROZEN
                ),
            }
        finally:
            connection.rollback()
            connection.close()

    def profile_creation_inputs(
        self,
        project_id: UUID,
        *,
        channel: str,
        sample_ids: tuple[UUID, ...],
        prompt_binding_id: UUID,
    ) -> dict[str, object]:
        connection = self._open(project_id)
        try:
            samples = connection.execute(
                """SELECT id, normalized_text_hash FROM synthetic_lab_imported_samples
                   WHERE project_id = %s AND channel = %s AND id = ANY(%s)
                   ORDER BY id""",
                (project_id, channel, list(sample_ids)),
            ).fetchall()
            if len(samples) != len(set(sample_ids)):
                raise SyntheticLabNotFound("an approved Style Sample option is unavailable")
            binding = connection.execute(
                """SELECT binding.id, binding.purpose, binding.release_id,
                          binding.release_hash, binding.binding_version
                   FROM prompt_program_bindings AS binding
                   WHERE binding.project_id = %s AND binding.id = %s
                     AND binding.purpose = 'synthetic_lab.style_profile'
                     AND NOT EXISTS (
                         SELECT 1 FROM prompt_program_bindings AS successor
                         WHERE successor.project_id = binding.project_id
                           AND successor.purpose = binding.purpose
                           AND successor.previous_binding_id = binding.id
                     )""",
                (project_id, prompt_binding_id),
            ).fetchone()
            if binding is None:
                raise SyntheticLabNotFound("current frozen Style Profile Prompt is unavailable")
            return {
                "sample_ids": tuple(row["id"] for row in samples),
                "sample_hashes": tuple(row["normalized_text_hash"] for row in samples),
                "prompt_release_id": binding["release_id"],
                "prompt_release_hash": binding["release_hash"],
                "prompt_binding_version": binding["binding_version"],
            }
        finally:
            connection.rollback()
            connection.close()

    def approved_style_samples(
        self,
        project_id: UUID,
        *,
        channel: str,
        sample_ids: tuple[UUID, ...],
    ) -> tuple[StyleSample, ...]:
        connection = self._open(project_id)
        try:
            rows = connection.execute(
                """SELECT id, project_id, collection_run_id, style_source_revision_id,
                          source_revision_number, channel, locale, normalized_text_hash,
                          language_reviewer_id, language_reviewed_at
                   FROM synthetic_lab_imported_samples
                   WHERE project_id = %s AND channel = %s AND id = ANY(%s)
                   ORDER BY normalized_text_hash, id""",
                (project_id, channel, list(sample_ids)),
            ).fetchall()
            if len(rows) != len(set(sample_ids)):
                raise SyntheticLabNotFound("an approved Style Sample option is unavailable")
            return tuple(
                StyleSample(
                    id=row["id"],
                    project_id=row["project_id"],
                    collection_run_id=row["collection_run_id"],
                    style_source_revision_id=row["style_source_revision_id"],
                    source_revision_number=row["source_revision_number"],
                    channel=row["channel"],
                    locale=row["locale"],
                    content_hash=row["normalized_text_hash"],
                    is_anonymized=True,
                    is_au_english=True,
                    review_status=StyleSampleReviewStatus.APPROVED,
                    reviewed_by=row["language_reviewer_id"],
                    reviewed_at=row["language_reviewed_at"],
                )
                for row in rows
            )
        finally:
            connection.rollback()
            connection.close()

    def review_case_inputs(
        self,
        project_id: UUID,
        *,
        question_set_id: UUID,
        fact_snapshot_id: UUID,
        profile_version_id: UUID,
    ) -> dict[str, object]:
        connection = self._open(project_id)
        try:
            question = connection.execute(
                """SELECT id, content_hash FROM knowledge_question_sets
                   WHERE project_id = %s AND id = %s AND status = 'frozen'
                     AND content_hash IS NOT NULL""",
                (project_id, question_set_id),
            ).fetchone()
            facts = connection.execute(
                """SELECT id, pack_hash FROM evidence_pack_attempts
                   WHERE project_id = %s AND id = %s AND status = 'ready'
                     AND pack_hash IS NOT NULL""",
                (project_id, fact_snapshot_id),
            ).fetchone()
            profile_row = connection.execute(
                """SELECT * FROM synthetic_lab_aggregate_versions
                   WHERE project_id = %s AND kind = 'style_profile' AND resource_id = %s
                   ORDER BY version DESC LIMIT 1""",
                (project_id, profile_version_id),
            ).fetchone()
            profile = aggregate_from_row(dict(profile_row)).payload if profile_row else None
            if question is None or facts is None:
                raise SyntheticLabNotFound("frozen Question Set or Fact snapshot is unavailable")
            if not isinstance(profile, StyleProfileVersion) or (
                profile.status is not StyleProfileStatus.FROZEN
            ):
                raise SyntheticLabNotFound("frozen Style Profile is unavailable")
            return {
                "question_set_hash": question["content_hash"],
                "fact_snapshot_hash": facts["pack_hash"],
                "profile_hash": profile.profile_hash,
            }
        finally:
            connection.rollback()
            connection.close()

    def authorization_by_id(self, project_id: UUID, authorization_id: UUID) -> AuthorizationRecord:
        connection = self._open(project_id)
        try:
            row = connection.execute(
                """SELECT * FROM synthetic_lab_authorization_versions
                   WHERE project_id = %s AND id = %s""",
                (project_id, authorization_id),
            ).fetchone()
            if row is None:
                raise SyntheticLabNotFound("Synthetic authorization was not found")
            record = authorization_from_row(dict(row)).record
            latest = connection.execute(
                """SELECT id FROM synthetic_lab_authorization_versions
                   WHERE project_id = %s AND channel = %s AND adapter_release = %s
                   ORDER BY version_number DESC LIMIT 1""",
                (project_id, record.channel, record.adapter_release),
            ).fetchone()
            if latest is None or latest["id"] != record.id:
                raise SyntheticLabNotFound("Synthetic authorization version is not current")
            return record
        finally:
            connection.rollback()
            connection.close()

    def aggregates(
        self,
        project_id: UUID,
        *,
        kind: str,
        limit: int,
        offset: int,
    ) -> SyntheticApiPage:
        connection = self._open(project_id)
        try:
            total = connection.execute(
                """SELECT count(DISTINCT resource_id)
                   FROM synthetic_lab_aggregate_versions
                   WHERE project_id = %s AND kind = %s""",
                (project_id, kind),
            ).fetchone()[0]
            rows = connection.execute(
                """SELECT DISTINCT ON (resource_id) *
                   FROM synthetic_lab_aggregate_versions
                   WHERE project_id = %s AND kind = %s
                   ORDER BY resource_id, version DESC
                   LIMIT %s OFFSET %s""",
                (project_id, kind, limit, offset),
            ).fetchall()
            return SyntheticApiPage(
                tuple(aggregate_from_row(dict(row)).payload for row in rows),
                int(total),
                limit,
                offset,
            )
        finally:
            connection.rollback()
            connection.close()

    def aggregate(
        self,
        project_id: UUID,
        *,
        kind: str,
        resource_id: UUID,
    ) -> VersionedAggregate:
        connection = self._open(project_id)
        try:
            row = connection.execute(
                """SELECT * FROM synthetic_lab_aggregate_versions
                   WHERE project_id = %s AND kind = %s AND resource_id = %s
                   ORDER BY version DESC LIMIT 1""",
                (project_id, kind, resource_id),
            ).fetchone()
            if row is None:
                raise SyntheticLabNotFound("Synthetic aggregate was not found")
            return aggregate_from_row(dict(row))
        finally:
            connection.rollback()
            connection.close()

    def style_source(self, project_id: UUID, revision_id: UUID) -> StyleSource:
        aggregate = self.aggregate(project_id, kind="style_source", resource_id=revision_id)
        if not isinstance(aggregate.payload, StyleSource):
            raise SyntheticLabNotFound("Style Source payload type changed")
        return aggregate.payload

    def style_collection_task_or_none(
        self, project_id: UUID, job_id: UUID
    ) -> StyleCollectionTask | None:
        """Load an admitted immutable task so an API retry can replay after state changes."""

        connection = self._open(project_id)
        try:
            row = connection.execute(
                """SELECT task_type, task_payload, task_payload_hash
                   FROM synthetic_lab_style_collection_tasks
                   WHERE project_id = %s AND job_id = %s""",
                (project_id, job_id),
            ).fetchone()
            if row is None:
                return None
            if payload_hash(row["task_payload"]) != row["task_payload_hash"]:
                raise ValueError("stored Style Collection task payload hash changed")
            task = decode_object(row["task_type"], row["task_payload"])
            if not isinstance(task, StyleCollectionTask):
                raise ValueError("stored Style Collection task type changed")
            return task
        finally:
            connection.rollback()
            connection.close()

    def job(self, project_id: UUID, job_id: UUID) -> SyntheticJob:
        connection = self._open(project_id)
        try:
            row = connection.execute(
                """SELECT metadata.*, durable.kind AS durable_kind, durable.status,
                          durable.priority, durable.input_hash, durable.idempotency_key,
                          durable.attempt_count, durable.max_attempts, durable.next_run_at,
                          durable.lease_owner, durable.lease_token,
                          durable.lease_expires_at, durable.heartbeat_at,
                          durable.fencing_generation, durable.cancel_requested_at,
                          durable.parent_job_id, durable.replay_nonce, durable.result_ref,
                          durable.error_code
                   FROM synthetic_lab_job_metadata AS metadata
                   JOIN durable_jobs AS durable
                     ON durable.id = metadata.job_id
                    AND durable.project_id = metadata.project_id
                   WHERE metadata.project_id = %s AND metadata.job_id = %s""",
                (project_id, job_id),
            ).fetchone()
            if row is None:
                raise SyntheticLabNotFound("Synthetic Job was not found")
            return job_from_row(dict(row))
        finally:
            connection.rollback()
            connection.close()

    def current_secret_handle(
        self,
        project_id: UUID,
        *,
        reference_id: UUID,
        purpose: str,
    ) -> SecretVersionHandle:
        connection = self._open(project_id)
        try:
            row = connection.execute(
                """SELECT reference.current_version, version.status
                   FROM secret_references AS reference
                   JOIN secret_versions AS version
                     ON version.reference_id = reference.id
                    AND version.project_id = reference.project_id
                    AND version.version = reference.current_version
                   WHERE reference.project_id = %s AND reference.id = %s
                     AND reference.purpose = %s""",
                (project_id, reference_id, purpose),
            ).fetchone()
            if row is None or row["status"] != "active":
                raise SyntheticLabNotFound("Style Collection login Secret is unavailable")
            return SecretVersionHandle(
                reference_id=reference_id,
                project_id=project_id,
                purpose=purpose,
                version=int(row["current_version"]),
            )
        finally:
            connection.rollback()
            connection.close()

    def _open(self, project_id: UUID) -> Any:
        connection = self._connection_factory()
        set_project_scope(connection, project_id)
        return connection


__all__ = ["PostgresSyntheticApiReads", "SyntheticApiPage"]
