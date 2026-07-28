from __future__ import annotations

import hashlib
from uuid import UUID

import pytest

from geo_core.recommendations import (
    AttributionRef,
    FactRef,
    MetricComparisonRef,
    MetricComparisonConclusion,
    PromptReleaseRef,
    RecommendationEvidenceKind,
    RecommendationEvidenceSelector,
    RecommendationPersistenceError,
    RecommendationRuleKind,
    RecommendationRuleSeverity,
    RecommendationRuleTriggerStatus,
    RecommendationSourceStale,
    RuleRef,
)
from geo_core.recommendations.postgres.evidence import (
    PostgresRecommendationEvidenceResolver,
)


PROJECT_ID = UUID("70000000-0000-0000-0000-000000000007")


class ConnectionStub:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.params = None

    def execute(self, query: str, params: object):
        assert "geo_resolve_recommendation_evidence" in query
        self.params = params
        return self

    def fetchone(self):
        return {"ref": self.payload}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _common(resource_id: str) -> dict[str, object]:
    return {
        "project_id": str(PROJECT_ID),
        "resource_id": resource_id,
        "version": "v1",
        "sha256": _digest(resource_id),
        "locator": {"source_id": resource_id},
        "valid": True,
        "summary": None,
    }


def test_postgres_evidence_resolver_uses_project_function_and_validates_summary() -> None:
    summary = "Approved AU product fact"
    connection = ConnectionStub(
        {
            "kind": "fact",
            "project_id": str(PROJECT_ID),
            "resource_id": "fact:1",
            "version": "v4",
            "sha256": _digest("fact:v4"),
            "locator": {"fact_id": "fact:1"},
            "valid": True,
            "approved": True,
            "retired": False,
            "summary": summary,
            "summary_hash": _digest(summary),
        }
    )
    resolver = PostgresRecommendationEvidenceResolver(connection, PROJECT_ID)
    selector = RecommendationEvidenceSelector(
        RecommendationEvidenceKind.FACT, "fact:1"
    )

    resolved = resolver.resolve_with_summaries(
        project_id=PROJECT_ID,
        selectors=(selector,),
    )

    assert resolved == (
        (
            FactRef(
                project_id=PROJECT_ID,
                resource_id="fact:1",
                version="v4",
                sha256=_digest("fact:v4"),
                locator={"fact_id": "fact:1"},
                valid=True,
                approved=True,
                retired=False,
            ),
            summary,
        ),
    )
    assert connection.params == (PROJECT_ID, "fact", "fact:1")


def test_postgres_evidence_resolver_fails_closed_for_missing_tampered_or_cross_project() -> None:
    selector = RecommendationEvidenceSelector(
        RecommendationEvidenceKind.FACT, "fact:1"
    )
    missing = PostgresRecommendationEvidenceResolver(ConnectionStub(None), PROJECT_ID)
    with pytest.raises(RecommendationSourceStale):
        missing.resolve_current(project_id=PROJECT_ID, selectors=(selector,))

    tampered = PostgresRecommendationEvidenceResolver(
        ConnectionStub(
            {
                "kind": "fact",
                "project_id": str(PROJECT_ID),
                "resource_id": "fact:1",
                "version": "v1",
                "sha256": _digest("fact"),
                "locator": {"fact_id": "fact:1"},
                "valid": True,
                "approved": True,
                "retired": False,
                "summary": "current",
                "summary_hash": _digest("different"),
            }
        ),
        PROJECT_ID,
    )
    with pytest.raises(RecommendationSourceStale, match="summary hash"):
        tampered.resolve_current(project_id=PROJECT_ID, selectors=(selector,))

    with pytest.raises(RecommendationPersistenceError, match="scope mismatch"):
        missing.resolve_current(project_id=UUID(int=8), selectors=(selector,))


@pytest.mark.parametrize(
    ("kind", "payload", "expected"),
    [
        (
            RecommendationEvidenceKind.METRIC_COMPARISON,
            {
                **_common("metric:1"),
                "kind": "metric_comparison",
                "observation_resource_ids": ["observation:1"],
                "method_version": "paired-bootstrap-v1",
                "method_sha256": _digest("method"),
                "sufficient_evidence": True,
                "conclusion": "inconclusive",
            },
            MetricComparisonRef,
        ),
        (
            RecommendationEvidenceKind.RULE,
            {
                **_common("rule:1"),
                "kind": "rule",
                "active": True,
                "rule_kind": "negative_question",
                "severity": "warning",
                "trigger_status": "acknowledged",
            },
            RuleRef,
        ),
        (
            RecommendationEvidenceKind.PROMPT_RELEASE,
            {
                **_common("prompt:1"),
                "kind": "prompt_release",
                "approved": True,
                "frozen": True,
            },
            PromptReleaseRef,
        ),
        (
            RecommendationEvidenceKind.ATTRIBUTION,
            {
                **_common("attribution:unavailable"),
                "kind": "attribution",
                "valid": False,
                "available": False,
                "reason": "connector_attribution_excluded_from_this_phase",
            },
            AttributionRef,
        ),
    ],
)
def test_postgres_evidence_resolver_preserves_typed_and_explicitly_unavailable_sources(
    kind: RecommendationEvidenceKind,
    payload: dict[str, object],
    expected: type[object],
) -> None:
    resource_id = str(payload["resource_id"])
    resolver = PostgresRecommendationEvidenceResolver(ConnectionStub(payload), PROJECT_ID)

    resolved = resolver.resolve_current(
        project_id=PROJECT_ID,
        selectors=(RecommendationEvidenceSelector(kind, resource_id),),
    )

    assert len(resolved) == 1
    assert isinstance(resolved[0], expected)
    assert resolved[0].identity == (kind.value, resource_id)
    if isinstance(resolved[0], AttributionRef):
        assert not resolved[0].available
        assert not resolved[0].current_and_valid
    if isinstance(resolved[0], MetricComparisonRef):
        assert resolved[0].conclusion is MetricComparisonConclusion.INCONCLUSIVE
    if isinstance(resolved[0], RuleRef):
        assert resolved[0].kind is RecommendationRuleKind.NEGATIVE_QUESTION
        assert resolved[0].severity is RecommendationRuleSeverity.WARNING
        assert resolved[0].trigger_status is RecommendationRuleTriggerStatus.ACKNOWLEDGED
        assert resolved[0].triggered


def test_postgres_evidence_parser_keeps_pre_admission_payloads_conservative() -> None:
    legacy_metric = {
        **_common("metric:legacy"),
        "kind": "metric_comparison",
        "observation_resource_ids": ["observation:1"],
        "method_version": "paired-bootstrap-v1",
        "method_sha256": _digest("method"),
        "sufficient_evidence": True,
    }
    legacy_rule = {
        **_common("rule:legacy"),
        "kind": "rule",
        "active": True,
    }

    metric = PostgresRecommendationEvidenceResolver(
        ConnectionStub(legacy_metric), PROJECT_ID
    ).resolve_current(
        project_id=PROJECT_ID,
        selectors=(
            RecommendationEvidenceSelector(
                RecommendationEvidenceKind.METRIC_COMPARISON,
                "metric:legacy",
            ),
        ),
    )[0]
    rule = PostgresRecommendationEvidenceResolver(
        ConnectionStub(legacy_rule), PROJECT_ID
    ).resolve_current(
        project_id=PROJECT_ID,
        selectors=(
            RecommendationEvidenceSelector(
                RecommendationEvidenceKind.RULE,
                "rule:legacy",
            ),
        ),
    )[0]

    assert isinstance(metric, MetricComparisonRef)
    assert metric.conclusion is MetricComparisonConclusion.INCONCLUSIVE
    assert isinstance(rule, RuleRef)
    assert rule.kind is RecommendationRuleKind.THRESHOLD
    assert rule.severity is RecommendationRuleSeverity.INFO
    assert rule.trigger_status is RecommendationRuleTriggerStatus.NOT_TRIGGERED
    assert not rule.triggered
