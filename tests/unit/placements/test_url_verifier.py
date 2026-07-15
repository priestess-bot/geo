import socket

import pytest

from geo_core.placements.url_verifier import (
    FetchedResponse,
    PermanentVerificationError,
    PublicUrlVerifier,
    RetryableVerificationError,
    _PinnedHTTPSConnection,
)


PUBLIC_IP = "93.184.216.34"


class FakeFetcher:
    def __init__(self, *responses: FetchedResponse) -> None:
        self.responses = list(responses)
        self.pinned_ips: list[str] = []

    def fetch(self, url, *, pinned_ip, timeout_seconds, maximum_bytes):
        del url, timeout_seconds, maximum_bytes
        self.pinned_ips.append(pinned_ip)
        return self.responses.pop(0)


def _public_resolver(hostname: str, port: int) -> tuple[str, ...]:
    del hostname, port
    return (PUBLIC_IP,)


def _response(body: bytes, *, status: int = 200, **headers: str) -> FetchedResponse:
    return FetchedResponse(
        status,
        {"content-type": "text/html; charset=utf-8", **headers},
        body,
    )


def test_http_200_without_expected_content_is_not_verified_or_scheduled() -> None:
    fetcher = FakeFetcher(_response(b"<html><body>Unrelated page</body></html>"))
    result = PublicUrlVerifier(resolver=_public_resolver, fetcher=fetcher).verify(
        "https://public.example/post",
        expected_text_fragments=("Robot vacuum review",),
        required_disclosures=("posted on behalf of the brand",),
        expected_links=("https://brand.example/product",),
        allowed_hosts=("public.example",),
    )
    assert fetcher.pinned_ips == [PUBLIC_IP]
    assert result.accessibility is True
    assert result.content_match is False
    assert result.disclosure_match is False
    assert result.link_match is False
    assert result.success is False


def test_matching_content_disclosure_and_link_is_verified() -> None:
    body = (
        b"<html><body>Robot vacuum review. Posted on behalf of the brand."
        b'<a href="https://brand.example/product">Product</a></body></html>'
    )
    verifier = PublicUrlVerifier(resolver=_public_resolver, fetcher=FakeFetcher(_response(body)))
    result = verifier.verify(
        "https://public.example/post",
        expected_text_fragments=("Robot vacuum review",),
        required_disclosures=("posted on behalf of the brand",),
        expected_links=("https://brand.example/product",),
        allowed_hosts=("public.example",),
    )
    assert result.success is True
    assert len(result.metadata_hash) == 64


def test_redirect_to_private_network_is_rejected_before_second_request() -> None:
    fetcher = FakeFetcher(_response(b"", status=302, location="https://127.0.0.1/internal"))

    def resolver(hostname: str, port: int) -> tuple[str, ...]:
        del port
        return ("127.0.0.1",) if hostname == "127.0.0.1" else (PUBLIC_IP,)

    with pytest.raises(PermanentVerificationError, match="non-public"):
        PublicUrlVerifier(resolver=resolver, fetcher=fetcher).verify(
            "https://public.example",
            expected_text_fragments=("expected",),
            required_disclosures=(),
            expected_links=(),
            allowed_hosts=("public.example", "127.0.0.1"),
        )
    assert fetcher.pinned_ips == [PUBLIC_IP]


def test_redirect_to_a_different_public_host_is_rejected() -> None:
    fetcher = FakeFetcher(_response(b"", status=302, location="https://different.example/post"))
    with pytest.raises(PermanentVerificationError, match="not allowed"):
        PublicUrlVerifier(resolver=_public_resolver, fetcher=fetcher).verify(
            "https://public.example/post",
            expected_text_fragments=("expected",),
            required_disclosures=(),
            expected_links=(),
            allowed_hosts=("public.example",),
        )
    assert fetcher.pinned_ips == [PUBLIC_IP]


@pytest.mark.parametrize(
    "url",
    (
        "http://public.example/",
        "https://user:password@public.example/",
        "https://public.example:8443/",
        "file:///etc/passwd",
    ),
)
def test_unsafe_url_shapes_are_permanent_failures(url: str) -> None:
    with pytest.raises(PermanentVerificationError):
        PublicUrlVerifier(resolver=_public_resolver, fetcher=FakeFetcher()).verify(
            url,
            expected_text_fragments=("expected",),
            required_disclosures=(),
            expected_links=(),
            allowed_hosts=("public.example",),
        )


@pytest.mark.parametrize("status", (429, 500, 503))
def test_only_throttling_and_server_statuses_are_retryable(status: int) -> None:
    verifier = PublicUrlVerifier(
        resolver=_public_resolver, fetcher=FakeFetcher(_response(b"", status=status))
    )
    with pytest.raises(RetryableVerificationError):
        verifier.verify(
            "https://public.example/post",
            expected_text_fragments=("expected",),
            required_disclosures=(),
            expected_links=(),
            allowed_hosts=("public.example",),
        )


def test_dns_rebinding_peer_mismatch_is_rejected(monkeypatch) -> None:
    class RawSocket:
        def close(self) -> None:
            pass

    class SecuredSocket:
        def getpeername(self):
            return ("93.184.216.35", 443)

    class Context:
        def wrap_socket(self, raw, *, server_hostname):
            del raw
            assert server_hostname == "public.example"
            return SecuredSocket()

    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: RawSocket())
    connection = _PinnedHTTPSConnection("public.example", PUBLIC_IP, timeout=1)
    connection._ssl_context = Context()
    with pytest.raises(PermanentVerificationError, match="pinned"):
        connection.connect()
