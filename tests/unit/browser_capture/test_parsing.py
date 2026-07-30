from datetime import UTC, datetime, timedelta
import hashlib
from uuid import uuid4

from geo_core.browser_capture.domain import EgressObservation, NetworkType, evaluate_egress
from geo_core.browser_capture.parsing import (
    CaptureOutcome,
    Citation,
    PageSignals,
    SurfaceRelease,
    parse_capture,
)


def _egress():
    now = datetime(2026, 7, 28, tzinfo=UTC)
    observations = tuple(
        EgressObservation(
            source=source, observed_ip="1.1.1.1", country="AU", region="NSW",
            asn="AS13335", observed_at=now + timedelta(seconds=index),
        )
        for index, source in enumerate(("geo-a", "geo-b"))
    )
    return evaluate_egress(
        verification_id=uuid4(),
        sticky_lease_hash=hashlib.sha256(b"lease").hexdigest(),
        pre=observations, post=observations, network_type=NetworkType.RESIDENTIAL,
    )


def _release(surface: str, host: str) -> SurfaceRelease:
    return SurfaceRelease(
        id=uuid4(), platform="google" if "google" in surface else "bing",
        surface=surface, release_hash="a" * 64, parser_release=f"{surface}-v1",
        allowed_hosts=(host,),
    )


def test_each_surface_keeps_its_own_release_identity() -> None:
    fixtures = (
        ("google_ai_overviews", "www.google.com"),
        ("google_ai_mode", "www.google.com"),
        ("bing_copilot", "www.bing.com"),
    )
    hashes = set()
    for surface, host in fixtures:
        result = parse_capture(
            release=_release(surface, host), egress=_egress(),
            signals=PageSignals(
                final_url=f"https://{host}/search?q=coffee", page_complete=True,
                detected_surface=surface, answer_text="A consumer answer",
                answer_locator="[data-answer]", page_country="AU",
                citations=(Citation("Source", "https://example.com", 1, "a[href]"),),
            ),
        )
        assert result.outcome is CaptureOutcome.CAPTURED and result.eligible
        hashes.add(result.observation_hash)
    assert len(hashes) == 3


def test_complete_normal_page_is_an_eligible_negative() -> None:
    result = parse_capture(
        release=_release("google_ai_overviews", "www.google.com"), egress=_egress(),
        signals=PageSignals(
            final_url="https://www.google.com/search?q=coffee", page_complete=True,
            detected_surface=None, answer_text=None, answer_locator=None,
            citations=(), page_country="AU",
        ),
    )
    assert result.outcome is CaptureOutcome.SURFACE_NOT_PRESENT and result.eligible


def test_captcha_and_page_geo_mismatch_are_ineligible() -> None:
    release = _release("bing_copilot", "www.bing.com")
    blocked = parse_capture(
        release=release, egress=_egress(),
        signals=PageSignals(
            final_url="https://www.bing.com/search?q=coffee", page_complete=True,
            detected_surface=None, answer_text=None, answer_locator=None,
            citations=(), page_country="AU", block_reason="captcha",
        ),
    )
    mismatch = parse_capture(
        release=release, egress=_egress(),
        signals=PageSignals(
            final_url="https://www.bing.com/search?q=coffee", page_complete=True,
            detected_surface="bing_copilot", answer_text="Answer", answer_locator="#answer",
            citations=(), page_country="US",
        ),
    )
    assert blocked.outcome is CaptureOutcome.ACCESS_BLOCKED and not blocked.eligible
    assert mismatch.outcome is CaptureOutcome.GEO_MISMATCH and not mismatch.eligible
