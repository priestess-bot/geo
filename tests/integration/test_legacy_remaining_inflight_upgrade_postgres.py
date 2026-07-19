from __future__ import annotations

from datetime import timedelta
import hashlib
import os
from typing import Any
from uuid import UUID, uuid4

from alembic import command
import psycopg
from psycopg.types.json import Jsonb
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.placements.artifact_worker import PlacementArtifactRepository
from geo_core.placements.domain import canonical_hash, canonical_json_bytes
from geo_core.placements.worker_composition import (
    ArtifactFinalizeHandler,
    EvidencePackHandler,
    MeasurementWindowHandler,
    PlacementWorkerDispatcher,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository
from tests.integration.legacy_inflight_upgrade_support import (
    insert_legacy_job,
    job_events,
)
from tests.integration.placement_worker_support import MemoryArtifactStore
from tests.integration.test_batch2_migrations_postgres import (
    _seed_legacy_fixture,
    _temporary_database,
)
from tests.integration.test_legacy_prompt_bundle_upgrade_postgres import (
    _seed_legacy_prompt_bundle,
)


ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_URL,
        reason="GEO_ACCESS_TEST_ADMIN_DATABASE_URL is required",
    ),
]


class _CountingArtifactStore(MemoryArtifactStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next = False
        self.puts: list[str] = []

    def put_object(
        self, *, key: str, content: bytes, content_type: str, expected_hash: str
    ) -> object:
        self.puts.append(key)
        return super().put_object(
            key=key,
            content=content,
            content_type=content_type,
            expected_hash=expected_hash,
        )


def test_legacy_remaining_placement_jobs_resume_once_after_head_upgrade() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0010_campaign_destinations")
        with psycopg.connect(database_url) as connection:
            fixture = _seed_legacy_fixture(connection)
            bundle = _seed_legacy_prompt_bundle(connection, fixture)
            evidence = _seed_evidence_pack_jobs(connection, fixture, bundle)
            artifacts = _seed_artifact_jobs(connection, fixture, bundle)
            measurements = _seed_measurement_jobs(connection, fixture, bundle)

        command.upgrade(configuration, "head")
        store = PostgresDurableJobStore(lambda: psycopg.connect(database_url))
        repository = PlacementWorkerRepository(store)
        object_store = _CountingArtifactStore()
        dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "evidence_pack.build": EvidencePackHandler(repository),
                "artifact.finalize": ArtifactFinalizeHandler(
                    store=store,
                    repository=PlacementArtifactRepository(store),
                    object_store=object_store,
                ),
                "placement.measure": MeasurementWindowHandler(repository),
            },
            worker_id="legacy-remaining-placement-reconciler",
            lease_for=timedelta(seconds=30),
        )

        for job_id in artifacts["jobs"].values():
            assert (
                dispatcher.process(job_id=job_id, project_id=fixture["project"])["status"]
                == "finalized"
            )
        for job_id in evidence["jobs"].values():
            assert (
                dispatcher.process(job_id=job_id, project_id=fixture["project"])["status"]
                == "ready"
            )
        for job_id in measurements["jobs"].values():
            assert (
                dispatcher.process(job_id=job_id, project_id=fixture["project"])["status"]
                == "awaiting_manual_samples"
            )

        all_jobs = {
            **{f"evidence-{key}": value for key, value in evidence["jobs"].items()},
            **{f"artifact-{key}": value for key, value in artifacts["jobs"].items()},
            **{f"measurement-{key}": value for key, value in measurements["jobs"].items()},
        }
        puts_after_first_run = list(object_store.puts)
        objects_after_first_run = dict(object_store.objects)
        for job_id in all_jobs.values():
            assert (
                dispatcher.process(job_id=job_id, project_id=fixture["project"])["status"]
                == "terminal"
            )
        assert object_store.puts == puts_after_first_run
        assert object_store.objects == objects_after_first_run

        with psycopg.connect(database_url) as connection:
            _assert_job_outcomes(connection, all_jobs)
            _assert_evidence_outcomes(connection, evidence)
            _assert_artifact_outcomes(connection, artifacts, object_store)
            _assert_measurement_outcomes(connection, measurements, fixture)
            assert connection.execute(
                """SELECT count(*) FROM model_call_logs
                   WHERE job_id = ANY(%s)""",
                (list(all_jobs.values()),),
            ).fetchone() == (0,)


def _seed_evidence_pack_jobs(
    connection: psycopg.Connection[Any],
    fixture: dict[str, Any],
    bundle: dict[str, UUID],
) -> dict[str, Any]:
    evidence_id = uuid4()
    source_id = uuid4()
    statement = "A documented consumer used Legacy Product in a normal household."
    statement_hash = hashlib.sha256(statement.encode()).hexdigest()
    connection.execute(
        """INSERT INTO evidence_items
             (id, project_id, item_type, source_id, subject_entity_id, subject_role,
              snapshot_text, snapshot_hash, source_revision_kind,
              source_revision_value, usage_rights, confidentiality)
           VALUES (%s, %s, 'consumer_experience', %s, %s, 'product', %s, %s,
                   'content_hash', %s, 'authorised_experience', 'internal')""",
        (
            evidence_id,
            fixture["project"],
            source_id,
            fixture["product"],
            statement,
            statement_hash,
            statement_hash,
        ),
    )
    jobs = {"queued": uuid4(), "expired_running": uuid4()}
    attempts: dict[str, UUID] = {}
    for attempt_number, (label, job_id) in enumerate(jobs.items(), start=2):
        attempt_id = uuid4()
        attempts[label] = attempt_id
        connection.execute(
            """INSERT INTO evidence_pack_attempts
                 (id, project_id, brief_version_id, attempt_number, status)
               VALUES (%s, %s, %s, %s, 'building')""",
            (
                attempt_id,
                fixture["project"],
                bundle["brief_version_id"],
                attempt_number,
            ),
        )
        insert_legacy_job(
            connection,
            job_id=job_id,
            project_id=fixture["project"],
            kind="evidence_pack.build",
            label=f"legacy-evidence-{label}",
            running=label == "expired_running",
        )
        connection.execute(
            """INSERT INTO evidence_pack_job_specs
                 (job_id, project_id, brief_version_id, evidence_pack_attempt_id)
               VALUES (%s, %s, %s, %s)""",
            (
                job_id,
                fixture["project"],
                bundle["brief_version_id"],
                attempt_id,
            ),
        )
    connection.commit()
    return {"jobs": jobs, "attempts": attempts, "evidence_id": evidence_id}


def _seed_artifact_jobs(
    connection: psycopg.Connection[Any],
    fixture: dict[str, Any],
    bundle: dict[str, UUID],
) -> dict[str, Any]:
    jobs = {"queued": uuid4(), "expired_running": uuid4()}
    bundles: dict[str, UUID] = {}
    storage_keys: dict[str, str] = {}
    for label, job_id in jobs.items():
        bundle_id = uuid4()
        payload = {"legacy_artifact": label, "schema_version": "legacy-v1"}
        content_hash = canonical_hash(payload)
        storage_key = f"content-prompts/{bundle_id}.json"
        bundles[label] = bundle_id
        storage_keys[label] = storage_key
        connection.execute(
            """INSERT INTO prompt_bundles
                 (id, project_id, brief_version_id, evidence_pack_attempt_id,
                  template_release_id, input_snapshot, storage_key, bundle_hash)
               SELECT %s, project_id, brief_version_id, evidence_pack_attempt_id,
                      template_release_id, %s, %s, %s
               FROM prompt_bundles WHERE id = %s AND project_id = %s""",
            (
                bundle_id,
                Jsonb(payload),
                storage_key,
                content_hash,
                bundle["bundle_id"],
                fixture["project"],
            ),
        )
        insert_legacy_job(
            connection,
            job_id=job_id,
            project_id=fixture["project"],
            kind="artifact.finalize",
            label=f"legacy-artifact-{label}",
            running=label == "expired_running",
        )
        connection.execute(
            """INSERT INTO artifact_finalize_outbox
                 (project_id, job_id, resource_kind, resource_id, pending_uri,
                  storage_key, content_hash, status, attempt_count)
               VALUES (%s, %s, 'prompt_bundle', %s, %s, %s, %s, %s, %s)""",
            (
                fixture["project"],
                job_id,
                bundle_id,
                f"postgres://prompt_bundles/{bundle_id}/input_snapshot",
                storage_key,
                content_hash,
                "finalizing" if label == "expired_running" else "pending",
                1 if label == "expired_running" else 0,
            ),
        )
    connection.commit()
    return {"jobs": jobs, "bundles": bundles, "storage_keys": storage_keys}


def _seed_measurement_jobs(
    connection: psycopg.Connection[Any],
    fixture: dict[str, Any],
    bundle: dict[str, UUID],
) -> dict[str, Any]:
    package_id, version_id, request_id, submission_id = (uuid4() for _ in range(4))
    content = {"legacy": "measurement-source"}
    connection.execute(
        "UPDATE publication_destinations SET policy_status = 'approved' WHERE id = %s",
        (fixture["destination"],),
    )
    connection.execute(
        """INSERT INTO placement_packages(id, project_id, opportunity_id)
           VALUES (%s, %s, %s)""",
        (package_id, fixture["project"], fixture["opportunity"]),
    )
    connection.execute(
        """INSERT INTO placement_package_versions
             (id, project_id, package_id, prompt_bundle_id, version_number,
              workflow_status, content_json, rendered_text, content_hash,
              edited_by, edit_reason)
           VALUES (%s, %s, %s, %s, 1, 'approved', %s,
                   'Legacy approved content for measurement.', %s, %s,
                   'legacy approved content')""",
        (
            version_id,
            fixture["project"],
            package_id,
            bundle["bundle_id"],
            Jsonb(content),
            canonical_hash(content),
            fixture["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO publication_requests
             (id, project_id, package_version_id, destination_id,
              publication_attempt, idempotency_key, status, requested_by)
           VALUES (%s, %s, %s, %s, 1, %s, 'publishing', %s)""",
        (
            request_id,
            fixture["project"],
            version_id,
            fixture["destination"],
            f"legacy-measurement-request-{request_id}",
            fixture["owner"],
        ),
    )
    submitted_url = "https://example.test/legacy-measurement"
    provider_submission_id = f"provider-{submission_id}"
    submission_hash = canonical_hash(
        {
            "publication_request_id": str(request_id),
            "provider_submission_id": provider_submission_id,
            "submitted_url": submitted_url,
        }
    )
    connection.execute(
        """INSERT INTO publication_submissions
             (id, project_id, publication_request_id, submitted_url,
              provider_submission_id, status, submitted_at, verified_at,
              idempotency_key, payload_hash, submitted_by, verification_result)
           VALUES (%s, %s, %s, %s, %s, 'verified', clock_timestamp(),
                   clock_timestamp(), %s, %s, %s, '{"legacy":true}'::jsonb)""",
        (
            submission_id,
            fixture["project"],
            request_id,
            submitted_url,
            provider_submission_id,
            f"legacy-measurement-submission-{submission_id}",
            submission_hash,
            fixture["owner"],
        ),
    )
    protocol_hash = connection.execute(
        "SELECT protocol_hash FROM monitoring_protocols WHERE id = %s",
        (fixture["protocol"],),
    ).fetchone()[0]
    jobs = {"queued": uuid4(), "expired_running": uuid4()}
    windows = {"queued": (28, "t28"), "expired_running": (56, "t56")}
    for label, job_id in jobs.items():
        due_offset, window = windows[label]
        insert_legacy_job(
            connection,
            job_id=job_id,
            project_id=fixture["project"],
            kind="placement.measure",
            label=f"legacy-measurement-{label}",
            running=label == "expired_running",
        )
        connection.execute(
            """INSERT INTO measurement_job_specs
                 (job_id, project_id, submission_id, due_offset_days, scheduled_for,
                  market_profile_id, locale, device, sample_size, protocol_snapshot,
                  protocol_hash, protocol_id, measurement_window,
                  expected_sample_count)
               VALUES (%s, %s, %s, %s, clock_timestamp() - interval '1 day',
                       %s, 'en-AU', 'desktop', 1, %s, %s, %s, %s, 1)""",
            (
                job_id,
                fixture["project"],
                submission_id,
                due_offset,
                fixture["market"],
                Jsonb({"schema_version": "legacy-measurement-v1", "window": window}),
                protocol_hash,
                fixture["protocol"],
                window,
            ),
        )
        connection.execute(
            """INSERT INTO measurement_job_queries
                 (job_id, project_id, monitoring_query_id)
               VALUES (%s, %s, %s)""",
            (job_id, fixture["project"], fixture["query"]),
        )
    connection.commit()
    return {"jobs": jobs, "submission_id": submission_id, "windows": windows}


def _assert_job_outcomes(connection: psycopg.Connection[Any], all_jobs: dict[str, UUID]) -> None:
    rows = connection.execute(
        """SELECT id, status, attempt_count FROM durable_jobs
           WHERE id = ANY(%s)""",
        (list(all_jobs.values()),),
    ).fetchall()
    assert len(rows) == len(all_jobs)
    expected_attempts = {
        job_id: 2 if label.endswith("expired_running") else 1 for label, job_id in all_jobs.items()
    }
    for job_id, status, attempt_count in rows:
        assert status == "succeeded"
        assert attempt_count == expected_attempts[job_id]
    for label, job_id in all_jobs.items():
        assert job_events(connection, job_id=job_id) == (
            ["lease_reclaimed", "job_succeeded"]
            if label.endswith("expired_running")
            else ["lease_claimed", "job_succeeded"]
        )


def _assert_evidence_outcomes(
    connection: psycopg.Connection[Any], evidence: dict[str, Any]
) -> None:
    rows = connection.execute(
        """SELECT id, status FROM evidence_pack_attempts
           WHERE id = ANY(%s) ORDER BY attempt_number""",
        (list(evidence["attempts"].values()),),
    ).fetchall()
    assert rows == [
        (evidence["attempts"]["queued"], "superseded"),
        (evidence["attempts"]["expired_running"], "ready"),
    ]
    assert connection.execute(
        """SELECT pack_attempt_id, evidence_item_id, count(*)
           FROM evidence_pack_items WHERE pack_attempt_id = ANY(%s)
           GROUP BY pack_attempt_id, evidence_item_id ORDER BY pack_attempt_id""",
        (list(evidence["attempts"].values()),),
    ).fetchall() == sorted(
        [(attempt_id, evidence["evidence_id"], 1) for attempt_id in evidence["attempts"].values()]
    )


def _assert_artifact_outcomes(
    connection: psycopg.Connection[Any],
    artifacts: dict[str, Any],
    object_store: _CountingArtifactStore,
) -> None:
    rows = connection.execute(
        """SELECT job_id, status, attempt_count, storage_key, final_uri
           FROM artifact_finalize_outbox WHERE job_id = ANY(%s) ORDER BY job_id""",
        (list(artifacts["jobs"].values()),),
    ).fetchall()
    assert len(rows) == 2
    for job_id, status, attempt_count, storage_key, final_uri in rows:
        label = next(key for key, value in artifacts["jobs"].items() if value == job_id)
        assert status == "finalized"
        assert attempt_count == (2 if label == "expired_running" else 1)
        assert final_uri == f"s3://geo-artifacts/{storage_key}"
    assert sorted(object_store.puts) == sorted(artifacts["storage_keys"].values())
    assert set(object_store.objects) == set(artifacts["storage_keys"].values())
    for label, bundle_id in artifacts["bundles"].items():
        payload = connection.execute(
            "SELECT input_snapshot FROM prompt_bundles WHERE id = %s", (bundle_id,)
        ).fetchone()[0]
        assert object_store.objects[artifacts["storage_keys"][label]] == canonical_json_bytes(
            payload
        )


def _assert_measurement_outcomes(
    connection: psycopg.Connection[Any],
    measurements: dict[str, Any],
    fixture: dict[str, Any],
) -> None:
    rows = connection.execute(
        """SELECT job_id, campaign_id, opportunity_id, destination_id,
                  submission_id, protocol_id, measurement_window,
                  expected_sample_count, status
           FROM measurement_collection_tasks
           WHERE job_id = ANY(%s) ORDER BY measurement_window""",
        (list(measurements["jobs"].values()),),
    ).fetchall()
    assert rows == [
        (
            measurements["jobs"]["queued"],
            fixture["campaign"],
            fixture["opportunity"],
            fixture["destination"],
            measurements["submission_id"],
            fixture["protocol"],
            "t28",
            1,
            "open",
        ),
        (
            measurements["jobs"]["expired_running"],
            fixture["campaign"],
            fixture["opportunity"],
            fixture["destination"],
            measurements["submission_id"],
            fixture["protocol"],
            "t56",
            1,
            "open",
        ),
    ]
