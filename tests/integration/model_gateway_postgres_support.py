from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from geo_core.model_gateway.ports import canonical_json_hash
from geo_core.model_gateway.contracts import ModelGatewayRequest, ModelGatewayResult
from geo_core.model_gateway.postgres_artifact_composition import (
    build_provider_artifact_worker_composition,
)
from geo_core.model_gateway.provider_adapters.artifacts import (
    MinioProviderArtifactSink,
    canonical_provider_json_bytes,
)
from geo_core.model_gateway.releases import AdapterRelease, ModelRoute
from geo_core.object_store import RetrievedObject, StoredObject, parse_s3_uri
from geo_core.project_scope import set_project_scope


class MemoryProviderArtifactObjectStore:
    def __init__(self) -> None:
        self.bucket = "provider-artifacts"
        self.objects: dict[str, tuple[bytes, str]] = {}

    def uri_for_key(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObject:
        payload = content.encode() if isinstance(content, str) else content
        digest = hashlib.sha256(payload).hexdigest()
        if expected_hash not in (None, digest):
            raise AssertionError("Provider artifact fixture object hash differs")
        self.objects[key] = (payload, content_type)
        return StoredObject(
            uri=self.uri_for_key(key),
            bucket=self.bucket,
            key=key,
            content_type=content_type,
            content_hash=digest,
            etag=None,
        )

    def get_s3_uri(
        self, *, uri: str, expected_hash: str | None = None
    ) -> RetrievedObject:
        bucket, key = parse_s3_uri(uri)
        payload, content_type = self.objects[key]
        digest = hashlib.sha256(payload).hexdigest()
        if bucket != self.bucket or expected_hash not in (None, digest):
            raise AssertionError("Provider artifact fixture retrieval differs")
        return RetrievedObject(
            content=payload,
            bucket=bucket,
            key=key,
            content_type=content_type,
            content_hash=digest,
            etag=None,
        )

    def delete_s3_uri(self, *, uri: str) -> bool:
        _bucket, key = parse_s3_uri(uri)
        self.objects.pop(key, None)
        return True


def provider_artifact_sink(
    *, database_url: str, directory: Path
) -> MinioProviderArtifactSink:
    keyring = directory / "provider-artifact-keyring.json"
    keyring.write_text(
        json.dumps(
            {
                "format": "geo-master-keyring-v1",
                "active_version": 1,
                "keys": {"1": base64.b64encode(b"P" * 32).decode("ascii")},
            }
        ),
        encoding="utf-8",
    )
    keyring.chmod(0o600)
    return build_provider_artifact_worker_composition(
        database_url=database_url,
        object_store=MemoryProviderArtifactObjectStore(),
        worker_id="model-gateway-integration-artifacts",
        keyring_path=str(keyring),
    ).sink


def attach_provider_artifacts(
    *,
    sink: MinioProviderArtifactSink,
    route: ModelRoute,
    adapter: AdapterRelease,
    request: ModelGatewayRequest,
    result: ModelGatewayResult,
) -> ModelGatewayResult:
    if request.project_id is None or request.model_call_job_id is None:
        raise AssertionError("Model Gateway fixture request lacks Job lineage")
    if request.model_call_attempt_id is None:
        raise AssertionError("Model Gateway fixture request lacks Attempt lineage")
    raw_payload = {"response_hash": result.response_hash, "output": result.output}
    raw_hash = hashlib.sha256(canonical_provider_json_bytes(raw_payload)).hexdigest()
    bundle = sink.capture(
        project_id=request.project_id,
        job_id=request.model_call_job_id,
        attempt_id=request.model_call_attempt_id,
        provider=route.provider,
        adapter_release_id=route.adapter_release_id,
        adapter_release_hash=route.adapter_release_hash,
        data_policy=adapter.data_policy,
        usage_purpose=request.purpose,
        usage_audience=request.usage_audience,
        raw_payload=raw_payload,
        raw_content_hash=raw_hash,
        derived_payload=result.output,
    )
    return replace(
        result,
        raw_artifact_reference=bundle.raw.manifest_reference,
        raw_artifact_manifest_hash=bundle.raw.manifest_hash,
        raw_artifact_content_hash=bundle.raw.content_hash,
        raw_artifact_byte_size=bundle.raw.byte_size,
        derived_artifact_reference=bundle.derived.manifest_reference,
        derived_artifact_manifest_hash=bundle.derived.manifest_hash,
        derived_artifact_content_hash=bundle.derived.content_hash,
        derived_artifact_byte_size=bundle.derived.byte_size,
    )


def assert_terminal_shape_guards(
    *,
    app_url: str,
    project_id: UUID,
    job_id: UUID,
    attempt_id: UUID,
    actor_id: UUID,
) -> None:
    cases = (
        {
            "status": "succeeded",
            "paid": 0,
            "call_id": uuid4(),
            "output_hash": "1" * 64,
            "response_hash": "2" * 64,
            "classification": None,
            "error_code": None,
            "retryable": None,
            "actor": None,
            "evidence": None,
            "message": "status_shape",
        },
        {
            "status": "failed",
            "paid": 1,
            "call_id": uuid4(),
            "output_hash": "1" * 64,
            "response_hash": "2" * 64,
            "classification": "provider",
            "error_code": "timeout",
            "retryable": False,
            "actor": None,
            "evidence": None,
            "message": "failed_artifact_shape",
        },
        {
            "status": "failed",
            "paid": 0,
            "call_id": None,
            "output_hash": None,
            "response_hash": None,
            "classification": "manual_reconciliation",
            "error_code": "configuration",
            "retryable": False,
            "actor": None,
            "evidence": None,
            "message": "reconciliation_class",
        },
        {
            "status": "failed",
            "paid": 0,
            "call_id": None,
            "output_hash": None,
            "response_hash": None,
            "classification": "provider",
            "error_code": "configuration",
            "retryable": False,
            "actor": actor_id,
            "evidence": "operator:forged-reconciliation",
            "message": "reconciliation_class",
        },
    )
    for case in cases:
        with psycopg.connect(app_url) as connection:
            set_project_scope(connection, project_id)
            budget_version = connection.execute(
                """SELECT budget_version FROM model_gateway_job_admissions
                   WHERE project_id = %s AND job_id = %s""",
                (project_id, job_id),
            ).fetchone()[0]
            with pytest.raises(psycopg.Error, match=case["message"]):
                connection.execute(
                    """INSERT INTO model_gateway_terminal_events(
                           id, project_id, job_id, attempt_id, expected_budget_version,
                           status, occurred_at, paid_call_count, gateway_call_log_id,
                           configured_model, provider_reported_model, provider_request_id,
                           prompt_tokens, completion_tokens, cost_usd, finish_reason,
                           input_hash, output_hash, response_hash, search_mode, capture_method,
                           citation_count, citation_lineage_hash, search_event_count,
                           search_lineage_hash, usage_details_hash,
                           raw_artifact_reference_hash, raw_artifact_policy_hash,
                           raw_artifact_storage_decision, raw_artifact_retention_days,
                           error_classification, error_code, error_retryable,
                           reconciled_by, reconciliation_evidence_ref
                       )
                       SELECT %s, attempt.project_id, attempt.job_id, attempt.id, %s,
                              %s, clock_timestamp(), %s, %s,
                              attempt.configured_model, attempt.configured_model, NULL,
                              NULL, NULL, NULL, NULL,
                              attempt.input_hash, %s, %s,
                              attempt.search_mode, attempt.capture_method,
                              0, %s, 0, %s, %s,
                              NULL, attempt.raw_artifact_policy_hash,
                              attempt.raw_artifact_storage_decision,
                              attempt.raw_artifact_retention_days,
                              %s, %s, %s, %s, %s
                       FROM model_gateway_call_attempts AS attempt
                       WHERE attempt.project_id = %s AND attempt.job_id = %s
                         AND attempt.id = %s""",
                    (
                        uuid4(),
                        budget_version,
                        case["status"],
                        case["paid"],
                        case["call_id"],
                        case["output_hash"],
                        case["response_hash"],
                        canonical_json_hash(()),
                        canonical_json_hash(()),
                        canonical_json_hash({}),
                        case["classification"],
                        case["error_code"],
                        case["retryable"],
                        case["actor"],
                        case["evidence"],
                        project_id,
                        job_id,
                        attempt_id,
                    ),
                )
            connection.rollback()


__all__ = [
    "MemoryProviderArtifactObjectStore",
    "assert_terminal_shape_guards",
    "attach_provider_artifacts",
    "provider_artifact_sink",
]
