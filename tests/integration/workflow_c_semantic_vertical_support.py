"""Reusable phases and infrastructure assertions for the Workflow C vertical test."""

from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import datetime, timedelta
import json
from typing import Any
from uuid import UUID

import dramatiq
from dramatiq.brokers.redis import RedisBroker
import psycopg
from psycopg.rows import dict_row
import pytest

from geo_api.workflow_c_sampling_contracts import (
    ReviewManualEvidenceRequest,
    SubmitManualEvidenceRequest,
)
from geo_api.workflow_c_sampling_postgres_manual import (
    PostgresWorkflowCManualEvidenceControl,
)
from geo_core.jobs.outbox import PostgresOutboxStore
from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.project_scope import set_project_scope
from geo_core.sampling import (
    PostgresManualEvidenceRepository,
    PostgresSamplingRunRepository,
    PostgresSamplingSuiteRepository,
    SURFACE_PARSER_RELEASES,
)
from geo_core.sampling.manual_artifact_governance import AUTOMATIC_POLICY_KEY
from geo_core.sampling.manual_artifact_storage import (
    IndependentWorkflowCArtifactEncryptor,
    MinioWorkflowCManualArtifactWriter,
)
from geo_core.sampling.postgres_worker import PostgresManualSamplingOperation
from geo_core.sampling.postgres_worker_repository import (
    PostgresWorkflowCSamplingRepository,
)
from geo_core.secrets import EnvelopeCipher
from geo_core.workflow_c_artifacts.postgres import (
    PostgresWorkflowCArtifactKeyVault,
    PostgresWorkflowCManualArtifactRepository,
)
from geo_core.workflow_c_artifacts.reader import (
    PostgresWorkflowCManualArtifactReader,
)
from geo_core.workflow_c_job_specs import PostgresWorkflowCJobSpecRepository
from geo_core.workflow_c_statistical_protocols import (
    PostgresWorkflowCStatisticalProtocolRepository,
    StatisticalProtocolStatus,
    new_statistical_protocol,
)
from tests.integration.test_workflow_c_artifact_maintenance_postgres import (
    _create_manual_sampling_lineage,
)


def create_and_process_manual_observations(
    *,
    objects: Any,
    app_connect: Callable[[], Any],
    worker_connect: Callable[[], Any],
    project_id: UUID,
    question_id: UUID,
    now: datetime,
    cipher: EnvelopeCipher,
) -> tuple[
    UUID,
    PostgresSamplingRunRepository,
    Any,
    PostgresWorkflowCManualArtifactReader,
    PostgresDurableJobStore,
    PostgresWorkflowCJobSpecRepository,
]:
    """Create three governed manual observations and return downstream runtime state."""

    parser_release = SURFACE_PARSER_RELEASES[0]
    run_id, _ = _create_manual_sampling_lineage(
        app_connect=app_connect,
        project_id=project_id,
        now=now,
        source_platform="google",
        source_surface="ai_overviews",
        adapter_release="manual-google-aio-v1",
        question_id=str(question_id),
    )
    runs = PostgresSamplingRunRepository(connect=app_connect)
    suites = PostgresSamplingSuiteRepository(connect=app_connect)
    run = runs.get_run(project_id=project_id, run_id=run_id)
    suite = suites.get_suite(project_id=project_id, suite_id=run.suite_id)
    tasks = runs.list_tasks(
        project_id=project_id,
        run_id=run_id,
        suite=suite,
    )
    assert len(tasks) == 3
    writer = MinioWorkflowCManualArtifactWriter(
        object_store=objects,
        encryptor=IndependentWorkflowCArtifactEncryptor(
            PostgresWorkflowCArtifactKeyVault(
                connect=app_connect,
                cipher=cipher,
                synchronize=False,
            )
        ),
        repository=PostgresWorkflowCManualArtifactRepository(connect=app_connect),
        clock=lambda: now,
    )
    control = PostgresWorkflowCManualEvidenceControl(
        imports=PostgresManualEvidenceRepository(connect=app_connect),
        runs=runs,
        suites=suites,
        artifact_writer=writer,
        clock=lambda: now,
    )
    artifact_reader = PostgresWorkflowCManualArtifactReader(
        connect=worker_connect,
        cipher=cipher,
        object_store=objects,
        clock=lambda: now,
    )
    store = PostgresDurableJobStore(worker_connect)
    specs = PostgresWorkflowCJobSpecRepository(worker_connect)
    manual_operation = PostgresManualSamplingOperation(
        store=store,
        specs=specs,
        repository=PostgresWorkflowCSamplingRepository(worker_connect),
        artifacts=artifact_reader,
        clock=lambda: now,
    )
    for ordinal, task in enumerate(tasks, start=1):
        artifact = {
            "schema_version": "consumer-surface-artifact-v1",
            "platform": parser_release.platform,
            "surface": parser_release.surface.value,
            "final_url": "https://www.google.com/search?q=advinsys",
            "page_ready": True,
            "surface_markers": [parser_release.surface_marker],
            "ordinary_result_markers": ["ordinary_results_ready"],
            "answer_blocks": [
                {
                    "text": (
                        f"Advinsys Suite is recommended in result {ordinal}. "
                        "Contact operator@example.com."
                    ),
                    "locator": "dom://answer/1",
                }
            ],
            "citations": [
                {
                    "url": "https://example.com",
                    "title": "Approved source",
                    "position": 1,
                    "locator": "dom://citation/1",
                }
            ],
            "blocking_state": None,
            "follow_up_count": 1,
        }
        submitted = control.submit(
            project_id=project_id,
            run_id=run_id,
            task_id=task.id,
            actor_id="capture-operator",
            idempotency_key=f"semantic-vertical:submit:{ordinal}",
            payload=SubmitManualEvidenceRequest(
                expected_task_version=task.version,
                content_base64=base64.b64encode(json.dumps(artifact).encode("utf-8")).decode(
                    "ascii"
                ),
                content_type="application/json",
                governance_policy_option_key=AUTOMATIC_POLICY_KEY,
                evidence_kind="transcript_export",
                pre_redacted_attestation=False,
                device="desktop",
                locale="en-AU",
                captured_at=now - timedelta(seconds=1),
                surface_parser_release_id=parser_release.id,
            ),
        )
        approved = control.review(
            project_id=project_id,
            import_id=submitted.id,
            actor_id="review-operator",
            idempotency_key=f"semantic-vertical:approve:{ordinal}",
            approved=True,
            payload=ReviewManualEvidenceRequest(
                expected_version=submitted.aggregate_version,
                reason="AU answer and citations match the review rubric",
            ),
        )
        job_id = _attempt_job_id(
            app_connect,
            project_id=project_id,
            attempt_id=approved.attempt_id,
        )
        claimed = store.claim(
            job_id=job_id,
            project_id=project_id,
            expected_kind="sampling.manual_import",
            worker_id="manual-semantic-vertical",
            lease_for=timedelta(seconds=60),
        )
        assert claimed.lease is not None
        manual_result = manual_operation.execute(claimed.lease)
        assert manual_result["status"] == "succeeded"
        assert manual_result["evidence_status"] == "complete"

    with app_connect() as connection:
        set_project_scope(connection, project_id)
        parsed_observations = connection.execute(
            """SELECT evidence_json->'surface_parse' AS surface_parse
               FROM workflow_c_sampling_observations
               WHERE project_id = %s ORDER BY observed_at""",
            (project_id,),
        ).fetchall()
    assert len(parsed_observations) == 3
    for row in parsed_observations:
        surface_parse = row["surface_parse"]
        assert surface_parse["outcome"] == "captured"
        assert surface_parse["automated_capture"] is False
        assert surface_parse["live_capture_eligible"] is False
        assert "answer_text" not in surface_parse
        assert "citations" not in surface_parse

    completed = runs.get_run(project_id=project_id, run_id=run_id)
    assert completed.status.value == "completed"
    return run_id, runs, suite, artifact_reader, store, specs


class _ProviderRecoveryForbidden:
    def recover_derived(self, request):
        del request
        raise AssertionError("manual semantic vertical must not access Provider artifacts")


class _UnusedRecommendationDependency:
    def __init__(self, label: str) -> None:
        self._label = label

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unused {self._label} accessed through {name}")


def _assert_outbox_relayed_through_valkey(
    monkeypatch: pytest.MonkeyPatch,
    *,
    worker_connect,
    database_url: str,
    valkey_url: str,
    project_id: UUID,
    semantic_job_id: UUID,
) -> None:
    from geo_worker import relay

    broker = RedisBroker(url=valkey_url)

    def publish(
        *,
        job_id: UUID,
        project_id: UUID,
        style_collection: bool,
        workflow_c_maintenance: bool,
        recommendation_artifact_maintenance: bool,
        synthetic_artifact_maintenance: bool,
        connector_sync: bool,
        browser_capture: bool,
    ) -> None:
        assert not any(
            (
                style_collection,
                workflow_c_maintenance,
                recommendation_artifact_maintenance,
                synthetic_artifact_maintenance,
                connector_sync,
                browser_capture,
            )
        )
        broker.enqueue(
            dramatiq.Message(
                queue_name="durable-jobs",
                actor_name="process_durable_job",
                args=(str(job_id), str(project_id)),
                kwargs={},
                options={},
            )
        )

    monkeypatch.setattr(relay, "_send_job", publish)
    delivered = relay.relay_once(
        PostgresOutboxStore(worker_connect),
        worker_id="semantic-vertical-relay",
        batch_size=20,
    )
    assert delivered == 4, f"expected three manual capture jobs plus semantic job, got {delivered}"

    consumer = broker.consume("durable-jobs", prefetch=20, timeout=500)
    received: set[tuple[str, str]] = set()
    try:
        while message := next(consumer):
            assert message.actor_name == "process_durable_job"
            received.add((message.args[0], message.args[1]))
            consumer.ack(message)
    finally:
        consumer.close()
        broker.close()
    assert (str(semantic_job_id), str(project_id)) in received

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        published_at = connection.execute(
            """SELECT published_at FROM broker_outbox
                WHERE project_id = %s AND job_id = %s""",
            (project_id, semantic_job_id),
        ).fetchone()
    assert published_at is not None
    assert published_at["published_at"] is not None


def _attempt_job_id(connect, *, project_id: UUID, attempt_id: UUID) -> UUID:
    with connect() as connection:
        set_project_scope(connection, project_id)
        row = connection.execute(
            """SELECT durable_job_id FROM workflow_c_sampling_attempts
                WHERE project_id = %s AND id = %s""",
            (project_id, attempt_id),
        ).fetchone()
    assert row is not None
    return UUID(str(row["durable_job_id"]))


def _approved_statistical_protocol(
    repository: PostgresWorkflowCStatisticalProtocolRepository,
    *,
    project_id: UUID,
    definition,
    key: str,
    now: datetime,
):
    draft = repository.create(
        new_statistical_protocol(
            project_id=project_id,
            definition=definition,
            actor_id="statistics-maker",
            idempotency_key=key,
            occurred_at=now,
        ),
        idempotency_key=key,
    )
    submitted = repository.transition(
        project_id=project_id,
        protocol_id=draft.id,
        expected_aggregate_version=draft.aggregate_version,
        target_status=StatisticalProtocolStatus.IN_REVIEW,
        actor_id="statistics-maker",
        idempotency_key=f"{key}:submit",
        occurred_at=now,
    )
    return repository.transition(
        project_id=project_id,
        protocol_id=draft.id,
        expected_aggregate_version=submitted.aggregate_version,
        target_status=StatisticalProtocolStatus.APPROVED,
        actor_id="statistics-checker",
        reason="frozen statistical design reviewed",
        idempotency_key=f"{key}:approve",
        occurred_at=now,
    )


def _assert_secret_free_lineage(database_url: str, *, project_id: UUID, job_id: UUID) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        row = connection.execute(
            """SELECT spec.spec_payload::text AS spec,
                      manifest.payload::text AS manifest,
                      job.status,
                      (SELECT count(*) FROM broker_outbox outbox
                        WHERE outbox.project_id = job.project_id
                          AND outbox.job_id = job.id) AS outbox_count
                 FROM durable_jobs job
                 JOIN workflow_c_job_specs spec
                   ON spec.project_id = job.project_id AND spec.job_id = job.id
                 JOIN workflow_c_analysis_input_manifests manifest
                   ON manifest.project_id = job.project_id
                  AND manifest.id = (spec.spec_payload->'semantic_metrics'->>'manifest_id')::uuid
                WHERE job.project_id = %s AND job.id = %s""",
            (project_id, job_id),
        ).fetchone()
    assert row is not None
    assert row["status"] == "succeeded"
    assert row["outbox_count"] == 1
    assert "Advinsys Suite" not in row["spec"] + row["manifest"]
    assert "operator@example.com" not in row["spec"] + row["manifest"]
    assert "must-not-persist" not in row["spec"] + row["manifest"]
