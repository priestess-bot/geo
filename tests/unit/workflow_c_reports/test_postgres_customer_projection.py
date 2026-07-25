from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Literal
from uuid import uuid4

import pytest

from geo_core.workflow_c_reports import (
    AdvanceWorkflowCReportSnapshot,
    CreateWorkflowCReportSnapshot,
    PostgresWorkflowCApprovedReportSnapshots,
    WorkflowCReportApprovalError,
    WorkflowCReportConflict,
)


NOW = datetime(2026, 7, 23, 9, 30, tzinfo=UTC)
HASH = "a" * 64
REPORT_HASH = "b" * 64


def test_customer_reader_uses_only_latest_approved_snapshot_version() -> None:
    command = _draft()
    connection = _Connection(source=_source(command))
    repository = PostgresWorkflowCApprovedReportSnapshots(lambda: connection)

    draft = repository.create_draft(command)
    review = repository.advance(_advance(draft, "in_review"))
    approved = repository.advance(_advance(review, "approved"))

    reports = repository.list_approved_reports(
        project_id=command.project_id,
        campaign_id=command.campaign_id,
    )

    assert approved.status == "approved"
    assert reports[0].id == command.report_id
    assert reports[0].report_hash == REPORT_HASH
    query = next(query for query in connection.queries if "WITH latest AS" in query)
    assert "latest.status = 'approved'" in query
    assert "report.status" not in query
    assert "NOT metric.test_only AND NOT metric.synthetic" in query
    assert "'manual_ui'" not in query


def test_approval_rechecks_semantic_evidence_at_the_approval_transition() -> None:
    command = _draft()
    source = _source(command)
    connection = _Connection(source=source)
    repository = PostgresWorkflowCApprovedReportSnapshots(lambda: connection)
    review = repository.advance(_advance(repository.create_draft(command), "in_review"))
    source["evidence_status"] = "insufficient_evidence"

    with pytest.raises(WorkflowCReportApprovalError, match="insufficient-evidence"):
        repository.advance(_advance(review, "approved"))

    assert [row["status"] for row in connection.versions] == ["draft", "in_review"]


def test_stale_latest_version_immediately_hides_an_earlier_approved_snapshot() -> None:
    command = _draft()
    connection = _Connection(source=_source(command))
    repository = PostgresWorkflowCApprovedReportSnapshots(lambda: connection)
    approved = repository.advance(
        _advance(repository.advance(_advance(repository.create_draft(command), "in_review")), "approved")
    )
    stale = repository.advance(_advance(approved, "stale", reason="source_changed"))

    assert stale.status == "stale"
    assert repository.list_approved_reports(
        project_id=command.project_id, campaign_id=command.campaign_id
    ) == ()


def test_customer_reader_fails_closed_for_a_hash_valid_unknown_payload_field() -> None:
    command = _draft()
    connection = _Connection(source=_source(command))
    repository = PostgresWorkflowCApprovedReportSnapshots(lambda: connection)
    approved = repository.advance(
        _advance(repository.advance(_advance(repository.create_draft(command), "in_review")), "approved")
    )
    payload = {"headline": "Approved evidence", "access_token": "must-not-cross"}
    connection.versions[-1]["approved_safe_payload"] = payload
    connection.versions[-1]["approved_safe_payload_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    with pytest.raises(WorkflowCReportApprovalError, match="Customer report row is invalid"):
        repository.list_approved_reports(
            project_id=approved.project_id,
            campaign_id=approved.campaign_id,
        )


def test_snapshot_lifecycle_rejects_skipping_review_before_approval() -> None:
    command = _draft()
    connection = _Connection(source=_source(command))
    repository = PostgresWorkflowCApprovedReportSnapshots(lambda: connection)
    draft = repository.create_draft(command)

    with pytest.raises(WorkflowCReportApprovalError, match="status transition"):
        repository.advance(_advance(draft, "approved"))


def test_persistent_receipts_replay_exact_versions_and_reject_key_reuse() -> None:
    command = _draft()
    connection = _Connection(source=_source(command))
    repository = PostgresWorkflowCApprovedReportSnapshots(lambda: connection)
    draft = repository.create_draft(command)
    submit_command = _advance(draft, "in_review", idempotency_key="report:submit:lost")
    submitted = repository.advance(submit_command)
    approved = repository.advance(_advance(submitted, "approved"))

    replayed_draft = repository.create_draft(
        replace(command, occurred_at=NOW + timedelta(minutes=5))
    )
    replayed_submit = repository.advance(
        replace(submit_command, occurred_at=NOW + timedelta(minutes=5))
    )

    assert approved.version == 3
    assert replayed_draft == draft
    assert replayed_submit == submitted
    assert len(connection.receipts) == 3

    with pytest.raises(WorkflowCReportConflict, match="different input or resource"):
        repository.advance(replace(submit_command, expected_version=2))
    with pytest.raises(WorkflowCReportConflict, match="different input or resource"):
        repository.advance(replace(submit_command, report_id=uuid4()))


def _draft() -> CreateWorkflowCReportSnapshot:
    return CreateWorkflowCReportSnapshot(
        report_id=uuid4(),
        project_id=uuid4(),
        campaign_id=uuid4(),
        monitoring_report_id=uuid4(),
        monitoring_report_hash=REPORT_HASH,
        semantic_snapshot_hash=HASH,
        source_kind="provider_api",
        approved_safe_payload={"headline": "Approved evidence", "metrics": {"mention": "0.8"}},
        actor_id=uuid4(),
        occurred_at=NOW,
        idempotency_key="report:create",
    )


def _advance(
    version,
    status: Literal["in_review", "approved", "stale", "superseded", "revoked"],
    *,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> AdvanceWorkflowCReportSnapshot:
    return AdvanceWorkflowCReportSnapshot(
        report_id=version.report_id,
        project_id=version.project_id,
        expected_version=version.version,
        status=status,
        actor_id=uuid4(),
        occurred_at=NOW,
        idempotency_key=idempotency_key or f"report:{status}:{uuid4()}",
        reason=reason,
    )


def _source(command: CreateWorkflowCReportSnapshot) -> dict[str, object]:
    return {
        "project_id": command.project_id,
        "campaign_id": command.campaign_id,
        "report_hash": REPORT_HASH,
        "evidence_status": "complete",
        "test_only": False,
        "synthetic": False,
        "metric_approved_at": NOW,
        "capture_method": "provider_api",
    }


class _Cursor:
    def __init__(self, *, row: dict[str, object] | None = None, rows: list[dict[str, object]] | None = None) -> None:
        self._row = row
        self._rows = rows or []

    def fetchone(self) -> dict[str, object] | None:
        return self._row

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _Connection:
    def __init__(self, *, source: dict[str, object]) -> None:
        self.source = source
        self.versions: list[dict[str, object]] = []
        self.receipts: list[dict[str, object]] = []
        self.queries: list[str] = []

    def execute(self, query: str, params: object = None) -> _Cursor:
        self.queries.append(query)
        if "WITH latest AS" in query:
            latest = self.versions[-1] if self.versions else None
            if latest is None or latest["status"] != "approved":
                return _Cursor(rows=[])
            return _Cursor(
                rows=[
                    {
                        "id": latest["report_id"],
                        "project_id": latest["project_id"],
                        "campaign_id": latest["campaign_id"],
                        "semantic_snapshot_hash": latest["semantic_snapshot_hash"],
                        "monitoring_report_hash": latest["monitoring_report_hash"],
                        "source_kind": latest["source_kind"],
                        "approved_safe_payload": latest["approved_safe_payload"],
                        "approved_safe_payload_hash": latest["approved_safe_payload_hash"],
                        "approved_at": latest["occurred_at"],
                    }
                ]
            )
        if "FROM monitoring_reports AS report" in query:
            return _Cursor(row=dict(self.source))
        if "FROM workflow_c_report_command_receipts" in query:
            assert isinstance(params, tuple)
            project_id, command_scope, key_hash = params
            receipt = next(
                (
                    item
                    for item in self.receipts
                    if item["project_id"] == project_id
                    and item["command_scope"] == command_scope
                    and item["idempotency_key_hash"] == key_hash
                ),
                None,
            )
            return _Cursor(row=dict(receipt) if receipt is not None else None)
        if "INSERT INTO workflow_c_report_command_receipts" in query:
            assert isinstance(params, tuple)
            self.receipts.append(
                {
                    "project_id": params[0],
                    "report_id": params[1],
                    "command_scope": params[2],
                    "idempotency_key_hash": params[3],
                    "input_hash": params[4],
                    "result_version": params[5],
                    "result_version_hash": params[6],
                    "created_at": params[7],
                }
            )
            return _Cursor()
        if "FROM workflow_c_report_snapshot_versions" in query:
            if "AND version = %s" in query:
                assert isinstance(params, tuple)
                row = next(
                    (
                        item
                        for item in self.versions
                        if item["project_id"] == params[0]
                        and item["report_id"] == params[1]
                        and item["version"] == params[2]
                    ),
                    None,
                )
                return _Cursor(row=dict(row) if row is not None else None)
            return _Cursor(row=dict(self.versions[-1]) if self.versions else None)
        if "INSERT INTO workflow_c_report_snapshot_versions" in query:
            assert isinstance(params, tuple)
            if "'draft'" in query:
                self.versions.append(
                    {
                        "project_id": params[0], "report_id": params[1], "version": 1,
                        "status": "draft", "campaign_id": params[2],
                        "monitoring_report_id": params[3], "monitoring_report_hash": params[4],
                        "semantic_snapshot_hash": params[5], "source_kind": params[6],
                        "approved_safe_payload": json.loads(params[7]),
                        "approved_safe_payload_hash": params[8], "version_hash": params[9],
                        "actor_id": params[10], "reason": None, "occurred_at": params[11],
                    }
                )
            else:
                self.versions.append(
                    {
                        "project_id": params[0], "report_id": params[1], "version": params[2],
                        "status": params[3], "campaign_id": params[4],
                        "monitoring_report_id": params[5], "monitoring_report_hash": params[6],
                        "semantic_snapshot_hash": params[7], "source_kind": params[8],
                        "approved_safe_payload": json.loads(params[9]),
                        "approved_safe_payload_hash": params[10], "version_hash": params[11],
                        "actor_id": params[12], "reason": params[13], "occurred_at": params[14],
                    }
                )
            return _Cursor()
        return _Cursor()

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass
