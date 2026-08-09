"""Private helpers shared by question application command mixins."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence
from uuid import UUID

from geo_core.knowledge.domain import KnowledgeConflict, KnowledgeValidationError
from geo_core.knowledge.question_coverage import CoverageQuestionPlan


def validate_competitors(
    connection: Any,
    project_id: UUID,
    campaign_id: UUID,
    dimensions: Sequence[Any],
) -> None:
    competitor_ids = {
        item.competitor_entity_id
        for item in dimensions
        if item.competitor_entity_id is not None
    }
    if not competitor_ids:
        return
    rows = many(
        connection.execute(
            """SELECT entity.id
               FROM product_entities entity
               JOIN campaign_entities member
                 ON member.entity_id = entity.id AND member.project_id = entity.project_id
               WHERE entity.project_id = %s AND entity.id = ANY(%s)
                 AND entity.entity_type = 'competitor' AND entity.status = 'active'
                 AND member.campaign_id = %s AND member.entity_role = 'competitor'""",
            (project_id, list(competitor_ids), campaign_id),
        )
    )
    if {item["id"] for item in rows} != competitor_ids:
        raise KnowledgeConflict("question competitor dimensions require Campaign competitors")


def generation_result(
    value: Mapping[str, object],
    *,
    dimensions: int,
    facts: int,
    entities: int,
    generation_mode: str = "single_scenario",
    coverage_plan: CoverageQuestionPlan | None = None,
) -> Mapping[str, object]:
    return {
        "job_id": value["job_id"],
        "project_id": value["project_id"],
        "campaign_id": value["campaign_id"],
        "status": value["status"],
        "input_hash": value["input_hash"],
        "dimension_count": dimensions,
        "fact_input_count": facts,
        "entity_input_count": entities,
        "generation_mode": generation_mode,
        "coverage_profile": coverage_plan.profile_key if coverage_plan else None,
        "target_count": coverage_plan.target_count if coverage_plan else None,
    }


def idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 200:
        raise KnowledgeValidationError("Idempotency-Key must contain 1 to 200 characters")
    return normalized


def canonical_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def json_value(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def one(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    return dict(value) if value is not None else None


def many(cursor: Any) -> list[dict[str, Any]]:
    return [dict(value) for value in cursor.fetchall()]
