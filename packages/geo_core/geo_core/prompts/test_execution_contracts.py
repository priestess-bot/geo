"""Immutable contracts for governed Prompt Program test execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.contracts import ModelCaptureMethod, ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.prompts.bootstrap_contracts import (
    BOOTSTRAP_TEST_SET_VERSION,
    PromptBootstrapSpec,
)
from geo_core.prompts.bootstrap_evaluation import PromptTestSetEvaluation
from geo_core.prompts.ports import PromptProgramRepository
from geo_core.prompts.program import (
    CompiledProgramPrompt,
    ProgramReleaseState,
    ProgramTestEvidence,
    PromptProgramRelease,
)
from geo_core.prompts.program_contracts import _canonical_hash, _canonical_value
from geo_core.secrets.models import SecretVersionHandle


PROMPT_TEST_JOB_KIND = "prompt.test.execute"
PROMPT_TEST_REQUIRED_JOB_KINDS = frozenset({PROMPT_TEST_JOB_KIND})
PROMPT_TEST_OUTBOX_TOPIC = "prompt.test.execute.queued"
PROMPT_TEST_ARTIFACT_SCHEMA = "geo.prompt-test-run.v1"
# Five fixtures may each consume one call on each of three durable Job attempts.
PROMPT_TEST_MAXIMUM_PAID_CALLS = 15


class PromptTestExecutionError(RuntimeError):
    """A governed Prompt test cannot safely continue."""


class PromptTestStale(PromptTestExecutionError):
    """A frozen Release, state, TestSet or Model route changed before completion."""


class PromptTestNotPassed(PromptTestExecutionError):
    """A completed run did not meet its frozen pass criteria."""


@dataclass(frozen=True)
class PromptTestRouteRequest:
    runtime_selection_id: UUID

    def __post_init__(self) -> None:
        _require_uuid(self.runtime_selection_id, "runtime selection")


@dataclass(frozen=True)
class PromptTestRuntimeOption:
    runtime_selection_id: UUID
    runtime_selection_hash: str
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    provider: str
    adapter_release_id: str
    adapter_release_hash: str
    model_release_id: str
    model_release_hash: str
    configured_model: str
    capture_method: ModelCaptureMethod
    policy_version_id: UUID
    policy_version_hash: str

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.runtime_selection_id, "runtime selection"),
            (self.runtime_manifest_id, "runtime manifest"),
            (self.policy_version_id, "Model policy"),
        ):
            _require_uuid(uuid_value, label)
        for hash_value, label in (
            (self.runtime_selection_hash, "runtime selection"),
            (self.runtime_manifest_hash, "runtime manifest"),
            (self.adapter_release_hash, "Adapter Release"),
            (self.model_release_hash, "Model Release"),
            (self.policy_version_hash, "Model policy"),
        ):
            _require_hash(hash_value, label)
        for text_value, label in (
            (self.provider, "Provider"),
            (self.adapter_release_id, "Adapter Release"),
            (self.model_release_id, "Model Release"),
            (self.configured_model, "configured model"),
        ):
            _require_text(text_value, label)
        object.__setattr__(self, "capture_method", ModelCaptureMethod(self.capture_method))


@dataclass(frozen=True)
class PromptTestModelSelection:
    runtime_selection_id: UUID
    runtime_selection_hash: str
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    route: ModelRoute
    configured_model: str
    capture_method: ModelCaptureMethod
    policy_version_id: UUID
    policy_version_hash: str
    policy: ModelPolicy
    provider_secret_handle: SecretVersionHandle

    def __post_init__(self) -> None:
        _require_uuid(self.runtime_selection_id, "runtime selection")
        _require_uuid(self.runtime_manifest_id, "runtime manifest")
        _require_uuid(self.policy_version_id, "Model policy")
        _require_hash(self.runtime_selection_hash, "runtime selection")
        _require_hash(self.runtime_manifest_hash, "runtime manifest")
        _require_hash(self.policy_version_hash, "Model policy")
        _require_text(self.configured_model, "configured model")
        object.__setattr__(self, "capture_method", ModelCaptureMethod(self.capture_method))
        if (
            self.policy.policy_version_id != self.policy_version_id
            or self.policy.policy_version_hash != self.policy_version_hash
            or self.policy.maximum_paid_calls is None
            or self.policy.maximum_paid_calls < PROMPT_TEST_MAXIMUM_PAID_CALLS
        ):
            raise PromptTestExecutionError(
                "Prompt test Model policy cannot cover the frozen five-case retry budget"
            )
        if self.provider_secret_handle.purpose != f"model_provider.{self.route.provider}":
            raise PromptTestExecutionError(
                "Prompt test Provider Secret purpose does not match the frozen route"
            )

    def canonical_value(self) -> Mapping[str, object]:
        return {
            "runtime_selection_id": str(self.runtime_selection_id),
            "runtime_selection_hash": self.runtime_selection_hash,
            "runtime_manifest_id": str(self.runtime_manifest_id),
            "runtime_manifest_hash": self.runtime_manifest_hash,
            "route": {
                "provider": self.route.provider,
                "adapter_release_id": self.route.adapter_release_id,
                "adapter_release_hash": self.route.adapter_release_hash,
                "model_release_id": self.route.model_release_id,
                "model_release_hash": self.route.model_release_hash,
            },
            "configured_model": self.configured_model,
            "capture_method": self.capture_method.value,
            "policy_version_id": str(self.policy_version_id),
            "policy_version_hash": self.policy_version_hash,
            "policy": self.policy.canonical_value(),
            "provider_secret_handle": self.provider_secret_handle.as_job_payload(),
        }


class PromptTestRuntimeSelector(Protocol):
    def list_approved(
        self,
        *,
        project_id: UUID,
    ) -> tuple[PromptTestRuntimeOption, ...]: ...

    def select(
        self,
        *,
        project_id: UUID,
        request: PromptTestRouteRequest,
    ) -> PromptTestModelSelection: ...


@dataclass(frozen=True, kw_only=True)
class PromptTestRunTask:
    project_id: UUID
    job_id: UUID
    program_id: UUID
    release_id: UUID
    release_version: int
    release_hash: str
    expected_state_id: UUID
    expected_state_version: int
    requested_by: UUID
    requested_at: datetime
    test_spec: PromptBootstrapSpec
    catalog_hash: str
    model: PromptTestModelSelection
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.project_id, "Prompt test Project"),
            (self.job_id, "Prompt test Job"),
            (self.program_id, "Prompt Program"),
            (self.release_id, "Prompt Release"),
            (self.expected_state_id, "Prompt Release state"),
            (self.requested_by, "Prompt test actor"),
        ):
            _require_uuid(value, label)
        if self.release_version < 1 or self.expected_state_version < 1:
            raise PromptTestExecutionError(
                "Prompt test Release and state versions must be positive"
            )
        _require_hash(self.release_hash, "Prompt Release")
        _require_hash(self.catalog_hash, "Prompt catalog")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise PromptTestExecutionError("Prompt test request time must be timezone-aware")
        if self.test_spec.test_set_id.int == 0:
            raise PromptTestExecutionError("Prompt test TestSet ID cannot be zero")
        object.__setattr__(self, "input_hash", _canonical_hash(self.canonical_value()))

    @property
    def test_set_id(self) -> UUID:
        return self.test_spec.test_set_id

    @property
    def test_set_version(self) -> int:
        return BOOTSTRAP_TEST_SET_VERSION

    @property
    def test_set_hash(self) -> str:
        return self.test_spec.test_set_hash

    @property
    def spec_hash(self) -> str:
        return self.test_spec.spec_hash

    def canonical_value(self) -> Mapping[str, object]:
        return {
            "schema_version": "geo.prompt-test-task.v1",
            "project_id": str(self.project_id),
            "job_id": str(self.job_id),
            "program_id": str(self.program_id),
            "release_id": str(self.release_id),
            "release_version": self.release_version,
            "release_hash": self.release_hash,
            "expected_state_id": str(self.expected_state_id),
            "expected_state_version": self.expected_state_version,
            "requested_by": str(self.requested_by),
            "test_set_id": str(self.test_set_id),
            "test_set_version": self.test_set_version,
            "test_set_hash": self.test_set_hash,
            "spec_hash": self.spec_hash,
            "catalog_hash": self.catalog_hash,
            "test_spec": self.test_spec.canonical_value(),
            "model": self.model.canonical_value(),
        }


@dataclass(frozen=True)
class PromptTestJob:
    id: UUID
    project_id: UUID
    release_id: UUID
    release_hash: str
    test_set_id: UUID
    test_set_version: int
    test_set_hash: str
    input_hash: str
    status: Literal[
        "queued",
        "running",
        "finalizing",
        "retry_wait",
        "succeeded",
        "failed",
        "dead_lettered",
        "cancelled",
    ] = "queued"

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "Prompt test Job"),
            (self.project_id, "Prompt test Project"),
            (self.release_id, "Prompt test Release"),
            (self.test_set_id, "Prompt test TestSet"),
        ):
            _require_uuid(value, label)
        _require_hash(self.release_hash, "Prompt Release")
        _require_hash(self.test_set_hash, "Prompt TestSet")
        _require_hash(self.input_hash, "Prompt test input")
        if self.test_set_version < 1:
            raise PromptTestExecutionError("Prompt test TestSet version must be positive")


@dataclass(frozen=True)
class PromptTestJobReceipt:
    value: PromptTestJob
    replayed: bool


@dataclass(frozen=True)
class StoredPromptTestJob:
    job: PromptTestJob
    replayed: bool


class PromptTestRunRepository(Protocol):
    def enqueue(
        self,
        *,
        task: PromptTestRunTask,
        idempotency_key_hash: str,
        outbox_id: UUID,
    ) -> StoredPromptTestJob: ...


class PromptTestUnitOfWork(Protocol):
    prompts: PromptProgramRepository
    test_runs: PromptTestRunRepository

    def __enter__(self) -> "PromptTestUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> bool | None: ...

    def commit(self) -> None: ...


class PromptTestUnitOfWorkFactory(Protocol):
    def __call__(self, *, project_id: UUID) -> PromptTestUnitOfWork: ...


@dataclass(frozen=True)
class PromptTestRunClaim:
    task: PromptTestRunTask
    release: PromptProgramRelease
    state: ProgramReleaseState


@dataclass(frozen=True)
class PromptTestCaseModelResult:
    fixture_id: str
    fixture_hash: str
    model_call_id: UUID
    response_hash: str
    output: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_text(self.fixture_id, "Prompt test fixture")
        _require_hash(self.fixture_hash, "Prompt test fixture")
        _require_uuid(self.model_call_id, "Prompt test model call")
        _require_hash(self.response_hash, "Prompt test response")
        object.__setattr__(
            self,
            "output",
            MappingProxyType(
                cast(dict[str, object], _canonical_value(self.output))
            ),
        )


@dataclass(frozen=True)
class PromptTestRunResult:
    task: PromptTestRunTask
    cases: tuple[PromptTestCaseModelResult, ...]
    evaluation: PromptTestSetEvaluation
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        cases = tuple(self.cases)
        expected = tuple(item.fixture_id for item in self.task.test_spec.fixtures)
        actual = tuple(item.fixture_id for item in cases)
        if actual != expected or len(set(actual)) != len(actual):
            raise PromptTestExecutionError(
                "Prompt test model results do not match the frozen fixture order"
            )
        fixture_hashes = {
            item.fixture_id: item.fixture_hash for item in self.task.test_spec.fixtures
        }
        if any(item.fixture_hash != fixture_hashes[item.fixture_id] for item in cases):
            raise PromptTestExecutionError("Prompt test fixture hash changed during execution")
        if (
            self.evaluation.spec_hash != self.task.spec_hash
            or self.evaluation.test_set_id != str(self.task.test_set_id)
            or self.evaluation.test_set_hash != self.task.test_set_hash
        ):
            raise PromptTestExecutionError("Prompt test evaluation lineage is inconsistent")
        object.__setattr__(self, "cases", cases)
        object.__setattr__(
            self,
            "result_hash",
            _canonical_hash(
                {
                    "task_input_hash": self.task.input_hash,
                    "evaluation_result_hash": self.evaluation.result_hash,
                    "model_calls": [
                        {
                            "fixture_id": item.fixture_id,
                            "fixture_hash": item.fixture_hash,
                            "model_call_id": str(item.model_call_id),
                            "response_hash": item.response_hash,
                        }
                        for item in cases
                    ],
                }
            ),
        )

    @property
    def passed(self) -> bool:
        return self.evaluation.passed

    def artifact_value(self) -> Mapping[str, object]:
        return {
            "schema_version": PROMPT_TEST_ARTIFACT_SCHEMA,
            "project_id": str(self.task.project_id),
            "job_id": str(self.task.job_id),
            "program_id": str(self.task.program_id),
            "release_id": str(self.task.release_id),
            "release_version": self.task.release_version,
            "release_hash": self.task.release_hash,
            "test_set_id": str(self.task.test_set_id),
            "test_set_version": self.task.test_set_version,
            "test_set_hash": self.task.test_set_hash,
            "spec_hash": self.task.spec_hash,
            "catalog_hash": self.task.catalog_hash,
            "task_input_hash": self.task.input_hash,
            "model": self.task.model.canonical_value(),
            "cases": [
                {
                    "fixture_id": item.fixture_id,
                    "fixture_hash": item.fixture_hash,
                    "model_call_id": str(item.model_call_id),
                    "response_hash": item.response_hash,
                    "output": _canonical_value(item.output),
                }
                for item in self.cases
            ],
            "evaluation": {
                "result_hash": self.evaluation.result_hash,
                "score": self.evaluation.score,
                "passed": self.evaluation.passed,
                "case_results": [
                    item.canonical_value() for item in self.evaluation.case_results
                ],
            },
            "result_hash": self.result_hash,
        }


@dataclass(frozen=True)
class PromptTestArtifactReceipt:
    uri: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_text(self.uri, "Prompt test artifact URI")
        _require_hash(self.content_hash, "Prompt test artifact")


class PromptTestCaseExecutor(Protocol):
    def execute(
        self,
        *,
        lease: WorkerLease,
        task: PromptTestRunTask,
        prompt: CompiledProgramPrompt,
        fixture_id: str,
        fixture_hash: str,
        output_schema: Mapping[str, object],
        application_output_schema: Mapping[str, object],
    ) -> PromptTestCaseModelResult: ...


class PromptTestArtifactStore(Protocol):
    def persist(self, result: PromptTestRunResult) -> PromptTestArtifactReceipt: ...


class PromptTestExecutionRepository(Protocol):
    def load(self, lease: WorkerLease) -> PromptTestRunClaim: ...

    def assert_current(self, task: PromptTestRunTask) -> None: ...

    def finalize_passed(
        self,
        *,
        connection: object,
        lease: WorkerLease,
        claim: PromptTestRunClaim,
        result: PromptTestRunResult,
        artifact: PromptTestArtifactReceipt,
        evidence: ProgramTestEvidence,
        state: ProgramReleaseState,
    ) -> None: ...


class PromptTestEvidenceVerifier(Protocol):
    def verify(
        self,
        *,
        release: PromptProgramRelease,
        evidence: ProgramTestEvidence,
    ) -> None: ...


def _require_uuid(value: UUID, label: str) -> None:
    if value.int == 0:
        raise PromptTestExecutionError(f"{label} ID cannot be zero")


def _require_text(value: str, label: str) -> None:
    if not value.strip():
        raise PromptTestExecutionError(f"{label} cannot be empty")


def _require_hash(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise PromptTestExecutionError(f"{label} hash must be lowercase SHA-256")


__all__ = [
    "PROMPT_TEST_ARTIFACT_SCHEMA",
    "PROMPT_TEST_JOB_KIND",
    "PROMPT_TEST_REQUIRED_JOB_KINDS",
    "PROMPT_TEST_OUTBOX_TOPIC",
    "PromptTestArtifactReceipt",
    "PromptTestArtifactStore",
    "PromptTestCaseExecutor",
    "PromptTestCaseModelResult",
    "PromptTestEvidenceVerifier",
    "PromptTestExecutionError",
    "PromptTestExecutionRepository",
    "PromptTestJob",
    "PromptTestJobReceipt",
    "PromptTestModelSelection",
    "PromptTestNotPassed",
    "PromptTestRouteRequest",
    "PromptTestRunClaim",
    "PromptTestRunRepository",
    "PromptTestRunResult",
    "PromptTestRunTask",
    "PromptTestRuntimeOption",
    "PromptTestRuntimeSelector",
    "PromptTestStale",
    "PromptTestUnitOfWork",
    "PromptTestUnitOfWorkFactory",
    "StoredPromptTestJob",
]
