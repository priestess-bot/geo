"""Application ports for the project-scoped synthetic evaluation laboratory."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from types import TracebackType
from typing import TYPE_CHECKING, Mapping, Protocol
from uuid import UUID

from geo_core.jobs.lifecycle import DurableJob, JobStatus
from geo_core.synthetic_lab.authorization import AuthorizationBinding, AuthorizationRecord
from geo_core.synthetic_lab.raw_artifact_governance import ArtifactGovernanceDecision
from geo_core.synthetic_lab.sample_import import ManualSampleImportManifest

if TYPE_CHECKING:
    from geo_core.synthetic_lab.collection_execution_contracts import (
        StyleCollectionTaskStagingPort,
    )
    from geo_core.synthetic_lab.execution_contracts import SyntheticExecutionTaskStagingPort


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SyntheticLabPersistenceError(RuntimeError):
    """A Synthetic Lab application transaction could not be persisted."""


class SyntheticLabNotFound(RuntimeError):
    """A Synthetic Lab resource is absent from the authorized Project."""


class SyntheticLabVersionConflict(SyntheticLabPersistenceError):
    """An aggregate changed after the caller read its expected version."""


class SyntheticLabIdempotencyConflict(SyntheticLabPersistenceError):
    """An Idempotency-Key was reused for a different immutable request."""


class SyntheticLabPermissionDenied(SyntheticLabPersistenceError):
    """The actor does not hold the role required by the command."""


class SyntheticLabStaleInput(SyntheticLabPersistenceError):
    """A frozen Fact, Profile or Prompt input is no longer current."""


class SyntheticLabJobOwnershipLost(SyntheticLabPersistenceError):
    """The worker lost its lease or fencing generation before a terminal write."""


class SyntheticCustomerProjectionDenied(SyntheticLabPersistenceError):
    """Synthetic laboratory output can never enter a Customer projection."""


class LabRole(StrEnum):
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    APPROVER = "approver"
    WORKER = "worker"


@dataclass(frozen=True, kw_only=True)
class LabPrincipal:
    project_id: UUID
    actor_id: UUID
    roles: frozenset[LabRole]

    def __post_init__(self) -> None:
        object.__setattr__(self, "roles", frozenset(LabRole(role) for role in self.roles))


class SyntheticCommandOperation(StrEnum):
    CREATE_AUTHORIZATION = "create_authorization"
    DECIDE_AUTHORIZATION = "decide_authorization"
    EXPIRE_AUTHORIZATION = "expire_authorization"
    REVOKE_AUTHORIZATION = "revoke_authorization"
    REASSESS_AUTHORIZATION = "reassess_authorization"
    ADMIT_COLLECTION = "admit_collection"
    CLAIM_COLLECTION = "claim_collection"
    CREATE_STYLE_SOURCE = "create_style_source"
    CREATE_STYLE_PROFILE = "create_style_profile"
    CREATE_REVIEW_SUITE = "create_review_suite"
    CREATE_REVIEW_CASE = "create_review_case"
    IMPORT_SAMPLES = "import_samples"
    SUBMIT_PROFILE = "submit_profile"
    DECIDE_PROFILE = "decide_profile"
    FREEZE_PROFILE = "freeze_profile"
    FREEZE_SUITE = "freeze_suite"
    ENQUEUE_GENERATION = "enqueue_generation"
    ENQUEUE_REVISION = "enqueue_revision"
    ENQUEUE_CORPUS = "enqueue_corpus"
    ENQUEUE_EXPERIMENT = "enqueue_experiment"
    ENQUEUE_EXECUTION = "enqueue_execution"
    CLAIM_JOB = "claim_job"
    CANCEL_JOB = "cancel_job"
    FINALIZE_RESULT = "finalize_result"
    FINALIZE_EXPERIMENT = "finalize_experiment"


@dataclass(frozen=True, kw_only=True)
class SyntheticCommandIdentity:
    project_id: UUID
    idempotency_key_hash: str
    operation: SyntheticCommandOperation
    request_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", SyntheticCommandOperation(self.operation))
        if not _SHA256.fullmatch(self.idempotency_key_hash):
            raise ValueError("Synthetic Lab idempotency key hash must be SHA-256")
        if not _SHA256.fullmatch(self.request_hash):
            raise ValueError("Synthetic Lab request hash must be SHA-256")


@dataclass(frozen=True)
class SyntheticCommandRecord:
    identity: SyntheticCommandIdentity
    result: object


@dataclass(frozen=True)
class CommandReceipt:
    result: object
    replayed: bool


@dataclass(frozen=True, kw_only=True)
class VersionedAggregate:
    project_id: UUID
    kind: str
    resource_id: UUID
    version: int
    submitted_by: UUID
    payload: object

    def __post_init__(self) -> None:
        if not self.kind.strip() or self.version < 1:
            raise ValueError("Synthetic Lab aggregate kind/version is invalid")
        scoped_project = getattr(self.payload, "project_id", self.project_id)
        if scoped_project != self.project_id:
            raise ValueError("Synthetic Lab aggregate payload belongs to another Project")


@dataclass(frozen=True, kw_only=True)
class AuthorizationEnvelope:
    record: AuthorizationRecord
    submitted_by: UUID


@dataclass(frozen=True, kw_only=True)
class RuntimeInputSnapshot:
    project_id: UUID
    fact_snapshot_id: UUID
    fact_snapshot_hash: str
    profile_version_id: UUID
    profile_hash: str
    prompt_release_id: UUID
    prompt_release_hash: str
    facts_current_approved: bool
    profile_frozen: bool
    prompt_frozen: bool

    def __post_init__(self) -> None:
        for value in (
            self.fact_snapshot_hash,
            self.profile_hash,
            self.prompt_release_hash,
        ):
            if not _SHA256.fullmatch(value):
                raise ValueError("Synthetic Lab runtime input hashes must be SHA-256")


@dataclass(frozen=True, kw_only=True)
class SyntheticJob:
    durable: DurableJob
    runtime_inputs: RuntimeInputSnapshot | None
    authorization_binding: AuthorizationBinding | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("Synthetic Job version must be positive")
        payload = dict(self.durable.spec.payload)
        _validate_identifier_payload(payload)
        if (
            self.runtime_inputs is not None
            and self.runtime_inputs.project_id != self.durable.project_id
        ):
            raise ValueError("Durable Job runtime inputs belong to another Project")
        if self.authorization_binding is not None:
            if self.authorization_binding.project_id != self.durable.project_id:
                raise ValueError("Durable Job authorization belongs to another Project")

    @property
    def id(self) -> UUID:
        return self.durable.id

    @property
    def project_id(self) -> UUID:
        return self.durable.project_id

    @property
    def kind(self) -> str:
        return self.durable.spec.kind

    @property
    def input_hash(self) -> str:
        return self.durable.input_hash

    @property
    def payload(self) -> Mapping[str, object]:
        return self.durable.spec.payload

    @property
    def status(self) -> JobStatus:
        return self.durable.status

    @property
    def lease_id(self) -> UUID | None:
        return self.durable.lease_token

    @property
    def fencing_token(self) -> int:
        return self.durable.fencing_generation

    @property
    def cancel_requested(self) -> bool:
        return self.durable.cancel_requested_at is not None


@dataclass(frozen=True, kw_only=True)
class SyntheticOutboxMessage:
    id: UUID
    project_id: UUID
    job_id: UUID
    event_type: str
    payload_hash: str

    def __post_init__(self) -> None:
        if not self.event_type.strip() or not _SHA256.fullmatch(self.payload_hash):
            raise ValueError("Synthetic Lab outbox event type/hash is invalid")


@dataclass(frozen=True, kw_only=True)
class JobTerminalResult:
    project_id: UUID
    job_id: UUID
    job_kind: str
    result: object
    result_hash: str

    def __post_init__(self) -> None:
        if not self.job_kind.strip() or not _SHA256.fullmatch(self.result_hash):
            raise ValueError("Synthetic Lab terminal result kind/hash is invalid")


class SyntheticCommandRepository(Protocol):
    def get(
        self, *, project_id: UUID, idempotency_key_hash: str
    ) -> SyntheticCommandRecord | None: ...

    def stage(self, record: SyntheticCommandRecord) -> None: ...


class SyntheticAggregateRepository(Protocol):
    def get(
        self, *, project_id: UUID, kind: str, resource_id: UUID
    ) -> VersionedAggregate | None: ...

    def stage(self, aggregate: VersionedAggregate, *, expected_version: int) -> None: ...


class SyntheticAuthorizationRepository(Protocol):
    def current(
        self, *, project_id: UUID, channel: str, adapter_release: str
    ) -> AuthorizationEnvelope | None: ...

    def stage(self, envelope: AuthorizationEnvelope, *, expected_version: int) -> None: ...


class SyntheticImportRepository(Protocol):
    def contains_sample_hash(self, *, project_id: UUID, sample_hash: str) -> bool: ...

    def stage(
        self,
        *,
        manifest: ManualSampleImportManifest,
        decisions: tuple[ArtifactGovernanceDecision, ...],
    ) -> None: ...


class SyntheticJobRepository(Protocol):
    def get(self, *, project_id: UUID, job_id: UUID) -> SyntheticJob | None: ...

    def stage(self, job: SyntheticJob, *, expected_version: int) -> None: ...

    def stage_terminal(self, result: JobTerminalResult) -> None: ...


class SyntheticOutboxRepository(Protocol):
    def stage(self, message: SyntheticOutboxMessage) -> None: ...


class SyntheticLabUnitOfWork(Protocol):
    commands: SyntheticCommandRepository
    aggregates: SyntheticAggregateRepository
    authorizations: SyntheticAuthorizationRepository
    imports: SyntheticImportRepository
    jobs: SyntheticJobRepository
    outbox: SyntheticOutboxRepository
    execution_tasks: "SyntheticExecutionTaskStagingPort"
    style_collection_tasks: "StyleCollectionTaskStagingPort"

    def __enter__(self) -> "SyntheticLabUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...


class SyntheticLabUnitOfWorkFactory(Protocol):
    def __call__(self, *, project_id: UUID) -> SyntheticLabUnitOfWork: ...


class RuntimeInputPort(Protocol):
    def current(self, frozen: RuntimeInputSnapshot) -> RuntimeInputSnapshot: ...


class CollectionAuthorizationPort(Protocol):
    def current(self, binding: AuthorizationBinding) -> AuthorizationRecord | None: ...


class CustomerSyntheticProjectionPort(Protocol):
    def publish(self, *, project_id: UUID, result: object) -> None: ...


@dataclass
class StaticRuntimeInputPort:
    """Test adapter whose value can be replaced to exercise stale-input paths."""

    value: RuntimeInputSnapshot

    def current(self, frozen: RuntimeInputSnapshot) -> RuntimeInputSnapshot:
        if frozen.project_id != self.value.project_id:
            raise SyntheticLabStaleInput("runtime input Project changed")
        return self.value


@dataclass
class StaticCollectionAuthorizationPort:
    records: dict[tuple[UUID, str, str], AuthorizationRecord] = field(default_factory=dict)

    def current(self, binding: AuthorizationBinding) -> AuthorizationRecord | None:
        return self.records.get((binding.project_id, binding.channel, binding.adapter_release))


class DenyCustomerSyntheticProjection:
    def publish(self, *, project_id: UUID, result: object) -> None:
        del project_id, result
        raise SyntheticCustomerProjectionDenied(
            "Synthetic Lab output is Admin-only and cannot be projected to Customer"
        )


def _validate_identifier_payload(
    payload: Mapping[str, object],
) -> None:
    for key, value in payload.items():
        if not key.endswith(("_id", "_ids", "_hash", "_hashes")):
            raise ValueError("Durable Job payload may contain only ID/hash fields")
        values = value if isinstance(value, tuple) else (value,)
        if not values:
            raise ValueError("Durable Job identifier payload cannot contain an empty tuple")
        for item in values:
            if isinstance(item, UUID):
                continue
            if not isinstance(item, str) or not _SHA256.fullmatch(item):
                raise ValueError("Durable Job payload values must be UUIDs or SHA-256 hashes")


__all__ = [
    "AuthorizationEnvelope",
    "CollectionAuthorizationPort",
    "CommandReceipt",
    "CustomerSyntheticProjectionPort",
    "DenyCustomerSyntheticProjection",
    "DurableJob",
    "JobTerminalResult",
    "LabPrincipal",
    "LabRole",
    "RuntimeInputPort",
    "RuntimeInputSnapshot",
    "StaticCollectionAuthorizationPort",
    "StaticRuntimeInputPort",
    "SyntheticCommandIdentity",
    "SyntheticCommandOperation",
    "SyntheticCommandRecord",
    "SyntheticCustomerProjectionDenied",
    "SyntheticLabIdempotencyConflict",
    "SyntheticLabJobOwnershipLost",
    "SyntheticLabNotFound",
    "SyntheticLabPermissionDenied",
    "SyntheticLabPersistenceError",
    "SyntheticLabStaleInput",
    "SyntheticLabUnitOfWork",
    "SyntheticLabUnitOfWorkFactory",
    "SyntheticLabVersionConflict",
    "SyntheticOutboxMessage",
    "SyntheticJob",
    "VersionedAggregate",
]
