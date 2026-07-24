"""Application commands for collection authorization and style sample intake."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

from geo_core.jobs.lifecycle import JobStatus
from geo_core.synthetic_lab.application_support import (
    canonical_hash,
    claim_synthetic_job,
    command_identity,
    new_outbox_message,
    new_synthetic_job,
    recover_command,
    reject_self_approval,
    require_roles,
    stage_command,
)
from geo_core.synthetic_lab.authorization import (
    AdmissionDisposition,
    AuthorizationRecord,
    AuthorizationState,
    CollectionAdmissionCommand,
    CollectionAdmissionRequest,
    CollectionPath,
    NavigationCommand,
    admit_collection,
    assert_next_authorization_version,
    open_authorization_reassessment,
    recheck_before_navigation,
)
from geo_core.synthetic_lab.ports import (
    AuthorizationEnvelope,
    CollectionAuthorizationPort,
    CommandReceipt,
    LabPrincipal,
    LabRole,
    SyntheticCommandOperation,
    SyntheticLabPermissionDenied,
    SyntheticLabPersistenceError,
    SyntheticLabUnitOfWorkFactory,
    SyntheticJob,
)
from geo_core.synthetic_lab.raw_artifact_governance import (
    RawArtifactInspection,
    govern_raw_artifact,
)
from geo_core.synthetic_lab.sample_import import (
    ManualSampleImportManifest,
    ManualSampleImportRequest,
    SampleDedupStatus,
    build_manual_import_manifest,
)


@dataclass(frozen=True, kw_only=True)
class CollectionAdmissionResult:
    command: CollectionAdmissionCommand
    job: SyntheticJob | None


@dataclass(frozen=True, kw_only=True)
class CollectionClaimResult:
    navigation: NavigationCommand
    job: SyntheticJob | None


class StyleApplication:
    def __init__(self, uow_factory: SyntheticLabUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def create_authorization(
        self,
        *,
        principal: LabPrincipal,
        record: AuthorizationRecord,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, record.project_id, LabRole.OPERATOR, LabRole.APPROVER)
        if record.state != AuthorizationState.NOT_ASSESSED:
            raise SyntheticLabPersistenceError(
                "new collection authorization must start as not_assessed"
            )
        identity = command_identity(
            project_id=record.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.CREATE_AUTHORIZATION,
            request={"record": record, "expected_version": expected_version},
        )
        with self._uow_factory(project_id=record.project_id) as uow:
            replay = recover_command(uow, identity, AuthorizationRecord)
            if replay is not None:
                return replay
            uow.authorizations.stage(
                AuthorizationEnvelope(record=record, submitted_by=principal.actor_id),
                expected_version=expected_version,
            )
            return stage_command(uow, identity, record)

    def decide_authorization(
        self,
        *,
        principal: LabPrincipal,
        record: AuthorizationRecord,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        if record.state not in {
            AuthorizationState.APPROVED,
            AuthorizationState.ASSESSED_NO_BASIS,
        }:
            raise SyntheticLabPersistenceError("authorization decision state is invalid")
        return self._transition_authorization(
            principal=principal,
            record=record,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.DECIDE_AUTHORIZATION,
            allowed_previous=frozenset({AuthorizationState.NOT_ASSESSED}),
            forbid_submitter=True,
        )

    def reassess_authorization(
        self,
        *,
        principal: LabPrincipal,
        previous: AuthorizationRecord,
        reassessment_id: UUID,
        opened_at: datetime,
        reassessment_reason: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, previous.project_id, LabRole.OPERATOR, LabRole.APPROVER)
        if not reassessment_reason.strip():
            raise SyntheticLabPersistenceError("authorization reassessment reason is required")
        if expected_version != previous.version_number:
            raise SyntheticLabPersistenceError("authorization reassessment version is stale")
        current = open_authorization_reassessment(
            previous,
            reassessment_id=reassessment_id,
            opened_at=opened_at,
        )
        identity = command_identity(
            project_id=previous.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.REASSESS_AUTHORIZATION,
            request={
                "previous": previous,
                "reassessment_id": reassessment_id,
                "opened_at": opened_at,
                "reassessment_reason": reassessment_reason,
                "expected_version": expected_version,
            },
        )
        with self._uow_factory(project_id=previous.project_id) as uow:
            replay = recover_command(uow, identity, AuthorizationRecord)
            if replay is not None:
                return replay
            envelope = uow.authorizations.current(
                project_id=previous.project_id,
                channel=previous.channel,
                adapter_release=previous.adapter_release,
            )
            if envelope is None or envelope.record != previous:
                raise SyntheticLabPersistenceError(
                    "authorization reassessment no longer targets the current version"
                )
            uow.authorizations.stage(
                AuthorizationEnvelope(record=current, submitted_by=principal.actor_id),
                expected_version=expected_version,
            )
            return stage_command(uow, identity, current)

    def expire_authorization(
        self,
        *,
        principal: LabPrincipal,
        record: AuthorizationRecord,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        if record.state != AuthorizationState.EXPIRED:
            raise SyntheticLabPersistenceError("expire command requires an expired record")
        return self._transition_authorization(
            principal=principal,
            record=record,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.EXPIRE_AUTHORIZATION,
            allowed_previous=frozenset({AuthorizationState.APPROVED}),
            forbid_submitter=False,
        )

    def revoke_authorization(
        self,
        *,
        principal: LabPrincipal,
        record: AuthorizationRecord,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        if record.state != AuthorizationState.REVOKED:
            raise SyntheticLabPersistenceError("revoke command requires a revoked record")
        return self._transition_authorization(
            principal=principal,
            record=record,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.REVOKE_AUTHORIZATION,
            allowed_previous=frozenset({AuthorizationState.APPROVED}),
            forbid_submitter=False,
        )

    def admit_automatic_collection(
        self,
        *,
        principal: LabPrincipal,
        request: CollectionAdmissionRequest,
        job_id: UUID,
        outbox_id: UUID,
        style_source_revision_id: UUID,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, request.project_id, LabRole.OPERATOR)
        if request.path != CollectionPath.AUTOMATIC:
            raise SyntheticLabPersistenceError(
                "automatic collection admission requires the automatic path"
            )
        identity = command_identity(
            project_id=request.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.ADMIT_COLLECTION,
            request={
                "request": request,
                "job_id": job_id,
                "outbox_id": outbox_id,
                "style_source_revision_id": style_source_revision_id,
            },
        )
        with self._uow_factory(project_id=request.project_id) as uow:
            replay = recover_command(uow, identity, CollectionAdmissionResult)
            if replay is not None:
                return replay
            envelope = uow.authorizations.current(
                project_id=request.project_id,
                channel=request.channel,
                adapter_release=request.adapter_release,
            )
            decision = admit_collection(request, envelope.record if envelope is not None else None)
            job: SyntheticJob | None = None
            if decision.disposition == AdmissionDisposition.ACCEPTED and decision.create_job:
                binding = decision.binding
                if binding is None:
                    raise SyntheticLabPersistenceError(
                        "accepted automatic collection is missing authorization lineage"
                    )
                job = new_synthetic_job(
                    job_id=job_id,
                    project_id=request.project_id,
                    kind="style_collection",
                    input_hash=canonical_hash(
                        {"request": request, "authorization_hash": binding.authorization_hash}
                    ),
                    payload={
                        "style_source_revision_id": style_source_revision_id,
                        "authorization_id": binding.authorization_id,
                        "authorization_hash": binding.authorization_hash,
                    },
                    runtime_inputs=None,
                    authorization_binding=binding,
                    idempotency_key_hash=identity.idempotency_key_hash,
                )
                uow.jobs.stage(job, expected_version=0)
                uow.outbox.stage(
                    new_outbox_message(
                        message_id=outbox_id,
                        job=job,
                        event_type="synthetic.style_collection.queued",
                    )
                )
            return stage_command(
                uow,
                identity,
                CollectionAdmissionResult(command=decision, job=job),
            )

    def claim_collection_job(
        self,
        *,
        principal: LabPrincipal,
        job_id: UUID,
        expected_version: int,
        claimed_at: datetime,
        lease_for: timedelta,
        authorization_port: CollectionAuthorizationPort,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, principal.project_id, LabRole.WORKER)
        identity = command_identity(
            project_id=principal.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.CLAIM_COLLECTION,
            request={
                "job_id": job_id,
                "expected_version": expected_version,
                "claimed_at": claimed_at,
                "lease_for_seconds": lease_for.total_seconds(),
            },
        )
        with self._uow_factory(project_id=principal.project_id) as uow:
            replay = recover_command(uow, identity, CollectionClaimResult)
            if replay is not None:
                return replay
            current_job = uow.jobs.get(project_id=principal.project_id, job_id=job_id)
            if current_job is None or current_job.authorization_binding is None:
                raise SyntheticLabPersistenceError("collection Job or authorization is missing")
            current_auth = authorization_port.current(current_job.authorization_binding)
            navigation = recheck_before_navigation(
                current_job.authorization_binding, current_auth, at=claimed_at
            )
            claimed: SyntheticJob | None = None
            if navigation.proceed:
                if current_job.status != JobStatus.QUEUED:
                    raise SyntheticLabPersistenceError(
                        "only a queued collection Job can be claimed"
                    )
                claimed = claim_synthetic_job(
                    current_job,
                    worker_id=str(principal.actor_id),
                    at=claimed_at,
                    lease_for=lease_for,
                )
                uow.jobs.stage(claimed, expected_version=expected_version)
            return stage_command(
                uow,
                identity,
                CollectionClaimResult(navigation=navigation, job=claimed),
            )

    def recheck_before_navigation(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        at: datetime,
        authorization_port: CollectionAuthorizationPort,
    ) -> NavigationCommand:
        with self._uow_factory(project_id=project_id) as uow:
            job = uow.jobs.get(project_id=project_id, job_id=job_id)
            if job is None or job.authorization_binding is None:
                raise SyntheticLabPersistenceError("collection Job or authorization is missing")
            return recheck_before_navigation(
                job.authorization_binding,
                authorization_port.current(job.authorization_binding),
                at=at,
            )

    def import_manual_samples(
        self,
        *,
        principal: LabPrincipal,
        request: ManualSampleImportRequest,
        manifest_id: UUID,
        preview_id: UUID,
        inspections: tuple[RawArtifactInspection, ...],
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, request.project_id, LabRole.OPERATOR, LabRole.REVIEWER)
        if request.imported_by != principal.actor_id:
            raise SyntheticLabPermissionDenied(
                "manual import attribution must match the authenticated actor"
            )
        identity = command_identity(
            project_id=request.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.IMPORT_SAMPLES,
            request={
                "request": request,
                "manifest_id": manifest_id,
                "preview_id": preview_id,
                "inspections": inspections,
            },
        )
        with self._uow_factory(project_id=request.project_id) as uow:
            replay = recover_command(uow, identity, ManualSampleImportManifest)
            if replay is not None:
                return replay
            rows = tuple(
                replace(
                    row,
                    dedup_status=SampleDedupStatus.CROSS_RUN_DUPLICATE,
                    nearest_sample_hash=row.normalized_text_hash,
                )
                if uow.imports.contains_sample_hash(
                    project_id=request.project_id,
                    sample_hash=row.normalized_text_hash,
                )
                else row
                for row in request.rows
            )
            normalized_request = replace(request, rows=rows)
            decisions = tuple(govern_raw_artifact(item) for item in inspections)
            if any(item.project_id != request.project_id for item in decisions):
                raise SyntheticLabPersistenceError(
                    "artifact governance evidence belongs to another Project"
                )
            manifest = build_manual_import_manifest(
                normalized_request,
                manifest_id=manifest_id,
                preview_id=preview_id,
            )
            governed_hashes = {
                item.persisted_content_hash for item in decisions if item.persistence_allowed
            }
            if any(
                sample.source_artifact_hash not in governed_hashes
                for sample in manifest.accepted_samples
            ):
                raise SyntheticLabPersistenceError(
                    "accepted manual Sample lacks a persistable governed artifact"
                )
            uow.imports.stage(manifest=manifest, decisions=decisions)
            return stage_command(uow, identity, manifest)

    def _transition_authorization(
        self,
        *,
        principal: LabPrincipal,
        record: AuthorizationRecord,
        expected_version: int,
        idempotency_key: str,
        operation: SyntheticCommandOperation,
        allowed_previous: frozenset[AuthorizationState],
        forbid_submitter: bool,
    ) -> CommandReceipt:
        require_roles(principal, record.project_id, LabRole.APPROVER)
        if record.decided_by != principal.actor_id:
            raise SyntheticLabPermissionDenied(
                "authorization decision attribution must match the actor"
            )
        identity = command_identity(
            project_id=record.project_id,
            idempotency_key=idempotency_key,
            operation=operation,
            request={
                "record": _authorization_decision_request(record),
                "expected_version": expected_version,
            },
        )
        with self._uow_factory(project_id=record.project_id) as uow:
            replay = recover_command(uow, identity, AuthorizationRecord)
            if replay is not None:
                return replay
            current = uow.authorizations.current(
                project_id=record.project_id,
                channel=record.channel,
                adapter_release=record.adapter_release,
            )
            if current is None or current.record.state not in allowed_previous:
                raise SyntheticLabPersistenceError(
                    "authorization transition does not follow the current state"
                )
            if forbid_submitter:
                reject_self_approval(principal, current.submitted_by)
            assert_next_authorization_version(current.record, record)
            if record.state in {AuthorizationState.EXPIRED, AuthorizationState.REVOKED}:
                self._assert_grant_lineage(current.record, record)
            uow.authorizations.stage(
                AuthorizationEnvelope(record=record, submitted_by=current.submitted_by),
                expected_version=expected_version,
            )
            return stage_command(uow, identity, record)

    @staticmethod
    def _assert_grant_lineage(
        previous: AuthorizationRecord,
        current: AuthorizationRecord,
    ) -> None:
        previous_grant = (
            previous.evidence_reference_hash,
            previous.allowed_purposes,
            previous.max_requests_per_period,
            previous.period_seconds,
            previous.max_concurrency,
            previous.expires_at,
        )
        current_grant = (
            current.evidence_reference_hash,
            current.allowed_purposes,
            current.max_requests_per_period,
            current.period_seconds,
            current.max_concurrency,
            current.expires_at,
        )
        if current_grant != previous_grant:
            raise SyntheticLabPersistenceError(
                "expired/revoked authorization must preserve its approved grant lineage"
            )


def _authorization_decision_request(record: AuthorizationRecord) -> dict[str, object]:
    """Exclude only the server clock and its derived hash from idempotency identity."""

    return {
        "id": record.id,
        "project_id": record.project_id,
        "channel": record.channel,
        "adapter_release": record.adapter_release,
        "version_number": record.version_number,
        "previous_version_id": record.previous_version_id,
        "state": record.state,
        "evidence_reference_hash": record.evidence_reference_hash,
        "decided_by": record.decided_by,
        "allowed_purposes": record.allowed_purposes,
        "max_requests_per_period": record.max_requests_per_period,
        "period_seconds": record.period_seconds,
        "max_concurrency": record.max_concurrency,
        "expires_at": record.expires_at,
        "decision_reason": record.decision_reason,
    }


__all__ = [
    "CollectionAdmissionResult",
    "CollectionClaimResult",
    "StyleApplication",
]
