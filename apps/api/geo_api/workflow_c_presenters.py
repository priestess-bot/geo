"""Semantic, statistical and alert domain-to-transport projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from geo_api.workflow_c_alert_contracts import (
    AlertCommandResponse,
    AlertDispositionResponse,
    AlertEvidenceContract,
    AlertPageResponse,
    AlertResponse,
    AlertRuleContract,
    AlertScopeContract,
    NotificationProjectionResponse,
)
from geo_api.workflow_c_analysis_contracts import (
    ComparisonFamilyPageResponse,
    ComparisonFamilyResponse,
    ComparisonResultResponse,
    DriftReportPageResponse,
    DriftReportResponse,
    PerformanceResponse,
    SemanticMetricResultResponse,
    SemanticMetricSnapshotPageResponse,
    SemanticMetricSnapshotResponse,
)
from geo_core.alerts import Alert, AlertCommandResult, NotificationOutboxCommand
from geo_core.semantic_metrics import SemanticMetricSnapshot
from geo_core.statistical_methods import ComparisonFamilyResult, DriftReport


def semantic_snapshot_response(
    project_id: UUID, snapshot: SemanticMetricSnapshot
) -> SemanticMetricSnapshotResponse:
    result_values = []
    for result in snapshot.results:
        value = result.canonical_value()
        value["result_hash"] = result.result_hash
        result_values.append(SemanticMetricResultResponse.model_validate(value))
    performance = snapshot.result_value()["performance"]
    return SemanticMetricSnapshotResponse(
        project_id=project_id,
        input_set_hash=snapshot.input_set_hash,
        suite_hash=snapshot.suite_hash,
        stratum_hash=snapshot.stratum_hash,
        results=result_values,
        performance=PerformanceResponse.model_validate(performance),
        computed_at=snapshot.computed_at,
        snapshot_hash=snapshot.snapshot_hash,
    )


def semantic_snapshot_page_response(
    project_id: UUID, items: tuple[SemanticMetricSnapshot, ...]
) -> SemanticMetricSnapshotPageResponse:
    return SemanticMetricSnapshotPageResponse(
        items=[semantic_snapshot_response(project_id, item) for item in items],
        total=len(items),
    )


def comparison_family_response(
    project_id: UUID, result: ComparisonFamilyResult
) -> ComparisonFamilyResponse:
    items = []
    for item in result.results:
        value = item.canonical_value()
        value["result_hash"] = item.result_hash
        items.append(ComparisonResultResponse.model_validate(value))
    return ComparisonFamilyResponse(
        project_id=project_id,
        family=result.family,
        alpha=str(result.alpha),
        correction_method=result.correction_method,
        results=items,
        family_hash=result.family_hash,
    )


def comparison_family_page_response(
    project_id: UUID, items: tuple[ComparisonFamilyResult, ...]
) -> ComparisonFamilyPageResponse:
    return ComparisonFamilyPageResponse(
        items=[comparison_family_response(project_id, item) for item in items],
        total=len(items),
    )


def drift_report_response(project_id: UUID, report: DriftReport) -> DriftReportResponse:
    return DriftReportResponse.model_validate(
        {
            "project_id": project_id,
            **report.canonical_value(),
            "report_hash": report.report_hash,
        }
    )


def drift_report_page_response(
    project_id: UUID, items: tuple[DriftReport, ...]
) -> DriftReportPageResponse:
    return DriftReportPageResponse(
        items=[drift_report_response(project_id, item) for item in items],
        total=len(items),
    )


def alert_response(item: Alert, *, replayed: bool = False) -> AlertResponse:
    rule = item.rule_version
    scope = item.scope
    return AlertResponse(
        id=item.id,
        project_id=item.project_id,
        rule=AlertRuleContract(
            id=rule.id,
            rule_key=rule.rule_key,
            version=rule.version,
            kind=rule.kind.value,
            severity=rule.severity.value,
            parameters=_mapping(rule.parameters),
            frozen_by=rule.frozen_by,
            frozen_at=rule.frozen_at,
        ),
        rule_hash=rule.rule_hash,
        scope=AlertScopeContract(
            resource_kind=scope.resource_kind,
            resource_key=scope.resource_key,
            dimensions=dict(scope.dimensions),
        ),
        trigger_values=_mapping(item.trigger_snapshot.values),
        trigger_snapshot_hash=item.trigger_snapshot.snapshot_hash,
        evidence=[
            AlertEvidenceContract(
                kind=evidence.kind,
                resource_id=evidence.resource_id,
                version=evidence.version,
                sha256=evidence.sha256,
                locator=evidence.locator,
            )
            for evidence in item.evidence
        ],
        severity=item.severity.value,
        dedupe_key=item.dedupe_key,
        status=item.status.value,
        opened_at=item.opened_at,
        updated_at=item.updated_at,
        version=item.version,
        dispositions=[
            AlertDispositionResponse(
                disposition=value.disposition.value,
                from_status=value.from_status.value,
                to_status=value.to_status.value,
                actor_id=value.actor_id,
                occurred_at=value.occurred_at,
                reason=value.reason,
                command_key=value.command_key,
                resulting_version=value.resulting_version,
                suppressed_until=value.suppressed_until,
                command_hash=value.command_hash,
            )
            for value in item.dispositions
        ],
        suppressed_until=item.suppressed_until,
        suppression_reason=item.suppression_reason,
        replayed=replayed,
    )


def notification_response(item: NotificationOutboxCommand) -> NotificationProjectionResponse:
    return NotificationProjectionResponse(
        id=item.id,
        project_id=item.project_id,
        alert_id=item.alert_id,
        alert_version=item.alert_version,
        channel=item.channel.value,
        topic=item.topic,
        idempotency_key=item.idempotency_key,
        created_at=item.created_at,
        payload_hash=item.payload_hash,
        summary=item.summary.payload(),
    )


def alert_command_response(result: AlertCommandResult) -> AlertCommandResponse:
    return AlertCommandResponse(
        alert=alert_response(result.alert, replayed=result.replayed),
        notifications=[notification_response(item) for item in result.notification_commands],
        replayed=result.replayed,
    )


def alert_page_response(items: tuple[Alert, ...]) -> AlertPageResponse:
    return AlertPageResponse(
        items=[alert_response(item) for item in items],
        total=len(items),
    )


def _mapping(value: Mapping[str, object]) -> dict[str, Any]:
    return {key: _json_value(item) for key, item in value.items()}


def _json_value(value: object) -> Any:
    if isinstance(value, Mapping):
        return _mapping(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value
