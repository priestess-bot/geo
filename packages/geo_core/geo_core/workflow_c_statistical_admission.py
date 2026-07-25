"""Atomic server-side admission for statistical comparison and drift Jobs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import psycopg

from geo_core.project_scope import set_project_scope
from geo_core.statistical_methods import StatisticalRuleViolation
from geo_core.workflow_c_job_specs import (
    WorkflowCEnqueuedJob,
    WorkflowCJobSpecError,
    enqueue_workflow_c_job_spec_in_transaction,
)
from geo_core.workflow_c_statistical_analysis_inputs import (
    _comparison_inputs as _comparison_inputs,
    _drift_inputs as _drift_inputs,
)
from geo_core.workflow_c_statistical_protocols import (
    ComparisonPlanDefinition,
    StatisticalProtocolError,
    StatisticalProtocolKind,
)
from geo_core.workflow_c_statistical_snapshot_inputs import (
    PostgresWorkflowCStatisticalAdmissionError,
    _ApprovedProtocol as _ApprovedProtocol,
    _hash,
    _load_protocol,
    _load_snapshots,
    _snapshot as _snapshot,
    _text,
)
from geo_core.workflow_c_statistical_specs import (
    comparison_input_value,
    drift_observation_value,
)


_COMPARISON_KIND = "workflow_c.analysis.comparison"
_DRIFT_KIND = "workflow_c.analysis.drift"


class PostgresWorkflowCStatisticalAdmissionRepository:
    """Resolve approved protocols and immutable snapshots in one transaction."""

    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def enqueue_comparison(
        self,
        *,
        project_id: UUID,
        comparison_plan_id: UUID,
        baseline_snapshot_hash: str,
        candidate_snapshot_hash: str,
        actor_id: str,
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> WorkflowCEnqueuedJob:
        return self._enqueue(
            project_id=project_id,
            protocol_id=comparison_plan_id,
            expected_protocol_kind=StatisticalProtocolKind.COMPARISON_PLAN,
            source_snapshot_hash=baseline_snapshot_hash,
            target_snapshot_hash=candidate_snapshot_hash,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
        )

    def enqueue_drift(
        self,
        *,
        project_id: UUID,
        drift_protocol_id: UUID,
        baseline_snapshot_hash: str,
        current_snapshot_hash: str,
        actor_id: str,
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> WorkflowCEnqueuedJob:
        return self._enqueue(
            project_id=project_id,
            protocol_id=drift_protocol_id,
            expected_protocol_kind=StatisticalProtocolKind.DRIFT_PROTOCOL,
            source_snapshot_hash=baseline_snapshot_hash,
            target_snapshot_hash=current_snapshot_hash,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
        )

    def _enqueue(
        self,
        *,
        project_id: UUID,
        protocol_id: UUID,
        expected_protocol_kind: StatisticalProtocolKind,
        source_snapshot_hash: str,
        target_snapshot_hash: str,
        actor_id: str,
        idempotency_key: str,
        max_attempts: int,
    ) -> WorkflowCEnqueuedJob:
        source_hash = _hash(source_snapshot_hash, "source metric snapshot hash")
        target_hash = _hash(target_snapshot_hash, "target metric snapshot hash")
        if source_hash == target_hash:
            raise PostgresWorkflowCStatisticalAdmissionError(
                "statistical source and target snapshots must differ"
            )
        actor = _text(actor_id, "statistical analysis actor")
        key = _text(idempotency_key, "statistical analysis Idempotency-Key", maximum=200)
        if max_attempts < 1:
            raise PostgresWorkflowCStatisticalAdmissionError(
                "statistical analysis max attempts must be positive"
            )
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            protocol = _load_protocol(
                connection,
                project_id=project_id,
                protocol_id=protocol_id,
                expected_kind=expected_protocol_kind,
            )
            source, target = _load_snapshots(
                connection,
                project_id=project_id,
                source_hash=source_hash,
                target_hash=target_hash,
            )
            if isinstance(protocol.definition, ComparisonPlanDefinition):
                kind = _COMPARISON_KIND
                body: dict[str, object] = {
                    "inputs": [
                        comparison_input_value(item)
                        for item in _comparison_inputs(
                            protocol=protocol,
                            baseline=source,
                            candidate=target,
                        )
                    ]
                }
                operation = "comparison"
            else:
                kind = _DRIFT_KIND
                baseline, current = _drift_inputs(
                    protocol=protocol,
                    baseline=source,
                    current=target,
                )
                body = {
                    "source_snapshot_hash": source.snapshot_hash,
                    "target_snapshot_hash": target.snapshot_hash,
                    "baseline": [drift_observation_value(item) for item in baseline],
                    "current": [drift_observation_value(item) for item in current],
                }
                operation = "drift"
            payload = {
                "schema_version": 1,
                "kind": kind,
                "admission": {
                    "protocol_kind": expected_protocol_kind.value,
                    "protocol_id": str(protocol.id),
                    "protocol_hash": protocol.definition_hash,
                    "source_snapshot_hash": source.snapshot_hash,
                    "target_snapshot_hash": target.snapshot_hash,
                    "requested_by": actor,
                },
                operation: body,
            }
            result = enqueue_workflow_c_job_spec_in_transaction(
                connection,
                project_id=project_id,
                kind=kind,
                payload=payload,
                idempotency_key=key,
                max_attempts=max_attempts,
            )
            connection.commit()
            return result
        except PostgresWorkflowCStatisticalAdmissionError:
            connection.rollback()
            raise
        except (
            StatisticalProtocolError,
            StatisticalRuleViolation,
            WorkflowCJobSpecError,
            ValueError,
        ) as error:
            connection.rollback()
            raise PostgresWorkflowCStatisticalAdmissionError(str(error)) from error
        except psycopg.Error as error:
            connection.rollback()
            detail = getattr(error.diag, "message_primary", "") or ""
            raise PostgresWorkflowCStatisticalAdmissionError(
                detail or "PostgreSQL rejected statistical analysis admission"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


__all__ = [
    "PostgresWorkflowCStatisticalAdmissionError",
    "PostgresWorkflowCStatisticalAdmissionRepository",
]
