"""Project-scoped PostgreSQL repositories for encrypted Secret Store state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .errors import (
    SecretConcurrencyConflict,
    SecretScopeViolation,
    SecretStateConflict,
)
from .models import EncryptedSecretVersion, SecretAuditEvent
from .ports import (
    SecretAggregate,
    SecretCommandRecord,
    SecretRepository,
    StoredSecretVersion,
)
from .postgres_fingerprint import envelope_fingerprint
from .postgres_rows import (
    VERSION_COLUMNS,
    aggregate_from_rows,
    audit_from_row,
    command_from_row,
    version_from_row,
)


class PsycopgSecretRepository(SecretRepository):
    __secret_bearing__ = True

    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection = connection
        self._project_id = project_id

    def get(self, reference_id: UUID) -> SecretAggregate | None:
        try:
            reference = self._optional(
                """SELECT id, project_id, purpose, aggregate_version, current_version,
                          created_by, created_at, updated_at
                   FROM secret_references
                   WHERE project_id = %s AND id = %s""",
                (self._project_id, reference_id),
            )
        except psycopg.Error:
            raise SecretStateConflict(
                "PostgreSQL could not read the Secret Store reference"
            ) from None
        if reference is None:
            return None
        try:
            versions = self._many(
                f"""SELECT {VERSION_COLUMNS} FROM secret_versions
                    WHERE project_id = %s AND reference_id = %s
                    ORDER BY version""",
                (self._project_id, reference_id),
            )
        except psycopg.Error:
            raise SecretStateConflict(
                "PostgreSQL could not read Secret Store versions"
            ) from None
        try:
            return aggregate_from_rows(reference, versions)
        except (KeyError, TypeError, ValueError) as error:
            del error
            raise SecretStateConflict(
                "stored Secret Store aggregate is invalid"
            ) from None

    def add(self, aggregate: SecretAggregate) -> None:
        self._require_scope(aggregate)
        if aggregate.aggregate_version != 1 or len(aggregate.versions) != 1:
            raise SecretStateConflict(
                "new Secret Store aggregate must contain only version one"
            )
        try:
            self._execute(
                """INSERT INTO secret_references
                     (id, project_id, purpose, aggregate_version, current_version,
                      created_by, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    aggregate.reference.id,
                    aggregate.project_id,
                    aggregate.reference.purpose,
                    aggregate.aggregate_version,
                    aggregate.current_version,
                    aggregate.created_by,
                    aggregate.reference.created_at,
                    aggregate.updated_at,
                ),
            )
            self._insert_version(aggregate.versions[0])
        except psycopg.Error:
            raise SecretStateConflict(
                "PostgreSQL rejected the new Secret Store reference"
            ) from None

    def save(self, aggregate: SecretAggregate, *, expected_version: int) -> None:
        self._require_scope(aggregate)
        if aggregate.aggregate_version != expected_version + 1:
            raise SecretConcurrencyConflict(
                "secret aggregate version must advance exactly once"
            )
        existing_rows = self._many(
            f"""SELECT {VERSION_COLUMNS} FROM secret_versions
                WHERE project_id = %s AND reference_id = %s
                ORDER BY version""",
            (self._project_id, aggregate.reference.id),
        )
        existing = {int(row["version"]): version_from_row(row) for row in existing_rows}
        incoming = {item.handle.version: item for item in aggregate.versions}
        if not existing or not set(existing) <= set(incoming):
            raise SecretStateConflict("Secret Store version history cannot be removed")

        with self._connection.cursor() as cursor:
            cursor.execute(
                """UPDATE secret_references
                   SET aggregate_version = %s, current_version = %s, updated_at = %s
                   WHERE project_id = %s AND id = %s AND aggregate_version = %s
                   RETURNING id""",
                (
                    aggregate.aggregate_version,
                    aggregate.current_version,
                    aggregate.updated_at,
                    self._project_id,
                    aggregate.reference.id,
                    expected_version,
                ),
            )
            if cursor.fetchone() is None:
                raise SecretConcurrencyConflict(
                    "secret aggregate expected_version is stale"
                )

        try:
            for number in sorted(set(incoming) - set(existing)):
                self._insert_version(incoming[number])
            changed = [
                item
                for number, item in incoming.items()
                if number in existing and item != existing[number]
            ]
            changed.sort(
                key=lambda item: 0 if item.status.value == "superseded" else 1
            )
            for item in changed:
                self._update_lifecycle(item)
        except psycopg.Error:
            raise SecretStateConflict(
                "PostgreSQL rejected the Secret Store lifecycle transition"
            ) from None

    def rewrap(self, envelope: EncryptedSecretVersion) -> None:
        handle = envelope.handle
        if handle.project_id != self._project_id:
            raise SecretScopeViolation("secret envelope belongs to another project")
        with self._connection.cursor() as cursor:
            cursor.execute(
                """UPDATE secret_versions
                   SET wrapped_data_key = %s, wrap_nonce = %s, master_key_version = %s
                   WHERE project_id = %s AND reference_id = %s
                     AND purpose = %s AND version = %s
                   RETURNING reference_id""",
                (
                    envelope.wrapped_data_key,
                    envelope.wrap_nonce,
                    envelope.master_key_version,
                    handle.project_id,
                    handle.reference_id,
                    handle.purpose,
                    handle.version,
                ),
            )
            if cursor.fetchone() is None:
                raise SecretStateConflict("secret version was not found for rewrap")

    def _insert_version(self, stored: StoredSecretVersion) -> None:
        envelope = stored.envelope
        handle = envelope.handle
        if handle.project_id != self._project_id:
            raise SecretScopeViolation("secret version belongs to another project")
        self._execute(
            """INSERT INTO secret_versions
                 (reference_id, project_id, purpose, version,
                  ciphertext, data_nonce, wrapped_data_key, wrap_nonce,
                  master_key_version, algorithm, created_at, status, created_by,
                  verified_by, verified_at, activated_by, activated_at,
                  revoked_by, revoked_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                handle.reference_id,
                handle.project_id,
                handle.purpose,
                handle.version,
                envelope.ciphertext,
                envelope.data_nonce,
                envelope.wrapped_data_key,
                envelope.wrap_nonce,
                envelope.master_key_version,
                envelope.algorithm,
                envelope.created_at,
                stored.status.value,
                stored.created_by,
                stored.verified_by,
                stored.verified_at,
                stored.activated_by,
                stored.activated_at,
                stored.revoked_by,
                stored.revoked_at,
            ),
        )

    def _update_lifecycle(self, stored: StoredSecretVersion) -> None:
        handle = stored.handle
        self._execute(
            """UPDATE secret_versions
               SET status = %s, verified_by = %s, verified_at = %s,
                   activated_by = %s, activated_at = %s,
                   revoked_by = %s, revoked_at = %s
               WHERE project_id = %s AND reference_id = %s
                 AND purpose = %s AND version = %s""",
            (
                stored.status.value,
                stored.verified_by,
                stored.verified_at,
                stored.activated_by,
                stored.activated_at,
                stored.revoked_by,
                stored.revoked_at,
                handle.project_id,
                handle.reference_id,
                handle.purpose,
                handle.version,
            ),
        )

    def _require_scope(self, aggregate: SecretAggregate) -> None:
        if aggregate.project_id != self._project_id:
            raise SecretScopeViolation("secret aggregate belongs to another project")

    def _execute(self, query: str, parameters: tuple[object, ...]) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(query, parameters)

    def _optional(
        self, query: str, parameters: tuple[object, ...]
    ) -> Mapping[str, Any] | None:
        with self._connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, parameters)
            return cast(Mapping[str, Any] | None, cursor.fetchone())

    def _many(
        self, query: str, parameters: tuple[object, ...]
    ) -> tuple[Mapping[str, Any], ...]:
        with self._connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, parameters)
            return tuple(cast(list[Mapping[str, Any]], cursor.fetchall()))


class PsycopgSecretCommandRepository:
    __secret_bearing__ = True

    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection = connection
        self._project_id = project_id

    def get(self, idempotency_key_hash: str) -> SecretCommandRecord | None:
        try:
            self._connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"secret-command:{self._project_id}:{idempotency_key_hash}",),
            )
            with self._connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """SELECT project_id, operation, idempotency_key_hash, request_hash,
                              reference_id, purpose, version, aggregate_version,
                              status, recorded_at
                       FROM secret_command_receipts
                       WHERE project_id = %s AND idempotency_key_hash = %s""",
                    (self._project_id, idempotency_key_hash),
                )
                row = cursor.fetchone()
        except psycopg.Error:
            raise SecretStateConflict(
                "PostgreSQL could not read the Secret Store command receipt"
            ) from None
        return command_from_row(row) if row is not None else None

    def add(self, record: SecretCommandRecord) -> None:
        if record.project_id != self._project_id:
            raise SecretScopeViolation("secret command belongs to another project")
        outcome = record.outcome
        handle = outcome.handle
        try:
            self._connection.execute(
                """INSERT INTO secret_command_receipts
                     (project_id, idempotency_key_hash, operation, request_hash,
                      reference_id, purpose, version, aggregate_version,
                      status, recorded_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    record.project_id,
                    record.idempotency_key_hash,
                    record.operation.value,
                    record.request_hash,
                    handle.reference_id,
                    handle.purpose,
                    handle.version,
                    outcome.aggregate_version,
                    outcome.status.value,
                    record.recorded_at,
                ),
            )
        except psycopg.errors.UniqueViolation:
            raise SecretStateConflict(
                "secret Idempotency-Key record already exists"
            ) from None
        except psycopg.Error:
            raise SecretStateConflict(
                "PostgreSQL rejected the Secret Store command receipt"
            ) from None


class PsycopgSecretAuditRepository:
    __secret_bearing__ = True

    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection = connection
        self._project_id = project_id

    def append(self, event: SecretAuditEvent) -> None:
        if event.project_id != self._project_id:
            raise SecretScopeViolation("secret audit event belongs to another project")
        with self._connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""SELECT {VERSION_COLUMNS} FROM secret_versions
                    WHERE project_id = %s AND reference_id = %s
                      AND purpose = %s AND version = %s""",
                (
                    event.project_id,
                    event.reference_id,
                    event.purpose,
                    event.version,
                ),
            )
            row = cursor.fetchone()
        if row is None:
            raise SecretStateConflict("secret audit version does not exist")
        fingerprint = envelope_fingerprint(version_from_row(row).envelope)
        try:
            self._connection.execute(
                """INSERT INTO secret_audit_events
                     (id, reference_id, project_id, purpose, version,
                      action, actor_id, occurred_at, master_key_version,
                      envelope_fingerprint)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    event.id,
                    event.reference_id,
                    event.project_id,
                    event.purpose,
                    event.version,
                    event.action.value,
                    event.actor_id,
                    event.occurred_at,
                    event.master_key_version,
                    fingerprint,
                ),
            )
        except psycopg.Error:
            raise SecretStateConflict(
                "PostgreSQL rejected the Secret Store audit event"
            ) from None


class PsycopgSecretReadRepository:
    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection = connection
        self._project_id = project_id

    def list_aggregates(
        self, *, limit: int, offset: int
    ) -> tuple[tuple[SecretAggregate, ...], int]:
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("Secret Store reference pagination is out of range")
        with self._connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT count(*) AS total FROM secret_references WHERE project_id = %s",
                (self._project_id,),
            )
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                """SELECT id, project_id, purpose, aggregate_version, current_version,
                          created_by, created_at, updated_at
                   FROM secret_references WHERE project_id = %s
                   ORDER BY created_at DESC, id LIMIT %s OFFSET %s""",
                (self._project_id, limit, offset),
            )
            references = tuple(cursor.fetchall())
        if not references:
            return (), total
        identifiers = [row["id"] for row in references]
        with self._connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""SELECT {VERSION_COLUMNS} FROM secret_versions
                    WHERE project_id = %s AND reference_id = ANY(%s)
                    ORDER BY reference_id, version""",
                (self._project_id, identifiers),
            )
            versions = tuple(cursor.fetchall())
        grouped: dict[UUID, list[Mapping[str, Any]]] = {}
        for row in versions:
            grouped.setdefault(cast(UUID, row["reference_id"]), []).append(row)
        return (
            tuple(
                aggregate_from_rows(row, grouped.get(cast(UUID, row["id"]), []))
                for row in references
            ),
            total,
        )

    def list_audits(
        self, *, limit: int, offset: int
    ) -> tuple[tuple[tuple[SecretAuditEvent, str], ...], int]:
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("Secret Store audit pagination is out of range")
        with self._connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT count(*) AS total FROM secret_audit_events WHERE project_id = %s",
                (self._project_id,),
            )
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                """SELECT id, reference_id, project_id, purpose, version,
                          action, actor_id, occurred_at, master_key_version,
                          envelope_fingerprint
                   FROM secret_audit_events
                    WHERE project_id = %s
                    ORDER BY occurred_at DESC, id
                    LIMIT %s OFFSET %s""",
                (self._project_id, limit, offset),
            )
            rows = tuple(cursor.fetchall())
        results: list[tuple[SecretAuditEvent, str]] = []
        for row in rows:
            results.append((audit_from_row(row), str(row["envelope_fingerprint"])))
        return tuple(results), total


__all__ = [
    "PsycopgSecretAuditRepository",
    "PsycopgSecretCommandRepository",
    "PsycopgSecretReadRepository",
    "PsycopgSecretRepository",
]
