"""Recoverable Workflow C manual artifact fixture for authenticated restore gates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyDecisionRequest,
    AdmissionPolicySubmitRequest,
    CreateAdmissionPolicyRequest,
    StartSamplingRunRequest,
)
from geo_api.workflow_c_sampling_postgres_policy import (
    PostgresWorkflowCSamplingPolicyControl,
)
from geo_api.workflow_c_sampling_postgres_run import PostgresWorkflowCSamplingRunControl
from geo_core.object_store import S3CompatibleObjectStore
from geo_core.sampling import (
    CaptureMethod,
    LocationControl,
    PersistentSamplingSuiteInput,
    PostgresSamplingRunRepository,
    PostgresSamplingSuiteRepository,
    SamplingQuestion,
    SamplingSourceStratum,
    SamplingSuite,
)
from geo_core.sampling.manual_artifact_governance import AUTOMATIC_POLICY_KEY
from geo_core.sampling.manual_artifact_storage import (
    IndependentWorkflowCArtifactEncryptor,
    MinioWorkflowCManualArtifactWriter,
)
from geo_core.sampling.postgres_admission import PostgresSamplingAdmissionRepository
from geo_core.sampling.postgres_suites import SAMPLING_SUITE_INPUT_NAMESPACE
from geo_core.secrets import EnvelopeCipher, load_master_keyring_from_docker_secret
from geo_core.workflow_c_artifacts.postgres import (
    PostgresWorkflowCArtifactKeyVault,
    PostgresWorkflowCManualArtifactRepository,
    synchronize_workflow_c_artifact_master_keys,
    verify_workflow_c_artifact_restore,
)
from scripts.backup_restore_gate_seed_common import (
    IDS,
    RestoreGateSeedError,
    stable_hash,
)


def seed_workflow_c_artifacts(
    *,
    database_url: str,
    object_store: S3CompatibleObjectStore,
    keyring_path: Path,
) -> dict[str, object]:
    """Persist and decrypt one governed production-format Workflow C artifact."""

    cipher = EnvelopeCipher(load_master_keyring_from_docker_secret(keyring_path))
    now = datetime.now(UTC).replace(microsecond=0)
    run_id, task_id = _seed_sampling_lineage(database_url=database_url, now=now)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        versions = synchronize_workflow_c_artifact_master_keys(connection, cipher)
        connection.commit()

    def connect():
        return psycopg.connect(database_url, row_factory=dict_row)

    writer = MinioWorkflowCManualArtifactWriter(
        object_store=object_store,
        encryptor=IndependentWorkflowCArtifactEncryptor(
            PostgresWorkflowCArtifactKeyVault(
                connect=connect,
                cipher=cipher,
                clock=lambda: now,
                synchronize=False,
            )
        ),
        repository=PostgresWorkflowCManualArtifactRepository(connect=connect),
        retention_days=30,
        clock=lambda: now,
    )
    receipt = writer.write(
        project_id=IDS.project,
        run_id=run_id,
        task_id=task_id,
        artifact_manifest_id=IDS.workflow_c_artifact,
        capture_session_id=IDS.workflow_c_capture_session,
        evidence_kind="transcript_export",
        content_type="application/json",
        content=bytearray(b'{"answer":"Restore Gate AU result","token":"redact-before-store"}'),
        governance_policy_key=AUTOMATIC_POLICY_KEY,
        pre_redacted_attestation=False,
    )
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        verification = verify_workflow_c_artifact_restore(
            connection=connection,
            cipher=cipher,
            object_store=object_store,
        )
    if (
        versions != (1, 2)
        or verification.active_dek_count != 1
        or verification.recoverable_artifact_count != 1
        or not verification.representative_artifact_verified
        or verification.representative_artifact_id != receipt.artifact_manifest_id
    ):
        raise RestoreGateSeedError("Workflow C restore artifact did not verify before backup")
    return {
        "active_dek_count": verification.active_dek_count,
        "master_key_version_count": len(versions),
        "recoverable_artifact_count": verification.recoverable_artifact_count,
        "representative_artifact_verified": (verification.representative_artifact_verified),
    }


def _seed_sampling_lineage(*, database_url: str, now: datetime) -> tuple[UUID, UUID]:
    option_key = "restore-gate-manual-au-v1"
    option_hash = stable_hash("restore-gate-workflow-c-runtime-option")
    location_hash = stable_hash("restore-gate-workflow-c-location:not-controlled")
    adapter_release = "restore-gate-manual-ui-au-v1"
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """INSERT INTO workflow_c_sampling_runtime_options(
                   project_id, option_key, option_hash, display_name, platform,
                   capture_method, adapter_release, location_control,
                   location_evidence_hash, authorization_reference, allowed_purposes,
                   status, frozen_at
               ) VALUES (
                   %s, %s, %s, 'Restore Gate manual AU', 'consumer_ai',
                   'manual_ui', %s, 'not_controlled', %s,
                   'authorization:restore-gate-manual-au', %s, 'approved', %s
               )""",
            (
                IDS.project,
                option_key,
                option_hash,
                adapter_release,
                location_hash,
                Jsonb(["geo_measurement"]),
                now,
            ),
        )

    def connect():
        return psycopg.connect(database_url, row_factory=dict_row)

    policies = PostgresWorkflowCSamplingPolicyControl(
        repository=PostgresSamplingAdmissionRepository(connect=connect, clock=lambda: now),
        clock=lambda: now,
    )
    created = policies.create(
        project_id=IDS.project,
        actor_id="restore-gate-maker",
        idempotency_key="restore-gate-workflow-c-policy",
        payload=CreateAdmissionPolicyRequest(
            runtime_authorization_option_key=option_key,
            purpose="geo_measurement",
            valid_until=now + timedelta(days=7),
            quota_remaining=3,
            daily_task_limit=3,
            minimum_request_interval_seconds=0,
            max_concurrency=1,
        ),
    ).record
    submitted = policies.submit(
        project_id=IDS.project,
        policy_id=created.id,
        actor_id="restore-gate-maker",
        idempotency_key="restore-gate-workflow-c-policy-submit",
        payload=AdmissionPolicySubmitRequest(expected_version=created.aggregate_version),
    ).record
    approved = policies.decide(
        project_id=IDS.project,
        policy_id=created.id,
        actor_id="restore-gate-checker",
        idempotency_key="restore-gate-workflow-c-policy-approve",
        payload=AdmissionPolicyDecisionRequest(
            expected_version=submitted.aggregate_version,
            reason="isolated authenticated restore verification",
        ),
        approved=True,
    ).record
    source = SamplingSourceStratum(
        platform="consumer_ai",
        surface="manual_consumer_ui",
        configured_model="not_disclosed",
        reported_model="not_disclosed",
        capture_method=CaptureMethod.MANUAL_UI,
        adapter_release=adapter_release,
        locale="en-AU",
        region="not_controlled",
        language="en",
        search_mode="consumer_ui",
        account_cohort="restore_gate_operator",
        egress_policy_category="operator_verified",
        location_control=LocationControl.NOT_CONTROLLED,
        location_evidence_hash=location_hash,
        requested_country="AU",
        requested_region=None,
        requested_locale="en-AU",
        requested_language="en",
        effective_country=None,
        effective_region=None,
        effective_locale=None,
        effective_language=None,
    )
    suite_input_key = "restore-gate-manual-artifact-v1"
    input_option = PersistentSamplingSuiteInput(
        id=uuid5(SAMPLING_SUITE_INPUT_NAMESPACE, f"{IDS.project}:{suite_input_key}"),
        project_id=IDS.project,
        option_key=suite_input_key,
        display_name="Restore Gate manual artifact",
        question_set_id=_id("workflow-c-question-set"),
        question_set_version="restore-gate-v1",
        question_set_hash=stable_hash("restore-gate-workflow-c-question-set"),
        questions=(
            SamplingQuestion(
                "restore-gate-au-query",
                "v1",
                stable_hash("restore-gate-workflow-c-question"),
            ),
        ),
        adapter_release_id=_id("workflow-c-adapter-release"),
        adapter_release_hash=stable_hash("restore-gate-workflow-c-adapter-release"),
        model_release_id=_id("workflow-c-model-release"),
        model_release_hash=stable_hash("restore-gate-workflow-c-model-release"),
        route_policy_id=_id("workflow-c-route-policy"),
        route_policy_hash=stable_hash("restore-gate-workflow-c-route-policy"),
        runtime_manifest_id=_id("workflow-c-runtime-manifest"),
        runtime_manifest_hash=stable_hash("restore-gate-workflow-c-runtime-manifest"),
        runtime_option_id=_id("workflow-c-runtime-option"),
        runtime_option_hash=option_hash,
        admission_policy_id=approved.id,
        admission_policy_hash=approved.definition_hash,
        source_stratum=source,
        frozen_at=now,
    )
    suites = PostgresSamplingSuiteRepository(connect=connect)
    suites.register_input(input_option, idempotency_key="restore-gate-workflow-c-suite-input")
    suite = SamplingSuite(
        id=IDS.workflow_c_suite,
        project_id=IDS.project,
        question_set_id=input_option.question_set_id,
        question_set_version=input_option.question_set_version,
        question_set_hash=input_option.question_set_hash,
        adapter_release_id=input_option.adapter_release_id,
        adapter_release_hash=input_option.adapter_release_hash,
        model_release_id=input_option.model_release_id,
        model_release_hash=input_option.model_release_hash,
        route_policy_id=input_option.route_policy_id,
        route_policy_hash=input_option.route_policy_hash,
        runtime_manifest_id=input_option.runtime_manifest_id,
        runtime_manifest_hash=input_option.runtime_manifest_hash,
        runtime_option_id=input_option.runtime_option_id,
        runtime_option_hash=input_option.runtime_option_hash,
        admission_policy_id=input_option.admission_policy_id,
        admission_policy_hash=input_option.admission_policy_hash,
        questions=input_option.questions,
        source_stratum=source,
        repetitions=3,
        statistics_method_version="restore-gate-statistics-v1",
        max_planned_tasks=3,
        max_daily_tasks=3,
        minimum_request_interval_seconds=0,
        max_concurrency=1,
        frozen_by="restore-gate-maker",
        frozen_at=now,
    )
    suites.create_suite(
        suite,
        input_option=input_option,
        idempotency_key="restore-gate-workflow-c-suite",
    )
    run, tasks = PostgresWorkflowCSamplingRunControl(
        runs=PostgresSamplingRunRepository(connect=connect),
        suites=suites,
        policies=policies,
        clock=lambda: now,
    ).start_run(
        project_id=IDS.project,
        suite_id=suite.id,
        idempotency_key="restore-gate-workflow-c-run",
        payload=StartSamplingRunRequest(purpose="geo_measurement", requested_not_before=now),
    )
    if len(tasks) != 3:
        raise RestoreGateSeedError("Workflow C restore denominator was not frozen")
    return run.id, tasks[0].id


def _id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"geo-restore-gate:{name}")


__all__ = ["seed_workflow_c_artifacts"]
