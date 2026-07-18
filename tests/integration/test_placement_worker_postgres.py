from __future__ import annotations

from datetime import timedelta
import os
import time
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.placements.application import PlacementApplication
from geo_core.placements.artifact_worker import PlacementArtifactRepository
from geo_core.placements.domain import (
    ConsumerExperience, PlacementConflict, PlacementRuleViolation,
)
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.placements.ports import GeneratedClaim
from geo_core.placements.worker_composition import (
    ArtifactFinalizeHandler,
    EvidencePackHandler,
    GenerationHandler,
    MeasurementWindowHandler,
    PlacementWorkerDispatcher,
    PublicationVerificationHandler,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository
from tests.integration.placement_worker_support import (
    assert_run_scoped_outbox_delivery,
    cleanup_projects,
    FakeGateway,
    FakeVerifier,
    MemoryArtifactStore,
    PermanentVerifier,
    RetryableGateway,
    login_url,
    seed_frozen_protocol,
    seed_project,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()


@pytest.mark.integration
@pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required")
def test_multi_project_crash_recovery_and_full_worker_chain() -> None:
    suffix = uuid4().hex[:10]
    app_login, worker_login = f"geo_app_it_{suffix}", f"geo_worker_it_{suffix}"
    app_password, worker_password = uuid4().hex, uuid4().hex
    tenants: list[UUID] = []
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
        projects = [seed_project(admin, suffix=f"{suffix}-{index}") for index in range(2)]
        tenants.extend(item["tenant"] for item in projects)
        admin.commit()
    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    artifact_store = MemoryArtifactStore()
    application = PlacementApplication(
        placement_uow_factory(lambda: psycopg.connect(app_url)),
        artifact_reader=artifact_store,
    )
    records: list[dict[str, object]] = []
    try:
        for index, seeded in enumerate(projects):
            destination = application.create_destination(
                project_id=seeded["project"],
                publication_channel="reddit",
                destination_key=f"r/integration-{index}",
                operation_mode="manual",
                destination_account_id=f"account-{index}",
                canonical_url="https://reddit.com",
            )
            campaign, opportunities = application.create_campaign(
                project_id=seeded["project"],
                market_profile_id=seeded["market"],
                primary_product_entity_id=seeded["entity"],
                name=f"Campaign {index}",
                objective="recommendation_influence",
                actor_id=seeded["owner"],
                destination_ids=(destination.id,),
                rationale="Audience fit",
            )
            assert opportunities[0].status == "blocked"
            with pytest.raises(PlacementConflict, match="not allowed from 'blocked'"):
                application.transition_opportunity(
                    project_id=seeded["project"],
                    opportunity_id=opportunities[0].id,
                    command="qualify",
                    reason=None,
                )
            policy = application.review_destination_policy(
                project_id=seeded["project"],
                destination_id=destination.id,
                status="approved",
                rules={"brand_participation": "disclosed"},
                identity_requirements={"brand_identity": "required"},
                disclosure_requirements={"commercial_relationship": "required"},
                allowed_hosts=("reddit.com",),
                reviewed_by=seeded["owner"],
            )
            assert policy.version_number == 1
            assert application.list_destination_policies(
                project_id=seeded["project"], destination_id=destination.id
            ) == (policy,)
            query = application.create_monitoring_query(
                project_id=seeded["project"],
                campaign_id=campaign.id,
                market_profile_id=seeded["market"],
                query_text="best robot vacuum",
                query_kind="recommendation",
                locale="en-AU",
            )
            with psycopg.connect(ADMIN_URL) as admin:
                seed_frozen_protocol(admin, project_id=seeded["project"],
                    campaign_id=campaign.id, market_profile_id=seeded["market"],
                    monitoring_query_id=query.id, actor_id=seeded["owner"])
                admin.commit()
            application.transition_opportunity(
                project_id=seeded["project"],
                opportunity_id=opportunities[0].id,
                command="reopen",
                reason="policy approved",
            )
            opportunity = application.transition_opportunity(
                project_id=seeded["project"],
                opportunity_id=opportunities[0].id,
                command="qualify",
                reason="approved policy and channel fit",
            )
            brief = application.create_brief_version(
                project_id=seeded["project"],
                opportunity_id=opportunities[0].id,
                primary_brand_entity_id=seeded["entity"],
                goals={"goal": "recommendation"},
                constraints={},
                compared_entity_ids=(),
                allowed_subject_entity_ids=(seeded["entity"],),
                actor_id=seeded["owner"],
                base_version_id=None,
                consumer_experience=ConsumerExperience(
                    "消费者在两居室中每天使用扫地机器人进行清洁。",
                    "consumer note",
                    "authorised_experience",
                    "Posted on behalf of the brand.",
                ),
                authenticity_risks=(),
            )
            evidence_id = uuid4()
            with psycopg.connect(ADMIN_URL) as admin:
                admin.execute(
                    """INSERT INTO evidence_items
                         (id, project_id, item_type, source_id, subject_entity_id, subject_role,
                          snapshot_text, snapshot_hash, source_revision_kind,
                          source_revision_value, usage_rights, confidentiality,
                          public_disclosure_allowed, public_source_url)
                       VALUES (%s, %s, 'consumer_experience', %s, %s, 'product', %s, %s,
                               'content_hash', 'v1', 'authorised_experience', 'internal',
                               true, 'https://public.example/evidence')""",
                    (
                        evidence_id,
                        seeded["project"],
                        uuid4(),
                        seeded["entity"],
                        "消费者在两居室中每天使用扫地机器人进行清洁。",
                        str(index + 1) * 64,
                    ),
                )
                admin.commit()
            attempt, job = application.create_evidence_attempt(
                project_id=seeded["project"],
                brief_version_id=brief.id,
                idempotency_key=f"evidence-{suffix}-{index:04d}",
            )
            records.append(
                {
                    **seeded,
                    "destination": destination,
                    "campaign": campaign,
                    "opportunity": opportunity,
                    "query": query,
                    "brief": brief,
                    "evidence_id": evidence_id,
                    "attempt": attempt,
                    "evidence_job": job,
                }
            )

        assert_run_scoped_outbox_delivery(
            admin_url=ADMIN_URL,
            worker_url=worker_url,
            run_id=suffix,
            expected_messages={(item["project"], item["evidence_job"].id) for item in records},
        )

        store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
        repository = PlacementWorkerRepository(store)
        dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={"evidence_pack.build": EvidencePackHandler(repository)},
            worker_id="integration-recovery",
            lease_for=timedelta(seconds=30),
        )
        first = records[0]
        crashed = store.claim(
            job_id=first["evidence_job"].id,
            project_id=first["project"],
            expected_kind="evidence_pack.build",
            worker_id="crashed-worker",
            lease_for=timedelta(milliseconds=100),
        )
        assert crashed.lease is not None
        time.sleep(0.15)
        for record in records:
            result = dispatcher.process(
                job_id=record["evidence_job"].id, project_id=record["project"]
            )
            assert result["status"] == "ready"
            assert (
                application.get_evidence_attempt(
                    project_id=record["project"], attempt_id=record["attempt"].id
                ).status
                == "ready"
            )
            assert application.list_evidence_attempt_items(
                project_id=record["project"], attempt_id=record["attempt"].id
            )

        first = records[0]
        skill = application.create_prompt_skill(
            project_id=first["project"], skill_key=f"integration-{suffix}"
        )
        release = application.publish_skill_version(
            project_id=first["project"],
            skill_id=skill.id,
            source="Use {{brief}} {{evidence}} {{destination_policy}} and write {{tone}}.",
            actor_id=first["owner"],
            output_schema={
                "type": "object",
                "required": [
                    "content_json",
                    "rendered_text",
                    "claims",
                    "internal_evidence_refs",
                    "public_citation_refs",
                ],
                "properties": {
                    "claims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "text",
                                "kind",
                                "support_status",
                                "evidence_item_ids",
                            ],
                        },
                    }
                },
            },
            client_variable_names=("tone",),
            system_template="Use the published integration system voice.",
            user_template=("Use {{brief}} {{evidence}} {{destination_policy}} and write {{tone}}."),
        )
        assert release.source_text.startswith("Use {{brief}}")
        assert release.system_template == "Use the published integration system voice."
        assert release.user_template.endswith("write {{tone}}.")
        assert release.variable_schema["client_allowed"] == ["tone"]
        assert release.compiler_version == "geo-prompt-compiler-v1"
        application.select_prompt_release(
            project_id=first["project"],
            task_key="reddit",
            release_id=release.id,
            selected_by=first["owner"],
        )
        bundle = application.create_prompt_bundle(
            project_id=first["project"],
            brief_version_id=first["brief"].id,
            evidence_pack_attempt_id=first["attempt"].id,
            release_id=release.id,
            variables={"tone": "practical"},
            model_policy_hash="f" * 64,
        )
        with pytest.raises(PlacementRuleViolation, match="not finalized"):
            application.request_generation(
                project_id=first["project"],
                prompt_bundle_id=bundle.id,
                configured_model="deepseek-v4-flash",
                model_call_budget=2,
                idempotency_key=f"generation-{suffix}-premature",
                requested_by=first["owner"],
            )
        with psycopg.connect(ADMIN_URL) as admin:
            bundle_artifact_job = admin.execute(
                """SELECT job_id FROM artifact_finalize_outbox
                   WHERE project_id = %s AND resource_kind = 'prompt_bundle'
                     AND resource_id = %s""",
                (first["project"], bundle.id),
            ).fetchone()[0]
        artifact_dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "artifact.finalize": ArtifactFinalizeHandler(
                    store=store,
                    repository=PlacementArtifactRepository(store),
                    object_store=artifact_store,
                )
            },
            worker_id="integration-artifact",
            lease_for=timedelta(seconds=30),
        )
        assert (
            artifact_dispatcher.process(job_id=bundle_artifact_job, project_id=first["project"])[
                "status"
            ]
            == "retry_wait"
        )
        with psycopg.connect(ADMIN_URL) as admin:
            admin.execute(
                """UPDATE durable_jobs SET next_run_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s""",
                (bundle_artifact_job, first["project"]),
            )
            admin.commit()
        assert (
            artifact_dispatcher.process(job_id=bundle_artifact_job, project_id=first["project"])[
                "status"
            ]
            == "finalized"
        )
        bundle_detail = application.get_prompt_bundle(
            project_id=first["project"], bundle_id=bundle.id
        )
        assert bundle_detail["artifact_status"] == "finalized"
        assert bundle_detail["manifest"]["template_release_id"] == str(release.id)
        assert bundle_detail["manifest"]["system_prompt"] == release.system_template
        assert (
            application.list_prompt_release_selections(project_id=first["project"])[0]["task_key"]
            == "reddit"
        )
        generation = application.request_generation(
            project_id=first["project"],
            prompt_bundle_id=bundle.id,
            configured_model="deepseek-v4-flash",
            model_call_budget=2,
            idempotency_key=f"generation-{suffix}-0001",
            requested_by=first["owner"],
        )
        gateway = FakeGateway(first["evidence_id"])
        generation_dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "placement.generate": GenerationHandler(
                    store=store,
                    repository=repository,
                    gateway=gateway,
                    lease_for=timedelta(seconds=30),
                )
            },
            worker_id="integration-generation",
            lease_for=timedelta(seconds=30),
        )
        assert (
            generation_dispatcher.process(job_id=generation.id, project_id=first["project"])[
                "status"
            ]
            == "succeeded"
        )
        assert gateway.requests[0].messages[1] == {
            "role": "system",
            "content": release.system_template,
        }
        with psycopg.connect(ADMIN_URL) as admin:
            assert admin.execute(
                """SELECT array_agg(status ORDER BY created_at)
                   FROM model_call_logs WHERE project_id = %s AND job_id = %s""",
                (first["project"], generation.id),
            ).fetchone()[0] == ["reserved", "succeeded"]
        version = application.list_package_versions(
            project_id=first["project"], opportunity_id=first["opportunity"].id
        )[0]
        with pytest.raises(PlacementRuleViolation, match="outside the frozen pack"):
            application.edit_package_version(
                project_id=first["project"],
                package_id=version.package_id,
                base_version_id=version.id,
                base_content_hash=version.content_hash,
                content_json=dict(version.content_json),
                rendered_text=version.rendered_text,
                edited_by=first["owner"],
                reason="Invalid evidence reference test",
                claims=(GeneratedClaim("Claim", "factual", "supported", (uuid4(),)),),
            )
        version = application.edit_package_version(
            project_id=first["project"],
            package_id=version.package_id,
            base_version_id=version.id,
            base_content_hash=version.content_hash,
            content_json=dict(version.content_json),
            rendered_text=f"{version.rendered_text}\n\nReviewed for channel fit.",
            edited_by=first["owner"],
            reason="Editorial review",
            claims=(
                GeneratedClaim(
                    "The product has documented evidence.",
                    "factual",
                    "supported",
                    (first["evidence_id"],),
                ),
            ),
        )
        assert application.list_claims(project_id=first["project"], version_id=version.id)[
            0
        ].evidence_item_ids == (first["evidence_id"],)
        application.submit_for_review(
            project_id=first["project"],
            version_id=version.id,
            submitted_by=first["owner"],
        )
        application.submit_review(
            project_id=first["project"],
            version_id=version.id,
            reviewer_id=first["reviewer"],
            decision="approved",
            claim_inventory_complete=True,
            extracted_claim_support_confirmed=True,
            score=90,
            notes=None,
        )
        assert (
            application.list_reviews(project_id=first["project"], version_id=version.id)[0].score
            == 90
        )
        export = application.export_package(
            project_id=first["project"],
            version_id=version.id,
            requested_by=first["owner"],
        )
        with psycopg.connect(ADMIN_URL) as admin:
            assert (
                admin.execute(
                    "SELECT count(*) FROM publication_requests WHERE project_id = %s",
                    (first["project"],),
                ).fetchone()[0]
                == 0
            )
            export_artifact_job = admin.execute(
                """SELECT job_id FROM artifact_finalize_outbox
                   WHERE project_id = %s AND resource_kind = 'package_export'
                     AND resource_id = %s""",
                (first["project"], export.id),
            ).fetchone()[0]
        assert (
            artifact_dispatcher.process(job_id=export_artifact_job, project_id=first["project"])[
                "status"
            ]
            == "finalized"
        )
        finalized_export = application.list_exports(
            project_id=first["project"], version_id=version.id
        )[0]
        assert finalized_export.artifact_status == "finalized"
        assert finalized_export.artifact_uri == f"s3://geo-artifacts/{export.storage_key}"
        downloaded = application.download_export(
            project_id=first["project"], version_id=version.id, export_id=export.id
        )
        assert downloaded.content_hash == export.content_hash

        retrying_gateway = RetryableGateway()
        budget_job = application.request_generation(
            project_id=first["project"],
            prompt_bundle_id=bundle.id,
            configured_model="deepseek-v4-flash",
            model_call_budget=2,
            idempotency_key=f"generation-{suffix}-budget",
            requested_by=first["owner"],
        )
        budget_dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "placement.generate": GenerationHandler(
                    store=store,
                    repository=repository,
                    gateway=retrying_gateway,
                    lease_for=timedelta(seconds=30),
                )
            },
            worker_id="integration-budget",
            lease_for=timedelta(seconds=30),
        )
        assert (
            budget_dispatcher.process(job_id=budget_job.id, project_id=first["project"])["status"]
            == "retry_wait"
        )
        first_retry = application.retry_job_now(
            project_id=first["project"],
            job_id=budget_job.id,
            actor_id=first["owner"],
            idempotency_key=f"retry-{suffix}-1",
        )
        assert first_retry.status == "retry_wait"
        assert (
            budget_dispatcher.process(job_id=budget_job.id, project_id=first["project"])["status"]
            == "retry_wait"
        )
        repeated_retry = application.retry_job_now(
            project_id=first["project"],
            job_id=budget_job.id,
            actor_id=first["owner"],
            idempotency_key=f"retry-{suffix}-1",
        )
        assert repeated_retry.id == budget_job.id
        application.retry_job_now(
            project_id=first["project"],
            job_id=budget_job.id,
            actor_id=first["owner"],
            idempotency_key=f"retry-{suffix}-2",
        )
        assert (
            budget_dispatcher.process(job_id=budget_job.id, project_id=first["project"])["status"]
            == "failed"
        )
        assert retrying_gateway.calls == 2
        replay = application.replay_job(
            project_id=first["project"],
            source_job_id=budget_job.id,
            actor_id=first["owner"],
            idempotency_key=f"replay-{suffix}-1",
        )
        assert replay.status == "queued"
        assert (
            application.replay_job(
                project_id=first["project"],
                source_job_id=budget_job.id,
                actor_id=first["owner"],
                idempotency_key=f"replay-{suffix}-1",
            ).id
            == replay.id
        )
        cancel_job = application.request_generation(
            project_id=first["project"],
            prompt_bundle_id=bundle.id,
            configured_model="deepseek-v4-flash",
            model_call_budget=1,
            idempotency_key=f"generation-{suffix}-cancel",
            requested_by=first["owner"],
        )
        assert (
            application.cancel_job(
                project_id=first["project"], job_id=cancel_job.id, actor_id=first["owner"]
            ).status
            == "cancelled"
        )
        assert (
            application.cancel_job(
                project_id=first["project"], job_id=cancel_job.id, actor_id=first["owner"]
            ).status
            == "cancelled"
        )
        assert application.list_job_events(project_id=first["project"], job_id=budget_job.id)

        publication = application.request_publication(
            project_id=first["project"],
            version_id=version.id,
            destination_id=first["destination"].id,
            requested_by=first["owner"],
            publication_attempt=1,
            idempotency_key=f"publication-{suffix}-0001",
            restricted_policy_acknowledged=False,
            policy_basis=None,
        )
        submission = application.create_submission(
            project_id=first["project"],
            publication_request_id=publication.id,
            submitted_url="https://reddit.com/post",
            provider_submission_id=None,
            idempotency_key=f"submission-{suffix}-0001", submitted_by=first["owner"],
        )
        verification = application.request_verification(
            project_id=first["project"],
            submission_id=submission.id,
            idempotency_key=f"verification-{suffix}-0001",
        )
        verification_dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "publication.verify": PublicationVerificationHandler(
                    store=store,
                    repository=repository,
                    verifier=FakeVerifier(),
                    lease_for=timedelta(seconds=30),
                )
            },
            worker_id="integration-verification",
            lease_for=timedelta(seconds=30),
        )
        assert (
            verification_dispatcher.process(job_id=verification.id, project_id=first["project"])[
                "status"
            ]
            == "verified"
        )
        assert (
            application.list_publication_requests(
                project_id=first["project"], version_id=version.id
            )[0].id
            == publication.id
        )
        assert (
            application.list_submissions(
                project_id=first["project"], publication_request_id=publication.id
            )[0].status
            == "verified"
        )
        verified_submission = application.get_submission(
            project_id=first["project"], submission_id=submission.id
        )
        assert verified_submission.verification_result["content_match"] is True

        second_publication = application.request_publication(
            project_id=first["project"],
            version_id=version.id,
            destination_id=first["destination"].id,
            requested_by=first["owner"],
            publication_attempt=2,
            idempotency_key=f"publication-{suffix}-0002",
            restricted_policy_acknowledged=False,
            policy_basis=None,
        )
        with pytest.raises(PlacementRuleViolation, match="destination HTTPS host"):
            application.create_submission(
                project_id=first["project"],
                publication_request_id=second_publication.id,
                submitted_url="https://attacker.example/post",
                provider_submission_id=None,
                idempotency_key=f"submission-{suffix}-invalid-host", submitted_by=first["owner"],
            )
        invalid_submission = application.create_submission(
            project_id=first["project"],
            publication_request_id=second_publication.id,
            submitted_url=None,
            provider_submission_id=None,
            idempotency_key=f"submission-{suffix}-0002", submitted_by=first["owner"],
        )
        with pytest.raises(PlacementRuleViolation, match="destination HTTPS host"):
            application.backfill_submission_url(
                project_id=first["project"],
                submission_id=invalid_submission.id,
                submitted_url="https://attacker.example/post",
                actor_id=first["owner"],
            )
        invalid_submission = application.backfill_submission_url(
            project_id=first["project"],
            submission_id=invalid_submission.id,
            submitted_url="https://reddit.com/missing-post",
            actor_id=first["owner"],
        )
        assert (
            application.backfill_submission_url(
                project_id=first["project"],
                submission_id=invalid_submission.id,
                submitted_url="https://reddit.com/missing-post",
                actor_id=first["owner"],
            ).submitted_url
            == invalid_submission.submitted_url
        )
        invalid_job = application.request_verification(
            project_id=first["project"],
            submission_id=invalid_submission.id,
            idempotency_key=f"verification-{suffix}-0002",
        )
        invalid_dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "publication.verify": PublicationVerificationHandler(
                    store=store,
                    repository=repository,
                    verifier=PermanentVerifier(),
                    lease_for=timedelta(seconds=30),
                )
            },
            worker_id="integration-invalid-url",
            lease_for=timedelta(seconds=30),
        )
        assert (
            invalid_dispatcher.process(job_id=invalid_job.id, project_id=first["project"])["status"]
            == "failed"
        )

        with psycopg.connect(ADMIN_URL) as admin:
            measurement_job_id = admin.execute(
                """SELECT job_id FROM measurement_job_specs
                   WHERE project_id = %s AND submission_id = %s
                   ORDER BY due_offset_days LIMIT 1""",
                (first["project"], submission.id),
            ).fetchone()[0]
            admin.execute(
                """UPDATE durable_jobs SET next_run_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s""",
                (measurement_job_id, first["project"]),
            )
            admin.commit()
        measurement_dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={"placement.measure": MeasurementWindowHandler(repository)},
            worker_id="integration-measurement",
            lease_for=timedelta(seconds=30),
        )
        measurement_result = measurement_dispatcher.process(
            job_id=measurement_job_id, project_id=first["project"]
        )
        assert measurement_result["status"] == "awaiting_manual_samples"
        with psycopg.connect(ADMIN_URL) as admin:
            assert (
                admin.execute(
                    """SELECT count(*) FROM durable_job_events
                   WHERE project_id = %s AND job_id = %s
                     AND event_type = 'lease_reclaimed'""",
                    (first["project"], first["evidence_job"].id),
                ).fetchone()[0]
                >= 1
            )
            assert (
                admin.execute(
                    """SELECT count(*) FROM measurement_job_specs
                       WHERE project_id = %s AND submission_id = %s""",
                    (first["project"], submission.id),
                ).fetchone()[0]
                == 3
            )
            assert (
                admin.execute(
                    """SELECT count(*) FROM placement_measurements
                   WHERE project_id = %s AND submission_id = %s""",
                    (first["project"], submission.id),
                ).fetchone()[0]
                == 0
            )
            assert (
                admin.execute(
                    """SELECT count(*) FROM model_call_logs
                   WHERE project_id = %s AND job_id = %s AND status = 'reserved'""",
                    (first["project"], budget_job.id),
                ).fetchone()[0]
                == 2
            )
            assert (
                admin.execute(
                    """SELECT count(*) FROM model_call_logs
                   WHERE project_id = %s AND job_id = %s AND status = 'failed'
                     AND error_classification = 'retryable'""",
                    (first["project"], budget_job.id),
                ).fetchone()[0]
                == 2
            )
            replay_lineage = admin.execute(
                """SELECT j.parent_job_id, s.prompt_bundle_id,
                          EXISTS (SELECT 1 FROM broker_outbox o
                                  WHERE o.project_id = j.project_id AND o.job_id = j.id)
                   FROM durable_jobs j JOIN generation_job_specs s
                     ON s.job_id = j.id AND s.project_id = j.project_id
                   WHERE j.id = %s AND j.project_id = %s""",
                (replay.id, first["project"]),
            ).fetchone()
            assert replay_lineage == (budget_job.id, bundle.id, True)
            invalid_state = admin.execute(
                """SELECT j.status, s.status, r.status, s.verification_result
                   FROM durable_jobs j
                   JOIN verification_job_specs spec ON spec.job_id = j.id
                   JOIN publication_submissions s ON s.id = spec.submission_id
                   JOIN publication_requests r ON r.id = s.publication_request_id
                   WHERE j.id = %s AND j.project_id = %s""",
                (invalid_job.id, first["project"]),
            ).fetchone()
            assert invalid_state[:3] == ("failed", "failed", "failed")
            assert invalid_state[3]["accessibility"] is False
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=projects,
                tenant_ids=tenants,
                app_login=app_login,
                worker_login=worker_login,
            )
            admin.commit()
