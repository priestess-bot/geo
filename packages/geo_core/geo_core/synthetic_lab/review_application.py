"""Application commands for frozen review inputs and synthetic workflow Jobs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

from geo_core.jobs.lifecycle import JobStatus, request_cancel
from geo_core.synthetic_lab.application_support import (
    JobWriteOwnership,
    assert_runtime_current,
    assert_terminal_write,
    canonical_hash,
    claim_synthetic_job,
    command_identity,
    complete_synthetic_job,
    new_outbox_message,
    new_synthetic_job,
    recover_command,
    reject_self_approval,
    require_roles,
    stage_command,
)
from geo_core.synthetic_lab.domain import (
    StyleProfileVersion,
    StyleSample,
)
from geo_core.synthetic_lab.domain_profile_transitions import transition_style_profile
from geo_core.synthetic_lab.ports import (
    CommandReceipt,
    JobTerminalResult,
    LabPrincipal,
    LabRole,
    RuntimeInputPort,
    RuntimeInputSnapshot,
    SyntheticCommandOperation,
    SyntheticLabPersistenceError,
    SyntheticLabUnitOfWorkFactory,
    SyntheticJob,
    VersionedAggregate,
)
from geo_core.synthetic_lab.review_cases import (
    ReviewCase,
    ReviewSuite,
    review_case_set_hash,
    transition_review_suite,
)


STYLE_PROFILE_KIND = "style_profile"
REVIEW_SUITE_KIND = "review_suite"


@dataclass(frozen=True, kw_only=True)
class JobEnqueueRequest:
    project_id: UUID
    job_id: UUID
    outbox_id: UUID
    resource_id: UUID
    resource_hash: str
    runtime_inputs: RuntimeInputSnapshot

    def __post_init__(self) -> None:
        if self.runtime_inputs.project_id != self.project_id:
            raise ValueError("Job enqueue runtime inputs belong to another Project")


class ReviewApplication:
    def __init__(self, uow_factory: SyntheticLabUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def freeze_profile(
        self,
        *,
        principal: LabPrincipal,
        profile: StyleProfileVersion,
        samples: tuple[StyleSample, ...],
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, profile.project_id, LabRole.APPROVER, LabRole.REVIEWER)
        identity = command_identity(
            project_id=profile.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.FREEZE_PROFILE,
            request={
                "profile": profile,
                "samples": samples,
                "expected_version": expected_version,
            },
        )
        with self._uow_factory(project_id=profile.project_id) as uow:
            replay = recover_command(uow, identity, StyleProfileVersion)
            if replay is not None:
                return replay
            current = uow.aggregates.get(
                project_id=profile.project_id,
                kind=STYLE_PROFILE_KIND,
                resource_id=profile.id,
            )
            if current is None or current.payload != profile:
                raise SyntheticLabPersistenceError("current Style Profile version is missing")
            reject_self_approval(principal, current.submitted_by)
            frozen = transition_style_profile(profile, command="freeze", samples=samples)
            uow.aggregates.stage(
                VersionedAggregate(
                    project_id=profile.project_id,
                    kind=STYLE_PROFILE_KIND,
                    resource_id=profile.id,
                    version=expected_version + 1,
                    submitted_by=current.submitted_by,
                    payload=frozen,
                ),
                expected_version=expected_version,
            )
            return stage_command(uow, identity, frozen)

    def submit_profile(
        self,
        *,
        principal: LabPrincipal,
        profile: StyleProfileVersion,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, profile.project_id, LabRole.OPERATOR, LabRole.REVIEWER)
        return self._transition_profile(
            principal=principal,
            profile=profile,
            command="submit",
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.SUBMIT_PROFILE,
            independent_reviewer=False,
        )

    def decide_profile(
        self,
        *,
        principal: LabPrincipal,
        profile: StyleProfileVersion,
        decision: str,
        decided_at: datetime,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, profile.project_id, LabRole.APPROVER, LabRole.REVIEWER)
        if decision not in {"approve", "reject"}:
            raise SyntheticLabPersistenceError("Style Profile decision is invalid")
        return self._transition_profile(
            principal=principal,
            profile=profile,
            command=decision,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.DECIDE_PROFILE,
            independent_reviewer=True,
            decided_at=decided_at,
        )

    def _transition_profile(
        self,
        *,
        principal: LabPrincipal,
        profile: StyleProfileVersion,
        command: str,
        expected_version: int,
        idempotency_key: str,
        operation: SyntheticCommandOperation,
        independent_reviewer: bool,
        decided_at: datetime | None = None,
    ) -> CommandReceipt:
        identity = command_identity(
            project_id=profile.project_id,
            idempotency_key=idempotency_key,
            operation=operation,
            request={
                "profile": profile,
                "command": command,
                "expected_version": expected_version,
                "decided_at": decided_at,
            },
        )
        with self._uow_factory(project_id=profile.project_id) as uow:
            replay = recover_command(uow, identity, StyleProfileVersion)
            if replay is not None:
                return replay
            current = uow.aggregates.get(
                project_id=profile.project_id,
                kind=STYLE_PROFILE_KIND,
                resource_id=profile.id,
            )
            if current is None or current.payload != profile:
                raise SyntheticLabPersistenceError("current Style Profile version is missing")
            if independent_reviewer:
                reject_self_approval(principal, current.submitted_by)
            transitioned = transition_style_profile(
                profile,
                command=command,
                reviewer_id=principal.actor_id if decided_at is not None else None,
                reviewed_at=decided_at,
            )
            uow.aggregates.stage(
                VersionedAggregate(
                    project_id=profile.project_id,
                    kind=STYLE_PROFILE_KIND,
                    resource_id=profile.id,
                    version=expected_version + 1,
                    submitted_by=current.submitted_by,
                    payload=transitioned,
                ),
                expected_version=expected_version,
            )
            return stage_command(uow, identity, transitioned)

    def freeze_suite(
        self,
        *,
        principal: LabPrincipal,
        suite: ReviewSuite,
        cases: tuple[ReviewCase, ...],
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, suite.project_id, LabRole.APPROVER, LabRole.REVIEWER)
        identity = command_identity(
            project_id=suite.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.FREEZE_SUITE,
            request={
                "suite": suite,
                "cases": cases,
                "expected_version": expected_version,
            },
        )
        with self._uow_factory(project_id=suite.project_id) as uow:
            replay = recover_command(uow, identity, ReviewSuite)
            if replay is not None:
                return replay
            current = uow.aggregates.get(
                project_id=suite.project_id,
                kind=REVIEW_SUITE_KIND,
                resource_id=suite.id,
            )
            if current is None or current.payload != suite:
                raise SyntheticLabPersistenceError("current Review Suite version is missing")
            reject_self_approval(principal, current.submitted_by)
            prepared = replace(
                suite,
                case_count=len(cases),
                case_set_hash=review_case_set_hash(cases),
            )
            frozen = transition_review_suite(prepared, command="freeze", cases=cases)
            uow.aggregates.stage(
                VersionedAggregate(
                    project_id=suite.project_id,
                    kind=REVIEW_SUITE_KIND,
                    resource_id=suite.id,
                    version=expected_version + 1,
                    submitted_by=current.submitted_by,
                    payload=frozen,
                ),
                expected_version=expected_version,
            )
            return stage_command(uow, identity, frozen)

    def enqueue_generation(
        self,
        *,
        principal: LabPrincipal,
        request: JobEnqueueRequest,
        runtime_port: RuntimeInputPort,
        idempotency_key: str,
    ) -> CommandReceipt:
        return self._enqueue(
            principal=principal,
            request=request,
            runtime_port=runtime_port,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.ENQUEUE_GENERATION,
            job_kind="candidate_generation",
            resource_name="review_case",
        )

    def enqueue_revision(
        self,
        *,
        principal: LabPrincipal,
        request: JobEnqueueRequest,
        runtime_port: RuntimeInputPort,
        idempotency_key: str,
    ) -> CommandReceipt:
        return self._enqueue(
            principal=principal,
            request=request,
            runtime_port=runtime_port,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.ENQUEUE_REVISION,
            job_kind="candidate_revision",
            resource_name="candidate",
        )

    def enqueue_corpus(
        self,
        *,
        principal: LabPrincipal,
        request: JobEnqueueRequest,
        runtime_port: RuntimeInputPort,
        idempotency_key: str,
    ) -> CommandReceipt:
        return self._enqueue(
            principal=principal,
            request=request,
            runtime_port=runtime_port,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.ENQUEUE_CORPUS,
            job_kind="corpus_finalize",
            resource_name="review_run",
        )

    def claim_job(
        self,
        *,
        principal: LabPrincipal,
        job_id: UUID,
        expected_version: int,
        claimed_at: datetime,
        lease_for: timedelta,
        runtime_port: RuntimeInputPort,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, principal.project_id, LabRole.WORKER)
        identity = command_identity(
            project_id=principal.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.CLAIM_JOB,
            request={
                "job_id": job_id,
                "expected_version": expected_version,
                "claimed_at": claimed_at,
                "lease_for_seconds": lease_for.total_seconds(),
            },
        )
        with self._uow_factory(project_id=principal.project_id) as uow:
            replay = recover_command(uow, identity, SyntheticJob)
            if replay is not None:
                return replay
            current = uow.jobs.get(project_id=principal.project_id, job_id=job_id)
            if current is None or current.status != JobStatus.QUEUED:
                raise SyntheticLabPersistenceError("only a queued Synthetic Lab Job can be claimed")
            if current.runtime_inputs is None:
                raise SyntheticLabPersistenceError("review Job lacks frozen runtime inputs")
            assert_runtime_current(current.runtime_inputs, runtime_port)
            claimed = claim_synthetic_job(
                current,
                worker_id=str(principal.actor_id),
                at=claimed_at,
                lease_for=lease_for,
            )
            uow.jobs.stage(claimed, expected_version=expected_version)
            return stage_command(uow, identity, claimed)

    def cancel_job(
        self,
        *,
        principal: LabPrincipal,
        job_id: UUID,
        expected_version: int,
        cancelled_at: datetime,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, principal.project_id, LabRole.OPERATOR, LabRole.APPROVER)
        identity = command_identity(
            project_id=principal.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.CANCEL_JOB,
            request={
                "job_id": job_id,
                "expected_version": expected_version,
                "cancelled_at": cancelled_at,
            },
        )
        with self._uow_factory(project_id=principal.project_id) as uow:
            replay = recover_command(uow, identity, SyntheticJob)
            if replay is not None:
                return replay
            current = uow.jobs.get(project_id=principal.project_id, job_id=job_id)
            if current is None or current.status not in {
                JobStatus.QUEUED,
                JobStatus.RUNNING,
            }:
                raise SyntheticLabPersistenceError("only queued/running Jobs can be cancelled")
            cancelled = replace(
                current,
                durable=request_cancel(current.durable, now=cancelled_at),
                version=current.version + 1,
            )
            uow.jobs.stage(cancelled, expected_version=expected_version)
            return stage_command(uow, identity, cancelled)

    def finalize_result(
        self,
        *,
        principal: LabPrincipal,
        job_id: UUID,
        ownership: JobWriteOwnership,
        expected_version: int,
        result: object,
        runtime_port: RuntimeInputPort,
        completed_at: datetime,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, principal.project_id, LabRole.WORKER)
        result_hash = canonical_hash(result)
        identity = command_identity(
            project_id=principal.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.FINALIZE_RESULT,
            request={
                "job_id": job_id,
                "ownership": ownership,
                "expected_version": expected_version,
                "result_hash": result_hash,
                "completed_at": completed_at,
            },
        )
        with self._uow_factory(project_id=principal.project_id) as uow:
            replay = recover_command(uow, identity, JobTerminalResult)
            if replay is not None:
                return replay
            job = uow.jobs.get(project_id=principal.project_id, job_id=job_id)
            if job is None:
                raise SyntheticLabPersistenceError("Synthetic Lab Job does not exist")
            result_project = getattr(result, "project_id", principal.project_id)
            if result_project != principal.project_id:
                raise SyntheticLabPersistenceError("terminal result belongs to another Project")
            assert_terminal_write(
                job,
                ownership=ownership,
                runtime_port=runtime_port,
                at=completed_at,
            )
            terminal = JobTerminalResult(
                project_id=principal.project_id,
                job_id=job.id,
                job_kind=job.kind,
                result=result,
                result_hash=result_hash,
            )
            completed = complete_synthetic_job(
                job,
                ownership=ownership,
                at=completed_at,
                result_ref=result_hash,
            )
            uow.jobs.stage_terminal(terminal)
            uow.jobs.stage(completed, expected_version=expected_version)
            return stage_command(uow, identity, terminal)

    def _enqueue(
        self,
        *,
        principal: LabPrincipal,
        request: JobEnqueueRequest,
        runtime_port: RuntimeInputPort,
        idempotency_key: str,
        operation: SyntheticCommandOperation,
        job_kind: str,
        resource_name: str,
    ) -> CommandReceipt:
        require_roles(principal, request.project_id, LabRole.OPERATOR, LabRole.REVIEWER)
        identity = command_identity(
            project_id=request.project_id,
            idempotency_key=idempotency_key,
            operation=operation,
            request=request,
        )
        with self._uow_factory(project_id=request.project_id) as uow:
            replay = recover_command(uow, identity, SyntheticJob)
            if replay is not None:
                return replay
            current = assert_runtime_current(request.runtime_inputs, runtime_port)
            job = new_synthetic_job(
                job_id=request.job_id,
                project_id=request.project_id,
                kind=job_kind,
                input_hash=canonical_hash(
                    {
                        "resource_id": request.resource_id,
                        "resource_hash": request.resource_hash,
                        "runtime_inputs": current,
                    }
                ),
                payload={
                    f"{resource_name}_id": request.resource_id,
                    f"{resource_name}_hash": request.resource_hash,
                },
                runtime_inputs=current,
                idempotency_key_hash=identity.idempotency_key_hash,
            )
            uow.jobs.stage(job, expected_version=0)
            uow.outbox.stage(
                new_outbox_message(
                    message_id=request.outbox_id,
                    job=job,
                    event_type=f"synthetic.{job_kind}.queued",
                )
            )
            return stage_command(uow, identity, job)


__all__ = [
    "JobEnqueueRequest",
    "REVIEW_SUITE_KIND",
    "ReviewApplication",
    "STYLE_PROFILE_KIND",
]
