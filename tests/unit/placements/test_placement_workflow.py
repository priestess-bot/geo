from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from geo_core.placements.application import PlacementApplication
from geo_core.placements.domain import (
    AuthenticityRisk,
    BriefVersion,
    Campaign,
    Claim,
    ConcurrencyConflict,
    ConsumerExperience,
    Destination,
    EvidencePackAttempt,
    ExportReceipt,
    JobReference,
    Measurement,
    MonitoringQuery,
    Opportunity,
    PackageVersion,
    PlacementRuleViolation,
    PromptBundleView,
    PromptReleaseView,
    PromptSkill,
    PublicationRequest,
    Review,
    ReviewSubmission,
    Submission,
    WorkflowStatus,
    canonical_hash,
)
from geo_core.prompts.domain import SkillVersion, TemplateRelease


OUTPUT_SCHEMA = {
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
                "required": ["text", "kind", "support_status", "evidence_item_ids"],
            },
        }
    },
}


class FakeRepository:
    def __init__(self) -> None:
        self.campaigns: list[Campaign] = []
        self.destinations: list[Destination] = []
        self.opportunities: list[Opportunity] = []
        self.briefs: list[BriefVersion] = []
        self.attempts: list[EvidencePackAttempt] = []
        self.releases: dict[UUID, TemplateRelease] = {}
        self.packages: list[PackageVersion] = []
        self.claims: list[Claim] = []
        self.reviews: list[Review] = []
        self.exports: list[ExportReceipt] = []
        self.publications: list[PublicationRequest] = []
        self.submissions: list[Submission] = []
        self.measurements: list[Measurement] = []
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
        return created

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
        item = BriefVersion(
            id=uuid4(),
            project_id=values["project_id"],
            brief_id=uuid4(),
            version_number=1,
            goals=values["goals"],
            constraints=values["constraints"],
            content_hash=values["content_hash"],
            base_version_id=values["base_version_id"],
        )
        self.briefs.append(item)
        return item

    def list_brief_versions(self, **values: Any) -> tuple[BriefVersion, ...]:
        del values
        return tuple(self.briefs)

    def create_evidence_attempt(self, **values: Any) -> tuple[EvidencePackAttempt, JobReference]:
        attempt = EvidencePackAttempt(
            id=uuid4(),
            project_id=values["project_id"],
            brief_version_id=values["brief_version_id"],
            attempt_number=len(self.attempts) + 1,
        )
        job = self._job(values["project_id"], "evidence_pack.build")
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
        return PromptReleaseView(
            template.id,
            values["project_id"],
            values["skill_version_id"],
            len(self.releases),
            template.release_hash,
        )

    def get_template_release(self, **values: Any) -> TemplateRelease | None:
        return self.releases.get(values["release_id"])

    def create_prompt_bundle(self, **values: Any) -> PromptBundleView:
        release = self.releases[values["release_id"]]
        rendered = {
            **values["variables"],
            "brief": "server brief",
            "evidence": "server evidence",
            "destination_policy": "server policy",
        }
        assert set(release.required_variables) <= set(rendered)
        bundle_id = uuid4()
        bundle_hash = canonical_hash({"release": str(release.id), "variables": values["variables"]})
        return PromptBundleView(
            bundle_id,
            values["project_id"],
            values["brief_version_id"],
            values["evidence_pack_attempt_id"],
            release.id,
            bundle_hash,
            f"content-prompts/{values['project_id']}/{values['brief_version_id']}/{bundle_id}",
            "pending",
            None,
        )

    def enqueue_generation(self, **values: Any) -> JobReference:
        return self._job(values["project_id"], "placement.generate")

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
        )
        self.exports.append(receipt)
        return receipt

    def list_exports(self, **values: Any) -> tuple[ExportReceipt, ...]:
        return tuple(
            item for item in self.exports if item.package_version_id == values["version_id"]
        )

    def create_publication_request(self, **values: Any) -> PublicationRequest:
        version = self.get_package_version(
            project_id=values["project_id"], version_id=values["version_id"]
        )
        if version.workflow_status != WorkflowStatus.APPROVED:
            raise PlacementRuleViolation("publication requires approved version")
        destination = next(
            item for item in self.destinations if item.id == values["destination_id"]
        )
        item = PublicationRequest(
            id=uuid4(),
            project_id=values["project_id"],
            package_version_id=version.id,
            destination_id=destination.id,
            publication_channel=destination.publication_channel,
            destination_key=destination.destination_key,
            publication_attempt=values["publication_attempt"],
            idempotency_key=values["idempotency_key"],
            restricted_policy_acknowledged=values["restricted_policy_acknowledged"],
            policy_basis=values["policy_basis"],
        )
        self.publications.append(item)
        return item

    def create_submission(self, **values: Any) -> Submission:
        item = Submission(
            uuid4(),
            values["project_id"],
            values["publication_request_id"],
            "submitted" if values["submitted_url"] else "awaiting_url",
            values["submitted_url"],
            values["provider_submission_id"],
        )
        self.submissions.append(item)
        return item

    def enqueue_verification(self, **values: Any) -> JobReference:
        return self._job(values["project_id"], "publication.verify")

    def record_measurement(self, **values: Any) -> Measurement:
        item = Measurement(id=uuid4(), **values)
        self.measurements.append(item)
        return item

    def list_measurements(self, **values: Any) -> tuple[Measurement, ...]:
        return tuple(
            item for item in self.measurements if item.submission_id == values["submission_id"]
        )

    def _job(self, project_id: UUID, kind: str) -> JobReference:
        job = JobReference(uuid4(), project_id, kind, "queued")
        self.jobs.append(job)
        return job


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
    bundle = app.create_prompt_bundle(
        project_id=project_id,
        brief_version_id=brief.id,
        evidence_pack_attempt_id=attempt.id,
        release_id=release.id,
        variables={"channel": "reddit"},
        model_policy_hash="f" * 64,
    )
    job = app.request_generation(
        project_id=project_id,
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
        {"title": "A practical review"},
        "A practical review",
        "a" * 64,
        WorkflowStatus.PENDING_HUMAN_REVIEW,
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
    app.submit_for_review(project_id=project_id, version_id=version.id, submitted_by=actor_id)
    app.submit_review(
        project_id=project_id,
        version_id=version.id,
        reviewer_id=reviewer_id,
        decision="approved",
        claim_inventory_complete=True,
        extracted_claim_support_confirmed=True,
        score=90,
        notes=None,
    )
    app.export_package(project_id=project_id, version_id=version.id, requested_by=actor_id)
    assert repository.publications == []
    publication = app.request_publication(
        project_id=project_id,
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
        publication_request_id=publication.id,
        submitted_url="https://reddit.example/post",
        provider_submission_id=None,
    )
    verify_job = app.request_verification(
        project_id=project_id,
        submission_id=submission.id,
        idempotency_key="verification-job-0001",
    )
    measurement = app.record_measurement(
        project_id=project_id,
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


def test_prompt_releases_are_independent_and_old_release_is_unchanged() -> None:
    app, repository = _application()
    project_id, actor_id = uuid4(), uuid4()
    skill = app.create_prompt_skill(project_id=project_id, skill_key="youtube-script")
    first = app.publish_skill_version(
        project_id=project_id,
        skill_id=skill.id,
        source="Use {{brief}} {{evidence}} {{destination_policy}} for {{product}}.",
        actor_id=actor_id,
        output_schema=OUTPUT_SCHEMA,
        client_variable_names=("product",),
    )
    first_template = repository.releases[first.id]
    second = app.publish_skill_version(
        project_id=project_id,
        skill_id=skill.id,
        source="Compare {{product}} with {{brief}} {{evidence}} {{destination_policy}}.",
        actor_id=actor_id,
        output_schema=OUTPUT_SCHEMA,
        client_variable_names=("product",),
    )
    assert first.release_hash != second.release_hash
    assert repository.releases[first.id] is first_template
    assert "for {{product}}" in first_template.template


def test_edit_uses_exact_base_hash_and_new_version_invalidates_old_review_lineage() -> None:
    app, repository = _application()
    project_id = uuid4()
    base = PackageVersion(
        uuid4(),
        project_id,
        uuid4(),
        uuid4(),
        1,
        {"body": "old"},
        "old",
        "b" * 64,
        WorkflowStatus.APPROVED,
    )
    repository.packages.append(base)
    with pytest.raises(ConcurrencyConflict):
        app.edit_package_version(
            project_id=project_id,
            package_id=base.package_id,
            base_version_id=base.id,
            base_content_hash="0" * 64,
            content_json={"body": "new"},
            rendered_text="new",
            edited_by=uuid4(),
            reason="Fix",
        )
    edited = app.edit_package_version(
        project_id=project_id,
        package_id=base.package_id,
        base_version_id=base.id,
        base_content_hash=base.content_hash,
        content_json={"body": "new"},
        rendered_text="new",
        edited_by=uuid4(),
        reason="Fix",
    )
    assert edited.workflow_status == WorkflowStatus.GENERATED
    assert edited.base_version_id == base.id
    assert repository.packages[0].workflow_status == WorkflowStatus.SUPERSEDED


def test_authenticity_hard_blocks_cannot_be_overridden() -> None:
    app, _ = _application()
    with pytest.raises(PlacementRuleViolation, match="synthetic_testimonial"):
        app.create_brief_version(
            project_id=uuid4(),
            opportunity_id=uuid4(),
            primary_brand_entity_id=uuid4(),
            goals={},
            constraints={},
            compared_entity_ids=(),
            allowed_subject_entity_ids=(),
            actor_id=uuid4(),
            base_version_id=None,
            consumer_experience=None,
            authenticity_risks=(AuthenticityRisk.SYNTHETIC_TESTIMONIAL,),
        )


def test_approval_requires_claim_inventory_and_support_confirmation() -> None:
    ids = [uuid4() for _ in range(5)]
    with pytest.raises(PlacementRuleViolation, match="both claim review gates"):
        Review(
            ids[0],
            ids[1],
            ids[2],
            ids[3],
            ids[4],
            "approved",
            claim_inventory_complete=True,
            extracted_claim_support_confirmed=False,
        )
    app, repository = _application()
    version = PackageVersion(
        uuid4(),
        ids[1],
        uuid4(),
        uuid4(),
        1,
        {"body": "claim"},
        "claim",
        "c" * 64,
        WorkflowStatus.PENDING_HUMAN_REVIEW,
    )
    repository.packages.append(version)
    repository.claims.append(
        Claim(uuid4(), ids[1], version.id, "Unproven fact", "factual", "unsupported")
    )
    repository.review_submission = ReviewSubmission(
        uuid4(), ids[1], version.id, ids[3], datetime.now(UTC)
    )
    with pytest.raises(PlacementRuleViolation, match="factual claims"):
        app.submit_review(
            project_id=ids[1],
            version_id=version.id,
            reviewer_id=ids[4],
            decision="approved",
            claim_inventory_complete=True,
            extracted_claim_support_confirmed=True,
            score=90,
            notes=None,
        )
