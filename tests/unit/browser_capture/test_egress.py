from datetime import UTC, datetime, timedelta
import hashlib
from uuid import uuid4

import pytest

from geo_core.browser_capture.domain import (
    BrowserCaptureError,
    EgressObservation,
    EgressOutcome,
    NetworkType,
    evaluate_egress,
)


NOW = datetime(2026, 7, 28, 6, 0, tzinfo=UTC)
LEASE_HASH = hashlib.sha256(b"sticky-lease-1").hexdigest()


def _observations(ip: str, country: str = "AU", asn: str = "AS13335"):
    return tuple(
        EgressObservation(source=source, observed_ip=ip, country=country,
                          region="NSW", asn=asn, observed_at=NOW + offset)
        for source, offset in (("geo-a", timedelta()), ("geo-b", timedelta(seconds=1)))
    )


def test_two_source_sticky_au_residential_is_consumer_representative() -> None:
    result = evaluate_egress(
        verification_id=uuid4(), sticky_lease_hash=LEASE_HASH,
        pre=_observations("1.1.1.1"), post=_observations("1.1.1.1"),
        network_type=NetworkType.RESIDENTIAL, expected_region="NSW",
    )
    assert result.outcome is EgressOutcome.AU_CONSUMER_REPRESENTATIVE
    assert result.eligible is True
    assert "1.1.1.1" not in repr(result) and len(result.verification_hash) == 64


def test_datacenter_is_geo_verified_but_ineligible() -> None:
    result = evaluate_egress(
        verification_id=uuid4(), sticky_lease_hash=LEASE_HASH,
        pre=_observations("1.1.1.1"), post=_observations("1.1.1.1"),
        network_type=NetworkType.DATACENTER,
    )
    assert result.outcome is EgressOutcome.AU_GEO_VERIFIED
    assert result.eligible is False


@pytest.mark.parametrize(
    ("pre", "post", "outcome"),
    [
        (_observations("1.1.1.1", "US"), _observations("1.1.1.1", "US"), EgressOutcome.GEO_MISMATCH),
        (_observations("1.1.1.1"), _observations("8.8.8.8", asn="AS15169"), EgressOutcome.EGRESS_CHANGED),
        (
            (_observations("1.1.1.1")[0], _observations("8.8.8.8")[1]),
            _observations("1.1.1.1"),
            EgressOutcome.GEO_UNVERIFIED,
        ),
    ],
)
def test_ineligible_egress_outcomes(pre, post, outcome) -> None:
    result = evaluate_egress(
        verification_id=uuid4(), sticky_lease_hash=LEASE_HASH,
        pre=pre, post=post, network_type=NetworkType.RESIDENTIAL,
    )
    assert result.outcome is outcome and result.eligible is False


def test_private_ip_and_single_source_are_not_accepted_as_proof() -> None:
    with pytest.raises(BrowserCaptureError, match="public"):
        EgressObservation(
            source="geo-a", observed_ip="127.0.0.1", country="AU", region=None,
            asn="AS0", observed_at=NOW,
        )
    one = (_observations("1.1.1.1")[0],)
    result = evaluate_egress(
        verification_id=uuid4(), sticky_lease_hash=LEASE_HASH,
        pre=one, post=one, network_type=NetworkType.RESIDENTIAL,
    )
    assert result.outcome is EgressOutcome.GEO_UNVERIFIED
