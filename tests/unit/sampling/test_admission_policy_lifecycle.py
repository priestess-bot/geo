from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest

from geo_core.sampling import (
    AdmissionPolicyStatus,
    AuthorizationState,
    CaptureMethod,
    SamplingAdmissionPolicyRecord,
    SamplingRuleViolation,
    decide_admission_policy,
    revoke_admission_policy,
    submit_admission_policy,
)

from tests.unit.sampling.factories import NOW


PROJECT_ID = UUID("51000000-0000-4000-8000-000000000001")
POLICY_ID = UUID("52000000-0000-4000-8000-000000000002")


def test_policy_definition_is_immutable_across_maker_checker_approval() -> None:
    draft = _draft()
    submitted = submit_admission_policy(
        draft, actor_id="sampling-maker", occurred_at=NOW + timedelta(minutes=1)
    )

    with pytest.raises(SamplingRuleViolation, match="maker cannot"):
        decide_admission_policy(
            submitted,
            actor_id="sampling-maker",
            occurred_at=NOW + timedelta(minutes=2),
            reason="Self approval is forbidden.",
            approved=True,
        )

    approved = decide_admission_policy(
        submitted,
        actor_id="sampling-checker",
        occurred_at=NOW + timedelta(minutes=2),
        reason="Terms evidence and frozen limits reviewed.",
        approved=True,
    )
    policy = approved.approved_policy(at=NOW + timedelta(minutes=3))

    assert approved.status is AdmissionPolicyStatus.APPROVED
    assert approved.aggregate_version == 3
    assert approved.definition_hash == draft.definition_hash
    assert approved.policy_version == draft.policy_version
    assert policy.id == approved.id
    assert policy.authorization_state is AuthorizationState.APPROVED
    assert policy.policy_hash


def test_no_basis_is_a_terminal_explicit_authorization_decision() -> None:
    submitted = submit_admission_policy(_draft(), actor_id="sampling-maker", occurred_at=NOW)
    decided = decide_admission_policy(
        submitted,
        actor_id="sampling-checker",
        occurred_at=NOW,
        reason="No acceptable automation basis was found.",
        approved=False,
    )

    assert decided.status is AdmissionPolicyStatus.ASSESSED_NO_BASIS
    assert decided.effective_authorization_state(at=NOW) is AuthorizationState.ASSESSED_NO_BASIS
    with pytest.raises(SamplingRuleViolation, match="assessed_no_basis"):
        decided.approved_policy(at=NOW)


def test_approved_policy_expires_without_mutating_its_frozen_definition() -> None:
    approved = _approved()
    original_hash = approved.definition_hash

    assert (
        approved.effective_authorization_state(at=approved.valid_until)
        is AuthorizationState.EXPIRED
    )
    assert approved.definition_hash == original_hash
    with pytest.raises(SamplingRuleViolation, match="expired"):
        approved.approved_policy(at=approved.valid_until)


def test_revocation_preserves_decision_audit_and_blocks_future_use() -> None:
    approved = _approved()
    revoked = revoke_admission_policy(
        approved,
        actor_id="security-owner",
        occurred_at=NOW + timedelta(minutes=3),
        reason="Provider authorization was withdrawn.",
    )

    assert revoked.status is AdmissionPolicyStatus.REVOKED
    assert revoked.decided_by == "sampling-checker"
    assert revoked.revoked_by == "security-owner"
    assert revoked.definition_hash == approved.definition_hash
    with pytest.raises(SamplingRuleViolation, match="revoked"):
        revoked.approved_policy(at=NOW + timedelta(minutes=4))


def _draft() -> SamplingAdmissionPolicyRecord:
    return SamplingAdmissionPolicyRecord(
        id=POLICY_ID,
        project_id=PROJECT_ID,
        revision=1,
        supersedes_policy_id=None,
        platform="openai",
        capture_method=CaptureMethod.PROVIDER_API,
        adapter_release="openai-web-search@2026-07-23",
        location_control="country",
        location_evidence_hash="a" * 64,
        authorization_reference="authorization:terms-review:42",
        authorized_purposes=("geo_measurement",),
        valid_until=NOW + timedelta(days=30),
        quota_remaining=100,
        daily_task_limit=20,
        minimum_request_interval_seconds=2,
        max_concurrency=2,
        next_allowed_at=NOW,
        created_by="sampling-maker",
        created_at=NOW,
    )


def _approved() -> SamplingAdmissionPolicyRecord:
    submitted = submit_admission_policy(
        _draft(), actor_id="sampling-maker", occurred_at=NOW + timedelta(minutes=1)
    )
    return decide_admission_policy(
        submitted,
        actor_id="sampling-checker",
        occurred_at=NOW + timedelta(minutes=2),
        reason="Terms evidence and frozen limits reviewed.",
        approved=True,
    )
