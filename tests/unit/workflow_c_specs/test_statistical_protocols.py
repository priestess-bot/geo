from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from geo_core.workflow_c_statistical_protocols import (
    ComparisonPlanDefinition,
    DriftProtocolDefinition,
    StatisticalProtocolError,
    StatisticalProtocolKind,
    new_statistical_protocol,
    parse_statistical_protocol_definition,
)


def comparison_plan() -> ComparisonPlanDefinition:
    return ComparisonPlanDefinition(
        family="primary-family",
        question_clusters=("purchase", "research"),
        alpha=Decimal("0.05"),
        delta=Decimal("0.05"),
        target_power=Decimal("0.80"),
        precision=Decimal("0.10"),
        min_pairs=3,
        power_plan_hash="a" * 64,
        a_priori_design_power=Decimal("0.90"),
        bootstrap_iterations=500,
    )


def test_comparison_plan_round_trips_canonical_definition() -> None:
    definition = comparison_plan()

    parsed = parse_statistical_protocol_definition(definition.canonical_value())

    assert parsed == definition
    assert parsed.kind is StatisticalProtocolKind.COMPARISON_PLAN
    assert parsed.definition_hash == definition.definition_hash
    assert parsed.canonical_value()["question_clusters"] == ["purchase", "research"]


def test_drift_protocol_round_trips_canonical_definition() -> None:
    definition = DriftProtocolDefinition(minimum_question_count=3)

    parsed = parse_statistical_protocol_definition(definition.canonical_value())

    assert parsed == definition
    assert parsed.kind is StatisticalProtocolKind.DRIFT_PROTOCOL


def test_statistical_protocol_identity_is_idempotent_and_kind_scoped() -> None:
    from uuid import UUID

    project_id = UUID("86000000-0000-4000-8000-000000000001")
    now = datetime(2026, 7, 24, tzinfo=UTC)
    first = new_statistical_protocol(
        project_id=project_id,
        definition=comparison_plan(),
        actor_id="maker",
        idempotency_key="statistical:create:1",
        occurred_at=now,
    )
    replay = new_statistical_protocol(
        project_id=project_id,
        definition=comparison_plan(),
        actor_id="maker",
        idempotency_key="statistical:create:1",
        occurred_at=now,
    )
    drift = new_statistical_protocol(
        project_id=project_id,
        definition=DriftProtocolDefinition(minimum_question_count=3),
        actor_id="maker",
        idempotency_key="statistical:create:1",
        occurred_at=now,
    )

    assert replay.id == first.id
    assert drift.id != first.id


@pytest.mark.parametrize(
    "change, message",
    [
        ({"correction_method": "none"}, "correction"),
        ({"target_power": Decimal("0.79")}, "target power"),
        ({"minimum_completion_ratio": Decimal("0.79")}, "completion ratio"),
        ({"question_clusters": ()}, "question clusters"),
    ],
)
def test_comparison_plan_rejects_unfrozen_or_weak_methods(
    change: dict[str, object], message: str
) -> None:
    values = {
        "family": "primary-family",
        "question_clusters": ("purchase",),
        "alpha": Decimal("0.05"),
        "delta": Decimal("0.05"),
        "target_power": Decimal("0.80"),
        "precision": Decimal("0.10"),
        "min_pairs": 3,
        "power_plan_hash": "a" * 64,
        "a_priori_design_power": Decimal("0.90"),
        "bootstrap_iterations": 500,
    }
    values.update(change)

    with pytest.raises(StatisticalProtocolError, match=message):
        ComparisonPlanDefinition(**values)  # type: ignore[arg-type]


def test_parser_rejects_unknown_definition_fields() -> None:
    value = comparison_plan().canonical_value() | {"runtime_threshold": "0.1"}

    with pytest.raises(StatisticalProtocolError, match="fields"):
        parse_statistical_protocol_definition(value)
