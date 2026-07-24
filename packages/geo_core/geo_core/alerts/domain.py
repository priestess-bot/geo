"""Pure alert rules, lifecycle, notification summaries and delivery isolation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from uuid import UUID


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,199}$")
DIMENSION_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class AlertRuleViolation(ValueError):
    """An alert command violates a deterministic domain invariant."""


class AlertConflict(RuntimeError):
    """An alert command conflicts with the current aggregate version or state."""


class AlertNotFound(RuntimeError):
    """The requested project-scoped alert does not exist."""


class AlertRuleKind(StrEnum):
    THRESHOLD = "threshold"
    BASELINE_DELTA = "baseline_delta"
    NEGATIVE_QUESTION = "negative_question"
    COMPLETION_FRESHNESS = "completion_freshness"
    MODEL_DRIFT = "model_drift"
    SOURCE_DRIFT = "source_drift"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    SUPPRESSED = "suppressed"
    RESOLVED = "resolved"


class AlertDispositionKind(StrEnum):
    ACKNOWLEDGED = "acknowledged"
    SUPPRESSED = "suppressed"
    UNSUPPRESSED = "unsuppressed"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class AlertRuleVersion:
    id: UUID
    project_id: UUID
    rule_key: str
    version: int
    kind: AlertRuleKind
    severity: AlertSeverity
    parameters: Mapping[str, object]
    frozen_by: str
    frozen_at: datetime
    rule_hash: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            kind = AlertRuleKind(self.kind)
            severity = AlertSeverity(self.severity)
        except ValueError as error:
            raise AlertRuleViolation("alert rule kind or severity is unsupported") from error
        rule_key = _bounded_key(self.rule_key, "alert rule key")
        actor = _bounded_text(self.frozen_by, "alert rule freezer")
        if self.version < 1:
            raise AlertRuleViolation("alert rule version must be positive")
        _require_aware(self.frozen_at, "alert rule frozen time")
        parameters = _freeze_mapping(self.parameters, "alert rule parameters")
        if not parameters:
            raise AlertRuleViolation("alert rule parameters are required")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "rule_key", rule_key)
        object.__setattr__(self, "frozen_by", actor)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "rule_hash", _canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "project_id": str(self.project_id),
            "rule_key": self.rule_key,
            "version": self.version,
            "kind": self.kind.value,
            "severity": self.severity.value,
            "parameters": _thaw(self.parameters),
        }


@dataclass(frozen=True)
class AlertScope:
    project_id: UUID
    resource_kind: str
    resource_key: str
    dimensions: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        resource_kind = _bounded_key(self.resource_kind, "alert scope resource kind")
        resource_key = _bounded_text(self.resource_key, "alert scope resource key")
        normalized: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw_key, raw_value in self.dimensions:
            key = raw_key.strip().lower()
            value = _bounded_text(raw_value, f"alert scope dimension {key or 'unknown'}")
            if not DIMENSION_KEY_PATTERN.fullmatch(key):
                raise AlertRuleViolation("alert scope dimension key is invalid")
            if key in seen:
                raise AlertRuleViolation("alert scope dimensions must be unique")
            seen.add(key)
            normalized.append((key, value))
        object.__setattr__(self, "resource_kind", resource_kind)
        object.__setattr__(self, "resource_key", resource_key)
        object.__setattr__(self, "dimensions", tuple(sorted(normalized)))

    def canonical_value(self) -> dict[str, object]:
        return {
            "project_id": str(self.project_id),
            "resource_kind": self.resource_kind,
            "resource_key": self.resource_key,
            "dimensions": dict(self.dimensions),
        }


@dataclass(frozen=True, order=True)
class AlertEvidenceReference:
    kind: str
    resource_id: str
    version: str
    sha256: str
    locator: str | None = None

    def __post_init__(self) -> None:
        kind = _bounded_key(self.kind, "alert evidence kind")
        resource_id = _bounded_text(self.resource_id, "alert evidence resource id")
        version = _bounded_text(self.version, "alert evidence version")
        if not SHA256_PATTERN.fullmatch(self.sha256):
            raise AlertRuleViolation("alert evidence hash must be lowercase SHA-256")
        locator = _optional_bounded_text(self.locator, "alert evidence locator", maximum=1000)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "resource_id", resource_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "locator", locator)

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "resource_id": self.resource_id,
            "version": self.version,
            "sha256": self.sha256,
            "locator": self.locator,
        }


@dataclass(frozen=True)
class AlertTriggerSnapshot:
    values: Mapping[str, object]
    captured_at: datetime
    snapshot_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_aware(self.captured_at, "alert trigger capture time")
        values = _freeze_mapping(self.values, "alert trigger snapshot")
        if not values:
            raise AlertRuleViolation("alert trigger snapshot is required")
        object.__setattr__(self, "values", values)
        object.__setattr__(
            self,
            "snapshot_hash",
            _canonical_hash(
                {
                    "captured_at": self.captured_at.isoformat(),
                    "values": _thaw(values),
                }
            ),
        )


@dataclass(frozen=True)
class AlertDisposition:
    disposition: AlertDispositionKind
    from_status: AlertStatus
    to_status: AlertStatus
    actor_id: str
    occurred_at: datetime
    reason: str
    command_key: str
    resulting_version: int
    suppressed_until: datetime | None = None
    command_hash: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            disposition = AlertDispositionKind(self.disposition)
            from_status = AlertStatus(self.from_status)
            to_status = AlertStatus(self.to_status)
        except ValueError as error:
            raise AlertRuleViolation("alert disposition or status is unsupported") from error
        actor = _bounded_text(self.actor_id, "alert disposition actor")
        reason = _bounded_text(self.reason, "alert disposition reason", maximum=1000)
        command_key = _bounded_key(self.command_key, "alert disposition command key")
        _require_aware(self.occurred_at, "alert disposition time")
        if self.resulting_version < 2:
            raise AlertRuleViolation("alert disposition version must follow initial state")
        if disposition is AlertDispositionKind.SUPPRESSED:
            if self.suppressed_until is None:
                raise AlertRuleViolation("suppression disposition requires an expiry")
            _require_aware(self.suppressed_until, "alert suppression expiry")
            if self.suppressed_until <= self.occurred_at:
                raise AlertRuleViolation("alert suppression expiry must follow disposition time")
        elif self.suppressed_until is not None:
            raise AlertRuleViolation("only a suppression disposition can retain an expiry")
        allowed_transition = {
            AlertDispositionKind.ACKNOWLEDGED: (
                frozenset({AlertStatus.OPEN}),
                AlertStatus.ACKNOWLEDGED,
            ),
            AlertDispositionKind.SUPPRESSED: (
                frozenset({AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED}),
                AlertStatus.SUPPRESSED,
            ),
            AlertDispositionKind.UNSUPPRESSED: (
                frozenset({AlertStatus.SUPPRESSED}),
                AlertStatus.OPEN,
            ),
            AlertDispositionKind.RESOLVED: (
                frozenset(
                    {AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED, AlertStatus.SUPPRESSED}
                ),
                AlertStatus.RESOLVED,
            ),
        }[disposition]
        if from_status not in allowed_transition[0] or to_status is not allowed_transition[1]:
            raise AlertRuleViolation("alert disposition transition is invalid")
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "from_status", from_status)
        object.__setattr__(self, "to_status", to_status)
        object.__setattr__(self, "actor_id", actor)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "command_key", command_key)
        object.__setattr__(
            self,
            "command_hash",
            _disposition_command_hash(
                disposition=disposition,
                actor_id=actor,
                reason=reason,
                suppressed_until=self.suppressed_until,
            ),
        )


@dataclass(frozen=True)
class Alert:
    id: UUID
    project_id: UUID
    rule_version: AlertRuleVersion
    scope: AlertScope
    trigger_snapshot: AlertTriggerSnapshot
    evidence: tuple[AlertEvidenceReference, ...]
    severity: AlertSeverity
    dedupe_key: str
    status: AlertStatus
    opened_at: datetime
    updated_at: datetime
    version: int = 1
    dispositions: tuple[AlertDisposition, ...] = ()
    suppressed_until: datetime | None = None
    suppression_reason: str | None = None

    def __post_init__(self) -> None:
        try:
            severity = AlertSeverity(self.severity)
            status = AlertStatus(self.status)
        except ValueError as error:
            raise AlertRuleViolation("alert severity or status is unsupported") from error
        if self.project_id != self.rule_version.project_id or self.project_id != self.scope.project_id:
            raise AlertRuleViolation("alert rule and scope must belong to the alert project")
        if severity is not self.rule_version.severity:
            raise AlertRuleViolation("alert severity must match its frozen rule version")
        if self.dedupe_key != alert_dedupe_key(self.rule_version, self.scope):
            raise AlertRuleViolation("alert dedupe key does not match rule and scope")
        _require_aware(self.opened_at, "alert opened time")
        _require_aware(self.updated_at, "alert updated time")
        if self.updated_at < self.opened_at or self.version < 1:
            raise AlertRuleViolation("alert time or version is inconsistent")
        evidence_set = set(self.evidence)
        evidence = tuple(
            sorted(
                evidence_set,
                key=lambda item: (
                    item.kind,
                    item.resource_id,
                    item.version,
                    item.sha256,
                    item.locator or "",
                ),
            )
        )
        if not evidence:
            raise AlertRuleViolation("alert requires at least one evidence reference")
        if len(evidence) != len(self.evidence):
            raise AlertRuleViolation("alert evidence references must be unique")
        if len(self.dispositions) != self.version - 1:
            raise AlertRuleViolation("alert disposition history does not match version")
        previous_status = AlertStatus.OPEN
        previous_time = self.opened_at
        seen_commands: set[str] = set()
        for index, disposition in enumerate(self.dispositions, start=2):
            if disposition.resulting_version != index:
                raise AlertRuleViolation("alert disposition versions must be contiguous")
            if disposition.from_status is not previous_status:
                raise AlertRuleViolation("alert disposition statuses must be contiguous")
            if disposition.occurred_at < previous_time:
                raise AlertRuleViolation("alert dispositions must be time ordered")
            if disposition.command_key in seen_commands:
                raise AlertRuleViolation("alert disposition command keys must be unique")
            seen_commands.add(disposition.command_key)
            previous_status = disposition.to_status
            previous_time = disposition.occurred_at
        if self.dispositions:
            if previous_status is not status or previous_time != self.updated_at:
                raise AlertRuleViolation("alert current state does not match disposition history")
        elif status is not AlertStatus.OPEN or self.updated_at != self.opened_at:
            raise AlertRuleViolation("an initial alert must be open at its opened time")
        if status is AlertStatus.SUPPRESSED:
            reason = _optional_bounded_text(
                self.suppression_reason, "alert suppression reason", maximum=1000
            )
            if self.suppressed_until is None or reason is None:
                raise AlertRuleViolation("a suppressed alert requires expiry and reason")
            _require_aware(self.suppressed_until, "alert suppression expiry")
            last = self.dispositions[-1]
            if (
                last.disposition is not AlertDispositionKind.SUPPRESSED
                or last.suppressed_until != self.suppressed_until
                or last.reason != reason
            ):
                raise AlertRuleViolation("alert suppression does not match its disposition")
            object.__setattr__(self, "suppression_reason", reason)
        elif self.suppressed_until is not None or self.suppression_reason is not None:
            raise AlertRuleViolation("a non-suppressed alert cannot retain suppression fields")
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "evidence", evidence)


def alert_dedupe_key(rule_version: AlertRuleVersion, scope: AlertScope) -> str:
    if rule_version.project_id != scope.project_id:
        raise AlertRuleViolation("alert rule and scope must belong to one project")
    digest = _canonical_hash(
        {
            "project_id": str(scope.project_id),
            "rule_key": rule_version.rule_key,
            "rule_version": rule_version.version,
            "rule_hash": rule_version.rule_hash,
            "scope": scope.canonical_value(),
        }
    )
    return f"alert:{digest}"


def _disposition_command_hash(
    *,
    disposition: AlertDispositionKind,
    actor_id: str,
    reason: str,
    suppressed_until: datetime | None,
) -> str:
    return _canonical_hash(
        {
            "disposition": disposition.value,
            "actor_id": actor_id,
            "reason": reason,
            "suppressed_until": (
                suppressed_until.isoformat() if suppressed_until is not None else None
            ),
        }
    )


def _freeze_mapping(values: Mapping[str, object], label: str) -> Mapping[str, object]:
    normalized: dict[str, object] = {}
    for raw_key, raw_value in values.items():
        key = raw_key.strip()
        if not key or len(key) > 100:
            raise AlertRuleViolation(f"{label} contains an invalid key")
        if key in normalized:
            raise AlertRuleViolation(f"{label} contains duplicate keys")
        normalized[key] = _freeze_value(raw_value, label)
    return MappingProxyType(dict(sorted(normalized.items())))


def _freeze_value(value: object, label: str) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value, label)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_value(item, label) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal) and value.is_finite():
        return _canonical_decimal(value)
    raise AlertRuleViolation(f"{label} must contain deterministic JSON-compatible values")


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _bounded_key(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if not KEY_PATTERN.fullmatch(normalized):
        raise AlertRuleViolation(f"{label} is invalid")
    return normalized


def _bounded_text(value: str, label: str, *, maximum: int = 200) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise AlertRuleViolation(f"{label} is required and must be at most {maximum} characters")
    return normalized


def _optional_bounded_text(
    value: str | None, label: str, *, maximum: int
) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, label, maximum=maximum)


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AlertRuleViolation(f"{label} must be timezone-aware")
