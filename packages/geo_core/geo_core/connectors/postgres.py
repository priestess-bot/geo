"""Project-scoped PostgreSQL persistence for Connector Core."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from geo_core.connectors.contracts import ConnectorSyncCommit, ConnectorSyncPlan
from geo_core.project_scope import set_project_scope


class ConnectorPersistenceError(RuntimeError):
    """Connector persistence rejected stale or inconsistent state."""


@dataclass(frozen=True)
class PersistedSyncRun:
    id: UUID
    version: int
    status: str
    replayed: bool


@dataclass(frozen=True)
class PersistedSyncResult:
    run_id: UUID
    raw_artifact_id: UUID
    schema_version_id: UUID
    projection_batch_id: UUID
    checkpoint_id: UUID
    checkpoint_version: int
    checkpoint_hash: str
    freshness_id: UUID


class PostgresConnectorRepository:
    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def create_sync_run(self, plan: ConnectorSyncPlan, *, run_id: UUID) -> PersistedSyncRun:
        if run_id.int == 0:
            raise ConnectorPersistenceError("sync run ID is invalid")
        with self._connect() as connection:
            set_project_scope(connection, plan.project_id)
            existing = connection.execute(
                """SELECT id, version, status
                     FROM connector_sync_runs
                    WHERE project_id = %s AND idempotency_key = %s""",
                (plan.project_id, plan.idempotency_key),
            ).fetchone()
            if existing is not None:
                return PersistedSyncRun(
                    id=existing["id"],
                    version=existing["version"],
                    status=existing["status"],
                    replayed=True,
                )
            row = connection.execute(
                """INSERT INTO connector_sync_runs(
                       id, project_id, definition_id, connection_id, scope_id,
                       input_checkpoint_id, input_checkpoint_hash, mode,
                       window_start, window_end, adapter_release, idempotency_key,
                       status, version, requested_by, requested_at
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       'planned', 1, %s, %s
                   ) RETURNING id, version, status""",
                (
                    run_id,
                    plan.project_id,
                    plan.definition_id,
                    plan.connection_id,
                    plan.scope_id,
                    plan.input_checkpoint_id,
                    plan.input_checkpoint_hash,
                    plan.mode.value,
                    plan.window_start,
                    plan.window_end,
                    plan.adapter_release,
                    plan.idempotency_key,
                    plan.requested_by,
                    plan.requested_at,
                ),
            ).fetchone()
            if row is None:
                raise ConnectorPersistenceError("sync run was not persisted")
            return PersistedSyncRun(
                id=row["id"], version=row["version"], status=row["status"], replayed=False
            )

    def mark_running(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        expected_version: int,
        started_at: datetime,
    ) -> PersistedSyncRun:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """UPDATE connector_sync_runs
                      SET status = 'running', version = version + 1, started_at = %s
                    WHERE project_id = %s AND id = %s
                      AND status IN ('planned', 'queued') AND version = %s
                RETURNING id, version, status""",
                (started_at, project_id, run_id, expected_version),
            ).fetchone()
            if row is None:
                raise ConnectorPersistenceError("sync run start lost optimistic ownership")
            return PersistedSyncRun(
                id=row["id"], version=row["version"], status=row["status"], replayed=False
            )

    def commit_success(
        self,
        commit: ConnectorSyncCommit,
        *,
        finished_at: datetime,
        connection: Any | None = None,
    ) -> PersistedSyncResult:
        ids = {
            "artifact": uuid4(),
            "schema": uuid4(),
            "projection": uuid4(),
            "checkpoint": uuid4(),
            "freshness": uuid4(),
        }
        context = self._connect() if connection is None else nullcontext(connection)
        with context as active_connection:
            set_project_scope(active_connection, commit.project_id)
            run = active_connection.execute(
                """SELECT * FROM connector_sync_runs
                    WHERE project_id = %s AND id = %s
                    FOR UPDATE""",
                (commit.project_id, commit.run_id),
            ).fetchone()
            if run is None:
                raise ConnectorPersistenceError("sync run was not found")
            if run["status"] == "succeeded":
                return self._load_result(active_connection, commit.project_id, commit.run_id)
            if run["status"] != "running" or run["version"] != commit.expected_run_version:
                raise ConnectorPersistenceError("sync run commit lost optimistic ownership")
            if run["input_checkpoint_hash"] != commit.expected_checkpoint_hash:
                raise ConnectorPersistenceError("sync run input checkpoint changed")
            self._assert_current_checkpoint(
                active_connection, run, commit.expected_checkpoint_hash
            )

            artifact_id = ids["artifact"]
            active_connection.execute(
                """INSERT INTO connector_raw_artifacts(
                       id, project_id, sync_run_id, manifest_uri, manifest_hash,
                       content_hash, schema_fingerprint, record_count, byte_size,
                       classification, retention_until, encryption_key_reference,
                       producer_commit, created_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    artifact_id,
                    commit.project_id,
                    commit.run_id,
                    commit.artifact.manifest_uri,
                    commit.artifact.manifest_hash,
                    commit.artifact.content_hash,
                    commit.artifact.schema_fingerprint,
                    commit.artifact.record_count,
                    commit.artifact.byte_size,
                    commit.artifact.classification,
                    commit.artifact.retention_until,
                    commit.artifact.encryption_key_reference,
                    commit.artifact.producer_commit,
                    finished_at,
                ),
            )
            schema_id = self._upsert_schema(
                active_connection, run, commit, ids["schema"], finished_at
            )
            projection_id = ids["projection"]
            active_connection.execute(
                """INSERT INTO connector_projection_batches(
                       id, project_id, sync_run_id, raw_artifact_id, schema_version_id,
                       projection_kind, row_count, dataset_hash, lineage, created_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    projection_id,
                    commit.project_id,
                    commit.run_id,
                    artifact_id,
                    schema_id,
                    commit.projection_kind,
                    commit.projection_row_count,
                    commit.projection_dataset_hash,
                    Jsonb(dict(commit.projection_lineage)),
                    finished_at,
                ),
            )
            self._insert_projection_rows(
                active_connection,
                project_id=commit.project_id,
                projection_id=projection_id,
                projection_kind=commit.projection_kind,
                records=commit.projection_records,
            )
            current_version = self._current_checkpoint_version(active_connection, run)
            checkpoint_id = ids["checkpoint"]
            checkpoint_version = current_version + 1
            active_connection.execute(
                """INSERT INTO connector_checkpoints(
                       id, project_id, connection_id, scope_id, version, cursor_state,
                       watermark, state_hash, advanced_by_run_id, created_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    checkpoint_id,
                    commit.project_id,
                    run["connection_id"],
                    run["scope_id"],
                    checkpoint_version,
                    Jsonb(dict(commit.next_cursor_state)),
                    commit.next_watermark,
                    commit.next_checkpoint_hash,
                    commit.run_id,
                    finished_at,
                ),
            )
            freshness_id = ids["freshness"]
            active_connection.execute(
                """INSERT INTO connector_freshness(
                       id, project_id, connection_id, scope_id, sync_run_id,
                       expected_watermark, observed_watermark, lag_seconds,
                       status, reason, observed_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    freshness_id,
                    commit.project_id,
                    run["connection_id"],
                    run["scope_id"],
                    commit.run_id,
                    commit.expected_watermark,
                    commit.next_watermark,
                    commit.lag_seconds,
                    commit.freshness_status.value,
                    commit.freshness_reason,
                    finished_at,
                ),
            )
            updated = active_connection.execute(
                """UPDATE connector_sync_runs
                      SET status = 'succeeded', version = version + 1, finished_at = %s
                    WHERE project_id = %s AND id = %s AND status = 'running'
                      AND version = %s
                RETURNING id""",
                (
                    finished_at,
                    commit.project_id,
                    commit.run_id,
                    commit.expected_run_version,
                ),
            ).fetchone()
            if updated is None:
                raise ConnectorPersistenceError("sync run terminal write was fenced")
            return PersistedSyncResult(
                run_id=commit.run_id,
                raw_artifact_id=artifact_id,
                schema_version_id=schema_id,
                projection_batch_id=projection_id,
                checkpoint_id=checkpoint_id,
                checkpoint_version=checkpoint_version,
                checkpoint_hash=commit.next_checkpoint_hash,
                freshness_id=freshness_id,
            )

    @staticmethod
    def _insert_projection_rows(
        connection: Any,
        *,
        project_id: UUID,
        projection_id: UUID,
        projection_kind: str,
        records: Sequence[Mapping[str, object]],
    ) -> None:
        if projection_kind == "gsc.search_analytics.v1":
            for index, value in enumerate(records):
                row = dict(value)
                connection.execute(
                    """INSERT INTO connector_gsc_projection_rows(
                           project_id, projection_batch_id, row_index, stream,
                           observed_date, query, page, country, device,
                           clicks, impressions, ctr, position, row_data, row_hash
                       ) VALUES (%s, %s, %s, %s, %s::date, %s, %s, %s, %s,
                                 %s, %s, %s, %s, %s, %s)""",
                    (
                        project_id,
                        projection_id,
                        index,
                        row.get("_geo_stream", "unknown"),
                        _date_value(row.get("date")),
                        row.get("query"),
                        row.get("page"),
                        row.get("country"),
                        row.get("device"),
                        _number(row.get("clicks")),
                        _number(row.get("impressions")),
                        _number(row.get("ctr")),
                        _number(row.get("position")),
                        Jsonb(row),
                        _row_hash(row),
                    ),
                )
            return
        if projection_kind == "ga4.aggregate_report.v1":
            for index, value in enumerate(records):
                row = dict(value)
                connection.execute(
                    """INSERT INTO connector_ga4_projection_rows(
                           project_id, projection_batch_id, row_index, observed_date,
                           dimensions, metrics, row_data, row_hash
                       ) VALUES (%s, %s, %s, %s::date, %s, %s, %s, %s)""",
                    (
                        project_id,
                        projection_id,
                        index,
                        _date_value(row.get("date")),
                        Jsonb(_dimension_values(row)),
                        Jsonb(_metric_values(row)),
                        Jsonb(row),
                        _row_hash(row),
                    ),
                )
            return
        raise ConnectorPersistenceError("projection kind has no typed row writer")

    @staticmethod
    def _assert_current_checkpoint(connection: Any, run: Any, expected_hash: str) -> None:
        row = connection.execute(
            """SELECT id, state_hash
                 FROM connector_checkpoints
                WHERE project_id = %s AND connection_id = %s AND scope_id = %s
                ORDER BY version DESC LIMIT 1 FOR UPDATE""",
            (run["project_id"], run["connection_id"], run["scope_id"]),
        ).fetchone()
        if run["input_checkpoint_id"] is None:
            if row is not None:
                raise ConnectorPersistenceError("initial sync no longer owns an empty checkpoint")
            return
        if (
            row is None
            or row["id"] != run["input_checkpoint_id"]
            or row["state_hash"] != expected_hash
        ):
            raise ConnectorPersistenceError("sync run checkpoint is stale")

    @staticmethod
    def _current_checkpoint_version(connection: Any, run: Any) -> int:
        row = connection.execute(
            """SELECT COALESCE(max(version), 0) AS version
                 FROM connector_checkpoints
                WHERE project_id = %s AND connection_id = %s AND scope_id = %s""",
            (run["project_id"], run["connection_id"], run["scope_id"]),
        ).fetchone()
        return int(row["version"])

    @staticmethod
    def _upsert_schema(
        connection: Any,
        run: Any,
        commit: ConnectorSyncCommit,
        proposed_id: UUID,
        created_at: datetime,
    ) -> UUID:
        existing = connection.execute(
            """SELECT id, schema_hash
                 FROM connector_schema_versions
                WHERE project_id = %s AND definition_id = %s
                  AND source_fingerprint = %s""",
            (commit.project_id, run["definition_id"], commit.artifact.schema_fingerprint),
        ).fetchone()
        if existing is not None:
            if existing["schema_hash"] != commit.schema_hash:
                raise ConnectorPersistenceError("source schema fingerprint changed meaning")
            return existing["id"]
        connection.execute(
            """INSERT INTO connector_schema_versions(
                   id, project_id, definition_id, source_fingerprint,
                   schema_document, schema_hash, compatibility, diff_summary, created_at
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                proposed_id,
                commit.project_id,
                run["definition_id"],
                commit.artifact.schema_fingerprint,
                Jsonb(dict(commit.schema_document)),
                commit.schema_hash,
                commit.compatibility.value,
                Jsonb(dict(commit.schema_diff)),
                created_at,
            ),
        )
        return proposed_id

    @staticmethod
    def _load_result(connection: Any, project_id: UUID, run_id: UUID) -> PersistedSyncResult:
        row = connection.execute(
            """SELECT raw.id AS raw_artifact_id, schema.id AS schema_version_id,
                      batch.id AS projection_batch_id, checkpoint.id AS checkpoint_id,
                      checkpoint.version AS checkpoint_version,
                      checkpoint.state_hash AS checkpoint_hash,
                      freshness.id AS freshness_id
                 FROM connector_sync_runs run
                 JOIN connector_raw_artifacts raw
                   ON raw.project_id = run.project_id AND raw.sync_run_id = run.id
                 JOIN connector_projection_batches batch
                   ON batch.project_id = run.project_id AND batch.sync_run_id = run.id
                 JOIN connector_schema_versions schema
                   ON schema.project_id = run.project_id AND schema.id = batch.schema_version_id
                 JOIN connector_checkpoints checkpoint
                   ON checkpoint.project_id = run.project_id
                  AND checkpoint.advanced_by_run_id = run.id
                 JOIN connector_freshness freshness
                   ON freshness.project_id = run.project_id AND freshness.sync_run_id = run.id
                WHERE run.project_id = %s AND run.id = %s""",
            (project_id, run_id),
        ).fetchone()
        if row is None:
            raise ConnectorPersistenceError("successful sync result lineage is incomplete")
        return PersistedSyncResult(run_id=run_id, **dict(row))


def _date_value(value: object) -> str:
    if not isinstance(value, str) or len(value) < 10:
        raise ConnectorPersistenceError("projection row date is missing")
    return value[:10]


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ConnectorPersistenceError("projection numeric value is invalid")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ConnectorPersistenceError("projection numeric value is invalid") from error


def _row_hash(row: Mapping[str, object]) -> str:
    from geo_core.connectors.contracts import canonical_hash

    return canonical_hash(row)


def _metric_values(row: Mapping[str, object]) -> dict[str, object]:
    explicit = row.get("metric_values") or row.get("metrics")
    if isinstance(explicit, Mapping):
        return dict(explicit)
    return {
        key: value
        for key, value in row.items()
        if key not in {"_geo_stream", "date", "dimension_values", "dimensions"}
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    }


def _dimension_values(row: Mapping[str, object]) -> dict[str, object]:
    explicit = row.get("dimension_values") or row.get("dimensions")
    if isinstance(explicit, Mapping):
        return dict(explicit)
    return {"date": row.get("date")}


__all__ = [
    "ConnectorPersistenceError",
    "PersistedSyncResult",
    "PersistedSyncRun",
    "PostgresConnectorRepository",
]
