"""Server-resolved Sampling Suite control for the Workflow C memory adapter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from geo_api.workflow_c_sampling_catalog import (
    ResolvedSamplingSuiteInputs,
    WorkflowCSamplingInputCatalog,
    select_sampling_questions,
)
from geo_api.workflow_c_sampling_contracts import CreateSamplingSuiteRequest
from geo_api.workflow_c_sampling_ids import sampling_command_id
from geo_api.workflow_c_sampling_policy_runtime import WorkflowCSamplingPolicyControl
from geo_core.sampling import (
    InMemorySamplingStore,
    SamplingApplication,
    SamplingConflict,
    SamplingNotFound,
    SamplingSuite,
)


class WorkflowCSamplingSuiteControl:
    def __init__(
        self,
        *,
        store: InMemorySamplingStore,
        application: SamplingApplication,
        policies: WorkflowCSamplingPolicyControl,
        clock: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._application = application
        self._policies = policies
        self._clock = clock
        self.inputs = WorkflowCSamplingInputCatalog()

    def create(
        self,
        *,
        project_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: CreateSamplingSuiteRequest,
    ) -> SamplingSuite:
        resolved = self.inputs.resolve(project_id=project_id, selector=payload)
        policy_record = self._policies.record(project_id, resolved.admission_policy_id)
        policy_record.approved_policy(at=self._clock())
        if policy_record.definition_hash != resolved.admission_policy_hash:
            raise SamplingConflict("Suite admission policy selector is stale")
        source = resolved.source_stratum
        if (
            policy_record.platform != source.platform
            or policy_record.capture_method is not source.capture_method
            or policy_record.adapter_release != source.adapter_release
            or policy_record.location_control is not source.location_control
            or policy_record.location_evidence_hash != source.location_evidence_hash
        ):
            raise SamplingConflict("Suite catalog target differs from admission policy")
        questions, _ = select_sampling_questions(
            resolved, payload.question_set_item_ids
        )
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
            frozen_at=self._clock(),
        )
        return self._application.register_suite(suite)

    def install(
        self,
        *,
        project_id: UUID,
        resolved: ResolvedSamplingSuiteInputs,
    ) -> None:
        self.inputs.install(
            project_id=project_id,
            admission_policy_id=resolved.admission_policy_id,
            admission_policy_hash=resolved.admission_policy_hash,
            resolved=resolved,
        )

    def list(self, *, project_id: UUID) -> tuple[SamplingSuite, ...]:
        return self._store.suites(project_id=project_id)

    def get(self, *, project_id: UUID, suite_id: UUID) -> SamplingSuite:
        suite = self._store.suite(project_id=project_id, suite_id=suite_id)
        if suite is None:
            raise SamplingNotFound("Sampling Suite does not exist")
        return suite
