"""Durable Internal API control for frozen Workflow C Sampling Suites."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid5

from geo_api.workflow_c_sampling_catalog import (
    ResolvedSamplingSuiteInputs,
    select_sampling_questions,
)
from geo_api.workflow_c_sampling_contracts import CreateSamplingSuiteRequest
from geo_api.workflow_c_sampling_ids import sampling_command_id
from geo_api.workflow_c_sampling_postgres_policy import (
    PostgresWorkflowCSamplingPolicyControl,
)
from geo_core.sampling import (
    CaptureMethod,
    PersistentSamplingSuiteInput,
    PersistentProviderSamplingExecutionInput,
    PostgresProviderSamplingExecutionInputRepository,
    PostgresSamplingSuiteRepository,
    ProviderSamplingExecutionInput,
    ProviderSamplingExecutionInputError,
    SamplingConflict,
    SamplingSuite,
)
from geo_core.sampling.postgres_suites import SAMPLING_SUITE_INPUT_NAMESPACE


class PostgresWorkflowCSamplingSuiteControl:
    """Create Suites only from approved persistent selector combinations."""

    persistence = "durable"

    def __init__(
        self,
        *,
        repository: PostgresSamplingSuiteRepository,
        execution_inputs: PostgresProviderSamplingExecutionInputRepository,
        policies: PostgresWorkflowCSamplingPolicyControl,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._execution_inputs = execution_inputs
        self._policies = policies
        self._clock = clock
        self.inputs = _PostgresSamplingSuiteInputs(repository)

    def create(
        self,
        *,
        project_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: CreateSamplingSuiteRequest,
    ) -> SamplingSuite:
        resolved = self.inputs.resolve(
            project_id=project_id,
            option_key=payload.suite_input_option_key,
        )
        policy = self._policies.record(project_id, resolved.admission_policy_id)
        policy.approved_policy(at=self._clock())
        if policy.definition_hash != resolved.admission_policy_hash:
            raise SamplingConflict("Suite admission policy selector is stale")
        source = resolved.source_stratum
        if (
            policy.platform != source.platform
            or policy.capture_method is not source.capture_method
            or policy.adapter_release != source.adapter_release
            or policy.location_control is not source.location_control
            or policy.location_evidence_hash != source.location_evidence_hash
        ):
            raise SamplingConflict("Suite catalog target differs from admission policy")
        questions, selected_item_ids = select_sampling_questions(
            resolved, payload.question_set_item_ids
        )
        now = self._clock()
        suite = SamplingSuite(
            id=sampling_command_id(project_id, "suite", idempotency_key),
            project_id=project_id,
            question_set_id=resolved.question_set_id,
            question_set_version=resolved.question_set_version,
            question_set_hash=resolved.question_set_hash,
            adapter_release_id=resolved.adapter_release_id,
            adapter_release_hash=resolved.adapter_release_hash,
            model_release_id=resolved.model_release_id,
            model_release_hash=resolved.model_release_hash,
            route_policy_id=resolved.route_policy_id,
            route_policy_hash=resolved.route_policy_hash,
            runtime_manifest_id=resolved.runtime_manifest_id,
            runtime_manifest_hash=resolved.runtime_manifest_hash,
            runtime_option_id=resolved.runtime_option_id,
            runtime_option_hash=resolved.runtime_option_hash,
            admission_policy_id=resolved.admission_policy_id,
            admission_policy_hash=resolved.admission_policy_hash,
            questions=questions,
            source_stratum=source,
            repetitions=payload.repetitions,
            statistics_method_version=payload.statistics_method_version,
            max_planned_tasks=payload.max_planned_tasks,
            max_daily_tasks=payload.max_daily_tasks,
            minimum_request_interval_seconds=payload.minimum_request_interval_seconds,
            max_concurrency=payload.max_concurrency,
            frozen_by=actor_id,
            frozen_at=now,
        )
        return self._repository.create_suite(
            suite,
            input_option=resolved,
            idempotency_key=idempotency_key,
            selected_question_set_item_ids=selected_item_ids,
        )

    def get(self, *, project_id: UUID, suite_id: UUID) -> SamplingSuite:
        return self._repository.get_suite(project_id=project_id, suite_id=suite_id)

    def list(self, *, project_id: UUID) -> tuple[SamplingSuite, ...]:
        return self._repository.list_suites(project_id=project_id)

    def install(
        self,
        *,
        project_id: UUID,
        resolved: ResolvedSamplingSuiteInputs,
        idempotency_key: str | None = None,
    ) -> PersistentSamplingSuiteInput:
        option = _persistent_input(project_id=project_id, resolved=resolved, at=self._clock())
        execution = resolved.provider_execution_input
        if option.source_stratum.capture_method in {
            CaptureMethod.PROVIDER_API,
            CaptureMethod.PROXY_GROUNDED_API,
        }:
            if execution is None:
                raise SamplingConflict(
                    "Provider Sampling Suite inputs require a frozen execution input"
                )
            _validate_provider_execution_input(option, execution)
        elif execution is not None:
            raise SamplingConflict(
                "manual_ui Sampling Suite inputs cannot include a Provider execution input"
            )
        persisted = self._repository.register_input(
            option,
            idempotency_key=idempotency_key or f"suite-input:{resolved.option_key}",
        )
        if execution is not None:
            self._execution_inputs.register(
                PersistentProviderSamplingExecutionInput(
                    project_id=project_id,
                    suite_input_option_id=persisted.id,
                    suite_input_option_hash=persisted.option_hash,
                    execution=execution,
                    frozen_at=option.frozen_at,
                ),
                idempotency_key=(
                    idempotency_key
                    or f"provider-execution-input:{resolved.option_key}"
                ),
            )
        return persisted


class _PostgresSamplingSuiteInputs:
    def __init__(self, repository: PostgresSamplingSuiteRepository) -> None:
        self._repository = repository

    def resolve(self, *, project_id: UUID, option_key: str) -> PersistentSamplingSuiteInput:
        return self._repository.resolve_input(project_id=project_id, option_key=option_key)

    def list(self, *, project_id: UUID) -> tuple[PersistentSamplingSuiteInput, ...]:
        return self._repository.list_inputs(project_id=project_id)


def _persistent_input(
    *,
    project_id: UUID,
    resolved: ResolvedSamplingSuiteInputs,
    at: datetime,
) -> PersistentSamplingSuiteInput:
    option_id = uuid5(SAMPLING_SUITE_INPUT_NAMESPACE, f"{project_id}:{resolved.option_key}")
    return PersistentSamplingSuiteInput(
        id=option_id,
        project_id=project_id,
        option_key=resolved.option_key,
        display_name=resolved.display_name,
        question_set_id=resolved.question_set_id,
        question_set_version=resolved.question_set_version,
        question_set_hash=resolved.question_set_hash,
        questions=resolved.questions,
        adapter_release_id=resolved.adapter_release_id,
        adapter_release_hash=resolved.adapter_release_hash,
        model_release_id=resolved.model_release_id,
        model_release_hash=resolved.model_release_hash,
        route_policy_id=resolved.route_policy_id,
        route_policy_hash=resolved.route_policy_hash,
        runtime_manifest_id=resolved.runtime_manifest_id,
        runtime_manifest_hash=resolved.runtime_manifest_hash,
        runtime_option_id=resolved.runtime_option_id,
        runtime_option_hash=resolved.runtime_option_hash,
        admission_policy_id=resolved.admission_policy_id,
        admission_policy_hash=resolved.admission_policy_hash,
        source_stratum=resolved.source_stratum,
        frozen_at=at,
    )


def _validate_provider_execution_input(
    option: PersistentSamplingSuiteInput,
    execution: ProviderSamplingExecutionInput,
) -> None:
    expected = {
        (question.question_id, question.question_version): question.text_hash
        for question in option.questions
    }
    actual = {
        (question.question_id, question.question_version): question.text_hash
        for question in execution.questions
    }
    if actual != expected:
        raise ProviderSamplingExecutionInputError(
            "Provider execution questions differ from the frozen Suite input"
        )


__all__ = ["PostgresWorkflowCSamplingSuiteControl"]
