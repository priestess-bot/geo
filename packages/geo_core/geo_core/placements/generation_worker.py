"""Dedicated placement generation worker orchestration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Mapping
from uuid import UUID

from geo_core.model_gateway import (
    ModelCallBudget,
    ModelGateway,
    ModelGatewayRequest,
    ModelPolicy,
)
from geo_core.model_gateway.contracts import ModelGatewayError
from geo_core.placements.domain import PackageVersion, PlacementRuleViolation
from geo_core.placements.ports import (
    GeneratedClaim,
    GeneratedPlacement,
    GenerationClaim,
    GenerationWorkerPort,
)


class PlacementGenerationWorker:
    """Claims/finalizes with short transactions and calls the model between them."""

    def __init__(
        self,
        *,
        port: GenerationWorkerPort,
        gateway: ModelGateway,
        worker_id: str,
        lease_for: timedelta = timedelta(minutes=5),
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker id is required")
        self._port = port
        self._gateway = gateway
        self._worker_id = worker_id
        self._lease_for = lease_for

    def run_once(self) -> PackageVersion | None:
        """Process one generation job; the claim call must release its transaction."""
        claim = self._port.claim_next(worker_id=self._worker_id, lease_for=self._lease_for)
        if claim is None:
            return None
        try:
            result = self._gateway.generate(
                ModelGatewayRequest(
                    messages=(
                        {
                            "role": "system",
                            "content": (
                                "Return JSON with content_json, rendered_text and claims. "
                                "Use only supplied evidence and never invent consumer experience."
                            ),
                        },
                        {"role": "user", "content": claim.rendered_prompt},
                    ),
                    configured_model=claim.configured_model,
                    prompt_bundle_hash=claim.prompt_bundle_hash,
                    project_id=claim.project_id,
                    purpose="geo-placement-generation",
                ),
                policy=ModelPolicy(),
                budget=ModelCallBudget(claim.model_call_budget),
            )
            placement = parse_generated_placement(result.output, claim=claim)
            return self._port.finalize(
                claim=claim,
                placement=placement,
                model_result=result,
                completed_at=datetime.now(UTC),
            )
        except (ModelGatewayError, PlacementRuleViolation) as exc:
            self._port.fail(
                claim=claim,
                error_code=type(exc).__name__,
                retry_at=datetime.now(UTC) + timedelta(minutes=1),
            )
            return None


def parse_generated_placement(
    output: Mapping[str, object], *, claim: GenerationClaim
) -> GeneratedPlacement:
    content_json = output.get("content_json")
    rendered_text = output.get("rendered_text")
    raw_claims = output.get("claims")
    if not isinstance(content_json, Mapping):
        raise PlacementRuleViolation("model output content_json must be an object")
    if not isinstance(rendered_text, str) or not rendered_text.strip():
        raise PlacementRuleViolation("model output rendered_text is required")
    if not isinstance(raw_claims, list):
        raise PlacementRuleViolation("model output claims must be an array")
    allowed_evidence = set(claim.evidence_item_ids)
    claims: list[GeneratedClaim] = []
    for item in raw_claims:
        if not isinstance(item, Mapping):
            raise PlacementRuleViolation("each generated claim must be an object")
        text = item.get("text")
        kind = item.get("kind")
        status = item.get("support_status")
        raw_evidence = item.get("evidence_item_ids", [])
        if not isinstance(text, str) or not text.strip():
            raise PlacementRuleViolation("generated claim text is required")
        if kind not in {"factual", "comparative", "experience", "non_factual"}:
            raise PlacementRuleViolation("generated claim kind is invalid")
        if status not in {"supported", "unsupported", "conflict", "not_required"}:
            raise PlacementRuleViolation("generated claim support status is invalid")
        if not isinstance(raw_evidence, list):
            raise PlacementRuleViolation("generated claim evidence ids must be an array")
        try:
            evidence_ids = tuple(UUID(str(value)) for value in raw_evidence)
        except (TypeError, ValueError) as exc:
            raise PlacementRuleViolation("generated claim evidence id is invalid") from exc
        if not set(evidence_ids).issubset(allowed_evidence):
            raise PlacementRuleViolation("claim references evidence outside the frozen pack")
        if kind != "non_factual" and status == "supported" and not evidence_ids:
            raise PlacementRuleViolation("a supported factual claim requires evidence")
        claims.append(GeneratedClaim(text.strip(), str(kind), str(status), evidence_ids))
    return GeneratedPlacement(dict(content_json), rendered_text.strip(), tuple(claims))
