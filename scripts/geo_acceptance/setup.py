"""Project, evidence, access and channel setup for GEO acceptance."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import cast
from uuid import UUID, uuid4

import psycopg

from geo_core.access.membership_service import AccessMembershipService
from geo_core.access.models import AccessPrincipal
from geo_core.access.postgres import PsycopgAccessUnitOfWorkFactory
from geo_core.access.service import AccessApplicationService
from geo_core.catalog.application import CatalogApplication
from geo_core.catalog.domain import (
    BootstrapResult,
    Confidentiality,
    EntityType,
    EvidenceDraft,
    EvidenceItem,
    EvidenceItemType,
    EvidenceSnapshot,
    MarketProfile,
    ProductEntity,
    PublicCitation,
    SubjectRole,
    UsageRights,
)
from geo_core.catalog.postgres import PsycopgCatalogUnitOfWorkFactory
from geo_core.object_store_config import build_object_store
from geo_core.placements.application import PlacementApplication
from geo_core.placements.domain import Campaign, Destination, Opportunity
from geo_core.placements.ports import UnitOfWorkFactory
from geo_core.placements.postgres_uow import placement_uow_factory

from scripts.geo_acceptance.adapters import ArtifactStore, MemoryArtifactStore
from scripts.geo_acceptance.contracts import (
    AcceptanceConfig,
    CHANNELS,
    PRODUCT_URL,
    run_scope_suffix,
)


EXPERIENCE_TEXT = (
    "A consumer described using the mower for routine lawn care and checking the "
    "completed area after each run."
)


@dataclass(frozen=True)
class AcceptanceSetup:
    suffix: str
    bootstrap: BootstrapResult
    owner: AccessPrincipal
    reviewer_identity_id: UUID
    customer: AccessPrincipal
    brand: ProductEntity
    product: ProductEntity
    market: MarketProfile
    fact: EvidenceItem
    experience: EvidenceItem
    placement: PlacementApplication
    artifact_store: ArtifactStore
    destinations: tuple[Destination, ...]
    campaign: Campaign
    owned_opportunity: Opportunity
    customer_invitation_id: UUID
    customer_invite_token: str

    @property
    def project_id(self) -> UUID:
        return self.bootstrap.project.id


def setup_acceptance(config: AcceptanceConfig) -> AcceptanceSetup:
    app_url = config.app_database_url.strip()
    suffix = run_scope_suffix(config.run_id)
    catalog = CatalogApplication(
        PsycopgCatalogUnitOfWorkFactory(app_url), development_bootstrap_allowed=True
    )
    access_factory = PsycopgAccessUnitOfWorkFactory(app_url)
    access = AccessApplicationService(
        access_factory, token_secret=f"geo-acceptance-token-secret-{suffix}"
    )
    bootstrap = catalog.bootstrap_development(
        tenant_name=f"GEO acceptance {suffix}",
        identity_subject=f"owner-{suffix}",
        identity_email=f"owner-{suffix}@example.com",
        project_name=f"[SIMULATION] ADVINSYS acceptance {suffix}",
    )
    owner = access.authenticate_development(
        identity_id=bootstrap.identity_id, tenant_id=bootstrap.tenant_id
    )
    reviewer = AccessMembershipService(access_factory).add_member(
        owner,
        project_id=bootstrap.project.id,
        issuer="https://identity.example.com/",
        subject=f"reviewer-{suffix}",
        email=f"reviewer-{suffix}@example.com",
        display_name=f"Acceptance Reviewer {suffix}",
        role="admin",
        idempotency_key=f"acceptance-add-reviewer-{suffix}",
    ).membership
    invitation = access.create_invitation(
        owner,
        project_id=bootstrap.project.id,
        email=f"customer-{suffix}@example.com",
        role="customer",
        target_surface="customer",
        expires_in_hours=1,
        idempotency_key=f"acceptance-customer-invitation-{suffix}",
    )
    customer = access.redeem_invitation(
        invitation_id=invitation.invitation.id,
        invite_token=invitation.invite_token,
        requested_surface="customer",
        idempotency_key=f"acceptance-customer-redemption-{suffix}",
    ).principal
    browser_invitation = access.create_invitation(
        owner,
        project_id=bootstrap.project.id,
        email=f"browser-customer-{suffix}@example.com",
        role="customer",
        target_surface="customer",
        expires_in_hours=1,
        idempotency_key=f"acceptance-browser-customer-invitation-{suffix}",
    )
    project_id = bootstrap.project.id

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
    fact = catalog.create_evidence(
        owner,
        project_id=project_id,
        draft=_evidence_draft(
            item_type=EvidenceItemType.APPROVED_FACT,
            subject_entity_id=product.id,
            text=(
                "The official ADVINSYS product page identifies TerraMow V600 as a "
                "Triple-Cam AI Vision Robot Mower in the robotic lawn mower category."
            ),
            source_url=PRODUCT_URL,
            source_title="ADVINSYS TerraMow V600 product page",
            usage_rights=UsageRights.OWNED,
        ),
    )
    experience = catalog.create_evidence(
        owner,
        project_id=project_id,
        draft=_evidence_draft(
            item_type=EvidenceItemType.CONSUMER_EXPERIENCE,
            subject_entity_id=product.id,
            text=EXPERIENCE_TEXT,
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
    campaign, opportunities = placement.create_campaign(
        project_id=project_id,
        market_profile_id=market.id,
        primary_product_entity_id=product.id,
        name=f"TerraMow V600 recommendation influence {suffix}",
        objective="recommendation_influence",
        actor_id=owner.identity_id,
        destination_ids=tuple(item.id for item in destinations),
        rationale="Create one governed manual placement task for every selected channel.",
    )
    if len(opportunities) != len(CHANNELS):
        raise AssertionError("every selected channel must create a persistent task")
    if any(item.status != "blocked" for item in opportunities):
        raise AssertionError("unreviewed destinations must fail closed")

    owned_destination, owned_opportunity = destinations[0], opportunities[0]
    for destination in destinations[1:]:
        setup_status = placement.review_destination_policy(
            project_id=project_id,
            destination_id=destination.id,
            status="restricted",
            rules={"manual_submission_only": True, "simulation_allowed": True},
            identity_requirements={"brand_relationship_disclosure": "required"},
            disclosure_requirements={"commercial_relationship": "required"},
            allowed_hosts=(destination.canonical_host,),
            reviewed_by=owner.identity_id,
        )
        if setup_status.status != "restricted":
            raise AssertionError("non-owned acceptance destinations must remain restricted")
    placement.review_destination_policy(
        project_id=project_id,
        destination_id=owned_destination.id,
        status="approved",
        rules={"manual_submission_only": True, "official_content": True},
        identity_requirements={"brand_account_authorisation": "required"},
        disclosure_requirements={"brand_relationship": "required"},
        allowed_hosts=("simulated.advinsys.example",),
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
    return AcceptanceSetup(
        suffix,
        bootstrap,
        owner,
        reviewer.identity_id,
        customer,
        brand,
        product,
        market,
        fact,
        experience,
        placement,
        artifact_store,
        destinations,
        campaign,
        owned_opportunity,
        browser_invitation.invitation.id,
        browser_invitation.invite_token,
    )


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
