from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import os
from typing import Any
from uuid import UUID, uuid4

from alembic import command
import psycopg
import pytest

from geo_core.model_gateway import ModelGatewayResult
from tests.integration.legacy_inflight_upgrade_support import (
    insert_legacy_job,
    job_events,
)
from tests.integration.test_batch2_migrations_postgres import (
    _seed_legacy_fixture,
    _temporary_database,
)
from tests.integration.test_knowledge_rag_postgres import _dispatcher


ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()
MINIO_ENDPOINT = os.getenv("GEO_F019_TEST_MINIO_ENDPOINT", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_URL,
        reason="GEO_ACCESS_TEST_ADMIN_DATABASE_URL is required",
    ),
    pytest.mark.skipif(
        not MINIO_ENDPOINT,
        reason="GEO_F019_TEST_MINIO_ENDPOINT is required",
    ),
]

SOURCE_SENTENCE = "Legacy Product has a documented capacity of 2 litres."
SOURCE_TEXT = (
    f"{SOURCE_SENTENCE}\n"
    "Legacy Product remains traceable through the upgraded Knowledge pipeline."
)


class _CountingGateway:
    provider = "legacy-inflight-integration"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request: Any, *, policy: Any, budget: Any) -> ModelGatewayResult:
        del policy
        budget.consume()
        payload = json.loads(request.messages[1]["content"])
        assert SOURCE_SENTENCE in payload["content"]
        self.calls += 1
        output = {
            "facts": [{"text": SOURCE_SENTENCE, "source_quote": SOURCE_SENTENCE}],
            "entities": [
                {
                    "entity_type": "Product",
                    "name": "Legacy Product",
                    "source_quote": "Legacy Product",
                }
            ],
            "relations": [],
        }
        response_hash = hashlib.sha256(
            json.dumps(output, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return ModelGatewayResult(
            output=output,
            call_log_id=uuid4(),
            provider_request_id=f"legacy-inflight-{uuid4()}",
            configured_model=request.configured_model,
            provider_reported_model=request.configured_model,
            prompt_tokens=30,
            completion_tokens=15,
            cost_usd=Decimal("0.001"),
            finish_reason="stop",
            response_hash=response_hash,
        )


def test_legacy_knowledge_process_jobs_resume_once_after_head_upgrade() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0010_campaign_destinations")
        with psycopg.connect(database_url) as connection:
            fixture = _seed_legacy_fixture(connection)
            seeded = _seed_knowledge_jobs(connection, fixture)

        command.upgrade(configuration, "head")
        gateway = _CountingGateway()
        dispatcher = _dispatcher(database_url, uuid4().hex[:10], gateway=gateway)
        rag_jobs: dict[str, UUID] = {}
        for label, job_id in seeded["jobs"].items():
            processed = dispatcher.process(job_id=job_id, project_id=fixture["project"])
            assert processed["status"] == "succeeded", processed
            rag_job_id = UUID(str(processed["rag_job_id"]))
            rag_jobs[label] = rag_job_id
            extracted = dispatcher.process(job_id=rag_job_id, project_id=fixture["project"])
            assert extracted["status"] == "succeeded", extracted

        assert gateway.calls == 2
        for job_id in (*seeded["jobs"].values(), *rag_jobs.values()):
            assert (
                dispatcher.process(job_id=job_id, project_id=fixture["project"])["status"]
                == "terminal"
            )
        assert gateway.calls == 2

        with psycopg.connect(database_url) as connection:
            _assert_process_jobs(connection, seeded, fixture)
            _assert_rag_jobs(connection, rag_jobs, seeded, fixture)


def _seed_knowledge_jobs(
    connection: psycopg.Connection[Any], fixture: dict[str, Any]
) -> dict[str, dict[str, UUID]]:
    jobs = {"queued": uuid4(), "expired_running": uuid4()}
    sources: dict[str, UUID] = {}
    runs: dict[str, UUID] = {}
    content = SOURCE_TEXT.encode()
    content_hash = hashlib.sha256(content).hexdigest()
    stages = ("ingest", "parse", "clean", "chunk", "fact_extract", "quality")
    for label, job_id in jobs.items():
        source_id, run_id = uuid4(), uuid4()
        sources[label], runs[label] = source_id, run_id
        running = label == "expired_running"
        connection.execute(
            """INSERT INTO knowledge_sources
                 (id, project_id, source_kind, title, filename, media_type, status,
                  raw_content, content_hash, created_by)
               VALUES (%s, %s, 'text', %s, %s, 'text/plain', %s, %s, %s, %s)""",
            (
                source_id,
                fixture["project"],
                f"Legacy inflight source {label}",
                f"legacy-inflight-{label}.txt",
                "processing" if running else "queued",
                content,
                content_hash,
                fixture["owner"],
            ),
        )
        connection.execute(
            """INSERT INTO knowledge_pipeline_runs
                 (id, project_id, source_id, status, input_hash, started_at, created_by)
               VALUES (%s, %s, %s, %s, %s,
                       CASE WHEN %s THEN clock_timestamp() - interval '15 minutes' END,
                       %s)""",
            (
                run_id,
                fixture["project"],
                source_id,
                "running" if running else "queued",
                content_hash,
                running,
                fixture["owner"],
            ),
        )
        for ordinal, stage in enumerate(stages, start=1):
            stage_running = running and stage == "ingest"
            connection.execute(
                """INSERT INTO knowledge_pipeline_stages
                     (project_id, pipeline_run_id, stage_key, ordinal, status, started_at)
                   VALUES (%s, %s, %s, %s, %s,
                           CASE WHEN %s THEN clock_timestamp() - interval '15 minutes' END)""",
                (
                    fixture["project"],
                    run_id,
                    stage,
                    ordinal,
                    "running" if stage_running else "pending",
                    stage_running,
                ),
            )
        insert_legacy_job(
            connection,
            job_id=job_id,
            project_id=fixture["project"],
            kind="knowledge.process",
            label=f"legacy-knowledge-{label}",
            running=running,
        )
        connection.execute(
            """INSERT INTO knowledge_job_specs
                 (job_id, project_id, pipeline_run_id, requested_by)
               VALUES (%s, %s, %s, %s)""",
            (job_id, fixture["project"], run_id, fixture["owner"]),
        )
    connection.commit()
    return {"jobs": jobs, "sources": sources, "runs": runs}


def _assert_process_jobs(
    connection: psycopg.Connection[Any],
    seeded: dict[str, dict[str, UUID]],
    fixture: dict[str, Any],
) -> None:
    rows = connection.execute(
        """SELECT id, status, attempt_count FROM durable_jobs
           WHERE id = ANY(%s) ORDER BY id""",
        (list(seeded["jobs"].values()),),
    ).fetchall()
    assert len(rows) == 2
    expected_attempts = {
        seeded["jobs"]["queued"]: 1,
        seeded["jobs"]["expired_running"]: 2,
    }
    for job_id, status, attempt_count in rows:
        assert status == "succeeded"
        assert attempt_count == expected_attempts[job_id]
    assert job_events(connection, job_id=seeded["jobs"]["queued"]) == [
        "lease_claimed",
        "job_succeeded",
    ]
    assert job_events(connection, job_id=seeded["jobs"]["expired_running"]) == [
        "lease_reclaimed",
        "job_succeeded",
    ]

    assert connection.execute(
        """SELECT count(*) FROM knowledge_sources
           WHERE id = ANY(%s) AND project_id = %s AND status = 'ready'""",
        (list(seeded["sources"].values()), fixture["project"]),
    ).fetchone() == (2,)
    assert connection.execute(
        """SELECT count(*) FROM knowledge_pipeline_runs
           WHERE id = ANY(%s) AND project_id = %s AND status = 'succeeded'""",
        (list(seeded["runs"].values()), fixture["project"]),
    ).fetchone() == (2,)
    assert connection.execute(
        """SELECT count(*) FROM knowledge_documents
           WHERE pipeline_run_id = ANY(%s) AND project_id = %s""",
        (list(seeded["runs"].values()), fixture["project"]),
    ).fetchone() == (2,)
    assert connection.execute(
        """SELECT count(*) FROM knowledge_chunks
           WHERE pipeline_run_id = ANY(%s) AND project_id = %s AND status = 'active'""",
        (list(seeded["runs"].values()), fixture["project"]),
    ).fetchone() == (2,)
    assert connection.execute(
        """SELECT count(*) FROM model_call_logs
           WHERE job_id = ANY(%s)""",
        (list(seeded["jobs"].values()),),
    ).fetchone() == (0,)


def _assert_rag_jobs(
    connection: psycopg.Connection[Any],
    rag_jobs: dict[str, UUID],
    seeded: dict[str, dict[str, UUID]],
    fixture: dict[str, Any],
) -> None:
    assert connection.execute(
        """SELECT count(*) FROM durable_jobs
           WHERE id = ANY(%s) AND status = 'succeeded' AND attempt_count = 1""",
        (list(rag_jobs.values()),),
    ).fetchone() == (2,)
    for job_id in rag_jobs.values():
        assert job_events(connection, job_id=job_id) == [
            "lease_claimed",
            "job_succeeded",
        ]
    assert connection.execute(
        """SELECT count(*), count(DISTINCT artifact_uri)
           FROM knowledge_rag_revisions
           WHERE pipeline_run_id = ANY(%s) AND project_id = %s
             AND lifecycle_status = 'active'""",
        (list(seeded["runs"].values()), fixture["project"]),
    ).fetchone() == (2, 2)
    assert connection.execute(
        """SELECT count(*) FILTER (WHERE status = 'reserved'),
                  count(*) FILTER (WHERE status = 'succeeded')
           FROM model_call_logs WHERE job_id = ANY(%s)""",
        (list(rag_jobs.values()),),
    ).fetchone() == (2, 2)
