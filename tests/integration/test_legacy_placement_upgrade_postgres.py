from __future__ import annotations

from datetime import timedelta
import hashlib
import os
from uuid import UUID, uuid4

from alembic import command
from alembic.script import ScriptDirectory
import psycopg
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.placements.application import PlacementApplication
from geo_core.placements.artifact_worker import PlacementArtifactRepository
from geo_core.placements.default_prompts import default_output_schema
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.placements.worker_composition import (
    ArtifactFinalizeHandler,
    EvidencePackHandler,
    GenerationHandler,
    PlacementWorkerDispatcher,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository
from tests.integration.placement_worker_support import FakeGateway, MemoryArtifactStore
from tests.integration.test_batch2_migrations_postgres import (
    _seed_legacy_fixture,
    _temporary_database,
)


ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_URL,
        reason="GEO_ACCESS_TEST_ADMIN_DATABASE_URL is required",
    ),
]


def test_legacy_placement_survives_upgrade_and_reaches_current_package() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0010_campaign_destinations")
        with psycopg.connect(database_url) as connection:
            fixture = _seed_legacy_fixture(connection)

        command.upgrade(configuration, "head")
        expected_head = ScriptDirectory.from_config(configuration).get_current_head()
        with psycopg.connect(database_url) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                expected_head,
            )
            legacy_binding = connection.execute(
                """SELECT binding_version, binding_state, is_legacy_backfill,
                          template_release_id
                   FROM current_opportunity_prompt_release_bindings
                   WHERE project_id = %s AND opportunity_id = %s""",
                (fixture["project"], fixture["opportunity"]),
            ).fetchone()
            assert legacy_binding == (1, "unbound", True, None)

        artifact_store = MemoryArtifactStore()
        artifact_store.fail_next = False
        application = PlacementApplication(
            placement_uow_factory(lambda: psycopg.connect(database_url)),
            artifact_reader=artifact_store,
        )
        project_id = fixture["project"]
        campaign_id = fixture["campaign"]
        opportunity_id = fixture["opportunity"]

        legacy_campaign = application.get_campaign(project_id=project_id, campaign_id=campaign_id)
        assert legacy_campaign is not None
        assert legacy_campaign.id == campaign_id
        opportunities = application.list_opportunities(
            project_id=project_id, campaign_id=campaign_id
        )
        assert len(opportunities) == 1
        assert opportunities[0].id == opportunity_id
        assert opportunities[0].opportunity_ref == "legacy-opportunity"

        legacy_releases = application.list_prompt_releases(
            project_id=project_id, skill_id=fixture["skill"]
        )
        assert len(legacy_releases) == 1
        assert legacy_releases[0].id == fixture["release"]
        assert legacy_releases[0].status.value == "approved"
        assert legacy_releases[0].compiler_version == "legacy-compiler"
        unbound = application.get_current_prompt_release_binding(
            project_id=project_id,
            campaign_id=campaign_id,
            opportunity_id=opportunity_id,
        )
        assert unbound is not None
        assert unbound.binding_version == 1
        assert unbound.status.value == "unbound"
        assert unbound.template_release_id is None

        application.review_destination_policy(
            project_id=project_id,
            destination_id=fixture["destination"],
            status="approved",
            rules={"manual_publication": True},
            identity_requirements={"brand_identity": "required"},
            disclosure_requirements={"commercial_relationship": "required"},
            allowed_hosts=("example.test",),
            reviewed_by=fixture["owner"],
        )
        qualified = application.transition_opportunity(
            project_id=project_id,
            campaign_id=campaign_id,
            opportunity_id=opportunity_id,
            command="qualify",
            reason="post-upgrade destination policy approved",
        )
        assert qualified.status == "qualified"

        brief = application.create_brief_version(
            project_id=project_id,
            campaign_id=campaign_id,
            opportunity_id=opportunity_id,
            primary_brand_entity_id=fixture["product"],
            goals={"goal": "legacy placement continuity"},
            constraints={"publication_mode": "manual"},
            compared_entity_ids=(),
            allowed_subject_entity_ids=(fixture["product"],),
            actor_id=fixture["owner"],
            base_version_id=None,
            consumer_experience=None,
            authenticity_risks=(),
        )

        suffix = uuid4().hex[:10]
        skill = application.create_prompt_skill(
            project_id=project_id, skill_key=f"legacy-upgrade-{suffix}"
        )
        release = application.publish_skill_version(
            project_id=project_id,
            skill_id=skill.id,
            source="Use {{brief}} {{evidence}} {{destination_policy}} and write {{tone}}.",
            actor_id=fixture["owner"],
            output_schema=default_output_schema(),
            client_variable_names=("tone",),
            system_template="Use the current executable Placement contract.",
            user_template=("Use {{brief}} {{evidence}} {{destination_policy}} and write {{tone}}."),
        )
        assert release.status.value == "draft"
        assert release.compiler_version == "geo-prompt-compiler-v1"
        release = application.transition_prompt_release(
            project_id=project_id,
            release_id=release.id,
            command="approve",
            expected_state_version=release.state_version,
            reason="approve post-upgrade executable Release",
            actor_id=fixture["owner"],
            idempotency_key=f"legacy-upgrade-release-{suffix}",
        )
        assert release.status.value == "approved"
        binding = application.bind_opportunity_prompt_release(
            project_id=project_id,
            campaign_id=campaign_id,
            opportunity_id=opportunity_id,
            release_id=release.id,
            expected_binding_version=1,
            reason="replace legacy unbound state with current executable Release",
            actor_id=fixture["owner"],
            idempotency_key=f"legacy-upgrade-binding-{suffix}",
        )
        assert binding.binding_version == 2
        assert binding.previous_binding_id == unbound.id
        assert binding.status.value == "bound"
        assert binding.template_release_id == release.id

        evidence_id = _seed_current_placement_evidence(database_url, fixture)
        attempt, evidence_job = application.create_evidence_attempt(
            project_id=project_id,
            campaign_id=campaign_id,
            brief_version_id=brief.id,
            idempotency_key=f"legacy-upgrade-evidence-{suffix}",
        )
        store = PostgresDurableJobStore(lambda: psycopg.connect(database_url))
        repository = PlacementWorkerRepository(store)
        evidence_dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={"evidence_pack.build": EvidencePackHandler(repository)},
            worker_id=f"legacy-upgrade-evidence-{suffix}",
            lease_for=timedelta(seconds=30),
        )
        assert (
            evidence_dispatcher.process(job_id=evidence_job.id, project_id=project_id)["status"]
            == "ready"
        )
        items = application.list_evidence_attempt_items(
            project_id=project_id,
            campaign_id=campaign_id,
            attempt_id=attempt.id,
        )
        assert {item["id"] for item in items} == {evidence_id}

        bundle = application.create_prompt_bundle(
            project_id=project_id,
            campaign_id=campaign_id,
            opportunity_id=opportunity_id,
            brief_version_id=brief.id,
            evidence_pack_attempt_id=attempt.id,
            prompt_release_binding_id=binding.id,
            confirmed_release_hash=release.release_hash,
            variables={"tone": "practical"},
            model_policy_hash="f" * 64,
            idempotency_key=f"legacy-upgrade-bundle-{suffix}",
            requested_by=fixture["owner"],
        )
        bundle_artifact_job = _artifact_job_id(
            database_url,
            project_id=project_id,
            resource_id=bundle.id,
        )
        artifact_dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "artifact.finalize": ArtifactFinalizeHandler(
                    store=store,
                    repository=PlacementArtifactRepository(store),
                    object_store=artifact_store,
                )
            },
            worker_id=f"legacy-upgrade-artifact-{suffix}",
            lease_for=timedelta(seconds=30),
        )
        assert (
            artifact_dispatcher.process(job_id=bundle_artifact_job, project_id=project_id)["status"]
            == "finalized"
        )
        finalized_bundle = application.list_prompt_bundles(
            project_id=project_id,
            campaign_id=campaign_id,
            brief_version_id=brief.id,
        )[0]
        assert finalized_bundle.id == bundle.id
        assert finalized_bundle.artifact_status == "finalized"
        assert finalized_bundle.prompt_release_binding_version == 2

        generation_job = application.request_generation(
            project_id=project_id,
            campaign_id=campaign_id,
            prompt_bundle_id=bundle.id,
            configured_model="deepseek-v4-flash",
            model_call_budget=1,
            idempotency_key=f"legacy-upgrade-generation-{suffix}",
            requested_by=fixture["owner"],
        )
        generation_dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "placement.generate": GenerationHandler(
                    store=store,
                    repository=repository,
                    gateway=FakeGateway(evidence_id),
                    lease_for=timedelta(seconds=30),
                )
            },
            worker_id=f"legacy-upgrade-generation-{suffix}",
            lease_for=timedelta(seconds=30),
        )
        generated = generation_dispatcher.process(job_id=generation_job.id, project_id=project_id)
        assert generated["status"] == "succeeded"
        version_id = UUID(str(generated["package_version_id"]))
        versions = application.list_package_versions(
            project_id=project_id,
            campaign_id=campaign_id,
            opportunity_id=opportunity_id,
        )
        assert len(versions) == 1
        assert versions[0].id == version_id
        assert versions[0].version_number == 1
        assert versions[0].prompt_bundle_id == bundle.id
        assert versions[0].generated_by_job_id == generation_job.id
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                """SELECT package.id, version.id
                   FROM placement_packages AS package
                   JOIN placement_package_versions AS version
                     ON version.package_id = package.id
                    AND version.project_id = package.project_id
                   WHERE package.project_id = %s AND package.opportunity_id = %s""",
                (project_id, opportunity_id),
            ).fetchone() == (versions[0].package_id, version_id)


def _seed_current_placement_evidence(database_url: str, fixture: dict[str, object]) -> UUID:
    evidence_id = uuid4()
    snapshot_text = "A documented consumer experience remains usable after the upgrade."
    snapshot_hash = hashlib.sha256(snapshot_text.encode()).hexdigest()
    source_revision = hashlib.sha256(b"legacy-upgrade-placement-source-v1").hexdigest()
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """INSERT INTO evidence_items
                 (id, project_id, item_type, source_id, subject_entity_id, subject_role,
                  snapshot_text, snapshot_hash, source_revision_kind,
                  source_revision_value, usage_rights, confidentiality,
                  public_disclosure_allowed, public_source_url)
               VALUES (%s, %s, 'consumer_experience', %s, %s, 'product', %s, %s,
                       'content_hash', %s, 'authorised_experience', 'internal',
                       true, 'https://public.example/legacy-upgrade')""",
            (
                evidence_id,
                fixture["project"],
                uuid4(),
                fixture["product"],
                snapshot_text,
                snapshot_hash,
                source_revision,
            ),
        )
        connection.commit()
    return evidence_id


def _artifact_job_id(database_url: str, *, project_id: UUID, resource_id: UUID) -> UUID:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """SELECT job_id FROM artifact_finalize_outbox
               WHERE project_id = %s AND resource_kind = 'prompt_bundle'
                 AND resource_id = %s""",
            (project_id, resource_id),
        ).fetchone()
    assert row is not None
    return row[0]
