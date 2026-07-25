"""Immutable governed comparison-plan and drift-protocol models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import re
from typing import TypeAlias
from uuid import UUID, uuid5

from geo_core.statistical_methods.contracts import canonical_hash, decimal_value
from geo_core.workflow_c_statistical_protocol_values import (
    StatisticalProtocolError,
    decimal_value as _decimal,
    enum_value as _enum,
    integer_value as _integer,
    key_value as _key,
    only_keys as _only_keys,
    require_aware as _aware,
    row_text as _text_value,
    schema_one as _schema_one,
    text_value as _text,
)


STATISTICAL_PROTOCOL_NAMESPACE = UUID("8f7bbf60-35b3-5606-bd8f-77463c2c1b3d")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StatisticalProtocolNotFound(LookupError):
    """The Project-scoped statistical release does not exist."""


class StatisticalProtocolKind(StrEnum):
    COMPARISON_PLAN = "comparison_plan"
    DRIFT_PROTOCOL = "drift_protocol"


class StatisticalProtocolStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    RETIRED = "retired"


@dataclass(frozen=True)
class ComparisonPlanDefinition:
    family: str
    question_clusters: tuple[str, ...]
    alpha: Decimal
    delta: Decimal
    target_power: Decimal
    precision: Decimal
    min_pairs: int
    power_plan_hash: str
    a_priori_design_power: Decimal
    metric_key: str = "question_performance"
    metric_method_version: str = "semantic-question-performance-v1"
    power_method_version: str = "a-priori-design-power-v1"
    minimum_completion_ratio: Decimal = Decimal("0.80")
    bootstrap_iterations: int = 10_000
    bootstrap_method: str = "paired-bootstrap-percentile-v1"
    correction_method: str = "holm-v1"
    simultaneous_interval_method: str = (
        "paired-bootstrap-percentile-bonferroni-family-v1"
    )
    definition_hash: str = field(init=False)
    kind: StatisticalProtocolKind = field(
        init=False, default=StatisticalProtocolKind.COMPARISON_PLAN
    )

    def __post_init__(self) -> None:
        family = _key(self.family, "comparison family")
        clusters = tuple(sorted({_text(value, "question cluster") for value in self.question_clusters}))
        if not clusters:
            raise StatisticalProtocolError("comparison plan requires question clusters")
        if self.metric_key != "question_performance" or (
            self.metric_method_version != "semantic-question-performance-v1"
        ):
            raise StatisticalProtocolError("comparison metric method is unsupported")
        if self.power_method_version != "a-priori-design-power-v1":
            raise StatisticalProtocolError("comparison power method is unsupported")
        if self.bootstrap_method != "paired-bootstrap-percentile-v1":
            raise StatisticalProtocolError("comparison bootstrap method is unsupported")
        if self.correction_method != "holm-v1" or self.simultaneous_interval_method != (
            "paired-bootstrap-percentile-bonferroni-family-v1"
        ):
            raise StatisticalProtocolError("comparison family correction is unsupported")
        for value, label in (
            (self.alpha, "alpha"),
            (self.delta, "delta"),
            (self.target_power, "target power"),
            (self.precision, "precision"),
            (self.a_priori_design_power, "a-priori design power"),
            (self.minimum_completion_ratio, "minimum completion ratio"),
        ):
            if not value.is_finite():
                raise StatisticalProtocolError(f"{label} must be finite")
        if not Decimal(0) < self.alpha < Decimal(1):
            raise StatisticalProtocolError("alpha must be in (0, 1)")
        if self.delta < 0 or self.precision <= 0:
            raise StatisticalProtocolError("delta/precision are invalid")
        if not Decimal("0.80") <= self.target_power <= Decimal(1):
            raise StatisticalProtocolError("target power must be at least 0.80")
        if not Decimal(0) <= self.a_priori_design_power <= Decimal(1):
            raise StatisticalProtocolError("a-priori design power is invalid")
        if not Decimal("0.80") <= self.minimum_completion_ratio <= Decimal(1):
            raise StatisticalProtocolError("minimum completion ratio must be at least 0.80")
        if self.min_pairs < 1 or self.bootstrap_iterations < 100:
            raise StatisticalProtocolError("comparison sample/iteration bounds are invalid")
        if not _SHA256.fullmatch(self.power_plan_hash):
            raise StatisticalProtocolError("power plan hash must be SHA-256")
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "question_clusters", clusters)
        object.__setattr__(self, "definition_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind.value,
            "family": self.family,
            "metric_key": self.metric_key,
            "metric_method_version": self.metric_method_version,
            "question_clusters": list(self.question_clusters),
            "alpha": decimal_value(self.alpha),
            "delta": decimal_value(self.delta),
            "target_power": decimal_value(self.target_power),
            "precision": decimal_value(self.precision),
            "min_pairs": self.min_pairs,
            "power_plan_hash": self.power_plan_hash,
            "a_priori_design_power": decimal_value(self.a_priori_design_power),
            "power_method_version": self.power_method_version,
            "minimum_completion_ratio": decimal_value(self.minimum_completion_ratio),
            "bootstrap_iterations": self.bootstrap_iterations,
            "bootstrap_method": self.bootstrap_method,
            "correction_method": self.correction_method,
            "simultaneous_interval_method": self.simultaneous_interval_method,
        }


@dataclass(frozen=True)
class DriftProtocolDefinition:
    minimum_question_count: int
    method_version: str = "strict-stratum-drift-v1"
    effect_metric: str = "question_performance"
    definition_hash: str = field(init=False)
    kind: StatisticalProtocolKind = field(
        init=False, default=StatisticalProtocolKind.DRIFT_PROTOCOL
    )

    def __post_init__(self) -> None:
        if self.method_version != "strict-stratum-drift-v1":
            raise StatisticalProtocolError("drift method is unsupported")
        if self.effect_metric != "question_performance":
            raise StatisticalProtocolError("drift effect metric is unsupported")
        if self.minimum_question_count < 1:
            raise StatisticalProtocolError("drift minimum question count must be positive")
        object.__setattr__(self, "definition_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind.value,
            "method_version": self.method_version,
            "effect_metric": self.effect_metric,
            "minimum_question_count": self.minimum_question_count,
        }


StatisticalProtocolDefinition: TypeAlias = (
    ComparisonPlanDefinition | DriftProtocolDefinition
)


@dataclass(frozen=True)
class StatisticalProtocolVersion:
    id: UUID
    project_id: UUID
    series_id: UUID
    version: int
    supersedes_protocol_id: UUID | None
    status: StatisticalProtocolStatus
    definition: StatisticalProtocolDefinition
    created_by: str
    created_at: datetime
    updated_at: datetime
    aggregate_version: int = 1
    submitted_by: str | None = None
    submitted_at: datetime | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    retired_by: str | None = None
    retired_at: datetime | None = None
    decision_reason: str | None = None

    def __post_init__(self) -> None:
        status = StatisticalProtocolStatus(self.status)
        if self.version < 1 or self.aggregate_version < 1:
            raise StatisticalProtocolError("statistical protocol versions are invalid")
        if (self.version == 1) != (self.supersedes_protocol_id is None):
            raise StatisticalProtocolError("statistical protocol predecessor is invalid")
        if self.version == 1 and self.series_id != self.id:
            raise StatisticalProtocolError("initial statistical series id must equal id")
        _aware(self.created_at, "created time")
        _aware(self.updated_at, "updated time")
        if self.updated_at < self.created_at:
            raise StatisticalProtocolError("statistical protocol time is invalid")
        _text(self.created_by, "creator")
        _validate_state(self, status)
        object.__setattr__(self, "status", status)

    @property
    def kind(self) -> StatisticalProtocolKind:
        return self.definition.kind

    @property
    def definition_hash(self) -> str:
        return self.definition.definition_hash


def parse_statistical_protocol_definition(
    value: Mapping[str, object],
) -> StatisticalProtocolDefinition:
    kind = _enum(StatisticalProtocolKind, value.get("kind"), "protocol kind")
    if kind is StatisticalProtocolKind.COMPARISON_PLAN:
        _only_keys(
            value,
            {
                "schema_version", "kind", "family", "metric_key",
                "metric_method_version", "question_clusters", "alpha", "delta",
                "target_power", "precision", "min_pairs", "power_plan_hash",
                "a_priori_design_power", "power_method_version",
                "minimum_completion_ratio", "bootstrap_iterations",
                "bootstrap_method", "correction_method", "simultaneous_interval_method",
            },
        )
        _schema_one(value)
        clusters = value.get("question_clusters")
        if not isinstance(clusters, list):
            raise StatisticalProtocolError("question clusters must be an array")
        return ComparisonPlanDefinition(
            family=_text_value(value, "family"),
            metric_key=_text_value(value, "metric_key"),
            metric_method_version=_text_value(value, "metric_method_version"),
            question_clusters=tuple(_text(item, "question cluster") for item in clusters),
            alpha=_decimal(value, "alpha"),
            delta=_decimal(value, "delta"),
            target_power=_decimal(value, "target_power"),
            precision=_decimal(value, "precision"),
            min_pairs=_integer(value, "min_pairs"),
            power_plan_hash=_text_value(value, "power_plan_hash"),
            a_priori_design_power=_decimal(value, "a_priori_design_power"),
            power_method_version=_text_value(value, "power_method_version"),
            minimum_completion_ratio=_decimal(value, "minimum_completion_ratio"),
            bootstrap_iterations=_integer(value, "bootstrap_iterations"),
            bootstrap_method=_text_value(value, "bootstrap_method"),
            correction_method=_text_value(value, "correction_method"),
            simultaneous_interval_method=_text_value(
                value, "simultaneous_interval_method"
            ),
        )
    _only_keys(
        value,
        {"schema_version", "kind", "method_version", "effect_metric", "minimum_question_count"},
    )
    _schema_one(value)
    return DriftProtocolDefinition(
        method_version=_text_value(value, "method_version"),
        effect_metric=_text_value(value, "effect_metric"),
        minimum_question_count=_integer(value, "minimum_question_count"),
    )


def new_statistical_protocol(
    *,
    project_id: UUID,
    definition: StatisticalProtocolDefinition,
    actor_id: str,
    idempotency_key: str,
    occurred_at: datetime,
    predecessor: StatisticalProtocolVersion | None = None,
) -> StatisticalProtocolVersion:
    key = _text(idempotency_key, "Idempotency-Key", maximum=200)
    protocol_id = uuid5(
        STATISTICAL_PROTOCOL_NAMESPACE,
        f"{project_id}:{definition.kind.value}:{key}",
    )
    if predecessor is None:
        series_id, version, predecessor_id = protocol_id, 1, None
    else:
        if predecessor.project_id != project_id or predecessor.kind is not definition.kind:
            raise StatisticalProtocolError("statistical predecessor scope/kind is invalid")
        if predecessor.status not in {
            StatisticalProtocolStatus.APPROVED,
            StatisticalProtocolStatus.RETIRED,
        }:
            raise StatisticalProtocolError("statistical predecessor must be decided")
        series_id, version, predecessor_id = (
            predecessor.series_id,
            predecessor.version + 1,
            predecessor.id,
        )
    return StatisticalProtocolVersion(
        id=protocol_id,
        project_id=project_id,
        series_id=series_id,
        version=version,
        supersedes_protocol_id=predecessor_id,
        status=StatisticalProtocolStatus.DRAFT,
        definition=definition,
        created_by=_text(actor_id, "creator"),
        created_at=occurred_at,
        updated_at=occurred_at,
    )


def transition_statistical_protocol(
    protocol: StatisticalProtocolVersion,
    *,
    target_status: StatisticalProtocolStatus,
    actor_id: str,
    occurred_at: datetime,
    reason: str | None = None,
) -> StatisticalProtocolVersion:
    """Apply the same maker-checker lifecycle enforced by the PostgreSQL RPC."""
    actor = _text(actor_id, "statistical protocol actor")
    _aware(occurred_at, "statistical protocol transition time")
    if target_status is StatisticalProtocolStatus.IN_REVIEW:
        if protocol.status is not StatisticalProtocolStatus.DRAFT or reason is not None:
            raise StatisticalProtocolError(
                "only a draft statistical protocol can be submitted without a reason"
            )
        return replace(
            protocol,
            status=target_status,
            submitted_by=actor,
            submitted_at=occurred_at,
            updated_at=occurred_at,
            aggregate_version=protocol.aggregate_version + 1,
        )
    normalized_reason = _text(reason or "", "statistical protocol decision reason")
    if target_status is StatisticalProtocolStatus.APPROVED:
        if protocol.status is not StatisticalProtocolStatus.IN_REVIEW:
            raise StatisticalProtocolError(
                "only an in-review statistical protocol can be approved"
            )
        if actor == protocol.created_by:
            raise StatisticalProtocolError(
                "statistical protocol maker cannot approve the same version"
            )
        return replace(
            protocol,
            status=target_status,
            approved_by=actor,
            approved_at=occurred_at,
            decision_reason=normalized_reason,
            updated_at=occurred_at,
            aggregate_version=protocol.aggregate_version + 1,
        )
    if target_status is StatisticalProtocolStatus.RETIRED:
        if protocol.status is not StatisticalProtocolStatus.APPROVED:
            raise StatisticalProtocolError(
                "only an approved statistical protocol can be retired"
            )
        return replace(
            protocol,
            status=target_status,
            retired_by=actor,
            retired_at=occurred_at,
            decision_reason=normalized_reason,
            updated_at=occurred_at,
            aggregate_version=protocol.aggregate_version + 1,
        )
    raise StatisticalProtocolError("statistical protocol transition target is invalid")


def _validate_state(
    value: StatisticalProtocolVersion, status: StatisticalProtocolStatus
) -> None:
    submitted = (value.submitted_by, value.submitted_at)
    approved = (value.approved_by, value.approved_at)
    retired = (value.retired_by, value.retired_at)
    if status is StatisticalProtocolStatus.DRAFT:
        valid = submitted == approved == retired == (None, None) and value.decision_reason is None
    elif status is StatisticalProtocolStatus.IN_REVIEW:
        valid = all(item is not None for item in submitted) and approved == retired == (None, None)
        valid = valid and value.decision_reason is None
    elif status is StatisticalProtocolStatus.APPROVED:
        valid = all(item is not None for item in (*submitted, *approved))
        valid = valid and retired == (None, None) and value.decision_reason is not None
        valid = valid and value.approved_by != value.created_by
    else:
        valid = all(item is not None for item in (*submitted, *approved, *retired))
        valid = valid and value.decision_reason is not None
    if not valid:
        raise StatisticalProtocolError("statistical protocol lifecycle state is invalid")
