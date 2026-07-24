"""Secret Store and frozen Prompt fixtures for the authenticated restore Gate."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from geo_core.access.models import AccessPrincipal
from geo_core.model_gateway.ports import PromptReleaseAdmission, canonical_json_hash
from geo_core.model_gateway.prompt_admission import (
    ModelCallAdmissionMode,
    PromptAdmissionState,
)
from geo_core.prompts.application import PromptProgramApplication
from geo_core.prompts.postgres import prompt_program_uow_factory
from geo_core.prompts.program import (
    ModelPolicySnapshot,
    ProgramKind,
    ProgramSchemaContract,
    ProgramTestEvidence,
    PromptProgramRelease,
)
from geo_core.prompts.test_execution_contracts import PromptTestExecutionError
from geo_core.secrets import (
    ResolveSecretCommand,
    SecretActorRole,
    SecretPrincipal,
    SecretSurface,
    SecretValue,
    SecretVersionHandle,
)
from geo_core.secrets.postgres import (
    build_secret_store_api,
    build_secret_store_postgres_runtime,
)
from scripts.backup_restore_gate_seed_common import (
    IDS,
    KEYRING_FILES,
    RestoreGateSeedError,
    SECRET_MARKERS,
    stable_hash,
)


def seed_secrets(
    *,
    database_url: str,
    keyring_directory: Path,
    owner: AccessPrincipal,
    reviewer: AccessPrincipal,
) -> SecretVersionHandle:
    request_key = keyring_directory / KEYRING_FILES["request_hash"]
    first = build_secret_store_api(
        database_url=database_url,
        master_keyring_path=keyring_directory / KEYRING_FILES["secret_v1"],
        request_hash_key_path=request_key,
    )
    if first is None:
        raise RestoreGateSeedError("Secret Store v1 composition is unavailable")
    _activate_secret(
        first,
        owner=owner,
        reviewer=reviewer,
        reference_id=IDS.secret_v1,
        purpose="restore_gate.secret_v1",
        value=SECRET_MARKERS[0],
    )
    current = build_secret_store_api(
        database_url=database_url,
        master_keyring_path=keyring_directory / KEYRING_FILES["secret_full"],
        request_hash_key_path=request_key,
    )
    if current is None:
        raise RestoreGateSeedError("Secret Store current composition is unavailable")
    _activate_secret(
        current,
        owner=owner,
        reviewer=reviewer,
        reference_id=IDS.secret_v2,
        purpose="restore_gate.secret_v2",
        value=SECRET_MARKERS[1],
    )
    _activate_secret(
        current,
        owner=owner,
        reviewer=reviewer,
        reference_id=IDS.provider_secret,
        purpose="model_provider.openai",
        value=SECRET_MARKERS[2],
    )
    handle = SecretVersionHandle(
        reference_id=IDS.provider_secret,
        project_id=IDS.project,
        purpose="model_provider.openai",
        version=1,
    )
    runtime = build_secret_store_postgres_runtime(
        database_url=database_url,
        master_keyring_path=keyring_directory / KEYRING_FILES["secret_full"],
        request_hash_key_path=request_key,
    )
    if runtime is None:
        raise RestoreGateSeedError("Secret Store runtime canary composition is unavailable")
    value = runtime.application.resolve(
        ResolveSecretCommand(
            principal=SecretPrincipal(
                actor_id=IDS.restore_probe_service,
                project_id=IDS.project,
                role=SecretActorRole.SERVICE,
                surface=SecretSurface.WORKER,
            ),
            handle=handle,
            idempotency_key="restore-gate-frozen-handle-resolve-v1",
        )
    )
    try:
        if not value.matches(SECRET_MARKERS[2]):
            raise RestoreGateSeedError("Secret Store runtime canary did not decrypt")
    finally:
        del value
    return handle


def _activate_secret(
    api: Any,
    *,
    owner: AccessPrincipal,
    reviewer: AccessPrincipal,
    reference_id: UUID,
    purpose: str,
    value: str,
) -> None:
    key = purpose.replace(".", "-")
    api.create(
        owner,
        project_id=IDS.project,
        reference_id=reference_id,
        purpose=purpose,
        value=SecretValue(value),
        expected_version=0,
        idempotency_key=f"restore-gate-{key}-create",
    )
    api.verify(
        owner,
        project_id=IDS.project,
        reference_id=reference_id,
        version=1,
        expected_version=1,
        idempotency_key=f"restore-gate-{key}-verify",
    )
    api.activate(
        reviewer,
        project_id=IDS.project,
        reference_id=reference_id,
        version=1,
        expected_version=2,
        idempotency_key=f"restore-gate-{key}-activate",
    )


def seed_prompt(
    *,
    database_url: str,
    owner: AccessPrincipal,
    reviewer: AccessPrincipal,
) -> tuple[PromptReleaseAdmission, dict[str, object]]:
    output_schema: dict[str, object] = {
        "additionalProperties": False,
        "properties": {
            "answer": {"type": "string"},
            "recommended": {"type": "boolean"},
        },
        "required": ["answer", "recommended"],
        "type": "object",
    }
    schemas = ProgramSchemaContract(
        variable_schema_version="vars-v1",
        variable_schema={"additionalProperties": False, "properties": {}, "type": "object"},
        input_schema_version="input-v1",
        input_schema={"additionalProperties": False, "properties": {}, "type": "object"},
        output_schema_version="restore-gate-output-v1",
        output_schema=output_schema,
    )
    factory = prompt_program_uow_factory(lambda: psycopg.connect(database_url))
    verifier = _RestoreGatePromptEvidenceVerifier()
    created = _prompt_command(
        factory,
        verifier,
        lambda app: app.create_program(
            owner,
            project_id=IDS.project,
            program_kind=ProgramKind.METRIC_JUDGE,
            purpose="restore_gate.model_call",
            system_template="Return one structured restore Gate answer.",
            user_template="Evaluate the fixed restore Gate input.",
            schemas=schemas,
            model_policy=ModelPolicySnapshot(
                version="restore-gate-model-policy-v1",
                policy={"allowed_providers": ["openai"], "fallback": False},
            ),
            test_set_id=IDS.prompt_test_set,
            test_set_version=1,
            test_set_hash=stable_hash("restore-gate-prompt-test-set"),
            compiler_version="geo-prompt-compiler-v2",
            expected_version=0,
            idempotency_key="restore-gate-prompt-create",
        ),
    )
    tested = _prompt_command(
        factory,
        verifier,
        lambda app: app.record_test(
            owner,
            project_id=IDS.project,
            release_id=created.value.release.id,
            output_artifact_ref="s3://restore-gate-evidence/prompt-test.json",
            output_hash=stable_hash("restore-gate-prompt-test-output"),
            expected_version=1,
            idempotency_key="restore-gate-prompt-test",
        ),
    )
    _prompt_command(
        factory,
        verifier,
        lambda app: app.approve_release(
            reviewer,
            project_id=IDS.project,
            release_id=created.value.release.id,
            expected_version=2,
            idempotency_key="restore-gate-prompt-approve",
        ),
    )
    frozen = _prompt_command(
        factory,
        verifier,
        lambda app: app.freeze_release(
            reviewer,
            project_id=IDS.project,
            release_id=created.value.release.id,
            expected_version=3,
            idempotency_key="restore-gate-prompt-freeze",
        ),
    )
    bound = _prompt_command(
        factory,
        verifier,
        lambda app: app.bind_release(
            reviewer,
            project_id=IDS.project,
            release_id=created.value.release.id,
            purpose="restore_gate.model_call",
            expected_version=0,
            idempotency_key="restore-gate-prompt-bind",
        ),
    )
    if tested.value.state.status.value != "tested":
        raise RestoreGateSeedError("Prompt Program test evidence is incomplete")
    return (
        PromptReleaseAdmission(
            project_id=IDS.project,
            admission_mode=ModelCallAdmissionMode.RUNTIME_FROZEN,
            binding_id=bound.value.binding.id,
            state_id=frozen.value.state.id,
            state_version=frozen.value.state.version,
            release_id=created.value.release.id,
            release_hash=created.value.release.release_hash,
            purpose="restore_gate.model_call",
            output_schema_hash=canonical_json_hash(output_schema),
            application_output_schema_hash=canonical_json_hash(
                schemas.application_output_schema
            ),
            test_set_hash=None,
            state_status=PromptAdmissionState.FROZEN,
        ),
        output_schema,
    )


class _RestoreGatePromptEvidenceVerifier:
    """Verify the only fixed test evidence admitted by the restore Gate seed.

    The Gate intentionally uses a private, deterministic Prompt rather than a
    production bootstrap catalog.  It still exercises approval through the
    same verifier boundary, but this verifier accepts no caller-controlled URI
    or hash and has no production composition path.
    """

    def verify(
        self, *, release: PromptProgramRelease, evidence: ProgramTestEvidence
    ) -> None:
        if (
            release.project_id != IDS.project
            or release.program_kind is not ProgramKind.METRIC_JUDGE
            or release.purpose != "restore_gate.model_call"
            or evidence.project_id != IDS.project
            or evidence.release_id != release.id
            or evidence.release_hash != release.release_hash
            or evidence.test_set_id != IDS.prompt_test_set
            or evidence.test_set_version != 1
            or evidence.output_artifact_ref != "s3://restore-gate-evidence/prompt-test.json"
            or evidence.output_hash != stable_hash("restore-gate-prompt-test-output")
        ):
            raise PromptTestExecutionError("restore Gate Prompt evidence changed")


def _prompt_command(
    factory: Any,
    verifier: _RestoreGatePromptEvidenceVerifier,
    operation: Callable[[PromptProgramApplication], Any],
) -> Any:
    with factory(IDS.project) as unit_of_work:
        result = operation(
            PromptProgramApplication(
                unit_of_work.prompts,
                test_evidence_verifier=verifier,
            )
        )
        unit_of_work.commit()
        return result


__all__ = ["seed_prompt", "seed_secrets"]
