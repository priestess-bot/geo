"""Small Admin control plane for Connector definitions, scopes, and syncs."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from psycopg import Error as PsycopgError
from psycopg.types.json import Jsonb

from geo_core.connectors.contracts import (
    ConnectorKind,
    ConnectorSyncMode,
    ConnectorSyncPlan,
    canonical_hash,
)
from geo_core.connectors.jobs import PostgresConnectorJobRepository
from geo_core.connectors.postgres import PostgresConnectorRepository
from geo_core.connectors.pyairbyte_source import (
    GA4_CONNECTOR_RELEASE,
    GSC_CONNECTOR_RELEASE,
    PYAIRBYTE_RELEASE,
    release_fingerprint,
)
from geo_core.connectors.scope import (
    ConnectorScopeError,
    connector_secret_purpose,
    validate_google_scope,
)
from geo_core.project_scope import set_project_scope


class ConnectorAdminError(RuntimeError):
    """Admin command is invalid, stale, or references unavailable state."""


_RELEASES: dict[ConnectorKind, tuple[str, str, tuple[str, ...]]] = {
    ConnectorKind.GOOGLE_SEARCH_CONSOLE: (
        "source-google-search-console",
        GSC_CONNECTOR_RELEASE,
        ("search_analytics_by_date", "search_analytics_by_page"),
    ),
    ConnectorKind.GOOGLE_ANALYTICS_4: (
        "source-google-analytics-data-api",
        GA4_CONNECTOR_RELEASE,
        ("reports",),
    ),
}
CONNECTOR_CONNECTION_TEST_NAMESPACE = UUID("fcf3f917-b90e-5398-a39d-e9c5630d15b3")

class ConnectorAdminService:
    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._clock = clock
        self._runs = PostgresConnectorRepository(connect=connect)
        self._jobs = PostgresConnectorJobRepository(connect=connect)

    def install_definition(
        self, *, project_id: UUID, actor_id: UUID, kind: ConnectorKind
    ) -> Mapping[str, object]:
        if kind not in _RELEASES:
            raise ConnectorAdminError("Only GSC and GA4 PyAirbyte definitions are installable")
        source, release, streams = _RELEASES[kind]
        definition_id = uuid4()
        now = self._clock()
        schema = {"type": "object", "additionalProperties": True}
        capability = {
            "modes": [mode.value for mode in ConnectorSyncMode],
            "streams": list(streams),
            "raw_first": True,
        }
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """INSERT INTO connector_definitions(
                       id, project_id, kind, adapter_release, runtime_release,
                       capability, config_schema, config_schema_hash, release_hash,
                       status, created_by, created_at
                   )
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s)
                   ON CONFLICT (project_id, kind, adapter_release) DO UPDATE
                       SET adapter_release = EXCLUDED.adapter_release
                   RETURNING id, kind, adapter_release, runtime_release, status,
                             created_by, created_at, approved_by, approved_at""",
                (
                    definition_id,
                    project_id,
                    kind.value,
                    f"{source}:{release}",
                    f"pyairbyte:{PYAIRBYTE_RELEASE}",
                    Jsonb(capability),
                    Jsonb(schema),
                    canonical_hash(schema),
                    release_fingerprint(source, release),
                    actor_id,
                    now,
                ),
            ).fetchone()
        return dict(row)

    def approve_definition(
        self, *, project_id: UUID, definition_id: UUID, reviewer_id: UUID
    ) -> Mapping[str, object]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """UPDATE connector_definitions
                      SET status = 'approved', approved_by = %s, approved_at = %s
                    WHERE project_id = %s AND id = %s AND status = 'draft'
                      AND created_by <> %s
                RETURNING id, kind, adapter_release, runtime_release, status,
                          created_by, created_at, approved_by, approved_at""",
                (
                    reviewer_id,
                    self._clock(),
                    project_id,
                    definition_id,
                    reviewer_id,
                ),
            ).fetchone()
        if row is None:
            raise ConnectorAdminError(
                "Definition is missing, already decided, or requires a different reviewer"
            )
        return dict(row)

    def create_connection(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        definition_id: UUID,
        name: str,
        secret_reference_id: UUID,
        secret_version: int,
        # Kept for direct callers during the API migration. HTTP clients no
        # longer send this internal value; when present it is checked against
        # the definition-derived purpose and never trusted as the source.
        secret_purpose: str | None = None,
    ) -> Mapping[str, object]:
        if not name.strip():
            raise ConnectorAdminError("Connection name is required")
        connection_id, now = uuid4(), self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            definition = connection.execute(
                """SELECT kind
                     FROM connector_definitions
                    WHERE project_id = %s AND id = %s AND status = 'approved'""",
                (project_id, definition_id),
            ).fetchone()
            if definition is None:
                raise ConnectorAdminError("Approved Connector definition was not found")
            try:
                expected_purpose = connector_secret_purpose(ConnectorKind(definition["kind"]))
            except (ConnectorScopeError, KeyError, ValueError) as error:
                raise ConnectorAdminError("Approved Connector definition has no supported Secret purpose") from error
            if secret_purpose is not None and secret_purpose != expected_purpose:
                raise ConnectorAdminError("Secret purpose is derived from the selected Connector definition")
            row = connection.execute(
                """INSERT INTO connector_connections(
                       id, project_id, definition_id, name, secret_reference_id,
                       secret_purpose, secret_version, auth_summary, status,
                       created_by, created_at, updated_at
                   )
                     SELECT %s, %s, definition.id, %s, %s, %s, %s,
                          jsonb_build_object('secret_reference_id', %s::text,
                                             'secret_version', %s),
                          'active', %s, %s, %s
                     FROM connector_definitions definition
                    WHERE definition.project_id = %s AND definition.id = %s
                      AND definition.status = 'approved'
                RETURNING id, definition_id, name, secret_reference_id,
                          secret_purpose, secret_version, status, version, created_at""",
                (
                    connection_id,
                    project_id,
                    name.strip(),
                    secret_reference_id,
                    expected_purpose,
                    secret_version,
                    secret_reference_id,
                    secret_version,
                    actor_id,
                    now,
                    now,
                    project_id,
                    definition_id,
                ),
            ).fetchone()
        if row is None:
            raise ConnectorAdminError("Approved Connector definition was not found")
        return dict(row)

    def create_scope(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        connection_id: UUID,
        source_locator: str,
        streams: Sequence[str],
        locale: str,
        report_spec: Mapping[str, object],
        date_policy: Mapping[str, object],
    ) -> Mapping[str, object]:
        if not source_locator.strip() or not locale.strip() or not streams:
            raise ConnectorAdminError("Source locator, locale, and streams are required")
        scope_value = {
            "source_locator": source_locator.strip(),
            "streams": list(streams),
            "locale": locale.strip(),
            "report_spec": dict(report_spec),
            "date_policy": dict(date_policy),
        }
        scope_id, now = uuid4(), self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            definition = connection.execute(
                """SELECT definition.kind, definition.capability
                     FROM connector_connections connection
                     JOIN connector_definitions definition
                       ON definition.project_id = connection.project_id
                      AND definition.id = connection.definition_id
                    WHERE connection.project_id = %s AND connection.id = %s
                      AND connection.status = 'active' AND definition.status = 'approved'""",
                (project_id, connection_id),
            ).fetchone()
            if definition is None:
                raise ConnectorAdminError("Active approved Connector connection was not found")
            allowed = set(definition["capability"]["streams"])
            if set(streams) != allowed:
                raise ConnectorAdminError("Scope streams differ from the approved definition")
            try:
                identity = validate_google_scope(
                    kind=ConnectorKind(definition["kind"]),
                    source_locator=source_locator,
                    streams=streams,
                    report_spec=report_spec,
                    date_policy=date_policy,
                )
            except (ConnectorScopeError, ValueError) as error:
                raise ConnectorAdminError(str(error)) from error
            scope_value["source_locator"] = identity.source_locator
            row = connection.execute(
                """INSERT INTO connector_scopes(
                       id, project_id, connection_id, source_locator, streams,
                       report_spec, locale, date_policy, scope_hash, status,
                       created_by, created_at
                   )
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s)
                   ON CONFLICT (project_id, connection_id, scope_hash) DO UPDATE
                       SET scope_hash = EXCLUDED.scope_hash
                   RETURNING id, connection_id, source_locator, streams, report_spec,
                             locale, date_policy, scope_hash, status, version, created_at""",
                (
                    scope_id,
                    project_id,
                    connection_id,
                    identity.source_locator,
                    Jsonb(list(streams)),
                    Jsonb(dict(report_spec)),
                    locale.strip(),
                    Jsonb(dict(date_policy)),
                    canonical_hash(scope_value),
                    actor_id,
                    now,
                ),
            ).fetchone()
        return dict(row)

    def set_connection_status(
        self,
        *,
        project_id: UUID,
        connection_id: UUID,
        status: str,
        expected_version: int,
    ) -> Mapping[str, object]:
        if status not in {"active", "disabled"}:
            raise ConnectorAdminError("Connection status must be active or disabled")
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """UPDATE connector_connections
                      SET status = %s, version = version + 1, updated_at = %s
                    WHERE project_id = %s AND id = %s AND version = %s
                      AND status IN ('active', 'disabled')
                RETURNING id, definition_id, name, secret_reference_id,
                          secret_purpose, secret_version, status, version, created_at""",
                (
                    status,
                    self._clock(),
                    project_id,
                    connection_id,
                    expected_version,
                ),
            ).fetchone()
        if row is None:
            raise ConnectorAdminError(
                "Connection is missing, revoked, or changed since it was loaded"
            )
        return dict(row)

    def rotate_connection_secret(
        self,
        *,
        project_id: UUID,
        connection_id: UUID,
        secret_version: int,
        expected_version: int,
    ) -> Mapping[str, object]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """UPDATE connector_connections AS target
                      SET secret_version = secret.version,
                          auth_summary = jsonb_build_object(
                              'secret_reference_id', target.secret_reference_id::text,
                              'secret_version', secret.version
                          ),
                          tested_at = NULL, test_classification = NULL,
                          version = target.version + 1, updated_at = %s
                     FROM secret_versions AS secret
                    WHERE target.project_id = %s AND target.id = %s
                      AND target.version = %s AND target.status <> 'revoked'
                      AND secret.reference_id = target.secret_reference_id
                      AND secret.project_id = target.project_id
                      AND secret.purpose = target.secret_purpose
                      AND secret.version = %s AND secret.status = 'active'
                RETURNING target.id, target.definition_id, target.name,
                          target.secret_reference_id, target.secret_purpose,
                          target.secret_version, target.status, target.version,
                          target.created_at""",
                (
                    self._clock(),
                    project_id,
                    connection_id,
                    expected_version,
                    secret_version,
                ),
            ).fetchone()
        if row is None:
            raise ConnectorAdminError(
                "Connection changed or the requested exact Secret version is not active"
            )
        return dict(row)

    def test_connection(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        connection_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> Mapping[str, object]:
        key = idempotency_key.strip()
        if not key or len(key) > 240 or expected_version < 1:
            raise ConnectorAdminError(
                "Connection test needs an idempotency key and current Connection version"
            )
        test_id = uuid5(CONNECTOR_CONNECTION_TEST_NAMESPACE, f"{project_id}:{key}")
        try:
            with self._connect() as connection:
                set_project_scope(connection, project_id)
                row = connection.execute(
                    """SELECT * FROM geo_enqueue_connector_connection_test(
                           %s, %s, %s, %s, %s, %s
                       )""",
                    (
                        project_id, test_id, connection_id, expected_version,
                        actor_id, self._clock(),
                    ),
                ).fetchone()
        except PsycopgError as error:
            reason = str(error).splitlines()[0].strip()
            raise ConnectorAdminError(
                reason or "Connector connection test admission failed"
            ) from error
        if row is None:
            raise ConnectorAdminError("Connector connection test returned no result")
        return dict(row)

    def cancel_sync(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        expected_version: int,
    ) -> Mapping[str, object]:
        now = self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            run = connection.execute(
                """SELECT id, durable_job_id, status, version
                     FROM connector_sync_runs
                    WHERE project_id = %s AND id = %s FOR UPDATE""",
                (project_id, run_id),
            ).fetchone()
            if run is None or run["version"] != expected_version:
                raise ConnectorAdminError("Connector Sync Run changed since it was loaded")
            if run["status"] in {"succeeded", "failed", "cancelled"}:
                raise ConnectorAdminError("Terminal Connector Sync Run cannot be cancelled")
            if run["durable_job_id"] is None:
                raise ConnectorAdminError("Connector Sync Run has no Durable Job")
            job = connection.execute(
                """SELECT status FROM durable_jobs
                    WHERE project_id = %s AND id = %s FOR UPDATE""",
                (project_id, run["durable_job_id"]),
            ).fetchone()
            if job is None:
                raise ConnectorAdminError("Connector Durable Job was not found")
            if job["status"] in {"queued", "retry_wait"}:
                connection.execute(
                    """UPDATE durable_jobs
                          SET status = 'cancelled', cancel_requested_at = %s,
                              completed_at = %s, updated_at = %s
                        WHERE project_id = %s AND id = %s""",
                    (now, now, now, project_id, run["durable_job_id"]),
                )
                connection.execute(
                    """UPDATE connector_sync_runs
                          SET status = 'cancelled', finished_at = %s,
                              version = version + 1, error_class = 'operator_cancelled'
                        WHERE project_id = %s AND id = %s""",
                    (now, project_id, run_id),
                )
                disposition = "cancelled"
            elif job["status"] in {"running", "finalizing"}:
                connection.execute(
                    """UPDATE durable_jobs
                          SET cancel_requested_at = COALESCE(cancel_requested_at, %s),
                              updated_at = %s
                        WHERE project_id = %s AND id = %s""",
                    (now, now, project_id, run["durable_job_id"]),
                )
                disposition = "cancel_requested"
            else:
                raise ConnectorAdminError("Connector Durable Job is already terminal")
        return {
            "run_id": run_id,
            "job_id": run["durable_job_id"],
            "status": disposition,
        }

    def start_sync(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        scope_id: UUID,
        mode: ConnectorSyncMode,
        window_start: datetime | None,
        window_end: datetime | None,
    ) -> Mapping[str, object]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT scope.connection_id, connection.definition_id,
                          definition.adapter_release,
                          checkpoint.id AS checkpoint_id,
                          checkpoint.state_hash AS checkpoint_hash
                     FROM connector_scopes scope
                     JOIN connector_connections connection
                       ON connection.project_id = scope.project_id
                      AND connection.id = scope.connection_id
                     JOIN connector_definitions definition
                       ON definition.project_id = connection.project_id
                      AND definition.id = connection.definition_id
                     JOIN secret_versions secret
                       ON secret.reference_id = connection.secret_reference_id
                      AND secret.project_id = connection.project_id
                      AND secret.purpose = connection.secret_purpose
                      AND secret.version = connection.secret_version
                     LEFT JOIN LATERAL (
                         SELECT id, state_hash FROM connector_checkpoints
                          WHERE project_id = scope.project_id
                            AND connection_id = scope.connection_id AND scope_id = scope.id
                          ORDER BY version DESC LIMIT 1
                     ) checkpoint ON true
                    WHERE scope.project_id = %s AND scope.id = %s
                      AND scope.status = 'active' AND connection.status = 'active'
                      AND definition.status = 'approved' AND secret.status = 'active'""",
                (project_id, scope_id),
            ).fetchone()
        if row is None:
            raise ConnectorAdminError(
                "Active Connector Scope with an active exact Secret version was not found"
            )
        if mode is ConnectorSyncMode.INITIAL and row["checkpoint_id"] is not None:
            raise ConnectorAdminError("Initial sync cannot run after a checkpoint exists")
        if mode is ConnectorSyncMode.INCREMENTAL and row["checkpoint_id"] is None:
            raise ConnectorAdminError("Incremental sync requires a successful initial sync")
        plan = ConnectorSyncPlan(
            project_id=project_id,
            definition_id=row["definition_id"],
            connection_id=row["connection_id"],
            scope_id=scope_id,
            mode=mode,
            adapter_release=row["adapter_release"],
            input_checkpoint_id=row["checkpoint_id"],
            input_checkpoint_hash=row["checkpoint_hash"] or "0" * 64,
            window_start=window_start,
            window_end=window_end,
            requested_by=actor_id,
            requested_at=self._clock(),
        )
        persisted = self._runs.create_sync_run(plan, run_id=uuid4())
        enqueued = self._jobs.enqueue(
            plan=plan,
            run_id=persisted.id,
            expected_run_version=persisted.version,
        )
        return {
            "run_id": persisted.id,
            "job_id": enqueued.job_id,
            "status": "queued",
            "replayed": persisted.replayed or enqueued.replayed,
            "plan_hash": plan.plan_hash,
        }

    def inventory(self, *, project_id: UUID) -> Mapping[str, object]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            definitions = connection.execute(
                """SELECT id, kind, adapter_release, runtime_release, status,
                          created_by, created_at, approved_by, approved_at
                     FROM connector_definitions WHERE project_id = %s
                    ORDER BY created_at DESC, id DESC""",
                (project_id,),
            ).fetchall()
            connections = connection.execute(
                """SELECT id, definition_id, name, secret_reference_id,
                          secret_purpose, secret_version, status, version, created_at
                     FROM connector_connections WHERE project_id = %s
                    ORDER BY created_at DESC, id DESC""",
                (project_id,),
            ).fetchall()
            scopes = connection.execute(
                """SELECT id, connection_id, source_locator, streams, report_spec,
                          locale, date_policy, status, version, created_at
                     FROM connector_scopes WHERE project_id = %s
                    ORDER BY created_at DESC, id DESC""",
                (project_id,),
            ).fetchall()
            runs = connection.execute(
                """SELECT run.id, run.scope_id, run.mode, run.status, run.version,
                          run.durable_job_id, run.requested_at, run.started_at,
                          run.finished_at, run.error_class,
                          job.cancel_requested_at,
                          projection.id AS projection_batch_id,
                          checkpoint.id AS checkpoint_id,
                          freshness.status AS freshness_status,
                          freshness.reason AS freshness_reason,
                          projection.row_count AS projected_row_count
                     FROM connector_sync_runs run
                     LEFT JOIN connector_projection_batches projection
                       ON projection.project_id = run.project_id
                      AND projection.sync_run_id = run.id
                     LEFT JOIN connector_checkpoints checkpoint
                       ON checkpoint.project_id = run.project_id
                      AND checkpoint.advanced_by_run_id = run.id
                     LEFT JOIN connector_freshness freshness
                       ON freshness.project_id = run.project_id
                      AND freshness.sync_run_id = run.id
                     LEFT JOIN durable_jobs job
                       ON job.project_id = run.project_id
                      AND job.id = run.durable_job_id
                    WHERE run.project_id = %s
                    ORDER BY run.requested_at DESC, run.id DESC LIMIT 100""",
                (project_id,),
            ).fetchall()
            connection_tests = connection.execute(
                """SELECT id, connection_id, definition_id, durable_job_id,
                          adapter_release, secret_reference_id, secret_purpose,
                          secret_version, status, version, requested_by, requested_at,
                          started_at, finished_at, result_hash, error_class
                     FROM connector_connection_tests WHERE project_id = %s
                    ORDER BY requested_at DESC, id DESC LIMIT 100""",
                (project_id,),
            ).fetchall()
        return {
            "definitions": [dict(row) for row in definitions],
            "connections": [dict(row) for row in connections],
            "scopes": [dict(row) for row in scopes],
            "runs": [dict(row) for row in runs],
            "connection_tests": [dict(row) for row in connection_tests],
        }


__all__ = ["ConnectorAdminError", "ConnectorAdminService"]
