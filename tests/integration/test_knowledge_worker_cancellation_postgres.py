from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import os
import threading
from typing import Any, Mapping, cast
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.knowledge import KnowledgeApplication
from geo_core.knowledge.domain import ProcessingInput, SourceInput
from geo_core.knowledge.processing import process_source as process_source_impl
from geo_core.knowledge.rag_domain import KnowledgeRagEnqueuePolicy
from geo_core.knowledge.rag_postgres import KnowledgeRagPostgresRepository
from geo_core.knowledge.rag_worker import KnowledgeRagExtractHandler
from geo_core.knowledge.worker import KnowledgeProcessHandler
from geo_core.model_gateway import ModelGatewayResult
from geo_core.placements.worker_composition import PlacementWorkerDispatcher
from geo_core.rag import RagSelection
from tests.integration.placement_worker_support import cleanup_projects, login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]

SELECTION_HASH = "b" * 64
SELECTION = RagSelection(
    "project-native-rag-v1",
    "project-native-rag-v1",
    "f019-corpus-v1",
    "c" * 64,
)


def test_queued_and_running_process_cancellation_close_pipeline_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix, app_login, worker_login, app_password, worker_password, project = _seed_access(
        "knowledge-cancel"
    )
    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    application = KnowledgeApplication(app_url)
    principal = _principal(project, suffix)
    dispatcher = _process_dispatcher(worker_url, suffix)
    try:
        queued = application.create_source(
            principal,
            project_id=project["project"],
            source=_source("Queued cancellation fixture."),
            idempotency_key=f"queued-cancel-{suffix}",
        )
        application.archive_source(
            principal,
            project_id=project["project"],
            source_id=cast(UUID, cast(Mapping[str, object], queued["source"])["id"]),
        )
        assert _dispatch_created(dispatcher, queued, project["project"])["status"] == "cancelled"
        assert _pipeline_state(cast(UUID, queued["job"]["id"])) == (
            "cancelled",
            "cancelled",
            "archived",
            ["skipped"],
        )

        missed_at_load = application.create_source(
            principal,
            project_id=project["project"],
            source=_source("Missed pre-cancel at load fixture."),
            idempotency_key=f"missed-load-cancel-{suffix}",
        )
        _archive_source_row(cast(UUID, missed_at_load["source"]["id"]))
        assert (
            _dispatch_created(dispatcher, missed_at_load, project["project"])["status"]
            == "cancelled"
        )
        assert _pipeline_state(cast(UUID, missed_at_load["job"]["id"])) == (
            "cancelled",
            "cancelled",
            "archived",
            ["skipped"],
        )

        running = application.create_source(
            principal,
            project_id=project["project"],
            source=_source("Running cancellation fixture."),
            idempotency_key=f"running-cancel-{suffix}",
        )
        running_source_id = cast(UUID, running["source"]["id"])

        def archive_during_processing(claim: ProcessingInput):
            application.archive_source(
                principal,
                project_id=project["project"],
                source_id=claim.source_id,
            )
            return process_source_impl(claim)

        monkeypatch.setattr("geo_core.knowledge.worker.process_source", archive_during_processing)
        assert _dispatch_created(dispatcher, running, project["project"])["status"] == "cancelled"
        assert cast(UUID, running["source"]["id"]) == running_source_id
        assert _pipeline_state(cast(UUID, running["job"]["id"])) == (
            "cancelled",
            "cancelled",
            "archived",
            ["skipped"],
        )

        missed_at_finalize = application.create_source(
            principal,
            project_id=project["project"],
            source=_source("Missed pre-cancel at finalize fixture."),
            idempotency_key=f"missed-finalize-cancel-{suffix}",
        )

        def archive_row_during_processing(claim: ProcessingInput):
            _archive_source_row(claim.source_id)
            return process_source_impl(claim)

        monkeypatch.setattr(
            "geo_core.knowledge.worker.process_source", archive_row_during_processing
        )
        assert (
            _dispatch_created(dispatcher, missed_at_finalize, project["project"])["status"]
            == "cancelled"
        )
        assert _pipeline_state(cast(UUID, missed_at_finalize["job"]["id"])) == (
            "cancelled",
            "cancelled",
            "archived",
            ["skipped"],
        )
    finally:
        _cleanup(project, app_login, worker_login)


def test_running_rag_cancellation_preserves_successful_ingest_pipeline() -> None:
    suffix, app_login, worker_login, app_password, worker_password, project = _seed_access(
        "knowledge-rag-cancel"
    )
    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    application = KnowledgeApplication(app_url)
    principal = _principal(project, suffix)
    process_dispatcher = _process_dispatcher(worker_url, suffix, with_rag=True)
    try:
        created = application.create_source(
            principal,
            project_id=project["project"],
            source=_source("星澜 A1 belongs_to 星澜。A1 的流量为每分钟 2 升。"),
            idempotency_key=f"rag-running-cancel-{suffix}",
        )
        processed = _dispatch_created(process_dispatcher, created, project["project"])
        assert processed["status"] == "succeeded"
        rag_job_id = UUID(str(processed["rag_job_id"]))
        source_id = cast(UUID, created["source"]["id"])

        store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
        rag_dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "knowledge.rag.extract": KnowledgeRagExtractHandler(
                    store=store,
                    repository=KnowledgeRagPostgresRepository(store),
                    gateway=_ArchiveDuringGenerate(
                        application, principal, project["project"], source_id
                    ),
                    object_store=_UnreachableObjectStore(),
                    selection=SELECTION,
                    selection_manifest_hash=SELECTION_HASH,
                    lease_for=timedelta(seconds=30),
                )
            },
            worker_id=f"rag-cancel-{suffix}",
            lease_for=timedelta(seconds=30),
        )
        assert (
            rag_dispatcher.process(job_id=rag_job_id, project_id=project["project"])["status"]
            == "cancelled"
        )

        with psycopg.connect(ADMIN_URL) as admin:
            assert (
                admin.execute(
                    "SELECT status FROM durable_jobs WHERE id = %s", (rag_job_id,)
                ).fetchone()[0]
                == "cancelled"
            )
            assert _pipeline_state(cast(UUID, created["job"]["id"]), connection=admin) == (
                "succeeded",
                "succeeded",
                "archived",
                ["succeeded"],
            )
            assert (
                admin.execute(
                    """SELECT count(*) FROM knowledge_rag_revisions
                   WHERE project_id = %s AND source_id = %s""",
                    (project["project"], source_id),
                ).fetchone()[0]
                == 0
            )
    finally:
        _cleanup(project, app_login, worker_login)


def test_archive_post_lock_cancel_closes_concurrent_reprocess_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix, app_login, worker_login, app_password, worker_password, project = _seed_access(
        "knowledge-archive-race"
    )
    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    application = KnowledgeApplication(app_url)
    principal = _principal(project, suffix)
    dispatcher = _process_dispatcher(worker_url, suffix)
    entered_gap = threading.Event()
    release_archive = threading.Event()
    archive_result: list[Mapping[str, object]] = []
    archive_error: list[BaseException] = []
    archive_thread: threading.Thread | None = None
    try:
        created = application.create_source(
            principal,
            project_id=project["project"],
            source=_source("Archive race fixture."),
            idempotency_key=f"archive-race-source-{suffix}",
        )
        assert _dispatch_created(dispatcher, created, project["project"])["status"] == "succeeded"
        source_id = cast(UUID, created["source"]["id"])

        from geo_core.knowledge import rag_source_application

        real_lock = rag_source_application.lock_source_aggregate

        def pause_archive_lock(connection: Any, logical_source_id: UUID) -> None:
            entered_gap.set()
            assert release_archive.wait(timeout=5), "archive gap was not released"
            real_lock(connection, logical_source_id)

        monkeypatch.setattr(rag_source_application, "lock_source_aggregate", pause_archive_lock)

        def archive() -> None:
            try:
                archive_result.append(
                    application.archive_source(
                        principal,
                        project_id=project["project"],
                        source_id=source_id,
                    )
                )
            except BaseException as exc:
                archive_error.append(exc)

        archive_thread = threading.Thread(target=archive)
        archive_thread.start()
        assert entered_gap.wait(timeout=5), "archive did not enter the pre/post cancel gap"
        reprocessed = application.reprocess_source(
            principal,
            project_id=project["project"],
            source_id=source_id,
            idempotency_key=f"archive-race-reprocess-{suffix}",
        )
        release_archive.set()
        archive_thread.join(timeout=5)
        assert not archive_thread.is_alive()
        assert archive_error == []
        assert archive_result[0]["outcome"] == "archived"

        assert (
            _dispatch_created(dispatcher, reprocessed, project["project"])["status"] == "cancelled"
        )
        assert _pipeline_state(cast(UUID, reprocessed["job"]["id"])) == (
            "cancelled",
            "cancelled",
            "archived",
            ["skipped"],
        )
    finally:
        release_archive.set()
        if archive_thread is not None and archive_thread.is_alive():
            archive_thread.join(timeout=5)
        _cleanup(project, app_login, worker_login)


class _ArchiveDuringGenerate:
    provider = "integration-test"

    def __init__(
        self,
        application: KnowledgeApplication,
        principal: AccessPrincipal,
        project_id: UUID,
        source_id: UUID,
    ) -> None:
        self._application = application
        self._principal = principal
        self._project_id = project_id
        self._source_id = source_id

    def generate(self, request: Any, *, policy: Any, budget: Any) -> ModelGatewayResult:
        del policy
        budget.consume()
        self._application.archive_source(
            self._principal,
            project_id=self._project_id,
            source_id=self._source_id,
        )
        output = {
            "facts": [
                {
                    "text": "A1 的流量为每分钟 2 升。",
                    "source_quote": "A1 的流量为每分钟 2 升。",
                }
            ],
            "entities": [
                {"entity_type": "Product", "name": "A1", "source_quote": "A1"},
                {"entity_type": "Brand", "name": "星澜", "source_quote": "星澜"},
            ],
            "relations": [
                {
                    "subject": "A1",
                    "predicate": "belongs_to",
                    "object": "星澜",
                    "source_quote": "A1 belongs_to 星澜",
                }
            ],
        }
        response_hash = hashlib.sha256(
            json.dumps(output, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return ModelGatewayResult(
            output=output,
            call_log_id=uuid4(),
            provider_request_id=f"cancel-{uuid4()}",
            configured_model=request.configured_model,
            provider_reported_model=request.configured_model,
            prompt_tokens=10,
            completion_tokens=10,
            cost_usd=Decimal("0.001"),
            finish_reason="stop",
            response_hash=response_hash,
        )


class _UnreachableObjectStore:
    def put_object(self, **kwargs: object) -> Any:
        del kwargs
        raise AssertionError("cancelled RAG work must not publish an artifact")


def _seed_access(prefix: str) -> tuple[str, str, str, str, str, Mapping[str, UUID]]:
    suffix = uuid4().hex[:10]
    app_login, worker_login = f"geo_{prefix}_app_{suffix}", f"geo_{prefix}_worker_{suffix}"
    app_password, worker_password = uuid4().hex, uuid4().hex
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                sql.Identifier(app_login), sql.Literal(app_password)
            )
        )
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                sql.Identifier(worker_login), sql.Literal(worker_password)
            )
        )
        project = seed_project(admin, suffix=f"{prefix}-{suffix}")
        admin.commit()
    return suffix, app_login, worker_login, app_password, worker_password, project


def _process_dispatcher(
    worker_url: str, suffix: str, *, with_rag: bool = False
) -> PlacementWorkerDispatcher:
    store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
    policy = (
        KnowledgeRagEnqueuePolicy(
            adapter_release=SELECTION.adapter_release,
            selection_manifest_hash=SELECTION_HASH,
            configured_model="deepseek-v4-flash",
        )
        if with_rag
        else None
    )
    return PlacementWorkerDispatcher(
        store=store,
        handlers={
            "knowledge.process": KnowledgeProcessHandler(
                store,
                rag_policy=policy,
                lease_for=timedelta(seconds=30),
            )
        },
        worker_id=f"knowledge-cancel-{suffix}",
        lease_for=timedelta(seconds=30),
    )


def _dispatch_created(
    dispatcher: PlacementWorkerDispatcher,
    created: Mapping[str, Any],
    project_id: UUID,
) -> Mapping[str, object]:
    return dispatcher.process(job_id=cast(UUID, created["job"]["id"]), project_id=project_id)


def _pipeline_state(
    job_id: UUID, *, connection: Any | None = None
) -> tuple[str, str, str, list[str]]:
    owned = connection is None
    connection = connection or psycopg.connect(ADMIN_URL)
    try:
        row = connection.execute(
            """SELECT job.status, run.status, source.status,
                      array_agg(DISTINCT stage.status ORDER BY stage.status)
               FROM durable_jobs job
               JOIN knowledge_job_specs spec
                 ON spec.job_id = job.id AND spec.project_id = job.project_id
               JOIN knowledge_pipeline_runs run
                 ON run.id = spec.pipeline_run_id AND run.project_id = spec.project_id
               JOIN knowledge_sources source
                 ON source.id = run.source_id AND source.project_id = run.project_id
               JOIN knowledge_pipeline_stages stage
                 ON stage.pipeline_run_id = run.id AND stage.project_id = run.project_id
               WHERE job.id = %s
               GROUP BY job.status, run.status, source.status""",
            (job_id,),
        ).fetchone()
        assert row is not None
        return cast(tuple[str, str, str, list[str]], row)
    finally:
        if owned:
            connection.close()


def _source(content: str) -> SourceInput:
    body = (
        f"{content}\n"
        "This governed source fixture contains enough descriptive text for deterministic "
        "Knowledge parsing and cancellation tests."
    )
    return SourceInput(
        source_kind="text",
        title="Cancellation fixture",
        source_url=None,
        filename="cancel.txt",
        media_type="text/plain",
        raw_content=body.encode(),
    )


def _archive_source_row(source_id: UUID) -> None:
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """UPDATE knowledge_sources SET status = 'archived',
                      updated_at = clock_timestamp()
               WHERE id = %s""",
            (source_id,),
        )
        admin.commit()


def _principal(project: Mapping[str, UUID], suffix: str) -> AccessPrincipal:
    return AccessPrincipal(
        identity_id=project["owner"],
        actor_id=f"knowledge-cancel-{suffix}",
        tenant_id=project["tenant"],
        memberships=(MembershipRecord(project["project"], project["tenant"], "admin"),),
        auth_method="development",
    )


def _cleanup(project: Mapping[str, UUID], app_login: str, worker_login: str) -> None:
    with psycopg.connect(ADMIN_URL) as admin:
        cleanup_projects(
            admin,
            projects=[project],
            tenant_ids=[project["tenant"]],
            app_login=app_login,
            worker_login=worker_login,
        )
        admin.commit()
