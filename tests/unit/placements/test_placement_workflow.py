from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from geo_core.placements.application import PlacementApplication
from geo_core.placements.domain import (
    BriefVersion,
    Campaign,
    CampaignResourceContext,
    CampaignResourceKind,
    CampaignScope,
    Claim,
    ConsumerExperience,
    Destination,
    EvidencePackAttempt,
    ExportReceipt,
    JobReference,
    MonitoringQuery,
    Opportunity,
    OpportunityPromptReleaseBinding,
    PackageVersion,
    PlacementConflict,
    PromptBundleView,
    PromptReleaseView,
    PromptReleaseBindingStatus,
    PromptSkill,
    Review,
    ReviewSubmission,
    WorkflowStatus,
    canonical_hash,
)
from geo_core.prompts.domain import SkillVersion, TemplateRelease
from tests.unit.placements.placement_test_support import (
    OUTPUT_SCHEMA,
    PublicationRepositorySupport,
)


class FakeRepository(PublicationRepositorySupport):
    def __init__(self) -> None:
        super().__init__()
        self.campaigns: list[Campaign] = []
        self.destinations: list[Destination] = []
        self.opportunities: list[Opportunity] = []
        self.briefs: list[BriefVersion] = []
        self.attempts: list[EvidencePackAttempt] = []
        self.releases: dict[UUID, TemplateRelease] = {}
        self.release_views: dict[UUID, PromptReleaseView] = {}
        self.bindings: dict[UUID, list[OpportunityPromptReleaseBinding]] = {}
        self.bundles: list[PromptBundleView] = []
        self.packages: list[PackageVersion] = []
        self.claims: list[Claim] = []
        self.reviews: list[Review] = []
        self.exports: list[ExportReceipt] = []
        self.jobs: list[JobReference] = []

    def create_destination(self, **values: Any) -> Destination:
        item = Destination(id=uuid4(), **values)
        self.destinations.append(item)
        return item

    def list_destinations(self, *, project_id: UUID) -> tuple[Destination, ...]:
        return tuple(item for item in self.destinations if item.project_id == project_id)

    def create_campaign(self, **values: Any) -> Campaign:
        values.pop("actor_id")
        item = Campaign(id=uuid4(), **values)
        self.campaigns.append(item)
        return item

    def create_opportunities(self, **values: Any) -> tuple[Opportunity, ...]:
        created = tuple(
            Opportunity(
                id=uuid4(),
                project_id=values["project_id"],
                campaign_id=values["campaign_id"],
                destination_id=destination_id,
                opportunity_ref=f"destination:{destination_id}",
                rationale=values["rationale"],
            )
            for destination_id in values["destination_ids"]
        )
        self.opportunities.extend(created)
        for opportunity in created:
            self.bindings[opportunity.id] = [
                OpportunityPromptReleaseBinding(
                    id=uuid4(),
                    project_id=opportunity.project_id,
                    campaign_id=opportunity.campaign_id,
                    opportunity_id=opportunity.id,
                    destination_id=opportunity.destination_id,
                    binding_version=1,
                    previous_binding_id=None,
                    status=PromptReleaseBindingStatus.UNBOUND,
                    changed_by=values["actor_id"],
                    changed_at=datetime.now(UTC),
                )
            ]
        return created

    def resolve_campaign_resource(
        self,
        *,
        scope: CampaignScope,
        kind: CampaignResourceKind,
        resource_id: UUID,
        lock: bool = False,
    ) -> CampaignResourceContext | None:
        del lock
        if kind == CampaignResourceKind.OPPORTUNITY:
            item = next((value for value in self.opportunities if value.id == resource_id), None)
            lineage = (item.campaign_id, item.id, item.destination_id) if item else None
        elif kind == CampaignResourceKind.BRIEF_VERSION:
            item = next((value for value in self.briefs if value.id == resource_id), None)
            lineage = _lineage(item) if item else None
        elif kind == CampaignResourceKind.EVIDENCE_ATTEMPT:
            item = next((value for value in self.attempts if value.id == resource_id), None)
            lineage = _lineage(item) if item else None
        elif kind == CampaignResourceKind.PROMPT_BUNDLE:
            item = next((value for value in self.bundles if value.id == resource_id), None)
            lineage = _lineage(item) if item else None
        elif kind in {CampaignResourceKind.PACKAGE, CampaignResourceKind.PACKAGE_VERSION}:
            item = next(
                (
                    value
                    for value in self.packages
                    if value.id == resource_id or value.package_id == resource_id
                ),
                None,
            )
            lineage = _lineage(item) if item else None
        elif kind == CampaignResourceKind.PUBLICATION:
            item = next((value for value in self.publications if value.id == resource_id), None)
            lineage = _lineage(item) if item else None
        elif kind == CampaignResourceKind.SUBMISSION:
            item = next((value for value in self.submissions if value.id == resource_id), None)
            lineage = _lineage(item) if item else None
        elif kind == CampaignResourceKind.EXPORT:
            item = next((value for value in self.exports if value.id == resource_id), None)
            lineage = _lineage(item) if item else None
        else:
            return None
        if lineage is None or lineage[0] != scope.campaign_id:
            return None
        return CampaignResourceContext(
            scope=scope,
            kind=kind,
            resource_id=resource_id,
            opportunity_id=lineage[1],
            destination_id=lineage[2],
        )

    def list_campaigns(self, *, project_id: UUID) -> tuple[Campaign, ...]:
        return tuple(item for item in self.campaigns if item.project_id == project_id)

    def get_campaign(self, *, project_id: UUID, campaign_id: UUID) -> Campaign | None:
        return next(
            (
                item
                for item in self.campaigns
                if item.project_id == project_id and item.id == campaign_id
            ),
            None,
        )

    def create_monitoring_query(self, **values: Any) -> MonitoringQuery:
        values.pop("campaign_id")
        return MonitoringQuery(id=uuid4(), **values)

    def list_monitoring_queries(self, **values: Any) -> tuple[MonitoringQuery, ...]:
        del values
        return ()

    def list_opportunities(self, **values: Any) -> tuple[Opportunity, ...]:
        return tuple(
            item
            for item in self.opportunities
            if item.project_id == values["project_id"] and item.campaign_id == values["campaign_id"]
        )

    def create_brief_version(self, **values: Any) -> BriefVersion:
        opportunity = next(
            item for item in self.opportunities if item.id == values["opportunity_id"]
        )
        item = BriefVersion(
            id=uuid4(),
            project_id=values["project_id"],
            brief_id=uuid4(),
            version_number=1,
            goals=values["goals"],
            constraints=values["constraints"],
            content_hash=values["content_hash"],
            base_version_id=values["base_version_id"],
            campaign_id=opportunity.campaign_id,
            opportunity_id=opportunity.id,
            destination_id=opportunity.destination_id,
        )
        self.briefs.append(item)
        return item

    def list_brief_versions(self, **values: Any) -> tuple[BriefVersion, ...]:
        del values
        return tuple(self.briefs)

    def create_evidence_attempt(self, **values: Any) -> tuple[EvidencePackAttempt, JobReference]:
        brief = next(item for item in self.briefs if item.id == values["brief_version_id"])
        attempt = EvidencePackAttempt(
            id=uuid4(),
            project_id=values["project_id"],
            brief_version_id=values["brief_version_id"],
            attempt_number=len(self.attempts) + 1,
            campaign_id=brief.campaign_id,
            opportunity_id=brief.opportunity_id,
            destination_id=brief.destination_id,
        )
        job = self._job(values["project_id"], brief.campaign_id, "evidence_pack.build")
        self.attempts.append(attempt)
        return attempt, job

    def list_evidence_attempts(self, **values: Any) -> tuple[EvidencePackAttempt, ...]:
        return tuple(
            item
            for item in self.attempts
            if item.project_id == values["project_id"]
            and item.brief_version_id == values["brief_version_id"]
        )

    def create_prompt_skill(self, *, project_id: UUID, skill_key: str) -> PromptSkill:
        return PromptSkill(uuid4(), project_id, skill_key)

    def create_skill_version(self, **values: Any) -> SkillVersion:
        version = 1 + sum(
            item.skill_version_id == values["skill_id"] for item in self.releases.values()
        )
        return SkillVersion.create(
            id=uuid4(), skill_id=values["skill_id"], version=version, source=values["source"]
        )

    def create_template_release(self, **values: Any) -> PromptReleaseView:
        template = values["template"]
        self.releases[template.id] = template
        variable_schema = {
            "required": template.required_variables,
            "client_allowed": values["client_variable_names"],
            "server_authoritative": ["brief", "evidence", "destination_policy"],
        }
        release_hash = canonical_hash(
            {
                "source_text": values["source_text"],
                "system_template": values["system_template"],
                "user_template": template.template,
                "variable_schema": variable_schema,
                "output_schema": values["output_schema"],
                "compiler_version": "geo-prompt-compiler-v1",
            }
        )
        view = PromptReleaseView(
            template.id,
            values["project_id"],
            values["skill_version_id"],
            len(self.releases),
            release_hash,
            values["source_text"],
            values["system_template"],
            template.template,
            variable_schema,
            values["output_schema"],
            "geo-prompt-compiler-v1",
        )
        self.release_views[view.id] = view
        return view

    def get_prompt_release_view(
        self, *, project_id: UUID, release_id: UUID
    ) -> PromptReleaseView | None:
        view = self.release_views.get(release_id)
        return view if view and view.project_id == project_id else None

    def get_current_prompt_release_binding(
        self, *, scope: CampaignScope, opportunity_id: UUID
    ) -> OpportunityPromptReleaseBinding | None:
        history = self.bindings.get(opportunity_id, [])
        current = history[-1] if history else None
        return current if current and current.campaign_id == scope.campaign_id else None

    def list_prompt_release_binding_history(
        self, *, scope: CampaignScope, opportunity_id: UUID
    ) -> tuple[OpportunityPromptReleaseBinding, ...]:
        return tuple(reversed(self.bindings.get(opportunity_id, [])))

    def bind_opportunity_prompt_release(self, **values: Any) -> OpportunityPromptReleaseBinding:
        scope = values["scope"]
        current = self.bindings[values["opportunity_id"]][-1]
        release = self.release_views[values["release_id"]]
        binding = OpportunityPromptReleaseBinding(
            id=uuid4(),
            project_id=scope.project_id,
            campaign_id=scope.campaign_id,
            opportunity_id=current.opportunity_id,
            destination_id=current.destination_id,
            binding_version=current.binding_version + 1,
            previous_binding_id=current.id,
            status=PromptReleaseBindingStatus.BOUND,
            changed_by=values["actor_id"],
            changed_at=datetime.now(UTC),
            template_release_id=release.id,
            skill_version_id=release.skill_version_id,
            release_version=release.release_number,
            release_hash=release.release_hash,
        )
        self.bindings[current.opportunity_id].append(binding)
        return binding

    def get_template_release(self, **values: Any) -> TemplateRelease | None:
        return self.releases.get(values["release_id"])

    def create_prompt_bundle(self, **values: Any) -> PromptBundleView:
        binding = next(
            item
            for item in self.bindings[values["opportunity_id"]]
            if item.id == values["prompt_release_binding_id"]
        )
        release = self.releases[binding.template_release_id]
        rendered = {
            **values["variables"],
            "brief": "server brief",
            "evidence": "server evidence",
            "destination_policy": "server policy",
        }
        assert set(release.required_variables) <= set(rendered)
        bundle_id = uuid4()
        bundle_hash = canonical_hash({"release": str(release.id), "variables": values["variables"]})
        bundle = PromptBundleView(
            bundle_id,
            values["scope"].project_id,
            values["brief_version_id"],
            values["evidence_pack_attempt_id"],
            release.id,
            bundle_hash,
            f"content-prompts/{values['scope'].project_id}/"
            f"{values['brief_version_id']}/{bundle_id}",
            "pending",
            None,
            campaign_id=values["scope"].campaign_id,
            opportunity_id=values["opportunity_id"],
            destination_id=binding.destination_id,
            prompt_release_binding_id=binding.id,
            prompt_release_binding_version=binding.binding_version,
            skill_version_id=binding.skill_version_id,
            release_version=binding.release_version,
            release_hash=binding.release_hash,
        )
        self.bundles.append(bundle)
        self.bundle_manifests[bundle.id] = {
            "schema": "geo-prompt-bundle-v3",
            "authoritative": {
                "destination_policy": {"disclosure_requirements": {}}
            },
        }
        return bundle

    def enqueue_generation(self, **values: Any) -> JobReference:
        return self._job(
            values["scope"].project_id,
            values["scope"].campaign_id,
            "placement.generate",
        )

    def list_package_versions(self, **values: Any) -> tuple[PackageVersion, ...]:
        del values
        return tuple(self.packages)

    def get_package_version(self, *, project_id: UUID, version_id: UUID) -> PackageVersion | None:
        return next(
            (
                item
                for item in self.packages
                if item.project_id == project_id and item.id == version_id
            ),
            None,
        )

    def save_edited_version(self, **values: Any) -> PackageVersion:
        old = self.get_package_version(
            project_id=values["version"].project_id,
            version_id=values["superseded_version_id"],
        )
        self.packages[self.packages.index(old)] = replace(
            old, workflow_status=WorkflowStatus.SUPERSEDED
        )
        self.packages.append(values["version"])
        self.claims.extend(
            Claim(
                uuid4(),
                values["version"].project_id,
                values["version"].id,
                item.text,
                item.kind,
                item.support_status,
                item.evidence_item_ids,
            )
            for item in values["claims"]
        )
        return values["version"]

    def list_claims(self, **values: Any) -> tuple[Claim, ...]:
        return tuple(
            item for item in self.claims if item.package_version_id == values["version_id"]
        )

    def submit_for_review(self, **values: Any) -> ReviewSubmission:
        item = ReviewSubmission(
            uuid4(),
            values["project_id"],
            values["version_id"],
            values["submitted_by"],
            datetime.now(UTC),
        )
        self.review_submission = item
        index = next(
            i for i, version in enumerate(self.packages) if version.id == item.package_version_id
        )
        self.packages[index] = replace(
            self.packages[index], workflow_status=WorkflowStatus.PENDING_HUMAN_REVIEW
        )
        return item

    def get_review_submission(self, **values: Any) -> ReviewSubmission | None:
        item = getattr(self, "review_submission", None)
        return item if item and item.package_version_id == values["version_id"] else None

    def save_review(self, *, review: Review) -> Review:
        self.reviews.append(review)
        index = next(
            i for i, item in enumerate(self.packages) if item.id == review.package_version_id
        )
        self.packages[index] = replace(
            self.packages[index], workflow_status=WorkflowStatus(review.decision)
        )
        return review

    def export_package(self, **values: Any) -> ExportReceipt:
        version = self.get_package_version(
            project_id=values["project_id"], version_id=values["version_id"]
        )
        claims = self.list_claims(project_id=values["project_id"], version_id=version.id)
        receipt = ExportReceipt(
            uuid4(),
            values["project_id"],
            version.id,
            version.content_hash,
            values["exported_at"],
            "json",
            values["requested_by"],
            "pending",
            f"content-artifacts/{values['project_id']}/{version.id}/export.json",
            None,
            version,
            claims,
            campaign_id=version.campaign_id,
            opportunity_id=version.opportunity_id,
            destination_id=version.destination_id,
        )
        self.exports.append(receipt)
        return receipt

    def list_exports(self, **values: Any) -> tuple[ExportReceipt, ...]:
        return tuple(
            item for item in self.exports if item.package_version_id == values["version_id"]
        )

    def _job(self, project_id: UUID, campaign_id: UUID | None, kind: str) -> JobReference:
        job = JobReference(uuid4(), project_id, kind, "queued", campaign_id)
        self.jobs.append(job)
        return job


def _lineage(value: Any) -> tuple[UUID, UUID, UUID] | None:
    if (
        value is None
        or value.campaign_id is None
        or value.opportunity_id is None
        or value.destination_id is None
    ):
        return None
    return value.campaign_id, value.opportunity_id, value.destination_id


class FakeUnitOfWork:
    def __init__(self, repository: FakeRepository) -> None:
        self.placements = repository
        self.committed = False

    def __enter__(self) -> "FakeUnitOfWork":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def commit(self) -> None:
        self.committed = True


def _application() -> tuple[PlacementApplication, FakeRepository]:
    repository = FakeRepository()
    return PlacementApplication(lambda project_id: FakeUnitOfWork(repository)), repository


def test_full_application_chain_keeps_export_and_publication_separate() -> None:
    app, repository = _application()
    project_id, actor_id = uuid4(), uuid4()
    destinations = [
        app.create_destination(
            project_id=project_id,
            publication_channel=channel,
            destination_key=f"account:{channel}",
            operation_mode="manual",
            destination_account_id=None,
            canonical_url=f"https://{channel}.example",
        )
        for channel in ("reddit", "youtube", "productreview")
    ]
    campaign, opportunities = app.create_campaign(
        project_id=project_id,
        market_profile_id=uuid4(),
        primary_product_entity_id=uuid4(),
        name="Robot vacuum recommendations",
        objective="recommendation_influence",
        actor_id=actor_id,
        destination_ids=tuple(item.id for item in destinations),
        rationale="Audience fit",
    )
    assert {item.destination_id for item in opportunities} == {item.id for item in destinations}

    brief = app.create_brief_version(
        project_id=project_id,
        campaign_id=campaign.id,
        opportunity_id=opportunities[0].id,
        primary_brand_entity_id=uuid4(),
        goals={"query": "best robot vacuum"},
        constraints={},
        compared_entity_ids=(),
        allowed_subject_entity_ids=(),
        actor_id=actor_id,
        base_version_id=None,
        consumer_experience=ConsumerExperience(
            "It cleaned a two-bedroom home daily.",
            "customer supplied note",
            "authorised_experience",
            "Customer wording was edited for clarity.",
        ),
        authenticity_risks=(),
    )
    attempt, _ = app.create_evidence_attempt(
        project_id=project_id,
        campaign_id=campaign.id,
        brief_version_id=brief.id,
        idempotency_key="evidence-attempt-0001",
    )
    skill = app.create_prompt_skill(project_id=project_id, skill_key="reddit-review")
    release = app.publish_skill_version(
        project_id=project_id,
        skill_id=skill.id,
        source=(
            "Use {{brief}} and {{evidence}} under {{destination_policy}} "
            "to write for {{channel}}."
        ),
        actor_id=actor_id,
        output_schema=OUTPUT_SCHEMA,
        client_variable_names=("channel",),
    )
    binding = app.bind_opportunity_prompt_release(
        project_id=project_id,
        campaign_id=campaign.id,
        opportunity_id=opportunities[0].id,
        release_id=release.id,
        expected_binding_version=1,
        reason="Use the approved Reddit Release",
        actor_id=actor_id,
        idempotency_key="bind-release-0001",
    )
    bundle = app.create_prompt_bundle(
        project_id=project_id,
        campaign_id=campaign.id,
        opportunity_id=opportunities[0].id,
        brief_version_id=brief.id,
        evidence_pack_attempt_id=attempt.id,
        prompt_release_binding_id=binding.id,
        confirmed_release_hash=release.release_hash,
        variables={"channel": "reddit"},
        model_policy_hash="f" * 64,
        idempotency_key="prompt-bundle-0001",
        requested_by=actor_id,
    )
    job = app.request_generation(
        project_id=project_id,
        campaign_id=campaign.id,
        prompt_bundle_id=bundle.id,
        configured_model="deepseek-v4-flash",
        model_call_budget=2,
        idempotency_key="generation-job-0001",
        requested_by=actor_id,
    )
    assert job.status == "queued"

    version = PackageVersion(
        uuid4(),
        project_id,
        uuid4(),
        bundle.id,
        1,
        {
            "title": "A practical review",
            "required_disclosures": [],
            "expected_links": [],
        },
        "A practical review",
        "a" * 64,
        WorkflowStatus.PENDING_HUMAN_REVIEW,
        campaign_id=campaign.id,
        opportunity_id=opportunities[0].id,
        destination_id=destinations[0].id,
    )
    repository.packages.append(version)
    repository.claims.append(
        Claim(
            uuid4(),
            project_id,
            version.id,
            "Daily cleaning was tested.",
            "factual",
            "supported",
            (uuid4(),),
        )
    )
    reviewer_id = uuid4()
    app.submit_for_review(
        project_id=project_id,
        campaign_id=campaign.id,
        version_id=version.id,
        submitted_by=actor_id,
    )
    app.submit_review(
        project_id=project_id,
        campaign_id=campaign.id,
        version_id=version.id,
        reviewer_id=reviewer_id,
        decision="approved",
        claim_inventory_complete=True,
        extracted_claim_support_confirmed=True,
        score=90,
        notes=None,
    )
    app.export_package(
        project_id=project_id,
        campaign_id=campaign.id,
        version_id=version.id,
        requested_by=actor_id,
    )
    assert repository.publications == []
    publication = app.request_publication(
        project_id=project_id,
        campaign_id=campaign.id,
        version_id=version.id,
        destination_id=destinations[0].id,
        requested_by=actor_id,
        publication_attempt=1,
        idempotency_key="publication-request-0001",
        restricted_policy_acknowledged=False,
        policy_basis=None,
    )
    submission = app.create_submission(
        project_id=project_id,
        campaign_id=campaign.id,
        publication_request_id=publication.id,
        submitted_url="https://reddit.example/post",
        provider_submission_id=None,
        idempotency_key="submission-0001",
        submitted_by=actor_id,
    )
    assert app.create_submission(
        project_id=project_id, campaign_id=campaign.id,
        publication_request_id=publication.id,
        submitted_url="https://reddit.example/post", provider_submission_id=None,
        idempotency_key="submission-0001", submitted_by=actor_id,
    ).id == submission.id
    with pytest.raises(PlacementConflict, match="different payload"):
        app.create_submission(
            project_id=project_id, campaign_id=campaign.id,
            publication_request_id=publication.id,
            submitted_url="https://reddit.example/other-post", provider_submission_id=None,
            idempotency_key="submission-0001", submitted_by=actor_id,
        )
    verify_job = app.request_verification(
        project_id=project_id,
        campaign_id=campaign.id,
        submission_id=submission.id,
        idempotency_key="verification-job-0001",
    )
    measurement = app.record_measurement(
        project_id=project_id,
        campaign_id=campaign.id,
        submission_id=submission.id,
        monitoring_query_id=uuid4(),
        measured_at=datetime.now(UTC),
        citation_present=True,
        recommendation_position=2,
        result_snapshot_uri="snapshots/result.json",
        metrics={"share_of_voice": 0.3},
    )
    assert verify_job.kind == "publication.verify"
    assert measurement.recommendation_position == 2
    assert campaign.id == opportunities[0].campaign_id
