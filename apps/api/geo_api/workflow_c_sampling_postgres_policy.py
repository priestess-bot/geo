"""Durable Internal API adapter for Workflow C Sampling admission policies."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyDecisionRequest,
    AdmissionPolicySubmitRequest,
    CreateAdmissionPolicyRequest,
)
from geo_api.workflow_c_sampling_ids import sampling_command_id
from geo_api.workflow_c_sampling_policy_runtime import (
    SamplingAdmissionPolicyView,
    SamplingAdmissionRuntimeOption,
)
from geo_core.sampling import (
    SamplingAdmissionPolicyRecord,
    SamplingConflict,
    SamplingNotFound,
    require_current_admission_policy,
)
from geo_core.sampling.postgres_admission import (
    PersistentSamplingAdmissionRuntimeOption,
    PostgresSamplingAdmissionRepository,
)


class PostgresWorkflowCSamplingPolicyControl:
    """Keep API role checks separate from durable policy state transitions."""

    persistence = "durable"

    def __init__(
        self,
        *,
        repository: PostgresSamplingAdmissionRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._clock = clock

    def create(
        self,
        *,
        project_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: CreateAdmissionPolicyRequest,
    ) -> SamplingAdmissionPolicyView:
        option = self._repository.runtime_option(
            project_id=project_id,
            option_key=payload.runtime_authorization_option_key,
        )
        if payload.purpose not in option.allowed_purposes:
            raise SamplingConflict("Sampling purpose is not allowed by runtime authorization")
        policy_id = sampling_command_id(project_id, "admission-policy", idempotency_key)
        existing = self._existing(project_id=project_id, policy_id=policy_id)
        predecessor = (
            self._repository.get(project_id=project_id, policy_id=payload.supersedes_policy_id)
            if payload.supersedes_policy_id is not None
            else None
        )
        if predecessor is not None and predecessor.status.value in {"draft", "pending_review"}:
            raise SamplingConflict("only a decided policy can be superseded")
        created_at = existing.created_at if existing is not None else self._clock()
        record = SamplingAdmissionPolicyRecord(
            id=policy_id,
            project_id=project_id,
            revision=1 if predecessor is None else predecessor.revision + 1,
            supersedes_policy_id=(predecessor.id if predecessor is not None else None),
            platform=option.platform,
            capture_method=option.capture_method,
            adapter_release=option.adapter_release,
            location_control=option.location_control,
            location_evidence_hash=option.location_evidence_hash,
            authorization_reference=option.authorization_reference,
            authorized_purposes=(payload.purpose,),
            valid_until=payload.valid_until,
            quota_remaining=payload.quota_remaining,
            daily_task_limit=payload.daily_task_limit,
            minimum_request_interval_seconds=payload.minimum_request_interval_seconds,
            max_concurrency=payload.max_concurrency,
            next_allowed_at=created_at,
            created_by=actor_id,
            created_at=created_at,
        )
        return self._view(
            self._repository.create(
                record,
                idempotency_key=idempotency_key,
                runtime_option=option,
            )
        )

    def get(self, *, project_id: UUID, policy_id: UUID) -> SamplingAdmissionPolicyView:
        return self._view(self._repository.get(project_id=project_id, policy_id=policy_id))

    def list(self, *, project_id: UUID) -> tuple[SamplingAdmissionPolicyView, ...]:
        return tuple(self._view(record) for record in self._repository.list(project_id=project_id))

    def submit(
        self,
        *,
        project_id: UUID,
        policy_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: AdmissionPolicySubmitRequest,
    ) -> SamplingAdmissionPolicyView:
        occurred_at = self._clock()
        return self._view(
            self._repository.transition(
                project_id=project_id,
                policy_id=policy_id,
                expected_version=payload.expected_version,
                operation="submit",
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                reason=None,
                occurred_at=occurred_at,
            )
        )

    def decide(
        self,
        *,
        project_id: UUID,
        policy_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: AdmissionPolicyDecisionRequest,
        approved: bool,
    ) -> SamplingAdmissionPolicyView:
        occurred_at = self._clock()
        return self._view(
            self._repository.transition(
                project_id=project_id,
                policy_id=policy_id,
                expected_version=payload.expected_version,
                operation="approve" if approved else "assess_no_basis",
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                reason=payload.reason,
                occurred_at=occurred_at,
            )
        )

    def revoke(
        self,
        *,
        project_id: UUID,
        policy_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: AdmissionPolicyDecisionRequest,
    ) -> SamplingAdmissionPolicyView:
        occurred_at = self._clock()
        return self._view(
            self._repository.transition(
                project_id=project_id,
                policy_id=policy_id,
                expected_version=payload.expected_version,
                operation="revoke",
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                reason=payload.reason,
                occurred_at=occurred_at,
            )
        )

    def record(self, project_id: UUID, policy_id: UUID) -> SamplingAdmissionPolicyRecord:
        return self._repository.get(project_id=project_id, policy_id=policy_id)

    def require_current(self, run, at: datetime) -> None:
        record = self.record(run.project_id, run.admission_policy_id)
        require_current_admission_policy(
            record,
            policy_id=run.admission_policy_id,
            policy_hash=run.admission_policy_hash,
            policy_version=run.admission_policy_version,
            at=at,
        )

    def runtime_option(
        self, *, project_id: UUID, option_key: str
    ) -> SamplingAdmissionRuntimeOption:
        return _runtime_option(
            self._repository.runtime_option(project_id=project_id, option_key=option_key)
        )

    def list_runtime_options(
        self, *, project_id: UUID
    ) -> tuple[SamplingAdmissionRuntimeOption, ...]:
        return tuple(
            _runtime_option(option)
            for option in self._repository.list_runtime_options(project_id=project_id)
        )

    def _existing(
        self, *, project_id: UUID, policy_id: UUID
    ) -> SamplingAdmissionPolicyRecord | None:
        try:
            return self._repository.get(project_id=project_id, policy_id=policy_id)
        except SamplingNotFound:
            return None

    def _view(self, record: SamplingAdmissionPolicyRecord) -> SamplingAdmissionPolicyView:
        return SamplingAdmissionPolicyView(
            record=record,
            effective_authorization_state=record.effective_authorization_state(at=self._clock()),
        )


def _runtime_option(
    option: PersistentSamplingAdmissionRuntimeOption,
) -> SamplingAdmissionRuntimeOption:
    return SamplingAdmissionRuntimeOption(
        option_key=option.option_key,
        display_name=option.display_name,
        platform=option.platform,
        capture_method=option.capture_method,
        adapter_release=option.adapter_release,
        location_control=option.location_control,
        location_evidence_hash=option.location_evidence_hash,
        authorization_reference=option.authorization_reference,
        allowed_purposes=option.allowed_purposes,
    )


__all__ = ["PostgresWorkflowCSamplingPolicyControl"]
