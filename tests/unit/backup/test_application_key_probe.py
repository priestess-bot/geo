from __future__ import annotations

from uuid import UUID

import pytest

from geo_core.model_gateway.artifact_restore import ProviderArtifactRestoreVerification
from geo_core.recommendations.artifact_keyring_postgres import (
    RecommendationArtifactRestoreVerification,
)
from geo_core.secrets.postgres import SecretStoreRestoreVerification
from geo_core.synthetic_lab.artifact_keyring_postgres import ArtifactRecoveryVerification
from geo_core.workflow_c_artifacts.postgres import (
    WorkflowCArtifactRestoreVerification,
)
from geo_worker.backup_restore_probe import (
    ApplicationKeyRecoveryError,
    PROBE_SCHEMA,
    SecretRuntimeRestoreVerification,
    build_probe_payload,
)


def test_probe_payload_records_all_key_versions_and_real_artifact_results() -> None:
    payload = build_probe_payload(
        secret_store=SecretStoreRestoreVerification(
            verified_key_versions=(1, 2),
            representative_secret_count=2,
        ),
        secret_runtime=_secret_runtime(),
        provider_artifacts=_provider(),
        synthetic_artifacts=_synthetic(),
        recommendation_artifacts=_recommendation(),
        workflow_c_artifacts=_workflow_c(),
    )

    assert payload["schema_version"] == PROBE_SCHEMA
    assert payload["secret_store"] == {
        "frozen_handle_audit_count": 1,
        "frozen_handle_receipt_count": 1,
        "frozen_handle_runtime_verified": True,
        "representative_secret_count": 2,
        "verified_key_versions": [1, 2],
    }
    assert payload["provider_artifacts"]["verified_master_key_versions"] == [1]
    assert payload["provider_artifacts"]["representative_artifact_verified"] is True
    assert payload["recommendation_artifacts"]["verified_master_key_versions"] == [1]
    assert payload["recommendation_artifacts"]["representative_artifact_verified"] is True
    assert payload["workflow_c_artifacts"]["verified_master_key_versions"] == [1]
    assert payload["workflow_c_artifacts"]["representative_artifact_verified"] is True
    assert payload["synthetic_artifacts"]["verified_master_key_versions"] == ["1"]
    assert payload["synthetic_artifacts"]["restricted_representative_verified"] is True
    assert payload["synthetic_artifacts"]["tier_representative_verified"] is True


def test_probe_payload_rejects_missing_canary_and_inconsistent_empty_flags() -> None:
    with pytest.raises(ApplicationKeyRecoveryError, match="canary coverage"):
        build_probe_payload(
            secret_store=SecretStoreRestoreVerification(
                verified_key_versions=(1,), representative_secret_count=1
            ),
            secret_runtime=_secret_runtime(),
            provider_artifacts=_provider(),
            synthetic_artifacts=_synthetic(versions=()),
            recommendation_artifacts=_recommendation(),
            workflow_c_artifacts=_workflow_c(),
        )

    inconsistent = ProviderArtifactRestoreVerification(
        verified_master_key_versions=(1,),
        active_dek_count=1,
        recoverable_artifact_count=1,
        representative_artifact_verified=True,
        representative_artifact_id=UUID("e1000000-0000-0000-0000-000000000001"),
        representative_manifest_hash="a" * 64,
        verification_receipt_hash="b" * 64,
        empty_artifact_domain=True,
    )
    with pytest.raises(ApplicationKeyRecoveryError, match="Provider artifact"):
        build_probe_payload(
            secret_store=SecretStoreRestoreVerification(
                verified_key_versions=(1,), representative_secret_count=1
            ),
            secret_runtime=_secret_runtime(),
            provider_artifacts=inconsistent,
            synthetic_artifacts=_synthetic(),
            recommendation_artifacts=_recommendation(),
            workflow_c_artifacts=_workflow_c(),
        )


def _provider() -> ProviderArtifactRestoreVerification:
    return ProviderArtifactRestoreVerification(
        verified_master_key_versions=(1,),
        active_dek_count=1,
        recoverable_artifact_count=1,
        representative_artifact_verified=True,
        representative_artifact_id=UUID("e1000000-0000-0000-0000-000000000001"),
        representative_manifest_hash="a" * 64,
        verification_receipt_hash="b" * 64,
        empty_artifact_domain=False,
    )


def _recommendation(
    *, versions: tuple[int, ...] = (1,)
) -> RecommendationArtifactRestoreVerification:
    return RecommendationArtifactRestoreVerification(
        verified_master_key_versions=versions,
        artifact_lineage_count=1,
        representative_artifact_verified=True,
        representative_child_job_id=UUID("e2000000-0000-0000-0000-000000000001"),
        representative_manifest_hash="c" * 64,
        verification_receipt_hash="d" * 64,
        empty_artifact_domain=False,
    )


def _workflow_c(
    *, versions: tuple[int, ...] = (1,)
) -> WorkflowCArtifactRestoreVerification:
    return WorkflowCArtifactRestoreVerification(
        verified_master_key_versions=versions,
        active_dek_count=1,
        recoverable_artifact_count=1,
        representative_artifact_verified=True,
        representative_artifact_id=UUID("e3000000-0000-0000-0000-000000000001"),
        representative_manifest_hash="e" * 64,
        verification_receipt_hash="f" * 64,
        empty_artifact_domain=False,
    )


def _synthetic(
    *, versions: tuple[str, ...] = ("1",)
) -> ArtifactRecoveryVerification:
    return ArtifactRecoveryVerification(
        non_retired_master_key_count=1,
        verified_master_key_canary_count=len(versions),
        verified_master_key_versions=versions,
        active_dek_count=1,
        nondeleted_artifact_count=2,
        tier_key_artifact_count=1,
        restricted_representative_verified=True,
        tier_representative_verified=True,
        empty_artifact_domain=False,
    )


def _secret_runtime() -> SecretRuntimeRestoreVerification:
    return SecretRuntimeRestoreVerification(audit_count=1, receipt_count=1)
