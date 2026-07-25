"""Narrow Customer projection contract for approved Workflow C reports."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Literal, Protocol, cast
from uuid import UUID


WorkflowCCustomerSourceKind = Literal[
    "provider_api", "proxy_grounded_api", "automated_ui"
]
_CUSTOMER_SOURCE_KINDS = frozenset(
    {"provider_api", "proxy_grounded_api", "automated_ui"}
)
WorkflowCCustomerMetricKey = Literal[
    "mention",
    "mention_rate",
    "recommendation_rate",
    "brand_mention",
    "product_mention",
    "recommendation",
    "recommendation_strength",
    "competitor_mention",
    "competitor_relative_position",
    "sentiment",
    "fact_accuracy",
    "explicit_conflict",
    "subject_mixup",
    "key_fact_omission",
    "citation_entailment",
    "citation_position",
    "citation_order",
    "verified_url_hit",
    "source_domain_diversity",
    "source_type_diversity",
    "approved_corpus_absorption",
]
_CUSTOMER_METRIC_KEYS = frozenset(
    {
        "mention",
        "mention_rate",
        "recommendation_rate",
        "brand_mention",
        "product_mention",
        "recommendation",
        "recommendation_strength",
        "competitor_mention",
        "competitor_relative_position",
        "sentiment",
        "fact_accuracy",
        "explicit_conflict",
        "subject_mixup",
        "key_fact_omission",
        "citation_entailment",
        "citation_position",
        "citation_order",
        "verified_url_hit",
        "source_domain_diversity",
        "source_type_diversity",
        "approved_corpus_absorption",
    }
)
_CUSTOMER_PAYLOAD_KEYS = frozenset(
    {
        "headline",
        "summary",
        "methodology",
        "warnings",
        "mention_rate",
        "recommendation_rate",
        "metrics",
    }
)
_CANONICAL_DECIMAL_TEXT = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
_COUNT_METRIC_KEYS = frozenset({"source_domain_diversity", "source_type_diversity"})
_SIGNED_METRIC_KEYS = frozenset({"competitor_relative_position", "sentiment"})
WorkflowCCustomerMetricValue = int | float | str


class WorkflowCCustomerProjectionError(ValueError):
    """A row is not eligible for the Workflow C Customer projection."""


@dataclass(frozen=True)
class WorkflowCCustomerReportPayload(Mapping[str, object]):
    """Small positive contract for content that may cross the Customer boundary."""

    headline: str
    summary: str | None = None
    methodology: str | None = None
    warnings: tuple[str, ...] = ()
    mention_rate: WorkflowCCustomerMetricValue | None = None
    recommendation_rate: WorkflowCCustomerMetricValue | None = None
    metrics: tuple[tuple[WorkflowCCustomerMetricKey, WorkflowCCustomerMetricValue], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "headline",
            _bounded_text(self.headline, "Customer headline", maximum=200),
        )
        for key in ("summary", "methodology"):
            value = getattr(self, key)
            if value is not None:
                object.__setattr__(
                    self,
                    key,
                    _bounded_text(value, f"Customer {key}", maximum=2_000),
                )
        if not isinstance(self.warnings, tuple) or len(self.warnings) > 20:
            raise WorkflowCCustomerProjectionError(
                "Workflow C Customer warnings are invalid"
            )
        object.__setattr__(
            self,
            "warnings",
            tuple(
                _bounded_text(item, "Customer warning", maximum=500)
                for item in self.warnings
            ),
        )
        for key in ("mention_rate", "recommendation_rate"):
            value = getattr(self, key)
            if value is not None:
                object.__setattr__(self, key, _optional_rate({key: value}, key))
        if not isinstance(self.metrics, tuple) or len(self.metrics) > 32:
            raise WorkflowCCustomerProjectionError("Workflow C Customer metrics are invalid")
        parsed_metrics: list[
            tuple[WorkflowCCustomerMetricKey, WorkflowCCustomerMetricValue]
        ] = []
        seen: set[str] = set()
        for key, value in self.metrics:
            if key not in _CUSTOMER_METRIC_KEYS or key in seen:
                raise WorkflowCCustomerProjectionError(
                    "Workflow C Customer payload contains an unknown or duplicate metric"
                )
            seen.add(key)
            parsed_metrics.append((key, _validated_metric_value(key, value)))
        object.__setattr__(self, "metrics", tuple(sorted(parsed_metrics)))

    @classmethod
    def from_mapping(cls, value: object) -> WorkflowCCustomerReportPayload:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping) or not value:
            raise WorkflowCCustomerProjectionError(
                "Workflow C Customer payload must be a non-empty object"
            )
        keys = set(value)
        if any(not isinstance(key, str) for key in keys) or not keys <= _CUSTOMER_PAYLOAD_KEYS:
            raise WorkflowCCustomerProjectionError(
                "Workflow C Customer payload contains an unknown field"
            )
        metrics: tuple[
            tuple[WorkflowCCustomerMetricKey, WorkflowCCustomerMetricValue], ...
        ] = ()
        if "metrics" in value:
            metrics_value = value["metrics"]
            if not isinstance(metrics_value, Mapping) or not metrics_value or len(metrics_value) > 32:
                raise WorkflowCCustomerProjectionError(
                    "Workflow C Customer metrics must be a non-empty bounded object"
                )
            parsed_metrics: list[
                tuple[WorkflowCCustomerMetricKey, WorkflowCCustomerMetricValue]
            ] = []
            for key, metric_value in metrics_value.items():
                if not isinstance(key, str) or key not in _CUSTOMER_METRIC_KEYS:
                    raise WorkflowCCustomerProjectionError(
                        "Workflow C Customer payload contains an unknown metric"
                    )
                parsed_metrics.append(
                    (
                        cast(WorkflowCCustomerMetricKey, key),
                        _validated_metric_value(key, metric_value),
                    )
                )
            metrics = tuple(sorted(parsed_metrics))
        return cls(
            headline=_required_text(value, "headline", maximum=200),
            summary=_optional_text(value, "summary", maximum=2_000),
            methodology=_optional_text(value, "methodology", maximum=2_000),
            warnings=_warnings(value),
            mention_rate=_optional_rate(value, "mention_rate"),
            recommendation_rate=_optional_rate(value, "recommendation_rate"),
            metrics=metrics,
        )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for key in ("headline", "summary", "methodology", "mention_rate", "recommendation_rate"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        if self.warnings:
            result["warnings"] = list(self.warnings)
        if self.metrics:
            result["metrics"] = dict(self.metrics)
        return result

    def __getitem__(self, key: str) -> object:
        try:
            return self.to_dict()[key]
        except KeyError:
            raise KeyError(key) from None

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(frozen=True)
class WorkflowCCustomerApprovedReport:
    """A current, approved, immutable report safe for a Customer reader.

    This object deliberately has no draft/status field.  Its PostgreSQL reader
    is required to return only current `approved` snapshots after checking the
    source semantic snapshot and Observation eligibility.  Keeping that
    constraint out of the general Monitoring Report model avoids accidental
    approval inheritance from the legacy monitoring state machine.
    """

    id: UUID
    project_id: UUID
    campaign_id: UUID
    semantic_snapshot_hash: str
    report_hash: str
    source_kind: WorkflowCCustomerSourceKind
    approved_safe_payload: WorkflowCCustomerReportPayload
    approved_at: datetime

    def __post_init__(self) -> None:
        if self.source_kind not in _CUSTOMER_SOURCE_KINDS:
            raise WorkflowCCustomerProjectionError(
                "Workflow C Customer reports require an automated or API source"
            )
        for label, value in (
            ("semantic snapshot", self.semantic_snapshot_hash),
            ("report", self.report_hash),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise WorkflowCCustomerProjectionError(
                    f"Workflow C Customer {label} hash is invalid"
                )
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise WorkflowCCustomerProjectionError(
                "Workflow C Customer approval time must be timezone-aware"
            )
        object.__setattr__(
            self,
            "approved_safe_payload",
            WorkflowCCustomerReportPayload.from_mapping(self.approved_safe_payload),
        )


class WorkflowCCustomerReportReader(Protocol):
    """Project/Campaign-scoped durable read port used only by Customer routes."""

    persistence: Literal["durable"]

    def list_approved_reports(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[WorkflowCCustomerApprovedReport, ...]: ...


def _optional_text(value: Mapping[object, object], key: str, *, maximum: int) -> str | None:
    if key not in value:
        return None
    item = value[key]
    if not isinstance(item, str) or not item.strip() or len(item) > maximum:
        raise WorkflowCCustomerProjectionError(f"Workflow C Customer {key} is invalid")
    return item.strip()


def _required_text(value: Mapping[object, object], key: str, *, maximum: int) -> str:
    item = _optional_text(value, key, maximum=maximum)
    if item is None:
        raise WorkflowCCustomerProjectionError(f"Workflow C Customer {key} is required")
    return item


def _warnings(value: Mapping[object, object]) -> tuple[str, ...]:
    if "warnings" not in value:
        return ()
    items = value["warnings"]
    if not isinstance(items, list) or not items or len(items) > 20:
        raise WorkflowCCustomerProjectionError(
            "Workflow C Customer warnings must be a non-empty bounded list"
        )
    return tuple(
        _bounded_text(item, "Customer warning", maximum=500) for item in items
    )


def _optional_rate(
    value: Mapping[object, object], key: str
) -> WorkflowCCustomerMetricValue | None:
    if key not in value:
        return None
    item = _metric_value(value[key], f"Customer {key}")
    number = Decimal(str(item))
    if number < 0 or number > 1:
        raise WorkflowCCustomerProjectionError(f"Workflow C Customer {key} must be a ratio")
    return item


def _metric_value(value: object, label: str) -> WorkflowCCustomerMetricValue:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise WorkflowCCustomerProjectionError(f"Workflow C {label} is invalid")
    if isinstance(value, (int, float)):
        try:
            finite = math.isfinite(float(value))
        except OverflowError as error:
            raise WorkflowCCustomerProjectionError(
                f"Workflow C {label} must be finite"
            ) from error
        if not finite:
            raise WorkflowCCustomerProjectionError(f"Workflow C {label} must be finite")
        return value
    if len(value) > 64 or not _CANONICAL_DECIMAL_TEXT.fullmatch(value):
        raise WorkflowCCustomerProjectionError(f"Workflow C {label} is invalid")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise WorkflowCCustomerProjectionError(f"Workflow C {label} is invalid") from error
    if not number.is_finite():
        raise WorkflowCCustomerProjectionError(f"Workflow C {label} must be finite")
    return value


def _validated_metric_value(
    key: str, value: object
) -> WorkflowCCustomerMetricValue:
    item = _metric_value(value, f"Customer metric {key}")
    number = Decimal(str(item))
    if key in _COUNT_METRIC_KEYS:
        valid = number >= 0 and number == number.to_integral_value()
    elif key in _SIGNED_METRIC_KEYS:
        valid = Decimal("-1") <= number <= Decimal("1")
    else:
        valid = Decimal("0") <= number <= Decimal("1")
    if not valid:
        raise WorkflowCCustomerProjectionError(
            f"Workflow C Customer metric {key} is outside its allowed range"
        )
    return item


def _bounded_text(value: object, label: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise WorkflowCCustomerProjectionError(f"Workflow C {label} is invalid")
    return value.strip()


__all__ = [
    "WorkflowCCustomerApprovedReport",
    "WorkflowCCustomerMetricKey",
    "WorkflowCCustomerMetricValue",
    "WorkflowCCustomerProjectionError",
    "WorkflowCCustomerReportPayload",
    "WorkflowCCustomerReportReader",
    "WorkflowCCustomerSourceKind",
]
