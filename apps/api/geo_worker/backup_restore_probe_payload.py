"""Validated, non-secret receipt payload for the restored application domains."""

from __future__ import annotations

from geo_core.model_gateway.artifact_restore import ProviderArtifactRestoreVerification
from geo_core.recommendations.artifact_keyring_postgres import (
    RecommendationArtifactRestoreVerification,
)
from geo_core.secrets.postgres import SecretStoreRestoreVerification
from geo_core.synthetic_lab.artifact_keyring_postgres import ArtifactRecoveryVerification
from geo_core.workflow_c_artifacts.postgres import WorkflowCArtifactRestoreVerification


PROBE_SCHEMA = "geo-application-key-recovery-probe-v3"


class ApplicationKeyRecoveryError(RuntimeError):
    """The isolated application-key recovery probe cannot establish authenticity."""


class SecretRuntimeRestoreVerification:
    """Proof that a pre-backup service resolve receipt replayed after restore."""

    def __init__(self, *, audit_count: int, receipt_count: int) -> None:
        self.audit_count = audit_count
        self.receipt_count = receipt_count


def build_probe_payload(
    *,
    secret_store: SecretStoreRestoreVerification,
    secret_runtime: SecretRuntimeRestoreVerification,
    provider_artifacts: ProviderArtifactRestoreVerification,
    synthetic_artifacts: ArtifactRecoveryVerification,
    recommendation_artifacts: RecommendationArtifactRestoreVerification,
    workflow_c_artifacts: WorkflowCArtifactRestoreVerification,
) -> dict[str, object]:
    provider_versions = list(provider_artifacts.verified_master_key_versions)
    synthetic_versions = list(synthetic_artifacts.verified_master_key_versions)
    recommendation_versions = list(recommendation_artifacts.verified_master_key_versions)
    workflow_c_versions = list(workflow_c_artifacts.verified_master_key_versions)
    if (
        not secret_store.verified_key_versions
        or not provider_versions
        or not synthetic_versions
        or not recommendation_versions
        or not workflow_c_versions
        or synthetic_artifacts.verified_master_key_canary_count
        != synthetic_artifacts.non_retired_master_key_count
        or synthetic_artifacts.verified_master_key_canary_count
        != len(synthetic_versions)
    ):
        raise ApplicationKeyRecoveryError("application key canary coverage is incomplete")
    if provider_artifacts.empty_artifact_domain == (
        provider_artifacts.active_dek_count > 0
        or provider_artifacts.recoverable_artifact_count > 0
    ):
        raise ApplicationKeyRecoveryError("Provider artifact recovery result is inconsistent")
    if synthetic_artifacts.empty_artifact_domain == (
        synthetic_artifacts.nondeleted_artifact_count > 0
    ):
        raise ApplicationKeyRecoveryError("Synthetic artifact recovery result is inconsistent")
    if recommendation_artifacts.empty_artifact_domain == (
        recommendation_artifacts.artifact_lineage_count > 0
    ):
        raise ApplicationKeyRecoveryError(
            "Recommendation artifact recovery result is inconsistent"
        )
    if workflow_c_artifacts.empty_artifact_domain == (
        workflow_c_artifacts.active_dek_count > 0
        or workflow_c_artifacts.recoverable_artifact_count > 0
    ):
        raise ApplicationKeyRecoveryError("Workflow C artifact recovery result is inconsistent")
    return {
        "provider_artifacts": {
            "active_dek_count": provider_artifacts.active_dek_count,
            "empty_artifact_domain": provider_artifacts.empty_artifact_domain,
            "recoverable_artifact_count": provider_artifacts.recoverable_artifact_count,
            "representative_artifact_verified": provider_artifacts.representative_artifact_verified,
            "verification_receipt_hash": provider_artifacts.verification_receipt_hash,
            "verified_master_key_versions": provider_versions,
        },
        "recommendation_artifacts": {
            "artifact_lineage_count": recommendation_artifacts.artifact_lineage_count,
            "empty_artifact_domain": recommendation_artifacts.empty_artifact_domain,
            "representative_artifact_verified": recommendation_artifacts.representative_artifact_verified,
            "verification_receipt_hash": recommendation_artifacts.verification_receipt_hash,
            "verified_master_key_versions": recommendation_versions,
        },
        "schema_version": PROBE_SCHEMA,
        "secret_store": {
            "frozen_handle_audit_count": secret_runtime.audit_count,
            "frozen_handle_receipt_count": secret_runtime.receipt_count,
            "frozen_handle_runtime_verified": True,
            "representative_secret_count": secret_store.representative_secret_count,
            "verified_key_versions": list(secret_store.verified_key_versions),
        },
        "synthetic_artifacts": {
            "active_dek_count": synthetic_artifacts.active_dek_count,
            "empty_artifact_domain": synthetic_artifacts.empty_artifact_domain,
            "nondeleted_artifact_count": synthetic_artifacts.nondeleted_artifact_count,
            "restricted_representative_verified": synthetic_artifacts.restricted_representative_verified,
            "tier_key_artifact_count": synthetic_artifacts.tier_key_artifact_count,
            "tier_representative_verified": synthetic_artifacts.tier_representative_verified,
            "verified_master_key_versions": synthetic_versions,
        },
        "workflow_c_artifacts": {
            "active_dek_count": workflow_c_artifacts.active_dek_count,
            "empty_artifact_domain": workflow_c_artifacts.empty_artifact_domain,
            "recoverable_artifact_count": workflow_c_artifacts.recoverable_artifact_count,
            "representative_artifact_verified": workflow_c_artifacts.representative_artifact_verified,
            "verification_receipt_hash": workflow_c_artifacts.verification_receipt_hash,
            "verified_master_key_versions": workflow_c_versions,
        },
    }


__all__ = [
    "ApplicationKeyRecoveryError",
    "PROBE_SCHEMA",
    "SecretRuntimeRestoreVerification",
    "build_probe_payload",
]
