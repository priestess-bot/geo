"""Fail-closed lookup for non-login Worker service identities."""

from __future__ import annotations

import os
from uuid import UUID

import psycopg


MODEL_GATEWAY_WORKER_SERVICE_NAME = "model_gateway_worker"
MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ENV = (
    "GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID"
)


def require_model_gateway_worker_identity(*, database_url: str) -> UUID:
    """Return the configured actor only after database binding validation."""

    raw_identity = os.getenv(MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ENV, "").strip()
    try:
        identity_id = UUID(raw_identity)
    except (TypeError, ValueError):
        raise RuntimeError(
            f"{MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ENV} must be a UUID"
        ) from None
    if identity_id.int == 0:
        raise RuntimeError(
            f"{MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ENV} cannot be the nil UUID"
        )
    try:
        with psycopg.connect(database_url) as connection:
            row = connection.execute(
                "SELECT geo_require_active_service_identity(%s, %s)",
                (identity_id, MODEL_GATEWAY_WORKER_SERVICE_NAME),
            ).fetchone()
    except psycopg.Error as error:
        raise RuntimeError("Model Gateway Worker service identity lookup failed") from error
    if row is None or row[0] is not True:
        raise RuntimeError("Model Gateway Worker service identity is not active")
    return identity_id


__all__ = [
    "MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ENV",
    "MODEL_GATEWAY_WORKER_SERVICE_NAME",
    "require_model_gateway_worker_identity",
]
