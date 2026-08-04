"""Project-scoped read projections used by the Synthetic Lab Internal API."""

from __future__ import annotations

from uuid import UUID

from geo_core.synthetic_lab.authorization import AuthorizationRecord
from geo_core.synthetic_lab.execution_contracts import (
    CorpusFinalizeOutput,
    DirectGenerationTask,
    ReviewCaseRunOutput,
    ReviewCaseRunTask,
)
from geo_core.synthetic_lab.domain import (
    StyleProfileSampleManifest,
    StyleProfileStatus,
    StyleProfileVersion,
    StyleSample,
    StyleSampleReviewStatus,
)
from geo_core.synthetic_lab.ports import SyntheticLabNotFound
from geo_core.synthetic_lab.postgres_rows import (
    aggregate_from_row,
    authorization_from_row,
)
from geo_core.synthetic_lab.postgres_codec import decode_object, payload_hash
from geo_core.synthetic_lab.postgres_api_read_models import (
    StyleProfileAggregateView,
    SyntheticAggregateView,
    SyntheticApiPage,
)
from geo_core.synthetic_lab.postgres_api_direct_reads import (
    _PostgresSyntheticApiDirectReads,
)
from geo_core.synthetic_lab.postgres_api_reads_tail import _PostgresSyntheticApiReadsTail


class PostgresSyntheticApiReads(
    _PostgresSyntheticApiDirectReads, _PostgresSyntheticApiReadsTail
):
    def __init__(self, connection_factory) -> None:
        self._connection_factory = connection_factory

    def authorizations(self, project_id: UUID, *, limit: int, offset: int) -> SyntheticApiPage:
        connection = self._open(project_id)
        try:
            total = connection.execute(
                """SELECT count(*) AS total FROM (
                       SELECT DISTINCT channel, adapter_release
                       FROM synthetic_lab_authorization_versions
                       WHERE project_id = %s
                   ) AS current""",
                (project_id,),
            ).fetchone()["total"]
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
                """SELECT count(*) AS total FROM synthetic_lab_imported_samples
                   WHERE project_id = %s""",
                (project_id,),
            ).fetchone()["total"]
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

    def profiles(
        self, project_id: UUID, *, limit: int, offset: int
    ) -> SyntheticApiPage:
        connection = self._open(project_id)
        try:
            total = connection.execute(
                """SELECT count(DISTINCT resource_id) AS total
                   FROM synthetic_lab_aggregate_versions
                   WHERE project_id = %s AND kind = 'style_profile'""",
                (project_id,),
            ).fetchone()["total"]
            rows = connection.execute(
                """SELECT DISTINCT ON (aggregate.resource_id) aggregate.*,
                          binding.verification_status AS build_verification_status,
                          coalesce(binding.rebuild_required, false) AS rebuild_required
                   FROM synthetic_lab_aggregate_versions AS aggregate
                   LEFT JOIN synthetic_lab_style_profile_build_bindings AS binding
                     ON binding.project_id = aggregate.project_id
                    AND binding.profile_version_id = aggregate.resource_id
                   WHERE aggregate.project_id = %s
                     AND aggregate.kind = 'style_profile'
                   ORDER BY aggregate.resource_id, aggregate.version DESC
                   LIMIT %s OFFSET %s""",
                (project_id, limit, offset),
            ).fetchall()
            items = []
            for row in rows:
                aggregate = aggregate_from_row(dict(row))
                items.append(
                    StyleProfileAggregateView(
                        payload=aggregate.payload,
                        state_version=aggregate.version,
                        build_verification_status=row["build_verification_status"],
                        rebuild_required=bool(row["rebuild_required"]),
                    )
                )
            return SyntheticApiPage(tuple(items), int(total), limit, offset)
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
                """SELECT DISTINCT ON (aggregate.resource_id) aggregate.*
                   FROM synthetic_lab_aggregate_versions AS aggregate
                   JOIN synthetic_lab_style_profile_build_bindings AS binding
                     ON binding.project_id = aggregate.project_id
                    AND binding.profile_version_id = aggregate.resource_id
                    AND binding.verification_status = 'verified'
                    AND binding.rebuild_required = false
                   WHERE aggregate.project_id = %s
                     AND aggregate.kind = 'style_profile'
                   ORDER BY aggregate.resource_id, aggregate.version DESC""",
                (project_id,),
            ).fetchall()
            profiles = tuple(aggregate_from_row(dict(row)).payload for row in profile_rows)
            execution_rows = connection.execute(
                """SELECT task.job_id, task.task_type, task.task_payload,
                          task.task_payload_hash, result.result_type,
                          result.result_payload, result.result_payload_hash,
                          result.result_hash, result.created_at
                   FROM synthetic_lab_execution_tasks AS task
                   JOIN synthetic_lab_execution_results AS result
                     ON result.project_id = task.project_id
                    AND result.job_id = task.job_id
                   JOIN durable_jobs AS job
                     ON job.project_id = task.project_id AND job.id = task.job_id
                   WHERE task.project_id = %s AND job.status = 'succeeded'
                   ORDER BY result.created_at DESC, task.job_id
                   LIMIT 5000""",
                (project_id,),
            ).fetchall()
            completed: list[tuple[UUID, object, object]] = []
            for row in execution_rows:
                if payload_hash(row["task_payload"]) != row["task_payload_hash"]:
                    raise ValueError("stored Synthetic execution task payload hash changed")
                if payload_hash(row["result_payload"]) != row["result_payload_hash"]:
                    raise ValueError("stored Synthetic execution result payload hash changed")
                task = decode_object(row["task_type"], row["task_payload"])
                result = decode_object(row["result_type"], row["result_payload"])
                if getattr(result, "result_hash", None) != row["result_hash"]:
                    raise ValueError("stored Synthetic execution result hash changed")
                completed.append((row["job_id"], task, result))
            review_jobs = tuple(
                {
                    "id": job_id,
                    "label": (
                        f"{task.case.channel} · {task.case.case_key} · "
                        f"{result.resolution.status.value}"
                    ),
                    "kind": "review_job",
                    "status": result.resolution.status.value,
                    "channel": task.case.channel,
                }
                for job_id, task, result in completed
                if isinstance(task, (ReviewCaseRunTask, DirectGenerationTask))
                and isinstance(result, ReviewCaseRunOutput)
                and result.resolved_candidate_text is not None
                and result.resolution.offline_experiment_eligible
            )
            candidate_corpora = tuple(
                {
                    "id": job_id,
                    "label": (
                        f"Candidate Corpus v{result.corpus.version_number} · "
                        f"{len(result.corpus.candidates)} candidates · "
                        f"{result.corpus.warning_count} warnings"
                    ),
                    "kind": "corpus_candidate",
                    "status": result.corpus.role.value,
                    "channel": None,
                }
                for job_id, _task, result in completed
                if isinstance(result, CorpusFinalizeOutput)
                and result.corpus.role.value == "new_candidate_corpus"
            )
            approved_corpora = tuple(
                {
                    "id": job_id,
                    "label": (
                        f"Approved Corpus v{result.corpus.version_number} · "
                        f"{len(result.corpus.candidates)} candidates · "
                        f"{result.corpus.warning_count} warnings"
                    ),
                    "kind": "corpus_approved",
                    "status": result.corpus.role.value,
                    "channel": None,
                }
                for job_id, _task, result in completed
                if isinstance(result, CorpusFinalizeOutput)
                and result.corpus.role.value == "current_approved_corpus"
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
                "review_jobs": review_jobs,
                "candidate_corpora": candidate_corpora,
                "approved_corpora": approved_corpora,
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

    def profile_sample_ids(
        self,
        project_id: UUID,
        *,
        profile_version_id: UUID,
        corpus_hash: str,
        legacy_sample_ids: tuple[UUID, ...] = (),
    ) -> tuple[UUID, ...]:
        try:
            record = self.aggregate(
                project_id,
                kind="style_profile_sample_manifest",
                resource_id=profile_version_id,
            )
        except SyntheticLabNotFound:
            if len(legacy_sample_ids) < 200:
                raise SyntheticLabNotFound(
                    "legacy Style Profile requires its original sample manifest"
                ) from None
            return legacy_sample_ids
        manifest = record.payload
        if not isinstance(manifest, StyleProfileSampleManifest):
            raise SyntheticLabNotFound("Style Profile sample manifest type changed")
        if manifest.profile_version_id != profile_version_id or manifest.corpus_hash != corpus_hash:
            raise SyntheticLabNotFound("Style Profile sample manifest lineage changed")
        if legacy_sample_ids and legacy_sample_ids != manifest.sample_ids:
            raise SyntheticLabNotFound("submitted Style Profile sample manifest changed")
        return manifest.sample_ids

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
        include_state: bool = False,
    ) -> SyntheticApiPage:
        connection = self._open(project_id)
        try:
            total = connection.execute(
                """SELECT count(DISTINCT resource_id) AS total
                   FROM synthetic_lab_aggregate_versions
                   WHERE project_id = %s AND kind = %s""",
                (project_id, kind),
            ).fetchone()["total"]
            rows = connection.execute(
                """SELECT DISTINCT ON (resource_id) *
                   FROM synthetic_lab_aggregate_versions
                   WHERE project_id = %s AND kind = %s
                   ORDER BY resource_id, version DESC
                   LIMIT %s OFFSET %s""",
                (project_id, kind, limit, offset),
            ).fetchall()
            aggregates = tuple(aggregate_from_row(dict(row)) for row in rows)
            return SyntheticApiPage(
                tuple(
                    SyntheticAggregateView(item.payload, item.version)
                    if include_state
                    else item.payload
                    for item in aggregates
                ),
                int(total),
                limit,
                offset,
            )
        finally:
            connection.rollback()
            connection.close()


__all__ = ["PostgresSyntheticApiReads", "SyntheticApiPage"]
