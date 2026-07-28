"""Project-scoped read projections used by the Synthetic Lab Internal API."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from geo_core.project_scope import set_project_scope
from geo_core.secrets.models import SecretVersionHandle
from geo_core.synthetic_lab.collection_execution_contracts import StyleCollectionTask
from geo_core.synthetic_lab.execution_contracts import (
    CorpusFinalizeOutput,
    CorpusFinalizeTask,
    OfflineExperimentRunOutput,
    OfflineExperimentRunTask,
    ReviewCaseRunOutput,
    ReviewCaseRunTask,
    StyleProfileBuildOutput,
    StyleProfileBuildTask,
    SyntheticExecutionOutput,
    SyntheticExecutionTask,
)
from geo_core.synthetic_lab.domain import (
    StyleSource,
)
from geo_core.synthetic_lab.ports import SyntheticJob, SyntheticLabNotFound, VersionedAggregate
from geo_core.synthetic_lab.postgres_rows import (
    aggregate_from_row,
    job_from_row,
)
from geo_core.synthetic_lab.postgres_codec import decode_object, payload_hash
from geo_core.synthetic_lab.profile_build_binding import (
    StyleProfileBuildBinding,
    StyleProfileBuildCandidate,
)

from geo_core.synthetic_lab.postgres_api_read_models import (
    SyntheticJobView,
    _corpus_warning_summary,
    _offline_warning_summary,
)


class _PostgresSyntheticApiReadsTail:
    _connection_factory: Any

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

    def execution_task_or_none(
        self, project_id: UUID, job_id: UUID
    ) -> SyntheticExecutionTask | None:
        connection = self._open(project_id)
        try:
            row = connection.execute(
                """SELECT task_type, task_payload, task_payload_hash
                   FROM synthetic_lab_execution_tasks
                   WHERE project_id = %s AND job_id = %s""",
                (project_id, job_id),
            ).fetchone()
            if row is None:
                return None
            if payload_hash(row["task_payload"]) != row["task_payload_hash"]:
                raise ValueError("stored Synthetic execution task payload hash changed")
            task = decode_object(row["task_type"], row["task_payload"])
            if not isinstance(
                task,
                (
                    StyleProfileBuildTask,
                    ReviewCaseRunTask,
                    CorpusFinalizeTask,
                    OfflineExperimentRunTask,
                ),
            ):
                raise ValueError("stored Synthetic execution task type changed")
            return task
        finally:
            connection.rollback()
            connection.close()

    def profile_build_output(
        self,
        project_id: UUID,
        *,
        profile_version_id: UUID,
        profile_hash: str,
    ) -> StyleProfileBuildOutput | None:
        candidate = self._profile_build_candidate(
            project_id,
            profile_version_id=profile_version_id,
            profile_hash=profile_hash,
            require_binding=True,
            bound_by=None,
        )
        return candidate.output if candidate is not None else None

    def profile_build_candidate(
        self,
        project_id: UUID,
        *,
        profile_version_id: UUID,
        profile_hash: str,
        bound_by: UUID,
    ) -> StyleProfileBuildCandidate | None:
        return self._profile_build_candidate(
            project_id,
            profile_version_id=profile_version_id,
            profile_hash=profile_hash,
            require_binding=False,
            bound_by=bound_by,
        )

    def _profile_build_candidate(
        self,
        project_id: UUID,
        *,
        profile_version_id: UUID,
        profile_hash: str,
        require_binding: bool,
        bound_by: UUID | None,
    ) -> StyleProfileBuildCandidate | None:
        connection = self._open(project_id)
        try:
            rows = connection.execute(
                """SELECT result.id AS execution_result_id,
                          result.job_id AS execution_job_id,
                          result.result_type, result.result_payload,
                          result.result_payload_hash, result.result_hash,
                          binding.profile_version_id AS bound_profile_version_id,
                          binding.profile_hash AS bound_profile_hash,
                          binding.execution_job_id AS bound_execution_job_id,
                          binding.execution_result_id AS bound_execution_result_id,
                          binding.result_hash AS bound_result_hash,
                          binding.result_payload_hash AS bound_result_payload_hash,
                          binding.artifact_hash AS bound_artifact_hash,
                          binding.bound_by
                   FROM synthetic_lab_execution_results AS result
                   JOIN synthetic_lab_job_metadata AS metadata
                     ON metadata.project_id = result.project_id
                    AND metadata.job_id = result.job_id
                   JOIN durable_jobs AS job
                    ON job.project_id = result.project_id
                    AND job.id = result.job_id
                   LEFT JOIN synthetic_lab_style_profile_build_bindings AS binding
                     ON binding.project_id = result.project_id
                    AND binding.profile_version_id = metadata.profile_version_id
                    AND binding.verification_status = 'verified'
                    AND binding.rebuild_required = false
                   WHERE result.project_id = %s
                     AND metadata.domain_job_kind = 'style_profile_build'
                     AND metadata.profile_version_id = %s
                     AND metadata.profile_hash = %s
                     AND job.status = 'succeeded'
                     AND (%s = false OR binding.profile_version_id IS NOT NULL)
                     AND (binding.profile_version_id IS NULL
                          OR (binding.execution_result_id = result.id
                              AND binding.execution_job_id = result.job_id
                              AND binding.result_hash = result.result_hash
                              AND binding.result_payload_hash = result.result_payload_hash))
                   ORDER BY result.created_at DESC, result.id DESC""",
                (project_id, profile_version_id, profile_hash, require_binding),
            ).fetchall()
            for row in rows:
                if payload_hash(row["result_payload"]) != row["result_payload_hash"]:
                    raise ValueError("stored Profile build output payload hash changed")
                output = decode_object(row["result_type"], row["result_payload"])
                if isinstance(output, StyleProfileBuildOutput):
                    selected_by = row["bound_by"] or bound_by
                    if selected_by is None:
                        raise ValueError("stored Profile build binding actor is unavailable")
                    binding = StyleProfileBuildBinding(
                        project_id=project_id,
                        profile_version_id=(
                            row["bound_profile_version_id"] or profile_version_id
                        ),
                        profile_hash=row["bound_profile_hash"] or profile_hash,
                        execution_job_id=(
                            row["bound_execution_job_id"] or row["execution_job_id"]
                        ),
                        execution_result_id=(
                            row["bound_execution_result_id"] or row["execution_result_id"]
                        ),
                        result_hash=row["bound_result_hash"] or row["result_hash"],
                        result_payload_hash=(
                            row["bound_result_payload_hash"]
                            or row["result_payload_hash"]
                        ),
                        artifact_hash=row["bound_artifact_hash"] or output.artifact_hash,
                        bound_by=selected_by,
                    )
                    return StyleProfileBuildCandidate(binding=binding, output=output)
            return None
        finally:
            connection.rollback()
            connection.close()

    def completed_execution(
        self,
        project_id: UUID,
        job_id: UUID,
    ) -> tuple[SyntheticExecutionTask, SyntheticExecutionOutput]:
        connection = self._open(project_id)
        try:
            row = connection.execute(
                """SELECT task.task_type, task.task_payload, task.task_payload_hash,
                          result.result_type, result.result_payload,
                          result.result_payload_hash, result.result_hash
                   FROM synthetic_lab_execution_tasks AS task
                   JOIN synthetic_lab_execution_results AS result
                     ON result.project_id = task.project_id
                    AND result.job_id = task.job_id
                   JOIN durable_jobs AS job
                     ON job.project_id = task.project_id AND job.id = task.job_id
                   WHERE task.project_id = %s AND task.job_id = %s
                     AND job.status = 'succeeded'""",
                (project_id, job_id),
            ).fetchone()
            if row is None:
                raise SyntheticLabNotFound("completed Synthetic execution is unavailable")
            if payload_hash(row["task_payload"]) != row["task_payload_hash"]:
                raise ValueError("stored Synthetic execution task payload hash changed")
            if payload_hash(row["result_payload"]) != row["result_payload_hash"]:
                raise ValueError("stored Synthetic execution result payload hash changed")
            task = decode_object(row["task_type"], row["task_payload"])
            result = decode_object(row["result_type"], row["result_payload"])
            if not isinstance(
                task,
                (
                    StyleProfileBuildTask,
                    ReviewCaseRunTask,
                    CorpusFinalizeTask,
                    OfflineExperimentRunTask,
                ),
            ) or not isinstance(
                result,
                (
                    StyleProfileBuildOutput,
                    ReviewCaseRunOutput,
                    CorpusFinalizeOutput,
                    OfflineExperimentRunOutput,
                ),
            ):
                raise ValueError("stored Synthetic execution type changed")
            if result.result_hash != row["result_hash"]:
                raise ValueError("stored Synthetic execution result hash changed")
            return task, result
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

    def job_view(self, project_id: UUID, job_id: UUID) -> SyntheticJobView:
        job = self.job(project_id, job_id)
        connection = self._open(project_id)
        try:
            row = connection.execute(
                """SELECT result_type, result_payload, result_payload_hash
                   FROM synthetic_lab_execution_results
                   WHERE project_id = %s AND job_id = %s""",
                (project_id, job_id),
            ).fetchone()
            if row is None:
                return SyntheticJobView(job, None)
            if payload_hash(row["result_payload"]) != row["result_payload_hash"]:
                raise ValueError("stored Synthetic execution result payload hash changed")
            result = decode_object(row["result_type"], row["result_payload"])
            task = self.execution_task_or_none(project_id, job_id)
            if isinstance(task, ReviewCaseRunTask) and isinstance(result, ReviewCaseRunOutput):
                resolution = result.resolution
                warning = resolution.status.value == "completed_with_warning"
                configured_model = (
                    result.evaluations[-1].call_lineage.configured_model
                    if result.evaluations
                    else "unknown"
                )
                return SyntheticJobView(
                    job,
                    {
                        "warning_count": 1 if warning else 0,
                        "candidate_count": 1,
                        "warning_ratio": 1.0 if warning else 0.0,
                        "by_code": {code: 1 for code in resolution.warning_codes},
                        "by_channel": {resolution.channel: 1} if warning else {},
                        "by_scenario_mode": (
                            {resolution.scenario_mode.value: 1} if warning else {}
                        ),
                        "by_competitor": (
                            {"competitor" if task.case.competitor_scenario else "non_competitor": 1}
                            if warning
                            else {}
                        ),
                        "by_model": {configured_model: 1} if warning else {},
                        "by_question_cluster": {task.case.case_key: 1} if warning else {},
                    },
                )
            if isinstance(task, CorpusFinalizeTask) and isinstance(result, CorpusFinalizeOutput):
                return SyntheticJobView(job, _corpus_warning_summary(result.corpus))
            if (
                isinstance(task, OfflineExperimentRunTask)
                and isinstance(result, OfflineExperimentRunOutput)
                and result.summary is not None
            ):
                return SyntheticJobView(
                    job,
                    _offline_warning_summary(result.summary.arm_summaries),
                )
            return SyntheticJobView(job, None)
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
