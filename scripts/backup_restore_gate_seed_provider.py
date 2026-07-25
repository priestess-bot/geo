"""Committed Provider artifact fixture for authenticated restore verification."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

import psycopg

from geo_core.jobs.lifecycle import JobStatus
from geo_core.model_gateway.application import ModelCallApplication
from geo_core.model_gateway.application_support import ExecuteModelCall
from geo_core.model_gateway.contracts import (
    ModelAudience,
    ModelCallBudget,
    ModelCaptureMethod,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
)
from geo_core.model_gateway.ports import (
    ModelCallAttemptKind,
    ModelCallJobAdmission,
    PromptReleaseAdmission,
    canonical_json_hash,
)
from geo_core.model_gateway.postgres import build_model_gateway_persistence
from geo_core.model_gateway.postgres_artifact_composition import (
    build_provider_artifact_worker_composition,
)
from geo_core.model_gateway.postgres_runtime_catalog import PostgresRuntimeCatalog
from geo_core.model_gateway.prompt_admission import ModelCallAdmissionMode
from geo_core.model_gateway.provider_adapters.artifacts import (
    MinioProviderArtifactSink,
    canonical_provider_json_bytes,
)
from geo_core.model_gateway.runtime_catalog import (
    RuntimeManifestRegistrationCatalog,
    register_runtime_manifest,
    runtime_options_for_manifest,
)
from geo_core.model_gateway.runtime_manifest import (
    ModelGatewayRuntimeManifest,
    parse_runtime_manifest,
)
from geo_core.object_store import S3CompatibleObjectStore
from geo_core.secrets import SecretVersionHandle
from scripts.backup_restore_gate_seed_common import (
    IDS,
    RestoreGateSeedError,
    stable_hash,
)


def seed_provider_artifacts(
    *,
    database_url: str,
    object_store: S3CompatibleObjectStore,
    provider_keyring: Path,
    provider_secret: SecretVersionHandle,
    prompt: PromptReleaseAdmission,
    output_schema: dict[str, object],
) -> dict[str, int]:
    now = datetime.now(UTC)
    manifest = _runtime_manifest(provider_secret=provider_secret, approved_at=now)
    catalog = PostgresRuntimeCatalog(database_url)
    handles = register_runtime_manifest(cast(RuntimeManifestRegistrationCatalog, catalog), manifest)
    if handles != (provider_secret,):
        raise RestoreGateSeedError("runtime manifest did not bind the exact Provider secret")
    option = runtime_options_for_manifest(manifest)[0]
    selection = catalog.resolve_approved_runtime(
        project_id=IDS.project,
        runtime_selection_id=option.option_id,
        required_purpose="restore_gate.model_call",
        search_mode="web",
    )
    _insert_running_job(database_url, now=now)
    persistence = build_model_gateway_persistence(database_url)
    if persistence is None:
        raise RestoreGateSeedError("Model Gateway persistence is unavailable")
    policy = selection.policy
    if (
        policy.policy_version_id is None
        or policy.policy_version_hash is None
        or policy.maximum_paid_calls is None
        or policy.maximum_concurrent_calls is None
    ):
        raise RestoreGateSeedError("Model Gateway policy is not frozen")
    adapter = selection.adapter_release
    job = ModelCallJobAdmission(
        project_id=IDS.project,
        job_id=IDS.provider_job,
        job_kind="restore_gate.model_call",
        job_version=1,
        admission_mode=ModelCallAdmissionMode.RUNTIME_FROZEN,
        status=JobStatus.RUNNING,
        lease_token=IDS.provider_lease,
        fencing_generation=1,
        purpose="restore_gate.model_call",
        usage_audience=ModelAudience.INTERNAL_WORKER,
        route=selection.route,
        provider_secret_handle=selection.provider_secret_handle,
        runtime_manifest_id=selection.runtime_manifest_id,
        runtime_manifest_hash=selection.runtime_manifest_hash,
        runtime_option_id=selection.runtime_option_id,
        runtime_option_hash=selection.runtime_option_hash,
        prompt_binding_id=prompt.binding_id,
        prompt_release_id=prompt.release_id,
        prompt_release_hash=prompt.release_hash,
        prompt_state_id=prompt.state_id,
        prompt_state_version=prompt.state_version,
        prompt_test_set_hash=None,
        prompt_bundle_hash=stable_hash("restore-gate-prompt-bundle"),
        output_schema_hash=canonical_json_hash(output_schema),
        # The restore fixture deliberately has no provider-only relaxation, but
        # the application schema must still be frozen independently.  Production
        # jobs always persist both hashes, even when their canonical JSON happens
        # to be identical.
        application_output_schema_hash=canonical_json_hash(output_schema),
        policy_version_id=policy.policy_version_id,
        policy_version_hash=policy.policy_version_hash,
        maximum_paid_calls=policy.maximum_paid_calls,
        maximum_concurrent_calls=policy.maximum_concurrent_calls,
        raw_artifact_policy_hash=adapter.data_policy_hash,
        raw_artifact_storage_decision=adapter.data_policy.storage.value,
        raw_artifact_cache_decision=adapter.data_policy.cache.value,
        raw_artifact_display_decision=adapter.data_policy.display.value,
        raw_artifact_redistribution_decision=adapter.data_policy.redistribution.value,
        raw_artifact_retention_days=adapter.data_policy.retention_days,
    )
    persistence.admit_job(job, prompt=prompt, admitted_by=IDS.reviewer, admitted_at=now)
    composition = build_provider_artifact_worker_composition(
        database_url=database_url,
        object_store=object_store,
        worker_id="restore-gate-provider-artifact-worker",
        keyring_path=str(provider_keyring),
    )
    command = ExecuteModelCall(
        project_id=IDS.project,
        job_id=IDS.provider_job,
        expected_job_version=1,
        lease_token=IDS.provider_lease,
        fencing_generation=1,
        route=selection.route,
        runtime_manifest_id=selection.runtime_manifest_id,
        runtime_manifest_hash=selection.runtime_manifest_hash,
        runtime_option_id=selection.runtime_option_id,
        runtime_option_hash=selection.runtime_option_hash,
        prompt_binding_id=prompt.binding_id,
        prompt_release_id=prompt.release_id,
        prompt_release_hash=prompt.release_hash,
        request=ModelGatewayRequest(
            messages=({"content": "Return the fixed restore Gate output.", "role": "user"},),
            configured_model=selection.configured_model,
            prompt_bundle_hash=job.prompt_bundle_hash,
            project_id=IDS.project,
            purpose=job.purpose,
            output_schema=output_schema,
            application_output_schema=output_schema,
            search_mode="web",
            capture_method=ModelCaptureMethod.PROVIDER_API,
            provider_secret_handle=selection.provider_secret_handle,
        ),
        attempt_kind=ModelCallAttemptKind.INITIAL,
        attempt_idempotency_key="restore-gate-provider-call",
    )
    execution = ModelCallApplication(
        gateway=_RestoreGateGateway(manifest=manifest, sink=composition.sink),
        release_registry=persistence.load_release_registry(),
        uow_factory=persistence.uow_factory,
    ).execute(command, policy=policy)
    if execution.terminal_event.status.value != "succeeded":
        raise RestoreGateSeedError("Provider artifact model call did not commit")
    with psycopg.connect(database_url) as connection:
        counts = connection.execute(
            """SELECT
                   (SELECT count(*) FROM model_gateway_artifact_deks
                    WHERE status = 'active'),
                   (SELECT count(*) FROM model_gateway_artifacts AS artifact
                    JOIN model_gateway_artifact_bundles AS bundle
                      ON bundle.id = artifact.bundle_id
                     AND bundle.project_id = artifact.project_id
                    WHERE bundle.status = 'committed')"""
        ).fetchone()
    if counts != (2, 2):
        raise RestoreGateSeedError("Provider artifact seed did not commit two ciphertexts")
    return {"active_dek_count": counts[0], "committed_artifact_count": counts[1]}


def _runtime_manifest(
    *, provider_secret: SecretVersionHandle, approved_at: datetime
) -> ModelGatewayRuntimeManifest:
    return parse_runtime_manifest(
        {
            "approval_evidence_reference": (
                "minio://geo-restore-gate-evidence/model-gateway/approval-v2.json"
            ),
            "approval_evidence_sha256": stable_hash("restore-gate-approval-evidence-v2"),
            "approved_at": approved_at.isoformat(),
            "approved_by": str(IDS.reviewer),
            "manifest_id": str(IDS.runtime_manifest),
            "model_releases": [
                {
                    "adapter_release_id": "restore-gate-openai-adapter-v1",
                    "allowed_reported_models": [],
                    "configured_model": "restore-gate-openai-model",
                    "model_release_id": "restore-gate-openai-model-v1",
                    "provider": "openai",
                    "reported_model_policy": "exact",
                }
            ],
            "project_id": str(IDS.project),
            "prepared_at": (approved_at - timedelta(seconds=1)).isoformat(),
            "prepared_by": str(IDS.owner),
            "project_policy": {
                "allowed_adapter_release_ids": ["restore-gate-openai-adapter-v1"],
                "allowed_providers": ["openai"],
                "external_training_allowed": False,
                "maximum_concurrent_calls": 1,
                "maximum_paid_calls": 1,
                "policy_version_id": str(IDS.policy),
                "previous_version_id": None,
                "structured_output_required": True,
                "version": 1,
            },
            "provider_runtimes": [
                {
                    "adapter_release_id": "restore-gate-openai-adapter-v1",
                    "allowed_purposes": [
                        "recommendations.recommendation",
                        "restore_gate.model_call",
                    ],
                    "allowed_search_modes": ["web"],
                    "capabilities": {
                        "data_retention_days": 7,
                        "external_training_allowed": False,
                        "policy_reference": "restore-gate:provider-capabilities-v1",
                        "structured_output": True,
                        "supports_citations": True,
                        "supports_idempotency": True,
                        "supports_search": True,
                        "supports_seed": True,
                        "supports_structured_output_with_tools": True,
                        "supports_tools": True,
                    },
                    "capability_evidence_reference": (
                        "minio://geo-restore-gate-evidence/model-gateway/openai-capabilities-v1.json"
                    ),
                    "capability_evidence_sha256": stable_hash(
                        "restore-gate-provider-capability-evidence-v1"
                    ),
                    "data_policy": {
                        "cache": "prohibited",
                        "display": "allowed",
                        "redistribution": "prohibited",
                        "retention_days": 7,
                        "storage": "allowed",
                        "terms_reference": (
                            "minio://geo-restore-gate-evidence/model-gateway/openai-terms-v1.json"
                        ),
                        "terms_sha256": stable_hash("restore-gate-provider-terms-evidence-v1"),
                    },
                    "expected_capture_method": "provider_api",
                    "interface_contract_version": "geo-model-gateway-v1",
                    "microsoft": None,
                    "provider": "openai",
                    "secret_reference_id": str(provider_secret.reference_id),
                }
            ],
            "schema_version": 2,
        }
    )


class _RestoreGateGateway:
    def __init__(
        self, *, manifest: ModelGatewayRuntimeManifest, sink: MinioProviderArtifactSink
    ) -> None:
        self._manifest = manifest
        self._sink = sink

    def generate(
        self,
        route: Any,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult:
        del policy
        budget.consume()
        if request.model_call_job_id is None or request.model_call_attempt_id is None:
            raise RestoreGateSeedError("Provider artifact attempt lineage is unavailable")
        adapter = self._manifest.provider_runtimes[0].adapter_release
        model = self._manifest.model_releases[0]
        raw_payload: Mapping[str, object] = {
            "provider_request_id": "restore-gate-request-v1",
            "response": {"answer": "Restore Gate answer", "recommended": True},
        }
        output = {"answer": "Restore Gate answer", "recommended": True}
        raw_hash = hashlib.sha256(canonical_provider_json_bytes(raw_payload)).hexdigest()
        bundle = self._sink.capture(
            project_id=request.project_id,
            job_id=request.model_call_job_id,
            attempt_id=request.model_call_attempt_id,
            provider=adapter.provider,
            adapter_release_id=adapter.adapter_release_id,
            adapter_release_hash=adapter.release_hash,
            data_policy=adapter.data_policy,
            usage_purpose=request.purpose,
            usage_audience=request.usage_audience,
            raw_payload=raw_payload,
            raw_content_hash=raw_hash,
            derived_payload=output,
        )
        return ModelGatewayResult(
            output=output,
            call_log_id=uuid5(NAMESPACE_URL, "geo-restore-gate:provider-call-log"),
            provider_request_id="restore-gate-request-v1",
            configured_model=model.configured_model,
            provider_reported_model=model.configured_model,
            prompt_tokens=12,
            completion_tokens=8,
            cost_usd=Decimal("0.0001"),
            finish_reason="completed",
            response_hash=raw_hash,
            provider=route.provider,
            adapter_release_id=route.adapter_release_id,
            adapter_release_hash=route.adapter_release_hash,
            model_release_id=route.model_release_id,
            model_release_hash=route.model_release_hash,
            raw_artifact_reference=bundle.raw.manifest_reference,
            raw_artifact_manifest_hash=bundle.raw.manifest_hash,
            raw_artifact_content_hash=bundle.raw.content_hash,
            raw_artifact_byte_size=bundle.raw.byte_size,
            derived_artifact_reference=bundle.derived.manifest_reference,
            derived_artifact_manifest_hash=bundle.derived.manifest_hash,
            derived_artifact_content_hash=bundle.derived.content_hash,
            derived_artifact_byte_size=bundle.derived.byte_size,
            capture_method=ModelCaptureMethod.PROVIDER_API,
            search_mode="web",
            usage_details={"input_tokens": 12, "output_tokens": 8},
        )


def _insert_running_job(database_url: str, *, now: datetime) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """INSERT INTO durable_jobs(
                   id, project_id, kind, status, input_hash, idempotency_key,
                   lease_owner, lease_token, lease_expires_at, heartbeat_at,
                   fencing_generation
               ) VALUES (%s, %s, 'restore_gate.model_call', 'running', %s, %s,
                         'restore-gate-worker', %s, %s, %s, 1)""",
            (
                IDS.provider_job,
                IDS.project,
                stable_hash("restore-gate-provider-job"),
                "restore-gate-provider-job",
                IDS.provider_lease,
                now + timedelta(hours=2),
                now,
            ),
        )


__all__ = ["seed_provider_artifacts"]
