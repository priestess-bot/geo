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
    PackageVersion,
    PromptBundleView,
    PublicationRequest,
    Review,
    Submission,
)
from geo_core.placements.worker_composition import (
    ArtifactFinalizeHandler,
    EvidencePackHandler,
    GenerationHandler,
    JobHandler,
    PlacementWorkerDispatcher,
    PublicationVerificationHandler,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository

from scripts.geo_acceptance.adapters import ControlledUrlVerifier, model_gateway
from scripts.geo_acceptance.contracts import (
    AcceptanceConfig,
    CHANNELS,
    MODEL,
    MODEL_POLICY_HASH,
)
from scripts.geo_acceptance.monitoring import BaselineResult
from scripts.geo_acceptance.setup import AcceptanceSetup, EXPERIENCE_TEXT


LEASE_FOR = timedelta(seconds=30)


@dataclass(frozen=True)
class PlacementResult:
    store: PostgresDurableJobStore
    brief: BriefVersion
    evidence_attempt: EvidencePackAttempt
    prompt_bindings: tuple[Mapping[str, object], ...]
    prompt_bundle: PromptBundleView
    generation_job: JobReference
    package: PackageVersion
    claims: tuple[Claim, ...]
    review: Review
    export: ExportReceipt
    publication: PublicationRequest
    submission: Submission
    submitted_url: str
    scheduled_windows: tuple[int, ...]


def run_placement(
    config: AcceptanceConfig,
    setup: AcceptanceSetup,
    baseline: BaselineResult,
) -> PlacementResult:
    app = setup.placement
    project_id = setup.project_id
    brief = app.create_brief_version(
        project_id=project_id,
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
        project_id=project_id, attempt_id=evidence_attempt.id
    )
    evidence_ids = {item["id"] for item in evidence_items}
    if not {setup.fact.id, setup.experience.id}.issubset(evidence_ids):
        raise AssertionError("the evidence pack omitted governed project evidence")

    bindings = app.install_default_prompt_catalog(
        project_id=project_id, actor_id=setup.owner.identity_id
    )
    if {str(item["task_key"]) for item in bindings} != {
        item["channel"] for item in CHANNELS
    }:
        raise AssertionError("the editable prompt catalog must cover all selected channels")
    owned_binding = next(item for item in bindings if item["task_key"] == "owned_site")
    bundle = app.create_prompt_bundle(
        project_id=project_id,
        brief_version_id=brief.id,
        evidence_pack_attempt_id=evidence_attempt.id,
        release_id=cast(UUID, owned_binding["template_release_id"]),
        variables={},
        model_policy_hash=MODEL_POLICY_HASH,
    )
    artifact_dispatcher = _artifact_dispatcher(store, setup)
    bundle_job = _artifact_job_id(
        store, project_id=project_id, resource_kind="prompt_bundle", resource_id=bundle.id
    )
    bundle_result = artifact_dispatcher.process(job_id=bundle_job, project_id=project_id)
    if bundle_result["status"] != "finalized":
        raise AssertionError(f"prompt bundle artifact did not finalize: {bundle_result}")

    generation_job = app.request_generation(
        project_id=project_id,
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
        project_id=project_id, opportunity_id=setup.owned_opportunity.id
    )[-1]
    claims = app.list_claims(project_id=project_id, version_id=package.id)
    if not claims or any(item.support_status != "supported" for item in claims):
        raise AssertionError("generated factual claims must be fully supported")
    app.submit_for_review(
        project_id=project_id,
        version_id=package.id,
        submitted_by=setup.owner.identity_id,
    )
    review = app.submit_review(
        project_id=project_id,
        version_id=package.id,
        reviewer_id=setup.reviewer_identity_id,
        decision="approved",
        claim_inventory_complete=True,
        extracted_claim_support_confirmed=True,
        score=95,
        notes="Controlled acceptance: subjects, evidence, disclosure and claims verified.",
    )

    if app.list_publication_requests(project_id=project_id, version_id=package.id):
        raise AssertionError("publication intent exists before export")
    export = app.export_package(
        project_id=project_id,
        version_id=package.id,
        requested_by=setup.owner.identity_id,
    )
    if app.list_publication_requests(project_id=project_id, version_id=package.id):
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
    exported = app.download_export(
        project_id=project_id, version_id=package.id, export_id=export.id
    )
    if exported.content_hash != export.content_hash:
        raise AssertionError("downloaded export no longer matches its immutable receipt")

    publication = app.request_publication(
        project_id=project_id,
        version_id=package.id,
        destination_id=setup.destinations[0].id,
        requested_by=setup.owner.identity_id,
        publication_attempt=1,
        idempotency_key=f"acceptance-publication-{setup.suffix}",
        restricted_policy_acknowledged=False,
        policy_basis=None,
    )
    submitted_url = f"https://www.advinsys.com.au/geo-acceptance/{setup.suffix}"
    submission = app.create_submission(
        project_id=project_id,
        publication_request_id=publication.id,
        submitted_url=submitted_url,
        provider_submission_id=f"controlled-{setup.suffix}",
    )
    verification_job = app.request_verification(
        project_id=project_id,
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
        project_id=project_id, submission_id=submission.id
    )
    if verified_submission is None or verified_submission.status != "verified":
        raise AssertionError("verified submission projection was not persisted")
    scheduled_windows = _measurement_windows(store, project_id, submission.id)
    if scheduled_windows != (28, 56, 84):
        raise AssertionError("verification must schedule T+28, T+56 and T+84")
    return PlacementResult(
        store,
        brief,
        evidence_attempt,
        bindings,
        bundle,
        generation_job,
        package,
        claims,
        review,
        export,
        publication,
        verified_submission,
        submitted_url,
        scheduled_windows,
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


def _measurement_windows(
    store: PostgresDurableJobStore, project_id: UUID, submission_id: UUID
) -> tuple[int, ...]:
    connection = store.open_project(project_id)
    try:
        rows = connection.execute(
            """SELECT due_offset_days FROM measurement_job_specs
               WHERE project_id = %s AND submission_id = %s ORDER BY due_offset_days""",
            (project_id, submission_id),
        ).fetchall()
        connection.commit()
    finally:
        connection.close()
    return tuple(int(row[0]) for row in rows)
