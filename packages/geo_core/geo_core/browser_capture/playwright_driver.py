"""Playwright capture through one frozen proxy and BrowserContext."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Mapping
from uuid import uuid4

from playwright.sync_api import BrowserContext, Page, sync_playwright

from geo_core.browser_capture.domain import (
    BrowserCaptureError,
    EgressObservation,
    EgressVerification,
    NetworkType,
    evaluate_egress,
)
from geo_core.browser_capture.parsing import Citation, PageSignals


@dataclass(frozen=True, repr=False)
class ProxyLease:
    server: str
    username: str | None
    password: str | None
    lease_id: str
    started_at: datetime
    expires_at: datetime
    network_type: NetworkType
    expected_region: str | None = None
    connection_log_reference: str | None = None
    connection_log_hash: str | None = None

    @property
    def lease_hash(self) -> str:
        return hashlib.sha256(self.lease_id.encode()).hexdigest()


@dataclass(frozen=True)
class EgressProbe:
    source: str
    url: str
    ip_field: str
    country_field: str
    region_field: str
    asn_field: str


@dataclass(frozen=True)
class BrowserProfile:
    locale: str = "en-AU"
    timezone: str = "Australia/Sydney"
    viewport_width: int = 1440
    viewport_height: int = 1000
    user_agent: str | None = None
    geolocation: Mapping[str, float] | None = None
    grant_location: bool = False


@dataclass(frozen=True)
class SurfaceSelectors:
    entry_url_template: str
    query_input: str
    page_complete: str
    surface_marker: str
    answer: str
    citations: str
    page_location: str
    block_detectors: Mapping[str, str] = field(default_factory=dict)
    ready_timeout_ms: int = 45_000


@dataclass(frozen=True)
class PlaywrightCapture:
    verification: EgressVerification
    signals: PageSignals
    screenshot: bytes = field(repr=False)
    dom: bytes = field(repr=False)
    har: bytes = field(repr=False)


class PlaywrightBrowserDriver:
    def __init__(self, *, browser_channel: str = "chromium") -> None:
        self._browser_channel = browser_channel

    def capture(
        self,
        *,
        query: str,
        expected_surface: str,
        proxy: ProxyLease,
        profile: BrowserProfile,
        selectors: SurfaceSelectors,
        probes: tuple[EgressProbe, ...],
        now: datetime | None = None,
    ) -> PlaywrightCapture:
        captured_at = now or datetime.now(UTC)
        if not query.strip() or len(probes) < 2 or len({item.source for item in probes}) < 2:
            raise BrowserCaptureError("Query and two independent Egress probes are required")
        if proxy.started_at > captured_at or proxy.expires_at <= captured_at:
            raise BrowserCaptureError("Sticky proxy lease is not active")
        with tempfile.TemporaryDirectory(prefix="geo-browser-capture-") as directory:
            har_path = Path(directory) / "capture.har"
            with sync_playwright() as playwright:
                browser_type = getattr(playwright, self._browser_channel, None)
                if browser_type is None:
                    raise BrowserCaptureError("Configured Playwright browser is unavailable")
                browser = browser_type.launch(headless=True)
                context = browser.new_context(
                    proxy={
                        "server": proxy.server,
                        **({"username": proxy.username} if proxy.username else {}),
                        **({"password": proxy.password} if proxy.password else {}),
                    },
                    locale=profile.locale,
                    timezone_id=profile.timezone,
                    viewport={"width": profile.viewport_width, "height": profile.viewport_height},
                    user_agent=profile.user_agent,
                    geolocation=dict(profile.geolocation) if profile.geolocation else None,
                    permissions=["geolocation"] if profile.grant_location else [],
                    record_har_path=har_path,
                    record_har_mode="full",
                )
                try:
                    pre = self._probe(context, probes, captured_at)
                    signals, screenshot, dom = self._target(
                        context, query, expected_surface, selectors
                    )
                    post = self._probe(context, probes, datetime.now(UTC))
                finally:
                    context.close()
                    browser.close()
            verification = evaluate_egress(
                verification_id=uuid4(),
                sticky_lease_hash=proxy.lease_hash,
                pre=pre,
                post=post,
                network_type=proxy.network_type,
                expected_region=proxy.expected_region,
                connection_log_reference=proxy.connection_log_reference,
                connection_log_hash=proxy.connection_log_hash,
            )
            har = _sanitize_har(har_path.read_bytes(), {item.url for item in probes})
            return PlaywrightCapture(
                verification=verification,
                signals=signals,
                screenshot=screenshot,
                dom=dom,
                har=har,
            )

    def verify_egress(
        self,
        *,
        proxy: ProxyLease,
        probes: tuple[EgressProbe, ...],
        now: datetime | None = None,
    ) -> EgressVerification:
        observed_at = now or datetime.now(UTC)
        if len(probes) < 2 or len({item.source for item in probes}) < 2:
            raise BrowserCaptureError("Two independent Egress probes are required")
        if proxy.started_at > observed_at or proxy.expires_at <= observed_at:
            raise BrowserCaptureError("Sticky proxy lease is not active")
        with sync_playwright() as playwright:
            browser_type = getattr(playwright, self._browser_channel, None)
            if browser_type is None:
                raise BrowserCaptureError("Configured Playwright browser is unavailable")
            browser = browser_type.launch(headless=True)
            context = browser.new_context(
                proxy={
                    "server": proxy.server,
                    **({"username": proxy.username} if proxy.username else {}),
                    **({"password": proxy.password} if proxy.password else {}),
                },
                locale="en-AU",
                timezone_id="Australia/Sydney",
            )
            try:
                pre = self._probe(context, probes, observed_at)
                post = self._probe(context, probes, datetime.now(UTC))
            finally:
                context.close()
                browser.close()
        return evaluate_egress(
            verification_id=uuid4(),
            sticky_lease_hash=proxy.lease_hash,
            pre=pre,
            post=post,
            network_type=proxy.network_type,
            expected_region=proxy.expected_region,
            connection_log_reference=proxy.connection_log_reference,
            connection_log_hash=proxy.connection_log_hash,
        )

    def _probe(
        self,
        context: BrowserContext,
        probes: tuple[EgressProbe, ...],
        observed_at: datetime,
    ) -> tuple[EgressObservation, ...]:
        observations = []
        for probe in probes:
            response = context.request.get(probe.url, timeout=15_000)
            if not response.ok:
                raise BrowserCaptureError(
                    f"Egress verification source {probe.source} returned HTTP {response.status}"
                )
            try:
                payload = response.json()
                observations.append(
                    EgressObservation(
                        source=probe.source,
                        observed_ip=str(_field(payload, probe.ip_field)),
                        country=str(_field(payload, probe.country_field)),
                        region=_optional_field(payload, probe.region_field),
                        asn=str(_field(payload, probe.asn_field)),
                        observed_at=observed_at,
                    )
                )
            except (TypeError, ValueError, KeyError) as error:
                raise BrowserCaptureError(
                    f"Egress verification source {probe.source} returned invalid evidence"
                ) from error
        return tuple(observations)

    def _target(
        self,
        context: BrowserContext,
        query: str,
        expected_surface: str,
        selectors: SurfaceSelectors,
    ) -> tuple[PageSignals, bytes, bytes]:
        page = context.new_page()
        try:
            page.goto(selectors.entry_url_template, wait_until="domcontentloaded")
            page.locator(selectors.query_input).fill(query)
            page.locator(selectors.query_input).press("Enter")
            timed_out = False
            try:
                page.locator(selectors.page_complete).wait_for(
                    state="visible", timeout=selectors.ready_timeout_ms
                )
            except Exception:
                timed_out = True
            block_reason = _first_block(page, selectors.block_detectors)
            detected = (
                expected_surface
                if page.locator(selectors.surface_marker).count() > 0
                else None
            )
            answer_locator = selectors.answer if page.locator(selectors.answer).count() > 0 else None
            answer = page.locator(selectors.answer).first.inner_text() if answer_locator else None
            citations = _citations(page, selectors.citations)
            location = (
                page.locator(selectors.page_location).first.inner_text()
                if page.locator(selectors.page_location).count() > 0
                else None
            )
            signals = PageSignals(
                final_url=page.url,
                page_complete=not timed_out,
                detected_surface=detected,
                answer_text=answer,
                answer_locator=answer_locator,
                citations=citations,
                page_country=_country_from_location(location),
                block_reason=block_reason,
                timed_out=timed_out,
            )
            return signals, page.screenshot(full_page=True), page.content().encode("utf-8")
        finally:
            page.close()


def _citations(page: Page, selector: str) -> tuple[Citation, ...]:
    values: list[Citation] = []
    for index, item in enumerate(page.locator(selector).all(), start=1):
        url = item.get_attribute("href")
        if not url or not url.startswith("https://"):
            continue
        values.append(
            Citation(
                title=(item.inner_text() or item.get_attribute("aria-label") or url).strip(),
                url=url,
                position=len(values) + 1,
                locator=f"{selector}:nth({index - 1})",
            )
        )
    return tuple(values)


def _first_block(page: Page, detectors: Mapping[str, str]) -> str | None:
    for reason, selector in detectors.items():
        if page.locator(selector).count() > 0:
            return reason
    return None


def _country_from_location(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.casefold()
    return "AU" if "australia" in normalized or normalized.strip() == "au" else None


def _field(value: object, path: str) -> object:
    current = value
    for key in path.split("."):
        if not isinstance(current, Mapping) or key not in current:
            raise KeyError(path)
        current = current[key]
    return current


def _optional_field(value: object, path: str) -> str | None:
    try:
        result = _field(value, path)
    except KeyError:
        return None
    return str(result) if result is not None else None


def _sanitize_har(payload: bytes, probe_urls: set[str]) -> bytes:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BrowserCaptureError("Playwright HAR is invalid") from error
    log = value.get("log") if isinstance(value, dict) else None
    if not isinstance(log, dict):
        raise BrowserCaptureError("Playwright HAR has no log")
    entries = log.get("entries")
    if not isinstance(entries, list):
        raise BrowserCaptureError("Playwright HAR has no entries")
    safe_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        request = entry.get("request")
        if isinstance(request, dict) and request.get("url") in probe_urls:
            continue
        for side in (entry.get("request"), entry.get("response")):
            if not isinstance(side, dict):
                continue
            headers = side.get("headers")
            if isinstance(headers, list):
                side["headers"] = [
                    header
                    for header in headers
                    if isinstance(header, dict)
                    and str(header.get("name", "")).casefold()
                    not in {"authorization", "cookie", "set-cookie", "proxy-authorization"}
                ]
            side.pop("cookies", None)
        safe_entries.append(entry)
    log["entries"] = safe_entries
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()


__all__ = [
    "BrowserProfile",
    "EgressProbe",
    "PlaywrightBrowserDriver",
    "PlaywrightCapture",
    "ProxyLease",
    "SurfaceSelectors",
]
