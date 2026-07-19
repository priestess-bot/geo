"""Dramatiq actors carrying only durable job and project identities."""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import socket
import threading
from uuid import UUID

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Middleware
import psycopg
from psycopg.rows import dict_row

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.knowledge.worker import KnowledgeProcessHandler
from geo_core.knowledge.question_postgres import KnowledgeQuestionPostgresRepository
from geo_core.knowledge.question_worker import KnowledgeQuestionGenerateHandler
from geo_core.knowledge.rag_domain import KnowledgeRagEnqueuePolicy
from geo_core.knowledge.rag_postgres import KnowledgeRagPostgresRepository
from geo_core.knowledge.rag_worker import KnowledgeRagExtractHandler
from geo_core.model_gateway.contracts import ModelGatewayError
from geo_core.model_gateway.deepseek import DeepSeekGateway, default_deepseek_capability_registry
from geo_core.object_store_config import build_object_store
from geo_core.placements.artifact_worker import PlacementArtifactRepository
from geo_core.placements.url_verifier import PublicUrlVerifier
from geo_core.placements.simulation_worker import PromptSimulationHandler
from geo_core.placements.worker_composition import (
    EvidencePackHandler,
    ArtifactFinalizeHandler,
    GenerationHandler,
    JobHandler,
    MeasurementWindowHandler,
    PlacementWorkerDispatcher,
    PublicationVerificationHandler,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository
from geo_core.project_exports.postgres_source import PostgresProjectExportSource
from geo_core.project_exports.repository import PostgresProjectExportRepository
from geo_core.project_exports.worker import ProjectExportHandler
from geo_core.runtime_health import PeriodicHeartbeat, RuntimeHealthRepository, RuntimeHeartbeat
from geo_core.rag import RagSelection, load_rag_selection
from geo_worker.config import (
    runtime_heartbeat_identity,
    runtime_heartbeat_interval_seconds,
    secret_setting,
)


BROKER_URL = os.getenv("GEO_TASK_QUEUE_BROKER_URL", "redis://valkey:6379/0").strip()
if not BROKER_URL:
    raise RuntimeError("GEO_TASK_QUEUE_BROKER_URL is required")


class RuntimeHeartbeatMiddleware(Middleware):
    """Start heartbeats in each real Dramatiq process after its consumer boots."""

    def __init__(self) -> None:
        self._periodic: PeriodicHeartbeat | None = None
        self._lock = threading.Lock()

    def after_process_boot(self, broker) -> None:
        del broker
        self._heartbeat().mark_starting()

    def after_consumer_thread_boot(self, broker, thread) -> None:
        del broker, thread
        self._heartbeat().start()

    def before_consumer_thread_shutdown(self, broker, thread) -> None:
        del broker, thread
        with self._lock:
            periodic = self._periodic
        if periodic is not None:
            periodic.stop()

    def _heartbeat(self) -> PeriodicHeartbeat:
        with self._lock:
            if self._periodic is None:
                interval = runtime_heartbeat_interval_seconds()
                database_url = secret_setting("GEO_DATABASE_URL")
                repository = RuntimeHealthRepository(lambda: psycopg.connect(database_url))
                heartbeat = RuntimeHeartbeat(
                    repository,
                    runtime_heartbeat_identity("task_worker", process_id=os.getpid()),
                    interval_seconds=interval,
                )
                self._periodic = PeriodicHeartbeat(heartbeat, interval_seconds=float(interval))
            return self._periodic


broker = RedisBroker(url=BROKER_URL)
broker.add_middleware(RuntimeHeartbeatMiddleware())
dramatiq.set_broker(broker)


@lru_cache(maxsize=1)
def dispatcher() -> PlacementWorkerDispatcher:
    database_url = secret_setting("GEO_DATABASE_URL")

    def connection_factory():
        return psycopg.connect(database_url, row_factory=dict_row)

    store = PostgresDurableJobStore(connection_factory)
    repository = PlacementWorkerRepository(store)
    lease_for = timedelta(seconds=max(30, int(os.getenv("GEO_JOB_LEASE_SECONDS", "120"))))
    gateway = LazyDeepSeekGateway()
    selection, selection_hash = rag_runtime_selection()
    rag_policy = KnowledgeRagEnqueuePolicy(
        adapter_release=selection.adapter_release,
        selection_manifest_hash=selection_hash,
        configured_model=os.getenv("GEO_RAG_MODEL", "deepseek-v4-flash").strip(),
    )
    object_store = LazyArtifactObjectStore()
    handlers: dict[str, JobHandler] = {
        "artifact.finalize": ArtifactFinalizeHandler(
            store=store,
            repository=PlacementArtifactRepository(store),
            object_store=object_store,
        ),
        "evidence_pack.build": EvidencePackHandler(repository),
        "placement.generate": GenerationHandler(
            store=store, repository=repository, gateway=gateway, lease_for=lease_for
        ),
        "prompt_simulation.generate": PromptSimulationHandler(
            store=store, repository=repository, gateway=gateway, lease_for=lease_for
        ),
        "publication.verify": PublicationVerificationHandler(
            store=store,
            repository=repository,
            verifier=PublicUrlVerifier(),
            lease_for=lease_for,
        ),
        "placement.measure": MeasurementWindowHandler(repository),
        "knowledge.process": KnowledgeProcessHandler(store, rag_policy=rag_policy),
        "knowledge.rag.extract": KnowledgeRagExtractHandler(
            store=store,
            repository=KnowledgeRagPostgresRepository(store),
            gateway=gateway,
            object_store=object_store,
            selection=selection,
            selection_manifest_hash=selection_hash,
            lease_for=lease_for,
        ),
        "knowledge.question.generate": KnowledgeQuestionGenerateHandler(
            store=store,
            repository=KnowledgeQuestionPostgresRepository(store),
            gateway=gateway,
            object_store=object_store,
            selection=selection,
            selection_manifest_hash=selection_hash,
            lease_for=lease_for,
        ),
        "project.export": ProjectExportHandler(
            store=store,
            repository=PostgresProjectExportRepository(
                connection_factory, job_store=store
            ),
            source=PostgresProjectExportSource(connection_factory),
            object_store=object_store,
            lease_for=lease_for,
        ),
    }
    worker_id = os.getenv("GEO_WORKER_ID", f"durable:{socket.gethostname()}").strip()
    return PlacementWorkerDispatcher(
        store=store, handlers=handlers, worker_id=worker_id, lease_for=lease_for
    )


@dramatiq.actor(
    actor_name="process_durable_job",
    queue_name="durable-jobs",
    max_retries=0,
    time_limit=900_000,
)
def process_durable_job(job_id: str, project_id: str) -> dict[str, object]:
    return dict(dispatcher().process(job_id=UUID(job_id), project_id=UUID(project_id)))


class LazyDeepSeekGateway:
    """Resolve the paid-provider secret only when a generation job actually runs."""

    provider = "deepseek"

    def generate(self, request, *, policy, budget):
        from pathlib import Path

        value = os.getenv("GEO_DEEPSEEK_API_KEY_FILE", "").strip()
        if not value or not Path(value).is_file():
            raise ModelGatewayError(
                "GEO_DEEPSEEK_API_KEY_FILE is required for model-backed Worker jobs"
            )
        return DeepSeekGateway(
            api_key_file=Path(value),
            capability_registry=default_deepseek_capability_registry(),
        ).generate(request, policy=policy, budget=budget)


class LazyArtifactObjectStore:
    """Resolve object-store credentials only for artifact finalization jobs."""

    def put_object(self, **values):
        return build_object_store().put_object(**values)


@lru_cache(maxsize=1)
def rag_runtime_selection() -> tuple[RagSelection, str]:
    default = Path(__file__).resolve().parents[3] / "benchmarks/f019/selection.json"
    path = Path(os.getenv("GEO_RAG_SELECTION_FILE", str(default)).strip())
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise RuntimeError("GEO_RAG_SELECTION_FILE cannot be read") from exc
    return load_rag_selection(path), hashlib.sha256(content).hexdigest()
