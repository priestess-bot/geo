"""Fail-closed operator entry point for a scoped GSC or GA4 canary.

``check`` only reads Connector metadata and never calls Google.  ``test`` and
``sync`` enqueue the existing Durable Job contracts; the Connector Worker is
the only component that resolves the Secret Store reference and talks to
PyAirbyte.  Secret values are never accepted as command-line arguments.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime
import json
import os
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from geo_core.connectors import ConnectorKind, ConnectorSyncMode
from geo_core.connectors.admin import ConnectorAdminError, ConnectorAdminService
from geo_core.connectors.scope import ConnectorScopeError, validate_google_scope
from geo_core.project_scope import set_project_scope


class CanaryFailure(RuntimeError):
    def __init__(self, code: str, detail: str, *, exit_status: int = 2) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.exit_status = exit_status


def run(arguments: argparse.Namespace) -> int:
    kind = _kind(arguments.kind)
    database_url = _database_url(arguments.database_url)
    project_id = _uuid(arguments.project_id, "project_id")
    connection_id = _uuid(arguments.connection_id, "connection_id")
    scope_id = _uuid(arguments.scope_id, "scope_id")
    row = _load_scope(database_url, project_id, connection_id, scope_id, kind)
    secret_reference_id = _optional_uuid(arguments.secret_reference_id, "secret_reference_id")
    if secret_reference_id is not None and secret_reference_id != row["secret_reference_id"]:
        raise CanaryFailure(
            "GEO_CONNECTOR_SECRET_REFERENCE_MISMATCH",
            "the supplied Secret Reference ID does not match the Connection; reload inventory",
            exit_status=3,
        )
    identity = _validate_row(row, kind)
    if arguments.mode == "check":
        _emit(
            {
                "status": "ready_for_enqueue",
                "kind": kind.value,
                "project_id": str(project_id),
                "connection_id": str(connection_id),
                "scope_id": str(scope_id),
                "scope": identity.as_dict(),
                "secret_reference_present": True,
                "secret_version": row["secret_version"],
                "network_call": False,
            }
        )
        return 0

    actor_id = _uuid(arguments.actor_id, "actor_id")
    expected_version = arguments.expected_version
    if expected_version != row["connection_version"]:
        raise CanaryFailure(
            "GEO_CONNECTOR_STALE_CONNECTION",
            "expected_version does not match the active Connector Connection; reload inventory",
            exit_status=3,
        )
    service = ConnectorAdminService(
        connect=lambda: psycopg.connect(database_url, row_factory=dict_row)
    )
    try:
        if arguments.mode == "test":
            idempotency_key = arguments.idempotency_key.strip()
            if not idempotency_key:
                raise CanaryFailure(
                    "GEO_CONNECTOR_IDEMPOTENCY_REQUIRED",
                    "--idempotency-key is required for a connection test",
                )
            result = service.test_connection(
                project_id=project_id,
                actor_id=actor_id,
                connection_id=connection_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
        else:
            result = service.start_sync(
                project_id=project_id,
                actor_id=actor_id,
                scope_id=scope_id,
                mode=ConnectorSyncMode(arguments.sync_mode),
                window_start=_datetime(arguments.window_start, "window_start"),
                window_end=_datetime(arguments.window_end, "window_end"),
            )
    except ConnectorAdminError as error:
        raise CanaryFailure(
            "GEO_CONNECTOR_ADMISSION_FAILED",
            f"Connector admission failed: {error}. Check approval, active Secret version, and scope.",
            exit_status=4,
        ) from error
    _emit(
        {
            "status": "queued",
            "kind": kind.value,
            "scope": identity.as_dict(),
            "network_call": "worker_only",
            **{key: str(value) if isinstance(value, UUID) else value for key, value in result.items()},
        }
    )
    return 0


def _load_scope(
    database_url: str,
    project_id: UUID,
    connection_id: UUID,
    scope_id: UUID,
    kind: ConnectorKind,
) -> dict[str, Any]:
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT definition.kind, definition.status AS definition_status,
                          connection.status AS connection_status,
                          connection.version AS connection_version,
                          connection.secret_reference_id, connection.secret_purpose,
                          connection.secret_version,
                          scope.status AS scope_status, scope.source_locator,
                          scope.streams, scope.report_spec, scope.date_policy
                     FROM connector_scopes scope
                     JOIN connector_connections connection
                       ON connection.project_id = scope.project_id
                      AND connection.id = scope.connection_id
                     JOIN connector_definitions definition
                       ON definition.project_id = connection.project_id
                      AND definition.id = connection.definition_id
                    WHERE scope.project_id = %s AND scope.id = %s
                      AND scope.connection_id = %s""",
                (project_id, scope_id, connection_id),
            ).fetchone()
    except (psycopg.Error, OSError) as error:
        raise CanaryFailure(
            "GEO_CONNECTOR_DATABASE_UNAVAILABLE",
            f"Cannot read Connector scope metadata: {type(error).__name__}. Verify GEO_DATABASE_URL and database health.",
            exit_status=5,
        ) from error
    if row is None:
        raise CanaryFailure(
            "GEO_CONNECTOR_SCOPE_NOT_FOUND",
            "The project, Connection, and Scope IDs do not identify one scoped Connector resource",
            exit_status=3,
        )
    if row["kind"] != kind.value:
        raise CanaryFailure(
            "GEO_CONNECTOR_KIND_MISMATCH",
            f"scope belongs to {row['kind']}, not requested {kind.value}",
            exit_status=3,
        )
    return dict(row)


def _validate_row(row: dict[str, Any], kind: ConnectorKind):
    if row["definition_status"] != "approved":
        raise CanaryFailure(
            "GEO_CONNECTOR_DEFINITION_NOT_APPROVED",
            "Connector Definition is not approved; approve the pinned release before enqueue",
            exit_status=3,
        )
    if row["connection_status"] != "active":
        raise CanaryFailure(
            "GEO_CONNECTOR_CONNECTION_NOT_ACTIVE",
            "Connector Connection is not active; re-enable or rotate its Secret Reference",
            exit_status=3,
        )
    if row["scope_status"] != "active":
        raise CanaryFailure(
            "GEO_CONNECTOR_SCOPE_NOT_ACTIVE",
            "Connector Scope is not active; create a new immutable Scope",
            exit_status=3,
        )
    expected_purpose = {
        ConnectorKind.GOOGLE_SEARCH_CONSOLE: "connector.gsc",
        ConnectorKind.GOOGLE_ANALYTICS_4: "connector.ga4",
    }[kind]
    if row["secret_purpose"] != expected_purpose or not row["secret_reference_id"]:
        raise CanaryFailure(
            "GEO_CONNECTOR_SECRET_REFERENCE_INVALID",
            f"Scope Connection must reference an active {expected_purpose} Secret version",
            exit_status=3,
        )
    try:
        return validate_google_scope(
            kind=kind,
            source_locator=row["source_locator"],
            streams=tuple(row["streams"]),
            report_spec=row["report_spec"],
            date_policy=row["date_policy"],
        )
    except (ConnectorScopeError, TypeError, ValueError) as error:
        raise CanaryFailure(
            "GEO_CONNECTOR_SCOPE_INVALID",
            f"Stored Scope is not an explicit valid {kind.value} resource: {error}",
            exit_status=3,
        ) from error


def _database_url(value: str | None) -> str:
    database_url = value or ""
    if not database_url:
        database_url = os.getenv("GEO_CONNECTOR_DATABASE_URL", "")
    if not database_url:
        database_url = os.getenv("GEO_DATABASE_URL", "")
    database_url = database_url.strip()
    if not database_url:
        raise CanaryFailure(
            "GEO_CONNECTOR_DATABASE_URL_REQUIRED",
            "Set GEO_CONNECTOR_DATABASE_URL (or GEO_DATABASE_URL); no external call was made",
        )
    return database_url


def _kind(value: str) -> ConnectorKind:
    try:
        return ConnectorKind(value)
    except ValueError as error:
        raise CanaryFailure(
            "GEO_CONNECTOR_KIND_INVALID",
            "--kind must be google_search_console or google_analytics_4",
        ) from error


def _uuid(value: str | None, name: str) -> UUID:
    if not value:
        raise CanaryFailure(f"GEO_CONNECTOR_{name.upper()}_REQUIRED", f"--{name} is required")
    try:
        return UUID(value)
    except ValueError as error:
        raise CanaryFailure(f"GEO_CONNECTOR_{name.upper()}_INVALID", f"--{name} must be a UUID") from error


def _optional_uuid(value: str | None, name: str) -> UUID | None:
    if value is None or not value.strip():
        return None
    return _uuid(value, name)


def _datetime(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CanaryFailure(f"GEO_CONNECTOR_{name.upper()}_INVALID", f"--{name} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CanaryFailure(f"GEO_CONNECTOR_{name.upper()}_INVALID", f"--{name} must include a timezone")
    return parsed


def _emit(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=True, sort_keys=True, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=[kind.value for kind in (
        ConnectorKind.GOOGLE_SEARCH_CONSOLE, ConnectorKind.GOOGLE_ANALYTICS_4,
    )])
    parser.add_argument("--mode", choices=("check", "test", "sync"), default="check")
    parser.add_argument("--database-url")
    parser.add_argument("--project-id")
    parser.add_argument("--connection-id")
    parser.add_argument("--scope-id")
    parser.add_argument("--secret-reference-id")
    parser.add_argument("--actor-id")
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--sync-mode", choices=[mode.value for mode in ConnectorSyncMode], default="initial")
    parser.add_argument("--window-start")
    parser.add_argument("--window-end")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(build_parser().parse_args(argv))
    except CanaryFailure as error:
        _emit({"status": "blocked", "error_code": error.code, "detail": error.detail})
        return error.exit_status


if __name__ == "__main__":
    raise SystemExit(main())
