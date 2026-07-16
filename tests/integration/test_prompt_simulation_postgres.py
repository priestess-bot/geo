from __future__ import annotations

import hashlib
import os
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.placements.application import PlacementApplication
from geo_core.placements.artifact_worker import PlacementArtifactRepository
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.placements.simulation_worker import PromptSimulationHandler
from geo_core.placements.worker_composition import (
    ArtifactFinalizeHandler,
    PlacementWorkerDispatcher,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository
from tests.integration.placement_worker_support import (
    FakeGateway,
    MemoryArtifactStore,
    cleanup_projects,
    login_url,
    seed_project,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_prompt_simulation_is_durable_and_cannot_create_formal_placement_objects() -> None:
    suffix = uuid4().hex[:10]
    app_login = f"geo_sim_app_{suffix}"
    worker_login = f"geo_sim_worker_{suffix}"
    app_password, worker_password = uuid4().hex, uuid4().hex
    brand_id, evidence_id = uuid4(), uuid4()
    evidence_text = "The selected product is a robotic lawn mower offered in Australia."
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
        ids = seed_project(admin, suffix=f"simulation-{suffix}")
        admin.execute(
            """INSERT INTO product_entities
                 (id, project_id, entity_type, canonical_name)
               VALUES (%s, %s, 'brand', %s)""",
            (brand_id, ids["project"], f"Brand simulation-{suffix}"),
        )
        admin.execute(
            """INSERT INTO evidence_items
                 (id, project_id, item_type, source_id, subject_entity_id, subject_role,
                  snapshot_text, snapshot_hash, source_revision_kind,
                  source_revision_value, usage_rights, confidentiality,
                  public_disclosure_allowed, public_source_url, public_source_title,
                  citation_label, quotation_allowed, attribution_required)
               VALUES (%s, %s, 'approved_fact', %s, %s, 'product', %s, %s,
                       'content_hash', %s, 'owned', 'public', true,
                       'https://example.test/product', 'Product source',
                       'Product source', false, true)""",
            (
                evidence_id,
                ids["project"],
                uuid4(),
                ids["entity"],
                evidence_text,
                hashlib.sha256(evidence_text.encode()).hexdigest(),
                hashlib.sha256(f"revision:{evidence_text}".encode()).hexdigest(),
            ),
        )
    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    artifact_store = MemoryArtifactStore()
    artifact_store.fail_next = False
    application = PlacementApplication(
        placement_uow_factory(lambda: psycopg.connect(app_url)),
        artifact_reader=artifact_store,
    )
    try:
        destination = application.create_destination(
            project_id=ids["project"],
            publication_channel="productreview",
            destination_key=f"simulation-{suffix}",
            operation_mode="manual",
            destination_account_id=None,
            canonical_url="https://www.productreview.com.au/",
        )
        bindings = application.install_default_prompt_catalog(
            project_id=ids["project"], actor_id=ids["owner"]
        )
        release_id = next(
            item["template_release_id"]
            for item in bindings
            if item["task_key"] == "productreview"
        )
        simulation, job = application.create_prompt_simulation(
            project_id=ids["project"],
            destination_id=destination.id,
            template_release_id=release_id,
            primary_brand_entity_id=brand_id,
            product_entity_id=ids["entity"],
            authenticity_mode="synthetic_testimonial",
            evidence_item_ids=(evidence_id,),
            goals={"deliverable": "native ProductReview technical preview"},
            constraints={"locale": "en-AU"},
            variables={},
            model_policy_hash="a" * 64,
            configured_model="deepseek-v4-flash",
            model_call_budget=1,
            requested_by=ids["owner"],
            idempotency_key=f"simulation-create-{suffix}",
        )
        replayed, replayed_job = application.create_prompt_simulation(
            project_id=ids["project"],
            destination_id=destination.id,
            template_release_id=release_id,
            primary_brand_entity_id=brand_id,
            product_entity_id=ids["entity"],
            authenticity_mode="synthetic_testimonial",
            evidence_item_ids=(evidence_id,),
            goals={"deliverable": "native ProductReview technical preview"},
            constraints={"locale": "en-AU"},
            variables={},
            model_policy_hash="a" * 64,
            configured_model="deepseek-v4-flash",
            model_call_budget=1,
            requested_by=ids["owner"],
            idempotency_key=f"simulation-create-{suffix}",
        )
        assert (replayed.id, replayed_job.id) == (simulation.id, job.id)
        assert simulation.test_only is True
        assert simulation.publication_eligible is False
        assert simulation.authenticity_mode == "synthetic_testimonial"
        assert simulation.destination_policy_version_id is None

        store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
        repository = PlacementWorkerRepository(store)
        generated = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "prompt_simulation.generate": PromptSimulationHandler(
                    store=store,
                    repository=repository,
                    gateway=FakeGateway(evidence_id),
                    lease_for=_lease(),
                )
            },
            worker_id=f"simulation-generation-{suffix}",
            lease_for=_lease(),
        ).process(job_id=job.id, project_id=ids["project"])
        assert generated["status"] == "succeeded"
        assert generated["test_only"] is True
        assert generated["publication_eligible"] is False

        artifact_job_id = _artifact_job(store, ids["project"], simulation.id)
        finalized = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "artifact.finalize": ArtifactFinalizeHandler(
                    store=store,
                    repository=PlacementArtifactRepository(store),
                    object_store=artifact_store,
                )
            },
            worker_id=f"simulation-artifact-{suffix}",
            lease_for=_lease(),
        ).process(job_id=artifact_job_id, project_id=ids["project"])
        assert finalized["status"] == "finalized"

        detail = application.get_prompt_simulation(
            project_id=ids["project"], simulation_id=simulation.id
        )
        assert detail is not None
        assert detail.generation_status == "succeeded"
        assert detail.artifact_status == "finalized"
        assert detail.artifact_manifest is not None
        assert detail.artifact_manifest["test_only"] is True
        assert detail.artifact_manifest["publication_eligible"] is False
        assert detail.input_snapshot is not None
        assert detail.input_snapshot["authenticity_mode"] == "synthetic_testimonial"
        assert detail.artifact_manifest["authenticity_mode"] == "synthetic_testimonial"
        downloaded = application.download_prompt_simulation_artifact(
            project_id=ids["project"], simulation_id=simulation.id
        )
        assert downloaded.content_hash == detail.manifest_hash

        with psycopg.connect(ADMIN_URL) as admin:
            counts = admin.execute(
                """SELECT
                     (SELECT count(*) FROM placement_packages WHERE project_id = %s),
                     (SELECT count(*) FROM placement_reviews WHERE project_id = %s),
                     (SELECT count(*) FROM placement_export_receipts WHERE project_id = %s),
                     (SELECT count(*) FROM publication_requests WHERE project_id = %s),
                     (SELECT count(*) FROM publication_submissions WHERE project_id = %s)""",
                (ids["project"],) * 5,
            ).fetchone()
        assert counts == (0, 0, 0, 0, 0)
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[ids],
                tenant_ids=[ids["tenant"]],
                app_login=app_login,
                worker_login=worker_login,
            )


def _lease():
    from datetime import timedelta

    return timedelta(seconds=30)


def _artifact_job(store, project_id, simulation_id):
    connection = store.open_project(project_id)
    try:
        row = connection.execute(
            """SELECT job_id FROM artifact_finalize_outbox
               WHERE project_id = %s AND resource_kind = 'prompt_simulation'
                 AND resource_id = %s""",
            (project_id, simulation_id),
        ).fetchone()
        connection.commit()
    finally:
        connection.close()
    assert row is not None
    return row[0]
