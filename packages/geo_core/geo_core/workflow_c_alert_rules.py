"""Governed Workflow C alert-rule releases and PostgreSQL lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from typing import Any
from uuid import UUID, uuid5

import psycopg
from psycopg.types.json import Jsonb

from geo_core.alerts import AlertRuleKind, AlertRuleVersion, AlertSeverity
from geo_core.project_scope import set_project_scope


ALERT_RULE_NAMESPACE = UUID("b9333829-f3ce-5c2d-a321-dffd3797702a")


class WorkflowCAlertRuleError(ValueError):
    """An alert-rule release or lifecycle command is invalid."""


class WorkflowCAlertRuleNotFound(LookupError):
    """The Project-scoped alert-rule release does not exist."""


class AlertRuleReleaseStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    RETIRED = "retired"


@dataclass(frozen=True)
class AlertRuleRelease:
    rule: AlertRuleVersion
    status: AlertRuleReleaseStatus
    aggregate_version: int
    approved_by: str | None = None
    approved_at: datetime | None = None
    retired_by: str | None = None
    retired_at: datetime | None = None
    decision_reason: str | None = None

    def __post_init__(self) -> None:
        status = AlertRuleReleaseStatus(self.status)
        if self.aggregate_version < 1:
            raise WorkflowCAlertRuleError("alert rule aggregate version is invalid")
        if status is AlertRuleReleaseStatus.DRAFT:
            if any(
                value is not None
                for value in (
                    self.approved_by,
                    self.approved_at,
                    self.retired_by,
                    self.retired_at,
                    self.decision_reason,
                )
            ):
                raise WorkflowCAlertRuleError("draft alert rule has decision state")
        elif status is AlertRuleReleaseStatus.APPROVED:
            if (
                not self.approved_by
                or self.approved_at is None
                or self.approved_by == self.rule.frozen_by
                or not self.decision_reason
                or self.retired_by is not None
                or self.retired_at is not None
            ):
                raise WorkflowCAlertRuleError("approved alert rule state is invalid")
        elif (
            not self.approved_by
            or self.approved_at is None
            or not self.retired_by
            or self.retired_at is None
            or not self.decision_reason
        ):
            raise WorkflowCAlertRuleError("retired alert rule state is invalid")
        for value in (self.rule.frozen_at, self.approved_at, self.retired_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise WorkflowCAlertRuleError("alert rule timestamps must be timezone-aware")
        object.__setattr__(self, "status", status)

    @property
    def id(self) -> UUID:
        return self.rule.id

    @property
    def project_id(self) -> UUID:
        return self.rule.project_id


def new_alert_rule_release(
    *,
    project_id: UUID,
    rule_key: str,
    version: int,
    kind: AlertRuleKind,
    severity: AlertSeverity,
    parameters: Mapping[str, object],
    actor_id: str,
    idempotency_key: str,
    occurred_at: datetime,
) -> AlertRuleRelease:
    key = _text(idempotency_key, "Idempotency-Key", maximum=200)
    rule = AlertRuleVersion(
        id=uuid5(ALERT_RULE_NAMESPACE, f"{project_id}:{key}"),
        project_id=project_id,
        rule_key=rule_key,
        version=version,
        kind=kind,
        severity=severity,
        parameters=parameters,
        frozen_by=actor_id,
        frozen_at=occurred_at,
    )
    return AlertRuleRelease(
        rule=rule,
        status=AlertRuleReleaseStatus.DRAFT,
        aggregate_version=1,
    )


def transition_alert_rule_release(
    release: AlertRuleRelease,
    *,
    target_status: AlertRuleReleaseStatus,
    actor_id: str,
    reason: str,
    occurred_at: datetime,
) -> AlertRuleRelease:
    target = AlertRuleReleaseStatus(target_status)
    actor = _text(actor_id, "alert rule actor")
    decision = _text(reason, "decision reason", maximum=2_000)
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise WorkflowCAlertRuleError("alert rule transition time must be timezone-aware")
    if target is AlertRuleReleaseStatus.APPROVED:
        if release.status is not AlertRuleReleaseStatus.DRAFT:
            raise WorkflowCAlertRuleError("only a draft alert rule can be approved")
        if actor == release.rule.frozen_by:
            raise WorkflowCAlertRuleError("alert rule maker cannot approve the same release")
        return replace(
            release,
            status=target,
            aggregate_version=release.aggregate_version + 1,
            approved_by=actor,
            approved_at=occurred_at,
            decision_reason=decision,
        )
    if target is AlertRuleReleaseStatus.RETIRED:
        if release.status is not AlertRuleReleaseStatus.APPROVED:
            raise WorkflowCAlertRuleError("only an approved alert rule can be retired")
        return replace(
            release,
            status=target,
            aggregate_version=release.aggregate_version + 1,
            retired_by=actor,
            retired_at=occurred_at,
            decision_reason=decision,
        )
    raise WorkflowCAlertRuleError("alert rule transition target is invalid")


class PostgresWorkflowCAlertRuleRepository:
    """Persist rule releases through scoped, idempotent database commands."""

    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._clock = clock

    def create(
        self,
        *,
        project_id: UUID,
        rule_key: str,
        version: int,
        kind: AlertRuleKind,
        severity: AlertSeverity,
        parameters: Mapping[str, object],
        actor_id: str,
        idempotency_key: str,
    ) -> AlertRuleRelease:
        release = new_alert_rule_release(
            project_id=project_id,
            rule_key=rule_key,
            version=version,
            kind=kind,
            severity=severity,
            parameters=parameters,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            occurred_at=self._clock(),
        )
        payload = _rule_payload(release.rule)
        input_hash = _canonical_hash(
            {
                "rule_id": str(release.id),
                "rule_key": release.rule.rule_key,
                "version": release.rule.version,
                "rule_hash": release.rule.rule_hash,
                "payload": payload,
                "actor_id": release.rule.frozen_by,
            }
        )
        return self._command(
            project_id=project_id,
            statement="""SELECT * FROM geo_create_workflow_c_alert_rule(
                             %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s
                         )""",
            parameters=(
                project_id,
                release.id,
                release.rule.rule_key,
                release.rule.version,
                release.rule.rule_hash,
                Jsonb(payload),
                release.rule.frozen_by,
                _digest(idempotency_key),
                input_hash,
                release.rule.frozen_at,
            ),
        )

    def transition(
        self,
        *,
        project_id: UUID,
        rule_id: UUID,
        expected_aggregate_version: int,
        target_status: AlertRuleReleaseStatus,
        actor_id: str,
        reason: str,
        idempotency_key: str,
    ) -> AlertRuleRelease:
        target = AlertRuleReleaseStatus(target_status)
        if target not in {AlertRuleReleaseStatus.APPROVED, AlertRuleReleaseStatus.RETIRED}:
            raise WorkflowCAlertRuleError("alert rule transition target is invalid")
        actor = _text(actor_id, "actor")
        decision = _text(reason, "decision reason", maximum=2_000)
        if expected_aggregate_version < 1:
            raise WorkflowCAlertRuleError("alert rule expected version is invalid")
        input_hash = _canonical_hash(
            {
                "rule_id": str(rule_id),
                "expected_aggregate_version": expected_aggregate_version,
                "target_status": target.value,
                "actor_id": actor,
                "reason": decision,
            }
        )
        return self._command(
            project_id=project_id,
            statement="""SELECT * FROM geo_transition_workflow_c_alert_rule(
                             %s, %s, %s, %s, %s, %s, %s, %s, %s
                         )""",
            parameters=(
                project_id,
                rule_id,
                expected_aggregate_version,
                target.value,
                actor,
                decision,
                _digest(idempotency_key),
                input_hash,
                self._clock(),
            ),
        )

    def get(self, *, project_id: UUID, rule_id: UUID) -> AlertRuleRelease:
        rows = self._read(
            project_id=project_id,
            statement="SELECT * FROM workflow_c_alert_rule_versions WHERE project_id = %s AND id = %s",
            parameters=(project_id, rule_id),
        )
        if not rows:
            raise WorkflowCAlertRuleNotFound("alert rule does not exist")
        return alert_rule_release_from_row(rows[0])

    def list(self, *, project_id: UUID) -> tuple[AlertRuleRelease, ...]:
        return tuple(
            alert_rule_release_from_row(row)
            for row in self._read(
                project_id=project_id,
                statement="""SELECT * FROM workflow_c_alert_rule_versions
                              WHERE project_id = %s ORDER BY created_at DESC, id DESC""",
                parameters=(project_id,),
            )
        )

    def _command(
        self,
        *,
        project_id: UUID,
        statement: str,
        parameters: tuple[object, ...],
    ) -> AlertRuleRelease:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(statement, parameters).fetchone()
            if row is None:
                raise WorkflowCAlertRuleError("alert rule command returned no release")
            result = alert_rule_release_from_row(_mapping(row))
            connection.commit()
            return result
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _read(
        self,
        *,
        project_id: UUID,
        statement: str,
        parameters: tuple[object, ...],
    ) -> tuple[Mapping[str, object], ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(statement, parameters).fetchall()
            connection.rollback()
            return tuple(_mapping(row) for row in rows)
        except psycopg.Error as error:
            connection.rollback()
            raise WorkflowCAlertRuleError("alert rules could not be read") from error
        finally:
            connection.close()


def alert_rule_release_from_row(row: Mapping[str, object]) -> AlertRuleRelease:
    try:
        payload = row["payload"]
        if not isinstance(payload, Mapping):
            raise TypeError("payload")
        parameters = payload.get("parameters")
        if not isinstance(parameters, Mapping):
            raise TypeError("parameters")
        rule = AlertRuleVersion(
            id=_uuid(row, "id"),
            project_id=_uuid(row, "project_id"),
            rule_key=_string(row, "rule_key"),
            version=_integer(row, "version"),
            kind=AlertRuleKind(_mapping_string(payload, "kind")),
            severity=AlertSeverity(_mapping_string(payload, "severity")),
            parameters=dict(parameters),
            frozen_by=_string(row, "created_by"),
            frozen_at=_timestamp(row, "created_at"),
        )
        if rule.rule_hash != _string(row, "rule_hash"):
            raise ValueError("rule hash")
        return AlertRuleRelease(
            rule=rule,
            status=AlertRuleReleaseStatus(_string(row, "status")),
            aggregate_version=_integer(row, "aggregate_version"),
            approved_by=_optional_string(row, "approved_by"),
            approved_at=_optional_timestamp(row, "approved_at"),
            retired_by=_optional_string(row, "retired_by"),
            retired_at=_optional_timestamp(row, "retired_at"),
            decision_reason=_optional_string(row, "decision_reason"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise WorkflowCAlertRuleError("alert rule row is malformed") from error


def _rule_payload(rule: AlertRuleVersion) -> dict[str, object]:
    return {
        "kind": rule.kind.value,
        "severity": rule.severity.value,
        "parameters": dict(rule.parameters),
    }


def _mapping(row: object) -> Mapping[str, object]:
    if not isinstance(row, Mapping):
        raise WorkflowCAlertRuleError("alert rule query must use mapping rows")
    return dict(row)


def _uuid(row: Mapping[str, object], key: str) -> UUID:
    value = row.get(key)
    if not isinstance(value, UUID):
        raise TypeError(key)
    return value


def _integer(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise TypeError(key)
    return value


def _string(row: Mapping[str, object], key: str) -> str:
    return _text(row.get(key), key, maximum=2_000)


def _mapping_string(row: Mapping[object, object], key: str) -> str:
    return _text(row.get(key), key, maximum=2_000)


def _optional_string(row: Mapping[str, object], key: str) -> str | None:
    return None if row.get(key) is None else _string(row, key)


def _timestamp(row: Mapping[str, object], key: str) -> datetime:
    value = row.get(key)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(key)
    return value


def _optional_timestamp(row: Mapping[str, object], key: str) -> datetime | None:
    return None if row.get(key) is None else _timestamp(row, key)


def _text(value: object, label: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise WorkflowCAlertRuleError(f"{label} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise WorkflowCAlertRuleError(f"{label} is invalid")
    return normalized


def _digest(value: str) -> str:
    return hashlib.sha256(_text(value, "Idempotency-Key", maximum=200).encode()).hexdigest()


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


__all__ = [
    "ALERT_RULE_NAMESPACE",
    "AlertRuleRelease",
    "AlertRuleReleaseStatus",
    "PostgresWorkflowCAlertRuleRepository",
    "WorkflowCAlertRuleError",
    "WorkflowCAlertRuleNotFound",
    "alert_rule_release_from_row",
    "new_alert_rule_release",
    "transition_alert_rule_release",
]
