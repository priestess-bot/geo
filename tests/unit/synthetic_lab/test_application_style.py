from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from uuid import UUID, uuid4

import pytest

from geo_core.synthetic_lab.authorization import (
    AdmissionDisposition,
    AuthorizationState,
    CollectionAdmissionRequest,
    CollectionPath,
    create_authorization_record,
)
from geo_core.synthetic_lab.memory import (
    InMemoryCollectionAuthorizationPort,
    InMemorySyntheticLabStore,
    InMemorySyntheticLabUnitOfWorkFactory,
)
from geo_core.synthetic_lab.ports import (
    LabPrincipal,
    LabRole,
    SyntheticLabIdempotencyConflict,
    SyntheticLabPermissionDenied,
    SyntheticLabPersistenceError,
)
from geo_core.synthetic_lab.raw_artifact_governance import (
    ArtifactAccessClass,
    ArtifactForm,
    RawArtifactInspection,
)
from geo_core.synthetic_lab.sample_import import (
    ManualSampleImportRequest,
    ManualSampleRow,
    SampleDedupStatus,
    SampleSourceRights,
)
from geo_core.synthetic_lab.style_application import (
    CollectionAdmissionResult,
    CollectionClaimResult,
    StyleApplication,
)


NOW = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _principal(project_id: UUID, role: LabRole, *, actor_id: UUID | None = None):
    return LabPrincipal(
        project_id=project_id,
        actor_id=actor_id or uuid4(),
        roles=frozenset({role}),
    )


def _authorization(
    project_id: UUID,
    state: AuthorizationState,
    *,
    actor_id: UUID | None = None,
    version: int = 1,
    previous_id: UUID | None = None,
    **changes: object,
):
    values: dict[str, object] = {
        "id": uuid4(),
        "project_id": project_id,
        "channel": "reddit",
        "adapter_release": "reddit-style-v1",
        "version_number": version,
        "previous_version_id": previous_id,
        "state": state,
        "evidence_reference_hash": None,
        "decided_by": None,
        "decided_at": None,
        "allowed_purposes": (),
        "max_requests_per_period": None,
        "period_seconds": None,
        "max_concurrency": None,
        "expires_at": None,
        "decision_reason": None,
    }
    if state != AuthorizationState.NOT_ASSESSED:
        values.update(
            decided_by=actor_id or uuid4(),
            decided_at=NOW,
            decision_reason=f"reviewed-{state.value}",
        )
    if state in {
        AuthorizationState.APPROVED,
        AuthorizationState.REVOKED,
        AuthorizationState.EXPIRED,
    }:
        values.update(
            evidence_reference_hash=_hash("authorization-evidence"),
            allowed_purposes=("style_collection",),
            max_requests_per_period=10,
            period_seconds=60,
            max_concurrency=2,
            expires_at=(
                NOW - timedelta(seconds=1)
                if state == AuthorizationState.EXPIRED
                else NOW + timedelta(days=30)
            ),
        )
    values.update(changes)
    return create_authorization_record(**values)


def _admission(project_id: UUID) -> CollectionAdmissionRequest:
    return CollectionAdmissionRequest(
        project_id=project_id,
        channel="reddit",
        adapter_release="reddit-style-v1",
        path=CollectionPath.AUTOMATIC,
        purpose="style_collection",
        requested_at=NOW + timedelta(minutes=1),
        planned_requests=5,
        planned_period_seconds=60,
        planned_concurrency=1,
    )


def _approved_application():
    project_id = uuid4()
    submitter = _principal(project_id, LabRole.OPERATOR)
    approver = _principal(project_id, LabRole.APPROVER)
    store = InMemorySyntheticLabStore()
    app = StyleApplication(InMemorySyntheticLabUnitOfWorkFactory(store))
    initial = _authorization(project_id, AuthorizationState.NOT_ASSESSED)
    app.create_authorization(
        principal=submitter,
        record=initial,
        expected_version=0,
        idempotency_key="authorization-create",
    )
    approved = _authorization(
        project_id,
        AuthorizationState.APPROVED,
        actor_id=approver.actor_id,
        version=2,
        previous_id=initial.id,
    )
    app.decide_authorization(
        principal=approver,
        record=approved,
        expected_version=1,
        idempotency_key="authorization-approve",
    )
    return project_id, submitter, approver, store, app, approved


def test_authorization_lifecycle_exact_replay_and_self_approval_limit() -> None:
    project_id = uuid4()
    submitter = _principal(project_id, LabRole.OPERATOR)
    self_approver = _principal(project_id, LabRole.APPROVER, actor_id=submitter.actor_id)
    reviewer = _principal(project_id, LabRole.APPROVER)
    store = InMemorySyntheticLabStore()
    app = StyleApplication(InMemorySyntheticLabUnitOfWorkFactory(store))
    initial = _authorization(project_id, AuthorizationState.NOT_ASSESSED)

    first = app.create_authorization(
        principal=submitter,
        record=initial,
        expected_version=0,
        idempotency_key="create-auth",
    )
    replay = app.create_authorization(
        principal=submitter,
        record=initial,
        expected_version=0,
        idempotency_key="create-auth",
    )
    assert not first.replayed and replay.replayed

    self_decision = _authorization(
        project_id,
        AuthorizationState.APPROVED,
        actor_id=submitter.actor_id,
        version=2,
        previous_id=initial.id,
    )
    with pytest.raises(SyntheticLabPermissionDenied, match="own resource"):
        app.decide_authorization(
            principal=self_approver,
            record=self_decision,
            expected_version=1,
            idempotency_key="self-approval",
        )

    approved = _authorization(
        project_id,
        AuthorizationState.APPROVED,
        actor_id=reviewer.actor_id,
        version=2,
        previous_id=initial.id,
    )
    app.decide_authorization(
        principal=reviewer,
        record=approved,
        expected_version=1,
        idempotency_key="reviewer-approval",
    )
    with pytest.raises(SyntheticLabIdempotencyConflict, match="reused"):
        app.create_authorization(
            principal=submitter,
            record=initial,
            expected_version=1,
            idempotency_key="create-auth",
        )


def test_automatic_admission_job_outbox_are_atomic_and_rechecked_at_claim() -> None:
    project_id, _, approver, store, app, approved = _approved_application()
    operator = _principal(project_id, LabRole.OPERATOR)
    worker = _principal(project_id, LabRole.WORKER)
    job_id = uuid4()
    receipt = app.admit_automatic_collection(
        principal=operator,
        request=_admission(project_id),
        job_id=job_id,
        outbox_id=uuid4(),
        style_source_revision_id=uuid4(),
        idempotency_key="admit-live",
    )
    result = receipt.result
    assert isinstance(result, CollectionAdmissionResult)
    assert result.command.disposition == AdmissionDisposition.ACCEPTED
    assert result.job is not None
    assert store.job_count(project_id) == store.outbox_count(project_id) == 1
    assert all(key.endswith(("_id", "_hash")) for key in result.job.payload)

    claimed = app.claim_collection_job(
        principal=worker,
        job_id=job_id,
        expected_version=1,
        claimed_at=NOW + timedelta(minutes=2),
        lease_for=timedelta(minutes=10),
        authorization_port=InMemoryCollectionAuthorizationPort(store),
        idempotency_key="claim-live",
    ).result
    assert isinstance(claimed, CollectionClaimResult)
    assert claimed.navigation.proceed and claimed.job is not None

    revoked = _authorization(
        project_id,
        AuthorizationState.REVOKED,
        actor_id=approver.actor_id,
        version=3,
        previous_id=approved.id,
    )
    app.revoke_authorization(
        principal=approver,
        record=revoked,
        expected_version=2,
        idempotency_key="revoke-live",
    )
    navigation = app.recheck_before_navigation(
        project_id=project_id,
        job_id=job_id,
        at=NOW + timedelta(minutes=3),
        authorization_port=InMemoryCollectionAuthorizationPort(store),
    )
    assert not navigation.proceed and not navigation.issue_network_request


def test_expire_preserves_the_approved_grant_lineage() -> None:
    project_id, _, approver, store, app, approved = _approved_application()
    expired = _authorization(
        project_id,
        AuthorizationState.EXPIRED,
        actor_id=approver.actor_id,
        version=3,
        previous_id=approved.id,
        evidence_reference_hash=approved.evidence_reference_hash,
        allowed_purposes=approved.allowed_purposes,
        max_requests_per_period=approved.max_requests_per_period,
        period_seconds=approved.period_seconds,
        max_concurrency=approved.max_concurrency,
        expires_at=approved.expires_at,
        decided_at=approved.expires_at,
    )
    app.expire_authorization(
        principal=approver,
        record=expired,
        expected_version=2,
        idempotency_key="expire-authorization",
    )
    current = store.get_authorization(
        project_id=project_id,
        channel="reddit",
        adapter_release="reddit-style-v1",
    )
    assert current is not None and current.record.state == AuthorizationState.EXPIRED


def test_no_basis_reassessment_requires_new_maker_checker_and_fresh_evidence() -> None:
    project_id = uuid4()
    first_maker = _principal(project_id, LabRole.OPERATOR)
    first_reviewer = _principal(project_id, LabRole.APPROVER)
    reassessment_maker = _principal(project_id, LabRole.OPERATOR)
    second_reviewer = _principal(project_id, LabRole.APPROVER)
    store = InMemorySyntheticLabStore()
    app = StyleApplication(InMemorySyntheticLabUnitOfWorkFactory(store))
    initial = _authorization(project_id, AuthorizationState.NOT_ASSESSED)
    app.create_authorization(
        principal=first_maker,
        record=initial,
        expected_version=0,
        idempotency_key="reassessment-initial",
    )
    no_basis = _authorization(
        project_id,
        AuthorizationState.ASSESSED_NO_BASIS,
        actor_id=first_reviewer.actor_id,
        version=2,
        previous_id=initial.id,
    )
    app.decide_authorization(
        principal=first_reviewer,
        record=no_basis,
        expected_version=1,
        idempotency_key="reassessment-no-basis",
    )
    pending_id = uuid4()
    pending = app.reassess_authorization(
        principal=reassessment_maker,
        previous=no_basis,
        reassessment_id=pending_id,
        opened_at=NOW + timedelta(hours=1),
        reassessment_reason="terms and account basis changed",
        expected_version=2,
        idempotency_key="reassessment-open",
    ).result
    assert pending.state is AuthorizationState.NOT_ASSESSED
    assert pending.evidence_reference_hash is None

    approved = _authorization(
        project_id,
        AuthorizationState.APPROVED,
        actor_id=second_reviewer.actor_id,
        version=4,
        previous_id=pending_id,
        evidence_reference_hash=_hash("fresh-reassessment-evidence"),
        decided_at=NOW + timedelta(hours=2),
    )
    self_decision = _authorization(
        project_id,
        AuthorizationState.APPROVED,
        actor_id=reassessment_maker.actor_id,
        version=4,
        previous_id=pending_id,
        evidence_reference_hash=_hash("fresh-reassessment-evidence"),
        decided_at=NOW + timedelta(hours=2),
    )
    with pytest.raises(SyntheticLabPermissionDenied, match="own resource"):
        app.decide_authorization(
            principal=_principal(
                project_id,
                LabRole.APPROVER,
                actor_id=reassessment_maker.actor_id,
            ),
            record=self_decision,
            expected_version=3,
            idempotency_key="reassessment-self-approval",
        )
    app.decide_authorization(
        principal=second_reviewer,
        record=approved,
        expected_version=3,
        idempotency_key="reassessment-fresh-approval",
    )
    current = store.get_authorization(
        project_id=project_id,
        channel="reddit",
        adapter_release="reddit-style-v1",
    )
    assert current is not None
    assert current.record.state is AuthorizationState.APPROVED
    assert current.record.evidence_reference_hash == _hash("fresh-reassessment-evidence")


def test_denied_admission_has_no_job_or_outbox_and_commit_failure_rolls_back_all() -> None:
    project_id = uuid4()
    operator = _principal(project_id, LabRole.OPERATOR)
    store = InMemorySyntheticLabStore()
    app = StyleApplication(InMemorySyntheticLabUnitOfWorkFactory(store))
    denied = app.admit_automatic_collection(
        principal=operator,
        request=_admission(project_id),
        job_id=uuid4(),
        outbox_id=uuid4(),
        style_source_revision_id=uuid4(),
        idempotency_key="missing-auth",
    ).result
    assert isinstance(denied, CollectionAdmissionResult)
    assert denied.command.disposition == AdmissionDisposition.REJECTED
    assert denied.job is None
    assert store.job_count(project_id) == store.outbox_count(project_id) == 0

    approved_project, _, _, approved_store, approved_app, _ = _approved_application()
    approved_store.fail_next_commit()
    with pytest.raises(SyntheticLabPersistenceError, match="simulated"):
        approved_app.admit_automatic_collection(
            principal=_principal(approved_project, LabRole.OPERATOR),
            request=_admission(approved_project),
            job_id=uuid4(),
            outbox_id=uuid4(),
            style_source_revision_id=uuid4(),
            idempotency_key="rolled-back-admission",
        )
    assert approved_store.job_count(approved_project) == 0
    assert approved_store.outbox_count(approved_project) == 0


def _row(number: int, *, text_hash: str | None = None) -> ManualSampleRow:
    artifact_hash = _hash(f"artifact-{number}-{uuid4()}")
    return ManualSampleRow(
        row_number=number,
        sample_id=uuid4(),
        source_locator_hash=_hash(f"locator-{number}"),
        source_artifact_hash=artifact_hash,
        normalized_text_hash=text_hash or _hash(f"text-{number}"),
        text_length=100,
        au_english_declared=True,
        language_reviewer_id=uuid4(),
        language_reviewed_at=NOW,
        anonymization_verified=True,
        unresolved_pii_codes=(),
        dedup_status=SampleDedupStatus.UNIQUE,
        nearest_sample_hash=None,
        source_rights=SampleSourceRights.AUTHORIZED_MANUAL_CAPTURE,
        rights_evidence_hash=_hash(f"rights-{number}"),
        source_overlap_ratio=0.1,
        reproduction_risk=False,
    )


def _import_request(
    project_id: UUID, actor_id: UUID, row: ManualSampleRow
) -> ManualSampleImportRequest:
    return ManualSampleImportRequest(
        id=uuid4(),
        project_id=project_id,
        channel="reddit",
        locale="en-AU",
        style_source_revision_id=uuid4(),
        source_revision_number=1,
        collection_run_id=uuid4(),
        imported_by=actor_id,
        imported_at=NOW,
        schema_release="manual-v1",
        submitted_field_names=("anonymous_text", "source_artifact"),
        rows=(row,),
    )


def _inspection(project_id: UUID, row: ManualSampleRow) -> RawArtifactInspection:
    return RawArtifactInspection(
        artifact_id=uuid4(),
        project_id=project_id,
        captured_at=NOW,
        access_class=ArtifactAccessClass.PUBLIC,
        form=ArtifactForm.DERIVED,
        payload_hash=row.source_artifact_hash,
        detected_findings=(),
        unresolved_findings=(),
        redaction_applied=False,
        redaction_verified=False,
        redacted_payload_hash=None,
        anonymization_verified=True,
    )


def test_manual_import_governs_before_persistence_and_dedupes_across_runs() -> None:
    project_id = uuid4()
    operator = _principal(project_id, LabRole.OPERATOR)
    store = InMemorySyntheticLabStore()
    app = StyleApplication(InMemorySyntheticLabUnitOfWorkFactory(store))
    first_row = _row(1)
    first = _import_request(project_id, operator.actor_id, first_row)
    manifest = app.import_manual_samples(
        principal=operator,
        request=first,
        manifest_id=uuid4(),
        preview_id=uuid4(),
        inspections=(_inspection(project_id, first_row),),
        idempotency_key="manual-import-1",
    ).result
    assert manifest.accepted_count == 1

    duplicate_row = _row(2, text_hash=first_row.normalized_text_hash)
    second = _import_request(project_id, operator.actor_id, duplicate_row)
    duplicate = app.import_manual_samples(
        principal=operator,
        request=second,
        manifest_id=uuid4(),
        preview_id=uuid4(),
        inspections=(_inspection(project_id, duplicate_row),),
        idempotency_key="manual-import-2",
    ).result
    assert duplicate.accepted_count == 0
    assert duplicate.duplicate_row_count == 1
    assert {error.code for error in duplicate.row_errors} == {"duplicate_cross_run_duplicate"}
