from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from geo_core.placements.domain import (
    CampaignContextMismatch,
    CampaignPlacementReadiness,
    CampaignResourceContext,
    CampaignResourceKind,
    CampaignScope,
    ChannelReadiness,
    ChannelReadinessReason,
    OpportunityPromptReleaseBinding,
    PlacementConflict,
    PlacementRuleViolation,
    PromptReleaseBindingStatus,
    PromptReleaseState,
    PromptReleaseStatus,
    STANDARD_PLACEMENT_CHANNELS,
    assert_same_campaign_lineage,
    transition_prompt_release_status,
)


NOW = datetime(2026, 7, 19, tzinfo=UTC)


def test_campaign_resource_lineage_rejects_mixed_opportunities_and_campaigns() -> None:
    project_id, campaign_id = uuid4(), uuid4()
    first = CampaignResourceContext(
        CampaignScope(project_id, campaign_id),
        CampaignResourceKind.BRIEF_VERSION,
        uuid4(),
        uuid4(),
        uuid4(),
    )
    other_opportunity = CampaignResourceContext(
        first.scope,
        CampaignResourceKind.EVIDENCE_ATTEMPT,
        uuid4(),
        uuid4(),
        first.destination_id,
    )
    other_campaign = CampaignResourceContext(
        CampaignScope(project_id, uuid4()),
        CampaignResourceKind.EVIDENCE_ATTEMPT,
        uuid4(),
        first.opportunity_id,
        first.destination_id,
    )

    assert assert_same_campaign_lineage(first) == first
    with pytest.raises(CampaignContextMismatch, match="same Opportunity"):
        assert_same_campaign_lineage(first, other_opportunity)
    with pytest.raises(CampaignContextMismatch, match="expected Campaign"):
        assert_same_campaign_lineage(first, other_campaign)


def test_prompt_release_lifecycle_is_forward_only() -> None:
    assert transition_prompt_release_status(status="draft", command="approve") == "approved"
    assert transition_prompt_release_status(status="approved", command="revoke") == "revoked"
    for status, command in (("draft", "revoke"), ("approved", "approve"), ("revoked", "approve")):
        with pytest.raises(PlacementConflict):
            transition_prompt_release_status(status=status, command=command)


def test_prompt_release_state_requires_linear_history_and_revoke_reason() -> None:
    values = (uuid4(), uuid4(), uuid4())
    PromptReleaseState(
        values[0], values[1], values[2], 1, None,
        PromptReleaseStatus.APPROVED, uuid4(), NOW,
    )
    with pytest.raises(PlacementRuleViolation, match="linear"):
        PromptReleaseState(
            uuid4(), values[1], values[2], 2, None,
            PromptReleaseStatus.REVOKED, uuid4(), NOW, "policy changed",
        )
    with pytest.raises(PlacementRuleViolation, match="requires a reason"):
        PromptReleaseState(
            uuid4(), values[1], values[2], 2, values[0],
            PromptReleaseStatus.REVOKED, uuid4(), NOW,
        )


def test_opportunity_binding_requires_complete_frozen_release_identity() -> None:
    common = {
        "id": uuid4(),
        "project_id": uuid4(),
        "campaign_id": uuid4(),
        "opportunity_id": uuid4(),
        "destination_id": uuid4(),
        "binding_version": 2,
        "previous_binding_id": uuid4(),
        "changed_by": uuid4(),
        "changed_at": NOW,
    }
    binding = OpportunityPromptReleaseBinding(
        **common,
        status=PromptReleaseBindingStatus.BOUND,
        template_release_id=uuid4(),
        skill_version_id=uuid4(),
        release_version=4,
        release_hash="a" * 64,
    )
    assert binding.release_version == 4

    with pytest.raises(PlacementRuleViolation, match="full Release identity"):
        OpportunityPromptReleaseBinding(
            **common,
            status=PromptReleaseBindingStatus.BOUND,
            template_release_id=uuid4(),
        )
    with pytest.raises(PlacementRuleViolation, match="cannot carry Release identity"):
        OpportunityPromptReleaseBinding(
            **common,
            status=PromptReleaseBindingStatus.UNBOUND,
            template_release_id=uuid4(),
        )


def test_campaign_readiness_has_exactly_nine_ordered_channels() -> None:
    blocked = ChannelReadiness(
        publication_channel=STANDARD_PLACEMENT_CHANNELS[0],
        ready=False,
        reasons=(ChannelReadinessReason.PROMPT_BINDING_MISSING,),
    )
    ready = tuple(
        ChannelReadiness(publication_channel=channel, ready=True, reasons=())
        for channel in STANDARD_PLACEMENT_CHANNELS[1:]
    )
    result = CampaignPlacementReadiness(uuid4(), uuid4(), (blocked, *ready))

    assert result.ready_count == 8
    assert not result.is_ready
    with pytest.raises(PlacementRuleViolation, match="all standard channels"):
        CampaignPlacementReadiness(result.project_id, result.campaign_id, tuple(reversed(result.channels)))
