"""Lease-owned worker for governed Prompt Program test execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
import json
from typing import Protocol
from uuid import uuid5

from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LeaseHeartbeat,
    LostJobLease,
    PostgresDurableJobStore,
    WorkerLease,
)
from geo_core.model_gateway.contracts import ModelGatewayError, RetryableModelGatewayError
from geo_core.prompts.bootstrap_contracts import PromptBootstrapRuleViolation
from geo_core.prompts.bootstrap_evaluation import evaluate_prompt_test_set
from geo_core.prompts.program import (
    ProgramReleaseCommand,
    ProgramReleaseState,
    ProgramTestEvidence,
    PromptProgramRuleViolation,
    render_program_release,
    transition_release_state,
)
from geo_core.prompts.test_execution_contracts import (
    PROMPT_TEST_JOB_KIND,
    PROMPT_TEST_REQUIRED_JOB_KINDS,
    PromptTestArtifactStore,
    PromptTestArtifactReceipt,
    PromptTestCaseExecutor,
    PromptTestExecutionError,
    PromptTestExecutionRepository,
    PromptTestRunClaim,
    PromptTestRunResult,
    PromptTestRunTask,
    PromptTestStale,
)
from geo_core.prompts.program_contracts import _canonical_value


class JobHandler(Protocol):
    def handle(self, lease: WorkerLease) -> Mapping[str, object]: ...


class PromptTestExecutionHandler:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: PromptTestExecutionRepository,
        executor: PromptTestCaseExecutor,
        artifacts: PromptTestArtifactStore,
        lease_for: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if lease_for.total_seconds() < 3:
            raise ValueError("Prompt test lease must be at least three seconds")
        self._store = store
        self._repository = repository
        self._executor = executor
        self._artifacts = artifacts
        self._lease_for = lease_for
        self._clock = clock

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        try:
            claim = self._repository.load(lease)
            _assert_claim_matches_lease(claim, lease)
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=min(self._lease_for / 3, timedelta(seconds=30)),
            ) as heartbeat:
                def checkpoint() -> None:
                    self._checkpoint(lease, claim.task, heartbeat)

                checkpoint()
                cases = []
                outputs = {}
                for fixture in claim.task.test_spec.fixtures:
                    prompt = render_program_release(
                        release=claim.release,
                        variables={
                            "request_json": json.dumps(
                                _canonical_value(fixture.input_value),
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                                allow_nan=False,
                            )
                        },
                    )
                    case = self._executor.execute(
                        lease=lease,
                        task=claim.task,
                        prompt=prompt,
                        fixture_id=fixture.fixture_id,
                        fixture_hash=fixture.fixture_hash,
                        output_schema=claim.release.schemas.output_schema,
                        application_output_schema=(
                            claim.release.schemas.application_output_schema
                        ),
                    )
                    cases.append(case)
                    outputs[fixture.fixture_id] = case.output
                    checkpoint()
                evaluation = evaluate_prompt_test_set(claim.task.test_spec, outputs)
                result = PromptTestRunResult(
                    task=claim.task,
                    cases=tuple(cases),
                    evaluation=evaluation,
                )
                artifact = self._artifacts.persist(result)
                checkpoint()
            evidence, state = _passed_transition(
                claim,
                result,
                artifact,
                tested_at=self._clock(),
            )
            with self._store.fenced_transaction(lease) as connection:
                if result.passed:
                    assert evidence is not None and state is not None
                    self._repository.finalize_passed(
                        connection=connection,
                        lease=lease,
                        claim=claim,
                        result=result,
                        artifact=artifact,
                        evidence=evidence,
                        state=state,
                    )
                self._store.complete_in_transaction(
                    connection,
                    lease,
                    result_ref=artifact.uri,
                    details={
                        "passed": result.passed,
                        "score": result.evaluation.score,
                        "result_hash": result.result_hash,
                        "artifact_hash": artifact.content_hash,
                        "test_set_hash": claim.task.test_set_hash,
                    },
                )
            return {
                "status": "succeeded",
                "job_id": str(lease.job_id),
                "passed": result.passed,
                "score": result.evaluation.score,
                "result_hash": result.result_hash,
            }
        except (JobCancellationRequested, LostJobLease):
            raise
        except PromptTestStale:
            return self._fail(
                lease,
                error_code="prompt_test_stale",
                classification="stale_input",
                retry_delay=None,
            )
        except RetryableModelGatewayError as error:
            seconds = error.retry_after_seconds or 30.0
            return self._fail(
                lease,
                error_code=f"prompt_test_model_{error.code.value}",
                classification="retryable_model",
                retry_delay=timedelta(seconds=min(300.0, max(1.0, seconds))),
            )
        except ModelGatewayError as error:
            return self._fail(
                lease,
                error_code=f"prompt_test_model_{error.code.value}",
                classification="permanent_model",
                retry_delay=None,
            )
        except (
            PromptTestExecutionError,
            PromptBootstrapRuleViolation,
            PromptProgramRuleViolation,
        ):
            return self._fail(
                lease,
                error_code="prompt_test_contract",
                classification="contract",
                retry_delay=None,
            )
        except Exception as error:
            return self._fail(
                lease,
                error_code="prompt_test_internal",
                classification=type(error).__name__,
                retry_delay=timedelta(seconds=30),
            )

    def _checkpoint(
        self,
        lease: WorkerLease,
        task: PromptTestRunTask,
        heartbeat: LeaseHeartbeat,
    ) -> None:
        heartbeat.raise_if_stopped()
        self._store.heartbeat(lease, lease_for=self._lease_for)
        self._repository.assert_current(task)
        heartbeat.raise_if_stopped()

    def _fail(
        self,
        lease: WorkerLease,
        *,
        error_code: str,
        classification: str,
        retry_delay: timedelta | None,
    ) -> Mapping[str, object]:
        self._store.heartbeat(lease, lease_for=self._lease_for)
        status = self._store.fail(
            lease,
            error_code=error_code,
            details={"classification": classification},
            retry_delay=retry_delay,
        )
        return {"status": status, "job_id": str(lease.job_id)}


def build_prompt_test_worker_handlers(
    *,
    store: PostgresDurableJobStore,
    repository: PromptTestExecutionRepository,
    executor: PromptTestCaseExecutor,
    artifacts: PromptTestArtifactStore,
    lease_for: timedelta,
) -> Mapping[str, JobHandler]:
    return {
        PROMPT_TEST_JOB_KIND: PromptTestExecutionHandler(
            store=store,
            repository=repository,
            executor=executor,
            artifacts=artifacts,
            lease_for=lease_for,
        )
    }


def _passed_transition(
    claim: PromptTestRunClaim,
    result: PromptTestRunResult,
    artifact: PromptTestArtifactReceipt,
    *,
    tested_at: datetime,
) -> tuple[ProgramTestEvidence | None, ProgramReleaseState | None]:
    if not result.passed:
        return None, None
    state_id = uuid5(claim.task.job_id, "prompt-test-passed-state")
    evidence = ProgramTestEvidence(
        id=uuid5(claim.task.job_id, "prompt-test-passed-evidence"),
        project_id=claim.task.project_id,
        release_id=claim.release.id,
        release_hash=claim.release.release_hash,
        tested_state_id=state_id,
        test_set_id=claim.release.test_set_id,
        test_set_version=claim.release.test_set_version,
        output_artifact_ref=artifact.uri,
        output_hash=artifact.content_hash,
        tested_by=claim.task.requested_by,
        tested_at=tested_at,
    )
    state = transition_release_state(
        id=state_id,
        release=claim.release,
        current=claim.state,
        command=ProgramReleaseCommand.RECORD_TEST,
        actor_id=claim.task.requested_by,
        acted_at=tested_at,
        evidence_ref=evidence.state_evidence_ref,
    )
    return evidence, state


def _assert_claim_matches_lease(
    claim: PromptTestRunClaim,
    lease: WorkerLease,
) -> None:
    if (
        lease.kind != PROMPT_TEST_JOB_KIND
        or claim.task.job_id != lease.job_id
        or claim.task.project_id != lease.project_id
        or claim.release.id != claim.task.release_id
        or claim.release.release_hash != claim.task.release_hash
        or claim.release.version != claim.task.release_version
        or claim.release.test_set_id != claim.task.test_set_id
        or claim.release.test_set_version != claim.task.test_set_version
        or claim.release.test_set_hash != claim.task.test_set_hash
        or claim.state.id != claim.task.expected_state_id
        or claim.state.version != claim.task.expected_state_version
    ):
        raise PromptTestStale("Prompt test claim no longer matches its frozen task")


__all__ = [
    "PROMPT_TEST_REQUIRED_JOB_KINDS",
    "PromptTestExecutionHandler",
    "build_prompt_test_worker_handlers",
]
