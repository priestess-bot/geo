"""Deterministic, versioned evaluators for non-connector alert rules."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from geo_core.alerts.domain import (
    SHA256_PATTERN,
    AlertEvidenceReference,
    AlertRuleKind,
    AlertRuleVersion,
    AlertRuleViolation,
    AlertScope,
    AlertTriggerSnapshot,
    _bounded_key,
    _bounded_text,
    _canonical_decimal,
    _canonical_hash,
    _require_aware,
)


ALERT_EVALUATOR_VERSION = "alert-evaluator-v1"


@dataclass(frozen=True)
class AlertEvaluation:
    """A replayable decision; only matched decisions contain a trigger snapshot."""

    rule_kind: AlertRuleKind
    rule_hash: str
    scope: AlertScope
    parameter_schema_version: str
    input_schema_version: str
    input_hash: str
    matched: bool
    reason_codes: tuple[str, ...]
    evidence: tuple[AlertEvidenceReference, ...]
    evaluated_at: datetime
    trigger_snapshot: AlertTriggerSnapshot | None
    evaluator_version: str = ALERT_EVALUATOR_VERSION
    evaluation_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at, "alert evaluation time")
        if not SHA256_PATTERN.fullmatch(self.rule_hash):
            raise AlertRuleViolation("alert evaluation rule hash is invalid")
        if not SHA256_PATTERN.fullmatch(self.input_hash):
            raise AlertRuleViolation("alert evaluation input hash is invalid")
        if self.matched != bool(self.reason_codes):
            raise AlertRuleViolation("alert evaluation reasons do not match its decision")
        if self.matched != (self.trigger_snapshot is not None):
            raise AlertRuleViolation("alert evaluation trigger does not match its decision")
        object.__setattr__(
            self,
            "evaluation_hash",
            _canonical_hash(self.canonical_value()),
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "evaluator_version": self.evaluator_version,
            "rule_kind": self.rule_kind.value,
            "rule_hash": self.rule_hash,
            "scope": self.scope.canonical_value(),
            "parameter_schema_version": self.parameter_schema_version,
            "input_schema_version": self.input_schema_version,
            "input_hash": self.input_hash,
            "matched": self.matched,
            "reason_codes": list(self.reason_codes),
            "evidence": [item.canonical_value() for item in self.evidence],
            "evaluated_at": self.evaluated_at.isoformat(),
            "trigger_snapshot_hash": (
                self.trigger_snapshot.snapshot_hash
                if self.trigger_snapshot is not None
                else None
            ),
        }


@dataclass(frozen=True)
class _RuleDecision:
    parameter_schema_version: str
    input_schema_version: str
    canonical_input: Mapping[str, object]
    trigger_values: Mapping[str, object]
    reason_codes: tuple[str, ...]


_Evaluator = Callable[
    [Mapping[str, object], Mapping[str, object], datetime],
    _RuleDecision,
]


def evaluate_alert_rule(
    *,
    rule_version: AlertRuleVersion,
    scope: AlertScope,
    input_values: Mapping[str, object],
    evidence: Sequence[AlertEvidenceReference],
    evaluated_at: datetime,
) -> AlertEvaluation:
    """Evaluate one frozen rule without persistence or implicit external reads."""

    _require_aware(evaluated_at, "alert evaluation time")
    if rule_version.project_id != scope.project_id:
        raise AlertRuleViolation("alert evaluation rule and scope project differ")
    evaluator = _EVALUATORS[rule_version.kind]
    decision = evaluator(rule_version.parameters, input_values, evaluated_at)
    input_hash = _canonical_hash(decision.canonical_input)
    normalized_evidence = _evidence_with_locators(evidence)
    matched = bool(decision.reason_codes)
    trigger_snapshot = None
    if matched:
        trigger_snapshot = AlertTriggerSnapshot(
            values={
                "evaluator_version": ALERT_EVALUATOR_VERSION,
                "rule_hash": rule_version.rule_hash,
                "input_hash": input_hash,
                "reason_codes": decision.reason_codes,
                **decision.trigger_values,
            },
            captured_at=evaluated_at,
        )
    return AlertEvaluation(
        rule_kind=rule_version.kind,
        rule_hash=rule_version.rule_hash,
        scope=scope,
        parameter_schema_version=decision.parameter_schema_version,
        input_schema_version=decision.input_schema_version,
        input_hash=input_hash,
        matched=matched,
        reason_codes=decision.reason_codes,
        evidence=normalized_evidence,
        evaluated_at=evaluated_at,
        trigger_snapshot=trigger_snapshot,
    )


def _threshold(
    parameters: Mapping[str, object],
    values: Mapping[str, object],
    _evaluated_at: datetime,
) -> _RuleDecision:
    parameter_schema = "alert-rule-threshold-v1"
    input_schema = "alert-input-threshold-v1"
    _exact(parameters, {"schema_version", "metric_key", "operator", "threshold"}, "threshold parameters")
    _schema(parameters, parameter_schema, "threshold parameters")
    metric_key = _key(parameters["metric_key"], "threshold metric key")
    operator = _enum(parameters["operator"], {"lt", "lte", "gt", "gte"}, "threshold operator")
    threshold = _decimal(parameters["threshold"], "threshold value")
    _exact(values, {"schema_version", "metric_key", "observed_value"}, "threshold input")
    _schema(values, input_schema, "threshold input")
    _same_key(values["metric_key"], metric_key, "threshold input metric key")
    observed = _decimal(values["observed_value"], "threshold observed value")
    matched = {
        "lt": observed < threshold,
        "lte": observed <= threshold,
        "gt": observed > threshold,
        "gte": observed >= threshold,
    }[operator]
    canonical_input = {
        "schema_version": input_schema,
        "metric_key": metric_key,
        "observed_value": _canonical_decimal(observed),
    }
    return _decision(
        parameter_schema,
        input_schema,
        canonical_input,
        {
            "metric_key": metric_key,
            "observed_value": _canonical_decimal(observed),
            "operator": operator,
            "threshold": _canonical_decimal(threshold),
        },
        ("threshold_crossed",) if matched else (),
    )


def _baseline_delta(
    parameters: Mapping[str, object],
    values: Mapping[str, object],
    _evaluated_at: datetime,
) -> _RuleDecision:
    parameter_schema = "alert-rule-baseline-delta-v1"
    input_schema = "alert-input-baseline-delta-v1"
    _exact(parameters, {"schema_version", "metric_key", "direction", "minimum_delta"}, "baseline delta parameters")
    _schema(parameters, parameter_schema, "baseline delta parameters")
    metric_key = _key(parameters["metric_key"], "baseline delta metric key")
    direction = _enum(parameters["direction"], {"decrease", "increase", "absolute"}, "baseline delta direction")
    minimum = _positive_decimal(parameters["minimum_delta"], "baseline minimum delta")
    _exact(values, {"schema_version", "metric_key", "baseline_value", "current_value"}, "baseline delta input")
    _schema(values, input_schema, "baseline delta input")
    _same_key(values["metric_key"], metric_key, "baseline delta input metric key")
    baseline = _decimal(values["baseline_value"], "baseline value")
    current = _decimal(values["current_value"], "current value")
    delta = current - baseline
    matched = {
        "decrease": delta <= -minimum,
        "increase": delta >= minimum,
        "absolute": abs(delta) >= minimum,
    }[direction]
    canonical_input = {
        "schema_version": input_schema,
        "metric_key": metric_key,
        "baseline_value": _canonical_decimal(baseline),
        "current_value": _canonical_decimal(current),
    }
    return _decision(
        parameter_schema,
        input_schema,
        canonical_input,
        {
            "metric_key": metric_key,
            "baseline_value": _canonical_decimal(baseline),
            "current_value": _canonical_decimal(current),
            "delta": _canonical_decimal(delta),
            "direction": direction,
            "minimum_delta": _canonical_decimal(minimum),
        },
        (f"baseline_{direction}",) if matched else (),
    )


def _negative_question(
    parameters: Mapping[str, object],
    values: Mapping[str, object],
    _evaluated_at: datetime,
) -> _RuleDecision:
    parameter_schema = "alert-rule-negative-question-v1"
    input_schema = "alert-input-negative-question-v1"
    _exact(parameters, {"schema_version", "metric_key", "maximum_delta", "require_interval_below_zero"}, "negative question parameters")
    _schema(parameters, parameter_schema, "negative question parameters")
    metric_key = _key(parameters["metric_key"], "negative question metric key")
    maximum = _decimal(parameters["maximum_delta"], "negative question maximum delta")
    if maximum >= 0:
        raise AlertRuleViolation("negative question maximum delta must be negative")
    require_interval = _boolean(parameters["require_interval_below_zero"], "negative question interval policy")
    _exact(values, {"schema_version", "metric_key", "question_id", "delta", "interval_low", "interval_high"}, "negative question input")
    _schema(values, input_schema, "negative question input")
    _same_key(values["metric_key"], metric_key, "negative question input metric key")
    question_id = _text(values["question_id"], "negative question id")
    delta = _decimal(values["delta"], "negative question delta")
    low = _decimal(values["interval_low"], "negative question interval low")
    high = _decimal(values["interval_high"], "negative question interval high")
    if low > high or not low <= delta <= high:
        raise AlertRuleViolation("negative question interval is inconsistent")
    matched = delta <= maximum and (not require_interval or high < 0)
    canonical_input = {
        "schema_version": input_schema,
        "metric_key": metric_key,
        "question_id": question_id,
        "delta": _canonical_decimal(delta),
        "interval_low": _canonical_decimal(low),
        "interval_high": _canonical_decimal(high),
    }
    return _decision(
        parameter_schema,
        input_schema,
        canonical_input,
        {
            **canonical_input,
            "maximum_delta": _canonical_decimal(maximum),
            "require_interval_below_zero": require_interval,
        },
        ("negative_question",) if matched else (),
    )


def _completion_freshness(
    parameters: Mapping[str, object],
    values: Mapping[str, object],
    evaluated_at: datetime,
) -> _RuleDecision:
    parameter_schema = "alert-rule-completion-freshness-v1"
    input_schema = "alert-input-completion-freshness-v1"
    _exact(parameters, {"schema_version", "minimum_completion_ratio", "maximum_age_seconds"}, "completion freshness parameters")
    _schema(parameters, parameter_schema, "completion freshness parameters")
    minimum = _decimal(parameters["minimum_completion_ratio"], "minimum completion ratio")
    if not 0 <= minimum <= 1:
        raise AlertRuleViolation("minimum completion ratio must be between zero and one")
    maximum_age = _positive_integer(parameters["maximum_age_seconds"], "maximum freshness age")
    _exact(values, {"schema_version", "planned_count", "valid_count", "invalid_count", "missing_count", "snapshot_captured_at"}, "completion freshness input")
    _schema(values, input_schema, "completion freshness input")
    planned = _positive_integer(values["planned_count"], "planned count")
    valid = _non_negative_integer(values["valid_count"], "valid count")
    invalid = _non_negative_integer(values["invalid_count"], "invalid count")
    missing = _non_negative_integer(values["missing_count"], "missing count")
    if valid + invalid + missing != planned:
        raise AlertRuleViolation("completion counts must equal the planned denominator")
    captured_at = _aware_datetime(values["snapshot_captured_at"], "snapshot capture time")
    if captured_at > evaluated_at:
        raise AlertRuleViolation("snapshot capture time cannot follow evaluation")
    completion = Decimal(valid) / Decimal(planned)
    age_seconds = Decimal(str((evaluated_at - captured_at).total_seconds()))
    insufficient = completion < minimum
    stale = age_seconds > maximum_age
    reasons = tuple(
        reason
        for reason, matched in (
            ("insufficient_samples", insufficient),
            ("stale_snapshot", stale),
        )
        if matched
    )
    canonical_input = {
        "schema_version": input_schema,
        "planned_count": planned,
        "valid_count": valid,
        "invalid_count": invalid,
        "missing_count": missing,
        "snapshot_captured_at": captured_at.isoformat(),
    }
    return _decision(
        parameter_schema,
        input_schema,
        canonical_input,
        {
            **canonical_input,
            "completion_ratio": _canonical_decimal(completion),
            "minimum_completion_ratio": _canonical_decimal(minimum),
            "age_seconds": _canonical_decimal(age_seconds),
            "maximum_age_seconds": maximum_age,
            "insufficient_samples": insufficient,
            "stale_snapshot": stale,
        },
        reasons,
    )


def _model_drift(
    parameters: Mapping[str, object],
    values: Mapping[str, object],
    _evaluated_at: datetime,
) -> _RuleDecision:
    return _set_drift(
        parameters,
        values,
        label="model drift",
        parameter_schema="alert-rule-model-drift-v1",
        input_schema="alert-input-model-drift-v1",
        baseline_key="baseline_models",
        current_key="current_models",
        minimum_key="minimum_changed_models",
        reason="model_drift",
        hash_items=False,
    )


def _source_drift(
    parameters: Mapping[str, object],
    values: Mapping[str, object],
    _evaluated_at: datetime,
) -> _RuleDecision:
    return _set_drift(
        parameters,
        values,
        label="source drift",
        parameter_schema="alert-rule-source-drift-v1",
        input_schema="alert-input-source-drift-v1",
        baseline_key="baseline_composition_hashes",
        current_key="current_composition_hashes",
        minimum_key="minimum_changed_compositions",
        reason="source_drift",
        hash_items=True,
    )


def _external_health(
    parameters: Mapping[str, object],
    values: Mapping[str, object],
    _evaluated_at: datetime,
) -> _RuleDecision:
    parameter_schema = "alert-rule-external-health-v1"
    input_schema = "alert-input-external-health-v1"
    _exact(parameters, {"schema_version", "minimum_severity"}, "external health parameters")
    _schema(parameters, parameter_schema, "external health parameters")
    minimum = _enum(
        parameters["minimum_severity"], {"info", "warning", "critical"},
        "external health minimum severity",
    )
    expected = {
        "schema_version", "source_kind", "source_id", "source_version",
        "signal_kind", "severity", "reason_code", "action_path", "payload",
        "observed_at",
    }
    _exact(values, expected, "external health input")
    _schema(values, input_schema, "external health input")
    source_kind = _key(values["source_kind"], "external health source kind")
    source_id = _text(values["source_id"], "external health source id")
    source_version = _positive_integer(values["source_version"], "external health source version")
    signal_kind = _key(values["signal_kind"], "external health signal kind")
    severity = _enum(values["severity"], {"info", "warning", "critical"}, "external health severity")
    reason_code = _key(values["reason_code"], "external health reason code")
    action_path = _text(values["action_path"], "external health action path")
    if not action_path.startswith("/projects/"):
        raise AlertRuleViolation("external health action path must be project-local")
    payload = values["payload"]
    if not isinstance(payload, Mapping):
        raise AlertRuleViolation("external health payload must be an object")
    observed_value = values["observed_at"]
    if not isinstance(observed_value, str):
        raise AlertRuleViolation("external health observed at must be ISO 8601 text")
    try:
        observed_at = datetime.fromisoformat(observed_value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AlertRuleViolation("external health observed at is invalid") from error
    _require_aware(observed_at, "external health observed at")
    ranks = {"info": 1, "warning": 2, "critical": 3}
    matched = ranks[severity] >= ranks[minimum]
    canonical_input = {
        "schema_version": input_schema,
        "source_kind": source_kind,
        "source_id": source_id,
        "source_version": source_version,
        "signal_kind": signal_kind,
        "severity": severity,
        "reason_code": reason_code,
        "action_path": action_path,
        "payload": dict(payload),
        "observed_at": observed_at.isoformat(),
    }
    return _decision(
        parameter_schema,
        input_schema,
        canonical_input,
        canonical_input | {"minimum_severity": minimum},
        (reason_code,) if matched else (),
    )


def _set_drift(
    parameters: Mapping[str, object],
    values: Mapping[str, object],
    *,
    label: str,
    parameter_schema: str,
    input_schema: str,
    baseline_key: str,
    current_key: str,
    minimum_key: str,
    reason: str,
    hash_items: bool,
) -> _RuleDecision:
    _exact(parameters, {"schema_version", minimum_key}, f"{label} parameters")
    _schema(parameters, parameter_schema, f"{label} parameters")
    minimum = _positive_integer(parameters[minimum_key], f"{label} minimum changes")
    _exact(values, {"schema_version", "stratum_hash", baseline_key, current_key}, f"{label} input")
    _schema(values, input_schema, f"{label} input")
    stratum_hash = _hash(values["stratum_hash"], f"{label} stratum hash")
    baseline = _string_set(values[baseline_key], f"{label} baseline", hashes=hash_items)
    current = _string_set(values[current_key], f"{label} current", hashes=hash_items)
    added = tuple(sorted(set(current) - set(baseline)))
    removed = tuple(sorted(set(baseline) - set(current)))
    changed = len(added) + len(removed)
    canonical_input = {
        "schema_version": input_schema,
        "stratum_hash": stratum_hash,
        baseline_key: baseline,
        current_key: current,
    }
    return _decision(
        parameter_schema,
        input_schema,
        canonical_input,
        {
            **canonical_input,
            "added": added,
            "removed": removed,
            "changed_count": changed,
            minimum_key: minimum,
        },
        (reason,) if changed >= minimum else (),
    )


def _decision(
    parameter_schema: str,
    input_schema: str,
    canonical_input: Mapping[str, object],
    trigger_values: Mapping[str, object],
    reason_codes: tuple[str, ...],
) -> _RuleDecision:
    return _RuleDecision(
        parameter_schema_version=parameter_schema,
        input_schema_version=input_schema,
        canonical_input=canonical_input,
        trigger_values=trigger_values,
        reason_codes=reason_codes,
    )


def _evidence_with_locators(
    evidence: Sequence[AlertEvidenceReference],
) -> tuple[AlertEvidenceReference, ...]:
    normalized = tuple(
        sorted(
            set(evidence),
            key=lambda item: (
                item.kind,
                item.resource_id,
                item.version,
                item.sha256,
                item.locator or "",
            ),
        )
    )
    if not normalized or len(normalized) != len(evidence):
        raise AlertRuleViolation("alert evaluation evidence must be non-empty and unique")
    if any(item.locator is None for item in normalized):
        raise AlertRuleViolation("alert evaluation evidence requires locators")
    return normalized


def _exact(values: Mapping[str, object], expected: set[str], label: str) -> None:
    if any(not isinstance(key, str) for key in values):
        raise AlertRuleViolation(f"{label} contains a non-text field")
    actual = set(values)
    if actual != expected:
        unknown = sorted(actual - expected)
        missing = sorted(expected - actual)
        raise AlertRuleViolation(
            f"{label} fields are invalid; unknown={unknown}, missing={missing}"
        )


def _schema(values: Mapping[str, object], expected: str, label: str) -> None:
    if values["schema_version"] != expected:
        raise AlertRuleViolation(f"{label} schema version is unsupported")


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise AlertRuleViolation(f"{label} must be a finite decimal")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as error:
        raise AlertRuleViolation(f"{label} must be a finite decimal") from error
    if not parsed.is_finite():
        raise AlertRuleViolation(f"{label} must be a finite decimal")
    return parsed


def _positive_decimal(value: object, label: str) -> Decimal:
    parsed = _decimal(value, label)
    if parsed <= 0:
        raise AlertRuleViolation(f"{label} must be positive")
    return parsed


def _non_negative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AlertRuleViolation(f"{label} must be a non-negative integer")
    return value


def _positive_integer(value: object, label: str) -> int:
    parsed = _non_negative_integer(value, label)
    if parsed == 0:
        raise AlertRuleViolation(f"{label} must be positive")
    return parsed


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise AlertRuleViolation(f"{label} must be boolean")
    return value


def _key(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise AlertRuleViolation(f"{label} must be a key")
    return _bounded_key(value, label)


def _same_key(value: object, expected: str, label: str) -> None:
    if _key(value, label) != expected:
        raise AlertRuleViolation(f"{label} does not match the frozen rule")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise AlertRuleViolation(f"{label} must be text")
    return _bounded_text(value, label)


def _enum(value: object, allowed: set[str], label: str) -> str:
    parsed = _key(value, label)
    if parsed not in allowed:
        raise AlertRuleViolation(f"{label} is unsupported")
    return parsed


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise AlertRuleViolation(f"{label} must be lowercase SHA-256")
    return value


def _string_set(value: object, label: str, *, hashes: bool) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AlertRuleViolation(f"{label} must be a non-empty sequence")
    parsed = tuple(
        _hash(item, label) if hashes else _text(item, label)
        for item in value
    )
    if not parsed or len(set(parsed)) != len(parsed):
        raise AlertRuleViolation(f"{label} must contain unique values")
    return tuple(sorted(parsed))


def _aware_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise AlertRuleViolation(f"{label} must be a datetime")
    _require_aware(value, label)
    return value


_EVALUATORS: Mapping[AlertRuleKind, _Evaluator] = {
    AlertRuleKind.THRESHOLD: _threshold,
    AlertRuleKind.BASELINE_DELTA: _baseline_delta,
    AlertRuleKind.NEGATIVE_QUESTION: _negative_question,
    AlertRuleKind.COMPLETION_FRESHNESS: _completion_freshness,
    AlertRuleKind.MODEL_DRIFT: _model_drift,
    AlertRuleKind.SOURCE_DRIFT: _source_drift,
    AlertRuleKind.EXTERNAL_HEALTH: _external_health,
}
