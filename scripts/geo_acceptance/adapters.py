"""Controlled and live adapters used by the acceptance workflow."""

from __future__ import annotations

from decimal import Decimal
import hashlib
from html import escape
from typing import Protocol
from uuid import UUID, uuid4

from geo_core.model_gateway import (
    ModelCallBudget,
    ModelGateway,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
)
from geo_core.model_gateway.deepseek import (
    DeepSeekGateway,
    default_deepseek_capability_registry,
)
from geo_core.object_store import RetrievedObject, StoredObject
from geo_core.placements.url_verifier import (
    FetchedResponse,
    PublicUrlVerifier,
    UrlVerificationResult,
)

from scripts.geo_acceptance.contracts import AcceptanceConfig, MODEL, PRODUCT_URL


class ArtifactStore(Protocol):
    def put_object(
        self, *, key: str, content: bytes, content_type: str, expected_hash: str
    ) -> StoredObject: ...

    def get_object(self, *, key: str, expected_hash: str) -> RetrievedObject: ...


class MemoryArtifactStore:
    """Artifact adapter for deterministic acceptance and tests."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put_object(
        self, *, key: str, content: bytes, content_type: str, expected_hash: str
    ) -> StoredObject:
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected_hash:
            raise ValueError("artifact hash does not match pending metadata")
        self.objects[key] = (content, content_type)
        return StoredObject(
            uri=f"s3://geo-artifacts/{key}",
            bucket="geo-artifacts",
            key=key,
            content_type=content_type,
            content_hash=digest,
            etag=f'"{digest}"',
        )

    def get_object(self, *, key: str, expected_hash: str) -> RetrievedObject:
        content, content_type = self.objects[key]
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected_hash:
            raise ValueError("stored artifact hash no longer matches its receipt")
        return RetrievedObject(
            content=content,
            bucket="geo-artifacts",
            key=key,
            content_type=content_type,
            content_hash=digest,
            etag=f'"{digest}"',
        )


class DeterministicGateway:
    """Schema-valid model double; it cannot consume provider credentials."""

    provider = "acceptance-fake"

    def __init__(self, *, evidence_id: UUID, product_url: str) -> None:
        self.evidence_id = evidence_id
        self.product_url = product_url

    def generate(
        self,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult:
        del request, policy
        budget.consume()
        return ModelGatewayResult(
            output={
                "content_json": {
                    "title": "TerraMow V600 official product information",
                    "body": (
                        "ADVINSYS identifies TerraMow V600 as a Triple-Cam AI Vision "
                        "Robot Mower in the robotic lawn mower category."
                    ),
                    "disclosure": "Official information published by ADVINSYS.",
                    "cta_url": self.product_url,
                    "required_disclosures": [
                        "Official information published by ADVINSYS."
                    ],
                    "expected_links": [self.product_url],
                    "submission_notes": "Publish only through an authorised brand account.",
                },
                "rendered_text": (
                    "Official information published by ADVINSYS. TerraMow V600 is "
                    "identified on the official product page as a Triple-Cam AI Vision "
                    "Robot Mower in the robotic lawn mower category."
                ),
                "claims": [
                    {
                        "text": (
                            "TerraMow V600 is identified as a Triple-Cam AI Vision "
                            "Robot Mower in the robotic lawn mower category."
                        ),
                        "kind": "factual",
                        "support_status": "supported",
                        "evidence_item_ids": [str(self.evidence_id)],
                    }
                ],
                "internal_evidence_refs": [str(self.evidence_id)],
                "public_citation_refs": [str(self.evidence_id)],
            },
            call_log_id=uuid4(),
            provider_request_id="deterministic-acceptance",
            configured_model=MODEL,
            provider_reported_model="deterministic-acceptance",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=Decimal("0"),
            finish_reason="stop",
            response_hash=hashlib.sha256(
                f"{self.evidence_id}:deterministic-acceptance".encode()
            ).hexdigest(),
        )


class ControlledUrlVerifier(PublicUrlVerifier):
    """Verifier double that checks worker-provided governed expectations."""

    def verify(
        self,
        url: str,
        *,
        expected_text_fragments: tuple[str, ...],
        required_disclosures: tuple[str, ...],
        expected_links: tuple[str, ...],
        allowed_hosts: tuple[str, ...],
    ) -> UrlVerificationResult:
        for field, value in (
            ("expected_text_fragments", expected_text_fragments),
            ("required_disclosures", required_disclosures),
        ):
            if not value:
                raise ValueError(f"verification input omitted {field}")
        if any(not value.strip() for value in expected_links):
            raise ValueError("verification input contains an empty expected link")
        if "simulated.advinsys.example" not in allowed_hosts:
            raise ValueError("verification did not retain the destination allowlist")

        body = "".join(
            (
                "<!doctype html><html><body>",
                *(f"<p>{escape(value)}</p>" for value in expected_text_fragments),
                *(f"<p>{escape(value)}</p>" for value in required_disclosures),
                *(
                    f'<a href="{escape(value, quote=True)}">approved link</a>'
                    for value in expected_links
                ),
                "</body></html>",
            )
        ).encode("utf-8")
        verifier = PublicUrlVerifier(
            resolver=lambda _hostname, _port: ("8.8.8.8",),
            fetcher=_ControlledHttpsFetcher(body),
        )
        return verifier.verify(
            url,
            expected_text_fragments=expected_text_fragments,
            required_disclosures=required_disclosures,
            expected_links=expected_links,
            allowed_hosts=allowed_hosts,
        )


class _ControlledHttpsFetcher:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def fetch(
        self,
        url: str,
        *,
        pinned_ip: str,
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> FetchedResponse:
        del url, timeout_seconds
        if pinned_ip != "8.8.8.8":
            raise ValueError("controlled verification did not retain its pinned address")
        if len(self._body) > maximum_bytes:
            raise ValueError("controlled verification response exceeds its byte budget")
        return FetchedResponse(
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=self._body,
        )


def model_gateway(config: AcceptanceConfig, *, evidence_id: UUID) -> ModelGateway:
    if not config.live_deepseek:
        return DeterministicGateway(evidence_id=evidence_id, product_url=PRODUCT_URL)
    assert config.deepseek_key_file is not None
    return DeepSeekGateway(
        api_key_file=config.deepseek_key_file,
        capability_registry=default_deepseek_capability_registry(),
    )


def adapter_manifest(config: AcceptanceConfig) -> tuple[dict[str, object], ...]:
    """Describe exactly what the inline run did and did not exercise."""

    return (
        {
            "purpose": "job_execution",
            "adapter": "inline_postgres_dispatcher",
            "controlled": True,
        },
        {
            "purpose": "generation_model",
            "adapter": "deepseek_gateway" if config.live_deepseek else "deterministic_gateway",
            "controlled": not config.live_deepseek,
        },
        {
            "purpose": "prompt_simulation_model",
            "adapter": "deterministic_gateway",
            "controlled": True,
        },
        {
            "purpose": "publication_url_verification",
            "adapter": "controlled_url_verifier",
            "controlled": True,
        },
        {
            "purpose": "artifact_storage",
            "adapter": (
                "runtime_object_store" if config.runtime_object_store else "memory_artifact_store"
            ),
            "controlled": not config.runtime_object_store,
        },
        {
            "purpose": "worker_relay_topology",
            "adapter": "not_exercised",
            "controlled": True,
        },
    )
