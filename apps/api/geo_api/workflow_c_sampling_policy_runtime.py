"""Memory Admission Policy control plane for the Workflow C test adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock
from typing import TypeVar
from uuid import UUID

from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyDecisionRequest,
    AdmissionPolicySubmitRequest,
    CreateAdmissionPolicyRequest,
)
from geo_api.workflow_c_sampling_ids import sampling_command_id
from geo_core.sampling import (
    AdmissionPolicyStatus,
    AuthorizationState,
    CaptureMethod,
    LocationControl,
    SamplingAdmissionPolicyRecord,
    SamplingAdmissionGrant,
    SamplingAdmissionReservation,
    SamplingAdmissionUsageWindow,
    SamplingConflict,
    SamplingNotFound,
    SamplingRun,
    SamplingRuleViolation,
    consume_reservation,
    decide_admission_policy,
    require_current_admission_policy,
    new_reservation,
    release_unused_reservation,
    revoke_admission_policy,
    submit_admission_policy,
    utc_usage_window,
)


_Result = TypeVar("_Result")


@dataclass(frozen=True)
class SamplingAdmissionPolicyView:
    record: SamplingAdmissionPolicyRecord
    effective_authorization_state: AuthorizationState


@dataclass(frozen=True)
class SamplingAdmissionRuntimeOption:
    option_key: str
    display_name: str
    platform: str
    capture_method: CaptureMethod
    adapter_release: str
    location_control: LocationControl
    location_evidence_hash: str
    authorization_reference: str
    allowed_purposes: tuple[str, ...]

    def __post_init__(self) -> None:
        capture_method = CaptureMethod(self.capture_method)
        location_control = LocationControl(self.location_control)
        if (
            capture_method is CaptureMethod.MANUAL_UI
            and location_control is not LocationControl.NOT_CONTROLLED
        ):
            raise SamplingRuleViolation(
                "manual_ui cannot claim controlled geography without a governed evidence resolver"
            )
        object.__setattr__(self, "capture_method", capture_method)
        object.__setattr__(self, "location_control", location_control)


class WorkflowCSamplingPolicyControl:
    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._lock = RLock()
        self._policies: dict[tuple[UUID, UUID], SamplingAdmissionPolicyRecord] = {}
        self._options: dict[
            tuple[UUID, str], SamplingAdmissionRuntimeOption
        ] = {}
        self._commands: dict[
            tuple[UUID, UUID, str, str],
            tuple[tuple[object, ...], SamplingAdmissionPolicyRecord],
        ] = {}
        self._reservations: dict[tuple[UUID, UUID], SamplingAdmissionReservation] = {}
        self._usage_windows: dict[
            tuple[UUID, UUID, datetime], SamplingAdmissionUsageWindow
        ] = {}
        self._execution_leases: dict[tuple[UUID, UUID, UUID], datetime] = {}
        self._next_request_at: dict[tuple[UUID, UUID], datetime] = {}

    def create(
        self,
        *,
        project_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: CreateAdmissionPolicyRequest,
    ) -> SamplingAdmissionPolicyView:
        policy_id = sampling_command_id(project_id, "admission-policy", idempotency_key)
        predecessor = None
        revision = 1
        if payload.supersedes_policy_id is not None:
            predecessor = self.record(project_id, payload.supersedes_policy_id)
            if predecessor.status in {
                AdmissionPolicyStatus.DRAFT,
                AdmissionPolicyStatus.PENDING_REVIEW,
            }:
                raise SamplingConflict("only a decided policy can be superseded")
            revision = predecessor.revision + 1
        option = self.runtime_option(
            project_id=project_id,
            option_key=payload.runtime_authorization_option_key,
        )
        if payload.purpose not in option.allowed_purposes:
            raise SamplingConflict("Sampling purpose is not allowed by runtime authorization")
        key = (project_id, policy_id)
        with self._lock:
            existing = self._policies.get(key)
        created_at = existing.created_at if existing is not None else self._clock()
        record = SamplingAdmissionPolicyRecord(
            id=policy_id,
            project_id=project_id,
            revision=revision,
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
        with self._lock:
            existing = self._policies.get(key)
            if existing is not None:
                if (
                    existing.definition_hash != record.definition_hash
                    or existing.created_by != record.created_by
                ):
                    raise SamplingConflict(
                        "admission policy Idempotency-Key was reused with different input"
                    )
                return self.view(existing)
            self._policies[key] = record
        return self.view(record)

    def get(self, *, project_id: UUID, policy_id: UUID) -> SamplingAdmissionPolicyView:
        return self.view(self.record(project_id, policy_id))

    def list(self, *, project_id: UUID) -> tuple[SamplingAdmissionPolicyView, ...]:
        with self._lock:
            records = tuple(
                item
                for (item_project, _), item in self._policies.items()
                if item_project == project_id
            )
        return tuple(
            self.view(item)
            for item in sorted(
                records,
                key=lambda value: (value.created_at, str(value.id)),
                reverse=True,
            )
        )

    def submit(
        self,
        *,
        project_id: UUID,
        policy_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: AdmissionPolicySubmitRequest,
    ) -> SamplingAdmissionPolicyView:
        return self._change(
            project_id=project_id,
            policy_id=policy_id,
            expected_version=payload.expected_version,
            command_name="submit",
            idempotency_key=idempotency_key,
            command_signature=(actor_id,),
            operation=lambda item: submit_admission_policy(
                item, actor_id=actor_id, occurred_at=self._clock()
            ),
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
        return self._change(
            project_id=project_id,
            policy_id=policy_id,
            expected_version=payload.expected_version,
            command_name="approve" if approved else "assess-no-basis",
            idempotency_key=idempotency_key,
            command_signature=(actor_id, payload.reason),
            operation=lambda item: decide_admission_policy(
                item,
                actor_id=actor_id,
                occurred_at=self._clock(),
                reason=payload.reason,
                approved=approved,
            ),
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
        return self._change(
            project_id=project_id,
            policy_id=policy_id,
            expected_version=payload.expected_version,
            command_name="revoke",
            idempotency_key=idempotency_key,
            command_signature=(actor_id, payload.reason),
            operation=lambda item: revoke_admission_policy(
                item,
                actor_id=actor_id,
                occurred_at=self._clock(),
                reason=payload.reason,
            ),
        )

    def record(self, project_id: UUID, policy_id: UUID) -> SamplingAdmissionPolicyRecord:
        with self._lock:
            record = self._policies.get((project_id, policy_id))
        if record is None:
            raise SamplingNotFound("Sampling admission policy does not exist")
        return record

    def install_runtime_option(
        self,
        *,
        project_id: UUID,
        option: SamplingAdmissionRuntimeOption,
    ) -> None:
        key = (project_id, option.option_key)
        with self._lock:
            existing = self._options.get(key)
            if existing is not None and existing != option:
                raise SamplingConflict("Sampling runtime option changed in place")
            self._options[key] = option

    def runtime_option(
        self,
        *,
        project_id: UUID,
        option_key: str,
    ) -> SamplingAdmissionRuntimeOption:
        with self._lock:
            option = self._options.get((project_id, option_key))
        if option is None:
            raise SamplingNotFound("approved Sampling runtime authorization option does not exist")
        return option

    def list_runtime_options(
        self, *, project_id: UUID
    ) -> tuple[SamplingAdmissionRuntimeOption, ...]:
        with self._lock:
            values = tuple(
                option
                for (option_project_id, _), option in self._options.items()
                if option_project_id == project_id
            )
        return tuple(sorted(values, key=lambda item: (item.display_name, item.option_key)))

    def require_current(self, run: SamplingRun, at: datetime) -> None:
        record = self.record(run.project_id, run.admission_policy_id)
        require_current_admission_policy(
            record,
            policy_id=run.admission_policy_id,
            policy_hash=run.admission_policy_hash,
            policy_version=run.admission_policy_version,
            at=at,
        )

    def create_reserved_run(
        self,
        *,
        record: SamplingAdmissionPolicyRecord,
        grant: SamplingAdmissionGrant,
        run_id: UUID,
        occurred_at: datetime,
        operation: Callable[[], _Result],
    ) -> tuple[_Result, SamplingAdmissionReservation, bool]:
        key = (record.project_id, run_id)
        with self._lock:
            existing = self._reservations.get(key)
            proposed = new_reservation(
                project_id=record.project_id,
                policy_id=record.id,
                policy_hash=grant.policy_hash,
                policy_version=grant.policy_version,
                run_id=run_id,
                suite_id=grant.suite_id,
                suite_hash=grant.suite_hash,
                purpose=grant.purpose,
                idempotency_key=grant.idempotency_key,
                reserved_task_count=grant.reserved_task_count,
                created_at=(existing.created_at if existing is not None else occurred_at),
            )
            if existing is not None:
                if existing.reservation_hash != proposed.reservation_hash:
                    raise SamplingConflict(
                        "Sampling Run reservation identity was reused with different input"
                    )
                return operation(), existing, True
            charged = sum(
                item.charged_task_count
                for item in self._reservations.values()
                if item.project_id == record.project_id and item.policy_id == record.id
            )
            if charged + proposed.reserved_task_count > record.quota_remaining:
                raise SamplingRuleViolation(
                    "sampling policy quota cannot cover all active Run reservations"
                )
            result = operation()
            self._reservations[key] = proposed
            return result, proposed, False

    def consume_and_execute(
        self,
        *,
        run: SamplingRun,
        task_count: int,
        occurred_at: datetime,
        operation: Callable[[], _Result],
    ) -> _Result:
        with self._lock:
            record = self.record(run.project_id, run.admission_policy_id)
            require_current_admission_policy(
                record,
                policy_id=run.admission_policy_id,
                policy_hash=run.admission_policy_hash,
                policy_version=run.admission_policy_version,
                at=occurred_at,
            )
            reservation = self._reservation(run.project_id, run.id)
            start, end = utc_usage_window(occurred_at)
            usage_key = (run.project_id, record.id, start)
            usage = self._usage_windows.get(
                usage_key,
                SamplingAdmissionUsageWindow(
                    project_id=run.project_id,
                    policy_id=record.id,
                    window_start=start,
                    window_end=end,
                    consumed_task_count=0,
                    updated_at=occurred_at,
                ),
            )
            if task_count < 0 or task_count > reservation.unused_task_count:
                raise SamplingRuleViolation("Run reservation cannot cover requested Tasks")
            if usage.consumed_task_count + task_count > record.daily_task_limit:
                raise SamplingRuleViolation("sampling policy daily task limit is exhausted")
            result = operation()
            if task_count:
                self._reservations[(run.project_id, run.id)] = consume_reservation(
                    reservation,
                    task_count=task_count,
                    occurred_at=occurred_at,
                )
                self._usage_windows[usage_key] = SamplingAdmissionUsageWindow(
                    project_id=usage.project_id,
                    policy_id=usage.policy_id,
                    window_start=usage.window_start,
                    window_end=usage.window_end,
                    consumed_task_count=usage.consumed_task_count + task_count,
                    updated_at=occurred_at,
                    aggregate_version=usage.aggregate_version + 1,
                )
            return result

    def release_unused(
        self,
        *,
        run: SamplingRun,
        task_count: int,
        occurred_at: datetime,
    ) -> SamplingAdmissionReservation:
        with self._lock:
            reservation = self._reservation(run.project_id, run.id)
            updated = release_unused_reservation(
                reservation,
                task_count=task_count,
                occurred_at=occurred_at,
            )
            self._reservations[(run.project_id, run.id)] = updated
            return updated

    def cancel_and_release(
        self,
        *,
        run: SamplingRun,
        unused_task_count: int,
        occurred_at: datetime,
        operation: Callable[[], _Result],
    ) -> _Result:
        with self._lock:
            reservation = self._reservation(run.project_id, run.id)
            if unused_task_count < 0 or unused_task_count > reservation.unused_task_count:
                raise SamplingRuleViolation("Run cancellation release count is invalid")
            result = operation()
            self._reservations[(run.project_id, run.id)] = release_unused_reservation(
                reservation,
                task_count=unused_task_count,
                occurred_at=occurred_at,
            )
            return result

    def claim_and_execute(
        self,
        *,
        run: SamplingRun,
        attempt_id: UUID,
        now: datetime,
        lease_for: timedelta,
        operation: Callable[[], _Result],
    ) -> _Result:
        with self._lock:
            record = self.record(run.project_id, run.admission_policy_id)
            policy = require_current_admission_policy(
                record,
                policy_id=run.admission_policy_id,
                policy_hash=run.admission_policy_hash,
                policy_version=run.admission_policy_version,
                at=now,
            )
            policy_key = (run.project_id, record.id)
            active = {
                key: expires_at
                for key, expires_at in self._execution_leases.items()
                if key[:2] == policy_key and expires_at > now
            }
            next_request_at = max(
                policy.next_allowed_at,
                self._next_request_at.get(policy_key, policy.next_allowed_at),
            )
            if now < next_request_at:
                raise SamplingRuleViolation("sampling policy request interval has not elapsed")
            if len(active) >= policy.max_concurrency:
                raise SamplingRuleViolation("sampling policy global concurrency is exhausted")
            result = operation()
            self._execution_leases[(run.project_id, record.id, attempt_id)] = now + lease_for
            self._next_request_at[policy_key] = now + timedelta(
                seconds=policy.minimum_request_interval_seconds
            )
            return result

    def update_execution_lease(
        self,
        *,
        run: SamplingRun,
        attempt_id: UUID,
        expires_at: datetime,
    ) -> None:
        with self._lock:
            key = (run.project_id, run.admission_policy_id, attempt_id)
            if key not in self._execution_leases:
                raise SamplingConflict("Sampling execution lease was not admission-tracked")
            self._execution_leases[key] = expires_at

    def release_execution(self, *, run: SamplingRun, attempt_id: UUID) -> None:
        with self._lock:
            self._execution_leases.pop(
                (run.project_id, run.admission_policy_id, attempt_id),
                None,
            )

    def reservation(
        self, *, project_id: UUID, run_id: UUID
    ) -> SamplingAdmissionReservation:
        with self._lock:
            return self._reservation(project_id, run_id)

    def usage_windows(
        self, *, project_id: UUID, policy_id: UUID
    ) -> tuple[SamplingAdmissionUsageWindow, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for item in self._usage_windows.values()
                        if item.project_id == project_id and item.policy_id == policy_id
                    ),
                    key=lambda item: item.window_start,
                )
            )

    def view(self, record: SamplingAdmissionPolicyRecord) -> SamplingAdmissionPolicyView:
        return SamplingAdmissionPolicyView(
            record=record,
            effective_authorization_state=record.effective_authorization_state(
                at=self._clock()
            ),
        )

    def _reservation(self, project_id: UUID, run_id: UUID) -> SamplingAdmissionReservation:
        reservation = self._reservations.get((project_id, run_id))
        if reservation is None:
            raise SamplingNotFound("Sampling admission reservation does not exist")
        return reservation

    def _change(
        self,
        *,
        project_id: UUID,
        policy_id: UUID,
        expected_version: int,
        command_name: str,
        idempotency_key: str,
        command_signature: tuple[object, ...],
        operation: Callable[
            [SamplingAdmissionPolicyRecord], SamplingAdmissionPolicyRecord
        ],
    ) -> SamplingAdmissionPolicyView:
        key = (project_id, policy_id)
        command_key = (project_id, policy_id, command_name, idempotency_key)
        signature = (expected_version, *command_signature)
        with self._lock:
            prior = self._commands.get(command_key)
            if prior is not None:
                if prior[0] != signature:
                    raise SamplingConflict(
                        "admission policy Idempotency-Key was reused with different input"
                    )
                return self.view(prior[1])
            current = self._policies.get(key)
            if current is None:
                raise SamplingNotFound("Sampling admission policy does not exist")
            if current.aggregate_version != expected_version:
                raise SamplingConflict(
                    "Sampling admission policy optimistic version check failed"
                )
            updated = operation(current)
            if updated.definition_hash != current.definition_hash:
                raise SamplingConflict("Sampling admission policy definition is immutable")
            self._policies[key] = updated
            self._commands[command_key] = (signature, updated)
        return self.view(updated)
