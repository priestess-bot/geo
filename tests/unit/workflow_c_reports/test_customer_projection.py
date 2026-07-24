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
        "approved_safe_payload": {"headline": "Approved result", "metrics": [1, 2]},
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


def test_customer_projection_rejects_raw_or_debug_payload_recursively() -> None:
    with pytest.raises(WorkflowCCustomerProjectionError, match="internal field"):
        _report(approved_safe_payload={"summary": {"raw_response": "no"}})
    with pytest.raises(WorkflowCCustomerProjectionError, match="internal field"):
        _report(approved_safe_payload={"summary": {"rawResponse": "no"}})


def test_customer_projection_requires_immutable_hashes_and_aware_approval_time() -> None:
    with pytest.raises(WorkflowCCustomerProjectionError, match="hash is invalid"):
        _report(report_hash="invalid")
    with pytest.raises(WorkflowCCustomerProjectionError, match="timezone-aware"):
        _report(approved_at=datetime(2026, 7, 23, 10, 0))
