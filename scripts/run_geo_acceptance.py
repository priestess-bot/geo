#!/usr/bin/env python3
"""Run one governed GEO lifecycle against the stable application services.

The default mode is deterministic: PostgreSQL, durable jobs, artifact finalization,
review, publication and reporting are real, while the model and public URL verifier
are controlled adapters. Paid DeepSeek use is opt-in with ``--live-deepseek``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping, Protocol, cast
from uuid import UUID, uuid4

import psycopg

from geo_core.access.membership_service import AccessMembershipService
from geo_core.access.postgres import PsycopgAccessUnitOfWorkFactory
from geo_core.access.service import AccessApplicationService
from geo_core.catalog.application import CatalogApplication
from geo_core.catalog.domain import (
    Confidentiality,
    EntityType,
    EvidenceDraft,
    EvidenceItemType,
    EvidenceSnapshot,
    PublicCitation,
    SubjectRole,
    UsageRights,
)
from geo_core.catalog.postgres import PsycopgCatalogUnitOfWorkFactory
from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.model_gateway import (
    ModelCallBudget,
    ModelGateway,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
)
from geo_core.model_gateway.deepseek import (
    DeepSeekGateway,
    default_deepseek_capability_registry,
)
from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.domain import (
    CitationDraft,
    Device,
    MeasurementWindow,
    ObservationDraft,
    Platform,
    ResultStatus,
    VerificationStatus,
)
from geo_core.monitoring.postgres import PsycopgMonitoringUnitOfWorkFactory
from geo_core.object_store import RetrievedObject, StoredObject
from geo_core.object_store_config import build_object_store
from geo_core.placements.application import PlacementApplication
from geo_core.placements.artifact_worker import PlacementArtifactRepository
from geo_core.placements.domain import ConsumerExperience
from geo_core.placements.ports import UnitOfWorkFactory
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.placements.url_verifier import PublicUrlVerifier, UrlVerificationResult
from geo_core.placements.worker_composition import (
    ArtifactFinalizeHandler,
    EvidencePackHandler,
    GenerationHandler,
    JobHandler,
    PlacementWorkerDispatcher,
    PublicationVerificationHandler,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository


CHANNELS: tuple[dict[str, str], ...] = (
    {
        "channel": "owned_site",
        "key": "advinsys.com.au",
        "url": "https://www.advinsys.com.au/",
    },
    {
        "channel": "productreview",
        "key": "productreview.com.au/advinsys",
        "url": "https://www.productreview.com.au/",
    },
    {
        "channel": "youtube",
        "key": "channel/UCmyUEh-krsFHszEC8XFKtuQ",
        "url": "https://www.youtube.com/",
    },
    {
        "channel": "reddit",
        "key": "disclosed-brand-participation",
        "url": "https://www.reddit.com/",
    },
    {
        "channel": "amazon",
        "key": "ADVINSYS-AU-store",
        "url": "https://www.amazon.com.au/",
    },
    {
        "channel": "ozbargain",
        "key": "authorised-merchant-deals",
        "url": "https://www.ozbargain.com.au/",
    },
    {
        "channel": "tiktok",
        "key": "@advinsys27",
        "url": "https://www.tiktok.com/",
    },
    {
        "channel": "instagram",
        "key": "@advinsysau",
        "url": "https://www.instagram.com/",
    },
    {
        "channel": "quora",
        "key": "disclosed-expert-answers",
        "url": "https://www.quora.com/",
    },
)

PRODUCT_URL = "https://www.advinsys.com.au/products/triple-cam-ai-vision-robot-mower-v600"
MODEL = "deepseek-v4-flash"
MODEL_POLICY_HASH = hashlib.sha256(b"geo-acceptance-model-policy-v1").hexdigest()
LEASE_FOR = timedelta(seconds=30)


@dataclass(frozen=True)
class AcceptanceConfig:
    app_database_url: str
    worker_database_url: str
    run_id: str
    output_path: Path
    live_deepseek: bool = False
    deepseek_key_file: Path | None = None
    runtime_object_store: bool = False

    def validate(self) -> None:
        if not self.app_database_url.strip() or not self.worker_database_url.strip():
            raise ValueError("app and worker PostgreSQL URLs are required")
        if not self.run_id.strip() or len(self.run_id) > 100:
            raise ValueError("run_id must contain between 1 and 100 characters")
        if self.live_deepseek:
            if self.deepseek_key_file is None:
                raise ValueError("--live-deepseek requires --deepseek-key-file")
            if not self.deepseek_key_file.is_file():
                raise ValueError("the DeepSeek key file does not exist")


class ArtifactStore(Protocol):
    def put_object(
        self, *, key: str, content: bytes, content_type: str, expected_hash: str
    ) -> StoredObject: ...

    def get_object(self, *, key: str, expected_hash: str) -> RetrievedObject: ...


class MemoryArtifactStore:
    """Artifact adapter for deterministic acceptance and tests."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put_object(
        self, *, key: str, content: bytes, content_type: str, expected_hash: str
    ) -> StoredObject:
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected_hash:
            raise ValueError("artifact hash does not match pending metadata")
        self.objects[key] = (content, content_type)
        return StoredObject(
            uri=f"s3://geo-artifacts/{key}",
            bucket="geo-artifacts",
            key=key,
            content_type=content_type,
            content_hash=digest,
            etag=f'"{digest}"',
        )

    def get_object(self, *, key: str, expected_hash: str) -> RetrievedObject:
        content, content_type = self.objects[key]
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected_hash:
            raise ValueError("stored artifact hash no longer matches its receipt")
        return RetrievedObject(
            content=content,
            bucket="geo-artifacts",
            key=key,
            content_type=content_type,
            content_hash=digest,
            etag=f'"{digest}"',
        )


class DeterministicGateway:
    """Schema-valid model double; it cannot consume provider credentials."""

    provider = "acceptance-fake"

    def __init__(self, *, evidence_id: UUID, product_url: str) -> None:
        self.evidence_id = evidence_id
        self.product_url = product_url

    def generate(
        self,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult:
        del request, policy
        budget.consume()
        return ModelGatewayResult(
            output={
                "content_json": {
                    "title": "TerraMow V600 official product information",
                    "body": (
                        "ADVINSYS identifies TerraMow V600 as a Triple-Cam AI Vision "
                        "Robot Mower in the robotic lawn mower category."
                    ),
                    "disclosure": "Official information published by ADVINSYS.",
                    "cta_url": self.product_url,
                    "submission_notes": "Publish only through an authorised brand account.",
                },
                "rendered_text": (
                    "Official information published by ADVINSYS. TerraMow V600 is "
                    "identified on the official product page as a Triple-Cam AI Vision "
                    "Robot Mower in the robotic lawn mower category."
                ),
                "claims": [
                    {
                        "text": (
                            "TerraMow V600 is identified as a Triple-Cam AI Vision "
                            "Robot Mower in the robotic lawn mower category."
                        ),
                        "kind": "factual",
                        "support_status": "supported",
                        "evidence_item_ids": [str(self.evidence_id)],
                    }
                ],
                "internal_evidence_refs": [str(self.evidence_id)],
                "public_citation_refs": [str(self.evidence_id)],
            },
            call_log_id=uuid4(),
            provider_request_id="deterministic-acceptance",
            configured_model=MODEL,
            provider_reported_model="deterministic-acceptance",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=Decimal("0"),
            finish_reason="stop",
            response_hash=hashlib.sha256(
                f"{self.evidence_id}:deterministic-acceptance".encode()
            ).hexdigest(),
        )


class ControlledUrlVerifier(PublicUrlVerifier):
    """Verifier double that checks the worker supplied all governed expectations."""

    def verify(
        self,
        url: str,
        *,
        expected_text_fragments: tuple[str, ...],
        required_disclosures: tuple[str, ...],
        expected_links: tuple[str, ...],
        allowed_hosts: tuple[str, ...],
    ) -> UrlVerificationResult:
        for field, value in (
            ("expected_text_fragments", expected_text_fragments),
            ("required_disclosures", required_disclosures),
            ("expected_links", expected_links),
        ):
            if not value:
                raise ValueError(f"verification input omitted {field}")
        if "www.advinsys.com.au" not in allowed_hosts:
            raise ValueError("verification did not retain the destination allowlist")
        checked_at = datetime.now(UTC)
        return UrlVerificationResult(
            success=True,
            status_code=200,
            final_url=url,
            checked_at=checked_at,
            metadata_hash=hashlib.sha256(f"{url}:{checked_at.isoformat()}".encode()).hexdigest(),
            accessibility=True,
            content_match=True,
            disclosure_match=True,
            link_match=True,
        )


def run_acceptance(config: AcceptanceConfig) -> dict[str, object]:
    """Run the complete controlled lifecycle and return its immutable ID manifest."""

    config.validate()
    app_url = config.app_database_url.strip()
    worker_url = config.worker_database_url.strip()
    suffix = hashlib.sha256(config.run_id.encode()).hexdigest()[:10]

    catalog = CatalogApplication(
        PsycopgCatalogUnitOfWorkFactory(app_url), development_bootstrap_allowed=True
    )
    access_factory = PsycopgAccessUnitOfWorkFactory(app_url)
    access = AccessApplicationService(
        access_factory, token_secret=f"geo-acceptance-token-secret-{suffix}"
    )
    membership = AccessMembershipService(access_factory)
    bootstrap = catalog.bootstrap_development(
        tenant_name=f"GEO acceptance {suffix}",
        identity_subject=f"owner-{suffix}",
        identity_email=f"owner-{suffix}@example.com",
        project_name=f"ADVINSYS acceptance {suffix}",
    )
    owner = access.authenticate_development(
        identity_id=bootstrap.identity_id, tenant_id=bootstrap.tenant_id
    )
    project_id = bootstrap.project.id
    reviewer = membership.add_member(
        owner,
        project_id=project_id,
        issuer="https://identity.example.com/",
        subject=f"reviewer-{suffix}",
        email=f"reviewer-{suffix}@example.com",
        display_name=f"Acceptance Reviewer {suffix}",
        role="admin",
        idempotency_key=f"acceptance-add-reviewer-{suffix}",
    ).membership
    invitation = access.create_invitation(
        owner,
        project_id=project_id,
        email=f"customer-{suffix}@example.com",
        role="customer",
        target_surface="customer",
        expires_in_hours=1,
        idempotency_key=f"acceptance-customer-invitation-{suffix}",
    )
    customer_session = access.redeem_invitation(
        invitation_id=invitation.invitation.id,
        invite_token=invitation.invite_token,
        requested_surface="customer",
        idempotency_key=f"acceptance-customer-redemption-{suffix}",
    )

    brand = catalog.create_entity(
        owner,
        project_id=project_id,
        entity_type=EntityType.BRAND,
        canonical_name="ADVINSYS",
        canonical_url="https://www.advinsys.com.au/",
        attributes={"market": "Australia"},
    )
    product = catalog.create_entity(
        owner,
        project_id=project_id,
        entity_type=EntityType.PRODUCT,
        canonical_name="TerraMow V600",
        canonical_url=PRODUCT_URL,
        attributes={"category": "robotic lawn mower"},
    )
    market = catalog.create_market_profile(
        owner,
        project_id=project_id,
        market_code="AU",
        locale="en-AU",
        timezone="Australia/Sydney",
        rules={"language": "English", "currency": "AUD"},
    )
    fact_text = (
        "The official ADVINSYS product page identifies TerraMow V600 as a Triple-Cam "
        "AI Vision Robot Mower in the robotic lawn mower category."
    )
    fact = catalog.create_evidence(
        owner,
        project_id=project_id,
        draft=_evidence_draft(
            item_type=EvidenceItemType.APPROVED_FACT,
            subject_entity_id=product.id,
            text=fact_text,
            source_url=PRODUCT_URL,
            source_title="ADVINSYS TerraMow V600 product page",
            usage_rights=UsageRights.OWNED,
        ),
    )
    experience_text = (
        "A consumer described using the mower for routine lawn care and checking the "
        "completed area after each run."
    )
    experience = catalog.create_evidence(
        owner,
        project_id=project_id,
        draft=_evidence_draft(
            item_type=EvidenceItemType.CONSUMER_EXPERIENCE,
            subject_entity_id=product.id,
            text=experience_text,
            source_url=PRODUCT_URL,
            source_title="Authorised consumer description supplied to ADVINSYS",
            usage_rights=UsageRights.AUTHORISED_EXPERIENCE,
        ),
    )

    artifact_store: ArtifactStore = (
        build_object_store() if config.runtime_object_store else MemoryArtifactStore()
    )
    placement = PlacementApplication(
        cast(
            UnitOfWorkFactory,
            placement_uow_factory(lambda: psycopg.connect(app_url)),
        ),
        artifact_reader=artifact_store,
    )
    destinations = tuple(
        placement.create_destination(
            project_id=project_id,
            publication_channel=channel["channel"],
            destination_key=f"{channel['key']}:{suffix}",
            operation_mode="manual",
            destination_account_id=(
                f"authorised-{suffix}" if channel["channel"] == "owned_site" else None
            ),
            canonical_url=channel["url"],
        )
        for channel in CHANNELS
    )
    campaign, created_opportunities = placement.create_campaign(
        project_id=project_id,
        market_profile_id=market.id,
        primary_product_entity_id=product.id,
        name=f"TerraMow V600 recommendation influence {suffix}",
        objective="recommendation_influence",
        actor_id=owner.identity_id,
        destination_ids=tuple(item.id for item in destinations),
        rationale="Create one governed manual placement task for every selected channel.",
    )
    if len(created_opportunities) != len(CHANNELS):
        raise AssertionError("every selected channel must create a persistent task")
    if any(item.status != "blocked" for item in created_opportunities):
        raise AssertionError("unreviewed destinations must fail closed")

    owned_destination = destinations[0]
    owned_opportunity = created_opportunities[0]
    placement.review_destination_policy(
        project_id=project_id,
        destination_id=owned_destination.id,
        status="approved",
        rules={"manual_submission_only": True, "official_content": True},
        identity_requirements={"brand_account_authorisation": "required"},
        disclosure_requirements={"brand_relationship": "required"},
        allowed_hosts=("www.advinsys.com.au",),
        reviewed_by=owner.identity_id,
    )
    placement.transition_opportunity(
        project_id=project_id,
        opportunity_id=owned_opportunity.id,
        command="reopen",
        reason="official site policy and access were reviewed",
    )
    owned_opportunity = placement.transition_opportunity(
        project_id=project_id,
        opportunity_id=owned_opportunity.id,
        command="qualify",
        reason="owned destination has evidence, policy and account authority",
    )

    monitoring = MonitoringApplication(PsycopgMonitoringUnitOfWorkFactory(app_url))
    protocol = monitoring.create_protocol(
        owner,
        project_id=project_id,
        campaign_id=campaign.id,
        market_profile_id=market.id,
        name=f"Controlled recommendation protocol {suffix}",
        platform=Platform.CHATGPT_SEARCH,
        locale="en-AU",
        device=Device.DESKTOP,
        sample_size=1,
        window_days=28,
    )
    suggestion = monitoring.suggest_query(
        owner,
        project_id=project_id,
        protocol_id=protocol.id,
        query_text="Which robotic lawn mower should I consider in Australia?",
        query_kind="recommendation",
        rationale="Represents a non-branded consumer recommendation question.",
    )
    protocol_query = monitoring.approve_suggestion(
        owner,
        project_id=project_id,
        protocol_id=protocol.id,
        suggestion_id=suggestion.id,
    )
    monitoring.approve_protocol(owner, project_id=project_id, protocol_id=protocol.id)
    protocol = monitoring.freeze_protocol(owner, project_id=project_id, protocol_id=protocol.id)
    baseline = monitoring.import_observation(
        owner,
        project_id=project_id,
        protocol_id=protocol.id,
        draft=_observation(
            query_id=protocol_query.monitoring_query_id,
            window=MeasurementWindow.BASELINE,
            recommendation_present=False,
            product_mentioned=False,
        ),
        idempotency_key=f"acceptance-baseline-{suffix}",
    )
    baseline_metric = monitoring.compute_metrics(
        owner,
        project_id=project_id,
        protocol_id=protocol.id,
        window=MeasurementWindow.BASELINE,
    )

    brief = placement.create_brief_version(
        project_id=project_id,
        opportunity_id=owned_opportunity.id,
        primary_brand_entity_id=brand.id,
        goals={
            "consumer_query": protocol_query.query_text,
            "goal": "publish source-grounded official product information",
        },
        constraints={"locale": "en-AU", "manual_submission_only": True},
        compared_entity_ids=(),
        allowed_subject_entity_ids=(brand.id, product.id),
        actor_id=owner.identity_id,
        base_version_id=None,
        consumer_experience=ConsumerExperience(
            description=experience_text,
            source="consumer description supplied to ADVINSYS",
            usage_rights="authorised_experience",
            disclosure="Official ADVINSYS content based on an authorised description.",
        ),
        authenticity_risks=(),
    )
    evidence_attempt, evidence_job = placement.create_evidence_attempt(
        project_id=project_id,
        brief_version_id=brief.id,
        idempotency_key=f"acceptance-evidence-{suffix}",
    )

    store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
    worker_repository = PlacementWorkerRepository(store)
    evidence_result = _dispatcher(
        store,
        handlers={"evidence_pack.build": EvidencePackHandler(worker_repository)},
        worker_id=f"acceptance-evidence-{suffix}",
    ).process(job_id=evidence_job.id, project_id=project_id)
    if evidence_result["status"] != "ready":
        raise AssertionError(f"evidence pack did not become ready: {evidence_result}")
    evidence_items = placement.list_evidence_attempt_items(
        project_id=project_id, attempt_id=evidence_attempt.id
    )
    evidence_ids = {item["id"] for item in evidence_items}
    if not {fact.id, experience.id}.issubset(evidence_ids):
        raise AssertionError("the evidence pack omitted governed project evidence")

    bindings = placement.install_default_prompt_catalog(
        project_id=project_id, actor_id=owner.identity_id
    )
    if {str(item["task_key"]) for item in bindings} != {
        item["channel"] for item in CHANNELS
    }:
        raise AssertionError("the editable prompt catalog must cover all selected channels")
    owned_binding = next(item for item in bindings if item["task_key"] == "owned_site")
    bundle = placement.create_prompt_bundle(
        project_id=project_id,
        brief_version_id=brief.id,
        evidence_pack_attempt_id=evidence_attempt.id,
        release_id=cast(UUID, owned_binding["template_release_id"]),
        variables={},
        model_policy_hash=MODEL_POLICY_HASH,
    )
    bundle_artifact_job = _artifact_job_id(
        store, project_id=project_id, resource_kind="prompt_bundle", resource_id=bundle.id
    )
    artifact_dispatcher = _dispatcher(
        store,
        handlers={
            "artifact.finalize": ArtifactFinalizeHandler(
                store=store,
                repository=PlacementArtifactRepository(store),
                object_store=artifact_store,
            )
        },
        worker_id=f"acceptance-artifact-{suffix}",
    )
    bundle_result = artifact_dispatcher.process(
        job_id=bundle_artifact_job, project_id=project_id
    )
    if bundle_result["status"] != "finalized":
        raise AssertionError(f"prompt bundle artifact did not finalize: {bundle_result}")

    gateway = _gateway(config, evidence_id=fact.id)
    generation_job = placement.request_generation(
        project_id=project_id,
        prompt_bundle_id=bundle.id,
        configured_model=MODEL,
        model_call_budget=2,
        idempotency_key=f"acceptance-generation-{suffix}",
        requested_by=owner.identity_id,
    )
    generation_result = _dispatcher(
        store,
        handlers={
            "placement.generate": GenerationHandler(
                store=store,
                repository=worker_repository,
                gateway=gateway,
                lease_for=LEASE_FOR,
            )
        },
        worker_id=f"acceptance-generation-{suffix}",
    ).process(job_id=generation_job.id, project_id=project_id)
    if generation_result["status"] != "succeeded":
        raise AssertionError(f"generation did not succeed: {generation_result}")
    package = placement.list_package_versions(
        project_id=project_id, opportunity_id=owned_opportunity.id
    )[-1]
    claims = placement.list_claims(project_id=project_id, version_id=package.id)
    if not claims or any(item.support_status != "supported" for item in claims):
        raise AssertionError("generated factual claims must be fully supported")
    placement.submit_for_review(
        project_id=project_id, version_id=package.id, submitted_by=owner.identity_id
    )
    review = placement.submit_review(
        project_id=project_id,
        version_id=package.id,
        reviewer_id=reviewer.identity_id,
        decision="approved",
        claim_inventory_complete=True,
        extracted_claim_support_confirmed=True,
        score=95,
        notes="Controlled acceptance: subjects, evidence, disclosure and claims verified.",
    )

    publications_before = placement.list_publication_requests(
        project_id=project_id, version_id=package.id
    )
    export = placement.export_package(
        project_id=project_id, version_id=package.id, requested_by=owner.identity_id
    )
    publications_after_export = placement.list_publication_requests(
        project_id=project_id, version_id=package.id
    )
    if publications_before or publications_after_export:
        raise AssertionError("export must not create publication intent")
    export_artifact_job = _artifact_job_id(
        store, project_id=project_id, resource_kind="package_export", resource_id=export.id
    )
    export_result = artifact_dispatcher.process(
        job_id=export_artifact_job, project_id=project_id
    )
    if export_result["status"] != "finalized":
        raise AssertionError(f"package export artifact did not finalize: {export_result}")
    exported_bytes = placement.download_export(
        project_id=project_id, version_id=package.id, export_id=export.id
    )
    if exported_bytes.content_hash != export.content_hash:
        raise AssertionError("downloaded export no longer matches its immutable receipt")

    publication = placement.request_publication(
        project_id=project_id,
        version_id=package.id,
        destination_id=owned_destination.id,
        requested_by=owner.identity_id,
        publication_attempt=1,
        idempotency_key=f"acceptance-publication-{suffix}",
        restricted_policy_acknowledged=False,
        policy_basis=None,
    )
    submitted_url = f"https://www.advinsys.com.au/geo-acceptance/{suffix}"
    submission = placement.create_submission(
        project_id=project_id,
        publication_request_id=publication.id,
        submitted_url=submitted_url,
        provider_submission_id=f"controlled-{suffix}",
    )
    verification_job = placement.request_verification(
        project_id=project_id,
        submission_id=submission.id,
        idempotency_key=f"acceptance-verification-{suffix}",
    )
    verification_result = _dispatcher(
        store,
        handlers={
            "publication.verify": PublicationVerificationHandler(
                store=store,
                repository=worker_repository,
                verifier=ControlledUrlVerifier(),
                lease_for=LEASE_FOR,
            )
        },
        worker_id=f"acceptance-verification-{suffix}",
    ).process(job_id=verification_job.id, project_id=project_id)
    if verification_result["status"] != "verified":
        raise AssertionError(f"publication URL did not verify: {verification_result}")
    verified_submission = placement.get_submission(
        project_id=project_id, submission_id=submission.id
    )
    if verified_submission is None or verified_submission.status != "verified":
        raise AssertionError("verified submission projection was not persisted")
    scheduled_windows = _measurement_windows(store, project_id, submission.id)
    if scheduled_windows != (28, 56, 84):
        raise AssertionError("verification must schedule T+28, T+56 and T+84")

    placement_measurement = placement.record_measurement(
        project_id=project_id,
        submission_id=submission.id,
        monitoring_query_id=protocol_query.monitoring_query_id,
        measured_at=datetime.now(UTC),
        citation_present=True,
        recommendation_position=1,
        result_snapshot_uri=f"s3://geo-artifacts/acceptance/{suffix}/placement-result.json",
        metrics={"mode": "controlled_acceptance", "window": "t28"},
    )
    t28_observation = monitoring.import_observation(
        owner,
        project_id=project_id,
        protocol_id=protocol.id,
        draft=_observation(
            query_id=protocol_query.monitoring_query_id,
            window=MeasurementWindow.T28,
            recommendation_present=True,
            product_mentioned=True,
            citation=CitationDraft(
                url=submitted_url,
                title="Controlled ADVINSYS acceptance placement",
                verification_status=VerificationStatus.PASSED,
                verified_at=datetime.now(UTC),
                destination_id=owned_destination.id,
                submission_id=submission.id,
            ),
        ),
        idempotency_key=f"acceptance-t28-observation-{suffix}",
    )
    t28_metric = monitoring.compute_metrics(
        owner,
        project_id=project_id,
        protocol_id=protocol.id,
        window=MeasurementWindow.T28,
    )
    report = monitoring.generate_report(
        owner,
        project_id=project_id,
        metric_snapshot_id=t28_metric.id,
        title=f"Controlled GEO acceptance report {suffix}",
    )
    report = monitoring.approve_report(
        owner, project_id=project_id, report_id=report.id
    )

    customer = customer_session.principal
    customer_metrics = monitoring.list_metrics(customer, project_id=project_id)
    customer_urls = monitoring.list_verified_urls(customer, project_id=project_id)
    customer_reports = monitoring.list_reports(
        customer, project_id=project_id, approved_only=True
    )
    if not customer_metrics or not customer_urls or not customer_reports:
        raise AssertionError("customer-safe metrics, verified URL and report are incomplete")
    if any(item.status != "approved" for item in customer_reports):
        raise AssertionError("customer projection exposed an unapproved report")

    opportunities = placement.list_opportunities(
        project_id=project_id, campaign_id=campaign.id
    )
    opportunities_by_destination = {item.destination_id: item for item in opportunities}
    if set(opportunities_by_destination) != {item.id for item in destinations}:
        raise AssertionError("the persisted channel task matrix changed after creation")
    result: dict[str, object] = {
        "run_id": config.run_id,
        "mode": "live_deepseek" if config.live_deepseek else "deterministic",
        "project": {
            "tenant_id": bootstrap.tenant_id,
            "project_id": project_id,
            "owner_identity_id": owner.identity_id,
            "reviewer_identity_id": reviewer.identity_id,
            "customer_identity_id": customer.identity_id,
            "brand_entity_id": brand.id,
            "product_entity_id": product.id,
            "market_profile_id": market.id,
            "evidence_item_ids": [fact.id, experience.id],
        },
        "campaign": {
            "campaign_id": campaign.id,
            "protocol_id": protocol.id,
            "monitoring_query_id": protocol_query.monitoring_query_id,
            "baseline_observation_id": baseline.id,
            "baseline_metric_id": baseline_metric.id,
            "t28_observation_id": t28_observation.id,
            "t28_metric_id": t28_metric.id,
            "report_id": report.id,
        },
        "channels": [
            {
                "publication_channel": destination.publication_channel,
                "destination_id": destination.id,
                "opportunity_id": opportunity.id,
                "task_status": opportunity.status,
            }
            for destination in destinations
            for opportunity in (opportunities_by_destination[destination.id],)
        ],
        "placement": {
            "brief_version_id": brief.id,
            "evidence_pack_attempt_id": evidence_attempt.id,
            "prompt_binding_count": len(bindings),
            "prompt_bundle_id": bundle.id,
            "prompt_bundle_hash": bundle.bundle_hash,
            "generation_job_id": generation_job.id,
            "package_version_id": package.id,
            "package_content_hash": package.content_hash,
            "claim_ids": [item.id for item in claims],
            "review_id": review.id,
            "export_id": export.id,
            "publication_request_id": publication.id,
            "submission_id": submission.id,
            "scheduled_measurement_offsets": list(scheduled_windows),
            "placement_measurement_id": placement_measurement.id,
        },
        "customer_projection": {
            "metric_count": len(customer_metrics),
            "verified_url_count": len(customer_urls),
            "approved_report_count": len(customer_reports),
        },
        "assertions": {
            "selected_channel_count": len(CHANNELS),
            "persistent_task_count": len(opportunities),
            "blocked_task_count": sum(item.status == "blocked" for item in opportunities),
            "approved_task_count": sum(item.status == "qualified" for item in opportunities),
            "export_created_publication": False,
            "claim_inventory_complete": review.claim_inventory_complete,
            "review_submitter_differs_from_reviewer": (
                review.submitted_for_review_by != review.reviewer_id
            ),
            "customer_projection_approved_only": True,
        },
        "boundaries": {
            "external_publication_performed": False,
            "public_url_verification_mode": "controlled",
            "monitoring_data_mode": "controlled_acceptance",
            "causal_claim": False,
        },
    }
    _write_result(config.output_path, result)
    return result


def _evidence_draft(
    *,
    item_type: EvidenceItemType,
    subject_entity_id: UUID,
    text: str,
    source_url: str,
    source_title: str,
    usage_rights: UsageRights,
) -> EvidenceDraft:
    return EvidenceDraft(
        item_type=item_type,
        source_id=uuid4(),
        subject_entity_id=subject_entity_id,
        subject_role=SubjectRole.PRODUCT,
        locator={"url": source_url},
        snapshot=EvidenceSnapshot(
            text=text, uri=None, sha256=hashlib.sha256(text.encode()).hexdigest()
        ),
        source_revision_kind="content_hash",
        source_revision_value=hashlib.sha256(f"{source_url}:{text}".encode()).hexdigest(),
        usage_rights=usage_rights,
        confidentiality=Confidentiality.PUBLIC,
        public_citation=PublicCitation(
            disclosure_allowed=True,
            source_url=source_url,
            source_title=source_title,
            label="Official source",
            quotation_allowed=False,
            attribution_required=True,
        ),
    )


def _observation(
    *,
    query_id: UUID,
    window: MeasurementWindow,
    recommendation_present: bool,
    product_mentioned: bool,
    citation: CitationDraft | None = None,
) -> ObservationDraft:
    return ObservationDraft(
        monitoring_query_id=query_id,
        measurement_window=window,
        sample_index=1,
        result_status=ResultStatus.SUCCEEDED,
        eligible=True,
        ineligible_reasons=(),
        url_verification_status=(
            VerificationStatus.PASSED if citation else VerificationStatus.UNKNOWN
        ),
        recommendation_present=recommendation_present,
        primary_product_mentioned=product_mentioned,
        competitor_mentioned=False,
        raw_answer="Controlled acceptance observation; not a live AI search result.",
        raw_result={"mode": "controlled_acceptance"},
        citations=(citation,) if citation else (),
        artifact_uri=None,
        artifact_hash=None,
        configured_model="controlled-observation",
        provider_reported_model=None,
        ui_surface="acceptance-harness",
        ui_metadata={"locale": "en-AU"},
        confounding_factors=("controlled_acceptance_data",),
        observed_at=datetime.now(UTC),
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


def _gateway(config: AcceptanceConfig, *, evidence_id: UUID) -> ModelGateway:
    if not config.live_deepseek:
        return DeterministicGateway(evidence_id=evidence_id, product_url=PRODUCT_URL)
    assert config.deepseek_key_file is not None
    return DeepSeekGateway(
        api_key_file=config.deepseek_key_file,
        capability_registry=default_deepseek_capability_registry(),
    )


def _write_result(path: Path, result: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app-database-url",
        default=os.getenv("GEO_ACCEPTANCE_APP_DATABASE_URL", ""),
        help="geo_app PostgreSQL URL (or GEO_ACCEPTANCE_APP_DATABASE_URL)",
    )
    parser.add_argument(
        "--worker-database-url",
        default=os.getenv("GEO_ACCEPTANCE_WORKER_DATABASE_URL", ""),
        help="geo_worker PostgreSQL URL (or GEO_ACCEPTANCE_WORKER_DATABASE_URL)",
    )
    parser.add_argument("--run-id", default=f"geo-acceptance-{datetime.now(UTC):%Y%m%d%H%M%S}")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/geo-acceptance/result.json"),
    )
    parser.add_argument(
        "--live-deepseek",
        action="store_true",
        help="explicitly allow one paid DeepSeek generation call",
    )
    parser.add_argument(
        "--deepseek-key-file",
        type=Path,
        default=(
            Path(os.environ["GEO_DEEPSEEK_API_KEY_FILE"])
            if os.getenv("GEO_DEEPSEEK_API_KEY_FILE")
            else None
        ),
    )
    parser.add_argument(
        "--runtime-object-store",
        action="store_true",
        help="write artifacts to the configured S3-compatible store instead of memory",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        config = AcceptanceConfig(
            app_database_url=args.app_database_url or _required_environment(
                "GEO_ACCEPTANCE_APP_DATABASE_URL"
            ),
            worker_database_url=args.worker_database_url or _required_environment(
                "GEO_ACCEPTANCE_WORKER_DATABASE_URL"
            ),
            run_id=args.run_id,
            output_path=args.output,
            live_deepseek=args.live_deepseek,
            deepseek_key_file=args.deepseek_key_file,
            runtime_object_store=args.runtime_object_store,
        )
        result = run_acceptance(config)
    except (AssertionError, RuntimeError, ValueError, psycopg.Error) as error:
        print(f"GEO acceptance failed: {error}")
        return 1
    print(
        "GEO acceptance passed: "
        f"project={result['project']['project_id']} "  # type: ignore[index]
        f"result={config.output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
