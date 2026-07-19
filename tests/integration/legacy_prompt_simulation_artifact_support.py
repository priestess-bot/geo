from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from geo_core.placements.domain import canonical_hash


def seed_legacy_artifact_replay(
    connection: psycopg.Connection[Any],
    *,
    fixture: dict[str, Any],
    simulation_id: UUID,
    generation_job_id: UUID,
    snapshot: dict[str, object],
) -> dict[str, object]:
    manifest_hash, storage_key = _insert_result(
        connection,
        fixture=fixture,
        simulation_id=simulation_id,
        generation_job_id=generation_job_id,
        snapshot=snapshot,
        label="replay",
    )
    source_job_id, replay_job_id = uuid4(), uuid4()
    input_hash = _artifact_input_hash(simulation_id, manifest_hash)
    job_key = "legacy-simulation-artifact-replayable"
    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, kind, status, input_hash, idempotency_key,
              error_code, completed_at)
           VALUES (%s, %s, 'artifact.finalize', 'failed', %s, %s,
                   'legacy_artifact_failed', clock_timestamp())""",
        (source_job_id, fixture["project"], input_hash, job_key),
    )
    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, kind, status, input_hash, idempotency_key,
              parent_job_id, replay_nonce, attempt_count, lease_owner,
              lease_token, lease_expires_at, fencing_generation)
           VALUES (%s, %s, 'artifact.finalize', 'running', %s, %s, %s, 1, 1,
                   'retired-artifact-worker', %s,
                   clock_timestamp() - interval '1 hour', 1)""",
        (
            replay_job_id,
            fixture["project"],
            input_hash,
            job_key,
            source_job_id,
            uuid4(),
        ),
    )
    _insert_outbox(
        connection,
        fixture=fixture,
        job_id=replay_job_id,
        simulation_id=simulation_id,
        storage_key=storage_key,
        manifest_hash=manifest_hash,
    )
    replay_key = "existing-legacy-simulation-artifact-replay"
    connection.execute(
        """INSERT INTO job_replay_requests
             (project_id, source_job_id, replay_job_id, idempotency_key, requested_by)
           VALUES (%s, %s, %s, %s, %s)""",
        (
            fixture["project"],
            source_job_id,
            replay_job_id,
            replay_key,
            fixture["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO broker_outbox
             (project_id, job_id, topic, payload, idempotency_key)
           VALUES (%s, %s, 'artifact.finalize', %s, %s)""",
        (
            fixture["project"],
            replay_job_id,
            Jsonb({"job_id": str(replay_job_id), "project_id": str(fixture["project"])}),
            f"replay:{replay_job_id}",
        ),
    )
    connection.execute(
        """INSERT INTO durable_job_events
             (project_id, job_id, event_type, worker_id, details)
           VALUES (%s, %s, 'job_replayed', %s, %s)""",
        (
            fixture["project"],
            replay_job_id,
            f"api:{fixture['owner']}",
            Jsonb({"parent_job_id": str(source_job_id)}),
        ),
    )
    return {
        "source_job_id": source_job_id,
        "replay_job_id": replay_job_id,
        "idempotency_key": replay_key,
    }


def seed_parentless_legacy_artifact(
    connection: psycopg.Connection[Any],
    *,
    fixture: dict[str, Any],
    simulation_id: UUID,
    generation_job_id: UUID,
    snapshot: dict[str, object],
) -> UUID:
    manifest_hash, storage_key = _insert_result(
        connection,
        fixture=fixture,
        simulation_id=simulation_id,
        generation_job_id=generation_job_id,
        snapshot=snapshot,
        label="parentless",
    )
    job_id = uuid4()
    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, kind, input_hash, idempotency_key)
           VALUES (%s, %s, 'artifact.finalize', %s, %s)""",
        (
            job_id,
            fixture["project"],
            _artifact_input_hash(simulation_id, manifest_hash),
            "legacy-simulation-artifact-parentless",
        ),
    )
    _insert_outbox(
        connection,
        fixture=fixture,
        job_id=job_id,
        simulation_id=simulation_id,
        storage_key=storage_key,
        manifest_hash=manifest_hash,
    )
    return job_id


def _insert_result(
    connection: psycopg.Connection[Any],
    *,
    fixture: dict[str, Any],
    simulation_id: UUID,
    generation_job_id: UUID,
    snapshot: dict[str, object],
    label: str,
) -> tuple[str, str]:
    manifest = {
        "schema": "geo-prompt-simulation-result-v2",
        "simulation_id": str(simulation_id),
        "project_id": str(fixture["project"]),
        "test_only": True,
        "publication_eligible": False,
        "authenticity_mode": "brand_authored",
        "input_hash": canonical_hash(snapshot),
        "output_hash": canonical_hash(f"legacy-{label}-output"),
        "model_call": {"provider_request_id": f"legacy-artifact-{label}"},
        "output": {"rendered_text": f"Legacy {label} artifact preview"},
    }
    manifest_hash = canonical_hash(manifest)
    storage_key = (
        f"content-simulations/{fixture['project']}/{simulation_id}/"
        f"simulation-{manifest_hash}.json"
    )
    connection.execute(
        """INSERT INTO prompt_simulation_results
             (simulation_id, project_id, generated_by_job_id, artifact_manifest,
              output_hash, manifest_hash, model_response_hash, storage_key)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            simulation_id,
            fixture["project"],
            generation_job_id,
            Jsonb(manifest),
            manifest["output_hash"],
            manifest_hash,
            canonical_hash(f"legacy-{label}-response"),
            storage_key,
        ),
    )
    return manifest_hash, storage_key


def _insert_outbox(
    connection: psycopg.Connection[Any],
    *,
    fixture: dict[str, Any],
    job_id: UUID,
    simulation_id: UUID,
    storage_key: str,
    manifest_hash: str,
) -> None:
    connection.execute(
        """INSERT INTO artifact_finalize_outbox
             (project_id, job_id, resource_kind, resource_id, pending_uri,
              storage_key, content_hash)
           VALUES (%s, %s, 'prompt_simulation', %s, %s, %s, %s)""",
        (
            fixture["project"],
            job_id,
            simulation_id,
            f"postgres://prompt_simulation_results/{simulation_id}/artifact_manifest",
            storage_key,
            manifest_hash,
        ),
    )


def _artifact_input_hash(simulation_id: UUID, manifest_hash: str) -> str:
    return canonical_hash(
        {
            "resource_kind": "prompt_simulation",
            "resource_id": str(simulation_id),
            "manifest_hash": manifest_hash,
        }
    )
