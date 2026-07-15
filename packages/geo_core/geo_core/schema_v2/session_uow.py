from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, Sequence
from uuid import UUID


SESSION_TOKEN_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_RAW_SESSION_TOKEN_LENGTH = 4096
_SESSION_TOKEN_HASH_FACTORY_KEY = object()
PROJECT_SCOPE_KEYS = frozenset(
    ("project_id", "roles", "permissions", "portal_capabilities", "scope_sources")
)


class SchemaV2SessionCursor(Protocol):
    def execute(self, sql: str, params: tuple[object, ...] = ()) -> Any: ...

    def fetchone(self) -> Any: ...

    def fetchall(self) -> Any: ...

    def __enter__(self) -> SchemaV2SessionCursor: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...


class SchemaV2SessionConnection(Protocol):
    def cursor(self) -> SchemaV2SessionCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


class SchemaV2SessionUnitOfWorkError(RuntimeError):
    """A redacted, fail-closed Schema v2 session transaction error."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class SchemaV2SessionTokenHashError(SchemaV2SessionUnitOfWorkError):
    def __init__(self) -> None:
        super().__init__(
            "invalid_session_token_hash",
            "session_token_hash must be produced by hash_raw_session_token",
        )


class SchemaV2RawSessionTokenError(SchemaV2SessionUnitOfWorkError):
    def __init__(self) -> None:
        super().__init__(
            "invalid_raw_session_token",
            "raw session token must be a non-empty bounded string",
        )


class SchemaV2SessionAuthorizationError(SchemaV2SessionUnitOfWorkError):
    def __init__(self) -> None:
        super().__init__(
            "session_context_unavailable",
            "Schema v2 session context is unavailable",
        )


class SchemaV2SessionLifecycleError(SchemaV2SessionUnitOfWorkError):
    def __init__(self, detail: str) -> None:
        super().__init__("invalid_session_uow_lifecycle", detail)


class SchemaV2SessionCommitOutcomeUnknownError(SchemaV2SessionUnitOfWorkError):
    retryable = False
    requires_idempotency_recovery = True
    transaction_outcome = "unknown"

    def __init__(self) -> None:
        super().__init__(
            "session_commit_outcome_unknown",
            "Schema v2 transaction commit outcome is unknown; recover by idempotency key",
        )


class SchemaV2SessionRollbackError(SchemaV2SessionUnitOfWorkError):
    retryable = False
    requires_idempotency_recovery = False
    transaction_outcome = "unknown"

    def __init__(self) -> None:
        super().__init__(
            "session_rollback_failed",
            "Schema v2 transaction rollback could not be confirmed",
        )


class _UnitOfWorkState(str, Enum):
    NEW = "new"
    ENTERING = "entering"
    ACTIVE = "active"
    FINISHED = "finished"
    BROKEN = "broken"


@dataclass(frozen=True, init=False)
class SchemaV2SessionTokenHash:
    """Opaque hash value produced only by the raw-token hashing boundary."""

    _value: str = field(repr=False)

    def __init__(self, value: str, *, _factory_key: object | None = None) -> None:
        if _factory_key is not _SESSION_TOKEN_HASH_FACTORY_KEY:
            raise SchemaV2SessionTokenHashError()
        if not SESSION_TOKEN_HASH_PATTERN.fullmatch(value):
            raise SchemaV2SessionTokenHashError()
        object.__setattr__(self, "_value", value)

    def __repr__(self) -> str:
        return "SchemaV2SessionTokenHash([redacted])"


def hash_raw_session_token(raw_session_token: str) -> SchemaV2SessionTokenHash:
    """Hash an opaque raw token without retaining or disclosing the input."""

    if (
        type(raw_session_token) is not str
        or not raw_session_token
        or len(raw_session_token) > MAX_RAW_SESSION_TOKEN_LENGTH
    ):
        raise SchemaV2RawSessionTokenError()
    digest = hashlib.sha256(raw_session_token.encode("utf-8")).hexdigest()
    return SchemaV2SessionTokenHash(
        digest,
        _factory_key=_SESSION_TOKEN_HASH_FACTORY_KEY,
    )


@dataclass(frozen=True)
class SchemaV2SessionCleanupTelemetry:
    status: str
    connection_discarded: bool


@dataclass(frozen=True)
class SchemaV2ResolvedProjectScope:
    project_id: UUID
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    portal_capabilities: tuple[str, ...]
    scope_sources: tuple[str, ...]


@dataclass(frozen=True)
class SchemaV2ResolvedSessionContext:
    session_id: UUID
    actor_id: str
    tenant_id: UUID
    project_ids: tuple[UUID, ...]
    tenant_roles: tuple[str, ...]
    project_scopes: tuple[SchemaV2ResolvedProjectScope, ...]


_ACTIVE_CONNECTION_IDS: set[int] = set()
_ACTIVE_CONNECTION_IDS_LOCK = threading.Lock()


class SchemaV2ApiSessionUnitOfWork:
    """Transaction-scoped Schema v2 API authorization from a pre-hashed token.

    The caller must hash the raw session token before constructing this adapter.
    This module never accepts a raw token and does not expose the hash in its
    resolver projection or error details.
    """

    def __init__(
        self,
        connection: SchemaV2SessionConnection,
        *,
        session_token_hash: SchemaV2SessionTokenHash,
    ) -> None:
        if type(session_token_hash) is not SchemaV2SessionTokenHash:
            raise SchemaV2SessionTokenHashError()
        if getattr(connection, "autocommit", False):
            raise SchemaV2SessionLifecycleError(
                "session unit of work requires autocommit to be disabled"
            )
        self._connection = connection
        self._session_token_hash: SchemaV2SessionTokenHash | None = session_token_hash
        self._state = _UnitOfWorkState.NEW
        self._context: SchemaV2ResolvedSessionContext | None = None
        self._connection_reserved = False
        self._connection_reusable = True
        self._cleanup_telemetry = SchemaV2SessionCleanupTelemetry(
            status="not_run",
            connection_discarded=False,
        )
        self._transaction_outcome = "not_started"

    @property
    def session_context(self) -> SchemaV2ResolvedSessionContext:
        if self._state is not _UnitOfWorkState.ACTIVE or self._context is None:
            raise SchemaV2SessionLifecycleError(
                "session_context is only available inside an active transaction"
            )
        return self._context

    @property
    def connection_reusable(self) -> bool:
        return self._connection_reusable

    @property
    def cleanup_telemetry(self) -> SchemaV2SessionCleanupTelemetry:
        return self._cleanup_telemetry

    @property
    def transaction_outcome(self) -> str:
        return self._transaction_outcome

    def cursor(self) -> SchemaV2SessionCursor:
        if self._state is not _UnitOfWorkState.ACTIVE:
            raise SchemaV2SessionLifecycleError(
                "database cursors are only available inside an active transaction"
            )
        return self._connection.cursor()

    def __enter__(self) -> SchemaV2ApiSessionUnitOfWork:
        if self._state is not _UnitOfWorkState.NEW:
            raise SchemaV2SessionLifecycleError("session unit of work cannot be entered more than once")
        self._state = _UnitOfWorkState.ENTERING
        self._reserve_connection()
        if not _connection_is_idle(self._connection):
            self._release_connection_reservation()
            self._state = _UnitOfWorkState.BROKEN
            raise SchemaV2SessionLifecycleError(
                "session unit of work requires an idle database connection"
            )

        token_hash = self._session_token_hash
        self._session_token_hash = None
        if token_hash is None:
            self._release_connection_reservation()
            self._state = _UnitOfWorkState.BROKEN
            raise SchemaV2SessionLifecycleError("session token hash has already been consumed")
        try:
            with self._connection.cursor() as cursor:
                cursor.execute("BEGIN")
                cursor.execute("SET LOCAL ROLE geo_v2_runtime")
                cursor.execute(
                    "SELECT set_config('app.session_token_hash', %s, true)",
                    (token_hash._value,),
                )
                cursor.execute(
                    """
                    SELECT session_id, actor_id, tenant_id, project_ids,
                           tenant_roles, project_scopes
                    FROM public.geo_v2_resolve_session_context()
                    """
                )
                context = _parse_resolver_rows(cursor.fetchall())
        except SchemaV2SessionAuthorizationError:
            self._abort_failed_enter()
            raise SchemaV2SessionAuthorizationError() from None
        except Exception:
            self._abort_failed_enter()
            raise SchemaV2SessionUnitOfWorkError(
                "session_transaction_setup_failed",
                "Schema v2 session transaction could not be started",
            ) from None

        self._context = context
        self._transaction_outcome = "active"
        self._state = _UnitOfWorkState.ACTIVE
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if self._state is not _UnitOfWorkState.ACTIVE:
            raise SchemaV2SessionLifecycleError("session unit of work is not active")

        if exc_type is None:
            try:
                self._connection.commit()
            except Exception:
                try:
                    self._connection.rollback()
                except Exception:
                    pass
                self._transaction_outcome = "unknown"
                self._finalize_exit(force_discard=True)
                raise SchemaV2SessionCommitOutcomeUnknownError() from None
            self._transaction_outcome = "committed"
        else:
            try:
                self._connection.rollback()
            except Exception:
                self._transaction_outcome = "unknown"
                self._finalize_exit(force_discard=True)
                raise SchemaV2SessionRollbackError() from None
            self._transaction_outcome = "rolled_back"

        self._finalize_exit(force_discard=False)
        return False

    def _finalize_exit(self, *, force_discard: bool) -> None:
        cleanup_succeeded = self._reset_session_state()
        should_discard = force_discard or not cleanup_succeeded
        if should_discard:
            self._discard_connection()
        self._cleanup_telemetry = SchemaV2SessionCleanupTelemetry(
            status="succeeded" if cleanup_succeeded else "failed",
            connection_discarded=should_discard,
        )
        self._context = None
        self._release_connection_reservation()
        self._state = (
            _UnitOfWorkState.BROKEN
            if should_discard
            else _UnitOfWorkState.FINISHED
        )

    def _reserve_connection(self) -> None:
        connection_id = id(self._connection)
        with _ACTIVE_CONNECTION_IDS_LOCK:
            if connection_id in _ACTIVE_CONNECTION_IDS:
                self._state = _UnitOfWorkState.BROKEN
                raise SchemaV2SessionLifecycleError(
                    "database connection already has an active session unit of work"
                )
            _ACTIVE_CONNECTION_IDS.add(connection_id)
        self._connection_reserved = True

    def _release_connection_reservation(self) -> None:
        if not self._connection_reserved:
            return
        with _ACTIVE_CONNECTION_IDS_LOCK:
            _ACTIVE_CONNECTION_IDS.discard(id(self._connection))
        self._connection_reserved = False

    def _abort_failed_enter(self) -> None:
        rollback_failed = False
        try:
            self._connection.rollback()
        except Exception:
            rollback_failed = True
        self._transaction_outcome = "unknown" if rollback_failed else "rolled_back"
        cleanup_failed = not self._reset_session_state()
        if rollback_failed or cleanup_failed:
            self._discard_connection()
        self._cleanup_telemetry = SchemaV2SessionCleanupTelemetry(
            status="failed" if cleanup_failed else "succeeded",
            connection_discarded=rollback_failed or cleanup_failed,
        )
        self._context = None
        self._release_connection_reservation()
        self._state = (
            _UnitOfWorkState.BROKEN
            if rollback_failed or cleanup_failed
            else _UnitOfWorkState.FINISHED
        )
        if rollback_failed or cleanup_failed:
            raise SchemaV2SessionUnitOfWorkError(
                "session_connection_cleanup_failed",
                "Schema v2 session connection could not be cleaned",
            ) from None

    def _reset_session_state(self) -> bool:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute("RESET ALL")
                cursor.execute("RESET ROLE")
            self._connection.commit()
            if not _connection_is_idle(self._connection):
                return False
        except Exception:
            return False
        return True

    def _discard_connection(self) -> None:
        self._connection_reusable = False
        invalidate = getattr(self._connection, "invalidate", None)
        close = getattr(self._connection, "close", None)
        try:
            if callable(invalidate):
                invalidate()
            elif callable(close):
                close()
        except Exception:
            pass


def _connection_is_idle(connection: SchemaV2SessionConnection) -> bool:
    info = getattr(connection, "info", None)
    status = getattr(info, "transaction_status", None)
    if status is None:
        return False
    status_name = getattr(status, "name", None)
    if status_name is not None:
        return status_name == "IDLE"
    try:
        return int(status) == 0
    except (TypeError, ValueError):
        return False


def _parse_resolver_rows(rows: object) -> SchemaV2ResolvedSessionContext:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or len(rows) != 1:
        raise SchemaV2SessionAuthorizationError()
    row = rows[0]
    if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != 6:
        raise SchemaV2SessionAuthorizationError()

    session_id = _canonical_uuid(row[0])
    actor_id = _canonical_actor_id(row[1])
    tenant_id = _canonical_uuid(row[2])
    project_ids = _uuid_tuple(_json_array(row[3]))
    tenant_roles = _string_tuple(_json_array(row[4]), allow_empty=True)
    raw_scopes = _json_array(row[5])
    scopes = tuple(_parse_project_scope(value) for value in raw_scopes)
    if not project_ids or tuple(scope.project_id for scope in scopes) != project_ids:
        raise SchemaV2SessionAuthorizationError()

    return SchemaV2ResolvedSessionContext(
        session_id=session_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
        project_ids=project_ids,
        tenant_roles=tenant_roles,
        project_scopes=scopes,
    )


def _parse_project_scope(value: object) -> SchemaV2ResolvedProjectScope:
    if not isinstance(value, dict) or set(value) != PROJECT_SCOPE_KEYS:
        raise SchemaV2SessionAuthorizationError()
    return SchemaV2ResolvedProjectScope(
        project_id=_canonical_uuid(value["project_id"]),
        roles=_string_tuple(_json_array(value["roles"]), allow_empty=False),
        permissions=_string_tuple(_json_array(value["permissions"]), allow_empty=True),
        portal_capabilities=_string_tuple(
            _json_array(value["portal_capabilities"]),
            allow_empty=True,
        ),
        scope_sources=_string_tuple(_json_array(value["scope_sources"]), allow_empty=False),
    )


def _json_array(value: object) -> list[object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SchemaV2SessionAuthorizationError() from exc
    if type(value) is not list:
        raise SchemaV2SessionAuthorizationError()
    return value


def _canonical_uuid(value: object) -> UUID:
    if not isinstance(value, (str, UUID)):
        raise SchemaV2SessionAuthorizationError()
    try:
        parsed = UUID(str(value))
    except ValueError as exc:
        raise SchemaV2SessionAuthorizationError() from exc
    if isinstance(value, str) and value != str(parsed):
        raise SchemaV2SessionAuthorizationError()
    return parsed


def _canonical_actor_id(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip().lower():
        raise SchemaV2SessionAuthorizationError()
    return value


def _uuid_tuple(values: list[object]) -> tuple[UUID, ...]:
    resolved = tuple(_canonical_uuid(value) for value in values)
    if len(set(resolved)) != len(resolved) or tuple(map(str, resolved)) != tuple(
        sorted(map(str, resolved))
    ):
        raise SchemaV2SessionAuthorizationError()
    return resolved


def _string_tuple(values: list[object], *, allow_empty: bool) -> tuple[str, ...]:
    if any(
        not isinstance(value, str)
        or not value
        or value != value.strip().lower()
        for value in values
    ):
        raise SchemaV2SessionAuthorizationError()
    resolved = tuple(values)
    if (
        len(set(resolved)) != len(resolved)
        or resolved != tuple(sorted(resolved))
        or (not allow_empty and not resolved)
    ):
        raise SchemaV2SessionAuthorizationError()
    return resolved


__all__ = [
    "SchemaV2ApiSessionUnitOfWork",
    "SchemaV2RawSessionTokenError",
    "SchemaV2ResolvedProjectScope",
    "SchemaV2ResolvedSessionContext",
    "SchemaV2SessionAuthorizationError",
    "SchemaV2SessionCleanupTelemetry",
    "SchemaV2SessionCommitOutcomeUnknownError",
    "SchemaV2SessionConnection",
    "SchemaV2SessionLifecycleError",
    "SchemaV2SessionRollbackError",
    "SchemaV2SessionTokenHash",
    "SchemaV2SessionTokenHashError",
    "SchemaV2SessionUnitOfWorkError",
    "hash_raw_session_token",
]
