"""Validated, non-secret scope identities for the Google connectors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from geo_core.connectors.contracts import ConnectorKind


class ConnectorScopeError(ValueError):
    """A Connector Scope is missing or names an invalid Google resource."""


_DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$", re.IGNORECASE)
_GA4_PROPERTY = re.compile(r"^properties/([0-9]+)$")
_SECRET_PURPOSES = {
    ConnectorKind.GOOGLE_SEARCH_CONSOLE: "connector.gsc",
    ConnectorKind.GOOGLE_ANALYTICS_4: "connector.ga4",
}


def connector_secret_purpose(kind: ConnectorKind) -> str:
    """Return the Secret Store purpose fixed by the Connector kind."""

    try:
        return _SECRET_PURPOSES[ConnectorKind(kind)]
    except (KeyError, ValueError) as error:
        raise ConnectorScopeError("Connector kind has no Secret purpose") from error


@dataclass(frozen=True)
class GoogleScopeIdentity:
    """The only source identity that may be used by a Google Connector run."""

    kind: ConnectorKind
    source_locator: str
    site_url: str | None = None
    property_id: str | None = None
    account_id: str | None = None

    def as_dict(self) -> dict[str, str]:
        value = {"source_locator": self.source_locator, "kind": self.kind.value}
        if self.site_url is not None:
            value["site_url"] = self.site_url
        if self.property_id is not None:
            value["property_id"] = self.property_id
        if self.account_id is not None:
            value["account_id"] = self.account_id
        return value


def validate_google_scope(
    *,
    kind: ConnectorKind,
    source_locator: str,
    streams: Sequence[str],
    report_spec: Mapping[str, object],
    date_policy: Mapping[str, object],
) -> GoogleScopeIdentity:
    """Validate the resource identity before it is persisted or sent to Airbyte.

    The database keeps the existing neutral ``source_locator`` column.  This
    function gives it a closed-world meaning for GSC and GA4 while keeping
    account/property/site identifiers out of plans, logs, and secret payloads.
    """

    try:
        connector_kind = ConnectorKind(kind)
    except ValueError as error:
        raise ConnectorScopeError("unsupported Google Connector kind") from error
    locator = source_locator.strip()
    if not locator:
        raise ConnectorScopeError("source_locator is required")
    if not streams or any(not isinstance(stream, str) or not stream.strip() for stream in streams):
        raise ConnectorScopeError("at least one non-empty stream is required")
    if not isinstance(report_spec, Mapping) or not isinstance(date_policy, Mapping):
        raise ConnectorScopeError("report_spec and date_policy must be objects")

    if connector_kind is ConnectorKind.GOOGLE_SEARCH_CONSOLE:
        identity = _gsc_identity(locator, report_spec)
        allowed = {"search_analytics_by_date", "search_analytics_by_page"}
        if set(streams) - allowed:
            raise ConnectorScopeError("GSC Scope contains an unsupported stream")
        return identity

    if connector_kind is ConnectorKind.GOOGLE_ANALYTICS_4:
        identity = _ga4_identity(locator, report_spec)
        if tuple(streams) != ("reports",):
            raise ConnectorScopeError("GA4 Scope must contain only the reports stream")
        _report_list(report_spec, "dimensions")
        _report_list(report_spec, "metrics")
        return identity

    raise ConnectorScopeError("Google Scope validation supports only GSC and GA4")


def scoped_runtime_config(
    *,
    kind: ConnectorKind,
    credential: Mapping[str, object],
    source_locator: str,
    streams: Sequence[str],
    report_spec: Mapping[str, object],
    date_policy: Mapping[str, object],
) -> dict[str, object]:
    """Add only the validated non-secret scope to a PyAirbyte config."""

    if not isinstance(credential, Mapping) or not credential:
        raise ConnectorScopeError("Connector Secret must be a non-empty object")
    identity = validate_google_scope(
        kind=kind,
        source_locator=source_locator,
        streams=streams,
        report_spec=report_spec,
        date_policy=date_policy,
    )
    config = dict(credential)
    auth_key = (
        "authorization"
        if identity.kind is ConnectorKind.GOOGLE_SEARCH_CONSOLE
        else "credentials"
    )
    if not isinstance(config.get(auth_key), Mapping):
        raise ConnectorScopeError(
            f"Connector Secret must contain a JSON object under {auth_key!r}"
        )
    if identity.kind is ConnectorKind.GOOGLE_SEARCH_CONSOLE:
        # The pinned source accepts site_urls as the explicit property filter.
        config["site_urls"] = [identity.source_locator]
        _copy_date(config, date_policy, "start_date", "end_date")
        custom_reports = report_spec.get("custom_reports_array")
        if custom_reports is not None:
            if not isinstance(custom_reports, list):
                raise ConnectorScopeError("GSC report_spec.custom_reports_array must be a list")
            config["custom_reports_array"] = custom_reports
    elif identity.property_id is not None:
        dimensions = _report_list(report_spec, "dimensions")
        metrics = _report_list(report_spec, "metrics")
        # The GA4 connector calls this field property_ids and exposes custom
        # reports as named streams.  ``reports`` is our stable stream name.
        config["property_ids"] = [identity.property_id]
        config["custom_reports_array"] = [{
            "name": "reports",
            "dimensions": dimensions,
            "metrics": metrics,
        }]
        _copy_date(config, date_policy, "date_ranges_start_date", "date_ranges_end_date")
    return config


def _gsc_identity(locator: str, report_spec: Mapping[str, object]) -> GoogleScopeIdentity:
    if locator.startswith("sc-domain:"):
        domain = locator.removeprefix("sc-domain:").lower()
        if not _DOMAIN.fullmatch(domain) or "." not in domain:
            raise ConnectorScopeError(
                "GSC source_locator must be sc-domain:<registered-domain>"
            )
        normalized = f"sc-domain:{domain}"
    elif locator.startswith("https://"):
        from urllib.parse import urlparse

        parsed = urlparse(locator)
        if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConnectorScopeError(
                "GSC site URL must be an https URL without credentials, query, or fragment"
            )
        normalized = locator.rstrip("/") + "/"
    else:
        raise ConnectorScopeError(
            "GSC source_locator must be sc-domain:<domain> or an https site URL"
        )
    declared = report_spec.get("site_url")
    if declared is not None and str(declared).strip() != normalized:
        raise ConnectorScopeError("GSC report_spec.site_url does not match source_locator")
    account_id = _optional_numeric(report_spec, "account_id")
    return GoogleScopeIdentity(
        kind=ConnectorKind.GOOGLE_SEARCH_CONSOLE,
        source_locator=normalized,
        site_url=normalized,
        account_id=account_id,
    )


def _ga4_identity(locator: str, report_spec: Mapping[str, object]) -> GoogleScopeIdentity:
    match = _GA4_PROPERTY.fullmatch(locator)
    if match is None:
        raise ConnectorScopeError("GA4 source_locator must be properties/<numeric-property-id>")
    property_id = match.group(1)
    declared = report_spec.get("property_id")
    if declared is not None and str(declared).strip() != property_id:
        raise ConnectorScopeError("GA4 report_spec.property_id does not match source_locator")
    return GoogleScopeIdentity(
        kind=ConnectorKind.GOOGLE_ANALYTICS_4,
        source_locator=f"properties/{property_id}",
        property_id=property_id,
        account_id=_optional_numeric(report_spec, "account_id"),
    )


def _optional_numeric(report_spec: Mapping[str, object], key: str) -> str | None:
    value = report_spec.get(key)
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized.isdigit():
        raise ConnectorScopeError(f"report_spec.{key} must be numeric when provided")
    return normalized


def _report_list(report_spec: Mapping[str, object], key: str) -> list[str]:
    value: Any = report_spec.get(key)
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ConnectorScopeError(f"GA4 report_spec.{key} must be a non-empty string list")
    return value


def _copy_date(
    config: dict[str, object], date_policy: Mapping[str, object], *keys: str
) -> None:
    for key in keys:
        value = date_policy.get(key.removeprefix("date_ranges_"))
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ConnectorScopeError(f"date_policy.{key} must be a non-empty string")
            config[key] = value.strip()


__all__ = [
    "ConnectorScopeError",
    "GoogleScopeIdentity",
    "connector_secret_purpose",
    "scoped_runtime_config",
    "validate_google_scope",
]
