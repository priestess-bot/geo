"""Fenced PostgreSQL lifecycle adapter for Recommendation task artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
from typing import Any
from uuid import UUID

import psycopg

from geo_core.recommendations.artifact_maintenance import (
    RecommendationArtifactDeletionLease,
    RecommendationArtifactDeletionPhase,
)
from geo_core.recommendations.generation_artifact_contracts import (
    RecommendationTaskArtifactDeletionTarget,
    RecommendationTaskArtifactRef,
)
from geo_core.recommendations.generation_artifact_serialization import canonical_bytes


class PostgresRecommendationArtifactDeletionRepository:
    """Use lifecycle SQL functions so each deletion transition is fenced."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        lease_seconds: int = 120,
        retry_delay: timedelta = timedelta(seconds=60),
    ) -> None:
        if not 30 <= lease_seconds <= 3600:
            raise ValueError("Recommendation artifact deletion lease is out of bounds")
        if not timedelta(seconds=1) <= retry_delay <= timedelta(days=1):
            raise ValueError("Recommendation artifact deletion retry delay is out of bounds")
        self._connect = connection_factory
        self._lease_seconds = lease_seconds
        self._retry_delay = retry_delay

    def enqueue_due(self, *, project_id: UUID, now: datetime) -> None:
        """Create idempotent expiry intents before claiming any deletion work."""

        _require_aware(now)
        self._call(
            "SELECT geo_enqueue_recommendation_artifact_maintenance(%s, %s)",
            (project_id, now),
        )

    def claim(
        self,
        *,
        project_id: UUID,
        worker_id: str,
        now: datetime,
        limit: int,
    ) -> tuple[RecommendationArtifactDeletionLease, ...]:
        if not worker_id.strip() or not 1 <= limit <= 1000:
            raise ValueError("Recommendation artifact deletion claim is invalid")
        _require_aware(now)
        rows = self._rows(
            """SELECT claim.*, task.task_artifact_byte_size
               FROM geo_claim_recommendation_artifact_deletion(
                   %s, %s, %s, %s, %s
               ) AS claim
               JOIN recommendation_model_tasks AS task
                 ON task.project_id = claim.project_id
                AND task.child_job_id = claim.child_job_id""",
            (project_id, worker_id, now, self._lease_seconds, limit),
        )
        return tuple(_lease(row) for row in rows)

    def mark_crypto_erased(
        self,
        lease: RecommendationArtifactDeletionLease,
        *,
        receipt_hash: str,
        erased_at: datetime,
    ) -> RecommendationArtifactDeletionLease:
        _require_aware(erased_at)
        self._call(
            """SELECT geo_mark_recommendation_artifact_crypto_erased(
                   %s, %s, %s, %s, %s
               )""",
            (
                lease.intent_id,
                lease.lease_token,
                lease.fencing_generation,
                receipt_hash,
                erased_at,
            ),
        )
        return replace(lease, phase=RecommendationArtifactDeletionPhase.CRYPTO_ERASED)

    def mark_deleted(
        self,
        lease: RecommendationArtifactDeletionLease,
        *,
        receipt_hash: str,
        deleted_at: datetime,
    ) -> None:
        _require_aware(deleted_at)
        self._call(
            """SELECT geo_mark_recommendation_artifact_deleted(
                   %s, %s, %s, %s, %s
               )""",
            (
                lease.intent_id,
                lease.lease_token,
                lease.fencing_generation,
                receipt_hash,
                deleted_at,
            ),
        )

    def retry(
        self,
        lease: RecommendationArtifactDeletionLease,
        *,
        error_code: str,
        failed_at: datetime,
    ) -> None:
        _require_aware(failed_at)
        self._call(
            """SELECT geo_retry_recommendation_artifact_deletion(
                   %s, %s, %s, %s, %s
               )""",
            (
                lease.intent_id,
                lease.lease_token,
                lease.fencing_generation,
                error_code,
                failed_at + self._retry_delay,
            ),
        )

    def _call(
        self,
        statement: str,
        values: tuple[object, ...],
        *,
        optional: bool = False,
    ) -> Mapping[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(statement, values).fetchone()
            connection.commit()
            if row is None and not optional:
                raise RuntimeError("Recommendation artifact lifecycle returned no row")
            return row
        except psycopg.Error as error:
            connection.rollback()
            raise RuntimeError(
                "Recommendation artifact lifecycle PostgreSQL transition failed"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _rows(
        self, statement: str, values: tuple[object, ...]
    ) -> tuple[Mapping[str, Any], ...]:
        connection = self._connect()
        try:
            rows = tuple(connection.execute(statement, values).fetchall())
            connection.commit()
            return rows
        except psycopg.Error as error:
            connection.rollback()
            raise RuntimeError(
                "Recommendation artifact lifecycle PostgreSQL claim failed"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _lease(row: Mapping[str, Any]) -> RecommendationArtifactDeletionLease:
    project_id = _uuid(row, "project_id")
    child_job_id = _uuid(row, "child_job_id")
    manifest_uri = _text(row, "manifest_uri")
    manifest_hash = _text(row, "manifest_hash")
    payload_uri = _text(row, "payload_uri")
    payload_hash = _text(row, "payload_hash")
    content_hash = _text(row, "content_hash")
    expires_at = _datetime(row, "expires_at")
    byte_size = _integer(row, "task_artifact_byte_size")
    target = RecommendationTaskArtifactDeletionTarget(
        reference=RecommendationTaskArtifactRef(
            uri=manifest_uri,
            manifest_hash=manifest_hash,
            payload_uri=payload_uri,
            payload_hash=payload_hash,
            content_hash=content_hash,
            byte_size=byte_size,
        ),
        payload_uri=payload_uri,
        payload_hash=payload_hash,
        expires_at=expires_at,
        tombstone_hash=_tombstone_hash(
            project_id=project_id,
            child_job_id=child_job_id,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            payload_uri=payload_uri,
            payload_hash=payload_hash,
            content_hash=content_hash,
            expires_at=expires_at,
        ),
    )
    return RecommendationArtifactDeletionLease(
        intent_id=_uuid(row, "id"),
        project_id=project_id,
        parent_job_id=_uuid(row, "parent_job_id"),
        child_job_id=child_job_id,
        lease_token=_uuid(row, "lease_token"),
        fencing_generation=_integer(row, "fencing_generation"),
        attempt_count=_integer(row, "attempt_count"),
        phase=RecommendationArtifactDeletionPhase(str(row["phase"])),
        target=target,
    )


def _tombstone_hash(
    *,
    project_id: UUID,
    child_job_id: UUID,
    manifest_uri: str,
    manifest_hash: str,
    payload_uri: str,
    payload_hash: str,
    content_hash: str,
    expires_at: datetime,
) -> str:
    return hashlib.sha256(
        canonical_bytes(
            {
                "schema_version": 1,
                "project_id": str(project_id),
                "child_job_id": str(child_job_id),
                "manifest_uri": manifest_uri,
                "manifest_hash": manifest_hash,
                "payload_uri": payload_uri,
                "payload_hash": payload_hash,
                "content_hash": content_hash,
                "expires_at": expires_at.isoformat(),
            }
        )
    ).hexdigest()


def _text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Recommendation artifact lifecycle field {key} is invalid")
    return value


def _uuid(row: Mapping[str, Any], key: str) -> UUID:
    value = row.get(key)
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            f"Recommendation artifact lifecycle field {key} is not a UUID"
        ) from error


def _integer(row: Mapping[str, Any], key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(f"Recommendation artifact lifecycle field {key} is invalid")
    return value


def _datetime(row: Mapping[str, Any], key: str) -> datetime:
    value = row.get(key)
    if not isinstance(value, datetime):
        raise RuntimeError(f"Recommendation artifact lifecycle field {key} is invalid")
    _require_aware(value)
    return value


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Recommendation artifact lifecycle timestamps must be timezone-aware")


__all__ = ["PostgresRecommendationArtifactDeletionRepository"]
