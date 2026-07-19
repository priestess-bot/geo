from __future__ import annotations

from datetime import timedelta
import os
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.knowledge import KnowledgeApplication
from geo_core.placements.application import PlacementApplication
from geo_core.placements.artifact_worker import PlacementArtifactRepository
from geo_core.placements.domain import PlacementRuleViolation
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.placements.worker_composition import (
    ArtifactFinalizeHandler,
    EvidencePackHandler,
    GenerationHandler,
    PlacementWorkerDispatcher,
    PublicationVerificationHandler,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository
from tests.integration.placement_worker_support import (
    FakeGateway,
    FakeVerifier,
    MemoryArtifactStore,
    cleanup_projects,
    login_url,
    seed_frozen_protocol,
    seed_project,
)
from tests.integration.test_knowledge_fact_evidence_postgres import (
    _promote,
    _seed_brief,
    _seed_knowledge_chain,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_retired_fact_blocks_new_package_effects_but_keeps_publication_audit() -> None:
    suffix = uuid4().hex[:10]
    app_login, worker_login = f"geo_publish_app_{suffix}", f"geo_publish_worker_{suffix}"
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
        project = seed_project(admin, suffix=f"publication-currency-{suffix}")
        lineage = _seed_knowledge_chain(admin, project)
        contexts = tuple(
            _seed_context(admin, project, suffix=f"{suffix}-{label}")
            for label in ("approval", "request", "verification")
        )
        monitoring_query_id = uuid4()
        admin.execute(
            """INSERT INTO monitoring_queries
                 (id, project_id, market_profile_id, query_text, query_kind, locale)
               VALUES (%s, %s, %s, 'publication currency query',
                       'recommendation', 'en-AU')""",
            (monitoring_query_id, project["project"], project["market"]),
        )
        seed_frozen_protocol(
            admin,
            project_id=project["project"],
            campaign_id=contexts[2]["campaign_id"],
            market_profile_id=project["market"],
            monitoring_query_id=monitoring_query_id,
            actor_id=project["owner"],
        )
        admin.commit()

    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    principal = AccessPrincipal(
        identity_id=project["owner"],
        actor_id=f"publication-currency-{suffix}",
        tenant_id=project["tenant"],
        memberships=(MembershipRecord(project["project"], project["tenant"], "admin"),),
        auth_method="development",
    )
    knowledge = KnowledgeApplication(app_url)
    placements = PlacementApplication(placement_uow_factory(lambda: psycopg.connect(app_url)))
    store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
    repository = PlacementWorkerRepository(store)
    object_store = MemoryArtifactStore()
    object_store.fail_next = False
    try:
        promoted = _promote(
            knowledge,
            principal,
            project,
            lineage["fact"],
            idempotency_key=f"publication-currency-evidence-{suffix}",
        )
        evidence_id = UUID(str(promoted["evidence"]["id"]))
        release = _install_prompt_release(placements, project)
        bindings = tuple(
            _bind_context(
                placements,
                project=project,
                context=context,
                release=release,
                suffix=suffix,
            )
            for context in contexts
        )
        dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "evidence_pack.build": EvidencePackHandler(repository),
                "artifact.finalize": ArtifactFinalizeHandler(
                    store=store,
                    repository=PlacementArtifactRepository(store),
                    object_store=object_store,
                ),
                "placement.generate": GenerationHandler(
                    store=store,
                    repository=repository,
                    gateway=FakeGateway(evidence_id),
                    lease_for=timedelta(seconds=30),
                ),
                "publication.verify": PublicationVerificationHandler(
                    store=store,
                    repository=repository,
                    verifier=FakeVerifier(),
                    lease_for=timedelta(seconds=30),
                ),
            },
            worker_id=f"publication-currency-worker-{suffix}",
            lease_for=timedelta(seconds=30),
        )
        versions = tuple(
            _generate_package(
                placements,
                dispatcher=dispatcher,
                project=project,
                context=context,
                binding=binding,
                release=release,
                suffix=f"{suffix}-{index}",
            )
            for index, (context, binding) in enumerate(zip(contexts, bindings, strict=True))
        )

        _submit_for_review(placements, project, contexts[0], versions[0])
        for context, version in zip(contexts[1:], versions[1:], strict=True):
            _submit_for_review(placements, project, context, version)
            _approve(placements, project, context, version)

        historical_export = placements.export_package(
            project_id=project["project"],
            campaign_id=contexts[2]["campaign_id"],
            version_id=versions[2],
            requested_by=project["owner"],
        )
        _finalize_export(dispatcher, project["project"], historical_export.id)
        publication = placements.request_publication(
            project_id=project["project"],
            campaign_id=contexts[2]["campaign_id"],
            version_id=versions[2],
            destination_id=contexts[2]["destination_id"],
            requested_by=project["owner"],
            publication_attempt=1,
            idempotency_key=f"publication-currency-request-{suffix}",
            restricted_policy_acknowledged=False,
            policy_basis=None,
        )
        submission = placements.create_submission(
            project_id=project["project"],
            campaign_id=contexts[2]["campaign_id"],
            publication_request_id=publication.id,
            submitted_url="https://source.example/published",
            provider_submission_id=None,
            idempotency_key=f"publication-currency-submission-{suffix}",
            submitted_by=project["owner"],
        )
        verification_job = placements.request_verification(
            project_id=project["project"],
            campaign_id=contexts[2]["campaign_id"],
            submission_id=submission.id,
            idempotency_key=f"publication-currency-verification-{suffix}",
        )

        knowledge.disable_chunk(
            principal,
            project_id=project["project"],
            chunk_id=lineage["chunk"],
        )

        with pytest.raises(PlacementRuleViolation, match="current approved Fact Evidence"):
            _approve(placements, project, contexts[0], versions[0])
        assert (
            placements.list_reviews(
                project_id=project["project"],
                campaign_id=contexts[0]["campaign_id"],
                version_id=versions[0],
            )
            == ()
        )

        with pytest.raises(PlacementRuleViolation, match="current approved Fact Evidence"):
            placements.request_publication(
                project_id=project["project"],
                campaign_id=contexts[1]["campaign_id"],
                version_id=versions[1],
                destination_id=contexts[1]["destination_id"],
                requested_by=project["owner"],
                publication_attempt=1,
                idempotency_key=f"publication-currency-blocked-{suffix}",
                restricted_policy_acknowledged=False,
                policy_basis=None,
            )
        with pytest.raises(PlacementRuleViolation, match="current approved Fact Evidence"):
            placements.export_package(
                project_id=project["project"],
                campaign_id=contexts[2]["campaign_id"],
                version_id=versions[2],
                requested_by=project["owner"],
            )

        assert (
            dispatcher.process(job_id=verification_job.id, project_id=project["project"])["status"]
            == "verification_failed"
        )
        attempts = placements.list_verification_attempts(
            project_id=project["project"],
            campaign_id=contexts[2]["campaign_id"],
            submission_id=submission.id,
        )
        assert len(attempts) == 1
        assert attempts[0].outcome == "failed"
        assert attempts[0].error_code == "lineage_stale"
        assert attempts[0].status_code == 200
        assert attempts[0].final_url == "https://source.example/published"
        assert attempts[0].failures == (
            {
                "code": "lineage_stale",
                "disposition": "permanent",
                "check": "input_contract",
                "retryable": False,
            },
        )
        stored_submission = placements.get_submission(
            project_id=project["project"],
            campaign_id=contexts[2]["campaign_id"],
            submission_id=submission.id,
        )
        assert stored_submission is not None
        assert stored_submission.status == "failed"
        assert stored_submission.verification_result["success"] is False
        assert stored_submission.verification_result["lineage_current"] is False
        assert (
            placements.list_publication_requests(
                project_id=project["project"],
                campaign_id=contexts[2]["campaign_id"],
                version_id=versions[2],
            )[0].status
            == "failed"
        )

        assert (
            placements.get_package_version(
                project_id=project["project"],
                campaign_id=contexts[2]["campaign_id"],
                version_id=versions[2],
            )
            is not None
        )
        assert (
            len(
                placements.list_reviews(
                    project_id=project["project"],
                    campaign_id=contexts[2]["campaign_id"],
                    version_id=versions[2],
                )
            )
            == 1
        )
        exports = placements.list_exports(
            project_id=project["project"],
            campaign_id=contexts[2]["campaign_id"],
            version_id=versions[2],
        )
        assert len(exports) == 1
        assert exports[0].id == historical_export.id
        assert exports[0].artifact_status == "finalized"
        with psycopg.connect(ADMIN_URL) as admin:
            assert (
                admin.execute(
                    """SELECT count(*) FROM measurement_job_specs
                   WHERE project_id = %s AND submission_id = %s""",
                    (project["project"], submission.id),
                ).fetchone()[0]
                == 0
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


def _seed_context(
    connection: psycopg.Connection[Any], project: dict[str, UUID], *, suffix: str
) -> dict[str, UUID]:
    campaign_id, brief_version_id = _seed_brief(connection, project, suffix)
    opportunity_id, destination_id = connection.execute(
        """SELECT opportunity_id, destination_id FROM placement_brief_versions
           WHERE project_id = %s AND id = %s""",
        (project["project"], brief_version_id),
    ).fetchone()
    return {
        "campaign_id": campaign_id,
        "brief_version_id": brief_version_id,
        "opportunity_id": opportunity_id,
        "destination_id": destination_id,
    }


def _install_prompt_release(placements: PlacementApplication, project: dict[str, UUID]) -> Any:
    catalog = placements.install_default_prompt_catalog(
        project_id=project["project"], actor_id=project["owner"]
    )
    release_id = next(
        item["template_release_id"] for item in catalog if item["task_key"] == "owned_site"
    )
    return next(
        release
        for skill in placements.list_prompt_skills(project_id=project["project"])
        for release in placements.list_prompt_releases(
            project_id=project["project"], skill_id=skill.id
        )
        if release.id == release_id
    )


def _bind_context(
    placements: PlacementApplication,
    *,
    project: dict[str, UUID],
    context: dict[str, UUID],
    release: Any,
    suffix: str,
) -> Any:
    placements.review_destination_policy(
        project_id=project["project"],
        destination_id=context["destination_id"],
        status="approved",
        rules={"brand_participation": "disclosed"},
        identity_requirements={},
        disclosure_requirements={},
        allowed_hosts=("source.example",),
        reviewed_by=project["owner"],
    )
    return placements.bind_opportunity_prompt_release(
        project_id=project["project"],
        campaign_id=context["campaign_id"],
        opportunity_id=context["opportunity_id"],
        release_id=release.id,
        expected_binding_version=1,
        reason="freeze publication currency regression Release",
        actor_id=project["owner"],
        idempotency_key=f"publication-currency-binding-{context['opportunity_id']}-{suffix}",
    )


def _generate_package(
    placements: PlacementApplication,
    *,
    dispatcher: PlacementWorkerDispatcher,
    project: dict[str, UUID],
    context: dict[str, UUID],
    binding: Any,
    release: Any,
    suffix: str,
) -> UUID:
    pack, pack_job = placements.create_evidence_attempt(
        project_id=project["project"],
        campaign_id=context["campaign_id"],
        brief_version_id=context["brief_version_id"],
        idempotency_key=f"publication-currency-pack-{suffix}",
    )
    assert dispatcher.process(job_id=pack_job.id, project_id=project["project"])["status"] == (
        "ready"
    )
    bundle = placements.create_prompt_bundle(
        project_id=project["project"],
        campaign_id=context["campaign_id"],
        opportunity_id=context["opportunity_id"],
        brief_version_id=context["brief_version_id"],
        evidence_pack_attempt_id=pack.id,
        prompt_release_binding_id=binding.id,
        confirmed_release_hash=release.release_hash,
        variables={},
        model_policy_hash="a" * 64,
        idempotency_key=f"publication-currency-bundle-{suffix}",
        requested_by=project["owner"],
    )
    with psycopg.connect(ADMIN_URL) as admin:
        artifact_job_id = admin.execute(
            """SELECT job_id FROM artifact_finalize_outbox
               WHERE project_id = %s AND resource_kind = 'prompt_bundle'
                 AND resource_id = %s""",
            (project["project"], bundle.id),
        ).fetchone()[0]
    assert (
        dispatcher.process(job_id=artifact_job_id, project_id=project["project"])["status"]
        == "finalized"
    )
    generation_job = placements.request_generation(
        project_id=project["project"],
        campaign_id=context["campaign_id"],
        prompt_bundle_id=bundle.id,
        configured_model="deepseek-v4-flash",
        model_call_budget=1,
        idempotency_key=f"publication-currency-generation-{suffix}",
        requested_by=project["owner"],
    )
    result = dispatcher.process(job_id=generation_job.id, project_id=project["project"])
    assert result["status"] == "succeeded", result
    return UUID(str(result["package_version_id"]))


def _submit_for_review(
    placements: PlacementApplication,
    project: dict[str, UUID],
    context: dict[str, UUID],
    version_id: UUID,
) -> None:
    placements.submit_for_review(
        project_id=project["project"],
        campaign_id=context["campaign_id"],
        version_id=version_id,
        submitted_by=project["owner"],
    )


def _approve(
    placements: PlacementApplication,
    project: dict[str, UUID],
    context: dict[str, UUID],
    version_id: UUID,
) -> None:
    placements.submit_review(
        project_id=project["project"],
        campaign_id=context["campaign_id"],
        version_id=version_id,
        reviewer_id=project["reviewer"],
        decision="approved",
        claim_inventory_complete=True,
        extracted_claim_support_confirmed=True,
        score=95,
        notes="publication currency regression approval",
    )


def _finalize_export(
    dispatcher: PlacementWorkerDispatcher, project_id: UUID, export_id: UUID
) -> None:
    with psycopg.connect(ADMIN_URL) as admin:
        job_id = admin.execute(
            """SELECT job_id FROM artifact_finalize_outbox
               WHERE project_id = %s AND resource_kind = 'package_export'
                 AND resource_id = %s""",
            (project_id, export_id),
        ).fetchone()[0]
    assert dispatcher.process(job_id=job_id, project_id=project_id)["status"] == "finalized"
