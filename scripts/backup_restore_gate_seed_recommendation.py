"""Recoverable Recommendation task fixture for the authenticated restore Gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.postgres_runtime_catalog import PostgresRuntimeCatalog
from geo_core.object_store import S3CompatibleObjectStore
from geo_core.project_scope import set_project_scope
from geo_core.recommendations.artifact_keyring_postgres import (
    synchronize_recommendation_artifact_key_canaries,
    verify_recommendation_artifact_restore,
)
from geo_core.recommendations.generation_artifacts import (
    EncryptedRecommendationTaskArtifactStore,
)
from geo_core.recommendations.generation_contracts import (
    FrozenPromptBinding,
    ResolvedGenerationPrompt,
)
from geo_core.recommendations.generation_worker_contracts import (
    RECOMMENDATION_PARENT_JOB_KIND,
    RecommendationModelRole,
    RecommendationModelTask,
)
from geo_core.recommendations.postgres.generation_worker_repository import (
    PostgresRecommendationGenerationWorkerRepository,
)
from geo_core.secrets import EnvelopeCipher, load_master_keyring_from_docker_secret
from scripts.backup_restore_gate_seed_common import (
    IDS,
    RestoreGateSeedError,
    stable_hash,
)


def seed_recommendation_artifacts(
    *,
    database_url: str,
    object_store: S3CompatibleObjectStore,
    keyring_path: Path,
    prompt_binding: FrozenPromptBinding,
    output_schema: dict[str, object],
) -> dict[str, object]:
    """Persist one production-format encrypted task and its durable lineage."""

    cipher = EnvelopeCipher(load_master_keyring_from_docker_secret(keyring_path))
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        versions = synchronize_recommendation_artifact_key_canaries(connection, cipher=cipher)
        option = connection.execute(
            """SELECT id FROM model_gateway_runtime_options
               WHERE project_id = %s AND manifest_id = %s""",
            (IDS.project, IDS.runtime_manifest),
        ).fetchone()
        connection.commit()
    if versions != (1, 2) or option is None:
        raise RestoreGateSeedError(
            "Recommendation artifact seed key or Runtime coverage is incomplete"
        )

    runtime = PostgresRuntimeCatalog(database_url).resolve_approved_runtime(
        project_id=IDS.project,
        runtime_selection_id=option["id"],
        required_purpose="recommendations.recommendation",
        search_mode="web",
    )
    now = datetime.now(UTC).replace(microsecond=0)
    expires_at = now + timedelta(days=30)
    parent_input_hash = stable_hash("restore-gate-recommendation-parent-input")
    prompt = ResolvedGenerationPrompt(
        binding=prompt_binding,
        route=runtime.route,
        configured_model=runtime.configured_model,
        capture_method=runtime.adapter_release.expected_capture_method,
        search_mode="web",
        prompt_bundle_hash=stable_hash("restore-gate-recommendation-prompt-bundle"),
        messages=(
            {
                "role": "system",
                "content": "Return the fixed restore Gate recommendation.",
            },
            {
                "role": "user",
                "content": "Evaluate only the fixed restore Gate evidence.",
            },
        ),
        output_schema=output_schema,
        application_output_schema=output_schema,
        policy=runtime.policy,
        structured_input_hash=stable_hash("restore-gate-recommendation-structured-input"),
    )
    task = RecommendationModelTask(
        child_job_id=IDS.recommendation_child_job,
        parent_job_id=IDS.recommendation_parent_job,
        project_id=IDS.project,
        parent_input_hash=parent_input_hash,
        role=RecommendationModelRole.PRIMARY,
        runtime_selection_id=runtime.runtime_option_id,
        runtime_manifest_id=runtime.runtime_manifest_id,
        runtime_manifest_hash=runtime.runtime_manifest_hash,
        runtime_option_id=runtime.runtime_option_id,
        runtime_option_hash=runtime.runtime_option_hash,
        prompt=prompt,
        admitted_by=IDS.reviewer,
        artifact_expires_at=expires_at,
    )
    _insert_parent_job(database_url=database_url, now=now, input_hash=parent_input_hash)
    lease = WorkerLease(
        job_id=IDS.recommendation_parent_job,
        project_id=IDS.project,
        kind=RECOMMENDATION_PARENT_JOB_KIND,
        worker_id="restore-gate-recommendation-worker",
        lease_token=IDS.recommendation_parent_lease,
        fencing_generation=1,
        attempt_count=1,
        max_attempts=3,
    )
    artifacts = EncryptedRecommendationTaskArtifactStore(
        object_store=object_store,
        cipher=cipher,
        clock=lambda: now,
    )
    repository = PostgresRecommendationGenerationWorkerRepository(
        lambda: psycopg.connect(database_url, row_factory=dict_row),
        prompts=cast(Any, _UnavailableRestoreDependency()),
        artifacts=artifacts,
        model_results=cast(Any, _UnavailableRestoreDependency()),
    )
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        set_project_scope(connection, IDS.project)
        repository.reserve_model_task(connection=connection, lease=lease, task=task)
        connection.commit()
    artifact = repository.prepare_model_task(task)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        set_project_scope(connection, IDS.project)
        repository.activate_model_task(
            connection=connection,
            lease=lease,
            task=task,
            artifact=artifact,
        )
        connection.commit()
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        verification = verify_recommendation_artifact_restore(
            connection=connection,
            cipher=cipher,
            artifacts=artifacts,
        )
    if (
        verification.artifact_lineage_count != 1
        or not verification.representative_artifact_verified
    ):
        raise RestoreGateSeedError("Recommendation restore artifact did not verify before backup")
    return {
        "active_master_key_version": cipher.active_master_key_version,
        "artifact_lineage_count": verification.artifact_lineage_count,
        "master_key_version_count": len(versions),
        "representative_artifact_verified": (verification.representative_artifact_verified),
    }


def _insert_parent_job(*, database_url: str, now: datetime, input_hash: str) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """INSERT INTO durable_jobs(
                   id, project_id, kind, status, input_hash, idempotency_key,
                   lease_owner, lease_token, lease_expires_at, heartbeat_at,
                   fencing_generation, attempt_count, max_attempts
               ) VALUES (
                   %s, %s, 'recommendation.generate', 'running', %s, %s,
                   'restore-gate-recommendation-worker', %s, %s, %s, 1, 1, 3
               )""",
            (
                IDS.recommendation_parent_job,
                IDS.project,
                input_hash,
                "restore-gate-recommendation-parent",
                IDS.recommendation_parent_lease,
                now + timedelta(hours=2),
                now,
            ),
        )


class _UnavailableRestoreDependency:
    def __getattr__(self, name: str) -> Any:
        raise RestoreGateSeedError(
            f"Recommendation restore seed touched unavailable dependency: {name}"
        )


__all__ = ["seed_recommendation_artifacts"]
