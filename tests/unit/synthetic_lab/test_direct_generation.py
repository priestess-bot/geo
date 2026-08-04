from __future__ import annotations

from dataclasses import replace
import hashlib
from uuid import uuid4

import pytest

from geo_core.synthetic_lab.channel_styles import ChannelStyleVersion
from geo_core.synthetic_lab.direct_generation import (
    DirectGenerationScenario,
    DirectKnowledgeItem,
    DirectKnowledgeSnapshot,
)
from geo_core.synthetic_lab.domain import SyntheticLabContractError
from geo_core.synthetic_lab.postgres_codec import decode_object, encode_object


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_manual_style_and_direct_knowledge_are_versioned_immutable_inputs() -> None:
    project_id = uuid4()
    product_id = uuid4()
    style_id = uuid4()
    style_v1 = ChannelStyleVersion(
        id=uuid4(),
        project_id=project_id,
        style_id=style_id,
        version_number=1,
        channel="reddit",
        directive="Use candid Australian English and only supplied knowledge.",
    )
    style_v2 = ChannelStyleVersion(
        id=uuid4(),
        project_id=project_id,
        style_id=style_id,
        version_number=2,
        previous_version_id=style_v1.id,
        channel="reddit",
        directive="Use concise, candid Australian English and state uncertainty.",
    )
    item = DirectKnowledgeItem(
        evidence_id=uuid4(),
        subject_entity_id=product_id,
        subject_name="ADVINSYS TerraMow V600",
        kind="citation",
        summary="The V600 is listed for lawns up to 600 square metres.",
        snapshot_hash=_hash("v600-evidence"),
        source_title="Official product page",
        source_url="https://www.advinsys.com.au/products/v600",
    )
    first = DirectKnowledgeSnapshot(
        id=uuid4(),
        project_id=project_id,
        primary_subject_id=product_id,
        items=(item,),
    )
    replay = replace(first, id=uuid4())

    assert style_v1.style_hash != style_v2.style_hash
    assert first.snapshot_hash == replay.snapshot_hash
    assert decode_object(*encode_object(style_v2)[:2]) == style_v2
    assert decode_object(*encode_object(first)[:2]) == first


def test_direct_scenario_rejects_unsupported_channels_and_missing_product_evidence() -> None:
    project_id = uuid4()
    product_id = uuid4()
    with pytest.raises(SyntheticLabContractError, match="channel is unsupported"):
        DirectGenerationScenario(
            id=uuid4(),
            project_id=project_id,
            input_snapshot_id=uuid4(),
            channel="facebook",
            persona="Australian buyer",
            use_case="A short review",
            subject="ADVINSYS TerraMow V600",
            generation_goal="Write a short practical review.",
        )

    brand_item = DirectKnowledgeItem(
        evidence_id=uuid4(),
        subject_entity_id=uuid4(),
        subject_name="ADVINSYS",
        kind="citation",
        summary="ADVINSYS operates an Australian website.",
        snapshot_hash=_hash("brand-evidence"),
    )
    with pytest.raises(SyntheticLabContractError, match="primary-subject evidence"):
        DirectKnowledgeSnapshot(
            id=uuid4(),
            project_id=project_id,
            primary_subject_id=product_id,
            items=(brand_item,),
        )


def test_execution_knowledge_snapshot_can_be_limited_to_approved_facts() -> None:
    project_id = uuid4()
    product_id = uuid4()
    fact = DirectKnowledgeItem(
        evidence_id=uuid4(),
        subject_entity_id=product_id,
        subject_name="ADVINSYS TerraMow V600",
        kind="approved_fact",
        summary="The approved product name is TerraMow V600.",
        snapshot_hash=_hash("approved-v600-name"),
    )

    snapshot = DirectKnowledgeSnapshot(
        id=uuid4(),
        project_id=project_id,
        primary_subject_id=product_id,
        items=(fact,),
    )

    assert snapshot.items == (fact,)
    assert snapshot.items[0].kind == "approved_fact"
