"""Frozen-output resolution for Workflow C alert admission."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import hashlib
import json
from typing import Any
from uuid import UUID

from geo_core.alerts import AlertEvidenceReference, AlertRuleKind, AlertScope
from geo_core.workflow_c_alert_admission_contracts import (
    AlertEvaluationSelector,
    WorkflowCAlertAdmissionError,
    _ResolvedAlertInput,
)


def _semantic_source(connection: Any, project_id: UUID, source_hash: str) -> Mapping[str, object]:
    row = _required_row(
        connection.execute(
            """SELECT snapshot_hash, metric_suite_hash, source_stratum_hash,
                      computed_at, payload
                 FROM workflow_c_semantic_metric_snapshots
                WHERE project_id = %s AND snapshot_hash = %s""",
            (project_id, source_hash),
        ).fetchone(),
        "semantic metric snapshot",
    )
    payload = _payload(row)
    canonical = {key: value for key, value in payload.items() if key != "computed_at"}
    if _canonical_hash(canonical) != source_hash:
        raise WorkflowCAlertAdmissionError("semantic snapshot content hash is invalid")
    return row


def _comparison_source(connection: Any, project_id: UUID, source_hash: str) -> Mapping[str, object]:
    row = _required_row(
        connection.execute(
            """SELECT family_hash, payload FROM workflow_c_comparison_families
                WHERE project_id = %s AND family_hash = %s""",
            (project_id, source_hash),
        ).fetchone(),
        "comparison family",
    )
    if _canonical_hash(_payload(row)) != source_hash:
        raise WorkflowCAlertAdmissionError("comparison family content hash is invalid")
    return row


def _drift_source(connection: Any, project_id: UUID, source_hash: str) -> Mapping[str, object]:
    row = _required_row(
        connection.execute(
            """SELECT report_hash, payload FROM workflow_c_drift_reports
                WHERE project_id = %s AND report_hash = %s""",
            (project_id, source_hash),
        ).fetchone(),
        "drift report",
    )
    if _canonical_hash(_payload(row)) != source_hash:
        raise WorkflowCAlertAdmissionError("drift report content hash is invalid")
    return row


def _external_health_source(
    connection: Any, project_id: UUID, source_hash: str
) -> Mapping[str, object]:
    return _required_row(
        connection.execute(
            """SELECT source_kind, source_id, source_version, signal_kind,
                      severity, reason_code, action_path, payload, input_hash,
                      observed_at
                 FROM external_operational_alert_inputs
                WHERE project_id = %s AND input_hash = %s""",
            (project_id, source_hash),
        ).fetchone(),
        "external operational alert input",
    )


def _external_health_input(
    source: Mapping[str, object], *, selector: AlertEvaluationSelector, project_id: UUID
) -> _ResolvedAlertInput:
    _forbid_extra_selector(selector, baseline=False, item=False)
    source_hash = _field(source, "input_hash", str)
    if source_hash != selector.source_hash:
        raise WorkflowCAlertAdmissionError("external health input hash changed")
    source_kind = _field(source, "source_kind", str)
    source_id = str(_required(source, "source_id"))
    signal_kind = _field(source, "signal_kind", str)
    return _resolved(
        project_id=project_id,
        resource_kind="external_operational_alert_input",
        resource_key=f"{source_kind}:{source_id}:{signal_kind}",
        source_hash=source_hash,
        dimensions=(("source_kind", source_kind), ("signal_kind", signal_kind)),
        values={
            "schema_version": "alert-input-external-health-v1",
            "source_kind": source_kind,
            "source_id": source_id,
            "source_version": _field(source, "source_version", int),
            "signal_kind": signal_kind,
            "severity": _field(source, "severity", str),
            "reason_code": _field(source, "reason_code", str),
            "action_path": _field(source, "action_path", str),
            "payload": _mapping(_required(source, "payload"), "external health payload"),
            "observed_at": _field(source, "observed_at", datetime).isoformat(),
        },
        evidence=(("external_operational_alert_input", source_hash, "payload"),),
    )


def _threshold_input(
    source: Mapping[str, object],
    *,
    parameters: Mapping[str, object],
    selector: AlertEvaluationSelector,
    project_id: UUID,
) -> _ResolvedAlertInput:
    _forbid_extra_selector(selector, baseline=False, item=False)
    metric_key = _parameter_text(parameters, "metric_key")
    result = _semantic_result(source, metric_key)
    _require_complete(result)
    return _resolved(
        project_id=project_id,
        resource_kind="semantic_metric_snapshot",
        source_hash=selector.source_hash,
        dimensions=(("metric_key", metric_key),),
        values={
            "schema_version": "alert-input-threshold-v1",
            "metric_key": metric_key,
            "observed_value": _field(result, "estimate", str),
        },
        evidence=(("semantic_metric_snapshot", selector.source_hash, f"results[{metric_key}]"),),
    )


def _completion_input(
    source: Mapping[str, object],
    *,
    selector: AlertEvaluationSelector,
    project_id: UUID,
) -> _ResolvedAlertInput:
    if selector.baseline_source_hash is not None or selector.source_item_key is None:
        raise WorkflowCAlertAdmissionError(
            "completion/freshness requires one metric-key locator and no baseline"
        )
    metric_key = selector.source_item_key
    result = _semantic_result(source, metric_key)
    computed_at = _field(_payload(source), "computed_at", str)
    return _resolved(
        project_id=project_id,
        resource_kind="semantic_metric_snapshot",
        source_hash=selector.source_hash,
        dimensions=(("metric_key", metric_key),),
        values={
            "schema_version": "alert-input-completion-freshness-v1",
            "planned_count": _field(result, "denominator", int),
            "valid_count": _field(result, "valid_input_count", int),
            "invalid_count": _field(result, "invalid_input_count", int),
            "missing_count": _field(result, "missing_input_count", int),
            "snapshot_captured_at": computed_at,
        },
        evidence=(("semantic_metric_snapshot", selector.source_hash, f"results[{metric_key}]"),),
    )


def _baseline_input(
    baseline: Mapping[str, object],
    current: Mapping[str, object],
    *,
    parameters: Mapping[str, object],
    selector: AlertEvaluationSelector,
    project_id: UUID,
) -> _ResolvedAlertInput:
    if selector.source_item_key is not None:
        raise WorkflowCAlertAdmissionError("baseline delta metric is frozen in the rule")
    if (
        baseline.get("metric_suite_hash") != current.get("metric_suite_hash")
        or baseline.get("source_stratum_hash") != current.get("source_stratum_hash")
    ):
        raise WorkflowCAlertAdmissionError("baseline delta snapshots mix metric or source strata")
    metric_key = _parameter_text(parameters, "metric_key")
    baseline_result = _semantic_result(baseline, metric_key)
    current_result = _semantic_result(current, metric_key)
    _require_complete(baseline_result)
    _require_complete(current_result)
    return _resolved(
        project_id=project_id,
        resource_kind="semantic_metric_delta",
        source_hash=selector.source_hash,
        resource_key=f"{selector.baseline_source_hash}:{selector.source_hash}",
        dimensions=(("metric_key", metric_key),),
        values={
            "schema_version": "alert-input-baseline-delta-v1",
            "metric_key": metric_key,
            "baseline_value": _field(baseline_result, "estimate", str),
            "current_value": _field(current_result, "estimate", str),
        },
        evidence=(
            ("semantic_metric_snapshot", str(selector.baseline_source_hash), f"results[{metric_key}]"),
            ("semantic_metric_snapshot", selector.source_hash, f"results[{metric_key}]"),
        ),
    )


def _negative_question_input(
    source: Mapping[str, object],
    *,
    parameters: Mapping[str, object],
    selector: AlertEvaluationSelector,
    project_id: UUID,
) -> _ResolvedAlertInput:
    if selector.baseline_source_hash is not None or selector.source_item_key is None:
        raise WorkflowCAlertAdmissionError(
            "negative-question alert requires one comparison locator and no baseline"
        )
    result = _array_item(_payload(source), "results", "comparison_id", selector.source_item_key)
    interval = _mapping(_required(result, "adjusted_interval"), "adjusted interval")
    metric_key = _parameter_text(parameters, "metric_key")
    return _resolved(
        project_id=project_id,
        resource_kind="comparison_family",
        source_hash=selector.source_hash,
        dimensions=(("comparison_id", selector.source_item_key),),
        values={
            "schema_version": "alert-input-negative-question-v1",
            "metric_key": metric_key,
            "question_id": selector.source_item_key,
            "delta": _field(result, "point_estimate", str),
            "interval_low": _field(interval, "low", str),
            "interval_high": _field(interval, "high", str),
        },
        evidence=(("comparison_family", selector.source_hash, f"results[{selector.source_item_key}]"),),
    )


def _drift_input(
    source: Mapping[str, object],
    *,
    kind: AlertRuleKind,
    selector: AlertEvaluationSelector,
    project_id: UUID,
) -> _ResolvedAlertInput:
    if selector.baseline_source_hash is not None or selector.source_item_key is None:
        raise WorkflowCAlertAdmissionError("drift alert requires one cohort locator and no baseline")
    payload = _payload(source)
    if kind is AlertRuleKind.MODEL_DRIFT:
        collection, baseline_key, current_key, schema = (
            "model_drift",
            "baseline_models",
            "current_models",
            "alert-input-model-drift-v1",
        )
    elif kind is AlertRuleKind.SOURCE_DRIFT:
        collection, baseline_key, current_key, schema = (
            "source_drift",
            "baseline_compositions",
            "current_compositions",
            "alert-input-source-drift-v1",
        )
    else:
        raise WorkflowCAlertAdmissionError("alert rule kind has no frozen-output resolver")
    values = _array(payload, collection)
    matching = [
        item
        for item in values
        if _canonical_hash(_mapping(_required(item, "cohort"), "drift cohort"))
        == selector.source_item_key
    ]
    if len(matching) != 1:
        raise WorkflowCAlertAdmissionError("drift cohort locator does not identify one signal")
    signal = matching[0]
    baseline_values = _string_array(signal, baseline_key)
    current_values = _string_array(signal, current_key)
    input_baseline = (
        "baseline_composition_hashes" if kind is AlertRuleKind.SOURCE_DRIFT else baseline_key
    )
    input_current = (
        "current_composition_hashes" if kind is AlertRuleKind.SOURCE_DRIFT else current_key
    )
    return _resolved(
        project_id=project_id,
        resource_kind="drift_report",
        source_hash=selector.source_hash,
        dimensions=(("cohort_hash", selector.source_item_key),),
        values={
            "schema_version": schema,
            "stratum_hash": selector.source_item_key,
            input_baseline: baseline_values,
            input_current: current_values,
        },
        evidence=(("drift_report", selector.source_hash, f"{collection}[{selector.source_item_key}]"),),
    )


def _resolved(
    *,
    project_id: UUID,
    resource_kind: str,
    source_hash: str,
    values: Mapping[str, object],
    evidence: Sequence[tuple[str, str, str]],
    dimensions: tuple[tuple[str, str], ...] = (),
    resource_key: str | None = None,
) -> _ResolvedAlertInput:
    return _ResolvedAlertInput(
        values=values,
        scope=AlertScope(
            project_id=project_id,
            resource_kind=resource_kind,
            resource_key=resource_key or source_hash,
            dimensions=dimensions,
        ),
        evidence=tuple(
            AlertEvidenceReference(
                kind=kind,
                resource_id=digest,
                version="workflow-c-frozen-output-v1",
                sha256=digest,
                locator=locator,
            )
            for kind, digest, locator in evidence
        ),
    )


def _semantic_result(source: Mapping[str, object], metric_key: str) -> Mapping[str, object]:
    return _array_item(_payload(source), "results", "metric_key", metric_key)


def _require_complete(result: Mapping[str, object]) -> None:
    if result.get("status") != "complete":
        raise WorkflowCAlertAdmissionError("insufficient metric evidence cannot drive this alert")


def _forbid_extra_selector(
    selector: AlertEvaluationSelector, *, baseline: bool, item: bool
) -> None:
    if (selector.baseline_source_hash is not None) is not baseline or (
        selector.source_item_key is not None
    ) is not item:
        raise WorkflowCAlertAdmissionError("alert selector contains fields not used by its rule")


def _payload(row: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(row.get("payload"), "frozen output payload")


def _array_item(
    payload: Mapping[str, object], collection: str, key: str, expected: str
) -> Mapping[str, object]:
    matches = [item for item in _array(payload, collection) if item.get(key) == expected]
    if len(matches) != 1:
        raise WorkflowCAlertAdmissionError(f"{collection} selector does not identify one item")
    return matches[0]


def _array(payload: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise WorkflowCAlertAdmissionError(f"frozen output {key} is malformed")
    return tuple(_mapping(item, f"{key} item") for item in value)


def _string_array(row: Mapping[str, object], key: str) -> list[str]:
    value = row.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise WorkflowCAlertAdmissionError(f"drift {key} is malformed")
    return value


def _parameter_text(parameters: Mapping[str, object], key: str) -> str:
    return _field(parameters, key, str)


def _required(row: Mapping[str, object], key: str) -> object:
    if key not in row:
        raise WorkflowCAlertAdmissionError(f"frozen output {key} is missing")
    return row[key]


def _field(row: Mapping[str, object], key: str, expected: type[Any]) -> Any:
    value = _required(row, key)
    if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
        raise WorkflowCAlertAdmissionError(f"frozen output {key} is malformed")
    return value


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise WorkflowCAlertAdmissionError(f"{label} is malformed")
    return dict(value)


def _row(value: object) -> Mapping[str, object] | None:
    return None if value is None else _mapping(value, "database row")


def _required_row(value: object, label: str) -> Mapping[str, object]:
    row = _row(value)
    if row is None:
        raise WorkflowCAlertAdmissionError(f"{label} does not exist")
    return row


def _text(value: object, label: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise WorkflowCAlertAdmissionError(f"{label} is invalid")
    return value.strip()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
