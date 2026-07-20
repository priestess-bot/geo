import json
import socket
import ssl
from typing import cast

import pytest

from geo_core.placements import url_verification_http
from geo_core.placements.url_verifier import (
    FetchedResponse,
    PermanentVerificationError,
    PublicUrlVerifier,
    RetryableVerificationError,
    VERIFIER_CONTRACT_VERSION,
    VerificationCheckName,
    VerificationFailureDisposition,
    _PinnedHTTPSConnection,
)


PUBLIC_IP = "93.184.216.34"


class FakeFetcher:
    def __init__(self, *responses: FetchedResponse) -> None:
        self.responses = list(responses)
        self.pinned_ips: list[str] = []
        self.urls: list[str] = []

    def fetch(self, url, *, pinned_ip, timeout_seconds, maximum_bytes):
        del timeout_seconds, maximum_bytes
        self.pinned_ips.append(pinned_ip)
        self.urls.append(url)
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


def test_f011_unit_01_empty_required_disclosures_is_an_explicit_passing_check() -> None:
    body = b"<html><body>Robot vacuum review.</body></html>"
    result = PublicUrlVerifier(
        resolver=_public_resolver,
        fetcher=FakeFetcher(_response(body)),
    ).verify(
        "https://public.example/post",
        expected_text_fragments=("Robot vacuum review",),
        required_disclosures=(),
        expected_links=(),
        allowed_hosts=("public.example",),
    )

    checks = {check.name: check for check in result.checks}
    assert result.success is True
    assert checks[VerificationCheckName.REQUIRED_DISCLOSURES].passed is True
    assert checks[VerificationCheckName.REQUIRED_DISCLOSURES].failure_code is None
    assert result.verifier_version == VERIFIER_CONTRACT_VERSION


def test_f011_unit_01_missing_required_disclosure_has_stable_permanent_failure() -> None:
    body = b"<html><body>Robot vacuum review.</body></html>"
    result = PublicUrlVerifier(
        resolver=_public_resolver,
        fetcher=FakeFetcher(_response(body)),
    ).verify(
        "https://public.example/post",
        expected_text_fragments=("Robot vacuum review",),
        required_disclosures=("Sponsored by Example Brand",),
        expected_links=(),
        allowed_hosts=("public.example",),
    )

    assert result.success is False
    assert result.disclosure_match is False
    assert [failure.code for failure in result.failures] == ["required_disclosure_missing"]
    assert result.failures[0].disposition is VerificationFailureDisposition.PERMANENT


def test_f011_contract_01_required_disclosures_must_be_an_explicit_array() -> None:
    fetcher = FakeFetcher()
    verifier = PublicUrlVerifier(resolver=_public_resolver, fetcher=fetcher)

    with pytest.raises(PermanentVerificationError) as raised:
        verifier.verify(
            "https://public.example/post",
            expected_text_fragments=("Robot vacuum review",),
            required_disclosures=cast(tuple[str, ...], None),
            expected_links=(),
            allowed_hosts=("public.example",),
        )

    assert raised.value.failure.code == "required_disclosures_not_array"
    assert raised.value.failure.check is VerificationCheckName.INPUT_CONTRACT
    assert raised.value.failure.disposition is VerificationFailureDisposition.PERMANENT
    assert fetcher.urls == []


def test_f011_unit_01_link_comparison_normalizes_url_and_ignores_fragment() -> None:
    body = (
        b'<html><body>Robot vacuum review.<a href="HTTPS://Brand.Example:443/'
        b'a/../product/%7eitem/?q=%61#page-fragment">Product</a></body></html>'
    )
    result = PublicUrlVerifier(
        resolver=_public_resolver,
        fetcher=FakeFetcher(_response(body)),
    ).verify(
        "https://public.example/post",
        expected_text_fragments=("Robot vacuum review",),
        required_disclosures=(),
        expected_links=("https://brand.example/product/~item?q=a#expected-fragment",),
        allowed_hosts=("public.example",),
    )

    assert result.success is True
    assert result.link_match is True


def test_f011_unit_01_query_is_part_of_the_normalized_link_contract() -> None:
    body = (
        b'<html><body>Robot vacuum review.<a href="https://brand.example/product?a=1">'
        b"Product</a></body></html>"
    )
    result = PublicUrlVerifier(
        resolver=_public_resolver,
        fetcher=FakeFetcher(_response(body)),
    ).verify(
        "https://public.example/post",
        expected_text_fragments=("Robot vacuum review",),
        required_disclosures=(),
        expected_links=("https://brand.example/product?a=2",),
        allowed_hosts=("public.example",),
    )

    assert result.success is False
    assert result.link_match is False
    assert "expected_link_missing" in {failure.code for failure in result.failures}


def test_f011_unit_01_redirects_revalidate_dns_and_allowlist_on_every_hop() -> None:
    fetcher = FakeFetcher(
        _response(b"", status=302, location="/moved"),
        _response(b"", status=308, location="https://cdn.example/final#section"),
        _response(b"<html><body>Approved copy</body></html>"),
    )
    resolutions: list[tuple[str, int]] = []

    def resolver(hostname: str, port: int) -> tuple[str, ...]:
        resolutions.append((hostname, port))
        return (PUBLIC_IP,)

    result = PublicUrlVerifier(resolver=resolver, fetcher=fetcher).verify(
        "https://public.example/start",
        expected_text_fragments=("Approved copy",),
        required_disclosures=(),
        expected_links=(),
        allowed_hosts=("PUBLIC.EXAMPLE", "cdn.example"),
    )

    assert result.success is True
    assert result.redirect_count == 2
    assert result.final_url == "https://cdn.example/final"
    assert resolutions == [
        ("public.example", 443),
        ("public.example", 443),
        ("cdn.example", 443),
    ]
    assert fetcher.urls == [
        "https://public.example/start",
        "https://public.example/moved",
        "https://cdn.example/final",
    ]


@pytest.mark.parametrize("status", (304, 400, 404))
def test_f011_unit_01_non_2xx_response_has_stable_failure(status: int) -> None:
    result = PublicUrlVerifier(
        resolver=_public_resolver,
        fetcher=FakeFetcher(_response(b"<html><body>Approved copy</body></html>", status=status)),
    ).verify(
        "https://public.example/post",
        expected_text_fragments=("Approved copy",),
        required_disclosures=(),
        expected_links=(),
        allowed_hosts=("public.example",),
    )

    assert result.success is False
    assert result.accessibility is False
    assert "http_non_2xx" in {failure.code for failure in result.failures}


def test_f011_unit_01_final_response_must_be_html() -> None:
    response = FetchedResponse(
        200,
        {"content-type": "text/plain; charset=utf-8"},
        b"Approved copy",
    )
    result = PublicUrlVerifier(
        resolver=_public_resolver,
        fetcher=FakeFetcher(response),
    ).verify(
        "https://public.example/post",
        expected_text_fragments=("Approved copy",),
        required_disclosures=(),
        expected_links=(),
        allowed_hosts=("public.example",),
    )

    assert result.success is False
    assert result.accessibility is False
    assert "response_not_html" in {failure.code for failure in result.failures}
    assert result.disclosure_match is True
    assert result.link_match is True
    assert "required_disclosure_missing" not in {failure.code for failure in result.failures}
    assert "expected_link_missing" not in {failure.code for failure in result.failures}


def test_f011_unit_01_content_must_be_visible_and_evidence_retains_only_hashes() -> None:
    secret_body = (
        b"<html><head><script>Approved copy SECRET-WHOLE-PAGE</script></head>"
        b"<body>Different visible copy</body></html>"
    )
    result = PublicUrlVerifier(
        resolver=_public_resolver,
        fetcher=FakeFetcher(_response(secret_body)),
    ).verify(
        "https://public.example/post",
        expected_text_fragments=("Approved copy",),
        required_disclosures=(),
        expected_links=(),
        allowed_hosts=("public.example",),
    )
    persisted = json.dumps(result.to_persistence_dict(), sort_keys=True)

    assert result.success is False
    assert result.content_match is False
    assert len(result.body_hash) == 64
    assert len(result.visible_text_hash) == 64
    assert len(result.content_rule_hash) == 64
    assert len(result.verification_rule_hash) == 64
    assert "SECRET-WHOLE-PAGE" not in persisted
    assert "Different visible copy" not in persisted


def test_f011_unit_01_retryable_exception_exposes_non_sensitive_failure_dto() -> None:
    verifier = PublicUrlVerifier(
        resolver=_public_resolver,
        fetcher=FakeFetcher(_response(b"", status=503)),
    )

    with pytest.raises(RetryableVerificationError) as raised:
        verifier.verify(
            "https://public.example/post",
            expected_text_fragments=("Approved copy",),
            required_disclosures=(),
            expected_links=(),
            allowed_hosts=("public.example",),
        )

    assert raised.value.failure.code == "http_upstream_unavailable"
    assert raised.value.failure.retryable is True
    assert raised.value.to_persistence_dict() == {
        "verifier_version": VERIFIER_CONTRACT_VERSION,
        "failure": {
            "code": "http_upstream_unavailable",
            "disposition": "retryable",
            "check": "http_2xx",
            "retryable": True,
        },
    }


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


@pytest.mark.parametrize(
    "address",
    (
        "64:ff9b::a9fe:a9fe",
        "::ffff:169.254.169.254",
        "::a9fe:a9fe",
        "2002:a9fe:a9fe::",
        "2001:0000:4136:e378:8000:63bf:3fff:fdd2",
    ),
)
def test_embedded_non_public_ipv4_addresses_are_rejected(address: str) -> None:
    with pytest.raises(PermanentVerificationError, match="non-public"):
        PublicUrlVerifier(
            resolver=lambda hostname, port: (address,),
            fetcher=FakeFetcher(),
        ).verify(
            "https://public.example/post",
            expected_text_fragments=("expected",),
            required_disclosures=(),
            expected_links=(),
            allowed_hosts=("public.example",),
        )


def test_public_nat64_address_remains_usable() -> None:
    address = "64:ff9b::808:808"
    fetcher = FakeFetcher(_response(b"<html><body>expected</body></html>"))

    result = PublicUrlVerifier(
        resolver=lambda hostname, port: (address,),
        fetcher=fetcher,
    ).verify(
        "https://public.example/post",
        expected_text_fragments=("expected",),
        required_disclosures=(),
        expected_links=(),
        allowed_hosts=("public.example",),
    )

    assert result.success is True
    assert fetcher.pinned_ips == [address]


def test_network_failure_falls_back_to_the_next_validated_address() -> None:
    second = "93.184.216.35"

    class FallbackFetcher(FakeFetcher):
        def fetch(self, url, *, pinned_ip, timeout_seconds, maximum_bytes):
            self.pinned_ips.append(pinned_ip)
            self.urls.append(url)
            if pinned_ip == PUBLIC_IP:
                raise OSError("IPv6 route unavailable")
            return _response(b"<html><body>expected</body></html>")

    fetcher = FallbackFetcher()
    result = PublicUrlVerifier(
        resolver=lambda hostname, port: (PUBLIC_IP, second),
        fetcher=fetcher,
    ).verify(
        "https://public.example/post",
        expected_text_fragments=("expected",),
        required_disclosures=(),
        expected_links=(),
        allowed_hosts=("public.example",),
    )

    assert result.success is True
    assert fetcher.pinned_ips == [PUBLIC_IP, second]


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
    connection._ssl_context = cast(ssl.SSLContext, Context())
    with pytest.raises(PermanentVerificationError, match="pinned"):
        connection.connect()


def test_pinned_peer_rejects_public_looking_nat64_metadata_address(monkeypatch) -> None:
    pinned_ip = "64:ff9b::a9fe:a9fe"

    class RawSocket:
        def close(self) -> None:
            pass

    class SecuredSocket:
        def getpeername(self):
            return (pinned_ip, 443)

    class Context:
        def wrap_socket(self, raw, *, server_hostname):
            del raw, server_hostname
            return SecuredSocket()

    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: RawSocket())
    connection = _PinnedHTTPSConnection("public.example", pinned_ip, timeout=1)
    connection._ssl_context = cast(ssl.SSLContext, Context())
    with pytest.raises(PermanentVerificationError, match="pinned public"):
        connection.connect()


def test_pinned_fetcher_encodes_idn_hostname_and_unicode_request_target(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        status = 200

        def read(self, maximum_bytes: int) -> bytes:
            del maximum_bytes
            return b"<html></html>"

        def getheaders(self):
            return (("Content-Type", "text/html"),)

    class Connection:
        def __init__(self, hostname: str, pinned_ip: str, *, timeout: float) -> None:
            captured.update(hostname=hostname, pinned_ip=pinned_ip, timeout=timeout)

        def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
            captured.update(method=method, target=target, headers=headers)

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(url_verification_http, "_PinnedHTTPSConnection", Connection)

    response = url_verification_http.PinnedHttpsFetcher().fetch(
        "https://b\N{LATIN SMALL LETTER U WITH DIAERESIS}cher.example/caf\N{LATIN SMALL LETTER E WITH ACUTE}/\N{CJK UNIFIED IDEOGRAPH-8DEF}\N{CJK UNIFIED IDEOGRAPH-5F84}?q=na\N{LATIN SMALL LETTER I WITH DIAERESIS}ve \N{CJK UNIFIED IDEOGRAPH-4F60}\N{CJK UNIFIED IDEOGRAPH-597D}",
        pinned_ip=PUBLIC_IP,
        timeout_seconds=3,
        maximum_bytes=1000,
    )

    assert response.status_code == 200
    assert captured["hostname"] == "xn--bcher-kva.example"
    assert captured["target"] == (
        "/caf%C3%A9/%E8%B7%AF%E5%BE%84?q=na%C3%AFve%20%E4%BD%A0%E5%A5%BD"
    )
    assert captured["headers"] == {
        "Host": "xn--bcher-kva.example",
        "User-Agent": "GEO-Verification/2.0",
        "Accept": "text/html",
        "Accept-Encoding": "identity",
    }
    assert captured["closed"] is True
