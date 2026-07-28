"""Reusable governed fixtures for Model Gateway PostgreSQL integration tests."""

from __future__ import annotations

from collections.abc import Callable
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import psycopg

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.model_gateway import (
    AdapterRelease,
    CapabilityVerification,
    DataUseDecision,
    ModelAudience,
    ModelCaptureMethod,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelRelease,
    ModelRoute,
    ProviderCapabilities,
    ProviderDataPolicy,
    ReleaseState,
    ReportedModelPolicy,
)
from geo_core.model_gateway.application_support import ExecuteModelCall
from geo_core.model_gateway.postgres_runtime_catalog import PostgresRuntimeCatalog
from geo_core.model_gateway.ports import ModelCallAttemptKind, PromptReleaseAdmission
from geo_core.model_gateway.prompt_admission import (
    ModelCallAdmissionMode,
    PromptAdmissionState,
)
from geo_core.model_gateway.runtime_catalog import (
    NewModelCallJobSelection,
    register_runtime_manifest,
    runtime_options_for_manifest,
)
from geo_core.model_gateway.runtime_manifest import parse_runtime_manifest
from geo_core.project_scope import set_project_scope
from geo_core.prompts.application import PromptProgramApplication
from geo_core.prompts.postgres import prompt_program_uow_factory
from geo_core.prompts.program import (
    ModelPolicySnapshot,
    ProgramKind,
    ProgramSchemaContract,
    ProgramTestEvidence,
    PromptProgramRelease,
)
from geo_core.secrets import SecretValue, SecretVersionHandle
from geo_core.secrets.postgres import build_secret_store_api


SECRET_MARKER = "MODEL_GATEWAY_MESSAGE_MUST_NEVER_PERSIST_7319"
RAW_REFERENCE = "minio://restricted/provider/raw-response-7319.json"


@dataclass(frozen=True)
class RegisteredRuntimeFixture:
    selection: NewModelCallJobSelection
    adapter: AdapterRelease
    model: ModelRelease
    route: ModelRoute


def frozen_prompt(
    app_url: str, ids: dict[str, UUID]
) -> tuple[PromptReleaseAdmission, dict[str, object]]:
    factory = prompt_program_uow_factory(lambda: psycopg.connect(app_url))
    owner = _principal(ids, "owner")
    reviewer = _principal(ids, "reviewer")
    schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "recommended": {"type": "boolean"},
        },
        "required": ["answer", "recommended"],
        "additionalProperties": False,
    }
    schemas = ProgramSchemaContract(
        variable_schema_version="vars-v1",
        variable_schema={"type": "object", "properties": {}, "additionalProperties": False},
        input_schema_version="input-v1",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema_version="answer-v1",
        output_schema=schema,
        application_output_schema_version="answer-application-v1",
        application_output_schema=schema,
    )
    created = _prompt_command(
        factory,
        ids["project"],
        lambda app: app.create_program(
            owner,
            project_id=ids["project"],
            program_kind=ProgramKind.METRIC_JUDGE,
            purpose="model_gateway.integration",
            system_template="Return one structured answer.",
            user_template="Evaluate the supplied question.",
            schemas=schemas,
            model_policy=ModelPolicySnapshot(
                version="model-gateway-integration-v1",
                policy={"allowed_providers": ["openai"], "fallback": False},
            ),
            test_set_id=uuid4(),
            test_set_version=1,
            test_set_hash="9" * 64,
            compiler_version="geo-prompt-compiler-v2",
            expected_version=0,
            idempotency_key="model-gateway-prompt-create",
        ),
    )
    tested = _prompt_command(
        factory,
        ids["project"],
        lambda app: app.record_test(
            owner,
            project_id=ids["project"],
            release_id=created.value.release.id,
            output_artifact_ref="s3://prompt-tests/model-gateway.json",
            output_hash="e" * 64,
            expected_version=1,
            idempotency_key="model-gateway-prompt-test",
        ),
    )
    _prompt_command(
        factory,
        ids["project"],
        lambda app: app.approve_release(
            reviewer,
            project_id=ids["project"],
            release_id=created.value.release.id,
            expected_version=2,
            idempotency_key="model-gateway-prompt-approve",
        ),
    )
    frozen = _prompt_command(
        factory,
        ids["project"],
        lambda app: app.freeze_release(
            reviewer,
            project_id=ids["project"],
            release_id=created.value.release.id,
            expected_version=3,
            idempotency_key="model-gateway-prompt-freeze",
        ),
    )
    bound = _prompt_command(
        factory,
        ids["project"],
        lambda app: app.bind_release(
            reviewer,
            project_id=ids["project"],
            release_id=created.value.release.id,
            purpose="model_gateway.integration",
            expected_version=0,
            idempotency_key="model-gateway-prompt-bind",
        ),
    )
    assert tested.value.state.status.value == "tested"
    return (
        PromptReleaseAdmission(
            project_id=ids["project"],
            admission_mode=ModelCallAdmissionMode.RUNTIME_FROZEN,
            binding_id=bound.value.binding.id,
            state_id=frozen.value.state.id,
            state_version=frozen.value.state.version,
            release_id=created.value.release.id,
            release_hash=created.value.release.release_hash,
            purpose="model_gateway.integration",
            output_schema_hash=_canonical_json_hash(schema),
            application_output_schema_hash=_canonical_json_hash(schema),
            test_set_hash=None,
            state_status=PromptAdmissionState.FROZEN,
        ),
        schema,
    )


def releases() -> tuple[AdapterRelease, ModelRelease, ModelRoute]:
    adapter_id = "openai-integration-adapter-v1"
    adapter = AdapterRelease(
        provider="openai",
        adapter_release_id=adapter_id,
        release_hash=hashlib.sha256(adapter_id.encode()).hexdigest(),
        interface_contract_version="geo-model-gateway-v1",
        expected_capture_method=ModelCaptureMethod.PROVIDER_API,
        capabilities=ProviderCapabilities(
            provider="openai",
            external_training_allowed=False,
            structured_output=True,
            data_retention_days=7,
            policy_reference="https://evidence.example/openai/policy/integration-v1",
            supports_seed=True,
            supports_tools=True,
            supports_search=True,
            supports_citations=True,
            supports_idempotency=True,
            supports_structured_output_with_tools=True,
            verification=CapabilityVerification.VERIFIED,
        ),
        data_policy=ProviderDataPolicy(
            storage=DataUseDecision.ALLOWED,
            cache=DataUseDecision.PROHIBITED,
            display=DataUseDecision.ALLOWED,
            redistribution=DataUseDecision.PROHIBITED,
            retention_days=7,
            terms_reference="https://evidence.example/openai/terms/integration-v1",
            terms_sha256="a" * 64,
        ),
        state=ReleaseState.APPROVED,
        capability_evidence_reference=(
            "https://evidence.example/openai/capabilities/integration-v1"
        ),
        capability_evidence_sha256="b" * 64,
    )
    model_id = "openai-integration-model-v1"
    model = ModelRelease(
        provider="openai",
        adapter_release_id=adapter_id,
        model_release_id=model_id,
        release_hash=hashlib.sha256(model_id.encode()).hexdigest(),
        configured_model="openai-integration-model",
        state=ReleaseState.APPROVED,
        reported_model_policy=ReportedModelPolicy.EXACT,
    )
    return (
        adapter,
        model,
        ModelRoute(
            provider="openai",
            adapter_release_id=adapter_id,
            adapter_release_hash=adapter.release_hash,
            model_release_id=model_id,
            model_release_hash=model.release_hash,
        ),
    )


def register_openai_runtime(
    *,
    app_url: str,
    ids: dict[str, UUID],
    provider_secret_handle: SecretVersionHandle,
    approved_at: datetime,
    allowed_purposes: tuple[str, ...] = ("model_gateway.integration",),
    allowed_search_modes: tuple[str | None, ...] = (None, "web"),
    required_purpose: str = "model_gateway.integration",
    search_mode: str | None = "web",
) -> RegisteredRuntimeFixture:
    adapter_id = "openai-integration-adapter-v1"
    model_id = "openai-integration-model-v1"
    policy_id = uuid4()
    manifest = parse_runtime_manifest(
        {
            "schema_version": 2,
            "manifest_id": str(uuid4()),
            "project_id": str(ids["project"]),
            "prepared_by": str(ids["owner"]),
            "prepared_at": (approved_at - timedelta(seconds=1)).isoformat(),
            "approved_by": str(ids["reviewer"]),
            "approved_at": approved_at.isoformat(),
            "approval_evidence_reference": (
                "minio://integration-evidence/model-gateway/approval-v2.json"
            ),
            "approval_evidence_sha256": "c" * 64,
            "provider_runtimes": [
                {
                    "provider": "openai",
                    "adapter_release_id": adapter_id,
                    "interface_contract_version": "geo-model-gateway-v1",
                    "expected_capture_method": "provider_api",
                    "capabilities": {
                        "external_training_allowed": False,
                        "structured_output": True,
                        "data_retention_days": 7,
                        "policy_reference": (
                            "https://evidence.example/openai/policy/integration-v1"
                        ),
                        "supports_seed": True,
                        "supports_tools": True,
                        "supports_search": True,
                        "supports_citations": True,
                        "supports_idempotency": True,
                        "supports_structured_output_with_tools": True,
                    },
                    "data_policy": {
                        "storage": "allowed",
                        "cache": "prohibited",
                        "display": "allowed",
                        "redistribution": "prohibited",
                        "retention_days": 7,
                        "terms_reference": (
                            "https://evidence.example/openai/terms/integration-v1"
                        ),
                        "terms_sha256": "a" * 64,
                    },
                    "capability_evidence_reference": (
                        "minio://integration-evidence/model-gateway/openai-capabilities-v1.json"
                    ),
                    "capability_evidence_sha256": "b" * 64,
                    "allowed_purposes": list(allowed_purposes),
                    "allowed_search_modes": list(allowed_search_modes),
                    "secret_reference_id": str(provider_secret_handle.reference_id),
                    "microsoft": None,
                }
            ],
            "model_releases": [
                {
                    "provider": "openai",
                    "adapter_release_id": adapter_id,
                    "model_release_id": model_id,
                    "configured_model": "openai-integration-model",
                    "reported_model_policy": "exact",
                    "allowed_reported_models": [],
                }
            ],
            "project_policy": {
                "policy_version_id": str(policy_id),
                "version": 1,
                "previous_version_id": None,
                "external_training_allowed": False,
                "structured_output_required": True,
                "allowed_providers": ["openai"],
                "allowed_adapter_release_ids": [adapter_id],
                "maximum_paid_calls": 4,
                "maximum_concurrent_calls": 1,
            },
        }
    )
    catalog = PostgresRuntimeCatalog(app_url)
    handles = register_runtime_manifest(catalog, manifest)
    if handles != (provider_secret_handle,):
        raise AssertionError("runtime manifest did not bind the exact Provider secret")
    option = runtime_options_for_manifest(manifest)[0]
    selection = catalog.resolve_approved_runtime(
        project_id=ids["project"],
        runtime_selection_id=option.option_id,
        required_purpose=required_purpose,
        search_mode=search_mode,
    )
    model = manifest.model_releases[0]
    return RegisteredRuntimeFixture(
        selection=selection,
        adapter=manifest.provider_runtimes[0].adapter_release,
        model=model,
        route=selection.route,
    )


def running_job(
    app_url: str,
    *,
    project_id: UUID,
    job_id: UUID,
    lease_token: UUID,
    now: datetime,
) -> None:
    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, project_id)
        connection.execute(
            """INSERT INTO durable_jobs(
                   id, project_id, kind, status, input_hash, idempotency_key,
                   lease_owner, lease_token, lease_expires_at, heartbeat_at,
                   fencing_generation
               ) VALUES (%s, %s, 'model.gateway.integration', 'running', %s, %s,
                         'integration-worker', %s, %s, %s, 1)""",
            (
                job_id,
                project_id,
                "d" * 64,
                f"model-gateway-job:{job_id}",
                lease_token,
                now + timedelta(hours=1),
                now,
            ),
        )


def model_result(adapter: AdapterRelease, model: ModelRelease) -> ModelGatewayResult:
    return ModelGatewayResult(
        output={"answer": "Recommended by the integration fixture.", "recommended": True},
        call_log_id=uuid4(),
        provider_request_id="provider-request-integration",
        configured_model=model.configured_model,
        provider_reported_model=model.configured_model,
        prompt_tokens=31,
        completion_tokens=9,
        cost_usd=Decimal("0.0042"),
        finish_reason="completed",
        response_hash="f" * 64,
        provider="openai",
        adapter_release_id=adapter.adapter_release_id,
        adapter_release_hash=adapter.release_hash,
        model_release_id=model.model_release_id,
        model_release_hash=model.release_hash,
        citations=({"url": "https://example.test/source", "ordinal": 1},),
        tool_events=({"type": "web_search_call", "query": "example australia"},),
        raw_artifact_reference=RAW_REFERENCE,
        raw_artifact_policy_hash=adapter.data_policy_hash,
        raw_artifact_storage_decision=adapter.data_policy.storage.value,
        raw_artifact_cache_decision=adapter.data_policy.cache.value,
        raw_artifact_display_decision=adapter.data_policy.display.value,
        raw_artifact_redistribution_decision=adapter.data_policy.redistribution.value,
        raw_artifact_retention_days=adapter.data_policy.retention_days,
        usage_purpose="model_gateway.integration",
        usage_audience=ModelAudience.INTERNAL_WORKER,
        capture_method=ModelCaptureMethod.PROVIDER_API,
        search_mode="web",
        usage_details={"input_tokens": 31, "output_tokens": 9, "total_tokens": 40},
    )


def model_command(
    *,
    project_id: UUID,
    job_id: UUID,
    lease_token: UUID,
    route: ModelRoute,
    runtime_manifest_id: UUID,
    runtime_manifest_hash: str,
    runtime_option_id: UUID,
    runtime_option_hash: str,
    prompt: PromptReleaseAdmission,
    schema: dict[str, object],
    model: ModelRelease,
    provider_secret_handle: SecretVersionHandle,
    idempotency_key: str,
) -> ExecuteModelCall:
    return ExecuteModelCall(
        project_id=project_id,
        job_id=job_id,
        expected_job_version=1,
        lease_token=lease_token,
        fencing_generation=1,
        route=route,
        runtime_manifest_id=runtime_manifest_id,
        runtime_manifest_hash=runtime_manifest_hash,
        runtime_option_id=runtime_option_id,
        runtime_option_hash=runtime_option_hash,
        prompt_binding_id=prompt.binding_id,
        prompt_release_id=prompt.release_id,
        prompt_release_hash=prompt.release_hash,
        request=ModelGatewayRequest(
            messages=(
                {"role": "system", "content": f"Never persist {SECRET_MARKER}."},
                {"role": "user", "content": "Is this recommended in Australia?"},
            ),
            configured_model=model.configured_model,
            prompt_bundle_hash="b" * 64,
            project_id=project_id,
            purpose=prompt.purpose,
            output_schema=schema,
            application_output_schema=schema,
            search_mode="web",
            capture_method=ModelCaptureMethod.PROVIDER_API,
            provider_secret_handle=provider_secret_handle,
        ),
        attempt_kind=ModelCallAttemptKind.INITIAL,
        attempt_idempotency_key=idempotency_key,
        admission_mode=prompt.admission_mode,
    )


def active_provider_secret(
    *,
    app_url: str,
    ids: dict[str, UUID],
    directory: Path,
):
    keyring = directory / "model-gateway-keyring.json"
    request_key = directory / "model-gateway-request-key"
    keyring.write_text(
        json.dumps(
            {
                "format": "geo-master-keyring-v1",
                "active_version": 1,
                "keys": {"1": base64.b64encode(b"K" * 32).decode("ascii")},
            }
        ),
        encoding="utf-8",
    )
    request_key.write_text(base64.b64encode(b"H" * 32).decode("ascii"), encoding="ascii")
    keyring.chmod(0o600)
    request_key.chmod(0o600)
    api = build_secret_store_api(
        database_url=app_url,
        master_keyring_path=keyring,
        request_hash_key_path=request_key,
    )
    assert api is not None
    reference_id = uuid4()
    api.create(
        _principal(ids, "owner"),
        project_id=ids["project"],
        reference_id=reference_id,
        purpose="model_provider.openai",
        value=SecretValue("model-gateway-provider-key-v1"),
        expected_version=0,
        idempotency_key="model-gateway-secret-create-v1",
    )
    api.verify(
        _principal(ids, "owner"),
        project_id=ids["project"],
        reference_id=reference_id,
        version=1,
        expected_version=1,
        idempotency_key="model-gateway-secret-verify-v1",
    )
    api.activate(
        _principal(ids, "reviewer"),
        project_id=ids["project"],
        reference_id=reference_id,
        version=1,
        expected_version=2,
        idempotency_key="model-gateway-secret-activate-v1",
    )
    return api, SecretVersionHandle(
        reference_id=reference_id,
        project_id=ids["project"],
        purpose="model_provider.openai",
        version=1,
    )


def _prompt_command(factory, project_id: UUID, operation: Callable):
    with factory(project_id) as unit_of_work:
        result = operation(
            PromptProgramApplication(
                unit_of_work.prompts,
                test_evidence_verifier=_FixtureEvidenceVerifier(),
            )
        )
        unit_of_work.commit()
        return result


class _FixtureEvidenceVerifier:
    def verify(
        self,
        *,
        release: PromptProgramRelease,
        evidence: ProgramTestEvidence,
    ) -> None:
        if (
            evidence.project_id != release.project_id
            or evidence.release_id != release.id
            or evidence.release_hash != release.release_hash
            or evidence.output_artifact_ref != "s3://prompt-tests/model-gateway.json"
            or evidence.output_hash != "e" * 64
        ):
            raise AssertionError("Prompt fixture evidence differs from its frozen Release")


def _principal(ids: dict[str, UUID], identity: str) -> AccessPrincipal:
    identity_id = ids[identity]
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=ids["tenant"],
        memberships=(MembershipRecord(ids["project"], ids["tenant"], "admin"),),
        auth_method="integration",
    )


def _canonical_json_hash(value: object) -> str:
    from geo_core.model_gateway.ports import canonical_json_hash

    return canonical_json_hash(value)


__all__ = [
    "RAW_REFERENCE",
    "SECRET_MARKER",
    "active_provider_secret",
    "frozen_prompt",
    "model_command",
    "model_result",
    "register_openai_runtime",
    "releases",
    "running_job",
]
