"""Worker-only atomic admission for a disagreeing Metric Judge batch Arbiter."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.secrets import EnvelopeCipher
from geo_core.semantic_metrics import (
    MetricInputSet,
    MetricJudgeCandidateResolution,
    MetricJudgePlanBatch,
)
from geo_core.workflow_c_metric_parent_admission import (
    MetricArbiterEvaluatorAdmission,
    WorkflowCMetricParentAdmissionError,
    build_metric_arbiter_child_payload,
)


_HASH = re.compile(r"^[0-9a-f]{64}$")
_PARENT_KIND = "workflow_c.analysis.semantic_metrics"


@dataclass(frozen=True)
class AdmittedMetricArbiterChild:
    """Identity of the one Arbiter atomically queued for a Judge batch."""

    batch_id: UUID
    child_job_id: UUID


class PostgresWorkflowCMetricArbiterAdmissionRepository:
    """Invoke the database transaction that creates one encrypted Arbiter child."""

    def __init__(self, *, cipher: EnvelopeCipher) -> None:
        self._cipher = cipher

    def admit_in_transaction(
        self,
        connection: Any,
        *,
        lease: WorkerLease,
        parent_input_hash: str,
        input_set: MetricInputSet,
        batch: MetricJudgePlanBatch,
        resolution: MetricJudgeCandidateResolution,
        evaluator: MetricArbiterEvaluatorAdmission,
        admitted_by: UUID,
        admitted_at: datetime,
    ) -> AdmittedMetricArbiterChild:
        if lease.kind != _PARENT_KIND or _HASH.fullmatch(parent_input_hash) is None:
            raise WorkflowCMetricParentAdmissionError("metric arbiter parent lease is invalid")
        payload = build_metric_arbiter_child_payload(
            cipher=self._cipher,
            lease=lease,
            parent_input_hash=parent_input_hash,
            input_set=input_set,
            batch=batch,
            resolution=resolution,
            evaluator=evaluator,
            admitted_by=admitted_by,
            admitted_at=admitted_at,
        )
        spec = _mapping(payload.get("spec_payload"), "metric arbiter public spec")
        reference = _mapping(spec.get("metric_model_child"), "metric arbiter child reference")
        batch_id = _uuid(reference.get("batch_id"), "metric arbiter batch ID")
        expected_child_id = _uuid(payload.get("id"), "metric arbiter child ID")
        row = connection.execute(
            """SELECT geo_admit_workflow_c_metric_arbiter_child(
                   %s, %s, %s, %s, %s, %s, %s::jsonb
               )""",
            (
                lease.project_id,
                lease.job_id,
                lease.lease_token,
                lease.fencing_generation,
                parent_input_hash,
                batch_id,
                _canonical_json(payload),
            ),
        ).fetchone()
        child_id = _row_uuid(row)
        if child_id != expected_child_id:
            raise WorkflowCMetricParentAdmissionError("metric arbiter admission result changed")
        return AdmittedMetricArbiterChild(batch_id=batch_id, child_job_id=child_id)


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError) as error:
        raise WorkflowCMetricParentAdmissionError(
            "metric arbiter admission payload is not canonical JSON"
        ) from error


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise WorkflowCMetricParentAdmissionError(f"{label} is invalid")
    return value


def _uuid(value: object, label: str) -> UUID:
    if isinstance(value, UUID) and value.int != 0:
        return value
    if isinstance(value, str):
        try:
            parsed = UUID(value)
        except ValueError as error:
            raise WorkflowCMetricParentAdmissionError(f"{label} is invalid") from error
        if parsed.int != 0:
            return parsed
    raise WorkflowCMetricParentAdmissionError(f"{label} is invalid")


def _row_uuid(row: object) -> UUID:
    if isinstance(row, Mapping):
        if len(row) != 1:
            raise WorkflowCMetricParentAdmissionError("metric arbiter admission row is invalid")
        return _uuid(next(iter(row.values())), "metric arbiter admission child ID")
    if isinstance(row, tuple) and len(row) == 1:
        return _uuid(row[0], "metric arbiter admission child ID")
    raise WorkflowCMetricParentAdmissionError("metric arbiter admission row is invalid")


__all__ = [
    "AdmittedMetricArbiterChild",
    "PostgresWorkflowCMetricArbiterAdmissionRepository",
]
