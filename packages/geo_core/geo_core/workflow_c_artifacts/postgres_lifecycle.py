"""Atomic PostgreSQL commands for Workflow C artifact lifecycle maintenance."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg

from geo_core.project_scope import set_project_scope
from geo_core.sampling.contracts import SamplingRuleViolation
from geo_core.workflow_c_artifacts.lifecycle import (
    WorkflowCArtifactDeletionLease,
    WorkflowCArtifactDeletionReason,
)


class PostgresWorkflowCArtifactLifecycleRepository:
    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def claim_deletion(
        self,
        *,
        project_id: UUID,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> WorkflowCArtifactDeletionLease | None:
        _require_aware(now)
        try:
            with self._connect() as connection:
                set_project_scope(connection, project_id)
                row = connection.execute(
                    """SELECT *
                         FROM geo_claim_workflow_c_artifact_deletion(%s, %s, %s, %s)""",
                    (project_id, worker_id, now, lease_seconds),
                ).fetchone()
        except psycopg.Error as exc:
            raise SamplingRuleViolation("Workflow C artifact deletion claim failed") from exc
        lease = None if row is None else _lease(row)
        if lease is not None and lease.project_id != project_id:
            raise SamplingRuleViolation(
                "Workflow C artifact deletion claim escaped its Project scope"
            )
        return lease

    def crypto_erase_deletion(
        self,
        lease: WorkflowCArtifactDeletionLease,
        *,
        erased_at: datetime,
    ) -> bool:
        """Fence and receipt DEK erasure before any remote delete is attempted."""

        _require_aware(erased_at)
        try:
            with self._connect() as connection:
                set_project_scope(connection, lease.project_id)
                row = connection.execute(
                    """SELECT *
                         FROM geo_crypto_erase_workflow_c_artifact_deletion(
                           %s, %s, %s, %s
                         )""",
                    (
                        lease.queue_id,
                        lease.lease_token,
                        lease.fencing_generation,
                        erased_at,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise SamplingRuleViolation(
                "Workflow C artifact crypto-erasure was not fenced"
            ) from exc
        if row is None or row["queue_id"] != lease.queue_id:
            raise SamplingRuleViolation("Workflow C artifact crypto-erasure identity changed")
        if not bool(row["key_destroyed"]):
            raise SamplingRuleViolation(
                "Workflow C artifact crypto-erasure did not persist its receipt"
            )
        return bool(row["newly_destroyed"])

    def record_deletion_attempt(
        self,
        lease: WorkflowCArtifactDeletionLease,
        *,
        object_deleted: bool,
        key_destroyed: bool,
        error_code: str | None,
        attempted_at: datetime,
        retry_not_before: datetime | None,
    ) -> str:
        _require_aware(attempted_at)
        if retry_not_before is not None:
            _require_aware(retry_not_before)
        try:
            with self._connect() as connection:
                set_project_scope(connection, lease.project_id)
                row = connection.execute(
                    """SELECT *
                         FROM geo_record_workflow_c_artifact_deletion_attempt(
                           %s, %s, %s, %s, %s, %s, %s, %s
                         )""",
                    (
                        lease.queue_id,
                        lease.lease_token,
                        lease.fencing_generation,
                        object_deleted,
                        key_destroyed,
                        error_code,
                        attempted_at,
                        retry_not_before,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise SamplingRuleViolation(
                "Workflow C artifact deletion outcome was not fenced"
            ) from exc
        if row is None or row["queue_id"] != lease.queue_id:
            raise SamplingRuleViolation("Workflow C artifact deletion outcome identity changed")
        return str(row["status"])


def _lease(row: Mapping[str, Any]) -> WorkflowCArtifactDeletionLease:
    return WorkflowCArtifactDeletionLease(
        queue_id=row["queue_id"],
        project_id=row["project_id"],
        artifact_id=row["artifact_id"],
        key_reference=row["key_ref"],
        payload_uri=str(row["payload_uri"]),
        payload_hash=str(row["payload_hash"]),
        manifest_uri=str(row["manifest_uri"]),
        manifest_hash=str(row["manifest_hash"]),
        reason=WorkflowCArtifactDeletionReason(str(row["reason"])),
        lease_token=row["lease_token"],
        fencing_generation=int(row["fencing_generation"]),
        attempt_count=int(row["attempt_count"]),
        object_deleted=bool(row["object_deleted"]),
        key_destroyed=bool(row["key_destroyed"]),
    )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SamplingRuleViolation("Workflow C artifact lifecycle time must be timezone-aware")


__all__ = ["PostgresWorkflowCArtifactLifecycleRepository"]
