"""Lease-owned PostgreSQL repository for governed Prompt test execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.contracts import ModelCaptureMethod, ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.project_scope import set_project_scope
from geo_core.prompts.bootstrap_catalog import (
    default_prompt_bootstrap_spec,
    prompt_bootstrap_catalog_hash,
)
from geo_core.prompts.ports import PromptProgramVersionConflict
from geo_core.prompts.postgres_repository import PsycopgPromptProgramRepository
from geo_core.prompts.postgres_serialization import plain_json
from geo_core.prompts.program import (
    ProgramReleaseState,
    ProgramReleaseStatus,
    ProgramTestEvidence,
    PromptProgramRelease,
)
from geo_core.prompts.test_execution_contracts import (
    PROMPT_TEST_JOB_KIND,
    PromptTestArtifactReceipt,
    PromptTestExecutionError,
    PromptTestExecutionRepository,
    PromptTestModelSelection,
    PromptTestRunClaim,
    PromptTestRunResult,
    PromptTestRunTask,
    PromptTestStale,
)
from geo_core.secrets.models import SecretVersionHandle


class PostgresPromptTestExecutionRepository(PromptTestExecutionRepository):
    """Load and finalize only the immutable task owned by an active lease."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def load(self, lease: WorkerLease) -> PromptTestRunClaim:
        connection = self._connection_factory()
        try:
            set_project_scope(connection, lease.project_id)
            row = _one(
                connection.execute(
                    """SELECT task.program_id, task.release_id, task.release_version,
                              task.release_hash, task.expected_state_id,
                              task.expected_state_version, task.test_set_id,
                              task.test_set_version, task.test_set_hash, task.spec_hash,
                              task.catalog_hash, task.requested_by, task.requested_at,
                              task.task_payload, task.task_payload_hash,
                              task.expected_job_input_hash,
                              job.kind, job.status, job.input_hash, job.lease_owner,
                              job.lease_token, job.fencing_generation,
                              job.lease_expires_at, job.cancel_requested_at
                       FROM prompt_program_test_run_tasks AS task
                       JOIN durable_jobs AS job
                         ON job.id = task.job_id AND job.project_id = task.project_id
                       WHERE task.project_id = %s AND task.job_id = %s""",
                    (lease.project_id, lease.job_id),
                )
            )
            if row is None:
                raise PromptTestExecutionError(
                    "Claimed Prompt test Job has no frozen execution task"
                )
            _assert_active_lease(row, lease)
            repository = PsycopgPromptProgramRepository(connection)
            release_id = _uuid(row["release_id"], "Prompt Release")
            release = repository.get_release(
                project_id=lease.project_id,
                release_id=release_id,
            )
            state = repository.get_current_release_state(
                project_id=lease.project_id,
                release_id=release_id,
            )
            if release is None or state is None:
                raise PromptTestStale("Prompt test Release no longer exists")
            task = _task_from_row(
                project_id=lease.project_id,
                job_id=lease.job_id,
                row=row,
                release=release,
            )
            _assert_task_current(task=task, release=release, state=state)
            return PromptTestRunClaim(task=task, release=release, state=state)
        finally:
            connection.rollback()
            connection.close()

    def assert_current(self, task: PromptTestRunTask) -> None:
        connection = self._connection_factory()
        try:
            set_project_scope(connection, task.project_id)
            repository = PsycopgPromptProgramRepository(connection)
            release = repository.get_release(
                project_id=task.project_id,
                release_id=task.release_id,
            )
            state = repository.get_current_release_state(
                project_id=task.project_id,
                release_id=task.release_id,
            )
            if release is None or state is None:
                raise PromptTestStale("Prompt test Release no longer exists")
            _assert_task_current(task=task, release=release, state=state)
            row = _one(
                connection.execute(
                    """SELECT task_payload, task_payload_hash, expected_job_input_hash
                       FROM prompt_program_test_run_tasks
                       WHERE project_id = %s AND job_id = %s""",
                    (task.project_id, task.job_id),
                )
            )
            if row is None or not _payload_matches_task(row, task):
                raise PromptTestStale("Prompt test frozen task changed")
        finally:
            connection.rollback()
            connection.close()

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
    ) -> None:
        database = cast(Any, connection)
        if not result.passed:
            raise PromptTestExecutionError(
                "Only a server-evaluated passing Prompt test may create evidence"
            )
        if (
            lease.project_id != claim.task.project_id
            or lease.job_id != claim.task.job_id
            or result.task != claim.task
            or artifact.uri != evidence.output_artifact_ref
            or artifact.content_hash != evidence.output_hash
            or evidence.tested_state_id != state.id
            or evidence.tested_by != claim.task.requested_by
            or state.acted_by != claim.task.requested_by
        ):
            raise PromptTestExecutionError(
                "Prompt test finalization changed frozen execution lineage"
            )
        _assert_task_current(
            task=claim.task,
            release=claim.release,
            state=claim.state,
        )
        stored = _one(
            database.execute(
                """SELECT task_payload, task_payload_hash, expected_job_input_hash
                   FROM prompt_program_test_run_tasks
                   WHERE project_id = %s AND job_id = %s""",
                (lease.project_id, lease.job_id),
            )
        )
        if stored is None or not _payload_matches_task(stored, claim.task):
            raise PromptTestStale("Prompt test frozen task changed before finalization")
        try:
            PsycopgPromptProgramRepository(database).store_worker_test_transition(
                project_id=lease.project_id,
                release=claim.release,
                state=state,
                expected_version=claim.state.version,
                test_evidence=evidence,
            )
        except PromptProgramVersionConflict as error:
            raise PromptTestStale(
                "Prompt test Release changed before finalization"
            ) from error


def build_prompt_test_execution_repository(
    database_url: str,
) -> PostgresPromptTestExecutionRepository:
    normalized = database_url.strip()
    if not normalized:
        raise ValueError("Prompt test database URL cannot be empty")

    def connect() -> Any:
        return psycopg.connect(normalized, row_factory=dict_row)

    return PostgresPromptTestExecutionRepository(connect)


def _task_from_row(
    *,
    project_id: UUID,
    job_id: UUID,
    row: Mapping[str, object],
    release: PromptProgramRelease,
) -> PromptTestRunTask:
    payload = _mapping(row["task_payload"], "Prompt test task")
    spec = default_prompt_bootstrap_spec(release.program_kind)
    if payload.get("test_spec") != plain_json(spec.canonical_value()):
        raise PromptTestStale("Prompt test immutable TestSet snapshot changed")
    task = PromptTestRunTask(
        project_id=project_id,
        job_id=job_id,
        program_id=_uuid(row["program_id"], "Prompt Program"),
        release_id=_uuid(row["release_id"], "Prompt Release"),
        release_version=_positive_int(row["release_version"], "Release version"),
        release_hash=_hash(row["release_hash"], "Prompt Release"),
        expected_state_id=_uuid(row["expected_state_id"], "Prompt state"),
        expected_state_version=_positive_int(
            row["expected_state_version"], "Prompt state version"
        ),
        requested_by=_uuid(row["requested_by"], "Prompt test actor"),
        requested_at=_aware_datetime(row["requested_at"]),
        test_spec=spec,
        catalog_hash=_hash(row["catalog_hash"], "Prompt catalog"),
        model=_model_selection(payload.get("model"), project_id=project_id),
    )
    expected_columns = {
        "release_version": task.release_version,
        "release_hash": task.release_hash,
        "expected_state_id": task.expected_state_id,
        "expected_state_version": task.expected_state_version,
        "test_set_id": task.test_set_id,
        "test_set_version": task.test_set_version,
        "test_set_hash": task.test_set_hash,
        "spec_hash": task.spec_hash,
        "catalog_hash": task.catalog_hash,
    }
    if any(row[key] != value for key, value in expected_columns.items()):
        raise PromptTestStale("Prompt test task columns differ from its frozen payload")
    if not _payload_matches_task(row, task):
        raise PromptTestStale("Prompt test task hash or payload changed")
    return task


def _model_selection(value: object, *, project_id: UUID) -> PromptTestModelSelection:
    model = _mapping(value, "Prompt test Model selection")
    route = _mapping(model.get("route"), "Prompt test Model route")
    secret = _mapping(
        model.get("provider_secret_handle"),
        "Prompt test Provider Secret handle",
    )
    if (
        set(model)
        != {
            "runtime_selection_id",
            "runtime_selection_hash",
            "runtime_manifest_id",
            "runtime_manifest_hash",
            "route",
            "configured_model",
            "capture_method",
            "policy_version_id",
            "policy_version_hash",
            "policy",
            "provider_secret_handle",
        }
        or set(route)
        != {
            "provider",
            "adapter_release_id",
            "adapter_release_hash",
            "model_release_id",
            "model_release_hash",
        }
        or set(secret)
        != {
            "secret_reference_id",
            "secret_project_id",
            "secret_purpose",
            "secret_version",
        }
    ):
        raise PromptTestExecutionError(
            "Prompt test Model selection fields differ from the frozen schema"
        )
    handle = SecretVersionHandle(
        reference_id=_uuid(secret["secret_reference_id"], "Provider Secret"),
        project_id=_uuid(secret["secret_project_id"], "Provider Secret Project"),
        purpose=_text(secret["secret_purpose"], "Provider Secret purpose"),
        version=_positive_int(secret["secret_version"], "Provider Secret version"),
    )
    if handle.project_id != project_id:
        raise PromptTestExecutionError(
            "Prompt test Provider Secret belongs to another Project"
        )
    policy_value = _mapping(model["policy"], "Prompt test Model policy")
    if set(policy_value) != {
        "external_training_allowed",
        "structured_output_required",
        "allowed_providers",
        "allowed_adapter_release_ids",
        "maximum_paid_calls",
        "maximum_concurrent_calls",
    }:
        raise PromptTestExecutionError(
            "Prompt test Model policy fields differ from the frozen schema"
        )
    policy_version_id = _uuid(model["policy_version_id"], "Model policy")
    policy = ModelPolicy(
        external_training_allowed=_boolean(
            policy_value["external_training_allowed"], "external training policy"
        ),
        structured_output_required=_boolean(
            policy_value["structured_output_required"], "structured output policy"
        ),
        allowed_providers=frozenset(
            _string_list(policy_value["allowed_providers"], "allowed Providers")
        ),
        allowed_adapter_release_ids=frozenset(
            _string_list(
                policy_value["allowed_adapter_release_ids"],
                "allowed Adapter Releases",
            )
        ),
        policy_version_id=policy_version_id,
        maximum_paid_calls=_positive_int(
            policy_value["maximum_paid_calls"], "paid-call budget"
        ),
        maximum_concurrent_calls=_positive_int(
            policy_value["maximum_concurrent_calls"], "concurrency budget"
        ),
    )
    return PromptTestModelSelection(
        runtime_selection_id=_uuid(
            model["runtime_selection_id"], "runtime selection"
        ),
        runtime_selection_hash=_hash(
            model["runtime_selection_hash"], "runtime selection"
        ),
        runtime_manifest_id=_uuid(model["runtime_manifest_id"], "runtime manifest"),
        runtime_manifest_hash=_hash(model["runtime_manifest_hash"], "runtime manifest"),
        route=ModelRoute(
            provider=_text(route["provider"], "Provider"),
            adapter_release_id=_text(route["adapter_release_id"], "Adapter Release"),
            adapter_release_hash=_hash(
                route["adapter_release_hash"], "Adapter Release"
            ),
            model_release_id=_text(route["model_release_id"], "Model Release"),
            model_release_hash=_hash(route["model_release_hash"], "Model Release"),
        ),
        configured_model=_text(model["configured_model"], "configured model"),
        capture_method=ModelCaptureMethod(
            _text(model["capture_method"], "capture method")
        ),
        policy_version_id=policy_version_id,
        policy_version_hash=_hash(model["policy_version_hash"], "Model policy"),
        policy=policy,
        provider_secret_handle=handle,
    )


def _assert_active_lease(row: Mapping[str, object], lease: WorkerLease) -> None:
    expires_at = row.get("lease_expires_at")
    if (
        row.get("kind") != PROMPT_TEST_JOB_KIND
        or lease.kind != PROMPT_TEST_JOB_KIND
        or row.get("status") not in {"running", "finalizing"}
        or row.get("lease_owner") != lease.worker_id
        or row.get("lease_token") != lease.lease_token
        or row.get("fencing_generation") != lease.fencing_generation
        or not isinstance(expires_at, datetime)
        or expires_at <= datetime.now(UTC)
        or row.get("cancel_requested_at") is not None
        or row.get("input_hash") != row.get("task_payload_hash")
        or row.get("input_hash") != row.get("expected_job_input_hash")
    ):
        raise PromptTestStale("Prompt test execution lease is stale or cancelled")


def _assert_task_current(
    *,
    task: PromptTestRunTask,
    release: PromptProgramRelease,
    state: ProgramReleaseState,
) -> None:
    if (
        release.project_id != task.project_id
        or release.program_id != task.program_id
        or release.id != task.release_id
        or release.version != task.release_version
        or release.release_hash != task.release_hash
        or release.test_set_id != task.test_set_id
        or release.test_set_version != task.test_set_version
        or release.test_set_hash != task.test_set_hash
        or state.id != task.expected_state_id
        or state.version != task.expected_state_version
        or state.release_hash != task.release_hash
        or state.status is not ProgramReleaseStatus.DRAFT
        or task.catalog_hash != prompt_bootstrap_catalog_hash()
    ):
        raise PromptTestStale("Prompt test Release, state, TestSet or catalog changed")


def _payload_matches_task(
    row: Mapping[str, object], task: PromptTestRunTask
) -> bool:
    return (
        row.get("task_payload") == plain_json(task.canonical_value())
        and row.get("task_payload_hash") == task.input_hash
        and row.get("expected_job_input_hash") == task.input_hash
    )


def _one(cursor: Any) -> dict[str, object] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip((item.name for item in cursor.description), row, strict=True))


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise PromptTestExecutionError(f"{label} must be an object")
    return dict(cast(Mapping[str, object], value))


def _uuid(value: object, label: str) -> UUID:
    try:
        parsed = value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PromptTestExecutionError(f"{label} identity is invalid") from error
    if parsed.int == 0:
        raise PromptTestExecutionError(f"{label} identity is invalid")
    return parsed


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise PromptTestExecutionError(f"{label} must be positive")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise PromptTestExecutionError(f"{label} must be boolean")
    return value


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PromptTestExecutionError(f"{label} must be an array")
    items = tuple(_text(item, label) for item in value)
    if not items or len(items) != len(set(items)):
        raise PromptTestExecutionError(f"{label} must be non-empty and unique")
    return items


def _aware_datetime(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise PromptTestExecutionError("Prompt test request time is invalid")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PromptTestExecutionError(f"{label} cannot be empty")
    return value


def _hash(value: object, label: str) -> str:
    rendered = _text(value, f"{label} hash")
    if len(rendered) != 64 or any(
        character not in "0123456789abcdef" for character in rendered
    ):
        raise PromptTestExecutionError(f"{label} hash is invalid")
    return rendered


__all__ = [
    "PostgresPromptTestExecutionRepository",
    "build_prompt_test_execution_repository",
]
