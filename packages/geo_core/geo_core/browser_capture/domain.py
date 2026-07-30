"""Pure Browser Capture contracts and AU egress eligibility rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import hashlib
import ipaddress
from urllib.parse import urlsplit
from uuid import UUID

from geo_core.connectors.contracts import canonical_hash


class BrowserCaptureError(RuntimeError):
    """Browser evidence is incomplete, unsafe, or outside its frozen release."""


class NetworkType(StrEnum):
    RESIDENTIAL = "residential"
    MOBILE = "mobile"
    DATACENTER = "datacenter"
    UNKNOWN = "unknown"


class EgressOutcome(StrEnum):
    AU_CONSUMER_REPRESENTATIVE = "au_consumer_representative"
    AU_GEO_VERIFIED = "au_geo_verified"
    GEO_MISMATCH = "geo_mismatch"
    GEO_UNVERIFIED = "geo_unverified"
    EGRESS_CHANGED = "egress_changed"


@dataclass(frozen=True)
class EgressObservation:
    source: str
    observed_ip: str = field(repr=False)
    country: str
    region: str | None
    asn: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.asn.strip():
            raise BrowserCaptureError("Egress source and ASN are required")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise BrowserCaptureError("Egress observation time must be timezone-aware")
        try:
            address = ipaddress.ip_address(self.observed_ip)
        except ValueError as error:
            raise BrowserCaptureError("Egress observation IP is invalid") from error
        if not address.is_global:
            raise BrowserCaptureError("Egress observation IP must be public")
        object.__setattr__(self, "source", self.source.strip())
        object.__setattr__(self, "country", self.country.strip().upper())
        object.__setattr__(self, "region", self.region.strip() if self.region else None)
        object.__setattr__(self, "asn", self.asn.strip().upper())

    @property
    def ip_hash(self) -> str:
        return hashlib.sha256(self.observed_ip.encode()).hexdigest()

    def safe_value(self) -> dict[str, object]:
        return {
            "source": self.source,
            "observed_ip_hash": self.ip_hash,
            "country": self.country,
            "region": self.region,
            "asn": self.asn,
            "observed_at": self.observed_at.isoformat(),
        }


@dataclass(frozen=True)
class EgressVerification:
    id: UUID
    sticky_lease_hash: str
    pre: tuple[EgressObservation, ...]
    post: tuple[EgressObservation, ...]
    network_type: NetworkType
    expected_region: str | None
    connection_log_reference: str | None
    connection_log_hash: str | None
    outcome: EgressOutcome
    verification_hash: str

    @property
    def eligible(self) -> bool:
        return self.outcome is EgressOutcome.AU_CONSUMER_REPRESENTATIVE


def evaluate_egress(
    *,
    verification_id: UUID,
    sticky_lease_hash: str,
    pre: tuple[EgressObservation, ...],
    post: tuple[EgressObservation, ...],
    network_type: NetworkType,
    expected_region: str | None = None,
    connection_log_reference: str | None = None,
    connection_log_hash: str | None = None,
) -> EgressVerification:
    if len(sticky_lease_hash) != 64:
        raise BrowserCaptureError("Sticky lease hash must be SHA-256")
    if (connection_log_reference is None) != (connection_log_hash is None):
        raise BrowserCaptureError("Connection log reference and hash must be paired")
    if connection_log_hash is not None and len(connection_log_hash) != 64:
        raise BrowserCaptureError("Connection log hash must be SHA-256")
    pre_state = _consensus(pre)
    post_state = _consensus(post)
    if pre_state is None or post_state is None:
        outcome = EgressOutcome.GEO_UNVERIFIED
    elif pre_state[:2] != post_state[:2]:
        outcome = EgressOutcome.EGRESS_CHANGED
    elif pre_state[2] != "AU" or post_state[2] != "AU":
        outcome = EgressOutcome.GEO_MISMATCH
    elif expected_region and (
        pre_state[3] is None
        or post_state[3] is None
        or pre_state[3].casefold() != expected_region.casefold()
        or post_state[3].casefold() != expected_region.casefold()
    ):
        outcome = EgressOutcome.GEO_MISMATCH
    elif network_type in {NetworkType.RESIDENTIAL, NetworkType.MOBILE}:
        outcome = EgressOutcome.AU_CONSUMER_REPRESENTATIVE
    else:
        outcome = EgressOutcome.AU_GEO_VERIFIED
    value = {
        "id": str(verification_id),
        "sticky_lease_hash": sticky_lease_hash,
        "pre": [item.safe_value() for item in pre],
        "post": [item.safe_value() for item in post],
        "network_type": network_type.value,
        "expected_region": expected_region,
        "connection_log_reference": connection_log_reference,
        "connection_log_hash": connection_log_hash,
        "outcome": outcome.value,
    }
    return EgressVerification(
        id=verification_id,
        sticky_lease_hash=sticky_lease_hash,
        pre=pre,
        post=post,
        network_type=network_type,
        expected_region=expected_region,
        connection_log_reference=connection_log_reference,
        connection_log_hash=connection_log_hash,
        outcome=outcome,
        verification_hash=canonical_hash(value),
    )


def allowed_final_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    allowed = {item.casefold() for item in allowed_hosts}
    if parsed.scheme != "https" or host not in allowed or parsed.username or parsed.password:
        raise BrowserCaptureError("Browser final URL is outside the Surface Release allowlist")
    return url


def _consensus(
    observations: tuple[EgressObservation, ...],
) -> tuple[str, str, str, str | None] | None:
    if len(observations) < 2 or len({item.source for item in observations}) < 2:
        return None
    states = {
        (item.ip_hash, item.asn, item.country, item.region)
        for item in observations
    }
    return next(iter(states)) if len(states) == 1 else None


__all__ = [
    "BrowserCaptureError",
    "EgressObservation",
    "EgressOutcome",
    "EgressVerification",
    "NetworkType",
    "allowed_final_url",
    "evaluate_egress",
]
