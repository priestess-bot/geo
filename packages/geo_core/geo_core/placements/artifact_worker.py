"""Pending placement artifact finalization against S3-compatible storage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from uuid import UUID

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.placements.domain import canonical_hash, canonical_json_bytes


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((item.name for item in cursor.description), value, strict=True))


@dataclass(frozen=True)
class PendingArtifact:
    project_id: UUID
    job_id: UUID
    resource_kind: str
    resource_id: UUID
    storage_key: str
    content_hash: str
    content: bytes


class ArtifactObjectStore(Protocol):
    def put_object(
        self, *, key: str, content: bytes, content_type: str, expected_hash: str
    ) -> object: ...


class PlacementArtifactRepository:
    def __init__(self, store: PostgresDurableJobStore) -> None:
        self._store = store

    def load(self, lease: WorkerLease) -> PendingArtifact:
        with self._store.fenced_transaction(lease) as connection:
            record = _row(
                connection.execute(
                    """SELECT resource_kind, resource_id, storage_key, content_hash
                       FROM artifact_finalize_outbox
                       WHERE job_id = %s AND project_id = %s
                         AND status IN ('pending', 'finalizing', 'failed')""",
                    (lease.job_id, lease.project_id),
                )
            )
            if record is None:
                raise RuntimeError("pending artifact does not exist")
            connection.execute(
                """UPDATE artifact_finalize_outbox
                   SET status = 'finalizing', attempt_count = attempt_count + 1,
                       last_error = NULL
                   WHERE job_id = %s AND project_id = %s""",
                (lease.job_id, lease.project_id),
            )
            if record["resource_kind"] == "prompt_bundle":
                source = _row(
                    connection.execute(
                        """SELECT input_snapshot AS payload FROM prompt_bundles
                           WHERE id = %s AND project_id = %s""",
                        (record["resource_id"], lease.project_id),
                    )
                )
            elif record["resource_kind"] == "package_export":
                source = _row(
                    connection.execute(
                        """SELECT manifest AS payload FROM placement_export_receipts
                           WHERE id = %s AND project_id = %s""",
                        (record["resource_id"], lease.project_id),
                    )
                )
            elif record["resource_kind"] == "prompt_simulation":
                source = _row(
                    connection.execute(
                        """SELECT artifact_manifest AS payload
                           FROM prompt_simulation_results
                           WHERE simulation_id = %s AND project_id = %s""",
                        (record["resource_id"], lease.project_id),
                    )
                )
            else:
                raise RuntimeError("pending artifact resource kind is unsupported")
            if source is None:
                raise RuntimeError("pending artifact source does not exist")
            payload = source["payload"]
            if canonical_hash(payload) != record["content_hash"]:
                raise RuntimeError("pending artifact hash does not match its frozen source")
            content = canonical_json_bytes(payload)
            return PendingArtifact(
                lease.project_id,
                lease.job_id,
                record["resource_kind"],
                record["resource_id"],
                record["storage_key"],
                record["content_hash"],
                content,
            )

    def finalize(self, lease: WorkerLease, artifact: PendingArtifact, stored: object) -> None:
        uri = str(getattr(stored, "uri"))
        content_hash = str(getattr(stored, "content_hash"))
        if content_hash != artifact.content_hash:
            raise RuntimeError("stored artifact hash does not match the pending artifact")
        with self._store.fenced_transaction(lease) as connection:
            changed = connection.execute(
                """UPDATE artifact_finalize_outbox
                   SET status = 'finalized', final_uri = %s,
                       finalized_at = clock_timestamp(), last_error = NULL
                   WHERE job_id = %s AND project_id = %s AND status = 'finalizing'""",
                (uri, lease.job_id, lease.project_id),
            ).rowcount
            if changed != 1:
                raise RuntimeError("artifact finalization lost its pending record")
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"artifact:{artifact.resource_kind}:{artifact.resource_id}",
                details={
                    "resource_kind": artifact.resource_kind,
                    "resource_id": str(artifact.resource_id),
                    "content_hash": artifact.content_hash,
                    "storage_uri": uri,
                },
            )

    def mark_failure(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        error: str,
        terminal: bool,
    ) -> None:
        connection = self._store.open_project(project_id)
        try:
            connection.execute(
                """UPDATE artifact_finalize_outbox
                   SET status = %s, last_error = %s
                   WHERE job_id = %s AND project_id = %s""",
                ("failed" if terminal else "pending", error[:2000], job_id, project_id),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
