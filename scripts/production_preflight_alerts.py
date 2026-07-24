"""Production alert transport validation without resolving DNS or secrets."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from scripts.production_preflight_contracts import PreflightIssue


_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_EMAIL = re.compile(r"^[^\s@<>]+@[^\s@<>]+$")


def validate_alert_runtime(values: dict[str, str], issues: list[PreflightIssue]) -> None:
    smtp_host = values.get("GEO_ALERT_SMTP_UPSTREAM_HOST", "").strip().lower()
    smtp_allowed = _hosts(values.get("GEO_ALERT_SMTP_UPSTREAM_ALLOWED_HOSTS", ""))
    if smtp_host and (not _valid_host(smtp_host) or smtp_host not in smtp_allowed):
        issues.append(
            PreflightIssue("ALERT_SMTP_HOST_NOT_ALLOWED", "GEO_ALERT_SMTP_UPSTREAM_HOST")
        )
    if not smtp_allowed or any(not _valid_host(item) for item in smtp_allowed):
        issues.append(
            PreflightIssue(
                "ALERT_SMTP_ALLOWLIST_INVALID",
                "GEO_ALERT_SMTP_UPSTREAM_ALLOWED_HOSTS",
            )
        )
    if values.get("GEO_ALERT_SMTP_TLS_MODE", "").strip().lower() not in {
        "starttls",
        "tls",
    }:
        issues.append(PreflightIssue("ALERT_SMTP_TLS_INVALID", "GEO_ALERT_SMTP_TLS_MODE"))
    _validate_addresses(values, "GEO_ALERT_SMTP_SENDER", single=True, issues=issues)
    _validate_addresses(values, "GEO_ALERT_SMTP_RECIPIENTS", single=False, issues=issues)

    endpoint = values.get("GEO_ALERT_WEBHOOK_ENDPOINT", "").strip()
    webhook_allowed = _hosts(values.get("GEO_ALERT_WEBHOOK_ALLOWED_HOSTS", ""))
    parsed = urlsplit(endpoint)
    webhook_host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not webhook_host
        or webhook_host not in webhook_allowed
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        issues.append(
            PreflightIssue("ALERT_WEBHOOK_ENDPOINT_INVALID", "GEO_ALERT_WEBHOOK_ENDPOINT")
        )
    if not webhook_allowed or any(not _valid_host(item) for item in webhook_allowed):
        issues.append(
            PreflightIssue(
                "ALERT_WEBHOOK_ALLOWLIST_INVALID",
                "GEO_ALERT_WEBHOOK_ALLOWED_HOSTS",
            )
        )
    for field in (
        "GEO_ALERT_SMTP_USERNAME",
        "GEO_ALERT_SMTP_PASSWORD",
        "GEO_ALERT_WEBHOOK_SIGNING_SECRET",
    ):
        if values.get(field, "").strip():
            issues.append(PreflightIssue("ALERT_SECRET_DIRECT_FORBIDDEN", field))


def _hosts(value: str) -> frozenset[str]:
    return frozenset(item.strip().lower() for item in value.split(",") if item.strip())


def _valid_host(value: str) -> bool:
    if "*" in value or value in {"localhost", "host.docker.internal"}:
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return _HOST.fullmatch(value) is not None
    return False


def _validate_addresses(
    values: dict[str, str],
    field: str,
    *,
    single: bool,
    issues: list[PreflightIssue],
) -> None:
    raw = values.get(field, "")
    addresses = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if (
        not addresses
        or (single and len(addresses) != 1)
        or len(set(addresses)) != len(addresses)
        or any(len(item) > 254 or _EMAIL.fullmatch(item) is None for item in addresses)
    ):
        issues.append(PreflightIssue("ALERT_EMAIL_INVALID", field))


__all__ = ["validate_alert_runtime"]
