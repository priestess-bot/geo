"""LokiProxy pool invariants shared by Admin admission and Browser workers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from geo_core.browser_capture.domain import BrowserCaptureError
from geo_core.project_scope import set_project_scope


ENABLE_ENDPOINT_SQL = """UPDATE browser_egress_endpoints endpoint
      SET status = 'approved', approved_by = %s, approved_at = %s,
          disabled_at = NULL, health_status = 'untested',
          consecutive_failures = 0, cooldown_until = NULL, last_error_class = NULL
    WHERE endpoint.project_id = %s AND endpoint.id = %s
      AND endpoint.status IN ('draft', 'approved', 'disabled')
      AND EXISTS (
        SELECT 1 FROM secret_versions secret
         WHERE secret.reference_id = endpoint.secret_reference_id
           AND secret.project_id = endpoint.project_id
           AND secret.purpose = endpoint.secret_purpose
           AND secret.version = endpoint.secret_version
           AND secret.status = 'active'
      )
   RETURNING endpoint.*"""

CREATE_ENDPOINT_SQL = """INSERT INTO browser_egress_endpoints(
       id, project_id, name, protocol, endpoint_host, endpoint_port,
       secret_reference_id, secret_purpose, secret_version,
       expected_country, expected_region, network_type, sticky_mode,
       egress_policy_version, egress_cohort_key, provider, pool_product,
       session_ttl_seconds, max_concurrency, status, created_by, created_at
   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'AU', %s,
             %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s)
   RETURNING *"""

SET_ENDPOINT_STATUS_SQL = """UPDATE browser_egress_endpoints endpoint
      SET status = %s,
          disabled_at = CASE WHEN %s = 'disabled' THEN %s ELSE NULL END,
          health_status = CASE WHEN %s = 'disabled' THEN 'disabled' ELSE 'untested' END,
          consecutive_failures = CASE WHEN %s = 'disabled' THEN consecutive_failures ELSE 0 END,
          cooldown_until = NULL,
          last_error_class = CASE WHEN %s = 'disabled' THEN last_error_class ELSE NULL END
    WHERE endpoint.project_id = %s AND endpoint.id = %s
      AND endpoint.status IN ('approved', 'disabled') AND endpoint.status <> %s
      AND (%s = 'disabled' OR EXISTS (
        SELECT 1 FROM secret_versions secret
         WHERE secret.reference_id = endpoint.secret_reference_id
           AND secret.project_id = endpoint.project_id
           AND secret.purpose = endpoint.secret_purpose
           AND secret.version = endpoint.secret_version
           AND secret.status = 'active'
      ))
   RETURNING endpoint.*"""


def install_pool_profile(
    *,
    connect: Callable[[], Any],
    project_id: UUID,
    actor_id: UUID,
    name: str,
    protocol: str,
    endpoint_host: str,
    endpoint_port: int,
    secret_reference_id: UUID,
    secret_purpose: str,
    secret_version: int,
    expected_region: str | None,
    network_type: str,
    egress_policy_version: str,
    egress_cohort_key: str,
    pool_product: str,
    session_ttl_seconds: int,
    max_concurrency: int,
    activated_at: datetime,
) -> Mapping[str, object]:
    expected: dict[str, object] = {
        "protocol": protocol,
        "endpoint_host": endpoint_host.strip(),
        "endpoint_port": endpoint_port,
        "secret_reference_id": secret_reference_id,
        "secret_purpose": secret_purpose,
        "secret_version": secret_version,
        "expected_region": expected_region,
        "network_type": network_type,
        "sticky_mode": "credential_session",
        "egress_policy_version": egress_policy_version,
        "egress_cohort_key": egress_cohort_key,
        "provider": "lokiproxy",
        "pool_product": pool_product,
        "session_ttl_seconds": session_ttl_seconds,
        "max_concurrency": max_concurrency,
    }
    with connect() as connection:
        set_project_scope(connection, project_id)
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"lokiproxy-pool:{project_id}",),
        )
        row = connection.execute(
            """SELECT * FROM browser_egress_endpoints
                WHERE project_id = %s AND name = %s""",
            (project_id, name.strip()),
        ).fetchone()
        if row is None:
            row = connection.execute(
                CREATE_ENDPOINT_SQL,
                (
                    uuid4(), project_id, name.strip(), protocol, endpoint_host.strip(),
                    endpoint_port, secret_reference_id, secret_purpose, secret_version,
                    expected_region, network_type, "credential_session",
                    egress_policy_version, egress_cohort_key, "lokiproxy", pool_product,
                    session_ttl_seconds, max_concurrency, actor_id, activated_at,
                ),
            ).fetchone()
        endpoint = dict(row)
        if any(endpoint.get(key) != value for key, value in expected.items()):
            raise BrowserCaptureError(
                "This LokiProxy idempotency key already has different pool settings"
            )
        if endpoint["status"] != "draft":
            return endpoint
        row = connection.execute(
            ENABLE_ENDPOINT_SQL,
            (actor_id, activated_at, project_id, endpoint["id"]),
        ).fetchone()
        if row is None:
            raise BrowserCaptureError(
                "LokiProxy pool cannot be enabled because its exact Secret version is not active"
            )
        connection.execute(
            """UPDATE browser_egress_endpoints
                  SET status = 'disabled', disabled_at = %s,
                      health_status = 'disabled', cooldown_until = NULL
                WHERE project_id = %s AND provider = 'lokiproxy'
                  AND id <> %s AND status = 'approved'""",
            (activated_at, project_id, endpoint["id"]),
        )
    return dict(row)


def reactivate_expired_cooldown(
    connection: Any, *, project_id: UUID, endpoint_id: UUID, now: datetime,
) -> None:
    connection.execute(
        """UPDATE browser_egress_endpoints
              SET health_status = 'degraded', cooldown_until = NULL
            WHERE project_id = %s AND id = %s
              AND provider = 'lokiproxy' AND status = 'approved'
              AND health_status = 'cooldown' AND cooldown_until <= %s""",
        (project_id, endpoint_id, now),
    )


def select_pool_candidates(
    endpoints: list[Mapping[str, object]],
) -> tuple[list[Mapping[str, object]], list[Mapping[str, object]]]:
    approved = [
        item for item in endpoints
        if item["status"] == "approved" and item.get("provider") == "lokiproxy"
        and item["network_type"] in {"residential", "mobile"}
    ]
    ready = [
        item for item in approved
        if item.get("health_status") == "healthy" and item.get("cooldown_until") is None
    ]
    return approved, ready


def validate_lokiproxy_lease(
    endpoint: Mapping[str, object], credential: Mapping[str, object],
    sticky_mode: str, protocol: str, ttl: int,
) -> None:
    if endpoint.get("provider", "manual") != "lokiproxy":
        return
    product = endpoint.get("pool_product")
    if (
        credential.get("provider") != "lokiproxy"
        or credential.get("pool_product") != product
        or sticky_mode != "credential_session"
        or product not in {"rotating_residential", "mobile"}
    ):
        raise BrowserCaptureError("LokiProxy pool Secret does not match its frozen profile")
    if ttl != _bounded_int(endpoint.get("session_ttl_seconds"), maximum=10_800):
        raise BrowserCaptureError("LokiProxy sticky duration differs from the pool profile")
    if protocol not in {"http", "https"}:
        raise BrowserCaptureError("LokiProxy Browser Capture requires HTTP or HTTPS proxying")


def require_healthy_pool(endpoint: dict[str, object]) -> dict[str, object]:
    if (
        endpoint.get("provider") != "lokiproxy"
        or endpoint.get("health_status") != "healthy"
        or endpoint.get("cooldown_until") is not None
    ):
        raise BrowserCaptureError("LokiProxy pool is not healthy for Browser Capture")
    return endpoint


def _bounded_int(value: object, *, maximum: int) -> int:
    if isinstance(value, bool):
        raise BrowserCaptureError("Browser numeric setting is invalid")
    try:
        result = int(str(value))
    except (TypeError, ValueError):
        raise BrowserCaptureError("Browser numeric setting is invalid") from None
    if not 1 <= result <= maximum:
        raise BrowserCaptureError("Browser numeric setting is outside its supported range")
    return result


__all__ = [
    "CREATE_ENDPOINT_SQL", "ENABLE_ENDPOINT_SQL", "SET_ENDPOINT_STATUS_SQL",
    "install_pool_profile", "reactivate_expired_cooldown", "require_healthy_pool",
    "select_pool_candidates", "validate_lokiproxy_lease",
]
