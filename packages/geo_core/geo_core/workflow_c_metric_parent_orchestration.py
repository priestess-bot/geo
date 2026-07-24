"""Reentrant Judge/Arbiter lifecycle for a durable semantic-metrics parent."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from typing import Any
from uuid import UUID

from geo_core.jobs.postgres import LeaseHeartbeat, PostgresDurableJobStore, WorkerLease
from geo_core.secrets import EnvelopeCipher
from geo_core.semantic_metrics import (
    FrozenMetricSuite,
    MetricInputSet,
    MetricJudgeCandidate,
    MetricJudgeCandidateResolution,
    MetricJudgePlanBatch,
    MetricStatus,
    SelectedMetricJudgeBatch,
    compute_semantic_metric_snapshot,
    merge_selected_metric_judge_batches,
    plan_metric_judge_batches,
    resolve_metric_judge_candidates,
)
from geo_core.workflow_c_analysis_common import WorkflowCAnalysisWorkerError
from geo_core.workflow_c_analysis_persistence import persist_semantic_snapshot
from geo_core.workflow_c_metric_arbiter_admission import (
    PostgresWorkflowCMetricArbiterAdmissionRepository,
)
from geo_core.workflow_c_metric_judge_worker_contracts import (
    WorkflowCMetricJudgeWorkerContractError,
    metric_judge_candidate_from_projection,
)
from geo_core.workflow_c_metric_parent_admission import (
    MetricJudgeParentAdmission,
    PostgresWorkflowCMetricJudgeParentAdmissionRepository,
    WorkflowCMetricParentAdmissionError,
)
from geo_core.workflow_c_metric_parent_specs import MetricModelProgramAdmission
from geo_core.workflow_c_semantic_specs import SemanticMetricMetadata


_HASH = re.compile(r"^[0-9a-f]{64}$")
_PARENT_KIND = "workflow_c.analysis.semantic_metrics"
_BATCH_STATUSES = frozenset({"queued", "running", "completed", "failed", "cancelled"})
_CHILD_PENDING = frozenset({"queued", "running"})


@dataclass(frozen=True)
class _ParentFailed:
    pass


_FAILED = _ParentFailed()


class WorkflowCMetricParentOrchestrationError(WorkflowCAnalysisWorkerError):
    """Frozen Metric parent state cannot progress safely."""


@dataclass(frozen=True)
class PersistedMetricBatch:
    batch_id: UUID
    observation_id: UUID
    ordinal: int
    plans_hash: str
    status: str
    selected_candidate_id: UUID | None
    selected_output_hash: str | None
    arbiter_child_job_id: UUID | None


class PostgresWorkflowCMetricParentProgressRepository:
    """Reads only the minimal Project-scoped child state needed by a parent."""

    def batches_in_transaction(
        self,
        connection: Any,
        *,
        lease: WorkerLease,
        parent_input_hash: str,
        expected: Sequence[MetricJudgePlanBatch],
        input_set_hash: str,
        metric_suite_hash: str,
    ) -> tuple[PersistedMetricBatch, ...]:
        rows = tuple(
            connection.execute(
                """SELECT id, observation_id, ordinal, planned_batch_count, plans_hash,
                              parent_input_hash, input_set_hash, metric_suite_hash, status,
                              selected_candidate_id, selected_output_hash, arbiter_child_job_id
                       FROM workflow_c_metric_judge_batches
                      WHERE project_id = %s AND parent_job_id = %s
                      ORDER BY observation_id, ordinal
                      FOR SHARE""",
                (lease.project_id, lease.job_id),
            ).fetchall()
        )
        if not rows:
            return ()
        expected_by_key = {(item.observation.id, item.ordinal): item for item in expected}
        if len(rows) != len(expected_by_key):
            raise WorkflowCMetricParentOrchestrationError("metric parent batch count changed")
        batches = tuple(
            _batch(
                row,
                parent_input_hash=parent_input_hash,
                expected=expected_by_key,
                expected_count=len(expected_by_key),
                input_set_hash=input_set_hash,
                metric_suite_hash=metric_suite_hash,
            )
            for row in rows
        )
        if {(item.observation_id, item.ordinal) for item in batches} != set(expected_by_key):
            raise WorkflowCMetricParentOrchestrationError("metric parent batch identity changed")
        return batches

    def judge_resolution_in_transaction(
        self,
        connection: Any,
        *,
        project_id: UUID,
        batch_id: UUID,
    ) -> MetricJudgeCandidateResolution | None:
        rows = tuple(
            connection.execute(
                """SELECT child.candidate_id, child.evaluator_id, child.status,
                              child.output_hash, projection.output_hash AS projection_hash,
                              projection.output_projection
                       FROM workflow_c_metric_model_children AS child
                       LEFT JOIN workflow_c_metric_child_output_projections AS projection
                         ON projection.project_id = child.project_id
                        AND projection.child_job_id = child.child_job_id
                      WHERE child.project_id = %s AND child.batch_id = %s
                        AND child.role = 'metric_judge'
                      ORDER BY child.evaluator_id, child.candidate_id
                      FOR SHARE""",
                (project_id, batch_id),
            ).fetchall()
        )
        if len(rows) < 2:
            raise WorkflowCMetricParentOrchestrationError("metric Judge batch has too few children")
        values = tuple(_mapping(row, "metric Judge child") for row in rows)
        statuses = {str(item.get("status")) for item in values}
        if statuses.intersection({"failed", "cancelled"}):
            raise WorkflowCMetricParentOrchestrationError("metric Judge child is terminal")
        if statuses.intersection(_CHILD_PENDING):
            return None
        if statuses != {"succeeded"}:
            raise WorkflowCMetricParentOrchestrationError("metric Judge child status changed")
        candidates: list[MetricJudgeCandidate] = []
        for value in values:
            output_hash = _hash(value.get("output_hash"), "metric Judge output hash")
            if value.get("projection_hash") != output_hash:
                raise WorkflowCMetricParentOrchestrationError(
                    "metric Judge output projection is unavailable"
                )
            projection = value.get("output_projection")
            if not isinstance(projection, Mapping):
                raise WorkflowCMetricParentOrchestrationError(
                    "metric Judge output projection is unavailable"
                )
            try:
                candidates.append(
                    metric_judge_candidate_from_projection(
                        candidate_id=_uuid(value.get("candidate_id"), "metric Judge candidate ID"),
                        evaluator_id=_text(value.get("evaluator_id"), "metric Judge evaluator ID"),
                        output_hash=output_hash,
                        projection=projection,
                    )
                )
            except WorkflowCMetricJudgeWorkerContractError as error:
                raise WorkflowCMetricParentOrchestrationError(
                    "metric Judge output projection is invalid"
                ) from error
        return resolve_metric_judge_candidates(tuple(candidates))

    def selected_candidate_in_transaction(
        self,
        connection: Any,
        *,
        project_id: UUID,
        batch: PersistedMetricBatch,
    ) -> MetricJudgeCandidate:
        if (
            batch.status != "completed"
            or batch.selected_candidate_id is None
            or batch.selected_output_hash is None
        ):
            raise WorkflowCMetricParentOrchestrationError("metric batch is not selected")
        row = _mapping(
            connection.execute(
                """SELECT child.candidate_id, child.evaluator_id, child.output_hash,
                              projection.output_hash AS projection_hash, projection.output_projection
                       FROM workflow_c_metric_model_children AS child
                       JOIN workflow_c_metric_child_output_projections AS projection
                         ON projection.project_id = child.project_id
                        AND projection.child_job_id = child.child_job_id
                      WHERE child.project_id = %s AND child.batch_id = %s
                        AND child.role = 'metric_judge' AND child.status = 'succeeded'
                        AND child.candidate_id = %s AND child.output_hash = %s""",
                (
                    project_id,
                    batch.batch_id,
                    batch.selected_candidate_id,
                    batch.selected_output_hash,
                ),
            ).fetchone(),
            "selected metric Judge child",
        )
        output_hash = _hash(row.get("output_hash"), "selected metric Judge output hash")
        if row.get("projection_hash") != output_hash:
            raise WorkflowCMetricParentOrchestrationError(
                "selected metric Judge projection is unavailable"
            )
        projection = row.get("output_projection")
        if not isinstance(projection, Mapping):
            raise WorkflowCMetricParentOrchestrationError(
                "selected metric Judge projection is unavailable"
            )
        try:
            return metric_judge_candidate_from_projection(
                candidate_id=_uuid(row.get("candidate_id"), "selected metric candidate ID"),
                evaluator_id=_text(row.get("evaluator_id"), "selected metric evaluator ID"),
                output_hash=output_hash,
                projection=projection,
            )
        except WorkflowCMetricJudgeWorkerContractError as error:
            raise WorkflowCMetricParentOrchestrationError(
                "selected metric Judge projection is invalid"
            ) from error

    def arbiter_child_status_in_transaction(
        self,
        connection: Any,
        *,
        project_id: UUID,
        batch: PersistedMetricBatch,
    ) -> str | None:
        if batch.arbiter_child_job_id is None:
            return None
        rows = tuple(
            connection.execute(
                """SELECT child_job_id, status FROM workflow_c_metric_model_children
                      WHERE project_id = %s AND batch_id = %s AND role = 'arbiter'
                      FOR SHARE""",
                (project_id, batch.batch_id),
            ).fetchall()
        )
        if len(rows) != 1:
            raise WorkflowCMetricParentOrchestrationError("metric Arbiter lineage changed")
        row = _mapping(rows[0], "metric Arbiter child")
        if _uuid(row.get("child_job_id"), "metric Arbiter child ID") != batch.arbiter_child_job_id:
            raise WorkflowCMetricParentOrchestrationError("metric Arbiter identity changed")
        status = _text(row.get("status"), "metric Arbiter status")
        if status in {"failed", "cancelled"}:
            raise WorkflowCMetricParentOrchestrationError("metric Arbiter child is terminal")
        if status == "succeeded":
            raise WorkflowCMetricParentOrchestrationError("metric Arbiter completed without batch")
        if status not in _CHILD_PENDING:
            raise WorkflowCMetricParentOrchestrationError("metric Arbiter child status changed")
        return status


class PostgresWorkflowCMetricParentOrchestrator:
    """Advance one parent through admission, polling, selection and persistence."""

    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        cipher: EnvelopeCipher,
        lease_for: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        poll_delay: timedelta = timedelta(seconds=15),
    ) -> None:
        if lease_for < timedelta(seconds=30) or poll_delay <= timedelta(0):
            raise ValueError("Metric parent lease and poll delay are invalid")
        self._store = store
        self._progress = PostgresWorkflowCMetricParentProgressRepository()
        self._judge_admission = PostgresWorkflowCMetricJudgeParentAdmissionRepository(cipher=cipher)
        self._arbiter_admission = PostgresWorkflowCMetricArbiterAdmissionRepository(cipher=cipher)
        self._lease_for, self._clock, self._poll_delay = lease_for, clock, poll_delay

    def execute(
        self,
        *,
        lease: WorkerLease,
        parent_input_hash: str,
        metadata: SemanticMetricMetadata,
        input_set: MetricInputSet,
        suite: FrozenMetricSuite,
        program: MetricModelProgramAdmission,
    ) -> Mapping[str, object]:
        if lease.kind != _PARENT_KIND or _HASH.fullmatch(parent_input_hash) is None:
            raise WorkflowCMetricParentOrchestrationError("metric parent lease is invalid")
        plans = _plans(input_set=input_set, suite=suite)
        if not plans:
            return self._persist(
                lease=lease,
                metadata=metadata,
                input_set=input_set,
                suite=suite,
                selected=(),
            )
        selected = self._advance_or_defer(
            lease=lease,
            parent_input_hash=parent_input_hash,
            metadata=metadata,
            input_set=input_set,
            suite=suite,
            plans=plans,
            program=program,
        )
        if isinstance(selected, _ParentFailed):
            return {"status": "failed", "job_id": str(lease.job_id)}
        if selected is None:
            return {"status": "waiting_for_metric_judges", "job_id": str(lease.job_id)}
        return self._persist(
            lease=lease,
            metadata=metadata,
            input_set=input_set,
            suite=suite,
            selected=selected,
        )

    def _advance_or_defer(
        self,
        *,
        lease: WorkerLease,
        parent_input_hash: str,
        metadata: SemanticMetricMetadata,
        input_set: MetricInputSet,
        suite: FrozenMetricSuite,
        plans: tuple[MetricJudgePlanBatch, ...],
        program: MetricModelProgramAdmission,
    ) -> tuple[SelectedMetricJudgeBatch, ...] | _ParentFailed | None:
        with self._store.fenced_transaction(lease) as connection:
            batches = self._progress.batches_in_transaction(
                connection,
                lease=lease,
                parent_input_hash=parent_input_hash,
                expected=plans,
                input_set_hash=input_set.input_set_hash,
                metric_suite_hash=suite.suite_hash,
            )
            if not batches:
                try:
                    self._judge_admission.admit_in_transaction(
                        connection,
                        lease=lease,
                        parent_input_hash=parent_input_hash,
                        admission=MetricJudgeParentAdmission(
                            run_id=metadata.run_id,
                            input_set=input_set,
                            suite=suite,
                            evaluators=program.judges,
                            admitted_by=program.admitted_by,
                            admitted_at=program.admitted_at,
                        ),
                    )
                except WorkflowCMetricParentAdmissionError as error:
                    raise WorkflowCMetricParentOrchestrationError(
                        "metric Judge admission is invalid"
                    ) from error
                self._defer(connection, lease, reason_code="metric_judges_admitted")
                return None

            if any(item.status in {"failed", "cancelled"} for item in batches):
                self._fail(connection, lease, error_code="metric_batch_terminal")
                return _FAILED
            if any(item.status == "queued" for item in batches):
                self._defer(connection, lease, reason_code="metric_judges_pending")
                return None

            plans_by_key = {(item.observation.id, item.ordinal): item for item in plans}
            has_pending = False
            for batch in batches:
                if batch.status == "completed":
                    continue
                if batch.status != "running":
                    raise WorkflowCMetricParentOrchestrationError("metric batch status changed")
                arbiter_status = self._progress.arbiter_child_status_in_transaction(
                    connection, project_id=lease.project_id, batch=batch
                )
                if arbiter_status is not None:
                    has_pending = True
                    continue
                resolution = self._progress.judge_resolution_in_transaction(
                    connection, project_id=lease.project_id, batch_id=batch.batch_id
                )
                if resolution is None:
                    has_pending = True
                    continue
                if not resolution.arbiter_required:
                    raise WorkflowCMetricParentOrchestrationError(
                        "matching metric Judges did not complete their batch"
                    )
                plan = plans_by_key[(batch.observation_id, batch.ordinal)]
                try:
                    self._arbiter_admission.admit_in_transaction(
                        connection,
                        lease=lease,
                        parent_input_hash=parent_input_hash,
                        input_set=input_set,
                        batch=plan,
                        resolution=resolution,
                        evaluator=program.arbiter,
                        admitted_by=program.admitted_by,
                        admitted_at=program.admitted_at,
                    )
                except WorkflowCMetricParentAdmissionError as error:
                    raise WorkflowCMetricParentOrchestrationError(
                        "metric Arbiter admission is invalid"
                    ) from error
                has_pending = True
            if has_pending:
                self._defer(connection, lease, reason_code="metric_judges_pending")
                return None
            selected = tuple(
                SelectedMetricJudgeBatch(
                    batch=plans_by_key[(batch.observation_id, batch.ordinal)],
                    candidate=self._progress.selected_candidate_in_transaction(
                        connection, project_id=lease.project_id, batch=batch
                    ),
                )
                for batch in batches
            )
        return selected

    def _persist(
        self,
        *,
        lease: WorkerLease,
        metadata: SemanticMetricMetadata,
        input_set: MetricInputSet,
        suite: FrozenMetricSuite,
        selected: Sequence[SelectedMetricJudgeBatch],
    ) -> Mapping[str, object]:
        try:
            merged = merge_selected_metric_judge_batches(
                input_set=input_set, suite=suite, selected_batches=selected
            )
        except ValueError as error:
            raise WorkflowCMetricParentOrchestrationError(
                "selected metric batches are invalid"
            ) from error
        with LeaseHeartbeat(
            self._store,
            lease,
            lease_for=self._lease_for,
            interval=min(self._lease_for / 3, timedelta(seconds=30)),
        ) as heartbeat:
            snapshot = compute_semantic_metric_snapshot(
                input_set=merged, suite=suite, computed_at=_aware_now(self._clock)
            )
            heartbeat.raise_if_stopped()
        status = (
            "complete"
            if all(item.status is MetricStatus.COMPLETE for item in snapshot.results)
            else "insufficient_evidence"
        )
        persist_semantic_snapshot(
            self._store,
            lease,
            snapshot=snapshot,
            run_id=metadata.run_id,
            source_stratum_hash=metadata.source_stratum_hash,
            capture_method=metadata.capture_method,
            warning_ratio=metadata.warning_ratio,
            test_only=metadata.test_only,
            synthetic=metadata.synthetic,
            evidence_status=status,
        )
        return {
            "status": status,
            "job_id": str(lease.job_id),
            "snapshot_hash": snapshot.snapshot_hash,
        }

    def _defer(self, connection: Any, lease: WorkerLease, *, reason_code: str) -> None:
        self._store.defer_in_transaction(
            connection,
            lease,
            reason_code=reason_code,
            details={"metric_parent": True},
            retry_delay=self._poll_delay,
        )

    def _fail(self, connection: Any, lease: WorkerLease, *, error_code: str) -> None:
        self._store.fail_in_transaction(
            connection,
            lease,
            error_code=error_code,
            details={"metric_parent": True},
        )


def _plans(
    *, input_set: MetricInputSet, suite: FrozenMetricSuite
) -> tuple[MetricJudgePlanBatch, ...]:
    return tuple(
        batch
        for observation in input_set.observations
        for batch in plan_metric_judge_batches(
            input_set=input_set, suite=suite, observation=observation
        )
    )


def _batch(
    row: object,
    *,
    parent_input_hash: str,
    expected: Mapping[tuple[UUID, int], MetricJudgePlanBatch],
    expected_count: int,
    input_set_hash: str,
    metric_suite_hash: str,
) -> PersistedMetricBatch:
    value = _mapping(row, "metric parent batch")
    batch_id = _uuid(value.get("id"), "metric batch ID")
    observation_id = _uuid(value.get("observation_id"), "metric batch observation ID")
    ordinal = _positive(value.get("ordinal"), "metric batch ordinal")
    plan = expected.get((observation_id, ordinal))
    status = _text(value.get("status"), "metric batch status")
    selected_id = _optional_uuid(value.get("selected_candidate_id"), "selected metric candidate ID")
    selected_hash = _optional_hash(value.get("selected_output_hash"), "selected metric output hash")
    if (
        plan is None
        or value.get("planned_batch_count") != expected_count
        or value.get("parent_input_hash") != parent_input_hash
        or value.get("input_set_hash") != input_set_hash
        or value.get("metric_suite_hash") != metric_suite_hash
        or value.get("plans_hash") != plan.input_hash
        or status not in _BATCH_STATUSES
        or (status == "completed") != (selected_id is not None and selected_hash is not None)
        or (status != "completed" and (selected_id is not None or selected_hash is not None))
    ):
        raise WorkflowCMetricParentOrchestrationError("metric parent batch lineage changed")
    return PersistedMetricBatch(
        batch_id=batch_id,
        observation_id=observation_id,
        ordinal=ordinal,
        plans_hash=plan.input_hash,
        status=status,
        selected_candidate_id=selected_id,
        selected_output_hash=selected_hash,
        arbiter_child_job_id=_optional_uuid(
            value.get("arbiter_child_job_id"), "metric Arbiter child ID"
        ),
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise WorkflowCMetricParentOrchestrationError(f"{label} is invalid")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowCMetricParentOrchestrationError(f"{label} is invalid")
    return value


def _hash(value: object, label: str) -> str:
    parsed = _text(value, label)
    if _HASH.fullmatch(parsed) is None:
        raise WorkflowCMetricParentOrchestrationError(f"{label} is invalid")
    return parsed


def _optional_hash(value: object, label: str) -> str | None:
    return None if value is None else _hash(value, label)


def _uuid(value: object, label: str) -> UUID:
    if isinstance(value, UUID) and value.int != 0:
        return value
    if isinstance(value, str):
        try:
            parsed = UUID(value)
        except ValueError as error:
            raise WorkflowCMetricParentOrchestrationError(f"{label} is invalid") from error
        if parsed.int != 0:
            return parsed
    raise WorkflowCMetricParentOrchestrationError(f"{label} is invalid")


def _optional_uuid(value: object, label: str) -> UUID | None:
    return None if value is None else _uuid(value, label)


def _positive(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise WorkflowCMetricParentOrchestrationError(f"{label} is invalid")
    return value


def _aware_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowCMetricParentOrchestrationError("metric parent clock must be timezone-aware")
    return value


__all__ = [
    "PostgresWorkflowCMetricParentOrchestrator",
    "PostgresWorkflowCMetricParentProgressRepository",
    "WorkflowCMetricParentOrchestrationError",
]
