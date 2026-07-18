"""Dramatiq actors carrying only durable job and project identities."""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
import os
import socket
from uuid import UUID

import dramatiq
from dramatiq.brokers.redis import RedisBroker
import psycopg

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.knowledge.worker import KnowledgeProcessHandler
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
from geo_worker.config import secret_setting


BROKER_URL = os.getenv("GEO_TASK_QUEUE_BROKER_URL", "redis://valkey:6379/0").strip()
if not BROKER_URL:
    raise RuntimeError("GEO_TASK_QUEUE_BROKER_URL is required")
dramatiq.set_broker(RedisBroker(url=BROKER_URL))


@lru_cache(maxsize=1)
def dispatcher() -> PlacementWorkerDispatcher:
    database_url = secret_setting("GEO_DATABASE_URL")
    store = PostgresDurableJobStore(lambda: psycopg.connect(database_url))
    repository = PlacementWorkerRepository(store)
    lease_for = timedelta(seconds=max(30, int(os.getenv("GEO_JOB_LEASE_SECONDS", "120"))))
    gateway = LazyDeepSeekGateway()
    handlers: dict[str, JobHandler] = {
        "artifact.finalize": ArtifactFinalizeHandler(
            store=store,
            repository=PlacementArtifactRepository(store),
            object_store=LazyArtifactObjectStore(),
        ),
        "evidence_pack.build": EvidencePackHandler(repository),
        "placement.generate": GenerationHandler(
            store=store, repository=repository, gateway=gateway, lease_for=lease_for
        ),
        "prompt_simulation.generate": PromptSimulationHandler(
            store=store, repository=repository, gateway=gateway, lease_for=lease_for
        ),
        "publication.verify": PublicationVerificationHandler(
            store=store, repository=repository, verifier=PublicUrlVerifier(),
            lease_for=lease_for,
        ),
        "placement.measure": MeasurementWindowHandler(repository),
        "knowledge.process": KnowledgeProcessHandler(store),
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
                "GEO_DEEPSEEK_API_KEY_FILE is required for placement.generate"
            )
        return DeepSeekGateway(
            api_key_file=Path(value),
            capability_registry=default_deepseek_capability_registry(),
        ).generate(request, policy=policy, budget=budget)


class LazyArtifactObjectStore:
    """Resolve object-store credentials only for artifact finalization jobs."""

    def put_object(self, **values):
        return build_object_store().put_object(**values)
