"""DNS-pinned HTTPS transport used by publication URL verification."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import ipaddress
import socket
import ssl
from typing import Mapping, Protocol
from urllib.parse import quote, urlsplit

from geo_core.placements.url_verification_contracts import (
    PermanentVerificationError,
    RetryableVerificationError,
    VerificationCheckName,
)


_IPV4_COMPATIBLE_NETWORK = ipaddress.IPv6Network("::/96")
_NAT64_WELL_KNOWN_NETWORK = ipaddress.IPv6Network("64:ff9b::/96")
_NAT64_LOCAL_USE_NETWORK = ipaddress.IPv6Network("64:ff9b:1::/48")
_PATH_SAFE = "/:@!$&'()*+,;=-._~%"
_QUERY_SAFE = "/?:@!$&'()*+,;=-._~%"


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


def fetch_from_addresses(
    fetcher: HttpsFetcher,
    url: str,
    *,
    addresses: tuple[str, ...],
    timeout_seconds: float,
    maximum_bytes: int,
) -> FetchedResponse:
    """Try every prevalidated address, falling back only after transport failures."""
    last_network_error: OSError | TimeoutError | http.client.HTTPException | None = None
    for address in addresses:
        try:
            return fetcher.fetch(
                url,
                pinned_ip=address,
                timeout_seconds=timeout_seconds,
                maximum_bytes=maximum_bytes,
            )
        except ssl.SSLCertVerificationError:
            raise
        except (PermanentVerificationError, RetryableVerificationError):
            raise
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            last_network_error = exc
    if last_network_error is not None:
        raise last_network_error
    raise ValueError("at least one prevalidated address is required")


def resolve_addresses(hostname: str, port: int) -> tuple[str, ...]:
    records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return tuple(str(record[4][0]) for record in records)


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
            if (
                peer_ip != ipaddress.ip_address(self._pinned_ip)
                or not is_public_network_address(peer_ip)
            ):
                raise PermanentVerificationError(
                    "verification connection peer does not match the pinned public address",
                    code="pinned_peer_mismatch",
                    check=VerificationCheckName.PUBLIC_URL,
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
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise PermanentVerificationError(
                "verification URL is invalid",
                code="url_invalid",
                check=VerificationCheckName.PUBLIC_URL,
            ) from exc
        if parsed.hostname is None:
            raise PermanentVerificationError(
                "verification URL has no hostname",
                code="url_hostname_missing",
                check=VerificationCheckName.PUBLIC_URL,
            )
        hostname = _ascii_hostname(parsed.hostname)
        try:
            target = quote(parsed.path or "/", safe=_PATH_SAFE, encoding="utf-8", errors="strict")
            if parsed.query:
                query = quote(parsed.query, safe=_QUERY_SAFE, encoding="utf-8", errors="strict")
                target = f"{target}?{query}"
        except UnicodeError as exc:
            raise PermanentVerificationError(
                "verification URL contains invalid Unicode",
                code="url_invalid_unicode",
                check=VerificationCheckName.PUBLIC_URL,
            ) from exc
        host_header = f"[{hostname}]" if ":" in hostname else hostname
        connection = _PinnedHTTPSConnection(hostname, pinned_ip, timeout=timeout_seconds)
        try:
            connection.request(
                "GET",
                target,
                headers={
                    "Host": host_header,
                    "User-Agent": "GEO-Verification/2.0",
                    "Accept": "text/html",
                    "Accept-Encoding": "identity",
                },
            )
            response = connection.getresponse()
            body = response.read(maximum_bytes + 1)
            if len(body) > maximum_bytes:
                raise PermanentVerificationError(
                    "verification response exceeds the size limit",
                    code="response_too_large",
                    check=VerificationCheckName.HTML_RESPONSE,
                )
            return FetchedResponse(
                int(response.status),
                {key.casefold(): value for key, value in response.getheaders()},
                body,
            )
        finally:
            connection.close()


def is_public_network_address(
    address: str | ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Reject public-looking transition addresses that embed a non-public IPv4 target."""
    try:
        value = ipaddress.ip_address(address) if isinstance(address, str) else address
    except ValueError:
        return False
    if not value.is_global or value.is_multicast:
        return False
    if isinstance(value, ipaddress.IPv4Address):
        return True
    if value in _NAT64_LOCAL_USE_NETWORK:
        return False
    embedded: list[ipaddress.IPv4Address] = []
    if value.ipv4_mapped is not None:
        embedded.append(value.ipv4_mapped)
    if value.sixtofour is not None:
        embedded.append(value.sixtofour)
    if value.teredo is not None:
        embedded.extend(value.teredo)
    if value in _IPV4_COMPATIBLE_NETWORK or value in _NAT64_WELL_KNOWN_NETWORK:
        embedded.append(ipaddress.IPv4Address(int(value) & 0xFFFFFFFF))
    return all(item.is_global and not item.is_multicast for item in embedded)


def _ascii_hostname(value: str) -> str:
    normalized = value.rstrip(".").casefold()
    try:
        return ipaddress.ip_address(normalized).compressed
    except ValueError:
        pass
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise PermanentVerificationError(
            "verification hostname is invalid",
            code="url_hostname_invalid",
            check=VerificationCheckName.PUBLIC_URL,
        ) from exc
