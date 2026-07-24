"""Atomic admission input for encrypted Workflow C Metric Judge children."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any
from uuid import UUID, uuid5

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.secrets import EnvelopeCipher
from geo_core.semantic_metrics import (
    FrozenMetricSuite,
    MetricInputSet,
    MetricJudgeCandidateResolution,
    MetricJudgePlanBatch,
    plan_metric_judge_batches,
)
from geo_core.workflow_c_metric_judge_worker_contracts import (
    ModelRequestTask,
    build_metric_arbiter_task,
    build_metric_judge_task,
    freeze_metric_task,
)


_HASH = re.compile(r"^[0-9a-f]{64}$")
_NAMESPACE = UUID("30ec7f46-fc54-50cb-a55f-058f6c28dd82")
_PARENT_KIND = "workflow_c.analysis.semantic_metrics"
_CHILD_KIND = "workflow_c.metric_judge"


class WorkflowCMetricParentAdmissionError(RuntimeError):
    """A parent Metric Job cannot safely admit its Judge child batch."""


@dataclass(frozen=True)
class MetricJudgeEvaluatorAdmission:
    """Frozen Model/Prompt lineage for one independently selected Judge."""

    evaluator_id: str
    runtime_selection_id: UUID
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    prompt_binding_id: UUID
    prompt_binding_version: int
    prompt_frozen_state_id: UUID
    prompt_state_version: int
    prompt_release_id: UUID
    prompt_release_version: int
    prompt_release_hash: str
    prompt_purpose: str
    prompt_bundle_hash: str
    request: ModelRequestTask

    def __post_init__(self) -> None:
        if not self.evaluator_id.strip():
            raise WorkflowCMetricParentAdmissionError("metric evaluator ID is required")
        for value, label in (
            (self.runtime_selection_id, "metric runtime selection"),
            (self.runtime_manifest_id, "metric runtime manifest"),
            (self.runtime_option_id, "metric runtime option"),
            (self.prompt_binding_id, "metric Prompt binding"),
            (self.prompt_frozen_state_id, "metric Prompt state"),
            (self.prompt_release_id, "metric Prompt Release"),
        ):
            if not isinstance(value, UUID) or value.int == 0:
                raise WorkflowCMetricParentAdmissionError(f"{label} is invalid")
        for digest, label in (
            (self.runtime_manifest_hash, "metric runtime manifest hash"),
            (self.runtime_option_hash, "metric runtime option hash"),
            (self.prompt_release_hash, "metric Prompt Release hash"),
            (self.prompt_bundle_hash, "metric Prompt bundle hash"),
        ):
            if _HASH.fullmatch(digest) is None:
                raise WorkflowCMetricParentAdmissionError(f"{label} is invalid")
        if (
            self.prompt_binding_version < 1
            or self.prompt_state_version < 1
            or self.prompt_release_version < 1
            or not self.prompt_purpose.strip()
        ):
            raise WorkflowCMetricParentAdmissionError("metric Prompt lineage is invalid")
        if self.runtime_selection_id != self.runtime_option_id:
            raise WorkflowCMetricParentAdmissionError(
                "metric runtime selection and option must be identical"
            )

    @property
    def portable_output_schema_hash(self) -> str:
        return canonical_json_hash(self.request.output_schema)

    @property
    def application_output_schema_hash(self) -> str:
        return canonical_json_hash(self.request.application_output_schema)


@dataclass(frozen=True)
class MetricArbiterEvaluatorAdmission:
    """Frozen Model/Prompt lineage for an Arbiter selected after Judge disagreement."""

    evaluator_id: str
    runtime_selection_id: UUID
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    prompt_binding_id: UUID
    prompt_binding_version: int
    prompt_frozen_state_id: UUID
    prompt_state_version: int
    prompt_release_id: UUID
    prompt_release_version: int
    prompt_release_hash: str
    prompt_purpose: str
    prompt_bundle_hash: str
    request: ModelRequestTask

    def __post_init__(self) -> None:
        if not self.evaluator_id.strip():
            raise WorkflowCMetricParentAdmissionError("metric arbiter evaluator ID is required")
        for value, label in (
            (self.runtime_selection_id, "metric arbiter runtime selection"),
            (self.runtime_manifest_id, "metric arbiter runtime manifest"),
            (self.runtime_option_id, "metric arbiter runtime option"),
            (self.prompt_binding_id, "metric arbiter Prompt binding"),
            (self.prompt_frozen_state_id, "metric arbiter Prompt state"),
            (self.prompt_release_id, "metric arbiter Prompt Release"),
        ):
            if not isinstance(value, UUID) or value.int == 0:
                raise WorkflowCMetricParentAdmissionError(f"{label} is invalid")
        for digest, label in (
            (self.runtime_manifest_hash, "metric arbiter runtime manifest hash"),
            (self.runtime_option_hash, "metric arbiter runtime option hash"),
            (self.prompt_release_hash, "metric arbiter Prompt Release hash"),
            (self.prompt_bundle_hash, "metric arbiter Prompt bundle hash"),
        ):
            if _HASH.fullmatch(digest) is None:
                raise WorkflowCMetricParentAdmissionError(f"{label} is invalid")
        if (
            self.prompt_binding_version < 1
            or self.prompt_state_version < 1
            or self.prompt_release_version < 1
            or not self.prompt_purpose.strip()
        ):
            raise WorkflowCMetricParentAdmissionError("metric arbiter Prompt lineage is invalid")
        if self.runtime_selection_id != self.runtime_option_id:
            raise WorkflowCMetricParentAdmissionError(
                "metric arbiter runtime selection and option must be identical"
            )

    @property
    def portable_output_schema_hash(self) -> str:
        return canonical_json_hash(self.request.output_schema)

    @property
    def application_output_schema_hash(self) -> str:
        return canonical_json_hash(self.request.application_output_schema)


@dataclass(frozen=True)
class MetricJudgeParentAdmission:
    """All server-owned facts required before a parent creates child Jobs."""

    run_id: UUID
    input_set: MetricInputSet
    suite: FrozenMetricSuite
    evaluators: tuple[MetricJudgeEvaluatorAdmission, ...]
    admitted_by: UUID
    admitted_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, UUID) or self.run_id.int == 0:
            raise WorkflowCMetricParentAdmissionError("metric sampling run ID is invalid")
        if not isinstance(self.admitted_by, UUID) or self.admitted_by.int == 0:
            raise WorkflowCMetricParentAdmissionError("metric admission actor is invalid")
        if self.admitted_at.tzinfo is None or self.admitted_at.utcoffset() is None:
            raise WorkflowCMetricParentAdmissionError("metric admission time must be timezone-aware")
        evaluators = tuple(sorted(self.evaluators, key=lambda item: item.evaluator_id))
        if len(evaluators) < 2 or len({item.evaluator_id for item in evaluators}) != len(
            evaluators
        ):
            raise WorkflowCMetricParentAdmissionError(
                "metric admission requires at least two distinct evaluators"
            )
        judge = self.suite.judge_version
        if any(
            item.prompt_release_id != judge.prompt_release_id
            or item.prompt_release_hash != judge.prompt_release_hash
            for item in evaluators
        ):
            raise WorkflowCMetricParentAdmissionError(
                "metric evaluator Prompt Release differs from the frozen suite"
            )
        object.__setattr__(self, "evaluators", evaluators)


@dataclass(frozen=True)
class AdmittedMetricJudgeBatch:
    batch_id: UUID
    child_count: int


class PostgresWorkflowCMetricJudgeParentAdmissionRepository:
    """Create all planned Judge batches, encrypted tasks and wakeups atomically."""

    def __init__(self, *, cipher: EnvelopeCipher) -> None:
        self._cipher = cipher

    def admit_in_transaction(
        self,
        connection: Any,
        *,
        lease: WorkerLease,
        parent_input_hash: str,
        admission: MetricJudgeParentAdmission,
    ) -> tuple[AdmittedMetricJudgeBatch, ...]:
        if lease.kind != _PARENT_KIND or _HASH.fullmatch(parent_input_hash) is None:
            raise WorkflowCMetricParentAdmissionError("metric parent lease is invalid")
        payload = _admission_payload(
            cipher=self._cipher,
            lease=lease,
            parent_input_hash=parent_input_hash,
            admission=admission,
        )
        if not payload:
            return ()
        rows = tuple(
            connection.execute(
                """SELECT * FROM geo_admit_workflow_c_metric_judge_batches(
                       %s, %s, %s, %s, %s, %s::jsonb
                   )""",
                (
                    lease.project_id,
                    lease.job_id,
                    lease.lease_token,
                    lease.fencing_generation,
                    parent_input_hash,
                    _canonical_json(payload),
                ),
            ).fetchall()
        )
        admitted = tuple(_admitted_batch(row) for row in rows)
        expected = {UUID(str(item["id"])) for item in payload}
        if (
            len(admitted) != len(expected)
            or {item.batch_id for item in admitted} != expected
            or any(item.child_count != len(admission.evaluators) for item in admitted)
        ):
            raise WorkflowCMetricParentAdmissionError("metric parent admission result changed")
        return tuple(sorted(admitted, key=lambda item: str(item.batch_id)))


def _admission_payload(
    *,
    cipher: EnvelopeCipher,
    lease: WorkerLease,
    parent_input_hash: str,
    admission: MetricJudgeParentAdmission,
) -> list[dict[str, object]]:
    plans = tuple(
        batch
        for observation in admission.input_set.observations
        for batch in plan_metric_judge_batches(
            input_set=admission.input_set,
            suite=admission.suite,
            observation=observation,
        )
    )
    planned_count = len(plans)
    batches: list[dict[str, object]] = []
    for batch in plans:
        batch_id = _batch_id(lease=lease, batch=batch)
        children = [
            _child_payload(
                cipher=cipher,
                lease=lease,
                parent_input_hash=parent_input_hash,
                admission=admission,
                batch=batch,
                batch_id=batch_id,
                evaluator=evaluator,
            )
            for evaluator in admission.evaluators
        ]
        batches.append(
            {
                "id": str(batch_id),
                "run_id": str(admission.run_id),
                "observation_id": str(batch.observation.id),
                "ordinal": batch.ordinal,
                "planned_batch_count": planned_count,
                "plans_hash": batch.input_hash,
                "input_set_hash": admission.input_set.input_set_hash,
                "metric_suite_hash": admission.suite.suite_hash,
                "children": children,
            }
        )
    return batches


def _child_payload(
    *,
    cipher: EnvelopeCipher,
    lease: WorkerLease,
    parent_input_hash: str,
    admission: MetricJudgeParentAdmission,
    batch: MetricJudgePlanBatch,
    batch_id: UUID,
    evaluator: MetricJudgeEvaluatorAdmission,
) -> dict[str, object]:
    child_job_id = uuid5(_NAMESPACE, f"metric-child:{batch_id}:{evaluator.evaluator_id}")
    candidate_id = uuid5(_NAMESPACE, f"metric-candidate:{batch_id}:{evaluator.evaluator_id}")
    task = build_metric_judge_task(
        admitted_by=admission.admitted_by,
        admitted_at=admission.admitted_at,
        request=evaluator.request,
        input_set=admission.input_set,
        batch=batch,
        schema_version=admission.suite.judge_version.schema_version,
    )
    frozen = freeze_metric_task(
        cipher=cipher,
        project_id=lease.project_id,
        child_job_id=child_job_id,
        task=task,
        created_at=admission.admitted_at,
    )
    spec_payload = {
        "schema_version": 1,
        "kind": _CHILD_KIND,
        "metric_model_child": {
            "child_job_id": str(child_job_id),
            "parent_job_id": str(lease.job_id),
            "batch_id": str(batch_id),
            "role": "metric_judge",
            "parent_input_hash": parent_input_hash,
            "task_hash": frozen.task_hash,
        },
    }
    envelope = frozen.envelope
    return {
        "id": str(child_job_id),
        "candidate_id": str(candidate_id),
        "ordinal": _evaluator_ordinal(admission.evaluators, evaluator),
        "evaluator_id": evaluator.evaluator_id,
        "runtime_selection_id": str(evaluator.runtime_selection_id),
        "runtime_manifest_id": str(evaluator.runtime_manifest_id),
        "runtime_manifest_hash": evaluator.runtime_manifest_hash,
        "runtime_option_id": str(evaluator.runtime_option_id),
        "runtime_option_hash": evaluator.runtime_option_hash,
        "prompt_binding_id": str(evaluator.prompt_binding_id),
        "prompt_binding_version": evaluator.prompt_binding_version,
        "prompt_frozen_state_id": str(evaluator.prompt_frozen_state_id),
        "prompt_state_version": evaluator.prompt_state_version,
        "prompt_release_id": str(evaluator.prompt_release_id),
        "prompt_release_version": evaluator.prompt_release_version,
        "prompt_release_hash": evaluator.prompt_release_hash,
        "prompt_purpose": evaluator.prompt_purpose,
        "prompt_bundle_hash": evaluator.prompt_bundle_hash,
        "portable_output_schema_hash": evaluator.portable_output_schema_hash,
        "application_output_schema_hash": evaluator.application_output_schema_hash,
        "task_ciphertext": _base64(envelope.ciphertext),
        "task_data_nonce": _base64(envelope.data_nonce),
        "task_wrapped_data_key": _base64(envelope.wrapped_data_key),
        "task_wrap_nonce": _base64(envelope.wrap_nonce),
        "task_master_key_version": envelope.master_key_version,
        "task_algorithm": envelope.algorithm,
        "task_hash": frozen.task_hash,
        "spec_hash": canonical_json_hash(spec_payload),
        "spec_payload": spec_payload,
    }


def build_metric_arbiter_child_payload(
    *,
    cipher: EnvelopeCipher,
    lease: WorkerLease,
    parent_input_hash: str,
    input_set: MetricInputSet,
    batch: MetricJudgePlanBatch,
    resolution: MetricJudgeCandidateResolution,
    evaluator: MetricArbiterEvaluatorAdmission,
    admitted_by: UUID,
    admitted_at: datetime,
) -> dict[str, object]:
    """Prepare the one encrypted Arbiter child permitted for a disagreeing batch.

    The returned dictionary is intentionally the database admission payload shape.
    Candidate output/rationale remains inside the encrypted task; the immutable
    Job spec is only a safe wake/reference bound to the task plaintext hash.
    """

    if lease.kind != _PARENT_KIND or _HASH.fullmatch(parent_input_hash) is None:
        raise WorkflowCMetricParentAdmissionError("metric arbiter parent lease is invalid")
    if not resolution.arbiter_required:
        raise WorkflowCMetricParentAdmissionError(
            "metric arbiter admission is forbidden when judges agree"
        )
    if any(_uuid_or_none(item.candidate_id) is None for item in resolution.candidates):
        raise WorkflowCMetricParentAdmissionError(
            "metric arbiter Judge candidate identity must be a UUID"
        )
    if admitted_at.tzinfo is None or admitted_at.utcoffset() is None:
        raise WorkflowCMetricParentAdmissionError("metric arbiter admission time must be timezone-aware")
    if not isinstance(admitted_by, UUID) or admitted_by.int == 0:
        raise WorkflowCMetricParentAdmissionError("metric arbiter admission actor is invalid")
    batch_id = _batch_id(lease=lease, batch=batch)
    child_job_id = uuid5(_NAMESPACE, f"metric-arbiter:{batch_id}:{evaluator.evaluator_id}")
    candidate_id = uuid5(_NAMESPACE, f"metric-arbiter-candidate:{batch_id}:{evaluator.evaluator_id}")
    task = build_metric_arbiter_task(
        admitted_by=admitted_by,
        admitted_at=admitted_at,
        request=evaluator.request,
        input_set=input_set,
        batch=batch,
        resolution=resolution,
    )
    frozen = freeze_metric_task(
        cipher=cipher,
        project_id=lease.project_id,
        child_job_id=child_job_id,
        task=task,
        created_at=admitted_at,
    )
    spec_payload = {
        "schema_version": 1,
        "kind": "workflow_c.metric_arbiter",
        "metric_model_child": {
            "child_job_id": str(child_job_id),
            "parent_job_id": str(lease.job_id),
            "batch_id": str(batch_id),
            "role": "arbiter",
            "parent_input_hash": parent_input_hash,
            "task_hash": frozen.task_hash,
        },
    }
    envelope = frozen.envelope
    return {
        "id": str(child_job_id),
        "candidate_id": str(candidate_id),
        "ordinal": 1,
        "evaluator_id": evaluator.evaluator_id,
        "runtime_selection_id": str(evaluator.runtime_selection_id),
        "runtime_manifest_id": str(evaluator.runtime_manifest_id),
        "runtime_manifest_hash": evaluator.runtime_manifest_hash,
        "runtime_option_id": str(evaluator.runtime_option_id),
        "runtime_option_hash": evaluator.runtime_option_hash,
        "prompt_binding_id": str(evaluator.prompt_binding_id),
        "prompt_binding_version": evaluator.prompt_binding_version,
        "prompt_frozen_state_id": str(evaluator.prompt_frozen_state_id),
        "prompt_state_version": evaluator.prompt_state_version,
        "prompt_release_id": str(evaluator.prompt_release_id),
        "prompt_release_version": evaluator.prompt_release_version,
        "prompt_release_hash": evaluator.prompt_release_hash,
        "prompt_purpose": evaluator.prompt_purpose,
        "prompt_bundle_hash": evaluator.prompt_bundle_hash,
        "portable_output_schema_hash": evaluator.portable_output_schema_hash,
        "application_output_schema_hash": evaluator.application_output_schema_hash,
        "task_ciphertext": _base64(envelope.ciphertext),
        "task_data_nonce": _base64(envelope.data_nonce),
        "task_wrapped_data_key": _base64(envelope.wrapped_data_key),
        "task_wrap_nonce": _base64(envelope.wrap_nonce),
        "task_master_key_version": envelope.master_key_version,
        "task_algorithm": envelope.algorithm,
        "task_hash": frozen.task_hash,
        "spec_hash": canonical_json_hash(spec_payload),
        "spec_payload": spec_payload,
    }


def _batch_id(*, lease: WorkerLease, batch: MetricJudgePlanBatch) -> UUID:
    return uuid5(
        _NAMESPACE,
        f"metric-batch:{lease.project_id}:{lease.job_id}:{batch.observation.id}:"
        f"{batch.ordinal}:{batch.input_hash}",
    )


def _evaluator_ordinal(
    evaluators: Sequence[MetricJudgeEvaluatorAdmission],
    evaluator: MetricJudgeEvaluatorAdmission,
) -> int:
    return tuple(item.evaluator_id for item in evaluators).index(evaluator.evaluator_id) + 1


def _base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError, AttributeError):
        return None


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError) as error:
        raise WorkflowCMetricParentAdmissionError(
            "metric parent admission payload is not canonical JSON"
        ) from error


def _admitted_batch(row: object) -> AdmittedMetricJudgeBatch:
    if not isinstance(row, Mapping):
        raise WorkflowCMetricParentAdmissionError("metric parent admission row is invalid")
    batch_id, child_count = row.get("batch_id"), row.get("child_count")
    if (
        not isinstance(batch_id, UUID)
        or not isinstance(child_count, int)
        or isinstance(child_count, bool)
        or child_count < 2
    ):
        raise WorkflowCMetricParentAdmissionError("metric parent admission row changed")
    return AdmittedMetricJudgeBatch(batch_id=batch_id, child_count=child_count)


__all__ = [
    "AdmittedMetricJudgeBatch",
    "MetricArbiterEvaluatorAdmission",
    "MetricJudgeEvaluatorAdmission",
    "MetricJudgeParentAdmission",
    "PostgresWorkflowCMetricJudgeParentAdmissionRepository",
    "WorkflowCMetricParentAdmissionError",
    "build_metric_arbiter_child_payload",
]
