"""Transactional in-memory adapter for Secret Store application ports."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from types import TracebackType
from typing import Never
from uuid import UUID

from .errors import (
    SecretConcurrencyConflict,
    SecretScopeViolation,
    SecretSerializationRejected,
    SecretStateConflict,
)
from .models import SecretAuditEvent, require_uuid
from .ports import (
    SecretAggregate,
    SecretAuditRepository,
    SecretCommandRecord,
    SecretCommandRepository,
    SecretRepository,
    SecretUnitOfWork,
    SecretUnitOfWorkFactory,
)


@dataclass
class _ProjectState:
    transaction_version: int
    references: dict[UUID, SecretAggregate]
    commands: dict[str, SecretCommandRecord]
    audits: list[SecretAuditEvent]


class MemorySecretDatabase:
    """Shared test/process state; it is not a production persistence adapter."""

    __secret_bearing__ = True
    __slots__ = ("_lock", "_projects")

    def __init__(self) -> None:
        self._lock = RLock()
        self._projects: dict[UUID, _ProjectState] = {}

    def __repr__(self) -> str:
        return "MemorySecretDatabase([ENCRYPTED STATE])"

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("Secret Store repositories cannot be serialized")

    def reference(self, project_id: UUID, reference_id: UUID) -> SecretAggregate | None:
        with self._lock:
            state = self._projects.get(project_id)
            return None if state is None else state.references.get(reference_id)

    def audit_events(self, project_id: UUID) -> tuple[SecretAuditEvent, ...]:
        with self._lock:
            state = self._projects.get(project_id)
            return () if state is None else tuple(state.audits)

    def command_records(self, project_id: UUID) -> tuple[SecretCommandRecord, ...]:
        with self._lock:
            state = self._projects.get(project_id)
            if state is None:
                return ()
            return tuple(state.commands[key] for key in sorted(state.commands))

    def transaction_version(self, project_id: UUID) -> int:
        with self._lock:
            state = self._projects.get(project_id)
            return 0 if state is None else state.transaction_version

    def _begin(self, project_id: UUID) -> _ProjectState:
        with self._lock:
            current = self._projects.get(project_id)
            if current is None:
                return _ProjectState(0, {}, {}, [])
            return _ProjectState(
                current.transaction_version,
                dict(current.references),
                dict(current.commands),
                list(current.audits),
            )

    def _commit(self, project_id: UUID, working: _ProjectState) -> None:
        with self._lock:
            current = self._projects.get(project_id)
            current_version = 0 if current is None else current.transaction_version
            if current_version != working.transaction_version:
                raise SecretConcurrencyConflict("project Secret Store transaction is stale")
            self._projects[project_id] = _ProjectState(
                transaction_version=current_version + 1,
                references=dict(working.references),
                commands=dict(working.commands),
                audits=list(working.audits),
            )


class MemorySecretRepository(SecretRepository):
    __secret_bearing__ = True

    def __init__(self, project_id: UUID, working: _ProjectState) -> None:
        self._project_id = project_id
        self._working = working

    def get(self, reference_id: UUID) -> SecretAggregate | None:
        return self._working.references.get(reference_id)

    def add(self, aggregate: SecretAggregate) -> None:
        self._require_scope(aggregate)
        if aggregate.reference.id in self._working.references:
            raise SecretStateConflict("secret reference already exists")
        self._working.references[aggregate.reference.id] = aggregate

    def save(self, aggregate: SecretAggregate, *, expected_version: int) -> None:
        self._require_scope(aggregate)
        current = self._working.references.get(aggregate.reference.id)
        if current is None:
            raise SecretStateConflict("secret reference does not exist")
        if current.aggregate_version != expected_version:
            raise SecretConcurrencyConflict("secret aggregate expected_version is stale")
        if aggregate.aggregate_version != expected_version + 1:
            raise SecretConcurrencyConflict("secret aggregate version must advance exactly once")
        self._working.references[aggregate.reference.id] = aggregate

    def _require_scope(self, aggregate: SecretAggregate) -> None:
        if aggregate.project_id != self._project_id:
            raise SecretScopeViolation("secret aggregate belongs to another project")


class MemorySecretCommandRepository(SecretCommandRepository):
    __secret_bearing__ = True

    def __init__(self, project_id: UUID, working: _ProjectState) -> None:
        self._project_id = project_id
        self._working = working

    def get(self, idempotency_key_hash: str) -> SecretCommandRecord | None:
        return self._working.commands.get(idempotency_key_hash)

    def add(self, record: SecretCommandRecord) -> None:
        if record.project_id != self._project_id:
            raise SecretScopeViolation("secret command record belongs to another project")
        if record.idempotency_key_hash in self._working.commands:
            raise SecretStateConflict("secret Idempotency-Key record already exists")
        self._working.commands[record.idempotency_key_hash] = record


class MemorySecretAuditRepository(SecretAuditRepository):
    __secret_bearing__ = True

    def __init__(self, project_id: UUID, working: _ProjectState) -> None:
        self._project_id = project_id
        self._working = working

    def append(self, event: SecretAuditEvent) -> None:
        if event.project_id != self._project_id:
            raise SecretScopeViolation("secret audit event belongs to another project")
        self._working.audits.append(event)


class MemorySecretUnitOfWork(SecretUnitOfWork):
    __secret_bearing__ = True

    def __init__(self, database: MemorySecretDatabase, project_id: UUID) -> None:
        require_uuid(project_id, "Secret Store Unit of Work project ID")
        self.project_id = project_id
        self._database = database
        self._working = database._begin(project_id)
        self._completed = False
        self.secrets = MemorySecretRepository(project_id, self._working)
        self.commands = MemorySecretCommandRepository(project_id, self._working)
        self.audits = MemorySecretAuditRepository(project_id, self._working)

    def __enter__(self) -> "MemorySecretUnitOfWork":
        if self._completed:
            raise SecretStateConflict("Secret Store Unit of Work is already completed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if exc_type is not None or not self._completed:
            self.rollback()
        return None

    def commit(self) -> None:
        if self._completed:
            raise SecretStateConflict("Secret Store Unit of Work is already completed")
        self._database._commit(self.project_id, self._working)
        self._completed = True

    def rollback(self) -> None:
        self._completed = True


class MemorySecretUnitOfWorkFactory(SecretUnitOfWorkFactory):
    __secret_bearing__ = True

    def __init__(self, database: MemorySecretDatabase | None = None) -> None:
        self.database = MemorySecretDatabase() if database is None else database

    def create(self, project_id: UUID) -> MemorySecretUnitOfWork:
        return MemorySecretUnitOfWork(self.database, project_id)
