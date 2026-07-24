"""Frozen-value parsing and canonical serialization for alert Worker commands."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import hashlib
import json
from uuid import UUID, uuid5

from geo_core.alerts.domain import (
    AlertEvidenceReference,
    AlertRuleKind,
    AlertRuleVersion,
    AlertScope,
    AlertSeverity,
)
from geo_core.alerts.notifications import NotificationChannel
from geo_core.workflow_c_job_specs import WorkflowCJobSpecError


ALERT_OPERATION_NAMESPACE = UUID("dd81a2cc-7bb3-5bea-a809-5389a2833216")


def parse_rule(raw: object, project_id: UUID) -> AlertRuleVersion:
    values = exact_mapping(
        raw,
        {
            "id",
            "rule_key",
            "version",
            "kind",
            "severity",
            "parameters",
            "frozen_by",
            "frozen_at",
            "rule_hash",
        },
        "alert rule",
    )
    parameters = values["parameters"]
    if not isinstance(parameters, Mapping) or not parameters:
        raise WorkflowCJobSpecError("alert rule parameters must be a non-empty object")
    try:
        result = AlertRuleVersion(
            id=uuid_value(values, "id", "alert rule id"),
            project_id=project_id,
            rule_key=text_value(values, "rule_key", "alert rule key"),
            version=positive_int(values, "version", "alert rule version"),
            kind=AlertRuleKind(text_value(values, "kind", "alert rule kind")),
            severity=AlertSeverity(text_value(values, "severity", "alert severity")),
            parameters=json_mapping(parameters, "alert rule parameters"),
            frozen_by=text_value(values, "frozen_by", "alert rule freezer"),
            frozen_at=timestamp_value(values, "frozen_at", "alert rule frozen time"),
        )
    except ValueError as error:
        raise WorkflowCJobSpecError("alert rule is invalid") from error
    expected_hash = text_value(values, "rule_hash", "alert rule hash")
    if result.rule_hash != expected_hash:
        raise WorkflowCJobSpecError("alert rule hash changed")
    return result


def rule_value(rule: AlertRuleVersion) -> dict[str, object]:
    return {
        "id": str(rule.id),
        "rule_key": rule.rule_key,
        "version": rule.version,
        "kind": rule.kind.value,
        "severity": rule.severity.value,
        "parameters": json_value(rule.parameters),
        "frozen_by": rule.frozen_by,
        "frozen_at": rule.frozen_at.isoformat(),
        "rule_hash": rule.rule_hash,
    }


def parse_scope(raw: object, project_id: UUID) -> AlertScope:
    values = exact_mapping(
        raw,
        {"project_id", "resource_kind", "resource_key", "dimensions"},
        "alert scope",
    )
    if uuid_value(values, "project_id", "alert scope project") != project_id:
        raise WorkflowCJobSpecError("alert scope project differs from durable Job")
    dimensions = values["dimensions"]
    if not isinstance(dimensions, Mapping):
        raise WorkflowCJobSpecError("alert scope dimensions must be an object")
    dimension_items: list[tuple[str, str]] = []
    for key, value in dimensions.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise WorkflowCJobSpecError("alert scope dimensions must be text")
        dimension_items.append((key, value))
    try:
        return AlertScope(
            project_id=project_id,
            resource_kind=text_value(values, "resource_kind", "alert scope resource kind"),
            resource_key=text_value(values, "resource_key", "alert scope resource key"),
            dimensions=tuple(dimension_items),
        )
    except ValueError as error:
        raise WorkflowCJobSpecError("alert scope is invalid") from error


def parse_evidence(raw: object) -> tuple[AlertEvidenceReference, ...]:
    if not isinstance(raw, list) or not raw:
        raise WorkflowCJobSpecError("alert evidence must be a non-empty array")
    items: list[AlertEvidenceReference] = []
    for value in raw:
        values = exact_mapping(
            value,
            {"kind", "resource_id", "version", "sha256", "locator"},
            "alert evidence item",
        )
        try:
            items.append(
                AlertEvidenceReference(
                    kind=text_value(values, "kind", "alert evidence kind"),
                    resource_id=text_value(values, "resource_id", "alert evidence resource"),
                    version=text_value(values, "version", "alert evidence version"),
                    sha256=text_value(values, "sha256", "alert evidence hash"),
                    locator=optional_text(values, "locator", "alert evidence locator"),
                )
            )
        except ValueError as error:
            raise WorkflowCJobSpecError("alert evidence is invalid") from error
    if len(set(items)) != len(items):
        raise WorkflowCJobSpecError("alert evidence items must be unique")
    return tuple(sorted(items))


def parse_channels(raw: object) -> tuple[NotificationChannel, ...]:
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        raise WorkflowCJobSpecError("alert notification channels must be a non-empty text array")
    try:
        values = tuple(sorted({NotificationChannel(item) for item in raw}, key=str))
    except ValueError as error:
        raise WorkflowCJobSpecError("alert notification channel is invalid") from error
    if len(values) != len(raw):
        raise WorkflowCJobSpecError("alert notification channels must be unique")
    return values


def exact_mapping(raw: object, keys: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(raw, Mapping) or set(raw) != keys:
        raise WorkflowCJobSpecError(f"{label} has an unexpected schema")
    if not all(isinstance(key, str) for key in raw):
        raise WorkflowCJobSpecError(f"{label} keys must be text")
    return raw


def json_mapping(raw: Mapping[object, object], label: str) -> Mapping[str, object]:
    value = json_value(raw)
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise WorkflowCJobSpecError(f"{label} must contain text keys")
    try:
        json.dumps(value, allow_nan=False, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise WorkflowCJobSpecError(f"{label} must be canonical JSON") from error
    return value


def json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [json_value(item) for item in value]
    if isinstance(value, list):
        return [json_value(item) for item in value]
    return value


def json_text(value: object) -> str:
    return json.dumps(json_value(value), allow_nan=False, separators=(",", ":"), sort_keys=True)


def canonical_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def deterministic_id(project_id: UUID, purpose: str, value: str) -> UUID:
    return uuid5(ALERT_OPERATION_NAMESPACE, f"{project_id}:{purpose}:{value}")


def uuid_value(values: Mapping[str, object], key: str, label: str) -> UUID:
    raw = values.get(key)
    if not isinstance(raw, str):
        raise WorkflowCJobSpecError(f"{label} must be a UUID")
    try:
        return UUID(raw)
    except ValueError as error:
        raise WorkflowCJobSpecError(f"{label} must be a UUID") from error


def positive_int(values: Mapping[str, object], key: str, label: str) -> int:
    raw = values.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        raise WorkflowCJobSpecError(f"{label} must be a positive integer")
    return raw


def timestamp_value(values: Mapping[str, object], key: str, label: str) -> datetime:
    raw = values.get(key)
    if not isinstance(raw, str):
        raise WorkflowCJobSpecError(f"{label} must be an ISO timestamp")
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as error:
        raise WorkflowCJobSpecError(f"{label} must be an ISO timestamp") from error
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowCJobSpecError(f"{label} must be timezone-aware")
    return value


def text_value(values: Mapping[str, object], key: str, label: str) -> str:
    raw = values.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise WorkflowCJobSpecError(f"{label} must be non-empty text")
    return raw


def optional_text(values: Mapping[str, object], key: str, label: str) -> str | None:
    raw = values.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise WorkflowCJobSpecError(f"{label} must be text or null")
    return raw


__all__ = [
    "ALERT_OPERATION_NAMESPACE",
    "canonical_hash",
    "deterministic_id",
    "exact_mapping",
    "json_mapping",
    "json_text",
    "json_value",
    "parse_channels",
    "parse_evidence",
    "parse_rule",
    "parse_scope",
    "positive_int",
    "rule_value",
    "timestamp_value",
    "uuid_value",
]
