from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from geo_core.placements.domain import (
    AuthenticityRisk,
    Claim,
    ConcurrencyConflict,
    PackageVersion,
    PlacementRuleViolation,
    Review,
    ReviewSubmission,
    WorkflowStatus,
)
from geo_core.placements.ports import GeneratedClaim
from tests.unit.placements.placement_test_support import OUTPUT_SCHEMA
from tests.unit.placements.test_placement_workflow import _application


def _content(body: str) -> dict[str, object]:
    return {"body": body, "required_disclosures": [], "expected_links": []}


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


def test_system_prompt_changes_release_hash_without_mutating_old_release() -> None:
    app, _repository = _application()
    project_id, actor_id = uuid4(), uuid4()
    skill = app.create_prompt_skill(project_id=project_id, skill_key="owned-site")
    source = "Use {{brief}} {{evidence}} {{destination_policy}}."
    first = app.publish_skill_version(
        project_id=project_id,
        skill_id=skill.id,
        source=source,
        actor_id=actor_id,
        output_schema=OUTPUT_SCHEMA,
        client_variable_names=(),
        system_template="Write concise content.",
    )
    second = app.publish_skill_version(
        project_id=project_id,
        skill_id=skill.id,
        source=source,
        actor_id=actor_id,
        output_schema=OUTPUT_SCHEMA,
        client_variable_names=(),
        system_template="Write detailed content.",
    )

    assert first.release_hash != second.release_hash
    assert first.system_template == "Write concise content."
    assert second.system_template == "Write detailed content."


def test_edit_uses_exact_base_hash_and_new_version_invalidates_old_review_lineage() -> None:
    app, repository = _application()
    project_id, campaign_id, opportunity_id, destination_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    base = PackageVersion(
        uuid4(),
        project_id,
        uuid4(),
        uuid4(),
        1,
        _content("old"),
        "old",
        "b" * 64,
        WorkflowStatus.APPROVED,
        campaign_id=campaign_id,
        opportunity_id=opportunity_id,
        destination_id=destination_id,
    )
    repository.packages.append(base)
    edited_claims = (GeneratedClaim("Editorial opinion", "non_factual", "not_required", ()),)
    with pytest.raises(ConcurrencyConflict):
        app.edit_package_version(
            project_id=project_id,
            campaign_id=campaign_id,
            package_id=base.package_id,
            base_version_id=base.id,
            base_content_hash="0" * 64,
            content_json=_content("new"),
            rendered_text="new",
            edited_by=uuid4(),
            reason="Fix",
            claims=edited_claims,
        )
    edited = app.edit_package_version(
        project_id=project_id,
        campaign_id=campaign_id,
        package_id=base.package_id,
        base_version_id=base.id,
        base_content_hash=base.content_hash,
        content_json=_content("new"),
        rendered_text="new",
        edited_by=uuid4(),
        reason="Fix",
        claims=edited_claims,
    )
    assert edited.workflow_status == WorkflowStatus.GENERATED
    assert edited.base_version_id == base.id
    assert repository.packages[0].workflow_status == WorkflowStatus.SUPERSEDED
    assert (
        repository.list_claims(project_id=project_id, version_id=edited.id)[0].claim_text
        == "Editorial opinion"
    )


def test_edit_and_review_reject_an_empty_claim_inventory() -> None:
    app, repository = _application()
    project_id, campaign_id, opportunity_id, destination_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    base = PackageVersion(
        uuid4(),
        project_id,
        uuid4(),
        uuid4(),
        1,
        _content("old"),
        "old",
        "b" * 64,
        campaign_id=campaign_id,
        opportunity_id=opportunity_id,
        destination_id=destination_id,
    )
    repository.packages.append(base)
    with pytest.raises(PlacementRuleViolation, match="complete claim inventory"):
        app.edit_package_version(
            project_id=project_id,
            campaign_id=campaign_id,
            package_id=base.package_id,
            base_version_id=base.id,
            base_content_hash=base.content_hash,
            content_json=_content("new"),
            rendered_text="new",
            edited_by=uuid4(),
            reason="Fix",
            claims=(),
        )
    with pytest.raises(PlacementRuleViolation, match="non-empty claim inventory"):
        app.submit_for_review(
            project_id=project_id,
            campaign_id=campaign_id,
            version_id=base.id,
            submitted_by=uuid4(),
        )


def test_authenticity_hard_blocks_cannot_be_overridden() -> None:
    app, _ = _application()
    with pytest.raises(PlacementRuleViolation, match="synthetic_testimonial"):
        app.create_brief_version(
            project_id=uuid4(),
            campaign_id=uuid4(),
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
        _content("claim"),
        "claim",
        "c" * 64,
        WorkflowStatus.PENDING_HUMAN_REVIEW,
        campaign_id=ids[0],
        opportunity_id=uuid4(),
        destination_id=uuid4(),
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
            campaign_id=ids[0],
            version_id=version.id,
            reviewer_id=ids[4],
            decision="approved",
            claim_inventory_complete=True,
            extracted_claim_support_confirmed=True,
            score=90,
            notes=None,
        )
