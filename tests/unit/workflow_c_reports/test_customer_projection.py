from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from geo_core.workflow_c_reports import (
    WorkflowCCustomerApprovedReport,
    WorkflowCCustomerProjectionError,
)


def _report(**changes: object) -> WorkflowCCustomerApprovedReport:
    values: dict[str, object] = {
        "id": UUID("cc400000-0000-0000-0000-000000000001"),
        "project_id": UUID("cc400000-0000-0000-0000-000000000002"),
        "campaign_id": UUID("cc400000-0000-0000-0000-000000000003"),
        "semantic_snapshot_hash": "a" * 64,
        "report_hash": "b" * 64,
        "source_kind": "provider_api",
        "approved_safe_payload": {
            "headline": "Approved result",
            "metrics": {"mention": "0.8"},
        },
        "approved_at": datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
    }
    values.update(changes)
    return WorkflowCCustomerApprovedReport(**values)  # type: ignore[arg-type]


def test_customer_projection_accepts_only_non_manual_real_source_kinds() -> None:
    assert _report(source_kind="automated_ui").source_kind == "automated_ui"
    assert _report(source_kind="proxy_grounded_api").source_kind == "proxy_grounded_api"

    for source_kind in ("manual_ui", "synthetic", "official_report_import"):
        with pytest.raises(WorkflowCCustomerProjectionError, match="automated or API"):
            _report(source_kind=source_kind)


@pytest.mark.parametrize("key", ["access_token", "raw_text", "system_prompt", "new_field"])
def test_customer_projection_rejects_every_unknown_top_level_field(key: str) -> None:
    with pytest.raises(WorkflowCCustomerProjectionError, match="unknown field"):
        _report(approved_safe_payload={"headline": "Result", key: "private"})


@pytest.mark.parametrize(
    "payload",
    [
        {"summary": {"raw_response": "no"}},
        {"metrics": {"mention": {"value": "0.8"}}},
        {"metrics": {"access_token": "1"}},
        {"metrics": ["0.8"]},
    ],
)
def test_customer_projection_rejects_nested_or_complex_values(payload: object) -> None:
    with pytest.raises(WorkflowCCustomerProjectionError):
        _report(approved_safe_payload=payload)


def test_customer_projection_normalizes_only_the_documented_compatibility_shape() -> None:
    report = _report(
        approved_safe_payload={
            "headline": "  Approved result  ",
            "summary": "Aggregate evidence",
            "methodology": "Observational comparison",
            "warnings": ["Small sample"],
            "mention_rate": 0.8,
            "recommendation_rate": "0.60",
            "metrics": {
                "sentiment": -0.2,
                "fact_accuracy": "1",
                "source_domain_diversity": 4,
                "source_type_diversity": "3",
            },
        }
    )

    assert dict(report.approved_safe_payload) == {
        "headline": "Approved result",
        "summary": "Aggregate evidence",
        "methodology": "Observational comparison",
        "warnings": ["Small sample"],
        "mention_rate": 0.8,
        "recommendation_rate": "0.60",
        "metrics": {
            "fact_accuracy": "1",
            "sentiment": -0.2,
            "source_domain_diversity": 4,
            "source_type_diversity": "3",
        },
    }


@pytest.mark.parametrize("value", ["01", "+1", "1e-2", "NaN", float("inf"), True])
def test_customer_projection_rejects_noncanonical_or_nonfinite_metric_values(
    value: object,
) -> None:
    with pytest.raises(WorkflowCCustomerProjectionError):
        _report(approved_safe_payload={"headline": "Result", "metrics": {"mention": value}})


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("source_domain_diversity", -1),
        ("source_type_diversity", "1.5"),
        ("sentiment", "-1.1"),
        ("competitor_relative_position", 1.1),
        ("fact_accuracy", "1.01"),
        ("mention", -0.01),
    ],
)
def test_customer_projection_rejects_metric_values_outside_kind_specific_ranges(
    key: str,
    value: object,
) -> None:
    with pytest.raises(WorkflowCCustomerProjectionError, match="allowed range"):
        _report(approved_safe_payload={"headline": "Result", "metrics": {key: value}})


@pytest.mark.parametrize(("key", "value"), [("mention_rate", 1.1), ("recommendation_rate", -0.1)])
def test_customer_projection_rejects_out_of_range_legacy_rates(
    key: str,
    value: object,
) -> None:
    with pytest.raises(WorkflowCCustomerProjectionError, match="must be a ratio"):
        _report(approved_safe_payload={"headline": "Result", key: value})


def test_customer_projection_requires_immutable_hashes_and_aware_approval_time() -> None:
    with pytest.raises(WorkflowCCustomerProjectionError, match="hash is invalid"):
        _report(report_hash="invalid")
    with pytest.raises(WorkflowCCustomerProjectionError, match="timezone-aware"):
        _report(approved_at=datetime(2026, 7, 23, 10, 0))
