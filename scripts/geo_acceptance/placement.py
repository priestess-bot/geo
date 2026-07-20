"""Durable evidence, generation, review, export and publication workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping, cast
from uuid import UUID

import psycopg

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.placements.artifact_worker import PlacementArtifactRepository
from geo_core.placements.domain import (
    BriefVersion,
    Claim,
    ConsumerExperience,
    EvidencePackAttempt,
    ExportReceipt,
    JobReference,
    MeasurementCollectionTask,
    OpportunityPromptReleaseBinding,
    PackageVersion,
    PromptBundleView,
    PublicationRequest,
    Review,
    Submission,
)
from geo_core.placements.simulation import PromptSimulation
from geo_core.placements.simulation_worker import PromptSimulationHandler
from geo_core.placements.worker_composition import (
    ArtifactFinalizeHandler,
    EvidencePackHandler,
    GenerationHandler,
    JobHandler,
    MeasurementWindowHandler,
    PlacementWorkerDispatcher,
    PublicationVerificationHandler,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository

from scripts.geo_acceptance.adapters import (
    ControlledUrlVerifier,
    DeterministicGateway,
    MemoryArtifactStore,
    model_gateway,
)
from scripts.geo_acceptance.contracts import (
    AcceptanceConfig,
    CHANNELS,
    MODEL,
    MODEL_POLICY_HASH,
)
from scripts.geo_acceptance.monitoring import BaselineResult
from scripts.geo_acceptance.placement_measurements import (
    make_measurement_job_due as _make_measurement_job_due,
    measurement_windows as _measurement_windows,
)
from scripts.geo_acceptance.setup import AcceptanceSetup, EXPERIENCE_TEXT


LEASE_FOR = timedelta(seconds=30)


@dataclass(frozen=True)
class PlacementResult:
    store: PostgresDurableJobStore
    brief: BriefVersion
    evidence_attempt: EvidencePackAttempt
    prompt_bindings: tuple[OpportunityPromptReleaseBinding, ...]
    prompt_simulations: tuple[PromptSimulation, ...]
    prompt_bundle: PromptBundleView
    generation_job: JobReference
    package: PackageVersion
    claims: tuple[Claim, ...]
    review: Review
    export: ExportReceipt
    publication: PublicationRequest
    submission: Submission
    measurement_tasks: tuple[MeasurementCollectionTask, ...]
    submitted_url: str
    scheduled_windows: tuple[int, ...]
    terminal_artifact_replay_count: int


def run_placement(
    config: AcceptanceConfig,
    setup: AcceptanceSetup,
    baseline: BaselineResult,
) -> PlacementResult:
    app = setup.placement
    project_id = setup.project_id
    brief = app.create_brief_version(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        opportunity_id=setup.owned_opportunity.id,
        primary_brand_entity_id=setup.brand.id,
        goals={
            "consumer_query": baseline.query.query_text,
            "goal": "publish source-grounded official product information",
        },
        constraints={"locale": "en-AU", "manual_submission_only": True},
        compared_entity_ids=(),
        allowed_subject_entity_ids=(setup.brand.id, setup.product.id),
        actor_id=setup.owner.identity_id,
        base_version_id=None,
        consumer_experience=ConsumerExperience(
            description=EXPERIENCE_TEXT,
            source="consumer description supplied to ADVINSYS",
            usage_rights="authorised_experience",
            disclosure="Official ADVINSYS content based on an authorised description.",
        ),
        authenticity_risks=(),
    )
    evidence_attempt, evidence_job = app.create_evidence_attempt(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        brief_version_id=brief.id,
        idempotency_key=f"acceptance-evidence-{setup.suffix}",
    )
    store = PostgresDurableJobStore(
        lambda: psycopg.connect(config.worker_database_url.strip())
    )
    repository = PlacementWorkerRepository(store)
    evidence_result = _dispatcher(
        store,
        handlers={"evidence_pack.build": EvidencePackHandler(repository)},
        worker_id=f"acceptance-evidence-{setup.suffix}",
    ).process(job_id=evidence_job.id, project_id=project_id)
    if evidence_result["status"] != "ready":
        raise AssertionError(f"evidence pack did not become ready: {evidence_result}")
    evidence_items = app.list_evidence_attempt_items(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        attempt_id=evidence_attempt.id,
    )
    evidence_ids = {item["id"] for item in evidence_items}
    if not {setup.fact.id, setup.experience.id}.issubset(evidence_ids):
        raise AssertionError("the evidence pack omitted governed project evidence")

    catalog_bindings = app.install_default_prompt_catalog(
        project_id=project_id, actor_id=setup.owner.identity_id
    )
    if {str(item["task_key"]) for item in catalog_bindings} != {
        item["channel"] for item in CHANNELS
    }:
        raise AssertionError("the editable prompt catalog must cover all selected channels")
    destination_by_channel = {
        item.publication_channel: item for item in setup.destinations
    }
    opportunity_by_destination = {
        item.destination_id: item
        for item in app.list_opportunities(
            project_id=project_id, campaign_id=setup.campaign.id
        )
    }
    prompt_bindings: list[OpportunityPromptReleaseBinding] = []
    for selection in catalog_bindings:
        channel = str(selection["task_key"])
        destination = destination_by_channel[channel]
        opportunity = opportunity_by_destination[destination.id]
        current = app.get_current_prompt_release_binding(
            project_id=project_id,
            campaign_id=setup.campaign.id,
            opportunity_id=opportunity.id,
        )
        if current is None or current.status.value != "unbound":
            raise AssertionError("new Opportunity did not start with an unbound Prompt Release")
        prompt_bindings.append(
            app.bind_opportunity_prompt_release(
                project_id=project_id,
                campaign_id=setup.campaign.id,
                opportunity_id=opportunity.id,
                release_id=cast(UUID, selection["template_release_id"]),
                expected_binding_version=current.binding_version,
                reason="Controlled acceptance Channel Prompt Release binding",
                actor_id=setup.owner.identity_id,
                idempotency_key=f"acceptance-binding-{channel}-{setup.suffix}",
            )
        )
    artifact_dispatcher = _artifact_dispatcher(store, setup)
    terminal_artifact_replay_count = 0
    simulations: list[PromptSimulation] = []
    simulation_dispatcher = _dispatcher(
        store,
        handlers={
            "prompt_simulation.generate": PromptSimulationHandler(
                store=store,
                repository=repository,
                gateway=DeterministicGateway(
                    evidence_id=setup.fact.id,
                    product_url=setup.product.canonical_url or "https://example.invalid/",
                ),
                lease_for=LEASE_FOR,
            )
        },
        worker_id=f"acceptance-simulation-{setup.suffix}",
    )
    for binding in prompt_bindings:
        destination = next(
            item for item in setup.destinations if item.id == binding.destination_id
        )
        channel = destination.publication_channel
        if binding.release_hash is None:
            raise AssertionError("bound Prompt Release has no frozen hash")
        simulation, simulation_job = app.create_prompt_simulation(
            project_id=project_id,
            campaign_id=setup.campaign.id,
            opportunity_id=binding.opportunity_id,
            destination_id=binding.destination_id,
            prompt_release_binding_id=binding.id,
            confirmed_release_hash=binding.release_hash,
            primary_brand_entity_id=setup.brand.id,
            product_entity_id=setup.product.id,
            authenticity_mode="fake_persona",
            evidence_item_ids=(setup.fact.id, setup.experience.id),
            goals={
                "consumer_query": baseline.query.query_text,
                "test_objective": f"validate the {channel} prompt contract",
            },
            constraints={"test_only": True, "publication_eligible": False},
            variables={},
            model_policy_hash=MODEL_POLICY_HASH,
            configured_model=MODEL,
            model_call_budget=1,
            requested_by=setup.owner.identity_id,
            idempotency_key=f"acceptance-simulation-{channel}-{setup.suffix}",
        )
        simulation_result = simulation_dispatcher.process(
            job_id=simulation_job.id, project_id=project_id
        )
        if simulation_result["status"] != "succeeded":
            raise AssertionError(f"{channel} prompt simulation failed: {simulation_result}")
        simulation_artifact_job = _artifact_job_id(
            store,
            project_id=project_id,
            resource_kind="prompt_simulation",
            resource_id=simulation.id,
        )
        artifact_result = artifact_dispatcher.process(
            job_id=simulation_artifact_job, project_id=project_id
        )
        if artifact_result["status"] != "finalized":
            raise AssertionError(f"{channel} simulation artifact did not finalize")
        _assert_terminal_artifact_replay(
            store,
            artifact_dispatcher,
            setup,
            job_id=simulation_artifact_job,
        )
        terminal_artifact_replay_count += 1
        finalized = app.get_prompt_simulation(
            project_id=project_id,
            campaign_id=setup.campaign.id,
            simulation_id=simulation.id,
        )
        if (
            finalized is None
            or finalized.publication_eligible
            or not finalized.test_only
            or finalized.artifact_status != "finalized"
        ):
            raise AssertionError(f"{channel} simulation escaped its TEST ONLY boundary")
        simulations.append(finalized)
    if len(simulations) != len(CHANNELS):
        raise AssertionError("every selected channel must have a prompt simulation")
    owned_binding = next(
        item for item in prompt_bindings
        if item.opportunity_id == setup.owned_opportunity.id
    )
    if owned_binding.release_hash is None:
        raise AssertionError("owned-site Prompt Release binding has no frozen hash")
    bundle = app.create_prompt_bundle(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        opportunity_id=setup.owned_opportunity.id,
        brief_version_id=brief.id,
        evidence_pack_attempt_id=evidence_attempt.id,
        prompt_release_binding_id=owned_binding.id,
        confirmed_release_hash=owned_binding.release_hash,
        variables={},
        model_policy_hash=MODEL_POLICY_HASH,
        idempotency_key=f"acceptance-prompt-bundle-{setup.suffix}",
        requested_by=setup.owner.identity_id,
    )
    bundle_job = _artifact_job_id(
        store, project_id=project_id, resource_kind="prompt_bundle", resource_id=bundle.id
    )
    bundle_result = artifact_dispatcher.process(job_id=bundle_job, project_id=project_id)
    if bundle_result["status"] != "finalized":
        raise AssertionError(f"prompt bundle artifact did not finalize: {bundle_result}")
    _assert_terminal_artifact_replay(
        store, artifact_dispatcher, setup, job_id=bundle_job
    )
    terminal_artifact_replay_count += 1

    generation_job = app.request_generation(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        prompt_bundle_id=bundle.id,
        configured_model=MODEL,
        model_call_budget=2,
        idempotency_key=f"acceptance-generation-{setup.suffix}",
        requested_by=setup.owner.identity_id,
    )
    generation_result = _dispatcher(
        store,
        handlers={
            "placement.generate": GenerationHandler(
                store=store,
                repository=repository,
                gateway=model_gateway(config, evidence_id=setup.fact.id),
                lease_for=LEASE_FOR,
            )
        },
        worker_id=f"acceptance-generation-{setup.suffix}",
    ).process(job_id=generation_job.id, project_id=project_id)
    if generation_result["status"] != "succeeded":
        raise AssertionError(f"generation did not succeed: {generation_result}")
    package = app.list_package_versions(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        opportunity_id=setup.owned_opportunity.id,
    )[-1]
    claims = app.list_claims(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        version_id=package.id,
    )
    if not claims or any(item.support_status != "supported" for item in claims):
        raise AssertionError("generated factual claims must be fully supported")
    app.submit_for_review(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        version_id=package.id,
        submitted_by=setup.owner.identity_id,
    )
    review = app.submit_review(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        version_id=package.id,
        reviewer_id=setup.reviewer_identity_id,
        decision="approved",
        claim_inventory_complete=True,
        extracted_claim_support_confirmed=True,
        score=95,
        notes="Controlled acceptance: subjects, evidence, disclosure and claims verified.",
    )

    if app.list_publication_requests(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        version_id=package.id,
    ):
        raise AssertionError("publication intent exists before export")
    export = app.export_package(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        version_id=package.id,
        requested_by=setup.owner.identity_id,
    )
    if app.list_publication_requests(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        version_id=package.id,
    ):
        raise AssertionError("export must not create publication intent")
    export_job = _artifact_job_id(
        store,
        project_id=project_id,
        resource_kind="package_export",
        resource_id=export.id,
    )
    export_result = artifact_dispatcher.process(job_id=export_job, project_id=project_id)
    if export_result["status"] != "finalized":
        raise AssertionError(f"package export artifact did not finalize: {export_result}")
    _assert_terminal_artifact_replay(
        store, artifact_dispatcher, setup, job_id=export_job
    )
    terminal_artifact_replay_count += 1
    exported = app.download_export(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        version_id=package.id,
        export_id=export.id,
    )
    if exported.content_hash != export.content_hash:
        raise AssertionError("downloaded export no longer matches its immutable receipt")

    publication = app.request_publication(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        version_id=package.id,
        destination_id=setup.destinations[0].id,
        requested_by=setup.owner.identity_id,
        publication_attempt=1,
        idempotency_key=f"acceptance-publication-{setup.suffix}",
        restricted_policy_acknowledged=False,
        policy_basis=None,
    )
    submitted_url = f"https://simulated.advinsys.example/geo-acceptance/{setup.suffix}"
    submission = app.create_submission(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        publication_request_id=publication.id,
        submitted_url=submitted_url,
        provider_submission_id=f"controlled-{setup.suffix}",
        idempotency_key=f"acceptance-submission-{setup.suffix}",
        submitted_by=setup.owner.identity_id,
    )
    verification_job = app.request_verification(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        submission_id=submission.id,
        idempotency_key=f"acceptance-verification-{setup.suffix}",
    )
    verification_result = _dispatcher(
        store,
        handlers={
            "publication.verify": PublicationVerificationHandler(
                store=store,
                repository=repository,
                verifier=ControlledUrlVerifier(),
                lease_for=LEASE_FOR,
            )
        },
        worker_id=f"acceptance-verification-{setup.suffix}",
    ).process(job_id=verification_job.id, project_id=project_id)
    if verification_result["status"] != "verified":
        raise AssertionError(f"publication URL did not verify: {verification_result}")
    verified_submission = app.get_submission(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        submission_id=submission.id,
    )
    if verified_submission is None or verified_submission.status != "verified":
        raise AssertionError("verified submission projection was not persisted")
    scheduled_windows = _measurement_windows(store, project_id, submission.id)
    if scheduled_windows != (28, 56, 84):
        raise AssertionError("verification must schedule T+28, T+56 and T+84")
    measurement_dispatcher = _dispatcher(
        store,
        handlers={"placement.measure": MeasurementWindowHandler(repository)},
        worker_id=f"acceptance-measurement-{setup.suffix}",
    )
    for offset in scheduled_windows:
        measurement_job_id = _make_measurement_job_due(
            store, project_id, submission.id, due_offset_days=offset
        )
        opened = measurement_dispatcher.process(
            job_id=measurement_job_id, project_id=project_id
        )
        if opened["status"] != "awaiting_manual_samples":
            raise AssertionError(f"T+{offset} collection task did not open: {opened}")
    tasks = app.list_measurement_collection_tasks(
        project_id=project_id,
        campaign_id=setup.campaign.id,
        submission_id=submission.id,
        status="open",
    )
    if tuple(item.measurement_window for item in tasks) != ("t28", "t56", "t84"):
        raise AssertionError(
            "scheduled jobs must persist queryable T+28, T+56 and T+84 collection tasks"
        )
    return PlacementResult(
        store,
        brief,
        evidence_attempt,
        tuple(prompt_bindings),
        tuple(simulations),
        bundle,
        generation_job,
        package,
        claims,
        review,
        export,
        publication,
        verified_submission,
        tasks,
        submitted_url,
        scheduled_windows,
        terminal_artifact_replay_count,
    )


def _artifact_dispatcher(
    store: PostgresDurableJobStore, setup: AcceptanceSetup
) -> PlacementWorkerDispatcher:
    return _dispatcher(
        store,
        handlers={
            "artifact.finalize": ArtifactFinalizeHandler(
                store=store,
                repository=PlacementArtifactRepository(store),
                object_store=setup.artifact_store,
            )
        },
        worker_id=f"acceptance-artifact-{setup.suffix}",
    )


def _dispatcher(
    store: PostgresDurableJobStore,
    *,
    handlers: Mapping[str, JobHandler],
    worker_id: str,
) -> PlacementWorkerDispatcher:
    return PlacementWorkerDispatcher(
        store=store,
        handlers=handlers,
        worker_id=worker_id,
        lease_for=LEASE_FOR,
    )


def _artifact_job_id(
    store: PostgresDurableJobStore,
    *,
    project_id: UUID,
    resource_kind: str,
    resource_id: UUID,
) -> UUID:
    connection = store.open_project(project_id)
    try:
        row = connection.execute(
            """SELECT job_id FROM artifact_finalize_outbox
               WHERE project_id = %s AND resource_kind = %s AND resource_id = %s""",
            (project_id, resource_kind, resource_id),
        ).fetchone()
        connection.commit()
    finally:
        connection.close()
    if row is None:
        raise AssertionError(f"{resource_kind} has no artifact finalization job")
    return row[0]


def _assert_terminal_artifact_replay(
    store: PostgresDurableJobStore,
    dispatcher: PlacementWorkerDispatcher,
    setup: AcceptanceSetup,
    *,
    job_id: UUID,
) -> None:
    before = _artifact_record(store, setup.project_id, job_id)
    artifact_store = setup.artifact_store
    object_count = (
        len(artifact_store.objects) if isinstance(artifact_store, MemoryArtifactStore) else None
    )
    repeated = dispatcher.process(job_id=job_id, project_id=setup.project_id)
    after = _artifact_record(store, setup.project_id, job_id)
    if repeated["status"] != "terminal":
        raise AssertionError("a finalized artifact job was not observed as terminal")
    if after != before:
        raise AssertionError("terminal artifact observation mutated its immutable record")
    if (
        object_count is not None
        and isinstance(artifact_store, MemoryArtifactStore)
        and len(artifact_store.objects) != object_count
    ):
        raise AssertionError("terminal artifact observation wrote another object")


def _artifact_record(
    store: PostgresDurableJobStore, project_id: UUID, job_id: UUID
) -> tuple[object, ...]:
    connection = store.open_project(project_id)
    try:
        rows = connection.execute(
            """SELECT status, attempt_count, final_uri, finalized_at, content_hash
               FROM artifact_finalize_outbox
               WHERE project_id = %s AND job_id = %s""",
            (project_id, job_id),
        ).fetchall()
        connection.commit()
    finally:
        connection.close()
    if len(rows) != 1 or rows[0][0] != "finalized":
        raise AssertionError("finalized artifact record is missing or duplicated")
    return tuple(rows[0])
