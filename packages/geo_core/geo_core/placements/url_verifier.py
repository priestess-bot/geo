"""Bounded publication URL verification with redirect-safe SSRF controls."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from html import unescape
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import posixpath
import re
import socket
import ssl
from typing import Callable
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit

from geo_core.placements.url_verification_contracts import (
    VERIFIER_CONTRACT_VERSION,
    PermanentVerificationError,
    RetryableVerificationError,
    UrlVerificationResult,
    VerificationCheck,
    VerificationCheckName,
    VerificationError,
    VerificationFailure,
    VerificationFailureDisposition,
)
from geo_core.placements.url_verification_http import (
    FetchedResponse,
    HttpsFetcher,
    PinnedHttpsFetcher,
    _PinnedHTTPSConnection,
)

__all__ = (
    "FetchedResponse", "HttpsFetcher", "PermanentVerificationError", "PinnedHttpsFetcher",
    "PublicUrlVerifier", "RetryableVerificationError", "UrlVerificationResult",
    "VERIFIER_CONTRACT_VERSION", "VerificationCheck", "VerificationCheckName",
    "VerificationError", "VerificationFailure", "VerificationFailureDisposition",
    "_PinnedHTTPSConnection",
)


class _TextExtractor(HTMLParser):
    _NON_VISIBLE_TAGS = frozenset({"head", "script", "style", "template", "noscript"})

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[str] = []
        self.base_href: str | None = None
        self._non_visible_depth = 0

    def handle_data(self, data: str) -> None:
        if self._non_visible_depth == 0:
            self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        attributes = {key.casefold(): value for key, value in attrs}
        if normalized_tag in self._NON_VISIBLE_TAGS:
            self._non_visible_depth += 1
            return
        if self._non_visible_depth:
            return
        if normalized_tag == "base" and self.base_href is None:
            self.base_href = attributes.get("href")
        if normalized_tag == "a":
            href = attributes.get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self._NON_VISIBLE_TAGS and self._non_visible_depth:
            self._non_visible_depth -= 1


class PublicUrlVerifier:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        maximum_bytes: int = 1_000_000,
        maximum_redirects: int = 5,
        resolver: Callable[[str, int], tuple[str, ...]] | None = None,
        fetcher: HttpsFetcher | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if timeout_seconds <= 0 or maximum_bytes <= 0 or maximum_redirects < 0:
            raise ValueError("URL verifier bounds must be positive")
        self._timeout_seconds = timeout_seconds
        self._maximum_bytes = maximum_bytes
        self._maximum_redirects = maximum_redirects
        self._resolver = resolver or _resolve_addresses
        self._fetcher = fetcher or PinnedHttpsFetcher()
        self._clock = clock or _utc_now

    def verify(
        self,
        url: str,
        *,
        expected_text_fragments: tuple[str, ...],
        required_disclosures: tuple[str, ...],
        expected_links: tuple[str, ...],
        allowed_hosts: tuple[str, ...],
    ) -> UrlVerificationResult:
        fragments = _normalized_contract_values(
            expected_text_fragments,
            field="expected_text_fragments",
            required=True,
        )
        disclosures = _normalized_contract_values(
            required_disclosures,
            field="required_disclosures",
            required=False,
        )
        raw_links = _contract_values(expected_links, field="expected_links", required=False)
        normalized_links = tuple(_validated_expected_link(value) for value in raw_links)
        normalized_links = tuple(dict.fromkeys(normalized_links))
        normalized_hosts = _normalized_allowed_hosts(allowed_hosts)
        content_rule_hash = _stable_hash(list(fragments))
        verification_rule_hash = _stable_hash(
            {
                "verifier_version": VERIFIER_CONTRACT_VERSION,
                "expected_text_fragments": list(fragments),
                "required_disclosures": list(disclosures),
                "expected_links": list(normalized_links),
                "allowed_hosts": list(normalized_hosts),
            }
        )

        current_url = _without_fragment(url)
        try:
            for redirect_count in range(self._maximum_redirects + 1):
                addresses = self._validate_and_resolve(
                    current_url,
                    allowed_hosts=normalized_hosts,
                )
                response = self._fetcher.fetch(
                    current_url,
                    pinned_ip=addresses[0],
                    timeout_seconds=self._timeout_seconds,
                    maximum_bytes=self._maximum_bytes,
                )
                response = FetchedResponse(
                    status_code=response.status_code,
                    headers={key.casefold(): value for key, value in response.headers.items()},
                    body=response.body,
                )
                status = response.status_code
                if status == 429:
                    raise RetryableVerificationError(
                        "publication URL returned a throttling response",
                        code="http_throttled",
                        check=VerificationCheckName.HTTP_2XX,
                    )
                if 500 <= status < 600:
                    raise RetryableVerificationError(
                        "publication URL returned an upstream availability response",
                        code="http_upstream_unavailable",
                        check=VerificationCheckName.HTTP_2XX,
                    )
                if status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise PermanentVerificationError(
                            "verification redirect has no Location header",
                            code="redirect_location_missing",
                            check=VerificationCheckName.REDIRECT_POLICY,
                        )
                    if redirect_count >= self._maximum_redirects:
                        raise PermanentVerificationError(
                            "verification redirect limit exceeded",
                            code="redirect_limit_exceeded",
                            check=VerificationCheckName.REDIRECT_POLICY,
                        )
                    current_url = _without_fragment(urljoin(current_url, location))
                    continue
                return self._inspect(
                    response,
                    final_url=current_url,
                    fragments=fragments,
                    disclosures=disclosures,
                    expected_links=normalized_links,
                    content_rule_hash=content_rule_hash,
                    verification_rule_hash=verification_rule_hash,
                    redirect_count=redirect_count,
                )
        except (PermanentVerificationError, RetryableVerificationError):
            raise
        except ssl.SSLCertVerificationError as exc:
            raise PermanentVerificationError(
                "verification URL certificate is not trusted",
                code="tls_certificate_untrusted",
                check=VerificationCheckName.PUBLIC_URL,
            ) from exc
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise RetryableVerificationError(
                "publication URL could not be reached",
                code="network_unavailable",
                check=VerificationCheckName.PUBLIC_URL,
            ) from exc
        raise PermanentVerificationError(
            "verification redirect limit exceeded",
            code="redirect_limit_exceeded",
            check=VerificationCheckName.REDIRECT_POLICY,
        )

    def _validate_and_resolve(
        self,
        url: str,
        *,
        allowed_hosts: tuple[str, ...],
    ) -> tuple[str, ...]:
        if _contains_control_character(url):
            raise PermanentVerificationError(
                "verification URL contains an invalid character",
                code="url_invalid",
                check=VerificationCheckName.PUBLIC_URL,
            )
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise PermanentVerificationError(
                "verification URL has an invalid port",
                code="url_port_invalid",
                check=VerificationCheckName.PUBLIC_URL,
            ) from exc
        if parsed.scheme.casefold() != "https" or not parsed.hostname:
            raise PermanentVerificationError(
                "verification URL must be an absolute HTTPS URL",
                code="url_not_absolute_https",
                check=VerificationCheckName.PUBLIC_URL,
            )
        if parsed.username or parsed.password:
            raise PermanentVerificationError(
                "verification URL must not contain user information",
                code="url_userinfo_forbidden",
                check=VerificationCheckName.PUBLIC_URL,
            )
        hostname = _normalize_hostname(parsed.hostname)
        if hostname == "localhost":
            raise PermanentVerificationError(
                "verification URL must not target localhost",
                code="url_localhost_forbidden",
                check=VerificationCheckName.PUBLIC_URL,
            )
        if hostname not in allowed_hosts:
            raise PermanentVerificationError(
                "verification URL host is not allowed for this destination",
                code="url_host_not_allowed",
                check=VerificationCheckName.PUBLIC_URL,
            )
        if port is not None and port != 443:
            raise PermanentVerificationError(
                "verification URL uses a non-standard port",
                code="url_port_not_allowed",
                check=VerificationCheckName.PUBLIC_URL,
            )
        try:
            addresses = self._resolver(hostname, 443)
        except socket.gaierror as exc:
            raise RetryableVerificationError(
                "verification hostname could not be resolved",
                code="dns_resolution_unavailable",
                check=VerificationCheckName.PUBLIC_URL,
            ) from exc
        if not addresses:
            raise RetryableVerificationError(
                "verification hostname did not resolve to an address",
                code="dns_resolution_empty",
                check=VerificationCheckName.PUBLIC_URL,
            )
        for address in addresses:
            try:
                parsed_address = ipaddress.ip_address(address)
            except ValueError as exc:
                raise PermanentVerificationError(
                    "verification hostname resolved to an invalid address",
                    code="dns_address_invalid",
                    check=VerificationCheckName.PUBLIC_URL,
                ) from exc
            if not parsed_address.is_global:
                raise PermanentVerificationError(
                    "verification URL resolves to a non-public network",
                    code="dns_address_not_public",
                    check=VerificationCheckName.PUBLIC_URL,
                )
        return tuple(dict.fromkeys(addresses))

    def _inspect(
        self,
        response: FetchedResponse,
        *,
        final_url: str,
        fragments: tuple[str, ...],
        disclosures: tuple[str, ...],
        expected_links: tuple[str, ...],
        content_rule_hash: str,
        verification_rule_hash: str,
        redirect_count: int,
    ) -> UrlVerificationResult:
        content_type_header = response.headers.get("content-type", "")
        content_type = content_type_header.split(";", 1)[0].strip().casefold()
        html_response = content_type == "text/html"
        status_ok = 200 <= response.status_code < 300

        visible = ""
        page_links: set[str] = set()
        if html_response:
            text = _decode_html(response.body, content_type_header)
            extractor = _TextExtractor()
            extractor.feed(text)
            visible = " ".join(extractor.parts)
            link_base = final_url
            if extractor.base_href:
                link_base = urljoin(final_url, extractor.base_href)
            page_links = {
                normalized
                for link in extractor.links
                if (normalized := _canonicalize_link(link, base_url=link_base)) is not None
            }

        normalized_visible = _normalize_text(visible)
        content_match = html_response and all(value in normalized_visible for value in fragments)
        disclosure_match = not disclosures or (
            html_response and all(value in normalized_visible for value in disclosures)
        )
        link_match = not expected_links or (
            html_response and all(link in page_links for link in expected_links)
        )
        checks = (
            VerificationCheck(VerificationCheckName.INPUT_CONTRACT, True),
            VerificationCheck(VerificationCheckName.PUBLIC_URL, True),
            VerificationCheck(VerificationCheckName.REDIRECT_POLICY, True),
            _check(
                VerificationCheckName.HTTP_2XX,
                status_ok,
                "http_non_2xx",
            ),
            _check(
                VerificationCheckName.HTML_RESPONSE,
                html_response,
                "response_not_html",
            ),
            _check(
                VerificationCheckName.APPROVED_CONTENT,
                content_match,
                "approved_content_missing",
            ),
            _check(
                VerificationCheckName.REQUIRED_DISCLOSURES,
                disclosure_match,
                "required_disclosure_missing",
            ),
            _check(
                VerificationCheckName.EXPECTED_LINKS,
                link_match,
                "expected_link_missing",
            ),
        )
        failures = tuple(
            VerificationFailure(
                code=check.failure_code,
                disposition=VerificationFailureDisposition.PERMANENT,
                check=check.name,
            )
            for check in checks
            if not check.passed and check.failure_code is not None
        )
        body_hash = hashlib.sha256(response.body).hexdigest()
        visible_text_hash = hashlib.sha256(normalized_visible.encode("utf-8")).hexdigest()
        normalized_final_url = _canonicalize_link(final_url) or final_url
        metadata_hash = _stable_hash(
            {
                "verifier_version": VERIFIER_CONTRACT_VERSION,
                "status_code": response.status_code,
                "final_url": normalized_final_url,
                "body_hash": body_hash,
                "visible_text_hash": visible_text_hash,
                "content_rule_hash": content_rule_hash,
                "verification_rule_hash": verification_rule_hash,
                "redirect_count": redirect_count,
                "checks": [check.to_persistence_dict() for check in checks],
                "failures": [failure.to_persistence_dict() for failure in failures],
            }
        )
        accessibility = status_ok and html_response
        return UrlVerificationResult(
            success=accessibility and content_match and disclosure_match and link_match,
            status_code=response.status_code,
            final_url=normalized_final_url,
            checked_at=self._clock(),
            metadata_hash=metadata_hash,
            accessibility=accessibility,
            content_match=content_match,
            disclosure_match=disclosure_match,
            link_match=link_match,
            checks=checks,
            failures=failures,
            body_hash=body_hash,
            visible_text_hash=visible_text_hash,
            content_rule_hash=content_rule_hash,
            verification_rule_hash=verification_rule_hash,
            redirect_count=redirect_count,
        )


def _check(
    name: VerificationCheckName,
    passed: bool,
    failure_code: str,
) -> VerificationCheck:
    return VerificationCheck(name, passed, None if passed else failure_code)


def _resolve_addresses(hostname: str, port: int) -> tuple[str, ...]:
    records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return tuple(str(record[4][0]) for record in records)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _contract_values(
    values: tuple[str, ...],
    *,
    field: str,
    required: bool,
) -> tuple[str, ...]:
    if values is None or isinstance(values, (str, bytes)):
        raise PermanentVerificationError(
            f"{field} must be an explicit array",
            code=f"{field}_not_array",
            check=VerificationCheckName.INPUT_CONTRACT,
        )
    normalized_values: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise PermanentVerificationError(
                f"{field} entries must be non-empty strings",
                code=f"{field}_entry_invalid",
                check=VerificationCheckName.INPUT_CONTRACT,
            )
        normalized_values.append(value.strip())
    if required and not normalized_values:
        raise PermanentVerificationError(
            f"{field} must not be empty",
            code=f"{field}_empty",
            check=VerificationCheckName.INPUT_CONTRACT,
        )
    return tuple(dict.fromkeys(normalized_values))


def _normalized_contract_values(
    values: tuple[str, ...],
    *,
    field: str,
    required: bool,
) -> tuple[str, ...]:
    contract_values = _contract_values(values, field=field, required=required)
    return tuple(dict.fromkeys(_normalize_text(value) for value in contract_values))


def _normalized_allowed_hosts(values: tuple[str, ...]) -> tuple[str, ...]:
    raw_hosts = _contract_values(values, field="allowed_hosts", required=True)
    normalized: list[str] = []
    for value in raw_hosts:
        if "://" in value or "/" in value or "@" in value:
            raise PermanentVerificationError(
                "allowed_hosts entries must be hostnames without a scheme or path",
                code="allowed_hosts_entry_invalid",
                check=VerificationCheckName.INPUT_CONTRACT,
            )
        normalized.append(_normalize_hostname(value))
    return tuple(dict.fromkeys(normalized))


def _normalize_hostname(value: str) -> str:
    normalized = value.strip().rstrip(".").casefold()
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise PermanentVerificationError(
            "verification hostname is invalid",
            code="url_hostname_invalid",
            check=VerificationCheckName.PUBLIC_URL,
        ) from exc


def _validated_expected_link(value: str) -> str:
    normalized = _canonicalize_link(value)
    if normalized is None:
        raise PermanentVerificationError(
            "expected_links entries must be absolute HTTP or HTTPS URLs",
            code="expected_links_entry_invalid",
            check=VerificationCheckName.INPUT_CONTRACT,
        )
    return normalized


def _canonicalize_link(value: str, *, base_url: str | None = None) -> str | None:
    if _contains_control_character(value):
        return None
    resolved = urljoin(base_url, value) if base_url is not None else value
    try:
        parsed = urlsplit(resolved)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    try:
        hostname = _normalize_hostname(parsed.hostname)
    except PermanentVerificationError:
        return None
    host_for_netloc = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 80 if scheme == "http" else 443
    netloc = host_for_netloc
    if port is not None and port != default_port:
        netloc = f"{host_for_netloc}:{port}"
    path = _normalize_url_path(parsed.path)
    query = _normalize_percent_encoding(parsed.query)
    return urlunsplit((scheme, netloc, path, query, ""))


def _normalize_url_path(value: str) -> str:
    normalized = _normalize_percent_encoding(value or "/")
    normalized = posixpath.normpath(normalized)
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return "/" if normalized in {"/.", "."} else normalized


_PERCENT_ESCAPE = re.compile(r"%([0-9a-fA-F]{2})")
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def _normalize_percent_encoding(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        character = chr(int(match.group(1), 16))
        return character if character in _UNRESERVED else f"%{match.group(1).upper()}"

    return _PERCENT_ESCAPE.sub(replace, value)


def _decode_html(body: bytes, content_type_header: str) -> str:
    charset = "utf-8"
    match = re.search(
        r"charset\s*=\s*['\"]?([^;'\"\s]+)",
        content_type_header,
        re.IGNORECASE,
    )
    if match:
        charset = match.group(1)
    try:
        return body.decode(charset, errors="replace")
    except LookupError as exc:
        raise PermanentVerificationError(
            "verification response declares an unsupported charset",
            code="response_charset_unsupported",
            check=VerificationCheckName.HTML_RESPONSE,
        ) from exc


def _normalize_text(value: str) -> str:
    compatible = unicodedata.normalize("NFKC", unescape(value))
    return re.sub(r"\s+", " ", compatible).strip().casefold()


def _without_fragment(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _contains_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _stable_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
