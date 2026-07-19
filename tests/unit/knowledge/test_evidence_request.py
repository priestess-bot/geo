from __future__ import annotations

from uuid import uuid4

import pytest

from geo_core.catalog.domain import Confidentiality, PublicCitation, SubjectRole, UsageRights
from geo_core.knowledge.domain import KnowledgeValidationError
from geo_core.knowledge.evidence_request import (
    normalize_citation,
    promotion_idempotency_key,
    promotion_request_hash,
)


def test_promotion_hash_is_canonical_and_binds_the_target_fact() -> None:
    project_id, fact_id, subject_id = uuid4(), uuid4(), uuid4()
    citation = normalize_citation(
        PublicCitation(True, " https://source.example/fact ", " Source ", " Source ")
    )
    values = {
        "project_id": project_id,
        "fact_id": fact_id,
        "title": "Governed Fact",
        "subject_entity_id": subject_id,
        "subject_role": SubjectRole.PRODUCT,
        "usage_rights": UsageRights.PUBLIC_REFERENCE,
        "confidentiality": Confidentiality.PUBLIC,
        "public_citation": citation,
    }

    first = promotion_request_hash(**values)

    assert first == promotion_request_hash(**values)
    assert first != promotion_request_hash(**{**values, "fact_id": uuid4()})
    assert first != promotion_request_hash(**{**values, "title": "Changed Fact"})
    assert citation.source_url == "https://source.example/fact"


@pytest.mark.parametrize("value", ["", " ", "x" * 201])
def test_promotion_idempotency_key_is_required_and_bounded(value: str) -> None:
    with pytest.raises(KnowledgeValidationError, match="Idempotency-Key"):
        promotion_idempotency_key(value)
