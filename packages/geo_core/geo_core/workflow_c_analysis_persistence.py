"""Fenced PostgreSQL persistence for Workflow C analytical result projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.semantic_metrics import MetricStatus
from geo_core.statistical_methods import ComparisonInput
from geo_core.statistical_methods.contracts import canonical_hash, decimal_value
from geo_core.workflow_c_analysis_common import (
    WorkflowCAnalysisWorkerError,
    canonical_json,
    decimal_equal,
    json_value,
    mapping_row,
)


def persist_semantic_snapshot(
    store: PostgresDurableJobStore,
    lease: WorkerLease,
    *,
    snapshot: Any,
    run_id: UUID,
    source_stratum_hash: str,
    capture_method: str,
    warning_ratio: Decimal,
    test_only: bool,
    synthetic: bool,
    evidence_status: str,
) -> None:
    payload = snapshot.canonical_value()
    result_rows = tuple(_semantic_result_row(result) for result in snapshot.results)
    with store.fenced_transaction(lease) as connection:
        connection.execute(
            """SELECT geo_persist_workflow_c_semantic_metric_snapshot(
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s::jsonb, %s, %s::jsonb
               )""",
            (
                lease.project_id,
                lease.job_id,
                lease.lease_token,
                lease.fencing_generation,
                snapshot.snapshot_hash,
                run_id,
                snapshot.input_set_hash,
                snapshot.suite_hash,
                source_stratum_hash,
                capture_method,
                evidence_status,
                warning_ratio,
                test_only,
                synthetic,
                json_value(payload),
                snapshot.computed_at,
                json_value(result_rows),
            ),
        )
        row = mapping_row(
            connection.execute(
                """SELECT project_id, run_id, input_set_hash, metric_suite_hash,
                              source_stratum_hash, capture_method, evidence_status,
                              warning_ratio, test_only, synthetic, payload
                           FROM workflow_c_semantic_metric_snapshots
                          WHERE project_id = %s AND snapshot_hash = %s""",
                (lease.project_id, snapshot.snapshot_hash),
            )
        )
        if not same_semantic_snapshot(
            row,
            lease=lease,
            snapshot=snapshot,
            run_id=run_id,
            source_stratum_hash=source_stratum_hash,
            capture_method=capture_method,
            warning_ratio=warning_ratio,
            test_only=test_only,
            synthetic=synthetic,
            evidence_status=evidence_status,
            payload=payload,
        ):
            raise WorkflowCAnalysisWorkerError("semantic snapshot hash collides with other input")
        for result in snapshot.results:
            result_payload = result.canonical_value()
            existing = mapping_row(
                connection.execute(
                    """SELECT metric_version, status, estimate, interval_json, denominator,
                              valid_count, invalid_count, missing_count, judge_version_hash,
                              rule_versions_hash, evidence_locators_json, payload
                           FROM workflow_c_semantic_metric_results
                          WHERE project_id = %s AND snapshot_hash = %s AND metric_key = %s""",
                    (lease.project_id, snapshot.snapshot_hash, result.metric_key.value),
                )
            )
            if not same_semantic_result(existing, result=result, payload=result_payload):
                raise WorkflowCAnalysisWorkerError("semantic metric result hash collides")
        store.complete_in_transaction(
            connection,
            lease,
            result_ref=f"workflow-c-semantic-metrics:{snapshot.snapshot_hash}",
            details={"snapshot_hash": snapshot.snapshot_hash, "status": evidence_status},
        )


def _semantic_result_row(result: Any) -> dict[str, object]:
    return {
        "metric_key": result.metric_key.value,
        "metric_version": result.metric_version,
        "status": result.status.value,
        "estimate": str(result.estimate) if result.status is MetricStatus.COMPLETE else None,
        "interval_json": result.interval.canonical_value(),
        "denominator": result.denominator,
        "valid_count": result.valid_input_count,
        "invalid_count": result.invalid_input_count,
        "missing_count": result.missing_input_count,
        "judge_version_hash": result.judge_version_hash,
        "rule_versions_hash": result.rule_versions_hash,
        "evidence_locators_json": [item.canonical_value() for item in result.evidence_locators],
        "payload": result.canonical_value(),
    }


def persist_comparison_family(
    store: PostgresDurableJobStore,
    lease: WorkerLease,
    *,
    family: Any,
    comparisons: tuple[ComparisonInput, ...],
    computed_at: Any,
) -> None:
    protocols = tuple(item.protocol for item in comparisons)
    power_plans = {item.power_plan_hash for item in protocols}
    if len(power_plans) != 1:
        raise WorkflowCAnalysisWorkerError(
            "a persisted comparison family needs one frozen power plan"
        )
    protocol_hash = canonical_hash(
        [item.frozen_hash for item in sorted(protocols, key=lambda value: value.comparison_id)]
    )
    status = family_status(family.results)
    payload = family.canonical_value()
    result_rows = tuple(
        _comparison_result_row(
            result,
            source=next(
                item for item in comparisons if item.protocol.comparison_id == result.comparison_id
            ),
        )
        for result in family.results
    )
    with store.fenced_transaction(lease) as connection:
        connection.execute(
            """SELECT geo_persist_workflow_c_comparison_family(
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s::jsonb, %s, %s::jsonb
               )""",
            (
                lease.project_id,
                lease.job_id,
                lease.lease_token,
                lease.fencing_generation,
                family.family_hash,
                protocol_hash,
                next(iter(power_plans)),
                protocols[0].bootstrap_method,
                protocols[0].bootstrap_iterations,
                family.correction_method,
                protocols[0].simultaneous_interval_method,
                status,
                json_value(payload),
                computed_at,
                json_value(result_rows),
            ),
        )
        row = mapping_row(
            connection.execute(
                """SELECT project_id, protocol_hash, power_plan_hash, payload
                       FROM workflow_c_comparison_families
                      WHERE project_id = %s AND family_hash = %s""",
                (lease.project_id, family.family_hash),
            )
        )
        if (
            row is None
            or row.get("project_id") != lease.project_id
            or row.get("protocol_hash") != protocol_hash
            or row.get("power_plan_hash") != next(iter(power_plans))
            or canonical_json(row.get("payload")) != canonical_json(payload)
        ):
            raise WorkflowCAnalysisWorkerError("comparison family hash collides with other input")
        source_by_comparison_id = {item.protocol.comparison_id: item for item in comparisons}
        for result in family.results:
            source = source_by_comparison_id[result.comparison_id]
            result_payload = result.canonical_value()
            existing = mapping_row(
                connection.execute(
                    """SELECT stratum_hash, sampling_source_stratum_hash, conclusion,
                              adjusted_p_value, interval_json, payload
                           FROM workflow_c_comparison_results
                          WHERE project_id = %s AND family_hash = %s AND comparison_id = %s""",
                    (lease.project_id, family.family_hash, result.comparison_id),
                )
            )
            if not same_comparison_result(
                existing, result=result, source=source, payload=result_payload
            ):
                raise WorkflowCAnalysisWorkerError(
                    "comparison result hash collides with other input"
                )
        store.complete_in_transaction(
            connection,
            lease,
            result_ref=f"workflow-c-comparison:{family.family_hash}",
            details={"family_hash": family.family_hash, "status": status},
        )


def persist_drift_report(
    store: PostgresDurableJobStore,
    lease: WorkerLease,
    *,
    report: Any,
    source_snapshot_hash: str,
    target_snapshot_hash: str,
    computed_at: Any,
) -> None:
    payload = report.canonical_value()
    with store.fenced_transaction(lease) as connection:
        protocol_hash = getattr(report, "protocol_hash", None)
        if protocol_hash is None:
            connection.execute(
                """SELECT geo_persist_workflow_c_drift_report(
                       %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s
                   )""",
                (
                    lease.project_id,
                    lease.job_id,
                    lease.lease_token,
                    lease.fencing_generation,
                    report.report_hash,
                    source_snapshot_hash,
                    target_snapshot_hash,
                    json_value(payload),
                    computed_at,
                ),
            )
        else:
            connection.execute(
                """SELECT geo_persist_workflow_c_drift_report_v2(
                       %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s
                   )""",
                (
                    lease.project_id,
                    lease.job_id,
                    lease.lease_token,
                    lease.fencing_generation,
                    report.report_hash,
                    protocol_hash,
                    source_snapshot_hash,
                    target_snapshot_hash,
                    json_value(payload),
                    computed_at,
                ),
            )
        row = mapping_row(
            connection.execute(
                """SELECT project_id, source_snapshot_hash, target_snapshot_hash, payload
                       FROM workflow_c_drift_reports
                      WHERE project_id = %s AND report_hash = %s""",
                (lease.project_id, report.report_hash),
            )
        )
        if (
            row is None
            or row.get("project_id") != lease.project_id
            or row.get("source_snapshot_hash") != source_snapshot_hash
            or row.get("target_snapshot_hash") != target_snapshot_hash
            or canonical_json(row.get("payload")) != canonical_json(payload)
        ):
            raise WorkflowCAnalysisWorkerError("drift report hash collides with other input")
        store.complete_in_transaction(
            connection,
            lease,
            result_ref=f"workflow-c-drift:{report.report_hash}",
            details={"report_hash": report.report_hash, "status": "complete"},
        )


def family_status(results: Sequence[Any]) -> str:
    return (
        "insufficient_evidence"
        if all(item.conclusion.value == "insufficient_evidence" for item in results)
        else "complete"
    )


def _comparison_result_row(result: Any, *, source: ComparisonInput) -> dict[str, object]:
    return {
        "comparison_id": result.comparison_id,
        "stratum_hash": result.stratum_hash,
        "sampling_source_stratum_hash": source.sampling_source_stratum_hash,
        "conclusion": result.conclusion.value,
        "adjusted_p_value": decimal_value(result.adjusted_p_value),
        "interval_json": result.adjusted_interval.canonical_value(),
        "payload": result.canonical_value(),
    }


def same_comparison_result(
    row: Mapping[str, object] | None,
    *,
    result: Any,
    source: ComparisonInput,
    payload: Mapping[str, object],
) -> bool:
    return (
        row is not None
        and row.get("stratum_hash") == result.stratum_hash
        and row.get("sampling_source_stratum_hash") == source.sampling_source_stratum_hash
        and row.get("conclusion") == result.conclusion.value
        and decimal_equal(row.get("adjusted_p_value"), result.adjusted_p_value)
        and canonical_json(row.get("interval_json"))
        == canonical_json(result.adjusted_interval.canonical_value())
        and canonical_json(row.get("payload")) == canonical_json(payload)
    )


def same_semantic_snapshot(
    row: Mapping[str, object] | None,
    *,
    lease: WorkerLease,
    snapshot: Any,
    run_id: UUID,
    source_stratum_hash: str,
    capture_method: str,
    warning_ratio: Decimal,
    test_only: bool,
    synthetic: bool,
    evidence_status: str,
    payload: Mapping[str, object],
) -> bool:
    return (
        row is not None
        and row.get("project_id") == lease.project_id
        and row.get("run_id") == run_id
        and row.get("input_set_hash") == snapshot.input_set_hash
        and row.get("metric_suite_hash") == snapshot.suite_hash
        and row.get("source_stratum_hash") == source_stratum_hash
        and row.get("capture_method") == capture_method
        and row.get("evidence_status") == evidence_status
        and decimal_equal(row.get("warning_ratio"), warning_ratio)
        and row.get("test_only") is test_only
        and row.get("synthetic") is synthetic
        and canonical_json(row.get("payload")) == canonical_json(payload)
    )


def same_semantic_result(
    row: Mapping[str, object] | None, *, result: Any, payload: Mapping[str, object]
) -> bool:
    return (
        row is not None
        and row.get("metric_version") == result.metric_version
        and row.get("status") == result.status.value
        and (
            (result.status is not MetricStatus.COMPLETE and row.get("estimate") is None)
            or decimal_equal(row.get("estimate"), result.estimate)
        )
        and canonical_json(row.get("interval_json"))
        == canonical_json(result.interval.canonical_value())
        and row.get("denominator") == result.denominator
        and row.get("valid_count") == result.valid_input_count
        and row.get("invalid_count") == result.invalid_input_count
        and row.get("missing_count") == result.missing_input_count
        and row.get("judge_version_hash") == result.judge_version_hash
        and row.get("rule_versions_hash") == result.rule_versions_hash
        and canonical_json(row.get("evidence_locators_json"))
        == canonical_json([item.canonical_value() for item in result.evidence_locators])
        and canonical_json(row.get("payload")) == canonical_json(payload)
    )


__all__ = [
    "family_status",
    "persist_comparison_family",
    "persist_drift_report",
    "persist_semantic_snapshot",
]
