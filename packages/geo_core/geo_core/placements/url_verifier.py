"""Bounded HTTPS verification with DNS pinning and redirect-safe SSRF controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from html import unescape
from html.parser import HTMLParser
import http.client
import ipaddress
import re
import socket
import ssl
from typing import Callable, Mapping, Protocol
from urllib.parse import urljoin, urlparse


class RetryableVerificationError(RuntimeError):
    """A network, throttling, or upstream availability failure."""


class PermanentVerificationError(RuntimeError):
    """A URL or connection violates the public publication policy."""


@dataclass(frozen=True)
class UrlVerificationResult:
    success: bool
    status_code: int
    final_url: str
    checked_at: datetime
    metadata_hash: str
    accessibility: bool
    content_match: bool
    disclosure_match: bool
    link_match: bool


@dataclass(frozen=True)
class FetchedResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class HttpsFetcher(Protocol):
    def fetch(
        self,
        url: str,
        *,
        pinned_ip: str,
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> FetchedResponse: ...


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, pinned_ip: str, *, timeout: float) -> None:
        self._ssl_context = ssl.create_default_context()
        super().__init__(hostname, 443, timeout=timeout, context=self._ssl_context)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        raw = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        try:
            secured = self._ssl_context.wrap_socket(raw, server_hostname=self.host)
            peer_ip = ipaddress.ip_address(secured.getpeername()[0])
            if peer_ip != ipaddress.ip_address(self._pinned_ip) or not peer_ip.is_global:
                raise PermanentVerificationError(
                    "verification connection peer does not match the pinned public address"
                )
            self.sock = secured
        except BaseException:
            raw.close()
            raise


class PinnedHttpsFetcher:
    def fetch(
        self,
        url: str,
        *,
        pinned_ip: str,
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> FetchedResponse:
        parsed = urlparse(url)
        if parsed.hostname is None:
            raise PermanentVerificationError("verification URL has no hostname")
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        connection = _PinnedHTTPSConnection(parsed.hostname, pinned_ip, timeout=timeout_seconds)
        try:
            connection.request(
                "GET",
                target,
                headers={"Host": parsed.hostname, "User-Agent": "GEO-Verification/1.0"},
            )
            response = connection.getresponse()
            body = response.read(maximum_bytes + 1)
            if len(body) > maximum_bytes:
                raise PermanentVerificationError("verification response exceeds the size limit")
            return FetchedResponse(
                int(response.status),
                {key.casefold(): value for key, value in response.getheaders()},
                body,
            )
        finally:
            connection.close()


class PublicUrlVerifier:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        maximum_bytes: int = 1_000_000,
        maximum_redirects: int = 5,
        resolver: Callable[[str, int], tuple[str, ...]] | None = None,
        fetcher: HttpsFetcher | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._maximum_bytes = maximum_bytes
        self._maximum_redirects = maximum_redirects
        self._resolver = resolver or _resolve_addresses
        self._fetcher = fetcher or PinnedHttpsFetcher()

    def verify(
        self,
        url: str,
        *,
        expected_text_fragments: tuple[str, ...],
        required_disclosures: tuple[str, ...],
        expected_links: tuple[str, ...],
        allowed_hosts: tuple[str, ...],
    ) -> UrlVerificationResult:
        current_url = url
        try:
            for redirect_count in range(self._maximum_redirects + 1):
                addresses = self._validate_and_resolve(current_url, allowed_hosts=allowed_hosts)
                response = self._fetcher.fetch(
                    current_url,
                    pinned_ip=addresses[0],
                    timeout_seconds=self._timeout_seconds,
                    maximum_bytes=self._maximum_bytes,
                )
                status = response.status_code
                if status == 429 or 500 <= status < 600:
                    raise RetryableVerificationError(
                        f"publication URL returned retryable HTTP {status}"
                    )
                if status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise PermanentVerificationError(
                            "verification redirect has no Location header"
                        )
                    if redirect_count >= self._maximum_redirects:
                        raise PermanentVerificationError("verification redirect limit exceeded")
                    current_url = urljoin(current_url, location)
                    continue
                return self._inspect(
                    response,
                    final_url=current_url,
                    expected_text_fragments=expected_text_fragments,
                    required_disclosures=required_disclosures,
                    expected_links=expected_links,
                )
        except PermanentVerificationError:
            raise
        except ssl.SSLCertVerificationError as exc:
            raise PermanentVerificationError("verification URL certificate is not trusted") from exc
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise RetryableVerificationError("publication URL could not be reached") from exc
        raise PermanentVerificationError("verification redirect limit exceeded")

    def _validate_and_resolve(self, url: str, *, allowed_hosts: tuple[str, ...]) -> tuple[str, ...]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise PermanentVerificationError("verification URL must be an absolute HTTPS URL")
        if parsed.username or parsed.password:
            raise PermanentVerificationError("verification URL must not contain user information")
        if parsed.hostname.casefold() == "localhost":
            raise PermanentVerificationError("verification URL must not target localhost")
        normalized_allowed = {value.casefold() for value in allowed_hosts}
        if not normalized_allowed or parsed.hostname.casefold() not in normalized_allowed:
            raise PermanentVerificationError(
                "verification URL host is not allowed for this destination"
            )
        try:
            port = parsed.port
        except ValueError as exc:
            raise PermanentVerificationError("verification URL has an invalid port") from exc
        if port is not None and port != 443:
            raise PermanentVerificationError("verification URL uses a non-standard port")
        try:
            addresses = self._resolver(parsed.hostname, 443)
        except socket.gaierror as exc:
            raise RetryableVerificationError("verification hostname could not be resolved") from exc
        if not addresses:
            raise RetryableVerificationError("verification hostname did not resolve to an address")
        for address in addresses:
            try:
                parsed_address = ipaddress.ip_address(address)
            except ValueError as exc:
                raise PermanentVerificationError(
                    "verification hostname resolved to an invalid address"
                ) from exc
            if not parsed_address.is_global:
                raise PermanentVerificationError(
                    "verification URL resolves to a non-public network"
                )
        return tuple(dict.fromkeys(addresses))

    def _inspect(
        self,
        response: FetchedResponse,
        *,
        final_url: str,
        expected_text_fragments: tuple[str, ...],
        required_disclosures: tuple[str, ...],
        expected_links: tuple[str, ...],
    ) -> UrlVerificationResult:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
        if content_type not in {"text/html", "text/plain", "application/json"}:
            return self._result(
                response.status_code, final_url, False, False, False, False, response.body
            )
        charset = "utf-8"
        match = re.search(
            r"charset\s*=\s*['\"]?([^;'\"\s]+)",
            response.headers.get("content-type", ""),
            re.IGNORECASE,
        )
        if match:
            charset = match.group(1)
        text = response.body.decode(charset, errors="replace")
        extractor = _TextExtractor()
        if content_type == "text/html":
            extractor.feed(text)
            visible = " ".join(extractor.parts)
        else:
            visible = text
        normalized = _normalize(visible)
        content_match = bool(expected_text_fragments) and all(
            _normalize(value) in normalized for value in expected_text_fragments
        )
        disclosure_match = all(_normalize(value) in normalized for value in required_disclosures)
        page_links = {urljoin(final_url, link).rstrip("/") for link in extractor.links}
        link_match = all(link.rstrip("/") in page_links for link in expected_links)
        accessible = 200 <= response.status_code < 300
        return self._result(
            response.status_code,
            final_url,
            accessible,
            content_match,
            disclosure_match,
            link_match,
            response.body,
        )

    @staticmethod
    def _result(
        status: int,
        final_url: str,
        accessibility: bool,
        content_match: bool,
        disclosure_match: bool,
        link_match: bool,
        body: bytes,
    ) -> UrlVerificationResult:
        body_hash = hashlib.sha256(body).hexdigest()
        metadata = (
            f"{status}\0{final_url}\0{body_hash}\0{accessibility}\0{content_match}"
            f"\0{disclosure_match}\0{link_match}"
        )
        return UrlVerificationResult(
            success=accessibility and content_match and disclosure_match and link_match,
            status_code=status,
            final_url=final_url,
            checked_at=datetime.now(UTC),
            metadata_hash=hashlib.sha256(metadata.encode()).hexdigest(),
            accessibility=accessibility,
            content_match=content_match,
            disclosure_match=disclosure_match,
            link_match=link_match,
        )


def _resolve_addresses(hostname: str, port: int) -> tuple[str, ...]:
    records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return tuple(str(record[4][0]) for record in records)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip().casefold()
