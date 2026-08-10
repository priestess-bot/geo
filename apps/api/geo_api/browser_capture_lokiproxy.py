"""LokiProxy pool setup kept separate from the Browser Capture route table."""

from __future__ import annotations

import json
from uuid import UUID, uuid5

from geo_api.browser_capture_contracts import (
    ConfigureLokiProxyPoolRequest,
    LokiProxyPoolSetupResponse,
)
from geo_api.problems import ApiProblem
from geo_api.secret_store_runtime import SecretStoreApi
from geo_core.access.models import AccessPrincipal
from geo_core.browser_capture.admin import BrowserCaptureAdminService
from geo_core.secrets import SecretStoreError, SecretValue


_SECRET_NAMESPACE = UUID("6a603035-688c-5b05-b660-58a3d364a40b")


def configure_lokiproxy_pool(
    *,
    project_id: UUID,
    payload: ConfigureLokiProxyPoolRequest,
    principal: AccessPrincipal,
    idempotency_key: str,
    service: BrowserCaptureAdminService,
    secrets: SecretStoreApi,
) -> LokiProxyPoolSetupResponse:
    key = idempotency_key.strip()
    if len(key) < 8 or len(key) > 240:
        raise ApiProblem(
            status=422,
            title="Invalid Idempotency Key",
            detail="LokiProxy pool setup needs an Idempotency-Key between 8 and 240 characters.",
            type_uri="urn:geo:problem:browser-egress-idempotency",
        )
    reference_id = uuid5(_SECRET_NAMESPACE, f"{project_id}:{key}:credential")
    secret_value = SecretValue(json.dumps({
        "provider": "lokiproxy",
        "pool_product": payload.pool_product,
        "username_template": payload.username_template,
        "password": payload.password.get_secret_value(),
        "lease_ttl_seconds": payload.session_ttl_seconds,
    }, ensure_ascii=True, separators=(",", ":")))
    try:
        created = secrets.create(
            principal, project_id=project_id, reference_id=reference_id,
            purpose="browser_egress.lokiproxy", value=secret_value,
            expected_version=0, idempotency_key=f"{key}:secret-create",
        )
        verified = secrets.verify(
            principal, project_id=project_id, reference_id=reference_id,
            version=created.version, expected_version=created.aggregate_version,
            idempotency_key=f"{key}:secret-verify",
        )
        activated = secrets.activate(
            principal, project_id=project_id, reference_id=reference_id,
            version=created.version, expected_version=verified.aggregate_version,
            idempotency_key=f"{key}:secret-activate",
        )
    except SecretStoreError as error:
        raise ApiProblem(
            status=409,
            title="LokiProxy Secret Setup Failed",
            detail=str(error),
            type_uri="urn:geo:problem:browser-egress-secret",
        ) from error
    endpoint = service.install_egress_endpoint(
        project_id=project_id,
        actor_id=principal.identity_id,
        name=f"{payload.name[:187].rstrip()} · {str(reference_id)[:8]}",
        protocol=payload.protocol,
        endpoint_host=payload.endpoint_host,
        endpoint_port=payload.endpoint_port,
        secret_reference_id=reference_id,
        secret_purpose="browser_egress.lokiproxy",
        secret_version=activated.version,
        expected_region=payload.expected_region,
        network_type="mobile" if payload.pool_product == "mobile" else "residential",
        egress_policy_version="lokiproxy-au-sticky-v1",
        egress_cohort_key=f"lokiproxy-au-{payload.pool_product}",
        provider="lokiproxy",
        pool_product=payload.pool_product,
        session_ttl_seconds=payload.session_ttl_seconds,
        max_concurrency=payload.max_concurrency,
    )
    return LokiProxyPoolSetupResponse.model_validate({
        "endpoint": endpoint,
        "secret_reference_id": reference_id,
        "secret_version": activated.version,
        "egress_test_required": True,
    })


__all__ = ["configure_lokiproxy_pool"]
