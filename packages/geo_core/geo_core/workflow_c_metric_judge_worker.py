"""Fenced durable Workers for Workflow C metric Judge and Arbiter children."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geo_core.jobs.postgres import LeaseHeartbeat, PostgresDurableJobStore, WorkerLease
from geo_core.model_gateway import (
    ExecuteModelCall,
    ModelAudience,
    ModelCallAdmissionMode,
    ModelCallAttemptKind,
    ModelCallUnknownOutcome,
    ModelGatewayError,
    ModelGatewayRequest,
    PromptAdmissionState,
    PromptReleaseAdmission,
)
from geo_core.model_gateway.application_support import ModelCallExecution
from geo_core.model_gateway.runtime_execution import (
    LoadedModelCallRuntime,
    NewModelCallJobAdmissionRequest,
)
from geo_core.project_scope import set_project_scope
from geo_core.secrets import EnvelopeCipher, load_master_keyring_from_docker_secret
from geo_core.semantic_metrics import (
    MetricJudgeCandidate,
    parse_arbiter_program_output,
    parse_metric_judge_program_output,
)
from geo_core.workflow_c_artifacts.postgres import verify_workflow_c_artifact_keyring_canaries
from geo_core.workflow_c_job_specs import PostgresWorkflowCJobSpecRepository, WorkflowCJobSpecError
from geo_core.workflow_c_metric_judge_worker_contracts import (
    MetricChild,
    MetricChildReference,
    MetricTask,
    WorkflowCMetricJudgeWorkerContractError,
    arbiter_hash,
    assert_task_schema_hashes,
    candidate_hash,
    decrypt_task,
    hash_value,
    metric_child,
    metric_child_reference,
    metric_judge_candidate_from_projection,
    row_mapping,
    text,
    uuid,
)

METRIC_JUDGE_KIND = "workflow_c.metric_judge"
METRIC_ARBITER_KIND = "workflow_c.metric_arbiter"


class WorkflowCMetricJudgeWorkerError(RuntimeError):
    """A frozen metric child cannot safely execute or finalize."""


class WorkflowCMetricModelRuntime(Protocol):
    def load_or_admit_claimed_job(
        self, request: NewModelCallJobAdmissionRequest
    ) -> object: ...

    def load(self, *, project_id: UUID, job_id: UUID) -> LoadedModelCallRuntime: ...


class WorkflowCWorkerOperation(Protocol):
    def execute(self, lease: WorkerLease) -> Mapping[str, object]: ...


class PostgresWorkflowCMetricJudgeRepository:
    """Project-scoped child reads and Worker-only fenced terminal RPC calls."""

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def load_child(self, *, lease: WorkerLease, reference: MetricChildReference) -> MetricChild:
        connection = self._connect()
        try:
            set_project_scope(connection, lease.project_id)
            row = connection.execute(
                """SELECT child.*, batch.status AS batch_status
                       FROM workflow_c_metric_model_children AS child
                       JOIN workflow_c_metric_judge_batches AS batch
                         ON batch.project_id = child.project_id AND batch.id = child.batch_id
                      WHERE child.project_id = %s AND child.child_job_id = %s""",
                (lease.project_id, lease.job_id),
            ).fetchone()
            connection.rollback()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        values = row_mapping(row)
        if values is None:
            raise WorkflowCMetricJudgeWorkerError("Workflow C metric child does not exist")
        child = metric_child(values)
        if (
            child.project_id != lease.project_id
            or child.child_job_id != lease.job_id
            or child.child_job_id != reference.child_job_id
            or child.parent_job_id != reference.parent_job_id
            or child.batch_id != reference.batch_id
            or child.role != reference.role
            or child.parent_input_hash != reference.parent_input_hash
            or child.task_hash != reference.task_hash
            or values.get("status") not in {"queued", "running"}
            or values.get("batch_status") not in {"queued", "running"}
        ):
            raise WorkflowCMetricJudgeWorkerError("metric child lineage is not executable")
        return child

    def judge_candidates(
        self, *, project_id: UUID, batch_id: UUID
    ) -> tuple[tuple[UUID, str, str], ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = tuple(
                connection.execute(
                    """SELECT candidate_id, evaluator_id, output_hash, status
                           FROM workflow_c_metric_model_children
                          WHERE project_id = %s AND batch_id = %s AND role = 'metric_judge'
                          ORDER BY evaluator_id, candidate_id""",
                    (project_id, batch_id),
                ).fetchall()
            )
            connection.rollback()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        candidates: list[tuple[UUID, str, str]] = []
        for row in rows:
            item = row_mapping(row)
            if item is None:
                raise WorkflowCMetricJudgeWorkerError("metric judge candidate row is invalid")
            output_hash = item.get("output_hash")
            if item.get("status") != "succeeded" or output_hash is None:
                raise WorkflowCMetricJudgeWorkerError("metric judge candidate is incomplete")
            candidates.append(
                (
                    uuid(item.get("candidate_id"), "candidate ID"),
                    text(item.get("evaluator_id"), "candidate evaluator ID"),
                    hash_value(output_hash, "candidate output hash"),
                )
            )
        if len(candidates) < 2:
            raise WorkflowCMetricJudgeWorkerError("metric arbiter requires two judge candidates")
        return tuple(candidates)

    def selected_judge_candidate(
        self, *, project_id: UUID, batch_id: UUID
    ) -> MetricJudgeCandidate:
        """Load the sole hash-bound Judge result selected by a completed batch."""

        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = row_mapping(
                connection.execute(
                    """SELECT child.candidate_id, child.evaluator_id, child.output_hash,
                              projection.output_projection
                           FROM workflow_c_metric_judge_batches AS batch
                           JOIN workflow_c_metric_model_children AS child
                             ON child.project_id = batch.project_id
                            AND child.batch_id = batch.id
                           JOIN workflow_c_metric_child_output_projections AS projection
                             ON projection.project_id = child.project_id
                            AND projection.child_job_id = child.child_job_id
                          WHERE batch.project_id = %s AND batch.id = %s
                            AND batch.status = 'completed'
                            AND child.role = 'metric_judge'
                            AND child.status = 'succeeded'
                            AND child.candidate_id = batch.selected_candidate_id
                            AND child.output_hash = batch.selected_output_hash""",
                    (project_id, batch_id),
                ).fetchone()
            )
            connection.rollback()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        if row is None:
            raise WorkflowCMetricJudgeWorkerError(
                "completed metric batch has no selected output projection"
            )
        projection = row.get("output_projection")
        if not isinstance(projection, Mapping):
            raise WorkflowCMetricJudgeWorkerError("metric output projection is unavailable")
        try:
            return metric_judge_candidate_from_projection(
                candidate_id=uuid(row.get("candidate_id"), "candidate ID"),
                evaluator_id=text(row.get("evaluator_id"), "candidate evaluator ID"),
                output_hash=hash_value(row.get("output_hash"), "candidate output hash"),
                projection=projection,
            )
        except WorkflowCMetricJudgeWorkerContractError as error:
            raise WorkflowCMetricJudgeWorkerError(
                "selected metric output projection is invalid"
            ) from error

    def complete(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        child: MetricChild,
        model_attempt_id: UUID,
        output_hash: str,
        output_projection: Mapping[str, object],
        selected_candidate_id: UUID | None,
        selected_output_hash: str | None,
    ) -> Mapping[str, object]:
        row = row_mapping(
            connection.execute(
                """SELECT * FROM geo_complete_workflow_c_metric_child(
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                   )""",
                (
                    lease.project_id, lease.job_id, lease.lease_token, lease.fencing_generation,
                    child.parent_input_hash, child.role, model_attempt_id, output_hash,
                    selected_candidate_id, selected_output_hash, Jsonb(dict(output_projection)),
                ),
            )
        )
        if row is None or row.get("child_status") != "succeeded":
            raise WorkflowCMetricJudgeWorkerError("metric child completion was fenced")
        return row

    def fail(
        self, *, connection: Any, lease: WorkerLease, child: MetricChild, error_code: str
    ) -> Mapping[str, object]:
        row = row_mapping(
            connection.execute(
                """SELECT * FROM geo_fail_workflow_c_metric_child(
                       %s, %s, %s, %s, %s, %s, %s
                   )""",
                (
                    lease.project_id, lease.job_id, lease.lease_token, lease.fencing_generation,
                    child.parent_input_hash, child.role, error_code,
                ),
            )
        )
        if row is None or row.get("child_status") != "failed":
            raise WorkflowCMetricJudgeWorkerError("metric child failure was fenced")
        return row

class _PostgresWorkflowCMetricOperation:
    kind: str
    role: str

    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        specs: PostgresWorkflowCJobSpecRepository,
        repository: PostgresWorkflowCMetricJudgeRepository,
        model_runtime: WorkflowCMetricModelRuntime,
        cipher: EnvelopeCipher,
        lease_for: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if lease_for < timedelta(seconds=30):
            raise ValueError("Workflow C metric worker lease must be at least 30 seconds")
        self._store, self._specs, self._repository = store, specs, repository
        self._model_runtime, self._cipher, self._lease_for, self._clock = (
            model_runtime,
            cipher,
            lease_for,
            clock,
        )

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        if lease.kind != self.kind:
            raise WorkflowCMetricJudgeWorkerError("Workflow C metric Worker kind is invalid")
        spec = self._specs.load(lease)
        child = self._repository.load_child(
            lease=lease, reference=metric_child_reference(spec, expected_role=self.role)
        )
        try:
            task = decrypt_task(self._cipher, child)
            assert_task_schema_hashes(task.request, child)
            execution = self._execute_model(lease, child, task)
            if execution.result is None:
                raise WorkflowCMetricJudgeWorkerError("metric model output is unavailable")
            output_hash, selected_id, selected_hash, output_projection = self._validate_output(
                child, task, execution.result.output
            )
        except ModelCallUnknownOutcome:
            raise
        except ModelGatewayError as error:
            return self._retry(lease, error) if error.retryable else self._terminal_failure(
                lease, child, f"metric_{error.code.value}"
            )
        except (
            ValueError,
            WorkflowCJobSpecError,
            WorkflowCMetricJudgeWorkerError,
            WorkflowCMetricJudgeWorkerContractError,
        ):
            return self._terminal_failure(lease, child, "metric_contract_invalid")
        with self._store.fenced_transaction(lease) as connection:
            outcome = self._repository.complete(
                connection=connection,
                lease=lease,
                child=child,
                model_attempt_id=execution.attempt.spec.id,
                output_hash=output_hash,
                output_projection=output_projection,
                selected_candidate_id=selected_id,
                selected_output_hash=selected_hash,
            )
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"workflow-c-metric-child:{child.batch_id}:{child.candidate_id}",
                details={
                    "batch_id": str(child.batch_id),
                    "candidate_id": str(child.candidate_id),
                    "batch_status": text(outcome.get("batch_status"), "batch status"),
                },
            )
        return {
            "status": "succeeded",
            "job_id": str(lease.job_id),
            "batch_id": str(child.batch_id),
            "output_hash": output_hash,
            "batch_status": outcome["batch_status"],
        }

    def _execute_model(
        self, lease: WorkerLease, child: MetricChild, task: MetricTask
    ) -> ModelCallExecution:
        prompt = PromptReleaseAdmission(
            project_id=lease.project_id,
            admission_mode=ModelCallAdmissionMode.RUNTIME_FROZEN,
            binding_id=child.prompt_binding_id,
            state_id=child.prompt_frozen_state_id,
            state_version=child.prompt_state_version,
            release_id=child.prompt_release_id,
            release_hash=child.prompt_release_hash,
            purpose=child.prompt_purpose,
            output_schema_hash=child.portable_output_schema_hash,
            application_output_schema_hash=child.application_output_schema_hash,
            test_set_hash=None,
            state_status=PromptAdmissionState.FROZEN,
        )
        self._model_runtime.load_or_admit_claimed_job(
            NewModelCallJobAdmissionRequest(
                project_id=lease.project_id,
                job_id=lease.job_id,
                job_kind=lease.kind,
                lease_token=lease.lease_token,
                fencing_generation=lease.fencing_generation,
                runtime_selection_id=child.runtime_selection_id,
                required_purpose=child.prompt_purpose,
                search_mode=task.request.search_mode,
                usage_audience=ModelAudience.INTERNAL_WORKER,
                prompt=prompt,
                prompt_bundle_hash=child.prompt_bundle_hash,
                output_schema_hash=child.portable_output_schema_hash,
                application_output_schema_hash=child.application_output_schema_hash,
                maximum_paid_calls=1,
                maximum_concurrent_calls=1,
                admitted_by=task.admitted_by,
                admitted_at=task.admitted_at,
            )
        )
        runtime = self._model_runtime.load(project_id=lease.project_id, job_id=lease.job_id)
        _assert_runtime_lineage(runtime, child)
        request = ModelGatewayRequest(
            messages=task.request.messages,
            configured_model=task.request.configured_model,
            prompt_bundle_hash=child.prompt_bundle_hash,
            project_id=lease.project_id,
            purpose=child.prompt_purpose,
            usage_audience=ModelAudience.INTERNAL_WORKER,
            temperature=task.request.temperature,
            max_output_tokens=task.request.max_output_tokens,
            output_schema=task.request.output_schema,
            application_output_schema=task.request.application_output_schema,
            seed=task.request.seed,
            tool_mode=task.request.tool_mode,
            search_mode=task.request.search_mode,
            deadline_at=task.request.deadline_at,
            idempotency_key=f"workflow-c-metric:{child.batch_id}:{child.candidate_id}",
            provider_secret_handle=runtime.job.provider_secret_handle,
        )
        command = ExecuteModelCall(
            project_id=lease.project_id,
            job_id=lease.job_id,
            expected_job_version=runtime.job.job_version,
            lease_token=lease.lease_token,
            fencing_generation=lease.fencing_generation,
            route=runtime.job.route,
            runtime_manifest_id=runtime.job.runtime_manifest_id,
            runtime_manifest_hash=runtime.job.runtime_manifest_hash,
            runtime_option_id=runtime.job.runtime_option_id,
            runtime_option_hash=runtime.job.runtime_option_hash,
            prompt_binding_id=child.prompt_binding_id,
            prompt_release_id=child.prompt_release_id,
            prompt_release_hash=child.prompt_release_hash,
            request=request,
            attempt_kind=ModelCallAttemptKind.INITIAL,
            attempt_idempotency_key=request.idempotency_key or "",
        )
        with LeaseHeartbeat(
            self._store,
            lease,
            lease_for=self._lease_for,
            interval=min(self._lease_for / 3, timedelta(seconds=30)),
        ) as heartbeat:
            execution = runtime.application.execute(command, policy=runtime.policy)
            heartbeat.raise_if_stopped()
        return execution

    def _validate_output(
        self, child: MetricChild, task: MetricTask, result: Mapping[str, object]
    ) -> tuple[str, UUID | None, str | None, Mapping[str, object]]:
        if self.role == "metric_judge":
            assert task.judge is not None
            parsed_judge = parse_metric_judge_program_output(
                result,
                plans=task.judge.plans,
                observation=task.judge.observation,
                subject_id=task.judge.subject_id,
                output_locale=task.judge.output_locale,
                schema_version=task.judge.schema_version,
            )
            projection = {
                "results": [item.canonical_value() for item in parsed_judge.results],
                "overall_status": parsed_judge.overall_status,
                "output_locale": parsed_judge.output_locale,
            }
            return candidate_hash(parsed_judge), None, None, projection
        assert task.arbiter is not None
        candidates = self._repository.judge_candidates(
            project_id=child.project_id, batch_id=child.batch_id
        )
        candidate_ids, evaluator_ids = tuple(str(item[0]) for item in candidates), tuple(
            item[1] for item in candidates
        )
        if (
            tuple(sorted(task.arbiter.candidate_ids)) != tuple(sorted(candidate_ids))
            or tuple(sorted(task.arbiter.evaluator_ids)) != tuple(sorted(evaluator_ids))
        ):
            raise WorkflowCMetricJudgeWorkerError("arbiter candidate lineage changed")
        parsed_arbiter = parse_arbiter_program_output(
            result,
            subject_id=task.arbiter.subject_id,
            output_locale=task.arbiter.output_locale,
            candidate_ids=candidate_ids,
            evaluator_ids=evaluator_ids,
            allowed_evidence_refs=set(task.arbiter.allowed_evidence_refs),
            allowed_citation_refs=set(task.arbiter.allowed_citation_refs),
        )
        selected_id = UUID(parsed_arbiter.selected_candidate_id)
        selected_hash = {candidate: output for candidate, _, output in candidates}.get(selected_id)
        if selected_hash is None:
            raise WorkflowCMetricJudgeWorkerError("arbiter selected an unknown candidate")
        projection = {
            "disposition": parsed_arbiter.disposition,
            "selected_candidate_id": parsed_arbiter.selected_candidate_id,
            "considered_evaluators": list(parsed_arbiter.considered_evaluators),
            "issue_codes": list(parsed_arbiter.issue_codes),
        }
        return arbiter_hash(parsed_arbiter), selected_id, selected_hash, projection

    def _retry(self, lease: WorkerLease, error: ModelGatewayError) -> Mapping[str, object]:
        status = self._store.fail(
            lease,
            error_code=f"metric_{error.code.value}",
            details={"classification": "retryable_model_gateway"},
            retry_delay=timedelta(seconds=30),
        )
        return {"status": status, "job_id": str(lease.job_id), "error_code": error.code.value}

    def _terminal_failure(
        self, lease: WorkerLease, child: MetricChild, error_code: str
    ) -> Mapping[str, object]:
        with self._store.fenced_transaction(lease) as connection:
            outcome = self._repository.fail(
                connection=connection, lease=lease, child=child, error_code=error_code
            )
            self._store.fail_in_transaction(
                connection,
                lease,
                error_code=error_code,
                details={
                    "batch_id": str(child.batch_id),
                    "batch_status": text(outcome.get("batch_status"), "batch status"),
                },
            )
        return {"status": "failed", "job_id": str(lease.job_id), "error_code": error_code}


class PostgresWorkflowCMetricJudgeOperation(_PostgresWorkflowCMetricOperation):
    kind = METRIC_JUDGE_KIND
    role = "metric_judge"


class PostgresWorkflowCMetricArbiterOperation(_PostgresWorkflowCMetricOperation):
    kind = METRIC_ARBITER_KIND
    role = "arbiter"


def build_workflow_c_metric_judge_operations(
    *,
    database_url: str,
    store: PostgresDurableJobStore,
    model_runtime: WorkflowCMetricModelRuntime,
    workflow_c_artifact_keyring_path: str,
    lease_for: timedelta,
) -> Mapping[str, "WorkflowCWorkerOperation"]:
    """Build the two bounded, governed Workflow C metric child operations."""

    url, keyring_path = database_url.strip(), workflow_c_artifact_keyring_path.strip()
    if not url or not keyring_path:
        raise ValueError("Workflow C metric PostgreSQL URL and keyring are required")

    def connect() -> Any:
        return psycopg.connect(url, row_factory=dict_row)

    cipher = EnvelopeCipher(load_master_keyring_from_docker_secret(keyring_path))
    connection = connect()
    try:
        connection.execute("SET TRANSACTION READ ONLY")
        verify_workflow_c_artifact_keyring_canaries(connection, cipher)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    specs = PostgresWorkflowCJobSpecRepository(connect)
    repository = PostgresWorkflowCMetricJudgeRepository(connect)
    return {
        METRIC_JUDGE_KIND: PostgresWorkflowCMetricJudgeOperation(
            store=store,
            specs=specs,
            repository=repository,
            model_runtime=model_runtime,
            cipher=cipher,
            lease_for=lease_for,
        ),
        METRIC_ARBITER_KIND: PostgresWorkflowCMetricArbiterOperation(
            store=store,
            specs=specs,
            repository=repository,
            model_runtime=model_runtime,
            cipher=cipher,
            lease_for=lease_for,
        ),
    }


def _assert_runtime_lineage(runtime: LoadedModelCallRuntime, child: MetricChild) -> None:
    job = runtime.job
    if not all(
        (
            job.runtime_manifest_id == child.runtime_manifest_id,
            job.runtime_manifest_hash == child.runtime_manifest_hash,
            job.runtime_option_id == child.runtime_option_id,
            job.runtime_option_hash == child.runtime_option_hash,
            job.runtime_option_id == child.runtime_selection_id,
            job.prompt_binding_id == child.prompt_binding_id,
            job.prompt_release_id == child.prompt_release_id,
            job.prompt_release_hash == child.prompt_release_hash,
            job.prompt_state_id == child.prompt_frozen_state_id,
            job.prompt_state_version == child.prompt_state_version,
            job.prompt_bundle_hash == child.prompt_bundle_hash,
            job.output_schema_hash == child.portable_output_schema_hash,
            job.application_output_schema_hash == child.application_output_schema_hash,
            job.purpose == child.prompt_purpose,
        )
    ):
        raise WorkflowCMetricJudgeWorkerError("frozen model admission differs from metric child")


__all__ = [
    "METRIC_ARBITER_KIND",
    "METRIC_JUDGE_KIND",
    "PostgresWorkflowCMetricArbiterOperation",
    "PostgresWorkflowCMetricJudgeOperation",
    "PostgresWorkflowCMetricJudgeRepository",
    "WorkflowCMetricJudgeWorkerError",
    "build_workflow_c_metric_judge_operations",
]
