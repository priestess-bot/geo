from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from geo_core.model_gateway import ModelGatewayResult


_REVISION_TERMS = (
    "rainfall",
    "slope",
    "shade",
    "frost",
    "clay",
    "noise",
    "battery",
    "boundary",
    "service",
    "seasonality",
)


class CoverageQuestionGateway:
    provider = "integration-coverage-question-gateway"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request: Any, *, policy: Any, budget: Any) -> ModelGatewayResult:
        del policy
        budget.consume()
        self.calls += 1
        payload = json.loads(request.messages[1]["content"])
        fact_id = payload["facts"][0]["fact_candidate_id"]
        questions = []
        for dimension in payload["dimensions"]:
            topic = str(dimension["topic_cluster"]).replace("_", " ")
            local_index = str(dimension["dimension_key"]).rsplit(":", 1)[-1]
            if dimension["coverage_role"] == "brand_control":
                text = f"How well does {dimension['subject']} support {topic} in Australia?"
            elif local_index == "1":
                text = (
                    "Which Australian households benefit most from a robot lawn mower "
                    f"when {topic} matters?"
                )
            elif local_index == "2":
                text = (
                    f"Which {topic} capabilities should Australians match to their property "
                    "before choosing a robot lawn mower?"
                )
            elif local_index == "3":
                text = (
                    f"How should Australians compare robot lawn mower alternatives for {topic}?"
                )
            else:
                text = (
                    "What limitations should Australians investigate when assessing "
                    f"robot lawn mowers for {topic}?"
                )
            semantic = (
                f"{topic} shared product fit"
                if dimension["coverage_role"] == "product_fit"
                and dimension["topic_cluster"] == "buying_priorities"
                and local_index in {"1", "2"}
                else f"{topic} {local_index} {dimension['coverage_role']}"
            )
            questions.append(
                {
                    "candidate_id": f"coverage-{dimension['dimension_key']}",
                    "dimension_key": dimension["dimension_key"],
                    "variant_index": 1,
                    "text": text,
                    "semantic_fingerprint": semantic,
                    "supported_fact_ids": [fact_id],
                    "supported_entity_ids": [],
                    "parent_candidate_id": None,
                }
            )
        output = {"questions": questions}
        response_hash = hashlib.sha256(
            json.dumps(output, sort_keys=True).encode()
        ).hexdigest()
        return ModelGatewayResult(
            output=output,
            call_log_id=uuid4(),
            provider_request_id=f"coverage-question-{uuid4()}",
            configured_model=request.configured_model,
            provider_reported_model=request.configured_model,
            prompt_tokens=300,
            completion_tokens=600,
            cost_usd=Decimal("0.003"),
            finish_reason="stop",
            response_hash=response_hash,
        )


def revise_possible_duplicate_candidates(
    knowledge: Any,
    principal: Any,
    *,
    project_id: UUID,
    campaign_id: UUID,
    candidates: Sequence[Mapping[str, Any]],
) -> dict[UUID, str]:
    """Give every flagged candidate distinct effective text before finalization."""
    revisions: dict[UUID, str] = {}
    revision_index = 0
    for candidate in candidates:
        if candidate["dedup_status"] != "possible_duplicate":
            continue
        term = _REVISION_TERMS[revision_index]
        revision_index += 1
        revised_text = (
            f"Which Australian buyer should verify {term} "
            f"marker {str(candidate['id'])[:8]} before comparing available options?"
        )
        knowledge.edit_question_candidate(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            candidate_id=candidate["id"],
            query_text=revised_text,
        )
        revisions[candidate["id"]] = revised_text
    return revisions
