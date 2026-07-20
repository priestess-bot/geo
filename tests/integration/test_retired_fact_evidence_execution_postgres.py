from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import os
from threading import Event
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.catalog.domain import Confidentiality, PublicCitation, SubjectRole, UsageRights
from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.knowledge import KnowledgeApplication
from geo_core.model_gateway import ModelGatewayResult
from geo_core.placements.application import PlacementApplication
from geo_core.placements.artifact_worker import PlacementArtifactRepository
from geo_core.placements.domain import PlacementConflict, PlacementRuleViolation
from geo_core.placements import evidence_worker_repository as evidence_repository_module
from geo_core.placements.ports import GeneratedPlacement
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.placements.simulation_worker import PromptSimulationHandler
from geo_core.placements.worker_composition import (
    ArtifactFinalizeHandler,
    GenerationHandler,
    PlacementWorkerDispatcher,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository
from tests.integration.placement_worker_support import (
    FakeGateway,
    cleanup_projects,
    login_url,
    seed_project,
)
from tests.integration.test_knowledge_fact_evidence_postgres import (
    _seed_brief,
    _seed_knowledge_chain,
)
from tests.integration.test_knowledge_rag_postgres import (
    _dispatcher,
    _object_store,
    _principal,
    _process_source,
    _source,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
MINIO_ENDPOINT = os.getenv("GEO_F019_TEST_MINIO_ENDPOINT", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
    pytest.mark.skipif(not MINIO_ENDPOINT, reason="GEO_F019_TEST_MINIO_ENDPOINT is required"),
]


def test_pack_freeze_rolls_back_when_fact_retires_after_eligibility_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    app_login, worker_login = f"geo_pack_race_app_{suffix}", f"geo_pack_race_worker_{suffix}"
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
        project = seed_project(admin, suffix=f"pack-race-{suffix}")
        lineage = _seed_knowledge_chain(admin, project)
        campaign_id, brief_version_id = _seed_brief(admin, project, suffix)
        admin.commit()

    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    knowledge = KnowledgeApplication(app_url)
    placements = PlacementApplication(placement_uow_factory(lambda: psycopg.connect(app_url)))
    principal = _principal(project, suffix)
    try:
        knowledge.promote_fact_to_evidence(
            principal,
            project_id=project["project"],
            fact_id=lineage["fact"],
            idempotency_key=f"pack-race-evidence-{suffix}",
            title="Pack race Evidence",
            subject_entity_id=None,
            subject_role=SubjectRole.NEUTRAL,
            usage_rights=UsageRights.OWNED,
            confidentiality=Confidentiality.INTERNAL,
            public_citation=PublicCitation(disclosure_allowed=False),
        )
        pack, job = placements.create_evidence_attempt(
            project_id=project["project"],
            campaign_id=campaign_id,
            brief_version_id=brief_version_id,
            idempotency_key=f"pack-race-{suffix}",
        )
        selected, retired = Event(), Event()
        original = evidence_repository_module.approved_fact_evidence_is_current

        def gated_current_check(db, *, project_id, evidence_ids):
            selected.set()
            if not retired.wait(timeout=10):
                raise AssertionError("Fact retirement did not reach the Pack freeze barrier")
            return original(
                db,
                project_id=project_id,
                evidence_ids=evidence_ids,
            )

        monkeypatch.setattr(
            evidence_repository_module,
            "approved_fact_evidence_is_current",
            gated_current_check,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _dispatcher(worker_url, suffix).process,
                job_id=job.id,
                project_id=project["project"],
            )
            assert selected.wait(timeout=10)
            with psycopg.connect(ADMIN_URL) as admin:
                admin.execute(
                    """UPDATE knowledge_fact_candidates
                       SET lifecycle_status = 'superseded'
                       WHERE project_id = %s AND id = %s""",
                    (project["project"], lineage["fact"]),
                )
                admin.execute(
                    """UPDATE knowledge_chunks SET status = 'disabled'
                       WHERE project_id = %s AND id = %s""",
                    (project["project"], lineage["chunk"]),
                )
                admin.commit()
            retired.set()
            result = future.result(timeout=15)
        assert result["status"] == "retry_wait"
        with psycopg.connect(ADMIN_URL) as admin:
            state = admin.execute(
                """SELECT attempt.status, job.status,
                          (SELECT count(*) FROM evidence_pack_items item
                           WHERE item.project_id = attempt.project_id
                             AND item.pack_attempt_id = attempt.id)
                   FROM evidence_pack_attempts attempt
                   JOIN evidence_pack_job_specs spec
                     ON spec.evidence_pack_attempt_id = attempt.id
                    AND spec.project_id = attempt.project_id
                   JOIN durable_jobs job
                     ON job.id = spec.job_id AND job.project_id = spec.project_id
                   WHERE attempt.id = %s AND attempt.project_id = %s""",
                (pack.id, project["project"]),
            ).fetchone()
        assert state == ("building", "retry_wait", 0)
    finally:
        retired.set()
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[project],
                tenant_ids=[project["tenant"]],
                app_login=app_login,
                worker_login=worker_login,
            )
            admin.commit()


def test_reprocess_keeps_history_but_blocks_all_stale_evidence_execution() -> None:
    suffix = uuid4().hex[:10]
    app_login, worker_login = f"geo_stale_app_{suffix}", f"geo_stale_worker_{suffix}"
    app_password, worker_password = uuid4().hex, uuid4().hex
    brand_id = uuid4()
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
        project = seed_project(admin, suffix=f"stale-execution-{suffix}")
        campaign_id, brief_version_id = _seed_brief(admin, project, suffix)
        admin.execute(
            """INSERT INTO product_entities
                 (id, project_id, entity_type, canonical_name)
               VALUES (%s, %s, 'brand', %s)""",
            (brand_id, project["project"], f"Stale execution brand {suffix}"),
        )
        opportunity_id, destination_id = admin.execute(
            """SELECT opportunity_id, destination_id FROM placement_brief_versions
               WHERE id = %s AND project_id = %s""",
            (brief_version_id, project["project"]),
        ).fetchone()
        admin.commit()

    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    knowledge = KnowledgeApplication(app_url)
    placements = PlacementApplication(placement_uow_factory(lambda: psycopg.connect(app_url)))
    dispatcher = _dispatcher(worker_url, suffix)
    store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
    repository = PlacementWorkerRepository(store)
    principal = _principal(project, suffix)
    try:
        release, binding = _prepare_prompt_context(
            placements,
            project=project,
            campaign_id=campaign_id,
            opportunity_id=opportunity_id,
            destination_id=destination_id,
            suffix=suffix,
        )
        created = knowledge.create_source(
            principal,
            project_id=project["project"],
            source=_source("每分钟 2 升"),
            idempotency_key=f"stale-source-{suffix}",
        )
        first = _process_source(dispatcher, created, project["project"])
        fact = next(
            item
            for item in knowledge.list_facts(principal, project_id=project["project"])
            if item["pipeline_run_id"] == first["run_id"] and item["lifecycle_status"] == "active"
        )
        knowledge.review_fact(
            principal,
            project_id=project["project"],
            fact_id=fact["id"],
            decision="approved",
            notes="approve before stale execution regression",
        )
        promoted = knowledge.promote_fact_to_evidence(
            principal,
            project_id=project["project"],
            fact_id=fact["id"],
            idempotency_key=f"stale-evidence-{suffix}",
            title="Stale execution Evidence",
            subject_entity_id=None,
            subject_role=SubjectRole.NEUTRAL,
            usage_rights=UsageRights.OWNED,
            confidentiality=Confidentiality.INTERNAL,
            public_citation=PublicCitation(disclosure_allowed=False),
        )
        evidence_id = promoted["evidence"]["id"]
        pack, pack_job = placements.create_evidence_attempt(
            project_id=project["project"],
            campaign_id=campaign_id,
            brief_version_id=brief_version_id,
            idempotency_key=f"stale-pack-{suffix}",
        )
        assert dispatcher.process(job_id=pack_job.id, project_id=project["project"])["status"] == (
            "ready"
        )
        bundle = placements.create_prompt_bundle(
            project_id=project["project"],
            campaign_id=campaign_id,
            opportunity_id=opportunity_id,
            brief_version_id=brief_version_id,
            evidence_pack_attempt_id=pack.id,
            prompt_release_binding_id=binding.id,
            confirmed_release_hash=release.release_hash,
            variables={},
            model_policy_hash="a" * 64,
            idempotency_key=f"stale-bundle-{suffix}",
            requested_by=project["owner"],
        )
        _finalize_bundle(
            store=store,
            bundle_id=bundle.id,
            project_id=project["project"],
            suffix=suffix,
        )

        finalize_job = _request_generation(
            placements, project, campaign_id, bundle.id, f"stale-finalize-{suffix}"
        )
        load_job = _request_generation(
            placements, project, campaign_id, bundle.id, f"stale-load-{suffix}"
        )
        finalize_lease = store.claim(
            job_id=finalize_job.id,
            project_id=project["project"],
            expected_kind="placement.generate",
            worker_id=f"stale-finalize-{suffix}",
            lease_for=timedelta(minutes=5),
        ).lease
        assert finalize_lease is not None
        generation_claim = repository.load_generation(finalize_lease)

        finalize_simulation, finalize_simulation_job = _create_simulation(
            placements,
            project=project,
            campaign_id=campaign_id,
            opportunity_id=opportunity_id,
            destination_id=destination_id,
            binding_id=binding.id,
            release_hash=release.release_hash,
            brand_id=brand_id,
            evidence_id=evidence_id,
            key=f"stale-simulation-finalize-{suffix}",
        )
        _, load_simulation_job = _create_simulation(
            placements,
            project=project,
            campaign_id=campaign_id,
            opportunity_id=opportunity_id,
            destination_id=destination_id,
            binding_id=binding.id,
            release_hash=release.release_hash,
            brand_id=brand_id,
            evidence_id=evidence_id,
            key=f"stale-simulation-load-{suffix}",
        )
        simulation_lease = store.claim(
            job_id=finalize_simulation_job.id,
            project_id=project["project"],
            expected_kind="prompt_simulation.generate",
            worker_id=f"stale-simulation-finalize-{suffix}",
            lease_for=timedelta(minutes=5),
        ).lease
        assert simulation_lease is not None
        simulation_claim = repository.load_prompt_simulation(simulation_lease)

        reprocessed = knowledge.reprocess_source(
            principal,
            project_id=project["project"],
            source_id=first["source_id"],
            idempotency_key=f"stale-reprocess-{suffix}",
        )
        _process_source(dispatcher, reprocessed, project["project"])

        with pytest.raises(PlacementConflict, match="no longer active"):
            placements.create_prompt_bundle(
                project_id=project["project"],
                campaign_id=campaign_id,
                opportunity_id=opportunity_id,
                brief_version_id=brief_version_id,
                evidence_pack_attempt_id=pack.id,
                prompt_release_binding_id=binding.id,
                confirmed_release_hash=release.release_hash,
                variables={},
                model_policy_hash="a" * 64,
                idempotency_key=f"stale-bundle-after-{suffix}",
                requested_by=project["owner"],
            )
        with pytest.raises(PlacementConflict, match="no longer active"):
            _request_generation(
                placements, project, campaign_id, bundle.id, f"stale-enqueue-after-{suffix}"
            )

        placement_gateway = FakeGateway(evidence_id)
        placement_result = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "placement.generate": GenerationHandler(
                    store=store,
                    repository=repository,
                    gateway=placement_gateway,
                    lease_for=timedelta(seconds=30),
                )
            },
            worker_id=f"stale-generation-load-{suffix}",
            lease_for=timedelta(seconds=30),
        ).process(job_id=load_job.id, project_id=project["project"])
        assert placement_result["status"] == "failed"
        assert placement_gateway.requests == []

        generated, model_result = _stale_result(evidence_id)
        with pytest.raises(PlacementRuleViolation, match="became stale"):
            repository.finalize_generation(
                finalize_lease, generation_claim, generated, model_result
            )
        _fail_claim(store, finalize_lease)

        with pytest.raises(PlacementRuleViolation, match="no longer active"):
            _create_simulation(
                placements,
                project=project,
                campaign_id=campaign_id,
                opportunity_id=opportunity_id,
                destination_id=destination_id,
                binding_id=binding.id,
                release_hash=release.release_hash,
                brand_id=brand_id,
                evidence_id=evidence_id,
                key=f"stale-simulation-after-{suffix}",
            )
        simulation_gateway = FakeGateway(evidence_id)
        simulation_result = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "prompt_simulation.generate": PromptSimulationHandler(
                    store=store,
                    repository=repository,
                    gateway=simulation_gateway,
                    lease_for=timedelta(seconds=30),
                )
            },
            worker_id=f"stale-simulation-load-{suffix}",
            lease_for=timedelta(seconds=30),
        ).process(job_id=load_simulation_job.id, project_id=project["project"])
        assert simulation_result["status"] == "failed"
        assert simulation_gateway.requests == []
        with pytest.raises(PlacementRuleViolation, match="became stale"):
            repository.finalize_prompt_simulation(
                simulation_lease, simulation_claim, generated, model_result
            )
        _fail_claim(store, simulation_lease)

        assert (
            placements.get_prompt_bundle(
                project_id=project["project"], campaign_id=campaign_id, bundle_id=bundle.id
            )
            is not None
        )
        assert (
            placements.get_prompt_simulation(
                project_id=project["project"],
                campaign_id=campaign_id,
                simulation_id=finalize_simulation.id,
            )
            is not None
        )
        _assert_history_preserved(
            project_id=project["project"],
            fact_id=fact["id"],
            evidence_id=evidence_id,
            pack_id=pack.id,
            bundle_id=bundle.id,
        )
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[project],
                tenant_ids=[project["tenant"]],
                app_login=app_login,
                worker_login=worker_login,
            )
            admin.commit()


def _prepare_prompt_context(
    placements: PlacementApplication,
    *,
    project: dict[str, UUID],
    campaign_id: UUID,
    opportunity_id: UUID,
    destination_id: UUID,
    suffix: str,
):
    placements.review_destination_policy(
        project_id=project["project"],
        destination_id=destination_id,
        status="approved",
        rules={"brand_participation": "disclosed"},
        identity_requirements={},
        disclosure_requirements={},
        allowed_hosts=("source.example",),
        reviewed_by=project["owner"],
    )
    catalog = placements.install_default_prompt_catalog(
        project_id=project["project"], actor_id=project["owner"]
    )
    release_id = next(
        item["template_release_id"] for item in catalog if item["task_key"] == "owned_site"
    )
    release = next(
        release
        for skill in placements.list_prompt_skills(project_id=project["project"])
        for release in placements.list_prompt_releases(
            project_id=project["project"], skill_id=skill.id
        )
        if release.id == release_id
    )
    binding = placements.bind_opportunity_prompt_release(
        project_id=project["project"],
        campaign_id=campaign_id,
        opportunity_id=opportunity_id,
        release_id=release.id,
        expected_binding_version=1,
        reason="freeze stale execution regression Release",
        actor_id=project["owner"],
        idempotency_key=f"stale-binding-{suffix}",
    )
    return release, binding


def _request_generation(
    placements: PlacementApplication,
    project: dict[str, UUID],
    campaign_id: UUID,
    bundle_id: UUID,
    key: str,
):
    return placements.request_generation(
        project_id=project["project"],
        campaign_id=campaign_id,
        prompt_bundle_id=bundle_id,
        configured_model="deepseek-v4-flash",
        model_call_budget=1,
        idempotency_key=key,
        requested_by=project["owner"],
    )


def _create_simulation(
    placements: PlacementApplication,
    *,
    project: dict[str, UUID],
    campaign_id: UUID,
    opportunity_id: UUID,
    destination_id: UUID,
    binding_id: UUID,
    release_hash: str,
    brand_id: UUID,
    evidence_id: UUID,
    key: str,
):
    return placements.create_prompt_simulation(
        project_id=project["project"],
        campaign_id=campaign_id,
        opportunity_id=opportunity_id,
        destination_id=destination_id,
        prompt_release_binding_id=binding_id,
        confirmed_release_hash=release_hash,
        primary_brand_entity_id=brand_id,
        product_entity_id=project["entity"],
        authenticity_mode="brand_authored",
        evidence_item_ids=(evidence_id,),
        goals={"deliverable": "stale execution regression"},
        constraints={},
        variables={},
        model_policy_hash="b" * 64,
        configured_model="deepseek-v4-flash",
        model_call_budget=1,
        requested_by=project["owner"],
        idempotency_key=key,
    )


def _finalize_bundle(
    *, store: PostgresDurableJobStore, bundle_id: UUID, project_id: UUID, suffix: str
) -> None:
    with psycopg.connect(ADMIN_URL) as admin:
        job_id = admin.execute(
            """SELECT job_id FROM artifact_finalize_outbox
               WHERE project_id = %s AND resource_kind = 'prompt_bundle'
                 AND resource_id = %s""",
            (project_id, bundle_id),
        ).fetchone()[0]
    result = PlacementWorkerDispatcher(
        store=store,
        handlers={
            "artifact.finalize": ArtifactFinalizeHandler(
                store=store,
                repository=PlacementArtifactRepository(store),
                object_store=_object_store(suffix),
            )
        },
        worker_id=f"stale-artifact-{suffix}",
        lease_for=timedelta(seconds=30),
    ).process(job_id=job_id, project_id=project_id)
    assert result["status"] == "finalized", result


def _stale_result(evidence_id: UUID) -> tuple[GeneratedPlacement, ModelGatewayResult]:
    generated = GeneratedPlacement(
        content_json={},
        rendered_text="This result must not be persisted after its Evidence retires.",
        claims=(),
        internal_evidence_refs=(evidence_id,),
        public_citation_refs=(),
    )
    result = ModelGatewayResult(
        output={},
        call_log_id=uuid4(),
        provider_request_id="stale-result",
        configured_model="deepseek-v4-flash",
        provider_reported_model="deepseek-v4-flash",
        prompt_tokens=1,
        completion_tokens=1,
        cost_usd=Decimal("0.001"),
        finish_reason="stop",
        response_hash="c" * 64,
    )
    return generated, result


def _fail_claim(store: PostgresDurableJobStore, lease) -> None:
    assert (
        store.fail(
            lease,
            error_code="stale_execution_test",
            details={"message": "expected stale execution rejection"},
            retry_delay=None,
        )
        == "failed"
    )


def _assert_history_preserved(
    *, project_id: UUID, fact_id: UUID, evidence_id: UUID, pack_id: UUID, bundle_id: UUID
) -> None:
    with psycopg.connect(ADMIN_URL) as admin:
        row = admin.execute(
            """SELECT
                 (SELECT count(*) FROM knowledge_fact_candidates
                  WHERE project_id = %s AND id = %s AND lifecycle_status = 'superseded'),
                 (SELECT count(*) FROM evidence_items
                  WHERE project_id = %s AND id = %s),
                 (SELECT count(*) FROM knowledge_fact_evidence_lineages
                  WHERE project_id = %s AND knowledge_fact_id = %s
                    AND evidence_item_id = %s),
                 (SELECT count(*) FROM evidence_pack_items
                  WHERE project_id = %s AND pack_attempt_id = %s
                    AND evidence_item_id = %s),
                 (SELECT count(*) FROM prompt_bundles
                  WHERE project_id = %s AND id = %s)""",
            (
                project_id,
                fact_id,
                project_id,
                evidence_id,
                project_id,
                fact_id,
                evidence_id,
                project_id,
                pack_id,
                evidence_id,
                project_id,
                bundle_id,
            ),
        ).fetchone()
    assert row == (1, 1, 1, 1, 1)
