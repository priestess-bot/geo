"""Published Dify snapshot persistence for the operator catalog."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from .errors import WorkflowConfigurationError
from .published import PublishedWorkflowSnapshot


def record_published_snapshot(
    connection: Any,
    *,
    project_id: UUID,
    release_id: UUID,
    snapshot: PublishedWorkflowSnapshot,
) -> UUID:
    try:
        release = _one(
            connection.execute(
                """SELECT purpose, dify_app_id,
                          registered_workflow_hash, registered_snapshot_hash
                   FROM dify_workflow_releases
                   WHERE id = %s AND project_id = %s""",
                (release_id, project_id),
            )
        )
        if release is None:
            raise WorkflowConfigurationError("Dify release was not found")
        if release["registered_workflow_hash"] is None:
            raise WorkflowConfigurationError(
                "legacy Dify release has no trusted published graph identity; "
                "re-enroll it before recording a snapshot",
                code="dify_release_requires_reenrollment",
            )
        if (
            release["purpose"] != snapshot.purpose
            or release["dify_app_id"] != snapshot.app_id
            or release["registered_workflow_hash"] != snapshot.workflow_hash
            or release["registered_snapshot_hash"] != snapshot.snapshot_hash
        ):
            raise WorkflowConfigurationError(
                "published Dify snapshot differs from its registered GEO Release; "
                "verify the console and enroll a new release",
                code="dify_registered_published_identity_changed",
            )
        snapshot_id = uuid4()
        inserted = _one(
            connection.execute(
                """INSERT INTO dify_workflow_published_snapshots (
                   id, project_id, release_id, purpose, dify_app_id,
                   dify_workflow_id, workflow_hash, snapshot_hash,
                   prompt_nodes, input_variables, graph_nodes,
                   published_at, observed_at
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s)
               ON CONFLICT (project_id, release_id, purpose,
                            dify_workflow_id, snapshot_hash) DO NOTHING
               RETURNING id""",
                (
                    snapshot_id,
                    project_id,
                    release_id,
                    snapshot.purpose,
                    snapshot.app_id,
                    snapshot.workflow_id,
                    snapshot.workflow_hash,
                    snapshot.snapshot_hash,
                    Jsonb(list(snapshot.prompt_nodes)),
                    Jsonb(list(snapshot.input_variables)),
                    Jsonb(list(snapshot.graph_nodes)),
                    snapshot.published_at,
                    snapshot.observed_at,
                ),
            )
        )
        if inserted is None:
            inserted = _one(
                connection.execute(
                    """SELECT id FROM dify_workflow_published_snapshots
                       WHERE project_id = %s AND release_id = %s AND purpose = %s
                         AND dify_workflow_id = %s AND snapshot_hash = %s""",
                    (
                        project_id,
                        release_id,
                        snapshot.purpose,
                        snapshot.workflow_id,
                        snapshot.snapshot_hash,
                    ),
                )
            )
        if inserted is None:
            raise WorkflowConfigurationError("Dify snapshot could not be persisted")
        connection.commit()
        return inserted["id"]
    except BaseException:
        connection.rollback()
        raise


def _one(cursor: Any) -> Mapping[str, Any] | None:
    row = cursor.fetchone()
    return dict(row) if row is not None else None
