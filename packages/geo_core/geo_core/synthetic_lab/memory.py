"""Thread-safe in-memory UoW for Synthetic Lab application and concurrency tests."""

from __future__ import annotations

from threading import RLock
from types import TracebackType
from typing import TypeVar
from uuid import UUID

from geo_core.synthetic_lab.authorization import AuthorizationBinding, AuthorizationRecord
from geo_core.synthetic_lab.ports import (
    AuthorizationEnvelope,
    JobTerminalResult,
    SyntheticAggregateRepository,
    SyntheticAuthorizationRepository,
    SyntheticCommandRecord,
    SyntheticCommandRepository,
    SyntheticDifyReconciliationPort,
    SyntheticImportRepository,
    SyntheticJobRepository,
    SyntheticLabIdempotencyConflict,
    SyntheticLabPersistenceError,
    SyntheticLabUnitOfWork,
    SyntheticLabVersionConflict,
    SyntheticOutboxMessage,
    SyntheticOutboxRepository,
    SyntheticJob,
    VersionedAggregate,
)
from geo_core.synthetic_lab.raw_artifact_governance import ArtifactGovernanceDecision
from geo_core.synthetic_lab.profile_build_binding import StyleProfileBuildBinding
from geo_core.synthetic_lab.sample_import import ManualSampleImportManifest


_Key = TypeVar("_Key")
_Value = TypeVar("_Value")


class InMemorySyntheticLabStore:
    """Committed state shared by short-lived, project-scoped UoWs."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._commands: dict[tuple[UUID, str], SyntheticCommandRecord] = {}
        self._aggregates: dict[tuple[UUID, str, UUID], VersionedAggregate] = {}
        self._authorizations: dict[tuple[UUID, str, str], AuthorizationEnvelope] = {}
        self._manifests: dict[tuple[UUID, UUID], ManualSampleImportManifest] = {}
        self._artifact_decisions: dict[tuple[UUID, UUID], ArtifactGovernanceDecision] = {}
        self._sample_hashes: dict[tuple[UUID, str], UUID] = {}
        self._jobs: dict[tuple[UUID, UUID], SyntheticJob] = {}
        self._outbox: dict[tuple[UUID, UUID], SyntheticOutboxMessage] = {}
        self._terminal_results: dict[tuple[UUID, UUID], JobTerminalResult] = {}
        self._execution_tasks: dict[tuple[UUID, UUID], object] = {}
        self._style_collection_tasks: dict[tuple[UUID, UUID], object] = {}
        self._profile_build_bindings: dict[
            tuple[UUID, UUID], StyleProfileBuildBinding
        ] = {}
        self._fail_next_commit = False

    def fail_next_commit(self) -> None:
        with self._lock:
            self._fail_next_commit = True

    def seed_aggregate(self, aggregate: VersionedAggregate) -> None:
        key = (aggregate.project_id, aggregate.kind, aggregate.resource_id)
        with self._lock:
            if key in self._aggregates:
                raise SyntheticLabVersionConflict("Synthetic Lab aggregate already exists")
            self._aggregates[key] = aggregate

    def seed_job(self, job: SyntheticJob) -> None:
        key = (job.project_id, job.id)
        with self._lock:
            if key in self._jobs:
                raise SyntheticLabVersionConflict("Synthetic Lab Job already exists")
            self._jobs[key] = job

    def command_count(self, project_id: UUID) -> int:
        with self._lock:
            return sum(scope == project_id for scope, _ in self._commands)

    def job_count(self, project_id: UUID) -> int:
        with self._lock:
            return sum(scope == project_id for scope, _ in self._jobs)

    def outbox_count(self, project_id: UUID) -> int:
        with self._lock:
            return sum(scope == project_id for scope, _ in self._outbox)

    def get_job(self, *, project_id: UUID, job_id: UUID) -> SyntheticJob | None:
        with self._lock:
            return self._jobs.get((project_id, job_id))

    def get_aggregate(
        self, *, project_id: UUID, kind: str, resource_id: UUID
    ) -> VersionedAggregate | None:
        with self._lock:
            return self._aggregates.get((project_id, kind, resource_id))

    def get_authorization(
        self, *, project_id: UUID, channel: str, adapter_release: str
    ) -> AuthorizationEnvelope | None:
        with self._lock:
            return self._authorizations.get((project_id, channel, adapter_release))

    def get_manifest(
        self, *, project_id: UUID, request_id: UUID
    ) -> ManualSampleImportManifest | None:
        with self._lock:
            return self._manifests.get((project_id, request_id))

    def get_terminal_result(self, *, project_id: UUID, job_id: UUID) -> JobTerminalResult | None:
        with self._lock:
            return self._terminal_results.get((project_id, job_id))

    def get_execution_task(self, *, project_id: UUID, job_id: UUID) -> object | None:
        with self._lock:
            return self._execution_tasks.get((project_id, job_id))

    def get_style_collection_task(self, *, project_id: UUID, job_id: UUID) -> object | None:
        with self._lock:
            return self._style_collection_tasks.get((project_id, job_id))

    def get_profile_build_binding(
        self, *, project_id: UUID, profile_version_id: UUID
    ) -> StyleProfileBuildBinding | None:
        with self._lock:
            return self._profile_build_bindings.get((project_id, profile_version_id))


class InMemorySyntheticLabUnitOfWorkFactory:
    def __init__(self, store: InMemorySyntheticLabStore) -> None:
        self.store = store

    def __call__(self, *, project_id: UUID) -> SyntheticLabUnitOfWork:
        return InMemorySyntheticLabUnitOfWork(self.store, project_id=project_id)


class InMemorySyntheticLabUnitOfWork:
    def __init__(self, store: InMemorySyntheticLabStore, *, project_id: UUID) -> None:
        self._store = store
        self.project_id = project_id
        self._active = False
        self.commands: SyntheticCommandRepository = _MemoryCommands(self)
        self.aggregates: SyntheticAggregateRepository = _MemoryAggregates(self)
        self.authorizations: SyntheticAuthorizationRepository = _MemoryAuthorizations(self)
        self.imports: SyntheticImportRepository = _MemoryImports(self)
        self.jobs: SyntheticJobRepository = _MemoryJobs(self)
        self.outbox: SyntheticOutboxRepository = _MemoryOutbox(self)
        self.execution_tasks = _MemoryExecutionTasks(self)
        self.style_collection_tasks = _MemoryStyleCollectionTasks(self)
        self.profile_build_bindings = _MemoryProfileBuildBindings(self)
        self.dify_reconciliation: SyntheticDifyReconciliationPort = (
            _MemoryDifyReconciliation(self)
        )

    def __enter__(self) -> "InMemorySyntheticLabUnitOfWork":
        if self._active:
            raise SyntheticLabPersistenceError("Synthetic Lab UoW is already active")
        with self._store._lock:
            self._base_commands = dict(self._store._commands)
            self._base_aggregates = dict(self._store._aggregates)
            self._base_authorizations = dict(self._store._authorizations)
            self._base_manifests = dict(self._store._manifests)
            self._base_decisions = dict(self._store._artifact_decisions)
            self._base_sample_hashes = dict(self._store._sample_hashes)
            self._base_jobs = dict(self._store._jobs)
            self._base_outbox = dict(self._store._outbox)
            self._base_results = dict(self._store._terminal_results)
            self._base_execution_tasks = dict(self._store._execution_tasks)
            self._base_style_collection_tasks = dict(self._store._style_collection_tasks)
            self._base_profile_build_bindings = dict(self._store._profile_build_bindings)
        self._commands = dict(self._base_commands)
        self._aggregates = dict(self._base_aggregates)
        self._authorizations = dict(self._base_authorizations)
        self._manifests = dict(self._base_manifests)
        self._decisions = dict(self._base_decisions)
        self._sample_hashes = dict(self._base_sample_hashes)
        self._jobs = dict(self._base_jobs)
        self._outbox = dict(self._base_outbox)
        self._results = dict(self._base_results)
        self._execution_tasks = dict(self._base_execution_tasks)
        self._style_collection_tasks = dict(self._base_style_collection_tasks)
        self._profile_build_bindings = dict(self._base_profile_build_bindings)
        self._touched_commands: set[tuple[UUID, str]] = set()
        self._touched_aggregates: set[tuple[UUID, str, UUID]] = set()
        self._touched_authorizations: set[tuple[UUID, str, str]] = set()
        self._touched_manifests: set[tuple[UUID, UUID]] = set()
        self._touched_decisions: set[tuple[UUID, UUID]] = set()
        self._touched_sample_hashes: set[tuple[UUID, str]] = set()
        self._touched_jobs: set[tuple[UUID, UUID]] = set()
        self._touched_outbox: set[tuple[UUID, UUID]] = set()
        self._touched_results: set[tuple[UUID, UUID]] = set()
        self._touched_execution_tasks: set[tuple[UUID, UUID]] = set()
        self._touched_style_collection_tasks: set[tuple[UUID, UUID]] = set()
        self._touched_profile_build_bindings: set[tuple[UUID, UUID]] = set()
        self._active = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self._active = False
        return None

    def commit(self) -> None:
        self._ensure_active()
        with self._store._lock:
            if self._store._fail_next_commit:
                self._store._fail_next_commit = False
                raise SyntheticLabPersistenceError("simulated Synthetic Lab commit failure")
            self._verify(self._touched_commands, self._base_commands, self._store._commands)
            self._verify(self._touched_aggregates, self._base_aggregates, self._store._aggregates)
            self._verify(
                self._touched_authorizations,
                self._base_authorizations,
                self._store._authorizations,
            )
            self._verify(self._touched_manifests, self._base_manifests, self._store._manifests)
            self._verify(
                self._touched_decisions,
                self._base_decisions,
                self._store._artifact_decisions,
            )
            self._verify(
                self._touched_sample_hashes,
                self._base_sample_hashes,
                self._store._sample_hashes,
            )
            self._verify(self._touched_jobs, self._base_jobs, self._store._jobs)
            self._verify(self._touched_outbox, self._base_outbox, self._store._outbox)
            self._verify(
                self._touched_results,
                self._base_results,
                self._store._terminal_results,
            )
            self._verify(
                self._touched_execution_tasks,
                self._base_execution_tasks,
                self._store._execution_tasks,
            )
            self._verify(
                self._touched_style_collection_tasks,
                self._base_style_collection_tasks,
                self._store._style_collection_tasks,
            )
            self._verify(
                self._touched_profile_build_bindings,
                self._base_profile_build_bindings,
                self._store._profile_build_bindings,
            )
            _apply(self._store._commands, self._commands, self._touched_commands)
            _apply(self._store._aggregates, self._aggregates, self._touched_aggregates)
            _apply(
                self._store._authorizations,
                self._authorizations,
                self._touched_authorizations,
            )
            _apply(self._store._manifests, self._manifests, self._touched_manifests)
            _apply(
                self._store._artifact_decisions,
                self._decisions,
                self._touched_decisions,
            )
            _apply(
                self._store._sample_hashes,
                self._sample_hashes,
                self._touched_sample_hashes,
            )
            _apply(self._store._jobs, self._jobs, self._touched_jobs)
            _apply(self._store._outbox, self._outbox, self._touched_outbox)
            _apply(
                self._store._terminal_results,
                self._results,
                self._touched_results,
            )
            _apply(
                self._store._execution_tasks,
                self._execution_tasks,
                self._touched_execution_tasks,
            )
            _apply(
                self._store._style_collection_tasks,
                self._style_collection_tasks,
                self._touched_style_collection_tasks,
            )
            _apply(
                self._store._profile_build_bindings,
                self._profile_build_bindings,
                self._touched_profile_build_bindings,
            )

    def _verify(
        self,
        keys: set[_Key],
        base: dict[_Key, _Value],
        committed: dict[_Key, _Value],
    ) -> None:
        for key in keys:
            if committed.get(key) != base.get(key):
                raise SyntheticLabVersionConflict(
                    "concurrent Synthetic Lab transaction changed committed state"
                )

    def _require_scope(self, project_id: UUID) -> None:
        self._ensure_active()
        if project_id != self.project_id:
            raise SyntheticLabPersistenceError("Synthetic Lab UoW Project scope mismatch")

    def _ensure_active(self) -> None:
        if not self._active:
            raise SyntheticLabPersistenceError("Synthetic Lab UoW is not active")


class _MemoryDifyReconciliation:
    def __init__(self, uow: InMemorySyntheticLabUnitOfWork) -> None:
        self._uow = uow

    def bind_resubmission(
        self,
        *,
        project_id: UUID,
        new_parent_job_id: UUID,
        actor_id: UUID,
        recovery_of_attempt_id: UUID | None,
        token: str | None,
    ) -> UUID | None:
        del new_parent_job_id, actor_id
        self._uow._require_scope(project_id)
        if recovery_of_attempt_id is None and token is None:
            return None
        raise SyntheticLabPersistenceError(
            "in-memory Synthetic Lab cannot consume a Dify reconciliation token"
        )


class _MemoryCommands:
    def __init__(self, uow: InMemorySyntheticLabUnitOfWork) -> None:
        self._uow = uow

    def get(self, *, project_id: UUID, idempotency_key_hash: str) -> SyntheticCommandRecord | None:
        self._uow._require_scope(project_id)
        return self._uow._commands.get((project_id, idempotency_key_hash))

    def stage(self, record: SyntheticCommandRecord) -> None:
        project_id = record.identity.project_id
        self._uow._require_scope(project_id)
        key = (project_id, record.identity.idempotency_key_hash)
        current = self._uow._commands.get(key)
        if current is not None:
            if current != record:
                raise SyntheticLabIdempotencyConflict(
                    "Idempotency-Key was reused with a different request or result"
                )
            return
        self._uow._commands[key] = record
        self._uow._touched_commands.add(key)


class _MemoryAggregates:
    def __init__(self, uow: InMemorySyntheticLabUnitOfWork) -> None:
        self._uow = uow

    def get(self, *, project_id: UUID, kind: str, resource_id: UUID) -> VersionedAggregate | None:
        self._uow._require_scope(project_id)
        return self._uow._aggregates.get((project_id, kind, resource_id))

    def stage(self, aggregate: VersionedAggregate, *, expected_version: int) -> None:
        self._uow._require_scope(aggregate.project_id)
        key = (aggregate.project_id, aggregate.kind, aggregate.resource_id)
        current = self._uow._aggregates.get(key)
        current_version = current.version if current is not None else 0
        if current_version != expected_version or aggregate.version != expected_version + 1:
            raise SyntheticLabVersionConflict("Synthetic Lab aggregate CAS failed")
        self._uow._aggregates[key] = aggregate
        self._uow._touched_aggregates.add(key)


class _MemoryAuthorizations:
    def __init__(self, uow: InMemorySyntheticLabUnitOfWork) -> None:
        self._uow = uow

    def current(
        self, *, project_id: UUID, channel: str, adapter_release: str
    ) -> AuthorizationEnvelope | None:
        self._uow._require_scope(project_id)
        return self._uow._authorizations.get((project_id, channel, adapter_release))

    def stage(self, envelope: AuthorizationEnvelope, *, expected_version: int) -> None:
        record = envelope.record
        self._uow._require_scope(record.project_id)
        key = (record.project_id, record.channel, record.adapter_release)
        current = self._uow._authorizations.get(key)
        current_version = current.record.version_number if current is not None else 0
        if current_version != expected_version or record.version_number != expected_version + 1:
            raise SyntheticLabVersionConflict("collection authorization CAS failed")
        self._uow._authorizations[key] = envelope
        self._uow._touched_authorizations.add(key)


class _MemoryImports:
    def __init__(self, uow: InMemorySyntheticLabUnitOfWork) -> None:
        self._uow = uow

    def contains_sample_hash(self, *, project_id: UUID, sample_hash: str) -> bool:
        self._uow._require_scope(project_id)
        return (project_id, sample_hash) in self._uow._sample_hashes

    def stage(
        self,
        *,
        manifest: ManualSampleImportManifest,
        decisions: tuple[ArtifactGovernanceDecision, ...],
    ) -> None:
        self._uow._require_scope(manifest.project_id)
        manifest_key = (manifest.project_id, manifest.request_id)
        if manifest_key in self._uow._manifests:
            raise SyntheticLabVersionConflict("manual import request already exists")
        for decision in decisions:
            self._uow._require_scope(decision.project_id)
            decision_key = (decision.project_id, decision.artifact_id)
            if decision_key in self._uow._decisions:
                raise SyntheticLabVersionConflict("artifact governance decision already exists")
            self._uow._decisions[decision_key] = decision
            self._uow._touched_decisions.add(decision_key)
        for sample in manifest.accepted_samples:
            sample_key = (manifest.project_id, sample.normalized_text_hash)
            if sample_key in self._uow._sample_hashes:
                raise SyntheticLabVersionConflict("manual import contains a cross-run duplicate")
            self._uow._sample_hashes[sample_key] = sample.id
            self._uow._touched_sample_hashes.add(sample_key)
        self._uow._manifests[manifest_key] = manifest
        self._uow._touched_manifests.add(manifest_key)


class _MemoryJobs:
    def __init__(self, uow: InMemorySyntheticLabUnitOfWork) -> None:
        self._uow = uow

    def get(self, *, project_id: UUID, job_id: UUID) -> SyntheticJob | None:
        self._uow._require_scope(project_id)
        return self._uow._jobs.get((project_id, job_id))

    def stage(self, job: SyntheticJob, *, expected_version: int) -> None:
        self._uow._require_scope(job.project_id)
        key = (job.project_id, job.id)
        current = self._uow._jobs.get(key)
        current_version = current.version if current is not None else 0
        if current_version != expected_version or job.version != expected_version + 1:
            raise SyntheticLabVersionConflict("Durable Synthetic Lab Job CAS failed")
        self._uow._jobs[key] = job
        self._uow._touched_jobs.add(key)

    def stage_terminal(self, result: JobTerminalResult) -> None:
        self._uow._require_scope(result.project_id)
        key = (result.project_id, result.job_id)
        if key in self._uow._results:
            raise SyntheticLabVersionConflict("Synthetic Lab terminal result already exists")
        self._uow._results[key] = result
        self._uow._touched_results.add(key)


class _MemoryOutbox:
    def __init__(self, uow: InMemorySyntheticLabUnitOfWork) -> None:
        self._uow = uow

    def stage(self, message: SyntheticOutboxMessage) -> None:
        self._uow._require_scope(message.project_id)
        key = (message.project_id, message.id)
        current = self._uow._outbox.get(key)
        if current is not None and current != message:
            raise SyntheticLabVersionConflict("Synthetic Lab outbox identity already exists")
        self._uow._outbox[key] = message
        self._uow._touched_outbox.add(key)


class _MemoryExecutionTasks:
    def __init__(self, uow: InMemorySyntheticLabUnitOfWork) -> None:
        self._uow = uow

    def stage(self, task, expected_job_input_hash: str) -> None:
        self._uow._require_scope(task.project_id)
        if task.input_hash != expected_job_input_hash:
            raise SyntheticLabVersionConflict("execution task and Durable Job input hashes differ")
        key = (task.project_id, task.job_id)
        current = self._uow._execution_tasks.get(key)
        if current is not None and current != task:
            raise SyntheticLabVersionConflict("Synthetic execution task identity already exists")
        self._uow._execution_tasks[key] = task
        self._uow._touched_execution_tasks.add(key)


class _MemoryStyleCollectionTasks:
    def __init__(self, uow: InMemorySyntheticLabUnitOfWork) -> None:
        self._uow = uow

    def stage(self, task, *, expected_job_input_hash: str) -> None:
        self._uow._require_scope(task.project_id)
        if task.input_hash != expected_job_input_hash:
            raise SyntheticLabVersionConflict(
                "Style Collection task and Durable Job input hashes differ"
            )
        key = (task.project_id, task.job_id)
        current = self._uow._style_collection_tasks.get(key)
        if current is not None and current != task:
            raise SyntheticLabVersionConflict("Style Collection task identity already exists")
        self._uow._style_collection_tasks[key] = task
        self._uow._touched_style_collection_tasks.add(key)


class _MemoryProfileBuildBindings:
    def __init__(self, uow: InMemorySyntheticLabUnitOfWork) -> None:
        self._uow = uow

    def get(
        self, *, project_id: UUID, profile_version_id: UUID
    ) -> StyleProfileBuildBinding | None:
        self._uow._require_scope(project_id)
        return self._uow._profile_build_bindings.get((project_id, profile_version_id))

    def stage(self, binding: StyleProfileBuildBinding) -> None:
        self._uow._require_scope(binding.project_id)
        key = (binding.project_id, binding.profile_version_id)
        current = self._uow._profile_build_bindings.get(key)
        if current is not None and current != binding:
            raise SyntheticLabVersionConflict(
                "Style Profile version is already bound to another build result"
            )
        self._uow._profile_build_bindings[key] = binding
        self._uow._touched_profile_build_bindings.add(key)


class InMemoryCollectionAuthorizationPort:
    """Claim/navigation recheck adapter reading only committed authorization state."""

    def __init__(self, store: InMemorySyntheticLabStore) -> None:
        self._store = store

    def current(self, binding: AuthorizationBinding) -> AuthorizationRecord | None:
        envelope = self._store.get_authorization(
            project_id=binding.project_id,
            channel=binding.channel,
            adapter_release=binding.adapter_release,
        )
        return envelope.record if envelope is not None else None


def _apply(target: dict[_Key, _Value], source: dict[_Key, _Value], keys: set[_Key]) -> None:
    for key in keys:
        target[key] = source[key]


__all__ = [
    "InMemoryCollectionAuthorizationPort",
    "InMemorySyntheticLabStore",
    "InMemorySyntheticLabUnitOfWork",
    "InMemorySyntheticLabUnitOfWorkFactory",
]
