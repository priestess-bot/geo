from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
import hashlib
from uuid import UUID, uuid4

import pytest

from geo_core.synthetic_lab import (
    AdmissionDisposition,
    AuthorizationRecord,
    AuthorizationState,
    AuthorizationTrack,
    CollectionAdmissionCommand,
    CollectionAdmissionRequest,
    CollectionPath,
    SyntheticLabContractError,
    admit_collection,
    assert_next_authorization_version,
    create_authorization_record,
    open_authorization_reassessment,
    recheck_before_navigation,
)


NOW = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _authorization(
    state: AuthorizationState,
    *,
    project_id: UUID | None = None,
    id: UUID | None = None,
    version_number: int = 1,
    previous_version_id: UUID | None = None,
    decided_at: datetime = NOW,
    **changes: object,
) -> AuthorizationRecord:
    values: dict[str, object] = {
        "id": id or uuid4(),
        "project_id": project_id or uuid4(),
        "channel": "reddit",
        "adapter_release": "style-reddit-v1",
        "version_number": version_number,
        "previous_version_id": previous_version_id,
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
            {
                "decided_by": uuid4(),
                "decided_at": decided_at,
                "decision_reason": f"decision-{state.value}",
            }
        )
    if state == AuthorizationState.APPROVED:
        values.update(
            {
                "evidence_reference_hash": _hash("terms-review-v1"),
                "allowed_purposes": ("style_collection",),
                "max_requests_per_period": 10,
                "period_seconds": 60,
                "max_concurrency": 2,
                "expires_at": decided_at + timedelta(days=30),
            }
        )
    if state in {AuthorizationState.EXPIRED, AuthorizationState.REVOKED}:
        values.update(
            {
                "evidence_reference_hash": _hash("prior-approval"),
                "allowed_purposes": ("style_collection",),
                "max_requests_per_period": 10,
                "period_seconds": 60,
                "max_concurrency": 2,
                "expires_at": decided_at - timedelta(seconds=1)
                if state == AuthorizationState.EXPIRED
                else decided_at + timedelta(days=30),
            }
        )
    values.update(changes)
    return create_authorization_record(**values)


def _request(
    project_id: UUID,
    *,
    path: CollectionPath = CollectionPath.AUTOMATIC,
    requested_at: datetime = NOW + timedelta(minutes=1),
    **changes: object,
) -> CollectionAdmissionRequest:
    values: dict[str, object] = {
        "project_id": project_id,
        "channel": "reddit",
        "adapter_release": "style-reddit-v1",
        "path": path,
        "purpose": "style_collection",
        "requested_at": requested_at,
        "planned_requests": 10,
        "planned_period_seconds": 60,
        "planned_concurrency": 2,
    }
    values.update(changes)
    return CollectionAdmissionRequest(**values)  # type: ignore[arg-type]


def test_authorization_versions_are_hashed_immutable_and_contiguous() -> None:
    project_id = uuid4()
    first = _authorization(AuthorizationState.NOT_ASSESSED, project_id=project_id)
    approved = _authorization(
        AuthorizationState.APPROVED,
        project_id=project_id,
        version_number=2,
        previous_version_id=first.id,
    )

    assert_next_authorization_version(first, approved)
    assert len(approved.record_hash) == 64
    with pytest.raises(FrozenInstanceError):
        approved.version_number = 3  # type: ignore[misc]
    with pytest.raises(SyntheticLabContractError, match="immutable hash"):
        replace(approved, allowed_purposes=("another_use",))
    skipped = _authorization(
        AuthorizationState.APPROVED,
        project_id=project_id,
        version_number=3,
        previous_version_id=first.id,
    )
    with pytest.raises(SyntheticLabContractError, match="contiguous identity"):
        assert_next_authorization_version(first, skipped)


def test_automatic_admission_freezes_exact_approved_authorization_and_is_atomic() -> None:
    authorization = _authorization(AuthorizationState.APPROVED)
    command = admit_collection(_request(authorization.project_id), authorization)

    assert command.disposition == AdmissionDisposition.ACCEPTED
    assert command.track == AuthorizationTrack.A_AUTOMATIC
    assert command.create_job and command.emit_outbox and command.may_issue_network_request
    assert command.binding is not None
    assert command.binding.authorization_id == authorization.id
    assert command.binding.version_number == authorization.version_number
    assert command.binding.authorization_hash == authorization.record_hash


@pytest.mark.parametrize(
    "state",
    [
        AuthorizationState.NOT_ASSESSED,
        AuthorizationState.ASSESSED_NO_BASIS,
        AuthorizationState.EXPIRED,
        AuthorizationState.REVOKED,
    ],
)
def test_nonapproved_automatic_admission_returns_zero_job_outbox_network(
    state: AuthorizationState,
) -> None:
    authorization = _authorization(state)
    command = admit_collection(_request(authorization.project_id), authorization)

    assert command.disposition == AdmissionDisposition.REJECTED
    assert command.binding is None
    assert not command.create_job
    assert not command.emit_outbox
    assert not command.may_issue_network_request


def test_missing_expired_wrong_purpose_scope_or_frequency_fail_closed() -> None:
    authorization = _authorization(AuthorizationState.APPROVED)
    requests = (
        (_request(authorization.project_id), None),
        (
            _request(
                authorization.project_id,
                requested_at=authorization.expires_at,  # type: ignore[arg-type]
            ),
            authorization,
        ),
        (_request(authorization.project_id, purpose="unapproved_use"), authorization),
        (_request(authorization.project_id, planned_requests=11), authorization),
        (_request(uuid4()), authorization),
    )

    for request, record in requests:
        command = admit_collection(request, record)
        assert command.disposition == AdmissionDisposition.REJECTED
        assert (command.create_job, command.emit_outbox, command.may_issue_network_request) == (
            False,
            False,
            False,
        )


@pytest.mark.parametrize("path", [CollectionPath.FIXTURE, CollectionPath.MANUAL_IMPORT])
def test_b_track_accepts_only_nonlive_fixture_or_manual_commands(path: CollectionPath) -> None:
    authorization = _authorization(AuthorizationState.ASSESSED_NO_BASIS)
    command = admit_collection(
        _request(authorization.project_id, path=path),
        authorization,
    )

    assert command.disposition == AdmissionDisposition.ACCEPTED
    assert command.track == AuthorizationTrack.B_FIXTURE_OR_MANUAL
    assert command.binding is None
    assert not command.create_job
    assert not command.emit_outbox
    assert not command.may_issue_network_request


def test_rejected_command_cannot_smuggle_job_or_outbox_intents() -> None:
    with pytest.raises(SyntheticLabContractError, match="zero Job"):
        CollectionAdmissionCommand(
            disposition=AdmissionDisposition.REJECTED,
            track=AuthorizationTrack.B_FIXTURE_OR_MANUAL,
            reason_code="denied",
            binding=None,
            create_job=True,
            emit_outbox=True,
            may_issue_network_request=True,
        )


def test_claim_and_navigation_recheck_stops_changed_revoked_or_expired_authorization() -> None:
    approved = _authorization(AuthorizationState.APPROVED)
    admitted = admit_collection(_request(approved.project_id), approved)
    assert admitted.binding is not None
    binding = admitted.binding

    proceed = recheck_before_navigation(binding, approved, at=NOW + timedelta(minutes=2))
    assert proceed.proceed and proceed.issue_network_request

    revoked = _authorization(
        AuthorizationState.REVOKED,
        project_id=approved.project_id,
        version_number=2,
        previous_version_id=approved.id,
    )
    for current, at in (
        (None, NOW + timedelta(minutes=2)),
        (revoked, NOW + timedelta(minutes=2)),
        (approved, approved.expires_at),
    ):
        stopped = recheck_before_navigation(binding, current, at=at)  # type: ignore[arg-type]
        assert not stopped.proceed
        assert not stopped.issue_network_request


@pytest.mark.parametrize(
    "terminal_state",
    (
        AuthorizationState.ASSESSED_NO_BASIS,
        AuthorizationState.EXPIRED,
        AuthorizationState.REVOKED,
    ),
)
def test_terminal_authorization_opens_blank_reassessment_then_accepts_fresh_decision(
    terminal_state: AuthorizationState,
) -> None:
    previous = _authorization(terminal_state)
    pending = open_authorization_reassessment(
        previous,
        reassessment_id=uuid4(),
        opened_at=NOW + timedelta(days=31),
    )
    approved = _authorization(
        AuthorizationState.APPROVED,
        project_id=previous.project_id,
        version_number=pending.version_number + 1,
        previous_version_id=pending.id,
        evidence_reference_hash=_hash(f"fresh-evidence-{terminal_state.value}"),
    )

    assert pending.state is AuthorizationState.NOT_ASSESSED
    assert pending.previous_version_id == previous.id
    assert pending.evidence_reference_hash is None
    assert pending.allowed_purposes == ()
    assert pending.decided_by is None
    assert_next_authorization_version(pending, approved)


def test_opening_reassessment_makes_old_approved_binding_stale_without_mutating_lineage() -> None:
    approved = _authorization(
        AuthorizationState.APPROVED,
        decided_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    admission = admit_collection(
        _request(approved.project_id, requested_at=NOW + timedelta(seconds=30)),
        approved,
    )
    assert admission.binding is not None
    original_hash = approved.record_hash
    pending = open_authorization_reassessment(
        approved,
        reassessment_id=uuid4(),
        opened_at=NOW + timedelta(minutes=2),
    )

    stopped = recheck_before_navigation(
        admission.binding,
        pending,
        at=NOW + timedelta(minutes=2),
    )
    assert not stopped.proceed
    assert approved.record_hash == original_hash
    assert admission.binding.authorization_hash == original_hash


def test_authorization_commands_remain_internal_synthetic_nonpublication() -> None:
    authorization = _authorization(AuthorizationState.APPROVED)
    request = _request(authorization.project_id)
    command = admit_collection(request, authorization)
    resources = (authorization, request, command, command.binding)

    assert all(item is not None and item.synthetic for item in resources)
    assert all(item is not None and item.test_only for item in resources)
    assert not any(item is not None and item.publication_eligible for item in resources)
