from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from uuid import uuid4

import pytest

from geo_core.synthetic_lab import (
    ArtifactAccessClass,
    ArtifactAudience,
    ArtifactForm,
    ArtifactLegalHold,
    ArtifactStorageTier,
    RawArtifactClassification,
    RawArtifactInspection,
    SensitiveFinding,
    SyntheticLabContractError,
    SyntheticLabScopeError,
    assert_storage_target,
    can_read_artifact,
    create_artifact_tombstone,
    govern_raw_artifact,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _inspection(**changes: object) -> RawArtifactInspection:
    values: dict[str, object] = {
        "artifact_id": uuid4(),
        "project_id": uuid4(),
        "captured_at": NOW,
        "access_class": ArtifactAccessClass.PUBLIC,
        "form": ArtifactForm.RAW,
        "payload_hash": _hash("raw-payload"),
        "detected_findings": (),
        "unresolved_findings": (),
        "redaction_applied": False,
        "redaction_verified": False,
        "redacted_payload_hash": None,
        "anonymization_verified": False,
        "policy_max_ttl_days": None,
    }
    values.update(changes)
    return RawArtifactInspection(**values)  # type: ignore[arg-type]


def test_public_raw_uses_encrypted_internal_bucket_for_at_most_90_days() -> None:
    decision = govern_raw_artifact(_inspection())

    assert decision.classification == RawArtifactClassification.PUBLIC_RAW
    assert decision.storage_tier == ArtifactStorageTier.ENCRYPTED_RAW
    assert decision.persistence_allowed
    assert not decision.independent_dek_required
    assert decision.ttl_days == 90
    assert decision.expires_at == NOW + timedelta(days=90)
    assert decision.allowed_audiences == (ArtifactAudience.INTERNAL_EVIDENCE,)
    assert not decision.customer_visible
    assert not decision.general_export_allowed


def test_authenticated_raw_requires_verified_redaction_restricted_bucket_and_own_dek() -> None:
    inspection = _inspection(
        access_class=ArtifactAccessClass.AUTHENTICATED,
        detected_findings=(SensitiveFinding.COOKIE, SensitiveFinding.USERNAME),
        unresolved_findings=(),
        redaction_applied=True,
        redaction_verified=True,
        redacted_payload_hash=_hash("redacted-payload"),
    )
    decision = govern_raw_artifact(inspection)

    assert decision.classification == RawArtifactClassification.RESTRICTED_AUTHENTICATED_RAW
    assert decision.persisted_content_hash == _hash("redacted-payload")
    assert decision.storage_tier == ArtifactStorageTier.RESTRICTED_INDEPENDENT_DEK
    assert decision.independent_dek_required
    assert decision.ttl_days == 30
    assert set(decision.allowed_audiences) == {
        ArtifactAudience.STYLE_RAW_REVIEWER,
        ArtifactAudience.SECURITY_AUDITOR,
    }
    with pytest.raises(SyntheticLabContractError, match="requested storage tier"):
        assert_storage_target(decision, ArtifactStorageTier.ENCRYPTED_RAW)
    assert_storage_target(decision, ArtifactStorageTier.RESTRICTED_INDEPENDENT_DEK)


@pytest.mark.parametrize(
    "finding",
    [
        SensitiveFinding.COOKIE,
        SensitiveFinding.AUTHORIZATION,
        SensitiveFinding.SESSION_TOKEN,
        SensitiveFinding.PASSWORD,
        SensitiveFinding.STORAGE_STATE,
        SensitiveFinding.EMAIL,
        SensitiveFinding.DIRECT_IDENTIFIER,
    ],
)
def test_unresolved_secret_or_pii_is_rejected_before_any_persistence(
    finding: SensitiveFinding,
) -> None:
    decision = govern_raw_artifact(
        _inspection(
            detected_findings=(finding,),
            unresolved_findings=(finding,),
        )
    )

    assert decision.classification == RawArtifactClassification.SECRET_BEARING_REJECTED
    assert not decision.persistence_allowed
    assert decision.storage_tier == ArtifactStorageTier.NONE
    assert decision.allowed_audiences == ()
    assert decision.ttl_days == 0
    assert decision.expires_at is None
    assert decision.destroy_temporary_payload
    with pytest.raises(SyntheticLabContractError, match="requested storage tier"):
        assert_storage_target(decision, ArtifactStorageTier.DERIVED_PROJECT)


def test_removed_sensitive_findings_require_verified_changed_redaction_hash() -> None:
    with pytest.raises(SyntheticLabContractError, match="verified redaction"):
        _inspection(
            detected_findings=(SensitiveFinding.COOKIE,),
            unresolved_findings=(),
        )
    with pytest.raises(SyntheticLabContractError, match="change the payload hash"):
        _inspection(
            detected_findings=(SensitiveFinding.COOKIE,),
            unresolved_findings=(),
            redaction_applied=True,
            redaction_verified=True,
            redacted_payload_hash=_hash("raw-payload"),
        )


def test_derived_anonymized_is_separate_and_never_customer_export_or_recommendation() -> None:
    decision = govern_raw_artifact(
        _inspection(
            form=ArtifactForm.DERIVED,
            anonymization_verified=True,
        )
    )

    assert decision.classification == RawArtifactClassification.DERIVED_ANONYMIZED
    assert decision.storage_tier == ArtifactStorageTier.DERIVED_PROJECT
    assert decision.ttl_days is None
    assert can_read_artifact(decision, ArtifactAudience.PROJECT_OPERATOR)
    assert can_read_artifact(decision, ArtifactAudience.MODEL_GENERATION)
    for audience in (
        ArtifactAudience.CUSTOMER,
        ArtifactAudience.GENERAL_EXPORT,
        ArtifactAudience.RECOMMENDATION,
    ):
        assert not can_read_artifact(decision, audience)

    with pytest.raises(SyntheticLabContractError, match="verified anonymization"):
        govern_raw_artifact(_inspection(form=ArtifactForm.DERIVED))

    shorter = govern_raw_artifact(
        _inspection(
            form=ArtifactForm.DERIVED,
            anonymization_verified=True,
            policy_max_ttl_days=5,
        )
    )
    assert shorter.ttl_days == 5
    assert shorter.expires_at == NOW + timedelta(days=5)


def test_restricted_content_and_shorter_platform_ttl_override_public_defaults() -> None:
    decision = govern_raw_artifact(
        _inspection(
            detected_findings=(SensitiveFinding.RESTRICTED_CONTENT,),
            policy_max_ttl_days=7,
        )
    )
    rejected_by_policy = govern_raw_artifact(_inspection(policy_max_ttl_days=0))

    assert decision.classification == RawArtifactClassification.RESTRICTED_AUTHENTICATED_RAW
    assert decision.ttl_days == 7
    assert decision.expires_at == NOW + timedelta(days=7)
    assert not rejected_by_policy.persistence_allowed


def test_raw_rbac_never_admits_customer_export_recommendation_or_model_generation() -> None:
    decisions = (
        govern_raw_artifact(_inspection()),
        govern_raw_artifact(_inspection(access_class=ArtifactAccessClass.AUTHENTICATED)),
    )
    forbidden = (
        ArtifactAudience.CUSTOMER,
        ArtifactAudience.GENERAL_EXPORT,
        ArtifactAudience.RECOMMENDATION,
        ArtifactAudience.MODEL_GENERATION,
    )

    assert can_read_artifact(decisions[0], ArtifactAudience.INTERNAL_EVIDENCE)
    assert can_read_artifact(decisions[1], ArtifactAudience.STYLE_RAW_REVIEWER)
    assert all(
        not can_read_artifact(decision, audience)
        for decision in decisions
        for audience in forbidden
    )


def test_ttl_deletion_destroys_object_and_dek_and_retains_only_tombstone() -> None:
    decision = govern_raw_artifact(_inspection())
    assert decision.expires_at is not None
    with pytest.raises(SyntheticLabContractError, match="not expired"):
        create_artifact_tombstone(
            decision,
            deleted_at=decision.expires_at - timedelta(seconds=1),
        )

    tombstone = create_artifact_tombstone(decision, deleted_at=decision.expires_at)
    assert tombstone.object_deleted
    assert tombstone.artifact_dek_destroyed
    assert not tombstone.recoverable_body_retained
    assert tombstone.original_content_hash == decision.persisted_content_hash


def test_legal_hold_requires_two_people_expires_within_90_days_and_blocks_deletion() -> None:
    decision = govern_raw_artifact(_inspection())
    assert decision.expires_at is not None
    approver = uuid4()
    with pytest.raises(SyntheticLabContractError, match="two distinct"):
        ArtifactLegalHold(
            id=uuid4(),
            project_id=decision.project_id,
            artifact_id=decision.artifact_id,
            approved_by=(approver, approver),
            reason="incident review",
            approved_at=NOW,
            expires_at=NOW + timedelta(days=30),
        )
    with pytest.raises(SyntheticLabContractError, match="within 90 days"):
        ArtifactLegalHold(
            id=uuid4(),
            project_id=decision.project_id,
            artifact_id=decision.artifact_id,
            approved_by=(uuid4(), uuid4()),
            reason="incident review",
            approved_at=NOW,
            expires_at=NOW + timedelta(days=91),
        )

    hold = ArtifactLegalHold(
        id=uuid4(),
        project_id=decision.project_id,
        artifact_id=decision.artifact_id,
        approved_by=(uuid4(), uuid4()),
        reason="incident review",
        approved_at=NOW + timedelta(days=60),
        expires_at=NOW + timedelta(days=100),
    )
    with pytest.raises(SyntheticLabContractError, match="active legal hold"):
        create_artifact_tombstone(
            decision,
            deleted_at=decision.expires_at,
            legal_hold=hold,
        )
    tombstone = create_artifact_tombstone(
        decision,
        deleted_at=hold.expires_at,
        legal_hold=hold,
    )
    assert len(hold.hold_hash) == 64
    assert len(tombstone.tombstone_hash) == 64


def test_legal_hold_cannot_be_applied_across_projects_or_artifacts() -> None:
    decision = govern_raw_artifact(_inspection())
    assert decision.expires_at is not None
    hold = ArtifactLegalHold(
        id=uuid4(),
        project_id=uuid4(),
        artifact_id=decision.artifact_id,
        approved_by=(uuid4(), uuid4()),
        reason="wrong project",
        approved_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )
    with pytest.raises(SyntheticLabScopeError, match="does not cover"):
        create_artifact_tombstone(
            decision,
            deleted_at=decision.expires_at,
            legal_hold=hold,
        )

    future_hold = ArtifactLegalHold(
        id=uuid4(),
        project_id=decision.project_id,
        artifact_id=decision.artifact_id,
        approved_by=(uuid4(), uuid4()),
        reason="future approval",
        approved_at=decision.expires_at + timedelta(days=1),
        expires_at=decision.expires_at + timedelta(days=2),
    )
    with pytest.raises(SyntheticLabContractError, match="was not active"):
        create_artifact_tombstone(
            decision,
            deleted_at=decision.expires_at,
            legal_hold=future_hold,
        )


def test_all_governance_records_remain_internal_test_only_and_nonpublication() -> None:
    inspection = _inspection()
    decision = govern_raw_artifact(inspection)
    assert decision.expires_at is not None
    tombstone = create_artifact_tombstone(decision, deleted_at=decision.expires_at)
    resources = (inspection, decision, tombstone)

    assert all(item.synthetic and item.test_only for item in resources)
    assert not any(item.publication_eligible for item in resources)
