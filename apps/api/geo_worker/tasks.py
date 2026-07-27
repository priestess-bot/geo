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
from geo_core.synthetic_lab.artifact_maintenance_contracts import (
    SYNTHETIC_ARTIFACT_MAINTENANCE_ACTOR,
    SYNTHETIC_ARTIFACT_MAINTENANCE_QUEUE,
)
from geo_worker.config import (
    runtime_heartbeat_identity,
    runtime_heartbeat_interval_seconds,
    secret_setting,
)
from geo_worker.recommendation_artifact_maintenance_routing import (
    RECOMMENDATION_ARTIFACT_MAINTENANCE_ACTOR,
    RECOMMENDATION_ARTIFACT_MAINTENANCE_QUEUE,
)
from geo_worker.workflow_c_maintenance_routing import (
    WORKFLOW_C_MAINTENANCE_ACTOR,
    WORKFLOW_C_MAINTENANCE_QUEUE,
)
from geo_worker.service_identity import require_model_gateway_worker_identity


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
        # Compose every admitted durable-job surface before this process starts
        # consuming. A partial registry would otherwise fail only after an
        # outbox message has already been delivered.
        dispatcher()
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

STYLE_COLLECTION_QUEUE = "style-collection"
STYLE_COLLECTION_ACTOR = "process_style_collection_job"


@lru_cache(maxsize=1)
def dispatcher() -> PlacementWorkerDispatcher:
    database_url = secret_setting("GEO_DATABASE_URL")

    def connection_factory():
        return psycopg.connect(database_url, row_factory=dict_row)

    store = PostgresDurableJobStore(connection_factory)
    repository = PlacementWorkerRepository(store)
    lease_for = timedelta(seconds=max(30, int(os.getenv("GEO_JOB_LEASE_SECONDS", "120"))))
    gateway = LazyDeepSeekGateway()
    workflow_executor = build_workflow_executor(store=store)
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
            store=store,
            repository=repository,
            gateway=gateway,
            lease_for=lease_for,
            workflow_executor=workflow_executor,
        ),
        "prompt_simulation.generate": PromptSimulationHandler(
            store=store,
            repository=repository,
            gateway=gateway,
            lease_for=lease_for,
            workflow_executor=workflow_executor,
        ),
        "publication.verify": PublicationVerificationHandler(
            store=store,
            repository=repository,
            verifier=PublicUrlVerifier(),
            lease_for=lease_for,
        ),
        "placement.measure": MeasurementWindowHandler(repository),
        "knowledge.process": KnowledgeProcessHandler(
            store, rag_policy=rag_policy, lease_for=lease_for
        ),
        "knowledge.rag.extract": KnowledgeRagExtractHandler(
            store=store,
            repository=KnowledgeRagPostgresRepository(store),
            gateway=gateway,
            object_store=object_store,
            selection=selection,
            selection_manifest_hash=selection_hash,
            lease_for=lease_for,
            workflow_executor=workflow_executor,
        ),
        "knowledge.question.generate": KnowledgeQuestionGenerateHandler(
            store=store,
            repository=KnowledgeQuestionPostgresRepository(store),
            gateway=gateway,
            object_store=object_store,
            selection=selection,
            selection_manifest_hash=selection_hash,
            lease_for=lease_for,
            workflow_executor=workflow_executor,
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
    handlers = build_shared_non_b_handlers(
        base=handlers,
        store=store,
        lease_for=lease_for,
    )
    worker_id = _worker_id()
    return PlacementWorkerDispatcher(
        store=store, handlers=handlers, worker_id=worker_id, lease_for=lease_for
    )


def build_workflow_executor(*, store: PostgresDurableJobStore):
    """Build the explicit native-or-Dify business runtime selection.

    ``native`` is an operator-visible rollback mode. Under ``dify`` an active
    binding is fail-closed: the executor never falls back after a Dify error.
    """

    backend = os.getenv("GEO_WORKFLOW_RUNTIME_BACKEND", "native").strip().lower()
    if backend == "native":
        return None
    if backend != "dify":
        raise RuntimeError("GEO_WORKFLOW_RUNTIME_BACKEND must be native or dify")

    from geo_core.model_gateway import build_secret_store_credential_resolver
    from geo_core.workflow_runtime import (
        DifyPublishedWorkflowReader,
        DifyWorkflowExecutor,
        PostgresWorkflowRuntimeRepository,
    )

    database_url = secret_setting("GEO_DATABASE_URL")
    return DifyWorkflowExecutor(
        repository=PostgresWorkflowRuntimeRepository(store),
        credential_resolver=build_secret_store_credential_resolver(
            database_url=database_url,
            master_keyring_path=_required_file_setting(
                "GEO_SECRET_STORE_MASTER_KEYRING_FILE"
            ),
            request_hash_key_path=_required_file_setting(
                "GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE"
            ),
            worker_actor_id=require_model_gateway_worker_identity(database_url=database_url),
        ),
        base_url=os.getenv("GEO_DIFY_API_URL", "http://dify-api:5001"),
        timeout_seconds=float(os.getenv("GEO_DIFY_TIMEOUT_SECONDS", "180")),
        published_reader=DifyPublishedWorkflowReader(
            base_url=os.getenv("GEO_DIFY_CONSOLE_URL", "http://dify-api:5001"),
            state_file=_required_file_setting("GEO_DIFY_STATE_FILE"),
        ),
        require_active=True,
    )


@lru_cache(maxsize=1)
def governed_model_gateway_runtime():
    """Build the only production Model Gateway factory available to Worker jobs.

    This intentionally has no legacy DeepSeek fallback: new Prompt/Synthetic/
    Recommendation/Workflow-C calls must use a frozen runtime selection,
    Secret Store credential resolver and encrypted Provider artifact store.
    """

    from geo_worker.model_gateway_runtime import build_governed_model_gateway_worker_runtime

    database_url = secret_setting("GEO_DATABASE_URL")
    worker_id = _worker_id()
    return build_governed_model_gateway_worker_runtime(
        database_url=database_url,
        object_store=LazyArtifactObjectStore(),
        worker_id=worker_id,
        worker_actor_id=require_model_gateway_worker_identity(database_url=database_url),
        secret_store_master_keyring_path=_required_file_setting(
            "GEO_SECRET_STORE_MASTER_KEYRING_FILE"
        ),
        secret_store_request_hash_key_path=_required_file_setting(
            "GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE"
        ),
        provider_artifact_keyring_path=_required_file_setting(
            "GEO_PROVIDER_ARTIFACT_KEYRING_FILE"
        ),
    )


def build_prompt_program_worker_handlers(
    *,
    store: PostgresDurableJobStore,
    lease_for: timedelta,
):
    """Compose Prompt test Jobs from durable PostgreSQL and the governed Gateway."""

    from geo_core.prompts.test_artifacts import S3PromptTestArtifactStore
    from geo_core.prompts.test_execution_repository import (
        build_prompt_test_execution_repository,
    )
    from geo_core.prompts.test_model_executor import ModelGatewayPromptTestCaseExecutor
    from geo_core.prompts.test_worker import build_prompt_test_worker_handlers

    runtime = governed_model_gateway_runtime()
    return build_prompt_test_worker_handlers(
        store=store,
        repository=build_prompt_test_execution_repository(secret_setting("GEO_DATABASE_URL")),
        executor=ModelGatewayPromptTestCaseExecutor(
            runtime=runtime.model_calls,
            result_recovery=runtime.artifacts.recovery,
        ),
        artifacts=S3PromptTestArtifactStore(LazyArtifactObjectStore()),
        lease_for=lease_for,
    )


def build_synthetic_lab_worker_handlers(
    *,
    store: PostgresDurableJobStore,
    lease_for: timedelta,
):
    """Compose non-browser Synthetic Jobs from governed, durable dependencies."""

    from geo_core.synthetic_lab.postgres_worker import (
        build_synthetic_production_worker_handlers,
    )

    runtime = governed_model_gateway_runtime()
    return build_synthetic_production_worker_handlers(
        database_url=secret_setting("GEO_DATABASE_URL"),
        store=store,
        model_runtime=runtime.model_calls,
        provider_result_recovery=runtime.artifacts.recovery,
        object_store=LazyArtifactObjectStore(),
        synthetic_artifact_keyring_path=_required_file_setting(
            "GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE"
        ),
        lease_for=lease_for,
    )


def build_shared_non_b_handlers(
    *,
    base: dict[str, JobHandler],
    store: PostgresDurableJobStore,
    lease_for: timedelta,
) -> dict[str, JobHandler]:
    """Register the complete shared non-B Worker surface at process startup.

    A missing immutable keyring, service identity, or PostgreSQL operation is
    intentionally fatal.  Durable Jobs must never be acknowledged by a worker
    whose registry only represents part of the routes that admission exposes.
    """

    from geo_worker.non_b_handlers import merge_non_b_handlers

    return merge_non_b_handlers(
        base=base,
        prompt=build_prompt_program_worker_handlers(store=store, lease_for=lease_for),
        synthetic=build_synthetic_lab_worker_handlers(store=store, lease_for=lease_for),
        recommendations=build_recommendation_generation_worker_handlers(
            store=store,
            lease_for=lease_for,
        ),
        workflow_c=build_workflow_c_production_worker_handlers(
            store=store,
            lease_for=lease_for,
        ),
    )


def build_recommendation_generation_worker_handlers(
    *,
    store: PostgresDurableJobStore,
    lease_for: timedelta,
):
    """Compose only the governed Recommendation parent/child job handlers.

    Recommendation task manifests use their own restricted bucket and keyring;
    model responses continue through the shared governed Model Gateway artifact
    recovery path. Neither dependency can fall back to the generic store.
    """

    from geo_core.object_store_config import build_object_store_from_prefix
    from geo_core.recommendations.artifact_composition import (
        build_recommendation_artifact_composition,
    )
    from geo_core.recommendations.generation_result_recovery import (
        GovernedRecommendationModelResultLoader,
        ProviderArtifactRecommendationRecoveryAdapter,
    )
    from geo_core.recommendations.postgres.prompt_runtime import (
        build_recommendation_prompt_resolver,
    )
    from geo_core.recommendations.postgres.worker_composition import (
        build_recommendation_generation_worker_handlers as build_handlers,
    )

    database_url = secret_setting("GEO_DATABASE_URL")

    def connection_factory():
        return psycopg.connect(database_url, row_factory=dict_row)

    artifacts = build_recommendation_artifact_composition(
        connection_factory=connection_factory,
        object_store=build_object_store_from_prefix(
            "GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE"
        ),
        keyring_path=_required_file_setting("GEO_RECOMMENDATION_ARTIFACT_KEYRING_FILE"),
    )
    runtime = governed_model_gateway_runtime()
    return build_handlers(
        store=store,
        connection_factory=connection_factory,
        prompts=build_recommendation_prompt_resolver(
            connection_factory=connection_factory
        ),
        artifacts=artifacts.artifacts,
        model_results=GovernedRecommendationModelResultLoader(
            ProviderArtifactRecommendationRecoveryAdapter(runtime.artifacts.recovery)
        ),
        model_job_admitter=runtime.model_calls,
        model_runtime_loader=runtime.model_calls,
        lease_for=lease_for,
    )


def build_workflow_c_production_worker_handlers(
    *,
    store: PostgresDurableJobStore,
    lease_for: timedelta,
):
    """Compose all shared Workflow C operations from durable dependencies.

    This intentionally delegates only to the Workflow C PostgreSQL composition
    root.  Import/configuration errors are allowed to propagate so the generic
    Worker cannot acknowledge a Workflow C Job without its complete operation
    set.
    """

    from geo_worker.workflow_c_production import (
        build_workflow_c_production_worker_handlers as build_handlers,
    )

    runtime = governed_model_gateway_runtime()
    return build_handlers(
        database_url=secret_setting("GEO_DATABASE_URL"),
        store=store,
        model_runtime=runtime.model_calls,
        provider_result_recovery=runtime.artifacts.recovery,
        workflow_c_artifact_keyring_path=_required_file_setting(
            "GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE"
        ),
        lease_for=lease_for,
    )


@dramatiq.actor(
    actor_name="process_durable_job",
    queue_name="durable-jobs",
    max_retries=0,
    time_limit=900_000,
)
def process_durable_job(job_id: str, project_id: str) -> dict[str, object]:
    return dict(dispatcher().process(job_id=UUID(job_id), project_id=UUID(project_id)))


def send_durable_job(
    *,
    job_id: UUID,
    project_id: UUID,
    style_collection: bool,
    workflow_c_maintenance: bool = False,
    recommendation_artifact_maintenance: bool = False,
    synthetic_artifact_maintenance: bool = False,
) -> None:
    """Route a durable Job to the one Worker allowed to consume its kind."""
    dedicated_workers = (
        int(style_collection)
        + int(workflow_c_maintenance)
        + int(recommendation_artifact_maintenance)
        + int(synthetic_artifact_maintenance)
    )
    if dedicated_workers > 1:
        raise RuntimeError("a durable Job cannot target two dedicated Workers")
    if not style_collection:
        if workflow_c_maintenance:
            broker.enqueue(
                dramatiq.Message(
                    queue_name=WORKFLOW_C_MAINTENANCE_QUEUE,
                    actor_name=WORKFLOW_C_MAINTENANCE_ACTOR,
                    args=(str(job_id), str(project_id)),
                    kwargs={},
                    options={},
                )
            )
            return
        if recommendation_artifact_maintenance:
            broker.enqueue(
                dramatiq.Message(
                    queue_name=RECOMMENDATION_ARTIFACT_MAINTENANCE_QUEUE,
                    actor_name=RECOMMENDATION_ARTIFACT_MAINTENANCE_ACTOR,
                    args=(str(job_id), str(project_id)),
                    kwargs={},
                    options={},
                )
            )
            return
        if synthetic_artifact_maintenance:
            broker.enqueue(
                dramatiq.Message(
                    queue_name=SYNTHETIC_ARTIFACT_MAINTENANCE_QUEUE,
                    actor_name=SYNTHETIC_ARTIFACT_MAINTENANCE_ACTOR,
                    args=(str(job_id), str(project_id)),
                    kwargs={},
                    options={},
                )
            )
            return
        process_durable_job.send(str(job_id), str(project_id))
        return
    broker.enqueue(
        dramatiq.Message(
            queue_name=STYLE_COLLECTION_QUEUE,
            actor_name=STYLE_COLLECTION_ACTOR,
            args=(str(job_id), str(project_id)),
            kwargs={},
            options={},
        )
    )


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
    """Resolve object-store credentials only when an artifact operation runs."""

    def put_object(self, **values):
        return build_object_store().put_object(**values)

    def get_s3_uri(self, **values):
        return build_object_store().get_s3_uri(**values)

    def delete_s3_uri(self, **values):
        return build_object_store().delete_s3_uri(**values)

    def uri_for_key(self, key: str) -> str:
        return build_object_store().uri_for_key(key)


def _worker_id() -> str:
    worker_id = os.getenv("GEO_WORKER_ID", f"durable:{socket.gethostname()}").strip()
    if not worker_id:
        raise RuntimeError("GEO_WORKER_ID cannot be empty")
    return worker_id


def _required_file_setting(name: str) -> str:
    path = os.getenv(name, "").strip()
    if not path:
        raise RuntimeError(f"{name} is required for governed Model Gateway Worker jobs")
    if not Path(path).is_file():
        raise RuntimeError(f"{name} must reference a readable regular file")
    return path


@lru_cache(maxsize=1)
def rag_runtime_selection() -> tuple[RagSelection, str]:
    default = Path(__file__).resolve().parents[3] / "benchmarks/f019/selection.json"
    path = Path(os.getenv("GEO_RAG_SELECTION_FILE", str(default)).strip())
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise RuntimeError("GEO_RAG_SELECTION_FILE cannot be read") from exc
    return load_rag_selection(path), hashlib.sha256(content).hexdigest()
