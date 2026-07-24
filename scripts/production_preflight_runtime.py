"""Image, URL, release, capacity, and runtime-threshold preflight checks."""

from __future__ import annotations

import re
from uuid import UUID

from scripts.production_preflight_common import valid_https_url
from scripts.production_preflight_contracts import (
    HTTPS_URL_FIELDS,
    IMAGE_FIELDS,
    INTEGER_BOUNDS,
    PreflightIssue,
    REQUIRED_TEXT_FIELDS,
)


_IMAGE_DIGEST = re.compile(r"^[^\s@]+@sha256:[0-9a-fA-F]{64}$")
_RELEASE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MEMORY_SIZE = re.compile(r"^[1-9][0-9]{0,5}[mg]$")
_RELEASE_PLACEHOLDERS = {"development", "latest", "replace", "unknown"}
_SECRET_PURPOSE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,256}$")


def required_value(
    values: dict[str, str], field: str, issues: list[PreflightIssue]
) -> str | None:
    if field not in values:
        issues.append(PreflightIssue("CONFIG_REQUIRED", field))
        return None
    value = values[field].strip()
    if not value:
        issues.append(PreflightIssue("CONFIG_EMPTY", field))
        return None
    return value


def validate_runtime_values(
    values: dict[str, str], issues: list[PreflightIssue]
) -> None:
    for field in IMAGE_FIELDS:
        value = required_value(values, field, issues)
        if value is not None and (
            not _IMAGE_DIGEST.fullmatch(value) or "replace" in value.casefold()
        ):
            issues.append(PreflightIssue("IMAGE_NOT_DIGEST_PINNED", field))

    for field in HTTPS_URL_FIELDS:
        value = required_value(values, field, issues)
        if value is not None and not valid_https_url(value):
            issues.append(PreflightIssue("URL_NOT_HTTPS", field))

    for field in REQUIRED_TEXT_FIELDS:
        required_value(values, field, issues)

    service_identity = values.get(
        "GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID", ""
    ).strip()
    if service_identity:
        try:
            if UUID(service_identity).int == 0:
                raise ValueError
        except ValueError:
            issues.append(
                PreflightIssue(
                    "SERVICE_IDENTITY_UUID_INVALID",
                    "GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID",
                )
            )

    for field in (
        "GEO_RESTORE_PROBE_SERVICE_IDENTITY_ID",
        "GEO_RESTORE_SECRET_REFERENCE_ID",
        "GEO_RESTORE_SECRET_PROJECT_ID",
    ):
        value = values.get(field, "").strip()
        if not value:
            continue
        try:
            if UUID(value).int == 0:
                raise ValueError
        except ValueError:
            issues.append(PreflightIssue("RESTORE_CANARY_UUID_INVALID", field))

    purpose = values.get("GEO_RESTORE_SECRET_PURPOSE", "").strip()
    if purpose and _SECRET_PURPOSE.fullmatch(purpose) is None:
        issues.append(PreflightIssue("SECRET_PURPOSE_INVALID", "GEO_RESTORE_SECRET_PURPOSE"))
    idempotency_key = values.get("GEO_RESTORE_SECRET_IDEMPOTENCY_KEY", "").strip()
    if idempotency_key and _IDEMPOTENCY_KEY.fullmatch(idempotency_key) is None:
        issues.append(
            PreflightIssue(
                "IDEMPOTENCY_KEY_INVALID", "GEO_RESTORE_SECRET_IDEMPOTENCY_KEY"
            )
        )

    origins = values.get("GEO_ADMIN_OIDC_ALLOWED_ORIGINS", "").strip()
    if origins:
        origin_values = [origin.strip() for origin in origins.split(",")]
        if any(
            not origin or not valid_https_url(origin, origin_only=True)
            for origin in origin_values
        ):
            issues.append(
                PreflightIssue("ORIGIN_NOT_HTTPS", "GEO_ADMIN_OIDC_ALLOWED_ORIGINS")
            )

    release_version = values.get("GEO_RELEASE_VERSION", "").strip()
    if release_version and (
        not _RELEASE_VERSION.fullmatch(release_version)
        or release_version.casefold() in _RELEASE_PLACEHOLDERS
        or "replace" in release_version.casefold()
    ):
        issues.append(PreflightIssue("RELEASE_VERSION_INVALID", "GEO_RELEASE_VERSION"))

    staging_size = values.get("GEO_BACKUP_MINIO_STAGING_SIZE", "").strip()
    if staging_size and _MEMORY_SIZE.fullmatch(staging_size.casefold()) is None:
        issues.append(
            PreflightIssue("MEMORY_SIZE_INVALID", "GEO_BACKUP_MINIO_STAGING_SIZE")
        )

    parsed_integers: dict[str, int] = {}
    for field, (minimum, maximum) in INTEGER_BOUNDS.items():
        value = required_value(values, field, issues)
        if value is None:
            continue
        try:
            parsed = int(value)
        except ValueError:
            issues.append(PreflightIssue("THRESHOLD_NOT_INTEGER", field))
            continue
        parsed_integers[field] = parsed
        if not minimum <= parsed <= maximum:
            issues.append(PreflightIssue("THRESHOLD_OUT_OF_RANGE", field))

    _validate_threshold_relationships(parsed_integers, issues)


def _validate_threshold_relationships(
    parsed: dict[str, int], issues: list[PreflightIssue]
) -> None:
    dependency_timeout = parsed.get("GEO_READINESS_DEPENDENCY_TIMEOUT_SECONDS")
    total_timeout = parsed.get("GEO_READINESS_TOTAL_TIMEOUT_SECONDS")
    if (
        dependency_timeout is not None
        and total_timeout is not None
        and total_timeout <= dependency_timeout
    ):
        issues.append(
            PreflightIssue(
                "READINESS_TOTAL_NOT_GREATER",
                "GEO_READINESS_TOTAL_TIMEOUT_SECONDS",
            )
        )

    heartbeat_interval = parsed.get("GEO_RUNTIME_HEARTBEAT_INTERVAL_SECONDS")
    heartbeat_stale = parsed.get("GEO_RUNTIME_HEARTBEAT_STALE_SECONDS")
    if (
        heartbeat_interval is not None
        and heartbeat_stale is not None
        and heartbeat_stale <= heartbeat_interval
    ):
        issues.append(
            PreflightIssue(
                "HEARTBEAT_STALE_NOT_GREATER",
                "GEO_RUNTIME_HEARTBEAT_STALE_SECONDS",
            )
        )


__all__ = ["required_value", "validate_runtime_values"]
