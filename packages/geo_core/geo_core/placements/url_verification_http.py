"""DNS-pinned HTTPS transport used by publication URL verification."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import ipaddress
import socket
import ssl
from typing import Mapping, Protocol
from urllib.parse import urlsplit

from geo_core.placements.url_verification_contracts import (
    PermanentVerificationError,
    VerificationCheckName,
)


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
        parsed = urlsplit(url)
        if parsed.hostname is None:
            raise PermanentVerificationError(
                "verification URL has no hostname",
                code="url_hostname_missing",
                check=VerificationCheckName.PUBLIC_URL,
            )
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        connection = _PinnedHTTPSConnection(parsed.hostname, pinned_ip, timeout=timeout_seconds)
        try:
            connection.request(
                "GET",
                target,
                headers={
                    "Host": parsed.hostname,
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
