"""PostgreSQL adapter for current, producer-owned Recommendation evidence."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any, TypedDict
from uuid import UUID

import psycopg

from geo_core.recommendations.evidence import (
    AttributionRef,
    ContentRef,
    EvidenceRef,
    FactRef,
    MetricComparisonRef,
    ModelCallRef,
    ObservationEvidenceClass,
    ObservationRef,
    PromptReleaseRef,
    QuestionRef,
    RuleRef,
    SurfaceRef,
)
from geo_core.recommendations.errors import (
    RecommendationRuleViolation,
    RecommendationSourceStale,
)
from geo_core.recommendations.ports import RecommendationPersistenceError
from geo_core.recommendations.resolution import RecommendationEvidenceSelector


class PostgresRecommendationEvidenceResolver:
    """Resolve each selector through the audited producer projection SQL contract."""

    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection = connection
        self._project_id = project_id

    def resolve_current(
        self,
        *,
        project_id: UUID,
        selectors: tuple[RecommendationEvidenceSelector, ...],
    ) -> tuple[EvidenceRef, ...]:
        return tuple(item[0] for item in self.resolve_with_summaries(
            project_id=project_id,
            selectors=selectors,
        ))

    def resolve_with_summaries(
        self,
        *,
        project_id: UUID,
        selectors: tuple[RecommendationEvidenceSelector, ...],
    ) -> tuple[tuple[EvidenceRef, str | None], ...]:
        if project_id != self._project_id:
            raise RecommendationPersistenceError(
                "Recommendation evidence resolver Project scope mismatch"
            )
        resolved: list[tuple[EvidenceRef, str | None]] = []
        try:
            for selector in selectors:
                row = self._connection.execute(
                    "SELECT geo_resolve_recommendation_evidence(%s, %s, %s) AS ref",
                    (project_id, selector.kind.value, selector.resource_id),
                ).fetchone()
                payload = _payload(row["ref"] if row is not None else None)
                if payload is None:
                    raise RecommendationSourceStale(
                        "Recommendation evidence selector is missing or outside the Project"
                    )
                reference = evidence_ref_from_payload(payload)
                if reference.identity != selector.identity or reference.project_id != project_id:
                    raise RecommendationSourceStale(
                        "Recommendation evidence resolver returned a mismatched identity"
                    )
                summary = payload.get("summary")
                if summary is not None and not isinstance(summary, str):
                    raise RecommendationSourceStale(
                        "Recommendation evidence summary is not text"
                    )
                normalized_summary = summary.strip() if summary else None
                summary_hash = payload.get("summary_hash")
                if normalized_summary is not None:
                    expected_hash = hashlib.sha256(normalized_summary.encode()).hexdigest()
                    if summary_hash != expected_hash:
                        raise RecommendationSourceStale(
                            "Recommendation evidence summary hash is inconsistent"
                        )
                resolved.append((reference, normalized_summary))
        except RecommendationSourceStale:
            raise
        except (RecommendationRuleViolation, TypeError, ValueError) as error:
            raise RecommendationSourceStale(
                "Recommendation evidence projection violated its typed contract"
            ) from error
        except psycopg.Error as error:
            raise RecommendationPersistenceError(
                "PostgreSQL could not resolve Recommendation evidence"
            ) from error
        return tuple(resolved)


class _CommonRef(TypedDict):
    project_id: UUID
    resource_id: str
    version: str
    sha256: str
    locator: dict[str, str]
    valid: bool


def evidence_ref_from_payload(value: Mapping[str, object]) -> EvidenceRef:
    kind = _text(value, "kind")
    common: _CommonRef = {
        "project_id": UUID(_text(value, "project_id")),
        "resource_id": _text(value, "resource_id"),
        "version": _text(value, "version"),
        "sha256": _text(value, "sha256"),
        "locator": _string_mapping(value, "locator"),
        "valid": _bool(value, "valid"),
    }
    if kind == "observation":
        return ObservationRef(
            **common,
            capture_method=_text(value, "capture_method"),
            evidence_class=ObservationEvidenceClass(_text(value, "evidence_class")),
            question_resource_id=_text(value, "question_resource_id"),
            surface_resource_id=_text(value, "surface_resource_id"),
            eligible=_bool(value, "eligible"),
        )
    if kind == "metric_comparison":
        return MetricComparisonRef(
            **common,
            observation_resource_ids=_strings(value, "observation_resource_ids"),
            method_version=_text(value, "method_version"),
            method_sha256=_text(value, "method_sha256"),
            sufficient_evidence=_bool(value, "sufficient_evidence"),
        )
    if kind == "fact":
        return FactRef(
            **common,
            approved=_bool(value, "approved"),
            retired=_bool(value, "retired"),
        )
    if kind == "rule":
        return RuleRef(**common, active=_bool(value, "active"))
    if kind == "prompt_release":
        return PromptReleaseRef(
            **common,
            approved=_bool(value, "approved"),
            frozen=_bool(value, "frozen"),
        )
    if kind == "model_call":
        return ModelCallRef(
            **common,
            prompt_release_resource_id=_text(value, "prompt_release_resource_id"),
            model_identity=_text(value, "model_identity"),
            succeeded=_bool(value, "succeeded"),
        )
    if kind == "content":
        return ContentRef(**common, current=_bool(value, "current"))
    if kind == "question":
        return QuestionRef(**common, active=_bool(value, "active"))
    if kind == "surface":
        return SurfaceRef(**common, active=_bool(value, "active"))
    if kind == "attribution":
        return AttributionRef(
            **common,
            available=_bool(value, "available"),
            reason=_text(value, "reason"),
        )
    raise RecommendationSourceStale("Recommendation evidence kind is unsupported")


def _payload(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise RecommendationSourceStale(
                "Recommendation evidence projection returned invalid JSON"
            ) from error
    if not isinstance(value, Mapping):
        raise RecommendationSourceStale(
            "Recommendation evidence projection returned a non-object"
        )
    return {str(key): item for key, item in value.items()}


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise RecommendationSourceStale(
            f"Recommendation evidence field {key} is missing"
        )
    return item.strip()


def _bool(value: Mapping[str, object], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise RecommendationSourceStale(
            f"Recommendation evidence field {key} is not boolean"
        )
    return item


def _strings(value: Mapping[str, object], key: str) -> tuple[str, ...]:
    item = value.get(key)
    if not isinstance(item, list) or not all(isinstance(entry, str) for entry in item):
        raise RecommendationSourceStale(
            f"Recommendation evidence field {key} is not a text list"
        )
    return tuple(entry for entry in item if entry.strip())


def _string_mapping(value: Mapping[str, object], key: str) -> dict[str, str]:
    item = value.get(key)
    if not isinstance(item, Mapping) or not all(
        isinstance(name, str) and isinstance(entry, str)
        for name, entry in item.items()
    ):
        raise RecommendationSourceStale(
            f"Recommendation evidence field {key} is not a text object"
        )
    return {str(name): str(entry) for name, entry in item.items()}


__all__ = [
    "PostgresRecommendationEvidenceResolver",
    "evidence_ref_from_payload",
]
